"""Deterministic tick-loop micro-benchmark.

Runs synthetic tick cycles (snapshot build + spread compute + JSON serialize +
CSV emit) against constant synthetic data.  No external dependencies (no Redis,
no live market data).

Outputs:
  reports/verification/tick_benchmark_latest.json
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

_D = Decimal
_ZERO = _D("0")


def _synthetic_snapshot() -> dict[str, Any]:
    """Return a representative controller snapshot dict for benchmarking."""
    return {
        "spread_multiplier": _D("1.0"),
        "spread_floor_pct": _D("0.001"),
        "base_spread_pct": _D("0.0008"),
        "pnl_governor_active": False,
        "runtime_family": "bench",
        "adaptive_effective_min_edge_pct": _D("0.0001"),
        "adaptive_fill_age_s": _D("120"),
        "adaptive_market_spread_bps_ewma": _D("3.5"),
        "adaptive_band_pct_ewma": _D("0.002"),
        "adaptive_market_floor_pct": _D("0.0005"),
        "adaptive_vol_ratio": _D("1.1"),
        "edge_pause_threshold_pct": _D("0.0001"),
        "edge_resume_threshold_pct": _D("0.00015"),
        "soft_pause_edge": False,
        "projected_total_quote": _D("500"),
        "history_seed_status": "seeded",
        "history_seed_bars": 60,
        "shared_edge_gate_enabled": True,
        "net_edge_pct": _D("0.0003"),
        "turnover_x": _D("2.5"),
        "spread_pct": _D("0.002"),
    }


def _synthetic_market_conditions() -> dict[str, Any]:
    return {
        "mid": _D("50000.00"),
        "bid": _D("49999.50"),
        "ask": _D("50000.50"),
        "spread_bps": _D("2.0"),
        "volatility_1m": _D("0.003"),
        "imbalance": _D("0.05"),
        "volume_24h": _D("1500000"),
    }


def _synthetic_payload() -> dict[str, Any]:
    """Build a payload similar to what gets serialized on every tick."""
    snap = _synthetic_snapshot()
    mc = _synthetic_market_conditions()
    return {
        "schema_version": 3,
        "runtime_family": "bench",
        "reference_price": mc["mid"],
        "spread_multiplier": snap["spread_multiplier"],
        "regime": "neutral_low_vol",
        "target_base_pct": _D("0.50"),
        "base_pct": _D("0.48"),
        "state": "running",
        "spread_pct": snap["spread_pct"],
        "spread_floor_pct": snap["spread_floor_pct"],
        "base_spread_pct": snap["base_spread_pct"],
        "net_edge_pct": snap["net_edge_pct"],
        "turnover_x": snap["turnover_x"],
        "equity_quote": _D("1000"),
        "base_bal": _D("0.01"),
        "quote_bal": _D("500"),
        "daily_loss_pct": _D("0.001"),
        "drawdown_pct": _D("0.002"),
        "projected_total_quote": snap["projected_total_quote"],
        "market": mc,
        "adaptive": {k: v for k, v in snap.items() if k.startswith("adaptive_")},
    }


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * pct)
    return s[min(idx, len(s) - 1)]


def _bench_json_serialize(iterations: int) -> list[float]:
    """Benchmark JSON serialization of a tick payload."""
    try:
        import orjson
        def serialize(p: dict) -> bytes:
            return orjson.dumps(p, default=str)
    except ImportError:
        def serialize(p: dict) -> bytes:
            return json.dumps(p, default=str).encode()

    payload = _synthetic_payload()
    timings: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        serialize(payload)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        timings.append(elapsed_ms)
    return timings


def _bench_snapshot_build(iterations: int) -> list[float]:
    """Benchmark building the tick snapshot dict."""
    snap = _synthetic_snapshot()
    mc = _synthetic_market_conditions()
    timings: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        _synthetic_payload()
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        timings.append(elapsed_ms)
    return timings


def _bench_csv_format(iterations: int) -> list[float]:
    """Benchmark formatting a CSV row from tick data."""
    payload = _synthetic_payload()
    fields = list(payload.keys()) + ["ts", "event_ts"]
    timings: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        row = {k: str(v) for k, v in payload.items()}
        row["ts"] = "2026-03-09T12:00:00+00:00"
        row["event_ts"] = "2026-03-09T12:00:00+00:00"
        ",".join(str(row.get(f, "")) for f in fields)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        timings.append(elapsed_ms)
    return timings


def _bench_spread_compute(iterations: int) -> list[float]:
    """Benchmark a simplified spread calculation (no external deps)."""
    maker_fee = _D("0.0002")
    slippage = _D("0.0001")
    adverse = _D("0.0003")
    turnover_penalty = _D("0.0001")
    min_edge = _D("0.0001")
    band = _D("0.002")
    timings: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        cost = maker_fee + slippage + adverse + turnover_penalty
        spread = max(cost + min_edge, band)
        edge = spread - cost
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        timings.append(elapsed_ms)
    return timings


def _make_stats(timings: list[float]) -> dict[str, float]:
    if not timings:
        return {"samples": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0, "mean_ms": 0}
    return {
        "samples": len(timings),
        "p50_ms": round(_percentile(timings, 0.50), 4),
        "p95_ms": round(_percentile(timings, 0.95), 4),
        "p99_ms": round(_percentile(timings, 0.99), 4),
        "max_ms": round(max(timings), 4),
        "mean_ms": round(statistics.mean(timings), 4),
    }


def run(
    root: Path,
    iterations: int = 1000,
    warn_total_p99_ms: float = 50.0,
    fail_total_p99_ms: float = 100.0,
) -> dict[str, Any]:
    """Execute the benchmark and write the report artifact."""
    logger.info("Running tick benchmark (%d iterations)...", iterations)

    snapshot_timings = _bench_snapshot_build(iterations)
    spread_timings = _bench_spread_compute(iterations)
    json_timings = _bench_json_serialize(iterations)
    csv_timings = _bench_csv_format(iterations)

    total_timings = [
        snapshot_timings[i] + spread_timings[i] + json_timings[i] + csv_timings[i]
        for i in range(iterations)
    ]

    total_stats = _make_stats(total_timings)
    total_p99 = total_stats["p99_ms"]

    if total_p99 >= fail_total_p99_ms:
        status = "fail"
    elif total_p99 >= warn_total_p99_ms:
        status = "warn"
    else:
        status = "pass"

    report: dict[str, Any] = {
        "ts_utc": datetime.now(UTC).isoformat(),
        "iterations": iterations,
        "status": status,
        "warn_threshold_ms": warn_total_p99_ms,
        "fail_threshold_ms": fail_total_p99_ms,
        "total": total_stats,
        "snapshot_build": _make_stats(snapshot_timings),
        "spread_compute": _make_stats(spread_timings),
        "json_serialize": _make_stats(json_timings),
        "csv_format": _make_stats(csv_timings),
    }

    reports_dir = root / "reports" / "verification"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "tick_benchmark_latest.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("Benchmark report written to %s (status=%s, total_p99=%.3fms)", out_path, status, total_p99)

    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(description="Tick-loop micro-benchmark")
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warn-p99-ms", type=float, default=50.0)
    parser.add_argument("--fail-p99-ms", type=float, default=100.0)
    args = parser.parse_args()

    report = run(args.root, iterations=args.iterations, warn_total_p99_ms=args.warn_p99_ms, fail_total_p99_ms=args.fail_p99_ms)
    if report["status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
