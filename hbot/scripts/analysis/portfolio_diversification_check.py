#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _parse_ts(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _iter_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _returns_by_ts(minute_path: Path) -> Dict[str, float]:
    rows: List[Tuple[str, float]] = []
    for row in _iter_rows(minute_path):
        ts = _parse_ts(str(row.get("ts", "")))
        mid = _safe_float(row.get("mid"), 0.0)
        if ts is None or mid <= 0.0:
            continue
        rows.append((ts.isoformat(), mid))
    rows.sort(key=lambda x: x[0])
    out: Dict[str, float] = {}
    prev_mid = 0.0
    for ts, mid in rows:
        if prev_mid > 0.0:
            out[ts] = (mid / prev_mid) - 1.0
        prev_mid = mid
    return out


def _aligned_values(a: Dict[str, float], b: Dict[str, float]) -> Tuple[List[float], List[float]]:
    common = sorted(set(a.keys()) & set(b.keys()))
    return [a[k] for k in common], [b[k] for k in common]


def _variance(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = mean(xs)
    return sum((x - mu) ** 2 for x in xs) / len(xs)


def _pearson_corr(xs: List[float], ys: List[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    den = den_x * den_y
    if den <= 0.0:
        return None
    return num / den


def _inverse_variance_weights(var_a: float, var_b: float) -> Dict[str, float]:
    if var_a <= 0.0 and var_b <= 0.0:
        return {"btc": 0.5, "eth": 0.5}
    if var_a <= 0.0:
        return {"btc": 0.5, "eth": 0.5}
    if var_b <= 0.0:
        return {"btc": 0.5, "eth": 0.5}
    w_a = 1.0 / var_a
    w_b = 1.0 / var_b
    denom = w_a + w_b
    if denom <= 0.0:
        return {"btc": 0.5, "eth": 0.5}
    return {"btc": w_a / denom, "eth": w_b / denom}


def build_diversification_report(
    btc_minute_path: Path,
    eth_minute_path: Path,
    max_abs_correlation: float = 0.70,
    min_overlap_points: int = 120,
) -> Dict[str, object]:
    btc_returns = _returns_by_ts(btc_minute_path)
    eth_returns = _returns_by_ts(eth_minute_path)
    btc_vals, eth_vals = _aligned_values(btc_returns, eth_returns)

    overlap = len(btc_vals)
    corr = _pearson_corr(btc_vals, eth_vals)
    btc_var = _variance(btc_vals)
    eth_var = _variance(eth_vals)
    weights = _inverse_variance_weights(btc_var, eth_var)

    status = "insufficient_data"
    checks: List[Dict[str, object]] = []
    if overlap >= min_overlap_points and corr is not None:
        corr_abs = abs(corr)
        corr_ok = corr_abs < max_abs_correlation
        status = "pass" if corr_ok else "fail"
        checks.append(
            {
                "name": "btc_eth_return_correlation",
                "pass": corr_ok,
                "value": corr,
                "abs_value": corr_abs,
                "max_abs_allowed": max_abs_correlation,
            }
        )
    else:
        checks.append(
            {
                "name": "btc_eth_return_correlation",
                "pass": False,
                "note": "insufficient_overlap",
                "overlap_points": overlap,
                "min_overlap_points": min_overlap_points,
            }
        )

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "inputs": {
            "btc_minute_path": str(btc_minute_path),
            "eth_minute_path": str(eth_minute_path),
            "max_abs_correlation": max_abs_correlation,
            "min_overlap_points": min_overlap_points,
        },
        "metrics": {
            "overlap_points": overlap,
            "btc_returns_count": len(btc_returns),
            "eth_returns_count": len(eth_returns),
            "btc_eth_return_correlation": corr,
            "btc_variance": btc_var,
            "eth_variance": eth_var,
        },
        "allocation_recommendation_inverse_variance": {
            "btc": weights["btc"],
            "eth": weights["eth"],
        },
        "checks": checks,
    }


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description="ROAD-9 diversification check: BTC vs ETH return correlation and inverse-variance weights."
    )
    parser.add_argument(
        "--btc-minute",
        default=str(root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"),
    )
    parser.add_argument(
        "--eth-minute",
        default=str(root / "data" / "bot3" / "logs" / "epp_v24" / "bot3_a" / "minute.csv"),
    )
    parser.add_argument("--max-abs-correlation", type=float, default=0.70)
    parser.add_argument("--min-overlap-points", type=int, default=120)
    parser.add_argument(
        "--out",
        default=str(root / "reports" / "policy" / "portfolio_diversification_latest.json"),
    )
    args = parser.parse_args()

    payload = build_diversification_report(
        btc_minute_path=Path(args.btc_minute),
        eth_minute_path=Path(args.eth_minute),
        max_abs_correlation=float(args.max_abs_correlation),
        min_overlap_points=max(2, int(args.min_overlap_points)),
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[portfolio-diversification] status={payload['status']}")
    print(f"[portfolio-diversification] evidence={out_path}")
    # Only fail on explicit diversification failure, not on insufficient data.
    return 2 if str(payload.get("status")) == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

