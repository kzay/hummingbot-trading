from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _audit_event(action: str, status: str, details: Dict[str, object]) -> Dict[str, object]:
    return {
        "event_id": str(uuid.uuid4()),
        "ts_utc": _utc_now(),
        "action": action,
        "status": status,
        "details": details,
    }


def _load_sample_intents() -> List[Dict[str, object]]:
    return [
        {
            "intent_id": "intent-allow-1",
            "bot": "bot4",
            "action": "place_order",
            "side": "buy",
            "symbol": "BTC/USDT",
            "qty": 0.001,
            "price": 60000.0,
            "max_notional_quote": 100.0,
        },
        {
            "intent_id": "intent-block-1",
            "bot": "bot4",
            "action": "place_order",
            "side": "buy",
            "symbol": "BTC/USDT",
            "qty": 0.01,
            "price": 60000.0,
            "max_notional_quote": 100.0,
        },
        {
            "intent_id": "intent-allow-2",
            "bot": "bot3",
            "action": "place_order",
            "side": "sell",
            "symbol": "BTC/USDT",
            "qty": 0.001,
            "price": 60500.0,
            "max_notional_quote": 100.0,
        },
    ]


def _simulate_paper_adapter(intents: List[Dict[str, object]]) -> Dict[str, object]:
    audit: List[Dict[str, object]] = []
    executed = 0
    vetoed = 0
    lifecycle_ok = 0

    for intent in intents:
        notional = float(intent.get("qty", 0.0)) * float(intent.get("price", 0.0))
        limit = float(intent.get("max_notional_quote", 0.0))
        risk_allow = notional <= limit

        if not risk_allow:
            vetoed += 1
            audit.append(
                _audit_event(
                    "risk_veto",
                    "blocked",
                    {
                        "intent_id": intent.get("intent_id"),
                        "reason": "max_notional_exceeded",
                        "notional_quote": notional,
                        "limit_quote": limit,
                    },
                )
            )
            continue

        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        executed += 1
        lifecycle_ok += 1
        audit.append(
            _audit_event(
                "order_created",
                "ok",
                {"intent_id": intent.get("intent_id"), "order_id": order_id, "notional_quote": notional},
            )
        )
        audit.append(
            _audit_event(
                "order_filled",
                "ok",
                {"intent_id": intent.get("intent_id"), "order_id": order_id, "fill_qty": intent.get("qty")},
            )
        )

    return {
        "adapter": "paper_only_spike",
        "intents_total": len(intents),
        "executed": executed,
        "vetoed": vetoed,
        "lifecycle_ok": lifecycle_ok,
        "audit_events": audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 14 migration spike: minimal execution adapter in paper mode.")
    parser.add_argument("--out-dir", type=str, default="reports/migration_spike", help="Output directory.")
    args = parser.parse_args()

    root = _root()
    intents = _load_sample_intents()
    result = _simulate_paper_adapter(intents)

    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = out_dir / f"execution_adapter_spike_{stamp}.json"
    out_audit = out_dir / f"execution_adapter_audit_{stamp}.jsonl"

    payload = {
        "ts_utc": _utc_now(),
        "status": "pass" if result["executed"] > 0 and result["vetoed"] > 0 else "fail",
        "features_validated": {
            "connector_stub": True,
            "order_lifecycle": bool(result["lifecycle_ok"] > 0),
            "risk_veto": bool(result["vetoed"] > 0),
            "audit_trail": bool(len(result["audit_events"]) > 0),
        },
        "summary": {k: v for k, v in result.items() if k != "audit_events"},
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with out_audit.open("w", encoding="utf-8") as f:
        for row in result["audit_events"]:
            f.write(json.dumps(row) + "\n")
    (out_dir / "latest_audit.jsonl").write_text(out_audit.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"[migration-spike] status={payload['status']}")
    print(f"[migration-spike] evidence={out_json}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
