"""Telegram command bot for the hbot trading desk.

Responds to commands in the configured chat, reading data directly from
minute.csv, fills.csv, and reports/ JSON files. No database required.

Commands:
    /status    — bot state, regime, orders, tick age
    /go        — one-line GO/HOLD + top blockers
    /orders    — active open orders (price, side, age, amount)
    /desk      — global gate/strict/day2 readiness snapshot
    /pnl       — equity, daily PnL, realized PnL, drawdown, fees
    /position  — net position, avg entry, exposure, margin ratio
    /fills [N] — last N fills (default 5) with side/price/edge
    /risk      — daily loss, drawdown, risk reasons, funding, margin
    /help      — list commands

Setup:
    TELEGRAM_BOT_TOKEN   — from @BotFather
    TELEGRAM_CHAT_ID     — numeric ID or @channel username
    HB_DATA_ROOT         — path to hbot/data (default: auto-detect)

Requires: python-telegram-bot >= 20.0 (async)

Run::

    python services/telegram_bot/main.py
"""
from __future__ import annotations

import asyncio
import csv
import html
import json
import logging
import os
import time
from pathlib import Path

from platform_lib.logging.log_namespace import list_bot_log_files
from platform_lib.logging.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID_RAW = os.environ.get("TELEGRAM_CHAT_ID", "")
_DATA_ROOT = Path(os.environ.get("HB_DATA_ROOT", ""))
if not _DATA_ROOT or not _DATA_ROOT.is_absolute():
    _DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

_REPORTS_ROOT = Path(os.environ.get("HB_REPORTS_ROOT", ""))
if not _REPORTS_ROOT or not _REPORTS_ROOT.is_absolute():
    _REPORTS_ROOT = Path(__file__).resolve().parents[2] / "reports"

_SNAPSHOT_ROOT = _REPORTS_ROOT / "desk_snapshot"
_SNAPSHOT_STALE_S = 180.0   # treat snapshot as stale after 3 minutes


def _allowed_chat_id() -> int | None:
    raw = _CHAT_ID_RAW.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data reading helpers
# ---------------------------------------------------------------------------

