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

Escalation:
  - First detection: alert + wait PAUSE_BEFORE_RESTART_S (gives human time to intervene)
  - After wait: if still stale, restart container
  - Circuit breaker: stop auto-restart after MAX_RESTARTS in WINDOW_S

Env vars:
  WATCHDOG_STALE_THRESHOLD_S     - seconds before a bot is considered frozen (default 300)
  WATCHDOG_CHECK_INTERVAL_S      - how often to check (default 60)
  WATCHDOG_PAUSE_BEFORE_RESTART_S - seconds to wait after first stale before restart (default 120)
  WATCHDOG_MAX_RESTARTS          - max restarts per window before breaker trips (default 5)
  WATCHDOG_WINDOW_S              - circuit breaker window in seconds (default 3600)
  WATCHDOG_BOTS                  - comma-separated list of bot names to watch (default: bot1)
  WATCHDOG_CONTAINER_PREFIX      - container name prefix (default: hbot-)
  HB_DATA_ROOT                   - path to hbot/data inside container
  TELEGRAM_BOT_TOKEN             - Telegram bot token for alerts
  TELEGRAM_CHAT_ID               - Telegram chat ID for alerts
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("bot_watchdog")

# ── Config ──────────────────────────────────────────────────────────
STALE_THRESHOLD_S = int(os.environ.get("WATCHDOG_STALE_THRESHOLD_S", "300"))
CHECK_INTERVAL_S = int(os.environ.get("WATCHDOG_CHECK_INTERVAL_S", "60"))
PAUSE_BEFORE_RESTART_S = int(os.environ.get("WATCHDOG_PAUSE_BEFORE_RESTART_S", "120"))
MAX_RESTARTS = int(os.environ.get("WATCHDOG_MAX_RESTARTS", "5"))
WINDOW_S = int(os.environ.get("WATCHDOG_WINDOW_S", "3600"))
MINUTE_STALE_HEARTBEAT_FRESH_GRACE_S = int(
    os.environ.get("WATCHDOG_MINUTE_STALE_HEARTBEAT_FRESH_GRACE_S", "900")
)
RESTART_BACKOFF_S = [
    int(x.strip())
    for x in os.environ.get("WATCHDOG_RESTART_BACKOFF_S", "60,120,300").split(",")
    if x.strip().isdigit()
]
if not RESTART_BACKOFF_S:
    RESTART_BACKOFF_S = [60, 120, 300]
FINGERPRINT_COOLDOWN_S = int(os.environ.get("WATCHDOG_FINGERPRINT_COOLDOWN_S", "600"))
BOT_NAMES = [b.strip() for b in os.environ.get("WATCHDOG_BOTS", "bot1").split(",") if b.strip()]
CONTAINER_PREFIX = os.environ.get("WATCHDOG_CONTAINER_PREFIX", "hbot-")
DATA_ROOT = Path(os.environ.get("HB_DATA_ROOT", "/workspace/hbot/data"))
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
STATE_FILE = Path(
    os.environ.get(
        "WATCHDOG_STATE_FILE",
        str(Path(os.environ.get("HB_DATA_ROOT", "/workspace/hbot/data")) / "watchdog_state.json"),
    )
)


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


# ── Docker socket API (no CLI needed) ────────────────────────────────
DOCKER_SOCK = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
_DOCKER_SOCK_PATH = "/var/run/docker.sock"


def _docker_api(method: str, path: str, timeout: int = 30) -> tuple[int, str]:
    """Call Docker API via Unix socket. Returns (status_code, body)."""
    import socket as _socket
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(_DOCKER_SOCK_PATH)
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Length: 0\r\n"
            f"Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode())
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        decoded = raw.decode("utf-8", errors="replace")
        first_line = decoded.split("\r\n")[0]
        try:
            code = int(first_line.split(" ")[1])
        except Exception:
            code = 0
        body = decoded.split("\r\n\r\n", 1)[-1] if "\r\n\r\n" in decoded else ""
        return code, body
    except Exception as exc:
        logger.error("Docker socket API %s %s failed: %s", method, path, exc)
        return 0, str(exc)


