"""Alert webhook sink.

Receives Alertmanager webhook calls, logs them to disk, and forwards
critical/warning alerts directly to Telegram as a belt-and-suspenders
delivery path (in case alertmanager Telegram config fails).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_PATH = Path("/tmp/alert_webhook_events.log")

_TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

# Severities that get a Telegram push from the sink (alertmanager also sends
# Telegram for critical — this is the fallback for any routing gaps).
_PUSH_SEVERITIES = {"critical", "warning"}
_PUSH_ALERT_NAMES = {
    "DailyStateStale", "BotHardStopActive", "BotSoftPauseTooLong",
    "ContainerDown", "ContainerRestartLoop", "OrderBookStale",
    "WsReconnectSpike", "MarginRatioLow", "PositionDriftHigh",
}


def _telegram_push(text: str) -> None:
    if not _TELEGRAM_TOKEN or not _TELEGRAM_CHAT:
        return
    try:
        payload = json.dumps({
            "chat_id": _TELEGRAM_CHAT,
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Never let Telegram errors break the sink


def _format_telegram(alert: dict) -> str | None:
    labels = alert.get("labels", {})
    severity = labels.get("severity", "")
    name = labels.get("alertname", "")
    status = alert.get("status", "firing")
    if status == "resolved":
        return None  # alertmanager handles resolved
    if severity not in _PUSH_SEVERITIES and name not in _PUSH_ALERT_NAMES:
        return None
    icon = "🔴" if severity == "critical" else "⚠️"
    annotations = alert.get("annotations", {})
    summary = annotations.get("summary", name)
    description = annotations.get("description", "")
    return f"{icon} <b>{name}</b> [{severity.upper()}]\n{summary}\n<i>{description[:200]}</i>"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": self.path,
            "body": body.decode("utf-8", errors="replace"),
        }
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Forward critical/key alerts to Telegram
        try:
            payload = json.loads(body)
            for alert in payload.get("alerts", []):
                msg = _format_telegram(alert)
                if msg:
                    _telegram_push(msg)
        except Exception:
            pass

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/events":
            payload = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 19093), Handler)
    server.serve_forever()
