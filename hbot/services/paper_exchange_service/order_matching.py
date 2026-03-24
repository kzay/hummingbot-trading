from __future__ import annotations

import logging
import time
from decimal import Decimal

from platform_lib.contracts.event_schemas import (
    AuditEvent,
    PaperExchangeCommandEvent,
    PaperExchangeEvent,
)
from services.paper_exchange_service.models import (
    FillCandidate,
    OrderRecord,
    PairSnapshot,
    PaperExchangeState,
    ServiceSettings,
)
from services.paper_exchange_service.order_fsm import (
    ACTIVE_ORDER_STATES as _ACTIVE_ORDER_STATES,
    TERMINAL_ORDER_STATES as _TERMINAL_ORDER_STATES,
    can_transition_state,
    is_immediate_tif,
    resolve_crossing_limit_order_outcome,
)
from services.paper_exchange_service.position_accounting import (
    _apply_position_fill,
    _calc_fill_fee_quote,
    _calc_margin_reserve_quote,
    _fee_rate_for_fill,
    _get_or_create_position,
    _preview_fill_realized_pnl,
    _remaining_amount_base,
    _snapshot_best_ask,
    _snapshot_best_bid,
)

logger = logging.getLogger(__name__)


_SUPPORTED_TIME_IN_FORCE = {"gtc", "ioc", "fok"}
_MIN_FILL_EPSILON = 1e-12
_PRIVILEGED_COMMANDS = {"cancel_all"}
_PRIVILEGED_METADATA_FIELDS = ("operator", "reason", "change_ticket", "trace_id")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


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


def _snapshot_best_bid_size(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_bid_size)


def _snapshot_best_ask_size(snapshot: PairSnapshot | None) -> float | None:
    return _positive_or_none(None if snapshot is None else snapshot.best_ask_size)


def _normalize_connector_name(value: str) -> str:
    from services.paper_exchange_service.main import _canonical_connector_name
    return _normalize(_canonical_connector_name(value))


def _is_privileged_command(command_name: str) -> bool:
    return _normalize(command_name) in _PRIVILEGED_COMMANDS


def _missing_privileged_metadata(metadata: dict[str, str]) -> list[str]:
    return [key for key in _PRIVILEGED_METADATA_FIELDS if not str(metadata.get(key, "")).strip()]


def _bool_from_record(record: dict[str, object], key: str, default: bool) -> bool:
    raw = record.get(key)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _build_privileged_audit_event(
    *,
    command: PaperExchangeCommandEvent,
    result_status: str,
    result_reason: str,
    command_metadata: dict[str, str],
) -> AuditEvent:
    status_norm = _normalize(result_status or "")
    severity = "warning" if status_norm != "processed" else "info"
    reason_norm = str(result_reason or "").strip() or "unknown"
    cmd = str(command.command or "").strip() or "unknown"
    return AuditEvent(
        producer="paper_exchange_service",
        instance_name=command.instance_name,
        correlation_id=command.event_id,
        severity=severity,
        category="paper_exchange_privileged_command",
        message=f"{cmd} {status_norm or 'processed'} ({reason_norm})",
        metadata={
            "command_event_id": str(command.event_id or ""),
            "command": cmd,
            "result_status": str(result_status or ""),
            "result_reason": reason_norm,
            "connector_name": str(command.connector_name or ""),
            "trading_pair": str(command.trading_pair or ""),
            "order_id": str(command.order_id or ""),
            "producer": str(command.producer or ""),
            "operator": str(command_metadata.get("operator", "")).strip(),
            "change_ticket": str(command_metadata.get("change_ticket", "")).strip(),
            "reason": str(command_metadata.get("reason", "")).strip(),
            "trace_id": str(command_metadata.get("trace_id", "")).strip(),
        },
    )


def _entry_sequence_from_stream_id(entry_id: str) -> int:
    text = str(entry_id or "").strip()
    if "-" not in text:
        return 0
    ms_part, seq_part = text.split("-", 1)
    try:
        ms = int(ms_part)
        seq = int(seq_part)
    except Exception:
        return 0
    # Deterministic sortable scalar for command stream ordering.
    return max(0, ms) * 1_000_000 + max(0, seq)


