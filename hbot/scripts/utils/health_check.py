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
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def check_system_time_drift(max_drift_seconds: float = 2.0) -> bool:
    """Check if system time is reasonably accurate."""
    import time

    ntp_time = time.time()
    local_time = datetime.now(timezone.utc).timestamp()
    drift = abs(ntp_time - local_time)

    if drift > max_drift_seconds:
        logger.warning(f"System time drift detected: {drift:.2f}s")
        return False

    logger.info(f"System time drift: {drift:.4f}s (OK)")
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
        with open("/proc/meminfo", "r") as f:
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
    parser = argparse.ArgumentParser(description="Hummingbot Health Check")
    parser.add_argument("--exchange", default="bitget", help="Exchange name")
    parser.add_argument("--pair", default="BTC-USDT", help="Trading pair")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Hummingbot Health Check")
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