def _docker_restart(container: str) -> bool:
    code, _ = _docker_api("POST", f"/containers/{container}/restart")
    return code in (204, 200)


def _container_status(container: str) -> str:
    code, body = _docker_api("GET", f"/containers/{container}/json")
    if code == 200:
        try:
            return json.loads(body).get("State", {}).get("Status", "unknown")
        except Exception:
            pass
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


def _find_heartbeat_files(bot: str) -> List[Path]:
    bot_logs = DATA_ROOT / bot / "logs"
    if not bot_logs.exists():
        return []
    return list(bot_logs.rglob("strategy_heartbeat.json"))


def _bot_is_stale(bot: str) -> tuple[bool, float, str]:
    """Returns (is_stale, age_seconds, reason)."""
    files = _find_minute_csvs(bot)
    hb_files = _find_heartbeat_files(bot)
    newest_minute = max((f.stat().st_mtime for f in files), default=0.0)
    newest_hb = max((f.stat().st_mtime for f in hb_files), default=0.0)
    now = time.time()
    minute_age = (now - newest_minute) if newest_minute > 0 else 9999.0
    hb_age = (now - newest_hb) if newest_hb > 0 else 9999.0

    if not files and not hb_files:
        return True, 9999, "no_minute_or_heartbeat_found"
    if files and minute_age > STALE_THRESHOLD_S:
        if hb_files and hb_age <= STALE_THRESHOLD_S:
            grace_limit = STALE_THRESHOLD_S + MINUTE_STALE_HEARTBEAT_FRESH_GRACE_S
            if minute_age <= grace_limit:
                return False, minute_age, f"minute_stale_heartbeat_fresh_grace_{minute_age:.0f}s"
        return True, minute_age, f"minute_csv_stale_{minute_age:.0f}s"
    if hb_files and hb_age > STALE_THRESHOLD_S:
        return True, hb_age, f"strategy_heartbeat_stale_{hb_age:.0f}s"
    if not files and hb_age > STALE_THRESHOLD_S:
        return True, hb_age, f"minute_missing_heartbeat_stale_{hb_age:.0f}s"
    if not hb_files and minute_age > STALE_THRESHOLD_S:
        return True, minute_age, f"heartbeat_missing_minute_stale_{minute_age:.0f}s"

    age = min(minute_age, hb_age)
    if age < 0:
        age = 0
    if age > STALE_THRESHOLD_S:
        return True, age, f"stale_{age:.0f}s"
    if not files:
        return False, hb_age, "minute_missing_heartbeat_ok"
    if not hb_files:
        return False, minute_age, "heartbeat_missing_minute_ok"
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
    state[f"{bot}_last_restart_ts"] = time.time()


def _restart_backoff_active(bot: str, state: dict) -> Tuple[bool, int]:
    restarts = state.get(f"{bot}_restarts", [])
    if not isinstance(restarts, list):
        restarts = []
    last_restart_ts = float(state.get(f"{bot}_last_restart_ts", 0))
    if last_restart_ts <= 0:
        return False, 0
    idx = min(max(len(restarts) - 1, 0), len(RESTART_BACKOFF_S) - 1)
    cooldown = RESTART_BACKOFF_S[idx]
    remaining = int(cooldown - (time.time() - last_restart_ts))
    return (remaining > 0), max(0, remaining)


def _failure_fingerprint(reason: str, container_state: str) -> str:
    return f"{reason}|{container_state}"


def _fingerprint_suppressed(bot: str, fingerprint: str, state: dict) -> Tuple[bool, int]:
    key = f"{bot}_fingerprints"
    fp_map = state.get(key, {})
    if not isinstance(fp_map, dict):
        fp_map = {}
    last_seen = float(fp_map.get(fingerprint, 0))
    if last_seen <= 0:
        return False, 0
    remaining = int(FINGERPRINT_COOLDOWN_S - (time.time() - last_seen))
    return (remaining > 0), max(0, remaining)


