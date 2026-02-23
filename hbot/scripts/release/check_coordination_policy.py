from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object in {path}")
    return payload


def _service_block(compose_text: str, service_name: str) -> str:
    marker = f"  {service_name}:"
    start = compose_text.find(marker)
    if start < 0:
        return ""
    rest = compose_text[start:]
    lines = rest.splitlines()
    out: List[str] = []
    first = True
    for line in lines:
        if not first and line.startswith("  ") and not line.startswith("    "):
            break
        out.append(line)
        first = False
    return "\n".join(out)


def _check(root: Path) -> Tuple[bool, List[str], Dict[str, object]]:
    errors: List[str] = []
    policy_path = root / "config" / "coordination_policy_v1.json"
    multi_path = root / "config" / "multi_bot_policy_v1.json"
    compose_path = root / "compose" / "docker-compose.yml"

    policy = _read_json(policy_path)
    multi = _read_json(multi_path)
    compose_text = compose_path.read_text(encoding="utf-8")
    block = _service_block(compose_text, "coordination-service")
    if not block:
        errors.append("coordination-service block missing in compose file")

    allowed = policy.get("allowed_instances", [])
    if not isinstance(allowed, list) or not allowed:
        errors.append("coordination policy requires non-empty allowed_instances")
        allowed_set = set()
    else:
        allowed_set = {str(x) for x in allowed}

    bots = multi.get("bots", {})
    bot_cfg = bots if isinstance(bots, dict) else {}
    for instance in sorted(allowed_set):
        cfg = bot_cfg.get(instance, {})
        if not isinstance(cfg, dict):
            errors.append(f"{instance}: missing in multi_bot_policy_v1")
            continue
        if not bool(cfg.get("enabled", False)):
            errors.append(f"{instance}: coordination allowed_instances must be enabled in multi_bot_policy_v1")
        mode = str(cfg.get("mode", "")).strip().lower()
        if mode not in {"live", "testnet_probe"}:
            errors.append(f"{instance}: coordination allowed mode must be live/testnet_probe, got {mode or 'unset'}")

    target_cfg = policy.get("target_base_pct", {})
    if not isinstance(target_cfg, dict):
        errors.append("coordination policy target_base_pct must be an object")
    else:
        min_v = float(target_cfg.get("min", 0.25))
        max_v = float(target_cfg.get("max", 0.75))
        if not (0.0 <= min_v <= max_v <= 1.0):
            errors.append(f"target_base_pct bounds invalid: min={min_v} max={max_v}")

    required_compose_tokens = [
        "COORD_POLICY_PATH=/workspace/hbot/config/coordination_policy_v1.json",
        "COORD_ENABLED=${COORD_ENABLED:-false}",
        "COORD_REQUIRE_ML_ENABLED=${COORD_REQUIRE_ML_ENABLED:-true}",
        "COORD_HEALTH_PATH=/workspace/hbot/reports/coordination/latest.json",
    ]
    for token in required_compose_tokens:
        if token not in block:
            errors.append(f"coordination-service compose env missing token: {token}")

    details = {
        "policy_path": str(policy_path),
        "multi_bot_policy_path": str(multi_path),
        "compose_path": str(compose_path),
        "allowed_instances": sorted(allowed_set),
    }
    return len(errors) == 0, errors, details


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "policy"
    reports_root.mkdir(parents=True, exist_ok=True)

    try:
        ok, errors, details = _check(root)
        payload = {
            "ts_utc": _utc_now(),
            "status": "pass" if ok else "fail",
            "errors": errors,
            "details": details,
        }
    except Exception as exc:
        payload = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "errors": [f"coordination policy check exception: {exc}"],
            "details": {},
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = reports_root / f"coordination_policy_check_{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "coordination_policy_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[coord-policy] status={payload['status']}")
    print(f"[coord-policy] evidence={out_file}")
    if payload.get("errors"):
        for error in payload["errors"]:
            print(f"[coord-policy] error={error}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
