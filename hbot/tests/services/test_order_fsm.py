from __future__ import annotations

from services.paper_exchange_service.order_fsm import (
    ACTIVE_ORDER_STATES,
    TERMINAL_ORDER_STATES,
    can_transition_state,
    is_active_state,
    is_immediate_tif,
    is_terminal_state,
    resolve_crossing_limit_order_outcome,
)


def test_state_sets_are_classified_consistently() -> None:
    assert "working" in ACTIVE_ORDER_STATES
    assert "filled" in TERMINAL_ORDER_STATES
    assert is_active_state("working")
    assert is_terminal_state("filled")
    assert not is_active_state("filled")
    assert not is_terminal_state("working")


def test_can_transition_state_allows_expected_lifecycle_edges() -> None:
    assert can_transition_state("working", "partially_filled")
    assert can_transition_state("partially_filled", "filled")
    assert can_transition_state("working", "cancelled")
    assert can_transition_state("filled", "filled")


def test_can_transition_state_rejects_invalid_edges() -> None:
    assert not can_transition_state("filled", "working")
    assert not can_transition_state("cancelled", "partially_filled")
    assert not can_transition_state("unknown", "filled")


def test_resolve_crossing_limit_order_outcome_fok_partial_expires_without_fill() -> None:
    new_state, reason, fill = resolve_crossing_limit_order_outcome(
        amount_base=2.0,
        immediate_fill_amount=1.0,
        time_in_force="fok",
    )
    assert new_state == "expired"
    assert reason == "time_in_force_fok_no_full_fill"
    assert fill == 0.0


def test_resolve_crossing_limit_order_outcome_ioc_partial_expires_remainder() -> None:
    new_state, reason, fill = resolve_crossing_limit_order_outcome(
        amount_base=2.0,
        immediate_fill_amount=1.0,
        time_in_force="ioc",
    )
    assert new_state == "expired"
    assert reason == "time_in_force_ioc_partial_fill_expired"
    assert fill == 1.0


def test_resolve_crossing_limit_order_outcome_gtc_partial_rests() -> None:
    new_state, reason, fill = resolve_crossing_limit_order_outcome(
        amount_base=2.0,
        immediate_fill_amount=1.0,
        time_in_force="gtc",
    )
    assert new_state == "partially_filled"
    assert reason == "order_partially_filled_crossing"
    assert fill == 1.0


def test_resolve_crossing_limit_order_outcome_full_fill() -> None:
    new_state, reason, fill = resolve_crossing_limit_order_outcome(
        amount_base=1.0,
        immediate_fill_amount=1.0,
        time_in_force="ioc",
    )
    assert new_state == "filled"
    assert reason == "order_filled_crossing"
    assert fill == 1.0


def test_is_immediate_tif_normalizes_value() -> None:
    assert is_immediate_tif("IOC")
    assert is_immediate_tif(" fok ")
    assert not is_immediate_tif("gtc")

