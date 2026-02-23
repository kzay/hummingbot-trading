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


def _read_yaml_like(path: Path) -> Dict[str, object]:
    """
    Minimal parser for key-value + list blocks used in local bot conf files.
    It intentionally supports only the subset needed by consistency checks.
    """
    out: Dict[str, object] = {}
    current_list_key = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- ") and current_list_key:
            arr = out.setdefault(current_list_key, [])
            if isinstance(arr, list):
                arr.append(line[2:].strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            out[key] = []
            current_list_key = key
            continue
        current_list_key = ""
        out[key] = value.strip("\"'")
    return out


def _check_catalog(root: Path) -> Tuple[bool, List[str], Dict[str, object]]:
    catalog_path = root / "config" / "strategy_catalog" / "catalog_v1.json"
    template_controller = root / "config" / "strategy_catalog" / "templates" / "controller_template.yml"
    template_script = root / "config" / "strategy_catalog" / "templates" / "script_template.yml"
    controllers_root = root / "controllers"

    errors: List[str] = []
    catalog = _read_json(catalog_path)
    bundles = catalog.get("approved_bundles", [])
    if not isinstance(bundles, list) or not bundles:
        raise ValueError("catalog_v1.json must contain a non-empty approved_bundles list")

    if not template_controller.exists():
        errors.append("missing controller template")
    if not template_script.exists():
        errors.append("missing script template")
    if not controllers_root.exists():
        errors.append("missing controllers root directory")

    checked_bundles: List[str] = []
    for item in bundles:
        if not isinstance(item, dict):
            errors.append("invalid bundle entry: expected object")
            continue
        bundle_id = str(item.get("bundle_id", "")).strip() or "unknown_bundle"
        checked_bundles.append(bundle_id)

        script_rel = str(item.get("script_config", "")).strip()
        controller_rel = str(item.get("controller_config", "")).strip()
        if not script_rel or not controller_rel:
            errors.append(f"{bundle_id}: missing script_config or controller_config")
            continue

        script_path = root / script_rel
        controller_path = root / controller_rel
        if not script_path.exists():
            errors.append(f"{bundle_id}: missing script config {script_rel}")
            continue
        if not controller_path.exists():
            errors.append(f"{bundle_id}: missing controller config {controller_rel}")
            continue

        script_payload = _read_yaml_like(script_path)
        controller_payload = _read_yaml_like(controller_path)

        expected_controller_name = controller_path.name
        script_controllers = script_payload.get("controllers_config", [])
        if not isinstance(script_controllers, list) or expected_controller_name not in script_controllers:
            errors.append(
                f"{bundle_id}: script config does not reference expected controller file {expected_controller_name}"
            )

        controller_name = str(controller_payload.get("controller_name", "")).strip()
        if not controller_name:
            errors.append(f"{bundle_id}: controller_name is missing in {controller_rel}")
        else:
            controller_code = controllers_root / f"{controller_name}.py"
            if not controller_code.exists():
                errors.append(
                    f"{bundle_id}: shared controller code missing for controller_name={controller_name} ({controller_code})"
                )

    details = {
        "catalog_path": str(catalog_path),
        "templates": [str(template_controller), str(template_script)],
        "controllers_root": str(controllers_root),
        "checked_bundles": checked_bundles,
    }
    return len(errors) == 0, errors, details


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "strategy_catalog"
    reports_root.mkdir(parents=True, exist_ok=True)

    try:
        ok, errors, details = _check_catalog(root)
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
            "errors": [f"catalog consistency exception: {exc}"],
            "details": {},
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = reports_root / f"strategy_catalog_check_{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[strategy-catalog] status={payload['status']}")
    print(f"[strategy-catalog] evidence={out_file}")
    if payload.get("errors"):
        for error in payload["errors"]:
            print(f"[strategy-catalog] error={error}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
