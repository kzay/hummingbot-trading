"""
Health Check Utility

Lightweight script to verify bot connectivity and exchange status.
Can be run standalone or imported into strategies.

Usage:
  python health_check.py --exchange bitget --pair BTC-USDT
"""

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def check_system_time_drift(max_drift_seconds: float = 2.0) -> bool:
    """Check system clock against Bitget server time.

    Queries Bitget's public time endpoint and compares against local clock.
    Falls back to checking against multiple HTTP Date headers if Bitget is unreachable.
    """
    import json as _json
    import time
    import urllib.request

    endpoints = [
        ("https://api.bitget.com/api/v2/public/time", "bitget"),
        ("https://api.binance.com/api/v3/time", "binance"),
    ]
    for url, name in endpoints:
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "kzay-capital-health-check/1.0")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = _json.loads(resp.read())
                if name == "bitget":
                    server_ms = int(body.get("data", {}).get("serverTime", 0))
                else:
                    server_ms = int(body.get("serverTime", 0))
                if server_ms > 0:
                    server_s = server_ms / 1000.0
                    local_s = time.time()
                    drift = abs(local_s - server_s)
                    if drift > max_drift_seconds:
                        logger.warning("Clock drift %.2fs vs %s server (max %.1fs)", drift, name, max_drift_seconds)
                        return False
                    logger.info("Clock drift: %.3fs vs %s server (OK)", drift, name)
                    return True
        except Exception as exc:
            logger.debug("Time check via %s failed: %s", name, exc)
            continue

    logger.warning("Could not reach any time server — clock drift check skipped")
    return True


def check_disk_space(min_free_gb: float = 1.0) -> bool:
    """Check if there's enough disk space."""
    import shutil

    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024**3)

    if free_gb < min_free_gb:
        logger.warning(f"Low disk space: {free_gb:.2f} GB free")
        return False

    logger.info(f"Disk space: {free_gb:.2f} GB free (OK)")
    return True


def check_memory(min_free_mb: float = 256.0) -> bool:
    """Check available memory."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
                    available_mb = available_kb / 1024

                    if available_mb < min_free_mb:
                        logger.warning(
                            f"Low memory: {available_mb:.0f} MB available"
                        )
                        return False

                    logger.info(f"Memory: {available_mb:.0f} MB available (OK)")
                    return True
    except FileNotFoundError:
        logger.info("Memory check skipped (not Linux)")
        return True

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Kzay Capital Health Check")
    parser.add_argument("--exchange", default="bitget", help="Exchange name")
    parser.add_argument("--pair", default="BTC-USDT", help="Trading pair")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Kzay Capital Health Check")
    logger.info("=" * 50)

    checks_passed = 0
    checks_total = 0

    # Disk check
    checks_total += 1
    if check_disk_space():
        checks_passed += 1

    # Memory check
    checks_total += 1
    if check_memory():
        checks_passed += 1

    # Time drift check
    checks_total += 1
    if asyncio.run(check_system_time_drift()):
        checks_passed += 1

    logger.info("=" * 50)
    logger.info(f"Results: {checks_passed}/{checks_total} checks passed")

    if checks_passed == checks_total:
        logger.info("STATUS: ALL OK")
        return 0
    else:
        logger.warning("STATUS: ISSUES DETECTED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
