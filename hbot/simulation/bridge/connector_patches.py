"""Connector patching utilities for paper exchange bridge.

Patches HB connector objects to route balance, order, and position queries
through the PaperDesk simulation layer.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from types import MethodType, SimpleNamespace
from typing import Any

from simulation.types import (
    InstrumentId,
    PositionAction,
)


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

try:
    from simulation.desk import PaperDesk
except ImportError:
    PaperDesk = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

def _patch_connector_balances(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Patch connector.get_balance / get_available_balance to return paper portfolio values."""
    if getattr(connector, "_epp_v2_balance_patched", False):
        return
    try:
        if not hasattr(connector, "_paper_desk_v2"):
            connector._paper_desk_v2 = desk
        if not hasattr(connector, "_paper_desk_v2_instrument_id"):
            connector._paper_desk_v2_instrument_id = iid

        if not hasattr(connector, "_epp_v2_orig_get_balance") and hasattr(connector, "get_balance"):
            connector._epp_v2_orig_get_balance = connector.get_balance
        if not hasattr(connector, "_epp_v2_orig_get_available_balance") and hasattr(connector, "get_available_balance"):
            connector._epp_v2_orig_get_available_balance = connector.get_available_balance
        if not hasattr(connector, "_epp_v2_orig_ready") and hasattr(connector, "ready"):
            connector._epp_v2_orig_ready = connector.ready
        if not hasattr(connector, "_epp_v2_orig_get_position") and hasattr(connector, "get_position"):
            connector._epp_v2_orig_get_position = connector.get_position
        if not hasattr(connector, "_epp_v2_orig_account_positions") and hasattr(connector, "account_positions"):
            connector._epp_v2_orig_account_positions = connector.account_positions

        def _paper_balance(asset: str) -> Decimal:
            return desk.portfolio.balance(asset)

        def _paper_available(asset: str) -> Decimal:
            return desk.portfolio.available(asset)

        def _patched_get_balance(self, asset: str) -> Decimal:
            try:
                return _paper_balance(asset)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_balance", None)
                return orig(asset) if callable(orig) else Decimal("0")

        def _patched_get_available_balance(self, asset: str) -> Decimal:
            try:
                return _paper_available(asset)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_available_balance", None)
                return orig(asset) if callable(orig) else Decimal("0")

        def _patched_ready(self) -> bool:
            return True

        def _paper_position_obj(position_action: Any = None):
            resolved_action = _normalize_position_action_hint(position_action)
            pos = desk.portfolio.get_position(iid, position_action=resolved_action)
            amount = pos.quantity
            entry_price = pos.avg_entry_price
            if resolved_action in {PositionAction.OPEN_LONG, PositionAction.CLOSE_LONG}:
                amount = pos.long_quantity
                entry_price = pos.long_avg_entry_price
            elif resolved_action in {PositionAction.OPEN_SHORT, PositionAction.CLOSE_SHORT}:
                amount = -pos.short_quantity
                entry_price = pos.short_avg_entry_price
            return SimpleNamespace(
                trading_pair=iid.trading_pair,
                amount=amount,
                entry_price=entry_price,
            )

        def _patched_get_position(self, trading_pair: str | None = None, *args, **kwargs):
            try:
                if trading_pair and str(trading_pair) != str(iid.trading_pair):
                    orig = getattr(self, "_epp_v2_orig_get_position", None)
                    return orig(trading_pair, *args, **kwargs) if callable(orig) else None
                position_action = kwargs.get("position_action") or kwargs.get("position_side")
                return _paper_position_obj(position_action)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_position", None)
                return orig(trading_pair, *args, **kwargs) if callable(orig) else None

        def _patched_account_positions(self, *args, **kwargs):
            try:
                net_pos = desk.portfolio.get_position(iid)
                return {
                    iid.trading_pair: {
                        "amount": net_pos.quantity,
                        "long_amount": net_pos.long_quantity,
                        "short_amount": -net_pos.short_quantity,
                    }
                }
            except Exception:
                orig = getattr(self, "_epp_v2_orig_account_positions", None)
                return orig(*args, **kwargs) if callable(orig) else {}

        if hasattr(connector, "get_balance"):
            connector.get_balance = MethodType(_patched_get_balance, connector)
        if hasattr(connector, "get_available_balance"):
            connector.get_available_balance = MethodType(_patched_get_available_balance, connector)
        if hasattr(connector, "ready"):
            connector.ready = MethodType(_patched_ready, connector)
        if hasattr(connector, "get_position"):
            connector.get_position = MethodType(_patched_get_position, connector)
        if hasattr(connector, "account_positions"):
            connector.account_positions = MethodType(_patched_account_positions, connector)

        connector._paper_desk_v2_get_balance = _paper_balance
        connector._paper_desk_v2_get_available = _paper_available
        connector._epp_v2_balance_patched = True
        logger.debug("Connector balance reads patched for v2 portfolio")
    except Exception as exc:
        logger.debug("Balance patch failed (non-critical): %s", exc)


