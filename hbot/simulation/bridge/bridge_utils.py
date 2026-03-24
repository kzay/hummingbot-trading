"""Pure utility functions for the Hummingbot bridge.

Stateless helpers for name normalization, type conversion, and formatting.
No business logic or external state — safe to import from any bridge module.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from simulation.types import OrderSide, PaperOrderType, PositionAction

# CONCURRENCY: read/written from main event loop only (single-threaded bridge tick).
# If _canonical_name() is ever called from _REDIS_IO_POOL threads, add a Lock.
_CANONICAL_CACHE: dict[str, str] = {}


def _canonical_name(connector_name: str) -> str:
    if connector_name in _CANONICAL_CACHE:
        return _CANONICAL_CACHE[connector_name]
    if not str(connector_name).endswith("_paper_trade"):
        return connector_name
    try:
        from platform_lib.market_data.exchange_profiles import resolve_profile

        profile = resolve_profile(connector_name)
        if isinstance(profile, dict):
            req = profile.get("requires_paper_trade_exchange")
            if isinstance(req, str) and req:
                _CANONICAL_CACHE[connector_name] = req
                return req
    except (ImportError, KeyError, AttributeError, TypeError):
        pass
    result = connector_name[:-12]
    _CANONICAL_CACHE[connector_name] = result
    return result


def _instance_env_suffix(instance_name: str) -> str:
    raw = str(instance_name or "").strip().upper()
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _parse_env_bool(raw_value: str, *, default: bool = False) -> bool:
    value = str(raw_value or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _order_type_text(order_type: Any) -> str:
    return str(getattr(order_type, "name", order_type) or "").upper()


def _normalize_position_action(position_action: Any, side: OrderSide) -> PositionAction:
    if isinstance(position_action, PositionAction):
        return position_action
    text = str(getattr(position_action, "name", position_action) or "").strip().lower()
    if text in {"open_long", "open"} and side == OrderSide.BUY:
        return PositionAction.OPEN_LONG
    if text in {"close_short", "close"} and side == OrderSide.BUY:
        return PositionAction.CLOSE_SHORT
    if text in {"open_short", "open"} and side == OrderSide.SELL:
        return PositionAction.OPEN_SHORT
    if text in {"close_long", "close"} and side == OrderSide.SELL:
        return PositionAction.CLOSE_LONG
    return PositionAction.AUTO


def _normalize_position_action_hint(position_action: Any) -> PositionAction | None:
    if position_action is None:
        return None
    if isinstance(position_action, PositionAction):
        return position_action
    text = str(getattr(position_action, "name", position_action) or "").strip().lower()
    mapping = {
        "open_long": PositionAction.OPEN_LONG,
        "close_long": PositionAction.CLOSE_LONG,
        "open_short": PositionAction.OPEN_SHORT,
        "close_short": PositionAction.CLOSE_SHORT,
        "auto": PositionAction.AUTO,
    }
    return mapping.get(text)


def _hb_order_type_to_v2(hb_order_type: Any) -> PaperOrderType:
    """Convert HB OrderType to PaperOrderType."""
    ot_str = str(getattr(hb_order_type, "name", str(hb_order_type))).upper()
    if "MAKER" in ot_str or "LIMIT_MAKER" in ot_str:
        return PaperOrderType.LIMIT_MAKER
    if "MARKET" in ot_str:
        return PaperOrderType.MARKET
    return PaperOrderType.LIMIT


def _fmt_contract_decimal(value: Any) -> str:
    try:
        if value is None:
            return ""
        parsed = Decimal(str(value))
        if parsed.is_nan():
            return ""
        return format(parsed, "f")
    except Exception:
        return ""
