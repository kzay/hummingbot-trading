"""Telegram command bot for the hbot trading desk.

Responds to commands in the configured chat, reading data directly from
minute.csv, fills.csv, and reports/ JSON files. No database required.

Commands:
    /status    — bot state, regime, orders, tick age
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

import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from services.common.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID_RAW = os.environ.get("TELEGRAM_CHAT_ID", "")
_DATA_ROOT = Path(os.environ.get("HB_DATA_ROOT", ""))
if not _DATA_ROOT or not _DATA_ROOT.is_absolute():
    _DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _allowed_chat_id() -> Optional[int]:
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


def _read_last_csv_row(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            last: Optional[Dict[str, str]] = None
            for row in reader:
                last = dict(row)
            return last
    except Exception:
        return None


def _read_last_n_csv_rows(path: Path, n: int) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows[-n:]
    except Exception:
        return []


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_minute_files() -> List[Path]:
    return sorted(_DATA_ROOT.glob("*/logs/epp_v24/*/minute.csv"))


def _find_fills_files() -> List[Path]:
    return sorted(_DATA_ROOT.glob("*/logs/epp_v24/*/fills.csv"))


def _state_emoji(state: str) -> str:
    return {"running": "✅", "soft_pause": "⏸", "hard_stop": "🛑"}.get(state, "❓")


def _pct(v: float) -> str:
    return f"{v * 100:.3f}%"


def _fmt_age(ts_str: str) -> str:
    if not ts_str:
        return "unknown"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age_s = int(time.time() - dt.timestamp())
        if age_s < 120:
            return f"{age_s}s ago"
        return f"{age_s // 60}m ago"
    except Exception:
        return ts_str


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _build_status() -> str:
    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found — is the bot running?"
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if not row:
            continue
        bot = mf.parts[-5]
        state = row.get("state", "?")
        regime = row.get("regime", "?")
        orders = int(_safe_float(row.get("orders_active")))
        risk = row.get("risk_reasons", "") or "none"
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
    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if not row:
            continue
        bot = mf.parts[-5]
        equity = _safe_float(row.get("equity_quote"))
        daily_loss = _safe_float(row.get("daily_loss_pct"))
        drawdown = _safe_float(row.get("drawdown_pct"))
        realized = _safe_float(row.get("realized_pnl_today_quote"))
        fees = _safe_float(row.get("fees_paid_today_quote"))
        fills = int(_safe_float(row.get("fills_count_today")))
        turnover = _safe_float(row.get("turnover_today_x"))

        pnl_sign = "+" if realized >= 0 else ""
        loss_sign = "+" if daily_loss >= 0 else ""
        parts.append(
            f"<b>{bot} PnL</b>\n"
            f"  Equity:    <code>{equity:.2f} USDT</code>\n"
            f"  Realized:  <code>{pnl_sign}{realized:.4f} USDT</code>\n"
            f"  Daily Δ:   <code>{loss_sign}{daily_loss * 100:.3f}%</code>\n"
            f"  Drawdown:  <code>{drawdown * 100:.3f}%</code>\n"
            f"  Fees paid: <code>{fees:.4f} USDT</code>\n"
            f"  Fills: {fills}  |  Turnover: {turnover:.2f}x"
        )
    return "\n\n".join(parts) or "No data."


def _build_position() -> str:
    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if not row:
            continue
        bot = mf.parts[-5]
        pos_base = _safe_float(row.get("position_base"))
        avg_entry = _safe_float(row.get("avg_entry_price"))
        base_pct = _safe_float(row.get("base_pct"))
        target_pct = _safe_float(row.get("target_base_pct"))
        net_base_pct = _safe_float(row.get("net_base_pct"))
        margin = _safe_float(row.get("margin_ratio"), 1.0)
        mid = _safe_float(row.get("mid"))
        notional = abs(pos_base) * mid if mid > 0 else 0.0
        pair = row.get("trading_pair", "?")

        direction = "LONG" if pos_base > 0 else ("SHORT" if pos_base < 0 else "FLAT")
        parts.append(
            f"<b>{bot} Position</b>\n"
            f"  {pair}: <code>{pos_base:+.6f}</code> ({direction})\n"
            f"  Notional:  <code>{notional:.2f} USDT</code>\n"
            f"  Avg entry: <code>{avg_entry:.2f}</code>  |  Mid: <code>{mid:.2f}</code>\n"
            f"  Base %:    <code>{_pct(base_pct)}</code> → target <code>{_pct(target_pct)}</code>\n"
            f"  Net %:     <code>{_pct(net_base_pct)}</code>\n"
            f"  Margin:    <code>{margin:.3f}</code>"
        )
    return "\n\n".join(parts) or "No data."


def _build_fills(n: int = 5) -> str:
    fills_files = _find_fills_files()
    if not fills_files:
        return "No fills.csv found."
    parts = []
    for ff in fills_files:
        bot = ff.parts[-5]
        rows = _read_last_n_csv_rows(ff, n)
        if not rows:
            parts.append(f"<b>{bot}</b>: no fills yet.")
            continue
        lines = [f"<b>{bot}</b> — last {len(rows)} fills:"]
        for row in reversed(rows):
            side = row.get("side", "?").upper()
            price = _safe_float(row.get("price"))
            amount = _safe_float(row.get("amount_base"))
            pnl = _safe_float(row.get("realized_pnl_quote"))
            is_maker = str(row.get("is_maker", "")).lower() == "true"
            ts = row.get("ts", "")[:16].replace("T", " ")
            role = "M" if is_maker else "T"
            pnl_str = f"  pnl={pnl:+.4f}" if pnl != 0 else ""
            lines.append(f"  {ts}  <code>{side:4s}</code> {amount:.6f} @ {price:.2f} [{role}]{pnl_str}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts) or "No data."


def _build_risk() -> str:
    minute_files = _find_minute_files()
    if not minute_files:
        return "No minute.csv found."
    parts = []
    for mf in minute_files:
        row = _read_last_csv_row(mf)
        if not row:
            continue
        bot = mf.parts[-5]
        daily_loss = _safe_float(row.get("daily_loss_pct"))
        drawdown = _safe_float(row.get("drawdown_pct"))
        risk_reasons = row.get("risk_reasons", "") or "none"
        funding = _safe_float(row.get("funding_rate"))
        margin = _safe_float(row.get("margin_ratio"), 1.0)
        drift = _safe_float(row.get("position_drift_pct"))
        ws_recon = int(_safe_float(row.get("ws_reconnect_count")))
        cancel_rate = _safe_float(row.get("cancel_per_min"))

        funding_bps = funding * 10000
        parts.append(
            f"<b>{bot} Risk</b>\n"
            f"  Daily loss:  <code>{daily_loss * 100:.3f}%</code>\n"
            f"  Drawdown:    <code>{drawdown * 100:.3f}%</code>\n"
            f"  Reasons:     <code>{risk_reasons}</code>\n"
            f"  Funding:     <code>{funding_bps:.2f} bps</code>\n"
            f"  Margin:      <code>{margin:.3f}</code>\n"
            f"  Pos drift:   <code>{drift * 100:.3f}%</code>\n"
            f"  WS reconn:   {ws_recon}  |  Cancels/min: {cancel_rate:.1f}"
        )
    return "\n\n".join(parts) or "No data."


def _build_help() -> str:
    return (
        "<b>hbot Trading Desk — Commands</b>\n\n"
        "/status  — bot state, regime, orders, tick age\n"
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
        await update.message.reply_html(_build_status())

    async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await update.message.reply_html(_build_pnl())

    async def cmd_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await update.message.reply_html(_build_position())

    async def cmd_fills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        n = 5
        if context.args:
            try:
                n = max(1, min(20, int(context.args[0])))
            except ValueError:
                pass
        await update.message.reply_html(_build_fills(n))

    async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await update.message.reply_html(_build_risk())

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _guard(update.effective_chat.id):
            return
        await update.message.reply_html(_build_help())

    app = (
        Application.builder()
        .token(_BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("position", cmd_position))
    app.add_handler(CommandHandler("fills", cmd_fills))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("help", cmd_help))

    logger.info(
        "Telegram command bot starting (data_root=%s, allowed_chat=%s)",
        _DATA_ROOT, _CHAT_ID_RAW or "ANY",
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
