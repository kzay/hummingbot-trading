from __future__ import annotations

ACTIVE_ORDER_STATES: set[str] = {"accepted", "working", "partially_filled"}
TERMINAL_ORDER_STATES: set[str] = {"filled", "cancelled", "rejected", "expired"}
ALL_ORDER_STATES: set[str] = set(ACTIVE_ORDER_STATES | TERMINAL_ORDER_STATES)

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "accepted": {"working", "partially_filled", "filled", "cancelled", "rejected", "expired"},
    "working": {"partially_filled", "filled", "cancelled", "rejected", "expired"},
    "partially_filled": {"filled", "cancelled", "rejected", "expired"},
    "filled": {"filled"},
    "cancelled": {"cancelled"},
    "rejected": {"rejected"},
    "expired": {"expired"},
}


def normalize_order_state(state: str) -> str:
    return str(state or "").strip().lower()


def is_active_state(state: str) -> bool:
    return normalize_order_state(state) in ACTIVE_ORDER_STATES


def is_terminal_state(state: str) -> bool:
    return normalize_order_state(state) in TERMINAL_ORDER_STATES


def can_transition_state(current_state: str, new_state: str) -> bool:
    current = normalize_order_state(current_state)
    target = normalize_order_state(new_state)
    if current not in ALL_ORDER_STATES or target not in ALL_ORDER_STATES:
        return False
    if current == target:
        return True
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def is_immediate_tif(time_in_force: str) -> bool:
    tif = str(time_in_force or "").strip().lower()
    return tif in {"ioc", "fok"}


def resolve_crossing_limit_order_outcome(
    *,
    amount_base: float,
    immediate_fill_amount: float,
    time_in_force: str,
    min_fill_epsilon: float = 1e-12,
) -> tuple[str, str, float]:
    """Resolve state/reason/fill for a crossing limit order.

    Returns: (new_state, reason, effective_fill_amount).
    """
    amount = max(0.0, float(amount_base))
    fill = max(0.0, float(immediate_fill_amount))
    tif = str(time_in_force or "").strip().lower()
    partially_filled = fill + float(min_fill_epsilon) < amount

    if tif == "fok" and partially_filled:
        return "expired", "time_in_force_fok_no_full_fill", 0.0
    if partially_filled and tif == "ioc":
        return "expired", "time_in_force_ioc_partial_fill_expired", fill
    if partially_filled:
        return "partially_filled", "order_partially_filled_crossing", fill
    return "filled", "order_filled_crossing", fill

