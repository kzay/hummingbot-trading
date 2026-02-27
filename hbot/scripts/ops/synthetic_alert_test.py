"""Synthetic alert validation script.

Pushes a metric value above an alert threshold to the Prometheus pushgateway,
waits for the alert to fire, then verifies it appears in Alertmanager.

Requires a running Prometheus + Alertmanager + Pushgateway stack
(e.g. via ``docker compose --profile monitoring up``).

Usage::

    python scripts/ops/synthetic_alert_test.py
    python scripts/ops/synthetic_alert_test.py --alert BotDailyPnlDrawdown
    python scripts/ops/synthetic_alert_test.py --pushgw http://localhost:9091 --alertmgr http://localhost:9093
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Dict, List, Optional
from urllib import request, error, parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYNTHETIC_ALERTS: Dict[str, Dict[str, str]] = {
    "BotHardStopActive": {
        "metric_line": 'hbot_bot_state{state="hard_stop",bot="synthetic_test",variant="a",exchange="test",pair="BTC-USDT",regime="neutral_low_vol"} 1\n',
        "description": "Pushes hbot_bot_state{state=hard_stop}=1 (fires after 3m for rule)",
    },
    "BotDailyPnlDrawdown": {
        "metric_line": 'hbot_bot_daily_pnl_quote{bot="synthetic_test",variant="a",exchange="test",pair="BTC-USDT"} -100\n',
        "description": "Pushes hbot_bot_daily_pnl_quote=-100 (threshold is -50)",
    },
    "TickDurationHigh": {
        "metric_line": 'hbot_bot_tick_duration_seconds{bot="synthetic_test",variant="a",exchange="test",pair="BTC-USDT"} 0.5\n',
        "description": "Pushes tick duration 500ms (threshold is 100ms)",
    },
}

JOB_NAME = "synthetic_alert_test"


def push_metric(pushgw_url: str, metric_line: str) -> bool:
    url = f"{pushgw_url}/metrics/job/{JOB_NAME}"
    data = f"# TYPE hbot_test gauge\n{metric_line}".encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "text/plain")
    try:
        with request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 202):
                logger.info("Metric pushed to %s (status=%d)", url, resp.status)
                return True
            logger.error("Pushgateway returned status %d", resp.status)
            return False
    except Exception as exc:
        logger.error("Failed to push metric: %s", exc)
        return False


def delete_metric(pushgw_url: str) -> None:
    url = f"{pushgw_url}/metrics/job/{JOB_NAME}"
    req = request.Request(url, method="DELETE")
    try:
        with request.urlopen(req, timeout=5):
            logger.info("Cleaned up pushgateway job %s", JOB_NAME)
    except Exception:
        logger.warning("Cleanup failed (non-critical)")


def check_alertmanager(alertmgr_url: str, alert_name: str) -> bool:
    import json
    url = f"{alertmgr_url}/api/v2/alerts?filter=alertname%3D%22{parse.quote(alert_name)}%22"
    try:
        req = request.Request(url)
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                logger.info("Alert %s FOUND in Alertmanager (%d instance(s))", alert_name, len(data))
                return True
            logger.info("Alert %s not yet in Alertmanager", alert_name)
            return False
    except Exception as exc:
        logger.warning("Alertmanager query failed: %s", exc)
        return False


def check_prometheus_alerts(prom_url: str, alert_name: str) -> Optional[str]:
    """Check Prometheus /api/v1/alerts for pending/firing state."""
    import json
    url = f"{prom_url}/api/v1/alerts"
    try:
        req = request.Request(url)
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            alerts = data.get("data", {}).get("alerts", [])
            for a in alerts:
                labels = a.get("labels", {})
                if labels.get("alertname") == alert_name:
                    return a.get("state", "unknown")
    except Exception:
        pass
    return None


def run_test(
    alert_name: str,
    pushgw_url: str,
    alertmgr_url: str,
    prom_url: str,
    wait_seconds: int,
    poll_interval: int,
) -> bool:
    config = SYNTHETIC_ALERTS.get(alert_name)
    if config is None:
        logger.error("Unknown alert: %s. Available: %s", alert_name, list(SYNTHETIC_ALERTS.keys()))
        return False

    logger.info("=== Testing alert: %s ===", alert_name)
    logger.info("Description: %s", config["description"])

    if not push_metric(pushgw_url, config["metric_line"]):
        return False

    logger.info("Waiting up to %ds for alert to fire...", wait_seconds)
    deadline = time.time() + wait_seconds
    found = False
    while time.time() < deadline:
        prom_state = check_prometheus_alerts(prom_url, alert_name)
        if prom_state:
            logger.info("Prometheus alert state: %s", prom_state)
        if prom_state == "firing":
            if check_alertmanager(alertmgr_url, alert_name):
                found = True
                break
        time.sleep(poll_interval)

        if not push_metric(pushgw_url, config["metric_line"]):
            logger.warning("Re-push failed, continuing...")

    delete_metric(pushgw_url)

    if found:
        logger.info("PASS: Alert %s fired and appeared in Alertmanager", alert_name)
    else:
        prom_state = check_prometheus_alerts(prom_url, alert_name)
        logger.warning(
            "TIMEOUT: Alert %s did not fully fire within %ds (last Prometheus state: %s). "
            "This may be expected if the alert has a 'for' duration longer than the wait time.",
            alert_name, wait_seconds, prom_state or "not found",
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Prometheus alert rules with synthetic metrics")
    parser.add_argument("--alert", default="BotDailyPnlDrawdown", choices=list(SYNTHETIC_ALERTS.keys()))
    parser.add_argument("--pushgw", default="http://localhost:9091", help="Pushgateway URL")
    parser.add_argument("--alertmgr", default="http://localhost:9093", help="Alertmanager URL")
    parser.add_argument("--prom", default="http://localhost:9090", help="Prometheus URL")
    parser.add_argument("--wait", type=int, default=120, help="Max seconds to wait for alert")
    parser.add_argument("--poll", type=int, default=10, help="Poll interval in seconds")
    parser.add_argument("--all", action="store_true", help="Test all configured alerts")
    args = parser.parse_args()

    alerts_to_test = list(SYNTHETIC_ALERTS.keys()) if args.all else [args.alert]
    results = {}
    for name in alerts_to_test:
        results[name] = run_test(name, args.pushgw, args.alertmgr, args.prom, args.wait, args.poll)

    logger.info("=== Results ===")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL/TIMEOUT"
        logger.info("  %s: %s", name, status)
        if not passed:
            all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
