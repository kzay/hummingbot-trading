from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _compose_cmd(*args: str) -> List[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "env/.env",
        "-f",
        "compose/docker-compose.yml",
        *args,
    ]


def _run_cmd(root: Path, cmd: List[str], label: str) -> Dict[str, object]:
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    return {
        "name": label,
        "cmd": cmd,
        "rc": int(proc.returncode),
        "stdout": (proc.stdout or "")[:2000],
        "stderr": (proc.stderr or "")[:2000],
    }


def _run_pytest_style_module(module_name: str) -> Dict[str, object]:
    module = importlib.import_module(module_name)
    failures: List[str] = []
    total = 0
    for name in sorted(dir(module)):
        if not name.startswith("test_"):
            continue
        fn = getattr(module, name)
        if not callable(fn):
            continue
        total += 1
        try:
            fn()
        except Exception as exc:
            failures.append(f"{module_name}.{name}: {exc}")
    return {
        "module": module_name,
        "total_tests": total,
        "failures": failures,
        "pass": len(failures) == 0 and total > 0,
    }


def _check_minimal_smoke(root: Path) -> Dict[str, object]:
    minute_files = sorted((root / "data" / "bot4" / "logs").glob("epp_v24/*/minute.csv"))
    snapshot_path = root / "reports" / "exchange_snapshots" / "latest.json"
    snapshot_ok = False
    snapshot_mode = ""
    snapshot_reason = "snapshot_missing_or_invalid"
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_mode = str(snapshot.get("mode", "")).strip().lower() if isinstance(snapshot, dict) else ""
            bots = snapshot.get("bots", {}) if isinstance(snapshot, dict) else {}
            bot3 = bots.get("bot3", {}) if isinstance(bots, dict) else {}
            paper_mode_marked = (
                isinstance(bot3, dict)
                and str(bot3.get("account_mode", "")) == "paper_only"
                and str(bot3.get("account_probe_status", "")) == "paper_only"
            )
            # In proxy_local mode, account probe fields are intentionally absent.
            # Accept bot3 paper exchange identity as minimal smoke evidence.
            proxy_local_paper = (
                isinstance(bot3, dict)
                and snapshot_mode == "proxy_local"
                and "paper" in str(bot3.get("exchange", "")).lower()
            )
            snapshot_ok = paper_mode_marked or proxy_local_paper
            if paper_mode_marked:
                snapshot_reason = "bot3_paper_only_probe_mode"
            elif proxy_local_paper:
                snapshot_reason = "bot3_paper_exchange_in_proxy_local_mode"
            else:
                snapshot_reason = "bot3_not_marked_as_paper"
        except Exception:
            snapshot_ok = False
            snapshot_reason = "snapshot_parse_error"
    return {
        "bot4_minute_artifacts_found": len(minute_files) > 0,
        "bot4_minute_sample": str(minute_files[-1]) if minute_files else "",
        "bot3_paper_snapshot_ok": snapshot_ok,
        "bot3_paper_snapshot_reason": snapshot_reason,
        "snapshot_mode": snapshot_mode,
        "snapshot_path": str(snapshot_path),
    }


def _run_unit_checks_in_control_plane(root: Path, modules: List[str]) -> Dict[str, object]:
    marker = "__UNIT_JSON__"
    py_code = "\n".join(
        [
            "import importlib",
            "import json",
            f"mods = {json.dumps(modules)}",
            "results = []",
            "all_ok = True",
            "for m in mods:",
            "    mod = importlib.import_module(m)",
            "    fails = []",
            "    total = 0",
            "    for n in sorted([x for x in dir(mod) if x.startswith('test_')]):",
            "        fn = getattr(mod, n)",
            "        if not callable(fn):",
            "            continue",
            "        total += 1",
            "        try:",
            "            fn()",
            "        except Exception as e:",
            "            fails.append(f'{m}.{n}: {e}')",
            "    ok = (len(fails) == 0 and total > 0)",
            "    all_ok = all_ok and ok",
            "    results.append({'module': m, 'total_tests': total, 'failures': fails, 'pass': ok})",
            f"print('{marker}' + json.dumps(results))",
            "raise SystemExit(0 if all_ok else 1)",
        ]
    )
    cmd = _compose_cmd("run", "--rm", "daily-ops-reporter", "python", "-c", py_code)
    result = _run_cmd(root, cmd, "unit_checks_control_plane")
    parsed: List[Dict[str, object]] = []
    for line in str(result.get("stdout", "")).splitlines():
        if line.startswith(marker):
            raw = line[len(marker) :].strip()
            try:
                payload = json.loads(raw)
                if isinstance(payload, list):
                    parsed = payload
            except Exception:
                parsed = []
    return {"runner": result, "results": parsed}


