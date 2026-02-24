"""Alerting health check for promotion gates.

Probes the available alerting endpoints in priority order and writes fresh
evidence to ``reports/reconciliation/last_webhook_sent.json``.

Priority:
  1. alert-webhook-sink  (http://127.0.0.1:19093/healthz)
  2. Alertmanager        (http://127.0.0.1:9093/-/healthy)
  3. SLACK_WEBHOOK_URL   (sends a test payload, checks HTTP 200)
  4. local_dev fallback  (no endpoints available – logs a warning, succeeds in
                          non-strict mode so the gate is not blocked locally)

Exit codes:
  0 – at least one probe passed (or local_dev fallback allowed)
  2 – strict mode and no probe passed

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
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def run_check(
    sink_url: str,
    alertmanager_url: str,
    slack_url: str,
    strict: bool,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    out_path = root / "reports" / "reconciliation" / "last_webhook_sent.json"

    probes: list[dict] = []

    # --- 1. alert-webhook-sink -----------------------------------------------
    ok, reason = _probe_http_get(sink_url)
    probes.append({"endpoint": "alert_webhook_sink", "url": sink_url, "ok": ok, "reason": reason})
    if ok:
        print(f"[alerting-health] alert-webhook-sink reachable: {reason}")

    # --- 2. Alertmanager -------------------------------------------------------
    if not ok:
        ok2, reason2 = _probe_http_get(alertmanager_url)
        probes.append({"endpoint": "alertmanager", "url": alertmanager_url, "ok": ok2, "reason": reason2})
        if ok2:
            ok = True
            print(f"[alerting-health] alertmanager reachable: {reason2}")

    # --- 3. Slack webhook (if URL set) ----------------------------------------
    if not ok and slack_url and slack_url.startswith("https://hooks.slack.com/"):
        ok3, reason3 = _probe_slack_webhook(slack_url)
        probes.append({"endpoint": "slack_webhook", "url": slack_url[:40] + "...", "ok": ok3, "reason": reason3})
        if ok3:
            ok = True
            print(f"[alerting-health] slack webhook verified: {reason3}")

    # --- 4. local_dev fallback ------------------------------------------------
    if not ok:
        mode = "local_dev_degraded"
        rc = 2 if strict else 0
        print(
            f"[alerting-health] WARNING: no alerting endpoint reachable "
            f"({'FAIL strict' if strict else 'OK local_dev'})"
        )
    else:
        mode = "live"
        rc = 0

    evidence = {
        "ts_utc": _utc_now(),
        "mode": mode,
        "probes": probes,
        "status": "ok" if ok else mode,
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
        "--strict",
        action="store_true",
        help="Fail (rc=2) if no alerting endpoint is reachable (for production gate enforcement)",
    )
    args = parser.parse_args()
    sys.exit(run_check(args.sink_url, args.alertmanager_url, args.slack_url, args.strict))


if __name__ == "__main__":
    main()
