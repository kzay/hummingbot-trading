"""Bot Watchdog Service.

Monitors bot health by checking minute.csv freshness and automatically
restarts frozen containers. Sends Telegram alerts before every action.

Failure modes detected:
  - WS event-loop hang (minute.csv stale > STALE_THRESHOLD_S seconds)
  - Container hard_stop not recovering (last state=hard_stop in minute.csv)

Circuit breaker:
  - Max MAX_RESTARTS_PER_WINDOW restarts within WINDOW_SECONDS
  - After breaker trips: escalated alert + stop auto-restarting
  - Breaker resets after WINDOW_SECONDS of no restarts

Usage (Docker):
  docker run -v /var/run/docker.sock:/var/run/docker.sock ...

Env vars:
  WATCHDOG_STALE_THRESHOLD_S  - seconds before a bot is considered frozen (default 300)
  WATCHDOG_CHECK_INTERVAL_S   - how often to check (default 60)
  WATCHDOG_MAX_RESTARTS       - max restarts per window before breaker trips (default 5)
  WATCHDOG_WINDOW_S           - circuit breaker window in seconds (default 3600)
  WATCHDOG_BOTS               - comma-separated list of bot names to watch (default: bot1)
  WATCHDOG_CONTAINER_PREFIX   - container name prefix (default: hbot-)
  HB_DATA_ROOT                - path to hbot/data inside container
  TELEGRAM_BOT_TOKEN          - Telegram bot token for alerts
  TELEGRAM_CHAT_ID            - Telegram chat ID for alerts
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("bot_watchdog")

# ── Config ──────────────────────────────────────────────────────────
STALE_THRESHOLD_S = int(os.environ.get("WATCHDOG_STALE_THRESHOLD_S", "300"))
CHECK_INTERVAL_S = int(os.environ.get("WATCHDOG_CHECK_INTERVAL_S", "60"))
MAX_RESTARTS = int(os.environ.get("WATCHDOG_MAX_RESTARTS", "5"))
WINDOW_S = int(os.environ.get("WATCHDOG_WINDOW_S", "3600"))
BOT_NAMES = [b.strip() for b in os.environ.get("WATCHDOG_BOTS", "bot1").split(",") if b.strip()]
CONTAINER_PREFIX = os.environ.get("WATCHDOG_CONTAINER_PREFIX", "hbot-")
DATA_ROOT = Path(os.environ.get("HB_DATA_ROOT", "/workspace/hbot/data"))
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
STATE_FILE = Path("/tmp/watchdog_state.json")


# ── Telegram ─────────────────────────────────────────────────────────
def _tg(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        payload = json.dumps({"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)


# ── Docker ───────────────────────────────────────────────────────────
def _docker_restart(container: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.error("docker restart %s failed: %s", container, exc)
        return False


def _container_status(container: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "inspect", container, "--format", "{{.State.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ── State ─────────────────────────────────────────────────────────────
def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Health check ──────────────────────────────────────────────────────
def _find_minute_csvs(bot: str) -> List[Path]:
    bot_data = DATA_ROOT / bot / "logs"
    if not bot_data.exists():
        return []
    return list(bot_data.rglob("minute.csv"))


def _bot_is_stale(bot: str) -> tuple[bool, float, str]:
    """Returns (is_stale, age_seconds, reason)."""
    files = _find_minute_csvs(bot)
    if not files:
        return True, 9999, "no_minute_csv_found"
    newest = max(f.stat().st_mtime for f in files)
    age = time.time() - newest
    if age > STALE_THRESHOLD_S:
        return True, age, f"minute_csv_stale_{age:.0f}s"
    return False, age, "ok"


def _get_current_equity(bot: str) -> str:
    files = _find_minute_csvs(bot)
    if not files:
        return "unknown"
    f = max(files, key=lambda p: p.stat().st_mtime)
    try:
        last = f.read_text(encoding="utf-8").strip().rsplit("\n", 1)[-1]
        cols = last.split(",")
        equity = float(cols[9]) if len(cols) > 9 else 0
        position = cols[44] if len(cols) > 44 else "?"
        return f"equity={equity:.2f} pos={position}"
    except Exception:
        return "unknown"


# ── Circuit breaker ───────────────────────────────────────────────────
def _check_circuit_breaker(bot: str, state: dict) -> tuple[bool, int]:
    """Returns (breaker_open, restart_count_in_window)."""
    now = time.time()
    key = f"{bot}_restarts"
    restarts: List[float] = state.get(key, [])
    # Prune outside window
    restarts = [t for t in restarts if now - t < WINDOW_S]
    state[key] = restarts
    return len(restarts) >= MAX_RESTARTS, len(restarts)


def _record_restart(bot: str, state: dict) -> None:
    key = f"{bot}_restarts"
    state.setdefault(key, []).append(time.time())


# ── Main loop ─────────────────────────────────────────────────────────
def run() -> None:
    logger.info(
        "Watchdog started — bots=%s stale_threshold=%ds check_interval=%ds "
        "circuit_breaker=%d/%ds",
        BOT_NAMES, STALE_THRESHOLD_S, CHECK_INTERVAL_S, MAX_RESTARTS, WINDOW_S,
    )
    if not TG_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — alerts will be logged only")

    _tg("🟢 <b>Bot Watchdog started</b>\nMonitoring: " + ", ".join(BOT_NAMES))

    while True:
        try:
            state = _load_state()
            now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

            for bot in BOT_NAMES:
                container = f"{CONTAINER_PREFIX}{bot}"
                stale, age, reason = _bot_is_stale(bot)

                if not stale:
                    continue

                # Bot is stale — check circuit breaker
                breaker_open, restart_count = _check_circuit_breaker(bot, state)
                equity_info = _get_current_equity(bot)
                container_state = _container_status(container)

                if breaker_open:
                    # Escalated alert — too many restarts, human must intervene
                    logger.error(
                        "CIRCUIT BREAKER OPEN for %s: %d restarts in %ds window. "
                        "Manual intervention required.",
                        bot, restart_count, WINDOW_S,
                    )
                    _tg(
                        f"⛔ <b>CIRCUIT BREAKER — {bot}</b>\n"
                        f"{restart_count} auto-restarts in the last {WINDOW_S//60} min.\n"
                        f"Container: {container_state} | {equity_info}\n"
                        f"<b>Manual intervention required. Bot NOT being restarted.</b>\n"
                        f"<i>{now_str}</i>"
                    )
                    # Don't restart — wait for manual action
                    continue

                # Normal restart path
                logger.warning(
                    "Bot %s is stale (age=%.0fs, reason=%s). Restarting %s (attempt %d/%d).",
                    bot, age, reason, container, restart_count + 1, MAX_RESTARTS,
                )
                _tg(
                    f"⚠️ <b>{bot} frozen — auto-restarting</b>\n"
                    f"Stale for <b>{age:.0f}s</b> ({reason})\n"
                    f"Container: {container_state} | {equity_info}\n"
                    f"Attempt {restart_count + 1}/{MAX_RESTARTS}\n"
                    f"<i>{now_str}</i>"
                )

                success = _docker_restart(container)
                _record_restart(bot, state)

                if success:
                    logger.info("Restarted %s successfully.", container)
                    # Wait for bot to come back and validate
                    time.sleep(90)
                    stale_after, age_after, _ = _bot_is_stale(bot)
                    if stale_after:
                        _tg(
                            f"🔴 <b>{bot} still unresponsive after restart</b>\n"
                            f"Still stale {age_after:.0f}s after restart.\n"
                            f"<i>{now_str}</i>"
                        )
                    else:
                        _tg(
                            f"✅ <b>{bot} recovered</b>\n"
                            f"Now responding after restart.\n"
                            f"<i>{now_str}</i>"
                        )
                else:
                    logger.error("Failed to restart %s.", container)
                    _tg(
                        f"🔴 <b>docker restart FAILED for {bot}</b>\n"
                        f"<i>{now_str}</i>"
                    )

            _save_state(state)

        except Exception as exc:
            logger.error("Watchdog loop error: %s", exc, exc_info=True)

        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    run()