def _write_report(root: Path, payload: Dict[str, object]) -> Path:
    out_dir = root / "reports" / "dev_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"dev_fast_checks_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def cmd_fast_checks(root: Path) -> int:
    syntax = _run_cmd(root, [sys.executable, "-m", "compileall", "controllers", "services", "scripts", "tests"], "compileall")
    unit_modules = [
        "tests.services.test_event_schemas",
        "tests.controllers.test_paper_engine_v2",
    ]
    unit_runner_payload = _run_unit_checks_in_control_plane(root, unit_modules)
    unit_results = (
        unit_runner_payload.get("results", [])
        if isinstance(unit_runner_payload.get("results", []), list)
        else []
    )
    if not unit_results:
        # fallback for environments where Docker is unavailable
        unit_results = []
        for m in unit_modules:
            try:
                unit_results.append(_run_pytest_style_module(m))
            except Exception as exc:
                unit_results.append({"module": m, "total_tests": 0, "failures": [str(exc)], "pass": False})
    smoke = _check_minimal_smoke(root)

    unit_ok = all(bool(r.get("pass")) for r in unit_results)
    smoke_ok = bool(smoke.get("bot4_minute_artifacts_found")) and bool(smoke.get("bot3_paper_snapshot_ok"))
    status = "pass" if int(syntax.get("rc", 1)) == 0 and unit_ok and smoke_ok else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "checks": {
            "lint_compileall": syntax,
            "unit_runner": unit_runner_payload.get("runner", {}),
            "unit_lightweight": unit_results,
            "minimal_smoke": smoke,
        },
    }
    out = _write_report(root, payload)
    print(f"[dev-fast-checks] status={status}")
    print(f"[dev-fast-checks] evidence={out}")
    return 0 if status == "pass" else 1


def cmd_compose(root: Path, profile: str, action: str) -> int:
    if action == "up":
        cmd = _compose_cmd("--profile", profile, "up", "-d")
    else:
        cmd = _compose_cmd("--profile", profile, "down")
    proc = subprocess.run(cmd, cwd=str(root), check=False)
    return int(proc.returncode)


def cmd_clear_pyc(root: Path, bot: str) -> int:
    container = f"hbot-{bot}"
    cmd = [
        "docker",
        "exec",
        container,
        "sh",
        "-lc",
        "rm -rf /home/hummingbot/controllers/__pycache__ /home/hummingbot/controllers/market_making/__pycache__",
    ]
    proc = subprocess.run(cmd, cwd=str(root), check=False)
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 11 local development workflow helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fast-checks", help="Run fast lint/unit/minimal-smoke checks.")
    sub.add_parser("up-test", help="Start test profile.")
    sub.add_parser("down-test", help="Stop test profile.")
    sub.add_parser("up-external", help="Start external profile.")
    sub.add_parser("down-external", help="Stop external profile.")
    clear_pyc = sub.add_parser("clear-pyc", help="Clear controller bytecode cache in a bot container.")
    clear_pyc.add_argument("--bot", default="bot1", help="Bot container suffix (e.g. bot1, bot3, bot4).")

    args = parser.parse_args()
    root = _root()

    if args.command == "fast-checks":
        return cmd_fast_checks(root)
    if args.command == "up-test":
        return cmd_compose(root, "test", "up")
    if args.command == "down-test":
        return cmd_compose(root, "test", "down")
    if args.command == "up-external":
        return cmd_compose(root, "external", "up")
    if args.command == "down-external":
        return cmd_compose(root, "external", "down")
    if args.command == "clear-pyc":
        return cmd_clear_pyc(root, args.bot)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
