from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from platform_lib.contracts.event_schemas import PaperExchangeEvent
from services.paper_exchange_service.models import (
    FundingSettlementCandidate, OrderRecord, PairSnapshot, PaperExchangeState, PositionRecord,
)

logger = logging.getLogger(__name__)

_MIN_FILL_EPSILON = 1e-12


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_connector_name(value: str) -> str:
    from services.paper_exchange_service.main import _normalize_connector_name as _nc
    return _nc(value)


def _namespace_base_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return (
        f"{_normalize(instance_name)}::"
        f"{_normalize_connector_name(connector_name)}::"
        f"{str(trading_pair or '').strip().upper()}"
    )


def _D(v: object) -> Decimal:
    """Convert to Decimal via string for exact intermediate arithmetic."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _positive_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _snapshot_best_bid(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_bid)


def _snapshot_best_ask(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_ask)


def _snapshot_best_bid_size(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_bid_size)


def _snapshot_best_ask_size(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_ask_size)


def _remaining_amount_base(order: OrderRecord) -> float:
    return max(0.0, float(order.amount_base) - float(order.filled_base))


def _position_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return _namespace_base_key(instance_name, connector_name, trading_pair)


def _get_or_create_position(state: PaperExchangeState, order: OrderRecord) -> PositionRecord:
    key = _position_key(order.instance_name, order.connector_name, order.trading_pair)
    position = state.positions_by_key.get(key)
    if position is not None:
        return position
    position = PositionRecord(
        instance_name=order.instance_name,
        connector_name=order.connector_name,
        trading_pair=order.trading_pair,
        position_mode=str(order.position_mode or "ONEWAY").upper() or "ONEWAY",
    )
    state.positions_by_key[key] = position
    return position


def _round_positive(value: float) -> float:
    return max(0.0, float(value))


def _open_long(position: PositionRecord, quantity: float, price: float) -> None:
    qty = _round_positive(quantity)
    if qty <= _MIN_FILL_EPSILON:
        return
    px = max(0.0, float(price))
    existing_qty = _round_positive(position.long_base)
    if existing_qty <= _MIN_FILL_EPSILON or position.long_avg_entry_price <= 0:
        position.long_base = qty
        position.long_avg_entry_price = px
        return
    d_total = _D(existing_qty) + _D(qty)
    position.long_avg_entry_price = float((_D(existing_qty) * _D(position.long_avg_entry_price) + _D(qty) * _D(px)) / d_total)
    position.long_base = float(d_total)


def _open_short(position: PositionRecord, quantity: float, price: float) -> None:
    qty = _round_positive(quantity)
    if qty <= _MIN_FILL_EPSILON:
        return
    px = max(0.0, float(price))
    existing_qty = _round_positive(position.short_base)
    if existing_qty <= _MIN_FILL_EPSILON or position.short_avg_entry_price <= 0:
        position.short_base = qty
        position.short_avg_entry_price = px
        return
    d_total = _D(existing_qty) + _D(qty)
    position.short_avg_entry_price = float((_D(existing_qty) * _D(position.short_avg_entry_price) + _D(qty) * _D(px)) / d_total)
    position.short_base = float(d_total)


def _close_long(position: PositionRecord, quantity: float, price: float) -> float:
    qty = min(_round_positive(quantity), _round_positive(position.long_base))
    if qty <= _MIN_FILL_EPSILON:
        return 0.0
    realized = float(_D(qty) * (_D(price) - _D(position.long_avg_entry_price)))
    position.long_base = max(0.0, float(_D(position.long_base) - _D(qty)))
    if position.long_base <= _MIN_FILL_EPSILON:
        position.long_base = 0.0
        position.long_avg_entry_price = 0.0
    position.realized_pnl_quote = float(_D(position.realized_pnl_quote) + _D(realized))
    return qty


def _close_short(position: PositionRecord, quantity: float, price: float) -> float:
    qty = min(_round_positive(quantity), _round_positive(position.short_base))
    if qty <= _MIN_FILL_EPSILON:
        return 0.0
    realized = float(_D(qty) * (_D(position.short_avg_entry_price) - _D(price)))
    position.short_base = max(0.0, float(_D(position.short_base) - _D(qty)))
    if position.short_base <= _MIN_FILL_EPSILON:
        position.short_base = 0.0
        position.short_avg_entry_price = 0.0
    position.realized_pnl_quote = float(_D(position.realized_pnl_quote) + _D(realized))
    return qty


def _is_flat_position(position: PositionRecord) -> bool:
    return _round_positive(position.long_base) <= _MIN_FILL_EPSILON and _round_positive(position.short_base) <= _MIN_FILL_EPSILON


def _sanitize_oneway_positions(positions: dict[str, PositionRecord]) -> int:
    """Collapse dual-leg ONEWAY positions to a single net leg on startup.

    Returns the number of positions repaired.
    """
    repaired = 0
    for key, pos in positions.items():
        mode = str(pos.position_mode or "ONEWAY").strip().upper()
        if "HEDGE" in mode:
            continue
        long_qty = _round_positive(pos.long_base)
        short_qty = _round_positive(pos.short_base)
        if long_qty <= _MIN_FILL_EPSILON or short_qty <= _MIN_FILL_EPSILON:
            continue
        net = float(_D(long_qty) - _D(short_qty))
        if net > _MIN_FILL_EPSILON:
            pos.long_base = net
            pos.short_base = 0.0
            pos.short_avg_entry_price = 0.0
        elif net < -_MIN_FILL_EPSILON:
            pos.short_base = abs(net)
            pos.long_base = 0.0
            pos.long_avg_entry_price = 0.0
        else:
            pos.long_base = 0.0
            pos.short_base = 0.0
            pos.long_avg_entry_price = 0.0
            pos.short_avg_entry_price = 0.0
        logger.warning(
            "ONEWAY_SANITIZE key=%s: collapsed dual-leg (long=%.8f short=%.8f) -> net=%.8f",
            key, long_qty, short_qty, net,
        )
        repaired += 1
    return repaired


def _preview_fill_realized_pnl(
    state: PaperExchangeState,
    order: OrderRecord,
    fill_amount_base: float,
    fill_price: float,
) -> float:
    """Pre-compute the realized PnL a fill would produce without mutating state."""
    key = _position_key(order.instance_name, order.connector_name, order.trading_pair)
    position = state.positions_by_key.get(key)
    if position is None:
        return 0.0
    qty = _round_positive(fill_amount_base)
    if qty <= _MIN_FILL_EPSILON:
        return 0.0
    side = _normalize(order.side)
    action = _normalize(order.position_action or "auto")
    mode = str(order.position_mode or "ONEWAY").strip().upper() or "ONEWAY"
    reduce_only = bool(order.reduce_only)
    if mode != "HEDGE" and action in ("open_long", "open_short", "close_long", "close_short"):
        action = "auto"
    realized = 0.0
    if mode == "HEDGE":
        if side == "buy" and (action == "close_short" or reduce_only):
            close_qty = min(qty, _round_positive(position.short_base))
            if close_qty > _MIN_FILL_EPSILON:
                realized = float(_D(close_qty) * (_D(position.short_avg_entry_price) - _D(fill_price)))
        elif side == "sell" and (action == "close_long" or reduce_only):
            close_qty = min(qty, _round_positive(position.long_base))
            if close_qty > _MIN_FILL_EPSILON:
                realized = float(_D(close_qty) * (_D(fill_price) - _D(position.long_avg_entry_price)))
    else:
        if side == "buy" and action != "open_long":
            close_qty = min(qty, _round_positive(position.short_base))
            if close_qty > _MIN_FILL_EPSILON:
                realized = float(_D(close_qty) * (_D(position.short_avg_entry_price) - _D(fill_price)))
        elif side == "sell" and action != "open_short":
            close_qty = min(qty, _round_positive(position.long_base))
            if close_qty > _MIN_FILL_EPSILON:
                realized = float(_D(close_qty) * (_D(fill_price) - _D(position.long_avg_entry_price)))
    return realized


def _apply_position_fill(
    *,
    state: PaperExchangeState,
    order: OrderRecord,
    fill_amount_base: float,
    fill_price: float,
    now_ms: int,
) -> None:
    qty = _round_positive(fill_amount_base)
    if qty <= _MIN_FILL_EPSILON:
        return
    position = _get_or_create_position(state, order)
    was_flat = _is_flat_position(position)
    side = _normalize(order.side)
    action = _normalize(order.position_action or "auto")
    mode = str(order.position_mode or "ONEWAY").strip().upper() or "ONEWAY"
    reduce_only = bool(order.reduce_only)
    if mode != "HEDGE" and action in ("open_long", "open_short", "close_long", "close_short"):
        action = "auto"

    if mode == "HEDGE":
        if side == "buy":
            if action == "close_short" or reduce_only:
                _close_short(position, qty, fill_price)
            else:
                _open_long(position, qty, fill_price)
        elif side == "sell":
            if action == "close_long" or reduce_only:
                _close_long(position, qty, fill_price)
            else:
                _open_short(position, qty, fill_price)
    else:
        remaining = qty
        if side == "buy":
            if action == "open_long":
                _open_long(position, remaining, fill_price)
                remaining = 0.0
            elif action == "close_short":
                _close_short(position, remaining, fill_price)
                remaining = 0.0
            else:
                closed = _close_short(position, remaining, fill_price)
                remaining = max(0.0, remaining - closed)
                if not reduce_only and remaining > _MIN_FILL_EPSILON:
                    _open_long(position, remaining, fill_price)
        elif side == "sell":
            if action == "open_short":
                _open_short(position, remaining, fill_price)
                remaining = 0.0
            elif action == "close_long":
                _close_long(position, remaining, fill_price)
                remaining = 0.0
            else:
                closed = _close_long(position, remaining, fill_price)
                remaining = max(0.0, remaining - closed)
                if not reduce_only and remaining > _MIN_FILL_EPSILON:
                    _open_short(position, remaining, fill_price)

    position.position_mode = mode
    position.last_fill_ts_ms = max(0, int(now_ms))
    if was_flat and not _is_flat_position(position):
        position.last_funding_ts_ms = max(0, int(now_ms))


def _funding_summary(state: PaperExchangeState) -> dict[str, object]:
    return {
        "positions_with_exposure": sum(1 for position in state.positions_by_key.values() if not _is_flat_position(position)),
        "funding_events_generated": int(state.funding_events_generated),
        "funding_debit_events": int(state.funding_debit_events),
        "funding_credit_events": int(state.funding_credit_events),
        "funding_paid_quote_total": float(state.funding_paid_quote_total),
    }


def _funding_events_for_snapshot(
    *,
    state: PaperExchangeState,
    snapshot: PairSnapshot,
    funding_interval_ms: int,
    now_ms: int,
) -> list[FundingSettlementCandidate]:
    interval_ms = max(1_000, int(funding_interval_ms))
    price_reference = max(
        0.0,
        float(snapshot.mark_price or 0.0) or float(snapshot.mid_price or 0.0),
    )
    if price_reference <= 0.0:
        return []
    funding_rate = float(snapshot.funding_rate or 0.0)
    if funding_rate == 0.0:
        return []
    candidates: list[FundingSettlementCandidate] = []
    matching_positions = [
        (position_key, position)
        for position_key, position in state.positions_by_key.items()
        if _normalize_connector_name(position.connector_name) == _normalize_connector_name(snapshot.connector_name)
        and str(position.trading_pair or "").strip().upper() == str(snapshot.trading_pair or "").strip().upper()
        and (
            not str(snapshot.instance_name or "").strip()
            or _normalize(position.instance_name) == _normalize(snapshot.instance_name)
        )
    ]
    for position_key, position in matching_positions:
        if _is_flat_position(position):
            position.last_funding_ts_ms = max(position.last_funding_ts_ms, int(now_ms))
            continue
        last_funding_ts_ms = max(0, int(position.last_funding_ts_ms))
        if last_funding_ts_ms <= 0:
            position.last_funding_ts_ms = int(now_ms)
            continue
        if (int(now_ms) - last_funding_ts_ms) < interval_ms:
            continue
        for leg_side, quantity, avg_entry_price, direction in (
            ("long", float(position.long_base), float(position.long_avg_entry_price), 1.0),
            ("short", float(position.short_base), float(position.short_avg_entry_price), -1.0),
        ):
            qty = _round_positive(quantity)
            if qty <= _MIN_FILL_EPSILON:
                continue
            reference_price = max(0.0, price_reference or avg_entry_price)
            if reference_price <= 0.0:
                continue
            notional_quote = float(_D(qty) * _D(reference_price))
            charge_quote = float(_D(funding_rate) * _D(notional_quote) * _D(direction))
            if abs(charge_quote) <= _MIN_FILL_EPSILON:
                continue
            cumulative_funding_quote = float(_D(position.funding_paid_quote) + _D(charge_quote))
            event_id = (
                f"pe-funding-{position.instance_name}-{snapshot.connector_name}-{snapshot.trading_pair}-"
                f"{leg_side}-{int(now_ms)}"
            )
            event = PaperExchangeEvent(
                producer="paper_exchange_service",
                event_id=event_id,
                correlation_id=event_id,
                instance_name=position.instance_name,
                command_event_id=event_id,
                command="funding_settlement",
                status="processed",
                reason="periodic_funding_settlement",
                connector_name=snapshot.connector_name,
                trading_pair=snapshot.trading_pair,
                position_mode=position.position_mode,
                metadata={
                    "leg_side": leg_side,
                    "funding_rate": str(funding_rate),
                    "charge_quote": str(charge_quote),
                    "reference_price": str(reference_price),
                    "position_base": str(qty),
                    "position_notional_quote": str(notional_quote),
                    "long_base": str(position.long_base),
                    "short_base": str(position.short_base),
                    "realized_pnl_quote": str(position.realized_pnl_quote),
                    "funding_paid_quote_total": str(cumulative_funding_quote),
                    "settlement_interval_ms": str(interval_ms),
                    "last_funding_ts_ms": str(last_funding_ts_ms),
                    "current_funding_ts_ms": str(int(now_ms)),
                    "snapshot_event_id": str(snapshot.event_id or ""),
                },
            )
            candidates.append(
                FundingSettlementCandidate(
                    position_key=position_key,
                    leg_side=leg_side,
                    funding_rate=funding_rate,
                    charge_quote=charge_quote,
                    reference_price=reference_price,
                    position_base=qty,
                    position_notional_quote=notional_quote,
                    last_funding_ts_ms=last_funding_ts_ms,
                    current_funding_ts_ms=int(now_ms),
                    event=event,
                )
            )
    return candidates


def _commit_funding_settlement(state: PaperExchangeState, candidate: FundingSettlementCandidate) -> None:
    position = state.positions_by_key.get(candidate.position_key)
    if position is None:
        return
    position.funding_paid_quote = float(_D(position.funding_paid_quote) + _D(candidate.charge_quote))
    position.last_funding_rate = float(candidate.funding_rate)
    position.funding_event_count += 1
    position.last_funding_ts_ms = int(candidate.current_funding_ts_ms)
    state.funding_events_generated += 1
    if float(candidate.charge_quote) > 0.0:
        state.funding_debit_events += 1
    else:
        state.funding_credit_events += 1
    state.funding_paid_quote_total = float(_D(state.funding_paid_quote_total) + _D(candidate.charge_quote))
