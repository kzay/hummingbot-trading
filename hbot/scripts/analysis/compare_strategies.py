from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from compute_metrics import compute_metrics
from extract_trades import load_normalized_trades

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _coerce_scalar(raw: str) -> Any:
    v = raw.strip().strip('"').strip("'")
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except Exception:
        return v


def _fallback_simple_yaml_load(path: Path) -> Dict[str, Any]:
    """Minimal parser for this project's lock config structure."""
    out: Dict[str, Any] = {}
    current: Optional[str] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith("  ") and line.endswith(":"):
            key = line[:-1].strip()
            out[key] = {}
            current = key
            continue
        if current and ":" in line:
            k, v = line.strip().split(":", 1)
            out[current][k.strip()] = _coerce_scalar(v)
    return out


def _pct_delta(new: float, old: float) -> float:
    if abs(old) < 1e-12:
        return 0.0 if abs(new) < 1e-12 else 100.0
    return ((new - old) / abs(old)) * 100.0


def _evaluate_gates(b: Dict[str, Any], c: Dict[str, Any], gates: Dict[str, Any]) -> List[Dict[str, Any]]:
    min_trades = int(gates.get("min_trades_per_strategy", 100))
    pnl_improvement = _pct_delta(float(c["net_pnl"]), float(b["net_pnl"]))
    dd_increase = _pct_delta(abs(float(c["max_drawdown"])), abs(float(b["max_drawdown"])))
    sharpe_delta = float(c["sharpe_proxy"]) - float(b["sharpe_proxy"])
    pf_delta = float(c["profit_factor"]) - float(b["profit_factor"])

    results = [
        {
            "name": "min_trades",
            "pass": int(b["trades"]) >= min_trades and int(c["trades"]) >= min_trades,
            "detail": f"baseline={b['trades']} candidate={c['trades']} min={min_trades}",
        },
        {
            "name": "net_pnl_improvement_pct",
            "pass": pnl_improvement >= float(gates.get("min_net_pnl_improvement_pct", 5.0)),
            "detail": f"delta={pnl_improvement:.2f}% threshold>={gates.get('min_net_pnl_improvement_pct', 5.0)}%",
        },
        {
            "name": "max_drawdown_increase_pct",
            "pass": dd_increase <= float(gates.get("max_drawdown_increase_pct", 0.0)),
            "detail": f"increase={dd_increase:.2f}% threshold<={gates.get('max_drawdown_increase_pct', 0.0)}%",
        },
        {
            "name": "sharpe_delta",
            "pass": sharpe_delta >= float(gates.get("min_sharpe_delta", 0.0)),
            "detail": f"delta={sharpe_delta:.4f} threshold>={gates.get('min_sharpe_delta', 0.0)}",
        },
        {
            "name": "profit_factor_delta",
            "pass": pf_delta >= float(gates.get("min_profit_factor_delta", 0.0)),
            "detail": f"delta={pf_delta:.4f} threshold>={gates.get('min_profit_factor_delta', 0.0)}",
        },
    ]
    return results


def run_comparison(db_path: str, lock_cfg: Dict[str, Any]) -> Dict[str, Any]:
    baseline_filter = lock_cfg["baseline"]["strategy_filter"]
    candidate_filter = lock_cfg["candidate"]["strategy_filter"]
    cost = lock_cfg["cost_model"]

    b_rows = load_normalized_trades(db_path, baseline_filter)
    c_rows = load_normalized_trades(db_path, candidate_filter)

    b_metrics = compute_metrics(
        b_rows,
        taker_fee_bps=float(cost["taker_fee_bps"]),
        slippage_bps=float(cost["slippage_bps"]),
        funding_bps_per_day=float(cost["funding_bps_per_day"]),
        expected_holding_hours=float(cost["expected_holding_hours"]),
    )
    c_metrics = compute_metrics(
        c_rows,
        taker_fee_bps=float(cost["taker_fee_bps"]),
        slippage_bps=float(cost["slippage_bps"]),
        funding_bps_per_day=float(cost["funding_bps_per_day"]),
        expected_holding_hours=float(cost["expected_holding_hours"]),
    )

    gates = _evaluate_gates(b_metrics, c_metrics, lock_cfg["gates"])
    all_pass = all(g["pass"] for g in gates)

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database": db_path,
        "baseline": {"name": lock_cfg["baseline"]["name"], "metrics": b_metrics},
        "candidate": {"name": lock_cfg["candidate"]["name"], "metrics": c_metrics},
        "gate_results": gates,
        "overall_pass": all_pass,
    }


def write_markdown_report(result: Dict[str, Any], output_path: str) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    b = result["baseline"]
    c = result["candidate"]
    gates = result["gate_results"]

    lines = [
        "# Strategy A/B Validation Report",
        "",
        f"- Timestamp (UTC): `{result['timestamp_utc']}`",
        f"- Database: `{result['database']}`",
        f"- Baseline: `{b['name']}`",
        f"- Candidate: `{c['name']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Baseline | Candidate |",
        "|---|---:|---:|",
    ]
    keys = ["rows", "trades", "gross_pnl", "net_pnl", "max_drawdown", "sharpe_proxy", "profit_factor", "win_rate", "turnover"]
    for k in keys:
        lines.append(f"| {k} | {b['metrics'].get(k, 0)} | {c['metrics'].get(k, 0)} |")

    lines += [
        "",
        "## Gate Results",
        "",
        "| Gate | Pass | Detail |",
        "|---|---|---|",
    ]
    for g in gates:
        lines.append(f"| {g['name']} | {'yes' if g['pass'] else 'no'} | {g['detail']} |")

    lines += [
        "",
        f"## Verdict: {'PASS' if result['overall_pass'] else 'FAIL'}",
        "",
        "PASS means candidate satisfies all locked outperform conditions.",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline vs candidate strategy performance.")
    parser.add_argument("--db", required=True, help="Path to sqlite database")
    parser.add_argument("--lock-config", required=True, help="Path to baseline lock YAML")
    parser.add_argument("--report-json", required=True, help="Output JSON report path")
    parser.add_argument("--report-md", required=True, help="Output Markdown report path")
    args = parser.parse_args()

    lock_path = Path(args.lock_config)
    if yaml is not None:
        cfg = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    else:
        cfg = _fallback_simple_yaml_load(lock_path)
    result = run_comparison(args.db, cfg)

    rj = Path(args.report_json)
    rj.parent.mkdir(parents=True, exist_ok=True)
    rj.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_markdown_report(result, args.report_md)
    print(f"Wrote reports: {args.report_json}, {args.report_md}")


if __name__ == "__main__":
    main()
