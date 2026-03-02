from __future__ import annotations

from services.portfolio_allocator.main import (
    _apply_diversification_variance_overrides,
    _compute_daily_goal_plan,
    _compute_inverse_variance_allocations,
    _eligible_bots,
)


def test_compute_inverse_variance_allocations_prefers_lower_variance() -> None:
    bots = {
        "bot1": {"equity_quote": 1000.0, "variance": 1.0, "max_alloc_pct": 1.0, "portfolio_action_enabled": 1.0},
        "bot3": {"equity_quote": 1000.0, "variance": 4.0, "max_alloc_pct": 1.0, "portfolio_action_enabled": 0.0},
    }
    out = _compute_inverse_variance_allocations(bots)
    assert out["bot1"] > out["bot3"]
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_compute_inverse_variance_allocations_respects_max_cap() -> None:
    bots = {
        "bot1": {"equity_quote": 1000.0, "variance": 0.2, "max_alloc_pct": 0.6, "portfolio_action_enabled": 1.0},
        "bot3": {"equity_quote": 1000.0, "variance": 1.0, "max_alloc_pct": 0.8, "portfolio_action_enabled": 0.0},
    }
    out = _compute_inverse_variance_allocations(bots)
    assert out["bot1"] <= 0.6 + 1e-6
    assert abs(sum(out.values()) - 1.0) < 1e-6


def test_eligible_bots_filters_disabled_and_zero_equity() -> None:
    policy = {
        "bots": {
            "bot1": {"enabled": True, "mode": "live", "alloc_variance_proxy": 1.0, "max_alloc_pct": 0.8},
            "bot2": {"enabled": False, "mode": "disabled"},
            "bot3": {"enabled": True, "mode": "paper_only", "alloc_variance_proxy": 2.0, "max_alloc_pct": 0.5},
        }
    }
    snapshots = {
        "bots": {
            "bot1": {"equity_quote": 500.0},
            "bot2": {"equity_quote": 1000.0},
            "bot3": {"equity_quote": 0.0},
        }
    }
    out = _eligible_bots(policy, snapshots)
    assert set(out.keys()) == {"bot1"}


def test_diversification_variance_overrides_apply_to_btc_and_eth() -> None:
    policy = {
        "bots": {
            "bot1": {
                "enabled": True,
                "mode": "live",
                "allowed_symbols": ["BTC-USDT"],
                "alloc_variance_proxy": 1.0,
                "max_alloc_pct": 0.8,
            },
            "bot3": {
                "enabled": True,
                "mode": "paper_only",
                "allowed_symbols": ["ETH-USDT"],
                "alloc_variance_proxy": 2.0,
                "max_alloc_pct": 0.5,
            },
        }
    }
    snapshots = {
        "bots": {
            "bot1": {"equity_quote": 500.0},
            "bot3": {"equity_quote": 300.0},
        }
    }
    eligible = _eligible_bots(policy, snapshots)
    report = {
        "status": "pass",
        "inputs": {"max_abs_correlation": 0.7},
        "metrics": {
            "btc_variance": 0.25,
            "eth_variance": 1.75,
            "btc_eth_return_correlation": 0.4,
        },
    }
    updated, diag = _apply_diversification_variance_overrides(eligible, report)

    assert float(updated["bot1"]["variance"]) == 0.25
    assert float(updated["bot3"]["variance"]) == 1.75
    assert str(updated["bot1"]["variance_source"]) == "diversification_report"
    assert str(updated["bot3"]["variance_source"]) == "diversification_report"
    assert int(diag["overrides_applied"]) == 2
    assert diag["correlation_ok"] is True


def test_diversification_variance_overrides_skip_when_metrics_missing() -> None:
    policy = {
        "bots": {
            "bot1": {
                "enabled": True,
                "mode": "live",
                "allowed_symbols": ["BTC-USDT"],
                "alloc_variance_proxy": 1.0,
                "max_alloc_pct": 0.8,
            }
        }
    }
    snapshots = {"bots": {"bot1": {"equity_quote": 500.0}}}
    eligible = _eligible_bots(policy, snapshots)
    updated, diag = _apply_diversification_variance_overrides(eligible, {})

    assert float(updated["bot1"]["variance"]) == 1.0
    assert str(updated["bot1"]["variance_source"]) == "policy_proxy"
    assert int(diag["overrides_applied"]) == 0


def test_compute_daily_goal_plan_weighted_by_allocation_pct() -> None:
    allocator_cfg = {
        "daily_goal": {
            "enabled": True,
            "target_pct_total_equity": 1.0,
            "distribution": "allocation_weighted",
            "apply_only_portfolio_action_enabled": False,
            "min_bot_target_pct": 0.0,
            "max_bot_target_pct": 10.0,
        }
    }
    proposals = [
        {"bot": "bot1", "equity_quote": 100.0, "allocation_pct": 0.8, "portfolio_action_enabled": True},
        {"bot": "bot3", "equity_quote": 100.0, "allocation_pct": 0.2, "portfolio_action_enabled": False},
    ]
    out = _compute_daily_goal_plan(allocator_cfg, proposals, total_equity_quote=200.0)
    assert out["status"] == "pass"
    rows = {str(r["bot"]): r for r in out["rows"]}
    assert abs(float(rows["bot1"]["daily_pnl_target_pct"]) - 1.6) < 1e-9
    assert abs(float(rows["bot3"]["daily_pnl_target_pct"]) - 0.4) < 1e-9
    assert abs(float(out["target_quote_total_equity"]) - 2.0) < 1e-9


def test_compute_daily_goal_plan_can_filter_to_action_scope() -> None:
    allocator_cfg = {
        "daily_goal": {
            "enabled": True,
            "target_pct_total_equity": 1.0,
            "distribution": "allocation_weighted",
            "apply_only_portfolio_action_enabled": True,
        }
    }
    proposals = [
        {"bot": "bot1", "equity_quote": 100.0, "allocation_pct": 0.8, "portfolio_action_enabled": True},
        {"bot": "bot3", "equity_quote": 100.0, "allocation_pct": 0.2, "portfolio_action_enabled": False},
    ]
    out = _compute_daily_goal_plan(allocator_cfg, proposals, total_equity_quote=200.0)
    assert out["status"] == "pass"
    rows = {str(r["bot"]): r for r in out["rows"]}
    assert set(rows.keys()) == {"bot1"}
    assert abs(float(rows["bot1"]["daily_pnl_target_pct"]) - 1.0) < 1e-9


def test_compute_daily_goal_plan_ignores_zero_weight_equity_in_goal_scope() -> None:
    allocator_cfg = {
        "daily_goal": {
            "enabled": True,
            "target_pct_total_equity": 1.0,
            "distribution": "allocation_weighted",
            "apply_only_portfolio_action_enabled": False,
        }
    }
    proposals = [
        {"bot": "bot1", "equity_quote": 100.0, "allocation_pct": 1.0, "portfolio_action_enabled": True},
        {"bot": "bot3", "equity_quote": 10_000.0, "allocation_pct": 0.0, "portfolio_action_enabled": False},
    ]
    out = _compute_daily_goal_plan(allocator_cfg, proposals, total_equity_quote=10_100.0)
    assert out["status"] == "pass"
    # Goal scope should be only weighted bots (bot1), not all snapshot equity.
    assert abs(float(out["goal_scope_equity_quote"]) - 100.0) < 1e-9
    assert abs(float(out["target_quote_total_equity"]) - 1.0) < 1e-9
    rows = {str(r["bot"]): r for r in out["rows"]}
    assert abs(float(rows["bot1"]["daily_pnl_target_pct"]) - 1.0) < 1e-9
