from __future__ import annotations

from platform_lib.market_data.market_history_policy import runtime_seed_policy, status_meets_policy
from platform_lib.market_data.market_history_types import MarketHistoryStatus


def test_runtime_seed_policy_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_SOURCE_PRIORITY", "exchange_ohlcv,quote_mid")
    monkeypatch.setenv("HB_HISTORY_ALLOW_FALLBACK", "true")
    monkeypatch.setenv("HB_HISTORY_REQUIRE_CLOSED", "false")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "fresh")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_BARS", "44")
    monkeypatch.setenv("HB_HISTORY_MAX_ACCEPTABLE_GAP_S", "90")

    policy = runtime_seed_policy(default_min_bars=30)

    assert policy.preferred_sources == ["exchange_ohlcv", "quote_mid"]
    assert policy.allow_fallback is True
    assert policy.require_closed is False
    assert policy.min_acceptable_status == "fresh"
    assert policy.min_bars_before_trading == 44
    assert policy.max_acceptable_gap_s == 90


def test_status_meets_policy_accepts_stale_when_other_constraints_are_clean() -> None:
    policy = runtime_seed_policy(default_min_bars=30)
    status = MarketHistoryStatus(
        status="stale",
        freshness_ms=120_000,
        max_gap_s=60,
        coverage_ratio=1.0,
        source_used="db_v2",
        degraded_reason="",
        bars_returned=30,
        bars_requested=30,
    )

    assert status_meets_policy(status, policy) is True


def test_status_meets_policy_rejects_gapped_or_too_few_bars() -> None:
    policy = runtime_seed_policy(default_min_bars=30)
    gapped = MarketHistoryStatus(
        status="gapped",
        freshness_ms=60_000,
        max_gap_s=600,
        coverage_ratio=0.5,
        source_used="db_v2",
        degraded_reason="gap",
        bars_returned=30,
        bars_requested=30,
    )
    too_few = MarketHistoryStatus(
        status="fresh",
        freshness_ms=60_000,
        max_gap_s=0,
        coverage_ratio=1.0,
        source_used="db_v2",
        degraded_reason="",
        bars_returned=5,
        bars_requested=30,
    )

    assert status_meets_policy(gapped, policy) is False
    assert status_meets_policy(too_few, policy) is False