def _parse_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_time_in_force(metadata: dict[str, str]) -> str:
    tif = str(metadata.get("time_in_force", "gtc")).strip().lower()
    return tif if tif in _SUPPORTED_TIME_IN_FORCE else ""


def _try_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _decimal_from_metadata(metadata: dict[str, str], key: str) -> Decimal | None:
    raw = metadata.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _is_multiple_of_increment(value: Decimal, increment: Decimal) -> bool:
    if increment <= Decimal("0"):
        return True
    try:
        remainder = value % increment
    except Exception:
        return False
    return remainder == 0


def _validate_order_constraints(
    *,
    metadata: dict[str, str],
    order_type: str,
    amount_base: float,
    price: float | None,
    market_reference_price: float | None,
) -> tuple[str, dict[str, str]] | None:
    min_quantity = _decimal_from_metadata(metadata, "min_quantity") or Decimal("0")
    size_increment = _decimal_from_metadata(metadata, "size_increment") or Decimal("0")
    price_increment = _decimal_from_metadata(metadata, "price_increment") or Decimal("0")
    min_notional = _decimal_from_metadata(metadata, "min_notional") or Decimal("0")
    amount_dec = Decimal(str(amount_base))
    reference_price = market_reference_price if order_type == "market" else price
    price_dec = Decimal(str(reference_price)) if reference_price is not None else None

    if min_quantity > 0 and amount_dec < min_quantity:
        return (
            "below_min_quantity",
            {
                "amount_base": str(amount_dec),
                "min_quantity": str(min_quantity),
            },
        )
    if size_increment > 0 and not _is_multiple_of_increment(amount_dec, size_increment):
        return (
            "invalid_size_increment",
            {
                "amount_base": str(amount_dec),
                "size_increment": str(size_increment),
            },
        )
    if order_type != "market" and price_dec is not None and price_increment > 0 and not _is_multiple_of_increment(price_dec, price_increment):
        return (
            "invalid_price_increment",
            {
                "price": str(price_dec),
                "price_increment": str(price_increment),
            },
        )
    if min_notional > 0 and price_dec is not None and (amount_dec * price_dec) < min_notional:
        return (
            "below_min_notional",
            {
                "notional_quote": str(amount_dec * price_dec),
                "min_notional": str(min_notional),
            },
        )
    return None


def _coerce_margin_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"leveraged", "standard"} else "leveraged"


def _resolve_accounting_contract(
    metadata: dict[str, str],
    *,
    pair_snapshot: PairSnapshot | None,
) -> tuple[float, float, float, str, float]:
    maker_fee_pct = _try_float(metadata.get("maker_fee_pct"))
    taker_fee_pct = _try_float(metadata.get("taker_fee_pct"))
    fallback_fee_pct = _try_float(metadata.get("fee_pct"))
    if fallback_fee_pct is None:
        fallback_fee_pct = _try_float(metadata.get("spot_fee_pct"))

    if maker_fee_pct is None:
        maker_fee_pct = fallback_fee_pct
    if taker_fee_pct is None:
        taker_fee_pct = fallback_fee_pct
    if maker_fee_pct is None and taker_fee_pct is not None:
        maker_fee_pct = taker_fee_pct
    if taker_fee_pct is None and maker_fee_pct is not None:
        taker_fee_pct = maker_fee_pct

    maker_fee_pct = max(0.0, float(maker_fee_pct or 0.0))
    taker_fee_pct = max(0.0, float(taker_fee_pct or 0.0))

    leverage = _try_float(metadata.get("leverage"))
    leverage = max(1.0, float(leverage if leverage is not None else 1.0))

    margin_mode = _coerce_margin_mode(metadata.get("margin_mode"))

    funding_rate = _try_float(metadata.get("funding_rate"))
    if funding_rate is None and pair_snapshot is not None and pair_snapshot.funding_rate is not None:
        funding_rate = float(pair_snapshot.funding_rate)
    funding_rate = float(funding_rate if funding_rate is not None else 0.0)

    return maker_fee_pct, taker_fee_pct, leverage, margin_mode, funding_rate


