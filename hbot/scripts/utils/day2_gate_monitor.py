from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path


def run_once(root: Path) -> int:
    script = root / "scripts" / "utils" / "event_store_count_check.py"
    gate = root / "scripts" / "utils" / "day2_gate_evaluator.py"
    r1 = subprocess.run(["python", str(script)], cwd=str(root), capture_output=True, text=True)
    r2 = subprocess.run(["python", str(gate)], cwd=str(root), capture_output=True, text=True)
    if r1.returncode == 0 and r2.returncode == 0:
        if r2.stdout.strip():
            print(r2.stdout.strip(), flush=True)
        return 0
    if r1.returncode != 0:
        print(r1.stderr.strip(), flush=True)
    if r2.returncode != 0:
        print(r2.stderr.strip(), flush=True)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-sec", type=int, default=int(os.getenv("DAY2_GATE_INTERVAL_SEC", "300")))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    interval = max(30, int(args.interval_sec))
    while True:
        run_once(root)
        time.sleep(interval)


if __name__ == "__main__":
    main()
