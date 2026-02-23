from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _compose_cmd(root: Path) -> List[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(root / "env" / ".env"),
        "-f",
        str(root / "compose" / "docker-compose.yml"),
        "config",
    ]


def _run_config_with_target(root: Path, target_image: str) -> Dict[str, object]:
    env = dict(**os.environ)
    env["HUMMINGBOT_IMAGE"] = target_image
    cmd = _compose_cmd(root)
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=env)
        return {
            "cmd": cmd,
            "rc": int(proc.returncode),
            "stdout": (proc.stdout or "")[:3000],
            "stderr": (proc.stderr or "")[:3000],
        }
    except Exception as exc:
        return {"cmd": cmd, "rc": 2, "stdout": "", "stderr": str(exc)}


def _load_env_secret_values(root: Path) -> List[str]:
    env_path = root / "env" / ".env"
    values: List[str] = []
    if not env_path.exists():
        return values
    secret_key_hints = ("KEY", "SECRET", "PASSPHRASE", "TOKEN", "PASSWORD")
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if any(h in key for h in secret_key_hints):
            if value and value.lower() not in {"changeme", "example", "your_value_here", "xxxxx"} and len(value) >= 8:
                values.append(value)
    return values


def _sanitize_text(text: str, secret_values: List[str]) -> str:
    out = text
    for secret in secret_values:
        if secret:
            out = out.replace(secret, "***redacted-secret***")
    # Generic redact for common inline patterns.
    out = re.sub(
        r"(?i)\b(api[_-]?key|secret|passphrase|token|password)\s*[:=]\s*([^\s\"']{4,}|\"[^\"]+\"|'[^']+')",
        r"\1=***redacted***",
        out,
    )
    return out


def _current_default_image(compose_text: str) -> str:
    m = re.search(r"\$\{HUMMINGBOT_IMAGE:-([^}]+)\}", compose_text)
    return m.group(1).strip() if m else ""


def _write_report(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run readiness check for Hummingbot image upgrades.")
    parser.add_argument("--target-image", required=True, help="Candidate HUMMINGBOT_IMAGE tag.")
    args = parser.parse_args()

    root = _root()
    compose_path = root / "compose" / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    current_default = _current_default_image(compose_text)
    target_image = str(args.target_image).strip()

    compose_check = _run_config_with_target(root, target_image)
    secret_values = _load_env_secret_values(root)
    compose_check["stdout"] = _sanitize_text(str(compose_check.get("stdout", "")), secret_values)[:3000]
    compose_check["stderr"] = _sanitize_text(str(compose_check.get("stderr", "")), secret_values)[:3000]
    render_ok = int(compose_check.get("rc", 1)) == 0
    changed = bool(current_default) and current_default != target_image

    status = "pass" if render_ok and changed else "fail"
    checks = {
        "compose_render_with_target": bool(render_ok),
        "target_differs_from_current_default": bool(changed),
    }
    notes: List[str] = []
    if not changed:
        notes.append("target image equals current default; no upgrade delta")
    if not render_ok:
        notes.append("compose config render failed with target image override")

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "target_image": target_image,
        "current_default_image": current_default,
        "checks": checks,
        "compose_check": compose_check,
        "notes": notes,
    }

    out_dir = root / "reports" / "upgrade"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"hb_upgrade_readiness_{stamp}.json"
    _write_report(out, payload)
    _write_report(out_dir / "latest.json", payload)

    print(f"[hb-upgrade-readiness] status={status}")
    print(f"[hb-upgrade-readiness] evidence={out}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
