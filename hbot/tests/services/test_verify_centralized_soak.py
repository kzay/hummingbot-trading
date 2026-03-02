from __future__ import annotations

from scripts.release.verify_centralized_soak import _target_source_matches_runtime


def test_target_source_matches_runtime_when_execution_intent_source_present() -> None:
    ok = _target_source_matches_runtime(
        bot_name="bot3",
        snap_row={
            "pnl_governor_target_source": "execution_intent_daily_pnl_target_pct",
            "pnl_governor_target_pnl_pct": 0.0,
            "pnl_governor_target_mode": "disabled",
        },
        goal_row={"daily_pnl_target_pct": 0.0, "portfolio_action_enabled": False},
    )
    assert ok is True


def test_target_source_matches_runtime_for_disabled_zero_target_lane() -> None:
    ok = _target_source_matches_runtime(
        bot_name="bot3",
        snap_row={
            "pnl_governor_target_source": "none",
            "pnl_governor_target_pnl_pct": 0.0,
            "pnl_governor_target_mode": "disabled",
        },
        goal_row={"daily_pnl_target_pct": 0.0, "portfolio_action_enabled": False},
    )
    assert ok is True


def test_target_source_matches_runtime_rejects_none_when_lane_enabled() -> None:
    ok = _target_source_matches_runtime(
        bot_name="bot3",
        snap_row={
            "pnl_governor_target_source": "none",
            "pnl_governor_target_pnl_pct": 0.0,
            "pnl_governor_target_mode": "disabled",
        },
        goal_row={"daily_pnl_target_pct": 0.0, "portfolio_action_enabled": True},
    )
    assert ok is False