def _fee_rate_for_fill(
    *,
    is_maker: bool,
    maker_fee_pct: float,
    taker_fee_pct: float,
) -> float:
    maker = max(0.0, float(maker_fee_pct))
    taker = max(0.0, float(taker_fee_pct))
    if is_maker:
        return maker if maker > 0 else taker
    return taker if taker > 0 else maker


def _calc_fill_fee_quote(
    *,
    fill_notional_quote: float,
    is_maker: bool,
    maker_fee_pct: float,
    taker_fee_pct: float,
) -> tuple[float, float]:
    fee_rate_pct = _fee_rate_for_fill(
        is_maker=is_maker,
        maker_fee_pct=maker_fee_pct,
        taker_fee_pct=taker_fee_pct,
    )
    fee_quote = float(max(Decimal(0), abs(_D(fill_notional_quote)) * _D(fee_rate_pct)))
    return fee_quote, fee_rate_pct


def _calc_margin_reserve_quote(
    *,
    filled_notional_quote_total: float,
    leverage: float,
    margin_mode: str,
) -> float:
    notional = max(Decimal(0), abs(_D(filled_notional_quote_total)))
    if _coerce_margin_mode(margin_mode) == "standard":
        return float(notional)
    lev = max(Decimal(1), _D(leverage))
    return float(notional / lev)


def _order_metadata(order: OrderRecord) -> dict[str, str]:
    remaining = _remaining_amount_base(order)
    return {
        "order_state": order.state,
        "side": order.side,
        "order_type": order.order_type,
        "amount_base": str(order.amount_base),
        "filled_amount_base_total": str(order.filled_base),
        "remaining_amount_base": str(remaining),
        "filled_notional_quote_total": str(order.filled_quote),
        "fill_count": str(order.fill_count),
        "price": str(order.price),
        "time_in_force": order.time_in_force,
        "reduce_only": "1" if order.reduce_only else "0",
        "post_only": "1" if order.post_only else "0",
        "updated_ts_ms": str(order.updated_ts_ms),
        "last_fill_snapshot_event_id": str(order.last_fill_snapshot_event_id or ""),
        "last_fill_amount_base": str(order.last_fill_amount_base),
        "filled_fee_quote_total": str(order.filled_fee_quote),
        "margin_reserve_quote": str(order.margin_reserve_quote),
        "maker_fee_pct": str(order.maker_fee_pct),
        "taker_fee_pct": str(order.taker_fee_pct),
        "leverage": str(order.leverage),
        "margin_mode": _coerce_margin_mode(order.margin_mode),
        "funding_rate": str(order.funding_rate),
    }


def _event_for_command(
    *,
    command: PaperExchangeCommandEvent,
    status: str,
    reason: str,
    metadata: dict[str, str] | None = None,
) -> PaperExchangeEvent:
    return PaperExchangeEvent(
        producer="paper_exchange_service",
        instance_name=command.instance_name,
        correlation_id=command.event_id,
        command_event_id=command.event_id,
        command=command.command,
        status=status,
        reason=reason,
        connector_name=command.connector_name,
        trading_pair=command.trading_pair,
        order_id=command.order_id,
        position_action=command.position_action,
        position_mode=command.position_mode,
        metadata=dict(metadata or {}),
    )


def _crosses_book(side: str, order_price: float, best_bid: float | None, best_ask: float | None) -> bool:
    if side == "buy":
        return best_ask is not None and order_price >= best_ask
    if side == "sell":
        return best_bid is not None and order_price <= best_bid
    return False


def _market_execution_price(side: str, snapshot: PairSnapshot | None) -> float | None:
    best_bid = _snapshot_best_bid(snapshot)
    best_ask = _snapshot_best_ask(snapshot)
    if side == "buy":
        return best_ask or (snapshot.mid_price if snapshot is not None else None)
    if side == "sell":
        return best_bid or (snapshot.mid_price if snapshot is not None else None)
    return None