def _patch_connector_open_orders(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Patch connector.get_open_orders() to return PaperDesk orders in connector-compatible format."""
    if getattr(connector, "_epp_v2_open_orders_patched", False):
        return
    try:
        if not hasattr(connector, "_epp_v2_orig_get_open_orders") and hasattr(connector, "get_open_orders"):
            connector._epp_v2_orig_get_open_orders = connector.get_open_orders

        def _patched_get_open_orders(self) -> list:
            try:
                engine = getattr(desk, "_engines", {}).get(iid.key)
                if engine is None:
                    return []
                open_orders_fn = getattr(engine, "open_orders", None)
                if not callable(open_orders_fn):
                    return []
                result: list = []
                working = list(open_orders_fn() or [])
                for inflight in list(getattr(engine, "_inflight", []) or []):
                    if not isinstance(inflight, tuple) or len(inflight) < 3:
                        continue
                    _due_ns, action, order = inflight
                    if str(action or "").lower() == "accept":
                        working.append(order)
                for order in working:
                    side_val = getattr(getattr(order, "side", None), "value", str(getattr(order, "side", "")))
                    trade_type_str = "BUY" if str(side_val).lower() == "buy" else "SELL"
                    remaining = order.quantity - order.filled_quantity
                    result.append(SimpleNamespace(
                        client_order_id=order.order_id,
                        trading_pair=iid.trading_pair,
                        price=order.price,
                        amount=order.quantity,
                        quantity=order.quantity,
                        executed_amount_base=order.filled_quantity,
                        remaining_amount=remaining,
                        trade_type=SimpleNamespace(name=trade_type_str),
                        order_type=SimpleNamespace(name=str(getattr(order.order_type, "value", "LIMIT")).upper()),
                        is_open=order.is_open,
                        creation_timestamp=order.created_at_ns / 1e9,
                        source_bot=getattr(order, "source_bot", ""),
                    ))
                return result
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_open_orders", None)
                return list(orig() or []) if callable(orig) else []

        connector.get_open_orders = MethodType(_patched_get_open_orders, connector)
        connector._epp_v2_open_orders_patched = True
        logger.debug("Connector get_open_orders patched for v2 desk")
    except Exception as exc:
        logger.debug("Open-orders patch failed (non-critical): %s", exc)


def _patch_connector_trading_rules(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Inject PaperDesk InstrumentSpec into connector.trading_rules for unified order sizing."""
    if getattr(connector, "_epp_v2_trading_rules_patched", False):
        return
    try:
        spec = desk._specs.get(iid.key)
        if spec is None:
            return
        trading_rules = getattr(connector, "trading_rules", None)
        if trading_rules is None:
            connector.trading_rules = {}
            trading_rules = connector.trading_rules
        if not isinstance(trading_rules, dict):
            return
        if iid.trading_pair not in trading_rules:
            collateral_token = iid.quote_asset
            trading_rules[iid.trading_pair] = SimpleNamespace(
                trading_pair=iid.trading_pair,
                min_order_size=spec.min_quantity,
                min_base_amount=spec.min_quantity,
                min_base_amount_increment=spec.size_increment,
                min_price_increment=spec.price_increment,
                min_notional_size=spec.min_notional,
                max_order_size=spec.max_quantity,
                min_amount=spec.min_quantity,
                buy_order_collateral_token=collateral_token,
                sell_order_collateral_token=collateral_token,
            )
        connector._epp_v2_trading_rules_patched = True
        logger.debug("Connector trading_rules patched for v2 desk spec %s", iid.trading_pair)
    except Exception as exc:
        logger.debug("Trading-rules patch failed (non-critical): %s", exc)


def _install_portfolio_snapshot(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Add connector.paper_portfolio_snapshot(mid) for unified equity/position/PnL access."""
    if getattr(connector, "_epp_v2_portfolio_snapshot_installed", False):
        return
    try:
        def _paper_portfolio_snapshot(mid: Decimal) -> dict[str, Decimal] | None:
            portfolio = desk.portfolio
            if portfolio is None:
                return None
            get_pos = getattr(portfolio, "get_position", None)
            if not callable(get_pos):
                return None
            pos = get_pos(iid)
            if pos is None:
                return None
            snapshot: dict[str, Decimal] = {
                "position_base": Decimal(str(getattr(pos, "quantity", _ZERO))),
                "position_gross_base": Decimal(str(getattr(pos, "gross_quantity", abs(getattr(pos, "quantity", _ZERO))))),
                "position_long_base": Decimal(str(getattr(pos, "long_quantity", max(_ZERO, getattr(pos, "quantity", _ZERO))))),
                "position_short_base": Decimal(str(getattr(pos, "short_quantity", max(_ZERO, -Decimal(str(getattr(pos, "quantity", _ZERO))))))),
                "position_mode": str(getattr(pos, "position_mode", "ONEWAY") or "ONEWAY").upper(),
                "avg_entry_price": Decimal(str(getattr(pos, "avg_entry_price", _ZERO))),
                "avg_entry_price_long": Decimal(str(getattr(pos, "long_avg_entry_price", _ZERO))),
                "avg_entry_price_short": Decimal(str(getattr(pos, "short_avg_entry_price", _ZERO))),
                "unrealized_pnl": Decimal(str(getattr(pos, "unrealized_pnl", _ZERO))),
                "realized_pnl": Decimal(str(getattr(pos, "realized_pnl", _ZERO))),
                "daily_open_equity": Decimal(str(getattr(portfolio, "daily_open_equity", _ZERO) or _ZERO)),
                "equity_quote": _ZERO,
            }
            if hasattr(portfolio, "equity_quote"):
                try:
                    quote_asset = iid.quote_asset
                    mid_d = Decimal(str(mid))
                    eq = portfolio.equity_quote({iid.key: mid_d}, quote_asset=quote_asset)
                    snapshot["equity_quote"] = Decimal(str(eq))
                except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
                    pass
            return snapshot

        connector.paper_portfolio_snapshot = _paper_portfolio_snapshot
        connector._epp_v2_portfolio_snapshot_installed = True
        logger.debug("paper_portfolio_snapshot installed on connector")
    except Exception as exc:
        logger.debug("portfolio_snapshot install failed (non-critical): %s", exc)


def _install_paper_stats(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Add paper_stats property to connector so ProcessedState can read fill counts."""
    if getattr(connector, "_epp_v2_paper_stats_installed", False):
        return
    try:
        def _paper_stats() -> dict[str, Decimal]:
            return desk.paper_stats(iid)

        connector.paper_stats = _paper_stats
        connector._epp_v2_paper_stats_installed = True
        logger.debug("paper_stats property installed on connector")
    except Exception as exc:
        logger.debug("paper_stats install failed (non-critical): %s", exc)


