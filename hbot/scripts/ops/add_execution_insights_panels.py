from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def _row(panel_id: int, title: str, y: int) -> Dict[str, Any]:
    return {
        "type": "row",
        "id": panel_id,
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
    }


def _stat(panel_id: int, title: str, expr: str, x: int, y: int, unit: str, decimals: int = 2) -> Dict[str, Any]:
    ds = {"type": "prometheus", "uid": "prometheus"}
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "gridPos": {"h": 4, "w": 4, "x": x, "y": y},
        "datasource": ds,
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "horizontal",
            "textMode": "auto",
            "graphMode": "none",
            "colorMode": "background",
        },
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals}},
        "targets": [{"datasource": ds, "expr": expr, "refId": "A", "instant": True}],
    }


def _timeseries(panel_id: int, title: str, x: int, y: int, targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {"defaults": {"drawStyle": "line", "lineWidth": 2, "showPoints": "never"}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "single"}},
        "targets": targets,
    }


def main() -> None:
    raw = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = raw.get("panels", [])
    ids = {int(p.get("id", -1)) for p in panels if isinstance(p.get("id"), int)}
    if 270 in ids:
        print("execution insight panels already present")
        return

    # Insert below Execution - Open Orders block (currently starts at y=12).
    for p in panels:
        gp = p.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int) and int(gp["y"]) >= 12:
            gp["y"] = int(gp["y"]) + 13

    inserts: List[Dict[str, Any]] = [
        _row(270, "Execution Insights", 12),
        _stat(271, "Open Orders", 'hbot_bot_open_orders_total{bot=~"$bot",variant=~"$variant"}', 0, 13, "short", 0),
        _stat(272, "Book Imbalance", 'hbot_bot_book_imbalance{bot=~"$bot",variant=~"$variant"}', 4, 13, "percentunit", 3),
        _stat(273, "Fills 5m", 'hbot_bot_fills_5m_count{bot=~"$bot",variant=~"$variant"}', 8, 13, "short", 0),
        _stat(274, "Fills 1h", 'hbot_bot_fills_1h_count{bot=~"$bot",variant=~"$variant"}', 12, 13, "short", 0),
        _stat(275, "Realized PnL 1h", 'hbot_bot_realized_pnl_1h_quote{bot=~"$bot",variant=~"$variant"}', 16, 13, "currencyUSD", 2),
        _stat(276, "Mid Price", 'hbot_bot_mid_price{bot=~"$bot",variant=~"$variant"}', 20, 13, "currencyUSD", 2),
        _timeseries(
            277,
            "Execution Costs (bps)",
            0,
            17,
            [
                {
                    "refId": "A",
                    "expr": 'hbot_bot_fill_slippage_bps_sum{bot=~"$bot",variant=~"$variant"} / clamp_min(hbot_bot_fill_slippage_bps_count{bot=~"$bot",variant=~"$variant"}, 1)',
                    "legendFormat": "Avg Slippage bps",
                },
                {
                    "refId": "B",
                    "expr": 'hbot_bot_fee_bps_sum{bot=~"$bot",variant=~"$variant"} / clamp_min(hbot_bot_fee_bps_count{bot=~"$bot",variant=~"$variant"}, 1)',
                    "legendFormat": "Avg Fee bps",
                },
            ],
        ),
        _timeseries(
            278,
            "Orderflow & Depth",
            12,
            17,
            [
                {
                    "refId": "A",
                    "expr": 'hbot_bot_open_orders_buy{bot=~"$bot",variant=~"$variant"}',
                    "legendFormat": "Open BUY",
                },
                {
                    "refId": "B",
                    "expr": 'hbot_bot_open_orders_sell{bot=~"$bot",variant=~"$variant"}',
                    "legendFormat": "Open SELL",
                },
                {
                    "refId": "C",
                    "expr": 'hbot_bot_best_bid_size{bot=~"$bot",variant=~"$variant"}',
                    "legendFormat": "Best Bid Size",
                },
                {
                    "refId": "D",
                    "expr": 'hbot_bot_best_ask_size{bot=~"$bot",variant=~"$variant"}',
                    "legendFormat": "Best Ask Size",
                },
            ],
        ),
    ]

    raw["panels"] = inserts + panels
    DASHBOARD_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
