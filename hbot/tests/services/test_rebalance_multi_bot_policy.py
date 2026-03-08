from __future__ import annotations

from scripts.analysis.rebalance_multi_bot_policy import (
    apply_rebalance_to_policy,
    build_rebalance_plan,
)


def test_build_rebalance_plan_passes_and_computes_updates() -> None:
    policy = {
        "bots": {
            "bot1": {
                "enabled": True,
                "mode": "live",
                "allowed_symbols": ["BTC-USDT"],
                "target_alloc_pct": 1.0,
                "alloc_variance_proxy": 1.0,
                "max_alloc_pct": 1.0,
            },
            "bot3": {
                "enabled": True,
                "mode": "paper_only",
                "allowed_symbols": ["ETH-USDT"],
                "target_alloc_pct": 0.0,
                "alloc_variance_proxy": 1.5,
                "max_alloc_pct": 0.5,
            },
        }
    }
    report = {
        "status": "pass",
        "metrics": {
            "btc_eth_return_correlation": 0.25,
            "btc_variance": 1.0e-6,
            "eth_variance": 2.0e-6,
        },
        "allocation_recommendation_inverse_variance": {
            "btc": 0.7,
            "eth": 0.3,
        },
    }
    plan = build_rebalance_plan(
        policy=policy,
        diversification_report=report,
        included_modes=["live", "paper_only"],
        update_max_alloc=True,
    )
    assert plan["plan_ready"] is True
    assert plan["status"] == "pass"
    updates = plan["updates"]
    assert abs(float(updates["bot1"]["new_target_alloc_pct"]) - 0.7) < 1e-9
    assert abs(float(updates["bot3"]["new_target_alloc_pct"]) - 0.3) < 1e-9
    assert abs(float(updates["bot1"]["new_alloc_variance_proxy"]) - 1.0e-6) < 1e-12
    assert abs(float(updates["bot3"]["new_alloc_variance_proxy"]) - 2.0e-6) < 1e-12
    assert float(updates["bot3"]["new_max_alloc_pct"]) >= 0.3


def test_build_rebalance_plan_fails_when_report_or_bucket_missing() -> None:
    policy = {
        "bots": {
            "bot1": {
                "enabled": True,
                "mode": "live",
                "allowed_symbols": ["BTC-USDT"],
                "target_alloc_pct": 1.0,
                "alloc_variance_proxy": 1.0,
                "max_alloc_pct": 1.0,
            }
        }
    }
    report = {"status": "insufficient_data", "allocation_recommendation_inverse_variance": {"btc": 1.0, "eth": 0.0}}
    plan = build_rebalance_plan(
        policy=policy,
        diversification_report=report,
        included_modes=["live", "paper_only"],
        update_max_alloc=False,
    )
    assert plan["plan_ready"] is False
    reasons = " ".join(plan["blocking_reasons"])
    assert "diversification_report_status=insufficient_data" in reasons
    assert "no_eth_strategy_bot_in_policy" in reasons


def test_apply_rebalance_to_policy_updates_targets_and_variance() -> None:
    policy = {
        "bots": {
            "bot1": {
                "enabled": True,
                "mode": "live",
                "allowed_symbols": ["BTC-USDT"],
                "target_alloc_pct": 1.0,
                "alloc_variance_proxy": 1.0,
                "max_alloc_pct": 1.0,
            }
        }
    }
    plan = {
        "updates": {
            "bot1": {
                "new_target_alloc_pct": 0.65,
                "new_alloc_variance_proxy": 0.000002,
                "new_max_alloc_pct": 0.9,
            }
        }
    }
    updated = apply_rebalance_to_policy(policy, plan)
    bot1 = updated["bots"]["bot1"]
    assert abs(float(bot1["target_alloc_pct"]) - 0.65) < 1e-9
    assert abs(float(bot1["alloc_variance_proxy"]) - 0.000002) < 1e-12
    assert abs(float(bot1["max_alloc_pct"]) - 0.9) < 1e-9
