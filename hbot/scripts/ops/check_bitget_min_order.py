"""Validate Bitget minimum order constraints before live smoke (Day 85).

Queries Bitget perpetual market limits via ccxt and prints the minimum
order size, minimum cost, and a recommended ``total_amount_quote`` value
for the controller YAML.

Run this script before switching bot1 from testnet to live. A recommended
value of ``total_amount_quote`` is printed that satisfies the exchange
minimum with a 20% buffer.

Usage::

    # Reads credentials from environment (.env must be loaded or exported):
    python hbot/scripts/ops/check_bitget_min_order.py

    # Explicit symbol:
    python hbot/scripts/ops/check_bitget_min_order.py --symbol BTC/USDT:USDT

    # Dry-run (no credentials required — uses public market data):
    python hbot/scripts/ops/check_bitget_min_order.py --public
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def _load_env() -> None:
    env_path = Path(__file__).parents[3] / "env" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _check(symbol: str, public: bool) -> dict:
    try:
        import ccxt
    except ImportError:
        print("ERROR: ccxt not installed. Run: pip install ccxt", file=sys.stderr)
        sys.exit(1)

    if public:
        exchange = ccxt.bitget({"options": {"defaultType": "swap"}})
    else:
        api_key = os.environ.get("BOT1_BITGET_API_KEY", "")
        secret = os.environ.get("BOT1_BITGET_API_SECRET", "")
        passphrase = os.environ.get("BOT1_BITGET_PASSPHRASE", "")
        if not all([api_key, secret, passphrase]):
            print(
                "WARNING: BOT1_BITGET_API_KEY / BOT1_BITGET_API_SECRET / "
                "BOT1_BITGET_PASSPHRASE not set in environment. "
                "Falling back to public market data (no auth).",
                file=sys.stderr,
            )
        exchange = ccxt.bitget(
            {
                "apiKey": api_key,
                "secret": secret,
                "password": passphrase,
                "options": {"defaultType": "swap"},
            }
        )

    markets = exchange.load_markets()
    if symbol not in markets:
        available = [s for s in markets if "BTC" in s and "USDT" in s]
        print(
            f"ERROR: Symbol '{symbol}' not found. BTC/USDT variants available: {available}",
            file=sys.stderr,
        )
        sys.exit(1)

    market = markets[symbol]
    limits = market.get("limits", {})
    precision = market.get("precision", {})

    min_amount = limits.get("amount", {}).get("min")  # base units (BTC)
    max_amount = limits.get("amount", {}).get("max")
    min_cost = limits.get("cost", {}).get("min")      # quote units (USDT)
    amount_precision = precision.get("amount")
    price_precision = precision.get("price")

    # Fetch current mid price to estimate min cost when not directly available
    ticker = exchange.fetch_ticker(symbol)
    mid_price = Decimal(str(ticker.get("last") or ticker.get("close") or 0))

    if min_amount and mid_price:
        min_cost_derived = Decimal(str(min_amount)) * mid_price
    else:
        min_cost_derived = None

    effective_min_cost = Decimal(str(min_cost)) if min_cost else min_cost_derived or Decimal("100")

    # Recommended total_amount_quote = effective minimum + 20% buffer, rounded up to nearest $10
    buffer_pct = Decimal("1.20")
    raw_recommended = effective_min_cost * buffer_pct
    recommended = (int(raw_recommended / 10) + 1) * 10  # round up to next $10

    result = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mid_price_usdt": float(mid_price) if mid_price else None,
        "min_amount_base": min_amount,
        "max_amount_base": max_amount,
        "min_cost_usdt_exchange": float(min_cost) if min_cost else None,
        "min_cost_usdt_derived": float(min_cost_derived) if min_cost_derived else None,
        "effective_min_cost_usdt": float(effective_min_cost),
        "amount_precision": amount_precision,
        "price_precision": price_precision,
        "recommended_total_amount_quote": recommended,
        "assessment": None,
        "action_required": False,
    }

    if recommended <= 50:
        result["assessment"] = "PASS — micro-cap framing valid ($10-50 range)"
        result["action_required"] = False
    elif recommended <= 200:
        result["assessment"] = (
            f"WARN — minimum cost is ~${float(effective_min_cost):.0f} USDT. "
            f"Update total_amount_quote to {recommended} before Day 85."
        )
        result["action_required"] = True
    else:
        result["assessment"] = (
            f"BLOCK — minimum cost is ~${float(effective_min_cost):.0f} USDT (>${recommended} recommended). "
            "Micro-cap framing ($10-50) is invalid for this market. "
            "Halt Day 85 and document revised capital plan in "
            "docs/ops/day85_min_order_assessment.md before proceeding."
        )
        result["action_required"] = True

    return result


def _print_report(result: dict) -> None:
    print()
    print("=" * 60)
    print("  Bitget Minimum Order Check — Day 85 Pre-Flight")
    print("=" * 60)
    print(f"  Symbol          : {result['symbol']}")
    print(f"  Mid price       : ${result['mid_price_usdt']:,.2f} USDT" if result["mid_price_usdt"] else "  Mid price       : unavailable")
    print(f"  Min amount      : {result['min_amount_base']} BTC (base)")
    print(f"  Min cost (exch) : {result['min_cost_usdt_exchange']} USDT")
    print(f"  Min cost (calc) : {result['min_cost_usdt_derived']:.2f} USDT" if result["min_cost_usdt_derived"] else "  Min cost (calc) : unavailable")
    print(f"  Effective min   : ${result['effective_min_cost_usdt']:.2f} USDT")
    print(f"  Recommended     : total_amount_quote: {result['recommended_total_amount_quote']}")
    print()
    status_icon = "✗" if result["action_required"] else "✓"
    print(f"  {status_icon}  {result['assessment']}")
    print("=" * 60)
    print()


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(description="Validate Bitget minimum order size before Day 85 live smoke.")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="ccxt symbol (default: BTC/USDT:USDT)")
    parser.add_argument("--public", action="store_true", help="Use public market data (no API credentials required)")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Output result as JSON")
    parser.add_argument("--out", default=None, help="Write JSON result to file path")
    args = parser.parse_args()

    print(f"Checking Bitget market limits for {args.symbol} ...")
    result = _check(args.symbol, public=args.public)

    if args.output_json or args.out:
        payload = json.dumps(result, indent=2)
        print(payload)
        if args.out:
            Path(args.out).write_text(payload)
            print(f"Result written to {args.out}")
    else:
        _print_report(result)

    if result["action_required"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
