from __future__ import annotations

from scripts.utils.day2_gate_evaluator import _lag_diagnostics


def test_lag_diagnostics_excludes_trimmed_market_streams_from_absolute_gate() -> None:
    diag = _lag_diagnostics(
        {
            "delta_produced_minus_ingested_since_baseline": {
                "hb.market_quote.v1": 40_000_000,
                "hb.market_depth.v1": 1_800_000,
                "hb.execution_intent.v1": 2,
            },
            "source_length_by_stream": {
                "hb.market_quote.v1": 100_000,
                "hb.market_depth.v1": 50_000,
                "hb.execution_intent.v1": 20,
            },
            "source_events_by_stream": {
                "hb.market_quote.v1": 42_000_000,
                "hb.market_depth.v1": 3_100_000,
                "hb.execution_intent.v1": 20,
            },
            "stored_events_by_stream": {
                "hb.market_quote.v1": 2_200_000,
                "hb.market_depth.v1": 1_300_000,
                "hb.execution_intent.v1": 18,
            },
        },
        max_allowed_delta=5,
    )

    assert diag["max_delta_observed"] == 2
    assert diag["offending_streams"] == {}
    assert "hb.market_quote.v1" in diag["excluded_streams"]
    assert "hb.market_depth.v1" in diag["excluded_streams"]
    assert diag["excluded_streams"]["hb.market_quote.v1"]["reason"] == "trimmed_retention_entries_added_not_comparable"


def test_lag_diagnostics_keeps_trim_sensitive_stream_when_not_yet_beyond_live_retention() -> None:
    diag = _lag_diagnostics(
        {
            "lag_produced_minus_ingested_since_baseline": {
                "hb.market_quote.v1": 9,
            },
            "source_length_by_stream": {
                "hb.market_quote.v1": 100_000,
            },
            "source_events_by_stream": {
                "hb.market_quote.v1": 95_000,
            },
            "stored_events_by_stream": {
                "hb.market_quote.v1": 10_000,
            },
        },
        max_allowed_delta=5,
    )

    assert diag["max_delta_observed"] == 9
    assert diag["worst_stream"] == "hb.market_quote.v1"
    assert diag["offending_streams"] == {"hb.market_quote.v1": 9}
    assert diag["excluded_streams"] == {}


def test_lag_diagnostics_keeps_control_plane_streams_strict() -> None:
    diag = _lag_diagnostics(
        {
            "delta_produced_minus_ingested_since_baseline": {
                "hb.execution_intent.v1": 32,
                "hb.audit.v1": 7,
            },
            "source_length_by_stream": {
                "hb.execution_intent.v1": 1_000,
                "hb.audit.v1": 1_000,
            },
            "source_events_by_stream": {
                "hb.execution_intent.v1": 1_200,
                "hb.audit.v1": 1_300,
            },
            "stored_events_by_stream": {
                "hb.execution_intent.v1": 500,
                "hb.audit.v1": 700,
            },
        },
        max_allowed_delta=5,
    )

    assert diag["max_delta_observed"] == 32
    assert diag["worst_stream"] == "hb.execution_intent.v1"
    assert diag["offending_streams"] == {
        "hb.audit.v1": 7,
        "hb.execution_intent.v1": 32,
    }
    assert diag["excluded_streams"] == {}


def test_lag_diagnostics_prefers_consumer_group_lag_when_available() -> None:
    diag = _lag_diagnostics(
        {
            "delta_produced_minus_ingested_since_baseline": {
                "hb.execution_intent.v1": 32,
                "hb.audit.v1": 32,
            },
            "consumer_group_lag_by_stream": {
                "hb.execution_intent.v1": 2,
                "hb.audit.v1": 2,
            },
        },
        max_allowed_delta=5,
    )

    assert diag["max_delta_observed"] == 2
    assert diag["offending_streams"] == {}
    assert diag["lag_by_stream_abs"] == {
        "hb.audit.v1": 2,
        "hb.execution_intent.v1": 2,
    }
    assert diag["raw_lag_by_stream_abs"] == {
        "hb.audit.v1": 32,
        "hb.execution_intent.v1": 32,
    }
