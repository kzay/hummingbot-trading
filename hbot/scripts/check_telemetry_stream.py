"""Quick check: inspect the BOT_TELEMETRY_STREAM for paper fill events."""
import json
import os
import sys

sys.path.insert(0, "/home/hummingbot/controllers")
sys.path.insert(0, "/home/hummingbot/services")

import redis

r = redis.Redis(host="redis", port=6379, decode_responses=True)

msgs = r.xrevrange("hb.bot_telemetry.v1", count=10)
if not msgs:
    print("hb.bot_telemetry.v1: stream empty or no messages yet")
else:
    print(f"hb.bot_telemetry.v1: {len(msgs)} recent messages")
    for mid, d in msgs:
        try:
            p = json.loads(d.get("payload", "{}"))
        except Exception:
            p = {}
        print(
            f"  id={mid}"
            f"  type={p.get('event_type', '?')}"
            f"  src={p.get('accounting_source', '?')}"
            f"  prod={p.get('producer', '?')}"
            f"  side={p.get('side', '?')}"
            f"  price={p.get('price', '?')}"
            f"  qty={p.get('amount_base', '?')}"
        )

# Also check fills.csv vs event_store for comparison
from pathlib import Path
import csv

fills_path = Path("/home/hummingbot/logs/epp_v24/bot1_a/fills.csv")
if fills_path.exists():
    lines = fills_path.read_text().splitlines()
    print(f"\nfills.csv: {len(lines)-1} fills total")
    print("  last 3:")
    for line in lines[-3:]:
        print(f"    {line[:120]}")
