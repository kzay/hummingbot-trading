#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_token(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "..." + token[-4:]


def _classify_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "403" in low or "forbidden" in low:
        return "403_forbidden"
    if "401" in low or "unauthorized" in low:
        return "unauthorized"
    if "chat not found" in low:
        return "invalid_chat_id"
    if "name or service not known" in low or "nodename nor servname" in low:
        return "network_error"
    if "timed out" in low or "timeout" in low:
        return "timeout"
    return "unknown_error"


def _validate_format(token: str, chat_id: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not token:
        reasons.append("missing_token")
    if not chat_id:
        reasons.append("missing_chat_id")
    # Typical bot token format: digits:tokenbody
    if token and not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", token):
        reasons.append("token_format_invalid")
    # Chat ID can be numeric or @channelusername
    if chat_id and not re.match(r"^(-?\d+|@[A-Za-z0-9_]{5,})$", chat_id):
        reasons.append("chat_id_format_invalid")
    return len(reasons) == 0, reasons


def _probe_send_message(token: str, chat_id: str, timeout_sec: float = 8.0) -> tuple[bool, str]:
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": f"Alerting validation probe {_utc_now()}",
        }
    ).encode("utf-8")
    req = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            return resp.status == 200, ("ok" if resp.status == 200 else f"http_{resp.status}")
    except HTTPError as e:
        return False, _classify_error(e)
    except URLError as e:
        return False, _classify_error(e)
    except Exception as e:
        return False, _classify_error(e)


def _read_env_file(root: Path) -> dict[str, str]:
    env_path = root / "env" / ".env"
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            row = raw.strip()
            if not row or row.startswith("#") or "=" not in row:
                continue
            key, value = row.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Telegram alerting configuration and delivery.")
    parser.add_argument("--token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""), help="Telegram bot token.")
    parser.add_argument("--chat-id", default=os.getenv("TELEGRAM_CHAT_ID", ""), help="Telegram chat ID.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on any validation/probe failure.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    out_path = root / "reports" / "ops" / "telegram_validation_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env_file = _read_env_file(root)
    token = args.token or env_file.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = args.chat_id or env_file.get("TELEGRAM_CHAT_ID", "")

    fmt_ok, format_reasons = _validate_format(token, chat_id)
    probe_ok = False
    probe_reason = "skipped"
    if fmt_ok:
        probe_ok, probe_reason = _probe_send_message(token, chat_id)

    status = "ok" if fmt_ok and probe_ok else "error"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "token_masked": _mask_token(token),
        "chat_id": chat_id,
        "format_ok": fmt_ok,
        "format_reasons": format_reasons,
        "probe_ok": probe_ok,
        "diagnosis": probe_reason if not (fmt_ok and probe_ok) else "ok",
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[telegram-validate] status={status} diagnosis={payload['diagnosis']}")
    print(f"[telegram-validate] evidence={out_path}")
    if args.strict and status != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
