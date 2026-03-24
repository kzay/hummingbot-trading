#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import redis  # type: ignore


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _safe_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _resolve_daily_state_path(root: Path, instance_name: str, variant: str) -> Path | None:
    base = root / "data" / instance_name / "logs" / "epp_v24" / f"{instance_name}_{variant}"
    if not base.exists():
        return None
    candidates = sorted(base.glob("daily_state_*_paper.json"))
    if not candidates:
        return None
    return candidates[0]


def _compute_equity_from_paper_desk(
    paper_desk_payload: dict[str, object], equity_source: str
) -> Decimal:
    portfolio = paper_desk_payload.get("portfolio", {})
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    balances = portfolio.get("balances", {})
    balances = balances if isinstance(balances, dict) else {}
    equity = _safe_decimal(balances.get("USDT"), Decimal("0"))
    positions = portfolio.get("positions", {})
    positions = positions if isinstance(positions, dict) else {}
    source = str(equity_source).strip().lower() or "controller_compatible"
    if source == "controller_compatible":
        # Match controller risk basis for perp mode:
        # quote balance + unrealized of perp positions only.
        for key, raw in positions.items():
            if ":perp" not in str(key):
                continue
            if not isinstance(raw, dict):
                continue
            equity += _safe_decimal(raw.get("unrealized_pnl"), Decimal("0"))
        return equity
    for raw in positions.values():
        if not isinstance(raw, dict):
            continue
        equity += _safe_decimal(raw.get("unrealized_pnl"), Decimal("0"))
    return equity


def run(
    *,
    instance_name: str,
    variant: str,
    redis_host: str,
    redis_port: int,
    redis_db: int,
    redis_password: str,
    root: Path,
    equity_source: str,
) -> int:
    redis_client = redis.Redis(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=(redis_password or None),
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
    )

    daily_state_key = f"epp:daily_state:{instance_name}:{variant}"
    paper_desk_key = f"paper_desk:v2:{instance_name}:{variant}"

    raw_daily = redis_client.get(daily_state_key)
    raw_desk = redis_client.get(paper_desk_key)
    if not raw_desk:
        print(f"[paper-baseline-reset] missing Redis key: {paper_desk_key}")
        return 2

    daily_state = json.loads(raw_daily) if raw_daily else {}
    if not isinstance(daily_state, dict):
        daily_state = {}
    paper_desk = json.loads(raw_desk)
    if not isinstance(paper_desk, dict):
        print(f"[paper-baseline-reset] invalid payload in key: {paper_desk_key}")
        return 2

    equity = _compute_equity_from_paper_desk(paper_desk, equity_source=equity_source)
    if equity <= Decimal("0"):
        print(f"[paper-baseline-reset] non-positive computed equity: {equity}")
        return 2

    today = _today_utc()
    daily_state["day_key"] = today
    daily_state["equity_open"] = str(equity)
    daily_state["equity_peak"] = str(equity)
    daily_state["traded_notional"] = "0"
    daily_state["fills_count"] = 0
    daily_state["fees_paid"] = "0"
    daily_state["funding_cost"] = "0"
    daily_state["realized_pnl"] = "0"
    daily_state["ts_utc"] = _utc_now()

    portfolio = paper_desk.get("portfolio", {})
    if isinstance(portfolio, dict):
        portfolio["daily_open_equity"] = str(equity)
        paper_desk["portfolio"] = portfolio
    paper_desk["ts_utc"] = _utc_now()

    redis_client.set(daily_state_key, json.dumps(daily_state), ex=172800)
    redis_client.set(paper_desk_key, json.dumps(paper_desk), ex=172800)

    daily_state_path = _resolve_daily_state_path(root, instance_name, variant)
    if daily_state_path is not None:
        _write_json(daily_state_path, daily_state)
    paper_desk_path = root / "data" / instance_name / "logs" / "epp_v24" / f"{instance_name}_{variant}" / "paper_desk_v2.json"
    if paper_desk_path.exists():
        _write_json(paper_desk_path, paper_desk)

    print(
        "[paper-baseline-reset] reset applied "
        f"instance={instance_name} variant={variant} equity_open={equity} equity_source={equity_source}"
    )
    if daily_state_path is not None:
        print(f"[paper-baseline-reset] daily_state_path={daily_state_path}")
    print(f"[paper-baseline-reset] redis_daily_key={daily_state_key}")
    print(f"[paper-baseline-reset] redis_desk_key={paper_desk_key}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset paper daily baseline to current PaperDesk equity.")
    parser.add_argument("--instance-name", default="bot1")
    parser.add_argument("--variant", default="a")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-db", type=int, default=0)
    parser.add_argument("--redis-password", default="")
    parser.add_argument(
        "--equity-source",
        default="controller_compatible",
        choices=["controller_compatible", "portfolio_equity"],
        help=(
            "Baseline equity source. controller_compatible uses USDT cash only "
            "(matches current controller risk basis); portfolio_equity includes unrealized PnL."
        ),
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    return run(
        instance_name=str(args.instance_name),
        variant=str(args.variant),
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password),
        root=root,
        equity_source=str(args.equity_source),
    )


if __name__ == "__main__":
    raise SystemExit(main())