def _extract_depth_levels(raw_levels: object, *, descending: bool, max_levels: int = 5) -> tuple[tuple[float, float], ...]:
    levels: list[tuple[float, float]] = []
    if not isinstance(raw_levels, list):
        return ()
    for raw in raw_levels:
        price: float | None = None
        size: float | None = None
        if isinstance(raw, dict):
            price = _try_float(raw.get("price"))
            size = _try_float(raw.get("size"))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            price = _try_float(raw[0])
            size = _try_float(raw[1])
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append((float(price), float(size)))
        if len(levels) >= max(1, int(max_levels)):
            break
    levels.sort(key=lambda item: item[0], reverse=bool(descending))
    return tuple(levels)


def _contra_levels_for_snapshot(
    snapshot: PairSnapshot,
    *,
    side: str,
    max_levels: int,
    limit_price: float | None = None,
) -> tuple[tuple[float, float], ...]:
    levels = snapshot.ask_levels if side == "buy" else snapshot.bid_levels
    if not levels:
        top_price = _snapshot_best_ask(snapshot) if side == "buy" else _snapshot_best_bid(snapshot)
        top_size = _snapshot_best_ask_size(snapshot) if side == "buy" else _snapshot_best_bid_size(snapshot)
        if top_price is None:
            return ()
        levels = ((float(top_price), float(top_size) if top_size is not None else float("inf")),)
    filtered: list[tuple[float, float]] = []
    for price, size in levels[: max(1, int(max_levels))]:
        if limit_price is not None:
            if side == "buy" and float(price) > float(limit_price):
                continue
            if side == "sell" and float(price) < float(limit_price):
                continue
        if float(size) <= _MIN_FILL_EPSILON:
            continue
        filtered.append((float(price), float(size)))
    return tuple(filtered)


def _sweep_fill_from_levels(
    *,
    amount_base: float,
    levels: tuple[tuple[float, float], ...],
) -> tuple[float, float | None]:
    remaining = max(0.0, float(amount_base))
    if remaining <= _MIN_FILL_EPSILON:
        return 0.0, None
    filled = 0.0
    notional = 0.0
    for price, size in levels:
        take = min(remaining, max(0.0, float(size)))
        if take <= _MIN_FILL_EPSILON:
            continue
        filled += take
        notional += take * float(price)
        remaining = max(0.0, remaining - take)
        if remaining <= _MIN_FILL_EPSILON:
            break
    if filled <= _MIN_FILL_EPSILON:
        return 0.0, None
    return filled, (notional / filled)


def _effective_depth_from_levels(
    levels: tuple[tuple[float, float], ...],
    *,
    decay: float = 0.70,
) -> float:
    if not levels:
        return 0.0
    total = 0.0
    weight = 1.0
    bounded_decay = min(1.0, max(0.1, float(decay)))
    for _price, size in levels:
        if float(size) > _MIN_FILL_EPSILON:
            total += float(size) * weight
        weight *= bounded_decay
    return max(0.0, float(total))


def _consume_levels(
    levels: list[tuple[float, float]],
    consumed: float,
) -> list[tuple[float, float]]:
    remaining = max(0.0, float(consumed))
    if remaining <= _MIN_FILL_EPSILON:
        return [(float(price), float(size)) for price, size in levels]
    out: list[tuple[float, float]] = []
    for price, size in levels:
        level_size = max(0.0, float(size))
        if remaining > _MIN_FILL_EPSILON and level_size > _MIN_FILL_EPSILON:
            used = min(level_size, remaining)
            level_size = max(0.0, level_size - used)
            remaining = max(0.0, remaining - used)
        if level_size > _MIN_FILL_EPSILON:
            out.append((float(price), level_size))
    return out


def _filter_levels_for_limit(
    levels: list[tuple[float, float]],
    *,
    side: str,
    limit_price: float,
    max_levels: int,
) -> tuple[tuple[float, float], ...]:
    filtered: list[tuple[float, float]] = []
    for price, size in levels[: max(1, int(max_levels))]:
        if side == "buy" and float(price) > float(limit_price):
            continue
        if side == "sell" and float(price) < float(limit_price):
            continue
        if float(size) <= _MIN_FILL_EPSILON:
            continue
        filtered.append((float(price), float(size)))
    return tuple(filtered)