def _record_fingerprint(bot: str, fingerprint: str, state: dict) -> None:
    key = f"{bot}_fingerprints"
    fp_map = state.get(key, {})
    if not isinstance(fp_map, dict):
        fp_map = {}
    fp_map[fingerprint] = time.time()
    # prune old fingerprints to keep state file compact
    for fp, ts in list(fp_map.items()):
        if time.time() - float(ts) > FINGERPRINT_COOLDOWN_S * 3:
            fp_map.pop(fp, None)
    state[key] = fp_map


def _get_stale_since(bot: str, state: dict) -> float:
    """Return timestamp when bot was first detected stale, or 0 if not tracked."""
    key = f"{bot}_stale_since"
    return float(state.get(key, 0))


def _set_stale_since(bot: str, state: dict, ts: float) -> None:
    state[f"{bot}_stale_since"] = ts


def _clear_stale_since(bot: str, state: dict) -> None:
    state.pop(f"{bot}_stale_since", None)


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

    service_recovery_enabled = os.environ.get("WATCHDOG_SERVICE_RECOVERY_ENABLED", "").lower() in ("true", "1")
    service_recovery_interval = int(os.environ.get("WATCHDOG_SERVICE_RECOVERY_INTERVAL_CHECKS", "5"))
    check_count = 0

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
                    _clear_stale_since(bot, state)
                    continue

                # Escalation: pause before restart — give human time to intervene
                stale_since = _get_stale_since(bot, state)
                if stale_since == 0:
                    _set_stale_since(bot, state, time.time())
                    stale_since = time.time()
                wait_remaining = max(0, PAUSE_BEFORE_RESTART_S - (time.time() - stale_since))
                if wait_remaining > 0:
                    logger.warning(
                        "Bot %s stale (age=%.0fs). Pausing %ds before restart. Human may intervene.",
                        bot, age, int(wait_remaining),
                    )
                    _tg(
                        f"⏸️ <b>{bot} frozen — pausing before restart</b>\n"
                        f"Stale for <b>{age:.0f}s</b> ({reason})\n"
                        f"Restart in <b>{int(wait_remaining)}s</b> unless you intervene.\n"
                        f"Container: {container_state} | {equity_info}\n"
                        f"<i>{now_str}</i>"
                    )
                    continue

                # Per-bot restart backoff to avoid rapid restart loops.
                backoff_active, backoff_remaining = _restart_backoff_active(bot, state)
                if backoff_active:
                    logger.warning(
                        "Bot %s stale but restart backoff active (%ds remaining).",
                        bot, backoff_remaining,
                    )
                    continue

                # Suppress repeated identical-failure restarts for a cooldown window.
                fingerprint = _failure_fingerprint(reason, container_state)
                suppressed, remaining = _fingerprint_suppressed(bot, fingerprint, state)
                if suppressed:
                    logger.warning(
                        "Bot %s stale with repeated fingerprint '%s' (suppressed %ds).",
                        bot, fingerprint, remaining,
                    )
                    continue

                # Pause period elapsed — proceed with restart
                _clear_stale_since(bot, state)
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
                _record_fingerprint(bot, fingerprint, state)

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

        # Optional: periodic service recovery (Redis, risk-service)
        check_count += 1
        if service_recovery_enabled and check_count >= service_recovery_interval:
            check_count = 0
            try:
                import subprocess
                root = Path(os.environ.get("HB_DATA_ROOT", "/workspace/hbot/data")).parent
                script = root / "scripts" / "ops" / "service_recovery.py"
                if script.exists():
                    subprocess.run(
                        [sys.executable, str(script)],
                        cwd=str(root),
                        capture_output=True,
                        timeout=60,
                        check=False,
                    )
            except Exception as exc:
                logger.warning("Service recovery failed: %s", exc)

        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    run()
