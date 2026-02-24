"""Test Slack webhook alert delivery.

Sends a test alert to the configured Slack webhook URL to verify
that the Alertmanager → Slack pipeline is working.

Usage::

    # Via env var:
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... python scripts/ops/test_slack_webhook.py

    # Via argument:
    python scripts/ops/test_slack_webhook.py --url https://hooks.slack.com/services/...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.utils import utc_now, write_json


def send_test_alert(webhook_url: str) -> dict:
    """Send a test message to Slack and return the result."""
    payload = {
        "text": ":test_tube: *Trading Desk Alert Test*\n"
                f"Timestamp: `{utc_now()}`\n"
                "This is a test alert from `scripts/ops/test_slack_webhook.py`.\n"
                "If you see this, Slack webhook delivery is working.",
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urlopen(req, timeout=10) as resp:
            status_code = resp.status
            body = resp.read().decode("utf-8", errors="replace")
        return {
            "status": "ok" if status_code < 300 else "error",
            "http_status": status_code,
            "response_body": body[:500],
        }
    except Exception as exc:
        return {
            "status": "error",
            "http_status": 0,
            "response_body": str(exc)[:500],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Slack webhook delivery")
    parser.add_argument("--url", default=os.getenv("SLACK_WEBHOOK_URL", ""), help="Slack webhook URL")
    args = parser.parse_args()

    url = args.url.strip()
    if not url:
        print("[slack-test] ERROR: No webhook URL provided. Set SLACK_WEBHOOK_URL env var or use --url")
        sys.exit(1)

    if not url.startswith("https://hooks.slack.com/"):
        print(f"[slack-test] WARNING: URL doesn't look like a Slack webhook: {url[:40]}...")

    result = send_test_alert(url)
    result["ts_utc"] = utc_now()
    result["webhook_url_prefix"] = url[:40] + "..."

    out_dir = _HBOT_ROOT / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "slack_webhook_test.json", result)

    print(f"[slack-test] status={result['status']} http={result['http_status']}")
    print(f"[slack-test] response={result['response_body'][:200]}")
    print(f"[slack-test] evidence=reports/ops/slack_webhook_test.json")

    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
