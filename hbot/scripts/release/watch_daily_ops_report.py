from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="Periodically regenerate daily ops report.")
    parser.add_argument("--interval-sec", type=int, default=900, help="Seconds between report generations.")
    parser.add_argument("--max-runs", type=int, default=0, help="Stop after N runs (0 for infinite).")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    run_count = 0

    while True:
        run_count += 1
        date_label = _today()
        cmd = [
            sys.executable,
            str(root / "scripts" / "release" / "generate_daily_ops_report.py"),
            "--date",
            date_label,
        ]
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        print(f"[daily-ops-watch] run={run_count} date={date_label} rc={proc.returncode} out={out}")
        if err:
            print(f"[daily-ops-watch] stderr={err}")

        if args.max_runs > 0 and run_count >= args.max_runs:
            break
        time.sleep(max(60, args.interval_sec))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
