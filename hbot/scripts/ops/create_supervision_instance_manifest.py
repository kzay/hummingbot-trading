#!/usr/bin/env python3
"""Create or update supervision discovery metadata for a bot instance.

This helper makes a bot visible to the realtime supervision UI before it emits
live stream traffic or writes desk snapshot artifacts.

Usage:
  python hbot/scripts/ops/create_supervision_instance_manifest.py --instance bot8
  python hbot/scripts/ops/create_supervision_instance_manifest.py --instance bot8 --controller-id epp_v2_4_bot8 --trading-pair BTC-USDT --label "Bot 8"
  python hbot/scripts/ops/create_supervision_instance_manifest.py --instance bot8 --create-marker

The script writes:
  - data/<instance>/conf/instance_meta.json
Optionally also touches:
  - data/<instance>/.supervision_enabled
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or update supervision discovery metadata for a bot instance.")
    parser.add_argument("--root", default="hbot", help="Workspace root that contains the data/ directory. Default: hbot")
    parser.add_argument("--instance", required=True, help="Bot instance name, e.g. bot8")
    parser.add_argument("--controller-id", default="", help="Optional controller identifier to surface in the supervision UI")
    parser.add_argument("--trading-pair", default="", help="Optional trading pair, e.g. BTC-USDT")
    parser.add_argument("--label", default="", help="Optional display label for the supervision UI")
    parser.add_argument(
        "--visible-in-supervision",
        dest="visible_in_supervision",
        action="store_true",
        default=True,
        help="Mark the instance as explicitly visible in supervision (default: true)",
    )
    parser.add_argument(
        "--no-visible-in-supervision",
        dest="visible_in_supervision",
        action="store_false",
        help="Write the manifest with visible_in_supervision=false",
    )
    parser.add_argument(
        "--create-marker",
        action="store_true",
        help="Also create data/<instance>/.supervision_enabled for simple marker-based discovery",
    )
    return parser


def run(
    root: Path,
    *,
    instance: str,
    controller_id: str,
    trading_pair: str,
    label: str,
    visible_in_supervision: bool,
    create_marker: bool,
) -> dict[str, Any]:
    instance_name = str(instance or "").strip()
    if not instance_name:
        raise ValueError("instance is required")

    data_dir = root / "data" / instance_name
    conf_dir = data_dir / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = conf_dir / "instance_meta.json"
    current = _read_json(manifest_path)
    payload: dict[str, Any] = dict(current)
    payload["visible_in_supervision"] = bool(visible_in_supervision)

    if label:
        payload["label"] = str(label).strip()
    elif "label" not in payload:
        payload["label"] = instance_name

    if controller_id:
        payload["controller_id"] = str(controller_id).strip()
    elif "controller_id" not in payload:
        payload["controller_id"] = ""

    if trading_pair:
        payload["trading_pair"] = str(trading_pair).strip().upper()
    elif "trading_pair" not in payload:
        payload["trading_pair"] = ""

    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    marker_path = data_dir / ".supervision_enabled"
    if create_marker:
        marker_path.write_text("", encoding="utf-8")

    return {
        "instance": instance_name,
        "manifest_path": str(manifest_path),
        "marker_path": str(marker_path) if create_marker else "",
        "manifest": payload,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = run(
        Path(args.root).resolve(),
        instance=args.instance,
        controller_id=args.controller_id,
        trading_pair=args.trading_pair,
        label=args.label,
        visible_in_supervision=bool(args.visible_in_supervision),
        create_marker=bool(args.create_marker),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