def _order_matches_snapshot(order: OrderRecord, snapshot: PairSnapshot) -> bool:
    snapshot_instance = _normalize(snapshot.instance_name)
    return (
        (not snapshot_instance or _normalize(order.instance_name) == snapshot_instance)
        and
        _normalize_connector_name(order.connector_name) == _normalize_connector_name(snapshot.connector_name)
        and str(order.trading_pair).upper() == str(snapshot.trading_pair).upper()
    )


def _ordered_active_orders_for_snapshot(state: PaperExchangeState, snapshot: PairSnapshot) -> list[OrderRecord]:
    active = [
        order
        for order in state.orders_by_id.values()
        if order.state in {"working", "partially_filled"} and _order_matches_snapshot(order, snapshot)
    ]
    active.sort(key=lambda order: (int(order.created_ts_ms), str(order.order_id)))
    return active


def _build_fill_candidates_for_snapshot(
    *,
    state: PaperExchangeState,
    snapshot: PairSnapshot,
    resting_fill_latency_ms: int = 0,
    maker_queue_participation: float = 1.0,
    market_sweep_depth_levels: int = 1,
) -> list[FillCandidate]:
    best_bid = _snapshot_best_bid(snapshot)
    best_ask = _snapshot_best_ask(snapshot)
    if best_bid is None and best_ask is None:
        return []

    bid_levels = list(_contra_levels_for_snapshot(snapshot, side="sell", max_levels=max(1, int(market_sweep_depth_levels))))
    ask_levels = list(_contra_levels_for_snapshot(snapshot, side="buy", max_levels=max(1, int(market_sweep_depth_levels))))
    candidates: list[FillCandidate] = []

    # Replay guard for partially processed snapshot rows:
    # reserve liquidity already consumed by fills tied to this snapshot event_id.
    for historical_order in state.orders_by_id.values():
        if str(historical_order.last_fill_snapshot_event_id or "") != str(snapshot.event_id):
            continue
        consumed = max(0.0, float(historical_order.last_fill_amount_base))
        if consumed <= _MIN_FILL_EPSILON:
            continue
        if historical_order.side == "buy":
            ask_levels = _consume_levels(ask_levels, consumed)
        elif historical_order.side == "sell":
            bid_levels = _consume_levels(bid_levels, consumed)

    for order in _ordered_active_orders_for_snapshot(state, snapshot):
        if is_immediate_tif(order.time_in_force):
            # Defensive migration guard: immediate-only orders must never keep resting
            # across snapshots (e.g., after version upgrades or legacy snapshots).
            if can_transition_state(order.state, "expired"):
                order.state = "expired"
                order.updated_ts_ms = _now_ms()
            else:
                state.market_fill_invalid_transition_drops += 1
                logger.warning(
                    "paper_exchange invalid transition dropped | order_id=%s from=%s to=expired source=immediate_tif_guard",
                    order.order_id,
                    order.state,
                )
            continue
        if str(order.last_fill_snapshot_event_id or "") == str(snapshot.event_id):
            # Replay guard: one fill step per order per snapshot event_id.
            continue
        remaining = _remaining_amount_base(order)
        if remaining <= _MIN_FILL_EPSILON:
            continue
        if not _crosses_book(order.side, float(order.price), best_bid, best_ask):
            continue
        if int(snapshot.timestamp_ms) - int(order.created_ts_ms) < max(0, int(resting_fill_latency_ms)):
            continue

        if order.side == "buy":
            contra_levels = _filter_levels_for_limit(
                ask_levels,
                side=order.side,
                limit_price=float(order.price),
                max_levels=max(1, int(market_sweep_depth_levels)),
            )
        else:
            contra_levels = _filter_levels_for_limit(
                bid_levels,
                side=order.side,
                limit_price=float(order.price),
                max_levels=max(1, int(market_sweep_depth_levels)),
            )
        if order.side == "buy":
            fill_price = float(order.price)
        else:
            fill_price = float(order.price)
        if fill_price <= 0:
            continue

        effective_depth = _effective_depth_from_levels(contra_levels)
        fillable_available = (
            remaining
            if effective_depth <= _MIN_FILL_EPSILON
            else float(effective_depth) * max(0.0, float(maker_queue_participation))
        )
        fill_amount = min(remaining, max(0.0, fillable_available))
        if fill_amount <= _MIN_FILL_EPSILON:
            continue

        remaining_after = max(0.0, remaining - fill_amount)
        if order.side == "buy":
            ask_levels = _consume_levels(ask_levels, fill_amount)
        else:
            bid_levels = _consume_levels(bid_levels, fill_amount)

        fill_notional_quote = float(_D(fill_amount) * _D(fill_price))
        fill_fee_quote, fill_fee_rate_pct = _calc_fill_fee_quote(
            fill_notional_quote=fill_notional_quote,
            is_maker=True,
            maker_fee_pct=order.maker_fee_pct,
            taker_fee_pct=order.taker_fee_pct,
        )
        filled_notional_quote_total = max(0.0, float(_D(order.filled_quote) + _D(fill_notional_quote)))
        margin_reserve_quote = _calc_margin_reserve_quote(
            filled_notional_quote_total=filled_notional_quote_total,
            leverage=order.leverage,
            margin_mode=order.margin_mode,
        )
        fill_count = int(order.fill_count) + 1
        candidates.append(
            FillCandidate(
                event_id=f"pe-fill-{snapshot.event_id}-{order.order_id}-{fill_count}",
                command_event_id=f"market_snapshot:{snapshot.event_id}",
                order_id=str(order.order_id),
                new_state="filled" if remaining_after <= _MIN_FILL_EPSILON else "partially_filled",
                fill_price=fill_price,
                fill_amount_base=fill_amount,
                fill_notional_quote=fill_notional_quote,
                remaining_amount_base=remaining_after,
                is_maker=True,
                snapshot_event_id=str(snapshot.event_id),
                snapshot_market_sequence=int(snapshot.market_sequence or 0),
                fill_count=fill_count,
                fill_fee_quote=float(fill_fee_quote),
                fill_fee_rate_pct=float(fill_fee_rate_pct),
                margin_reserve_quote=float(margin_reserve_quote),
                funding_rate=float(order.funding_rate),
            )
        )
    return candidates


