"""Alerting health check for promotion gates.

Probes the available alerting endpoints in priority order and writes fresh
evidence to ``reports/reconciliation/last_webhook_sent.json``.

Priority:
  1. Telegram API        (sends test message if TELEGRAM_BOT_TOKEN set)
  2. alert-webhook-sink  (http://127.0.0.1:19093/healthz)
  3. Alertmanager        (http://127.0.0.1:9093/-/healthy)
  4. SLACK_WEBHOOK_URL   (sends a test payload, checks HTTP 200)
  5. local_dev fallback  (no endpoints available – logs a warning, succeeds in
                          non-strict mode so the gate is not blocked locally)

Exit codes:
  0 – healthy alerting path validated (or local_dev fallback allowed)
  2 – fail-closed condition:
      - Telegram is configured but probe fails, OR
      - strict mode and no probe passed

Usage::

    python scripts/release/check_alerting_health.py
    python scripts/release/check_alerting_health.py --strict
    python scripts/release/check_alerting_health.py --sink-url http://localhost:19093/healthz
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _probe_http_get(url: str, timeout: float = 4.0) -> tuple[bool, str]:
    """Return (success, reason)."""
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            return status < 300, f"HTTP {status}"
    except URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def _probe_slack_webhook(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """POST a silent test payload to a Slack webhook URL."""
    payload = json.dumps({
        "text": f":white_check_mark: alerting health check (probe) — {_utc_now()}"
    }).encode("utf-8")
    try:
        req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            return status < 300, f"HTTP {status}"
    except URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def _probe_telegram(token: str, chat_id: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Send a test message via Telegram API."""
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
    try:
        payload = json.dumps({
            "chat_id": chat_id,
            "text": f"✅ Alerting health check (probe) — {_utc_now()}",
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            if status == 200:
                return True, "Telegram API OK"
            return False, f"Telegram HTTP {status}"
    except URLError as e:
        err = str(e.reason) if hasattr(e, "reason") else str(e)
        if "403" in err or "Forbidden" in err:
            return False, "Telegram 403 Forbidden (token revoked?)"
        return False, err
    except Exception as e:
        return False, str(e)


def run_check(
    sink_url: str,
    alertmanager_url: str,
    slack_url: str,
    telegram_token: str,
    telegram_chat_id: str,
    strict: bool,
    *,
    root: Path | None = None,
) -> int:
    root = (
        root
        if root is not None
        else (Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2])
    )
    out_path = root / "reports" / "reconciliation" / "last_webhook_sent.json"

    probes: list[dict] = []
    ok = False
    telegram_configured = bool(str(telegram_token or "").strip() or str(telegram_chat_id or "").strip())
    telegram_probe_ok = False
    telegram_probe_reason = "not_configured"

    # --- 1. Telegram API (primary for watchdog/alertmanager) -------------------
    if telegram_configured:
        ok_tg, reason_tg = _probe_telegram(telegram_token, telegram_chat_id)
        telegram_probe_ok = bool(ok_tg)
        telegram_probe_reason = str(reason_tg)
        probes.append({
            "endpoint": "telegram",
            "url": "https://api.telegram.org/bot***/sendMessage",
            "ok": ok_tg,
            "reason": reason_tg,
        })
        if ok_tg:
            ok = True
            print(f"[alerting-health] Telegram API verified: {reason_tg}")

    # --- 2. alert-webhook-sink -----------------------------------------------
    if not ok:
        ok, reason = _probe_http_get(sink_url)
        probes.append({"endpoint": "alert_webhook_sink", "url": sink_url, "ok": ok, "reason": reason})
        if ok:
            print(f"[alerting-health] alert-webhook-sink reachable: {reason}")

    # --- 3. Alertmanager -------------------------------------------------------
    if not ok:
        ok2, reason2 = _probe_http_get(alertmanager_url)
        probes.append({"endpoint": "alertmanager", "url": alertmanager_url, "ok": ok2, "reason": reason2})
        if ok2:
            ok = True
            print(f"[alerting-health] alertmanager reachable: {reason2}")

    # --- 4. Slack webhook (if URL set) ----------------------------------------
    if not ok and slack_url and slack_url.startswith("https://hooks.slack.com/"):
        ok3, reason3 = _probe_slack_webhook(slack_url)
        probes.append({"endpoint": "slack_webhook", "url": slack_url[:40] + "...", "ok": ok3, "reason": reason3})
        if ok3:
            ok = True
            print(f"[alerting-health] slack webhook verified: {reason3}")

    telegram_required_failure = telegram_configured and (not telegram_probe_ok)

    # --- 5. result / local_dev fallback ----------------------------------------
    if telegram_required_failure:
        mode = "telegram_configured_unhealthy"
        rc = 2
        status = "error"
        print(
            "[alerting-health] ERROR: Telegram configured but probe failed "
            f"(reason={telegram_probe_reason})"
        )
    elif not ok:
        mode = "local_dev_degraded"
        rc = 2 if strict else 0
        status = mode
        print(
            f"[alerting-health] WARNING: no alerting endpoint reachable "
            f"({'FAIL strict' if strict else 'OK local_dev'})"
        )
    else:
        mode = "live"
        rc = 0
        status = "ok"

    evidence = {
        "ts_utc": _utc_now(),
        "mode": mode,
        "telegram_configured": telegram_configured,
        "telegram_probe_ok": telegram_probe_ok,
        "telegram_probe_reason": telegram_probe_reason,
        "telegram_required_failure": telegram_required_failure,
        "probes": probes,
        "status": status,
    }
    _write_json(out_path, evidence)
    print(f"[alerting-health] status={evidence['status']} mode={mode}")
    print(f"[alerting-health] evidence={out_path}")
    return rc


def main() -> None:
    parser = argparse.ArgumentParser(description="Alerting health probe for promotion gates")
    parser.add_argument(
        "--sink-url",
        default=os.getenv("ALERT_SINK_URL", "http://127.0.0.1:19093/healthz"),
        help="Alert webhook sink health URL (default: http://127.0.0.1:19093/healthz)",
    )
    parser.add_argument(
        "--alertmanager-url",
        default=os.getenv("ALERTMANAGER_URL", "http://127.0.0.1:9093/-/healthy"),
        help="Alertmanager health URL (default: http://127.0.0.1:9093/-/healthy)",
    )
    parser.add_argument(
        "--slack-url",
        default=os.getenv("SLACK_WEBHOOK_URL", ""),
        help="Slack webhook URL (optional, from SLACK_WEBHOOK_URL env var)",
    )
    parser.add_argument(
        "--telegram-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        help="Telegram bot token (from TELEGRAM_BOT_TOKEN env var)",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID", ""),
        help="Telegram chat ID (from TELEGRAM_CHAT_ID env var)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (rc=2) if no alerting endpoint is reachable (for production gate enforcement)",
    )
    args = parser.parse_args()
    sys.exit(run_check(
        args.sink_url,
        args.alertmanager_url,
        args.slack_url,
        args.telegram_token,
        args.telegram_chat_id,
        args.strict,
    ))


if __name__ == "__main__":
    main()