def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _read_last_csv_row(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            last: dict[str, str] | None = None
            for row in reader:
                last = dict(row)
            return last
    except Exception:
        return None


def _read_last_n_csv_rows(path: Path, n: int) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        rows: list[dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows[-n:]
    except Exception:
        return []


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_minute_files() -> list[Path]:
    return list_bot_log_files(_DATA_ROOT, "minute.csv")


def _find_fills_files() -> list[Path]:
    return list_bot_log_files(_DATA_ROOT, "fills.csv")


def _find_open_orders_files() -> list[Path]:
    return sorted(_DATA_ROOT.glob("*/logs/recovery/open_orders_latest.json"))


# ---------------------------------------------------------------------------
# Canonical desk snapshot helpers (INFRA-5)
# ---------------------------------------------------------------------------

def _read_desk_snapshot(bot: str) -> dict | None:
    """Return the canonical desk snapshot for *bot* if present and fresh."""
    path = _SNAPSHOT_ROOT / bot / "latest.json"
    d = _read_json(path)
    if not d:
        return None
    # Check freshness based on snapshot generated_ts
    gen_ts = str(d.get("generated_ts", ""))
    if gen_ts:
        try:
            from datetime import datetime
            epoch = datetime.fromisoformat(gen_ts.replace("Z", "+00:00")).timestamp()
            if time.time() - epoch > _SNAPSHOT_STALE_S:
                return None  # stale — fall back to raw files
        except Exception:
            pass  # Justification: parse failure is expected for malformed snapshot ts — still return snapshot
    return d


def _load_all_snapshots() -> dict[str, dict]:
    """Return {bot_name: snapshot} for all bots with a valid fresh snapshot."""
    result: dict[str, dict] = {}
    if not _SNAPSHOT_ROOT.exists():
        return result
    for bot_dir in sorted(_SNAPSHOT_ROOT.iterdir()):
        if not bot_dir.is_dir():
            continue
        snap = _read_desk_snapshot(bot_dir.name)
        if snap:
            result[bot_dir.name] = snap
    return result


def _snap_minute(snap: dict) -> dict:
    """Extract minute dict from snapshot, or empty dict."""
    m = snap.get("minute")
    return m if isinstance(m, dict) else {}


def _snap_age_warn(snap: dict) -> str:
    """Return a stale warning suffix if minute data is old."""
    age = snap.get("minute_age_s")
    if age is not None and age > 120:
        return f" ⚠️ tick {int(age)}s"
    return ""


def _state_emoji(state: str) -> str:
    return {"running": "✅", "soft_pause": "⏸", "hard_stop": "🛑"}.get(state, "❓")


def _pct(v: float) -> str:
    return f"{v * 100:.3f}%"


def _fmt_age(ts_str: str) -> str:
    if not ts_str:
        return "unknown"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age_s = int(time.time() - dt.timestamp())
        if age_s < 120:
            return f"{age_s}s ago"
        return f"{age_s // 60}m ago"
    except Exception:
        return ts_str


_TG_MAX_MSG_LEN = 4096
_REPLY_MAX_RETRIES = 3
_REPLY_RETRY_BASE_S = 1.0


def _truncate(text: str, limit: int = _TG_MAX_MSG_LEN) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n… <i>(truncated)</i>"
    return text[: limit - len(suffix)] + suffix


def _esc(value: object) -> str:
    """HTML-escape arbitrary user/data values for Telegram messages."""
    return html.escape(str(value))


async def _safe_reply_html(message, text: str) -> None:
    """Send an HTML reply with truncation and bounded retry on transient errors."""
    body = _truncate(text)
    for attempt in range(1, _REPLY_MAX_RETRIES + 1):
        try:
            await message.reply_html(body)
            return
        except Exception:
            if attempt == _REPLY_MAX_RETRIES:
                logger.error("Failed to send Telegram reply after %d attempts", _REPLY_MAX_RETRIES, exc_info=True)
                return
            delay = _REPLY_RETRY_BASE_S * (2 ** (attempt - 1))
            logger.warning("Telegram reply attempt %d failed, retrying in %.1fs", attempt, delay, exc_info=True)
            await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _build_status() -> str:
    snapshots = _load_all_snapshots()
    parts = []

    if snapshots:
        for bot, snap in snapshots.items():
            row = _snap_minute(snap)
            state = _esc(row.get("state", "?"))
            regime = _esc(row.get("regime", "?"))
            orders = int(_safe_float(row.get("orders_active")))
            risk = _esc(row.get("risk_reasons", "") or "none")
            age = _fmt_age(row.get("ts", ""))
            book_stale = str(row.get("order_book_stale", "")).lower() == "true"
            stale_warn = " ⚠️ book stale" if book_stale else ""
            age_warn = _snap_age_warn(snap)
            completeness = snap.get("completeness", 1.0)
            comp_warn = f" ⚠️ data {completeness:.0%}" if completeness < 0.8 else ""
            parts.append(
                f"<b>{_esc(bot)}</b> {_state_emoji(state)} <code>{state}</code>\n"
                f"  Regime: <code>{regime}</code>\n"
                f"  Orders: {orders}  |  Tick: {age}{stale_warn}{age_warn}{comp_warn}\n"
                f"  Risk: <code>{risk}</code>"
            )
        return "\n\n".join(parts)

    # Fallback: direct file reads
    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found — is the bot running?"
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if not row:
            continue
        bot = _esc(mf.parts[-5])
        state = _esc(row.get("state", "?"))
        regime = _esc(row.get("regime", "?"))
        orders = int(_safe_float(row.get("orders_active")))
        risk = _esc(row.get("risk_reasons", "") or "none")
        age = _fmt_age(row.get("ts", ""))
        book_stale = str(row.get("order_book_stale", "")).lower() == "true"
        stale_warn = " ⚠️ book stale" if book_stale else ""
        parts.append(
            f"<b>{bot}</b> {_state_emoji(state)} <code>{state}</code>\n"
            f"  Regime: <code>{regime}</code>\n"
            f"  Orders: {orders}  |  Tick: {age}{stale_warn}\n"
            f"  Risk: <code>{risk}</code>"
        )
    return "\n\n".join(parts) or "No data."


def _build_pnl() -> str:
    def _render(bot: str, row: dict) -> str:
        equity = _safe_float(row.get("equity_quote"))
        daily_loss = _safe_float(row.get("daily_loss_pct"))
        drawdown = _safe_float(row.get("drawdown_pct"))
        realized = _safe_float(row.get("realized_pnl_today_quote"))
        fees = _safe_float(row.get("fees_paid_today_quote"))
        fills = int(_safe_float(row.get("fills_count_today")))
        turnover = _safe_float(row.get("turnover_today_x"))
        pnl_sign = "+" if realized >= 0 else ""
        loss_sign = "+" if daily_loss >= 0 else ""
        return (
            f"<b>{_esc(bot)} PnL</b>\n"
            f"  Equity:    <code>{equity:.2f} USDT</code>\n"
            f"  Realized:  <code>{pnl_sign}{realized:.4f} USDT</code>\n"
            f"  Daily Δ:   <code>{loss_sign}{daily_loss * 100:.3f}%</code>\n"
            f"  Drawdown:  <code>{drawdown * 100:.3f}%</code>\n"
            f"  Fees paid: <code>{fees:.4f} USDT</code>\n"
            f"  Fills: {fills}  |  Turnover: {turnover:.2f}x"
        )

    snapshots = _load_all_snapshots()
    if snapshots:
        return "\n\n".join(_render(b, _snap_minute(s)) for b, s in snapshots.items()) or "No data."

    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if row:
            parts.append(_render(mf.parts[-5], row))
    return "\n\n".join(parts) or "No data."


def _build_position() -> str:
    def _render(bot: str, row: dict) -> str:
        pos_base = _safe_float(row.get("position_base"))
        avg_entry = _safe_float(row.get("avg_entry_price"))
        base_pct = _safe_float(row.get("base_pct"))
        target_pct = _safe_float(row.get("target_base_pct"))
        net_base_pct = _safe_float(row.get("net_base_pct"))
        margin = _safe_float(row.get("margin_ratio"), 1.0)
        mid = _safe_float(row.get("mid"))
        notional = abs(pos_base) * mid if mid > 0 else 0.0
        pair = _esc(row.get("trading_pair", "?"))
        direction = "LONG" if pos_base > 0 else ("SHORT" if pos_base < 0 else "FLAT")
        return (
            f"<b>{_esc(bot)} Position</b>\n"
            f"  {pair}: <code>{pos_base:+.6f}</code> ({direction})\n"
            f"  Notional:  <code>{notional:.2f} USDT</code>\n"
            f"  Avg entry: <code>{avg_entry:.2f}</code>  |  Mid: <code>{mid:.2f}</code>\n"
            f"  Base %:    <code>{_pct(base_pct)}</code> → target <code>{_pct(target_pct)}</code>\n"
            f"  Net %:     <code>{_pct(net_base_pct)}</code>\n"
            f"  Margin:    <code>{margin:.3f}</code>"
        )

    snapshots = _load_all_snapshots()
    if snapshots:
        return "\n\n".join(_render(b, _snap_minute(s)) for b, s in snapshots.items()) or "No data."

    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if row:
            parts.append(_render(mf.parts[-5], row))
    return "\n\n".join(parts) or "No data."


def _build_fills(n: int = 5) -> str:
    fills_files = _find_fills_files()
    if not fills_files:
        return "No fills.csv found."
    parts = []
    for ff in fills_files:
        bot = _esc(ff.parts[-5])
        rows = _read_last_n_csv_rows(ff, n)
        if not rows:
            parts.append(f"<b>{bot}</b>: no fills yet.")
            continue
        lines = [f"<b>{bot}</b> — last {len(rows)} fills:"]
        for row in reversed(rows):
            side = _esc(row.get("side", "?").upper())
            price = _safe_float(row.get("price"))
            amount = _safe_float(row.get("amount_base"))
            pnl = _safe_float(row.get("realized_pnl_quote"))
            is_maker = str(row.get("is_maker", "")).lower() == "true"
            ts = _esc(row.get("ts", "")[:16].replace("T", " "))
            role = "M" if is_maker else "T"
            pnl_str = f"  pnl={pnl:+.4f}" if pnl != 0 else ""
            lines.append(f"  {ts}  <code>{side:4s}</code> {amount:.6f} @ {price:.2f} [{role}]{pnl_str}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts) or "No data."


def _build_orders(limit_per_bot: int = 20, bot_filter: str | None = None) -> str:
    order_files = _find_open_orders_files()
    minute_by_bot: dict[str, dict[str, str]] = {}
    for mf in _find_minute_files():
        bot = mf.parts[-5]
        row = _read_last_csv_row(mf)
        if row:
            minute_by_bot[bot] = row

    if not order_files and not minute_by_bot:
        return "No order/strategy data found."

    parts: list[str] = []
    seen_bots: set[str] = set()
    for path in order_files:
        bot = path.parts[-4] if len(path.parts) >= 4 else "unknown"
        if bot_filter and bot != bot_filter:
            continue
        seen_bots.add(bot)
        payload = _read_json(path) or {}
        orders = payload.get("orders", [])
        if not isinstance(orders, list):
            orders = []
        ts_utc = str(payload.get("ts_utc", ""))
        minute = minute_by_bot.get(bot, {})
        state = _esc(str(minute.get("state", "?")))
        regime = _esc(str(minute.get("regime", "?")))
        risk = _esc(str(minute.get("risk_reasons", "") or "none"))
        bot_e = _esc(bot)
        header = (
            f"<b>{bot_e} Orders</b> {_state_emoji(state)} <code>{state}</code>\n"
            f"  Regime: <code>{regime}</code>  |  Snapshot: {_fmt_age(ts_utc)}\n"
            f"  Risk: <code>{risk}</code>\n"
            f"  Active: <code>{len(orders)}</code>"
        )
        if not orders:
            parts.append(header + "\n  <i>No active orders.</i>")
            continue
        rows = [header]
        for row in orders[:limit_per_bot]:
            side = _esc(str(row.get("side", "?")).upper())
            price = _safe_float(row.get("price"))
            amount = _safe_float(row.get("amount"))
            age = _safe_float(row.get("age_sec"))
            oid = _esc(str(row.get("order_id", ""))[:14])
            pair = _esc(str(row.get("trading_pair", "?")))
            rows.append(
                f"  <code>{side:4s}</code> {amount:.6f} @ {price:.2f}  ({age:.0f}s)  {pair}  <code>{oid}</code>"
            )
        parts.append("\n".join(rows))

    for bot, minute in minute_by_bot.items():
        if bot_filter and bot != bot_filter:
            continue
        if bot in seen_bots:
            continue
        state = _esc(str(minute.get("state", "?")))
        regime = _esc(str(minute.get("regime", "?")))
        orders_active = int(_safe_float(minute.get("orders_active")))
        bot_e = _esc(bot)
        parts.append(
            f"<b>{bot_e} Orders</b> {_state_emoji(state)} <code>{state}</code>\n"
            f"  Regime: <code>{regime}</code>\n"
            f"  Active (minute.csv): <code>{orders_active}</code>\n"
            f"  <i>No open_orders snapshot file yet.</i>"
        )
    return "\n\n".join(parts) if parts else "No active orders."


def _build_desk() -> str:
    # Prefer snapshot gates from any bot's snapshot (they all share the same gate reports)
    gates: dict = {}
    snapshots = _load_all_snapshots()
    for snap in snapshots.values():
        if snap.get("gates"):
            gates = snap["gates"]
            break

    def _gate(key: str) -> dict:
        return gates.get(key) or _read_json(_REPORTS_ROOT / _GATE_PATHS.get(key, "")) or {}

    _GATE_PATHS = {
        "promotion": "promotion_gates/latest.json",
        "strict_cycle": "promotion_gates/strict_cycle_latest.json",
        "day2": "event_store/day2_gate_eval_latest.json",
        "soak": "paper_soak/latest.json",
        "reconciliation": "reconciliation/latest.json",
    }

    promotion = _gate("promotion")
    strict_cycle = _gate("strict_cycle")
    day2 = _gate("day2")
    soak = _gate("soak")
    recon = _gate("reconciliation")

    prom_status = _esc(str(promotion.get("status", "unknown")).upper())
    strict_status = _esc(str(strict_cycle.get("strict_gate_status", "unknown")).upper())
    day2_go = bool(day2.get("go", False))
    soak_status = _esc(str(soak.get("status", "unknown")).upper())
    recon_status = _esc(str(recon.get("status", "unknown")).upper())

    critical_failures = promotion.get("critical_failures", [])
    if not isinstance(critical_failures, list):
        critical_failures = []

    lines = [
        "<b>Desk Global Status</b>",
        f"  Promotion gates: <code>{prom_status}</code>",
        f"  Strict cycle:    <code>{strict_status}</code>",
        f"  Day2 gate:       <code>{'GO' if day2_go else 'HOLD'}</code>",
        f"  Paper soak:      <code>{soak_status}</code>",
        f"  Reconciliation:  <code>{recon_status}</code>",
    ]
    if critical_failures:
        lines.append("  Critical fails:")
        for name in critical_failures[:8]:
            lines.append(f"   - <code>{_esc(name)}</code>")
    else:
        lines.append("  Critical fails: <code>none</code>")
    return "\n".join(lines)


def _build_go() -> str:
    # Try snapshot gates first
    promotion: dict = {}
    for snap in _load_all_snapshots().values():
        g = snap.get("gates", {})
        if g.get("promotion"):
            promotion = g["promotion"]
            break
    if not promotion:
        promotion = _read_json(_REPORTS_ROOT / "promotion_gates" / "latest.json") or {}
    status = str(promotion.get("status", "UNKNOWN")).upper()
    critical_failures = promotion.get("critical_failures", [])
    if not isinstance(critical_failures, list):
        critical_failures = []
    blockers = critical_failures[:3]
    if status == "PASS":
        return "✅ <b>GO</b> — all critical promotion gates PASS."
    if blockers:
        joined = ", ".join(f"<code>{_esc(b)}</code>" for b in blockers)
        return f"⛔ <b>HOLD</b> — blockers: {joined}"
    return f"⛔ <b>HOLD</b> — promotion status: <code>{_esc(status)}</code>"


def _build_risk() -> str:
    def _render(bot: str, row: dict) -> str:
        daily_loss = _safe_float(row.get("daily_loss_pct"))
        drawdown = _safe_float(row.get("drawdown_pct"))
        risk_reasons = _esc(row.get("risk_reasons", "") or "none")
        funding = _safe_float(row.get("funding_rate"))
        margin = _safe_float(row.get("margin_ratio"), 1.0)
        drift = _safe_float(row.get("position_drift_pct"))
        ws_recon = int(_safe_float(row.get("ws_reconnect_count")))
        cancel_rate = _safe_float(row.get("cancel_per_min"))
        funding_bps = funding * 10000
        return (
            f"<b>{_esc(bot)} Risk</b>\n"
            f"  Daily loss:  <code>{daily_loss * 100:.3f}%</code>\n"
            f"  Drawdown:    <code>{drawdown * 100:.3f}%</code>\n"
            f"  Reasons:     <code>{risk_reasons}</code>\n"
            f"  Funding:     <code>{funding_bps:.2f} bps</code>\n"
            f"  Margin:      <code>{margin:.3f}</code>\n"
            f"  Pos drift:   <code>{drift * 100:.3f}%</code>\n"
            f"  WS reconn:   {ws_recon}  |  Cancels/min: {cancel_rate:.1f}"
        )

    snapshots = _load_all_snapshots()
    if snapshots:
        return "\n\n".join(_render(b, _snap_minute(s)) for b, s in snapshots.items()) or "No data."

    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if row:
            parts.append(_render(mf.parts[-5], row))
    return "\n\n".join(parts) or "No data."


def _build_help() -> str:
    return (
        "<b>hbot Trading Desk — Commands</b>\n\n"
        "/status  — bot state, regime, orders, tick age\n"
        "/go      — one-line GO/HOLD + blockers\n"
        "/orders [bot] [N] — active orders with side/price/age\n"
        "/desk    — global gates/strict/day2 status\n"
        "/pnl     — equity, daily PnL, realized PnL, fees\n"
        "/position — position, avg entry, exposure, margin\n"
        "/fills [N] — last N fills (default 5)\n"
        "/risk    — daily loss, drawdown, risk reasons, funding\n"
        "/help    — this message"
    )


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------

def run() -> None:
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes
    except ImportError:
        logger.error(
            "python-telegram-bot not installed. Run: pip install 'python-telegram-bot>=20.0'"
        )
        return

    if not _BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot start bot.")
        return

    allowed_id = _allowed_chat_id()
    if allowed_id is None:
        logger.warning(
            "TELEGRAM_CHAT_ID is not a numeric ID ('%s'). "
            "Bot will accept messages from ANY chat — set a numeric ID for security.",
            _CHAT_ID_RAW,
        )

    def _guard(chat_id: int) -> bool:
        if allowed_id is None:
            return True
        return chat_id == allowed_id

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_status())

    async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_pnl())

    async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        n = 20
        bot_filter: str | None = None
        if context.args:
            if len(context.args) == 1:
                arg = context.args[0].strip()
                if arg.isdigit():
                    n = max(1, min(50, int(arg)))
                else:
                    bot_filter = arg
            elif len(context.args) >= 2:
                bot_filter = context.args[0].strip()
                if context.args[1].strip().isdigit():
                    n = max(1, min(50, int(context.args[1].strip())))
        await _safe_reply_html(update.message, _build_orders(limit_per_bot=n, bot_filter=bot_filter))

    async def cmd_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_go())

    async def cmd_desk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_desk())

    async def cmd_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_position())

    async def cmd_fills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        n = 5
        if context.args:
            try:
                n = max(1, min(20, int(context.args[0])))
            except ValueError:
                pass
        await _safe_reply_html(update.message, _build_fills(n))

    async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_risk())

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await _safe_reply_html(update.message, _build_help())

    app = (
        Application.builder()
        .token(_BOT_TOKEN)
        .build()
    )

    import asyncio as _aio
    try:
        me = _aio.get_event_loop().run_until_complete(app.bot.get_me())
        logger.info("Telegram token verified — bot identity: @%s (id=%s)", me.username, me.id)
    except Exception:
        logger.error("Telegram token validation failed (getMe). Check TELEGRAM_BOT_TOKEN.", exc_info=True)
        return

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("go", cmd_go))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("desk", cmd_desk))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("position", cmd_position))
    app.add_handler(CommandHandler("fills", cmd_fills))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("help", cmd_help))

    import threading

    def _heartbeat_loop() -> None:
        while True:
            Path("/tmp/telegram_heartbeat").touch()
            time.sleep(60)

    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    logger.info(
        "Telegram command bot starting (data_root=%s, allowed_chat=%s)",
        _DATA_ROOT, _CHAT_ID_RAW or "ANY",
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
