from __future__ import annotations

from scripts.release.run_strict_promotion_cycle import build_parser


def test_strict_cycle_parser_defaults_enable_paper_exchange_gates(monkeypatch) -> None:
    monkeypatch.delenv("STRICT_REQUIRE_PAPER_EXCHANGE_THRESHOLDS", raising=False)
    monkeypatch.delenv("STRICT_REQUIRE_PAPER_EXCHANGE_PREFLIGHT", raising=False)
    monkeypatch.delenv("STRICT_REQUIRE_PAPER_EXCHANGE_GOLDEN_PATH", raising=False)
    monkeypatch.delenv("STRICT_CHECK_PAPER_EXCHANGE_PERF_REGRESSION", raising=False)
    monkeypatch.delenv("STRICT_CHECK_REALTIME_L2_DATA_QUALITY", raising=False)

    parser = build_parser()
    args = parser.parse_args([])

    assert args.check_paper_exchange_thresholds is True
    assert args.check_paper_exchange_preflight is True
    assert args.check_paper_exchange_golden_path is True
    assert args.check_paper_exchange_perf_regression is True
    assert args.check_realtime_l2_data_quality is True


def test_strict_cycle_parser_env_can_disable_paper_exchange_gates(monkeypatch) -> None:
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_THRESHOLDS", "false")
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_PREFLIGHT", "0")
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_GOLDEN_PATH", "false")
    monkeypatch.setenv("STRICT_CHECK_PAPER_EXCHANGE_PERF_REGRESSION", "false")
    monkeypatch.setenv("STRICT_CHECK_REALTIME_L2_DATA_QUALITY", "false")

    parser = build_parser()
    args = parser.parse_args([])

    assert args.check_paper_exchange_thresholds is False
    assert args.check_paper_exchange_preflight is False
    assert args.check_paper_exchange_golden_path is False
    assert args.check_paper_exchange_perf_regression is False
    assert args.check_realtime_l2_data_quality is False


def test_strict_cycle_parser_no_flags_override_enabled_defaults(monkeypatch) -> None:
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_THRESHOLDS", "true")
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_PREFLIGHT", "true")
    monkeypatch.setenv("STRICT_REQUIRE_PAPER_EXCHANGE_GOLDEN_PATH", "true")
    monkeypatch.setenv("STRICT_CHECK_PAPER_EXCHANGE_PERF_REGRESSION", "true")
    monkeypatch.setenv("STRICT_CHECK_REALTIME_L2_DATA_QUALITY", "true")

    parser = build_parser()
    args = parser.parse_args(
        [
            "--no-check-paper-exchange-thresholds",
            "--no-check-paper-exchange-preflight",
            "--no-check-paper-exchange-golden-path",
            "--no-check-paper-exchange-perf-regression",
            "--no-check-realtime-l2-data-quality",
        ]
    )

    assert args.check_paper_exchange_thresholds is False
    assert args.check_paper_exchange_preflight is False
    assert args.check_paper_exchange_golden_path is False
    assert args.check_paper_exchange_perf_regression is False
    assert args.check_realtime_l2_data_quality is False