def _market_fill_event_from_candidate(
    *,
    order: OrderRecord,
    snapshot: PairSnapshot,
    candidate: FillCandidate,
    realized_pnl_quote: float = 0.0,
) -> PaperExchangeEvent:
    reason = "resting_order_filled" if candidate.new_state == "filled" else "resting_order_partial_fill"
    filled_base_total = max(0.0, float(_D(order.filled_base) + _D(candidate.fill_amount_base)))
    filled_notional_quote_total = max(0.0, float(_D(order.filled_quote) + _D(candidate.fill_notional_quote)))
    filled_fee_quote_total = max(0.0, float(_D(order.filled_fee_quote) + _D(candidate.fill_fee_quote)))
    return PaperExchangeEvent(
        producer="paper_exchange_service",
        event_id=str(candidate.event_id),
        correlation_id=str(candidate.command_event_id),
        instance_name=order.instance_name,
        command_event_id=str(candidate.command_event_id),
        command="order_fill",
        status="processed",
        reason=reason,
        connector_name=order.connector_name,
        trading_pair=order.trading_pair,
        order_id=order.order_id,
        metadata={
            "order_state": candidate.new_state,
            "side": order.side,
            "order_type": order.order_type,
            "amount_base": str(order.amount_base),
            "price": str(order.price),
            "time_in_force": order.time_in_force,
            "reduce_only": "1" if order.reduce_only else "0",
            "post_only": "1" if order.post_only else "0",
            "fill_price": str(candidate.fill_price),
            "fill_amount_base": str(candidate.fill_amount_base),
            "fill_notional_quote": str(candidate.fill_notional_quote),
            "fill_fee_quote": str(candidate.fill_fee_quote),
            "fill_fee_rate_pct": str(candidate.fill_fee_rate_pct),
            "is_maker": "1" if candidate.is_maker else "0",
            "remaining_amount_base": str(candidate.remaining_amount_base),
            "filled_amount_base_total": str(filled_base_total),
            "filled_notional_quote_total": str(filled_notional_quote_total),
            "filled_fee_quote_total": str(filled_fee_quote_total),
            "maker_fee_pct": str(order.maker_fee_pct),
            "taker_fee_pct": str(order.taker_fee_pct),
            "leverage": str(order.leverage),
            "margin_mode": _coerce_margin_mode(order.margin_mode),
            "funding_rate": str(candidate.funding_rate),
            "snapshot_funding_rate": str(snapshot.funding_rate) if snapshot.funding_rate is not None else "",
            "margin_reserve_quote": str(candidate.margin_reserve_quote),
            "fill_count": str(candidate.fill_count),
            "snapshot_event_id": str(candidate.snapshot_event_id),
            "snapshot_market_sequence": str(candidate.snapshot_market_sequence),
            "best_bid": str(snapshot.best_bid) if snapshot.best_bid is not None else "",
            "best_ask": str(snapshot.best_ask) if snapshot.best_ask is not None else "",
            "realized_pnl_quote": str(realized_pnl_quote),
        },
    )


def _apply_fill_candidate(order: OrderRecord, candidate: FillCandidate, *, now_ms: int) -> bool:
    target_state = str(candidate.new_state or "").strip().lower()
    if not can_transition_state(order.state, target_state):
        logger.warning(
            "paper_exchange invalid transition dropped | order_id=%s from=%s to=%s source=apply_fill_candidate",
            order.order_id,
            order.state,
            target_state,
        )
        return False
    order.filled_base = max(0.0, float(_D(order.filled_base) + _D(candidate.fill_amount_base)))
    order.filled_quote = max(0.0, float(_D(order.filled_quote) + _D(candidate.fill_notional_quote)))
    order.filled_fee_quote = max(0.0, float(_D(order.filled_fee_quote) + _D(candidate.fill_fee_quote)))
    order.margin_reserve_quote = max(0.0, float(candidate.margin_reserve_quote))
    order.fill_count = int(candidate.fill_count)
    if float(candidate.fill_amount_base) > _MIN_FILL_EPSILON and int(order.first_fill_ts_ms) <= 0:
        order.first_fill_ts_ms = int(now_ms)
    order.state = target_state
    order.last_fill_snapshot_event_id = str(candidate.snapshot_event_id)
    order.last_fill_amount_base = max(0.0, float(candidate.fill_amount_base))
    order.updated_ts_ms = int(now_ms)
    return True


def _prune_orders(
    *,
    state: PaperExchangeState,
    now_ms: int,
    terminal_order_ttl_ms: int,
    max_orders_tracked: int,
) -> int:
    removed = 0
    ttl_ms = max(0, int(terminal_order_ttl_ms))
    max_tracked = max(1, int(max_orders_tracked))

    if ttl_ms > 0:
        for order_id, order in list(state.orders_by_id.items()):
            if order.state not in _TERMINAL_ORDER_STATES:
                continue
            order_age_ms = max(0, int(now_ms) - int(order.updated_ts_ms))
            if order_age_ms > ttl_ms:
                state.orders_by_id.pop(order_id, None)
                removed += 1

    overflow = len(state.orders_by_id) - max_tracked
    if overflow > 0:
        sorted_orders = sorted(
            state.orders_by_id.items(),
            key=lambda item: (
                0 if item[1].state in _TERMINAL_ORDER_STATES else 1,
                int(item[1].updated_ts_ms),
                str(item[0]),
            ),
        )
        for order_id, _order in sorted_orders[:overflow]:
            if order_id in state.orders_by_id:
                state.orders_by_id.pop(order_id, None)
                removed += 1

    if removed > 0:
        state.orders_pruned_total += removed
    return removed
