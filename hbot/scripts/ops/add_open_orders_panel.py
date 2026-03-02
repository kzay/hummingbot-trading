from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def _make_row_panel(panel_id: int, title: str, y: int) -> Dict[str, Any]:
    return {
        "type": "row",
        "id": panel_id,
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
    }


def _make_open_orders_table(panel_id: int, y: int) -> Dict[str, Any]:
    ds = {"type": "prometheus", "uid": "prometheus"}
    return {
        "id": panel_id,
        "type": "table",
        "title": "Open Orders (Price + Direction)",
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": y},
        "datasource": ds,
        "options": {"showHeader": True, "footer": {"show": False}},
        "targets": [
            {
                "datasource": ds,
                "expr": 'hbot_bot_open_order_price{bot=~"$bot",variant=~"$variant"}',
                "refId": "A",
                "format": "table",
                "instant": True,
            },
            {
                "datasource": ds,
                "expr": 'hbot_bot_open_order_amount_base{bot=~"$bot",variant=~"$variant"}',
                "refId": "B",
                "format": "table",
                "instant": True,
            },
            {
                "datasource": ds,
                "expr": 'hbot_bot_open_order_age_seconds{bot=~"$bot",variant=~"$variant"}',
                "refId": "C",
                "format": "table",
                "instant": True,
            },
        ],
        "transformations": [
            {"id": "joinByField", "options": {"byField": "order_id", "mode": "outer"}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time A": True,
                        "Time B": True,
                        "Time C": True,
                        "__name__": True,
                        "__name__ A": True,
                        "__name__ B": True,
                        "__name__ C": True,
                        "job": True,
                        "instance": True,
                        "mode": True,
                        "exchange": True,
                        "accounting": True,
                        "regime": True,
                    },
                    "renameByName": {
                        "Value A": "Price",
                        "Value B": "Amount (Base)",
                        "Value C": "Age (s)",
                        "side A": "Direction",
                        "pair A": "Pair",
                    },
                    "indexByName": {
                        "order_id": 0,
                        "Direction": 1,
                        "Pair": 2,
                        "Price": 3,
                        "Amount (Base)": 4,
                        "Age (s)": 5,
                    },
                },
            },
        ],
        "fieldConfig": {
            "defaults": {},
            "overrides": [
                {"matcher": {"id": "byName", "options": "Price"}, "properties": [{"id": "unit", "value": "currencyUSD"}]},
                {"matcher": {"id": "byName", "options": "Amount (Base)"}, "properties": [{"id": "decimals", "value": 6}]},
                {"matcher": {"id": "byName", "options": "Age (s)"}, "properties": [{"id": "unit", "value": "s"}]},
            ],
        },
    }


def main() -> None:
    raw = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = raw.get("panels", [])

    # Skip if already present.
    ids = {int(p.get("id", -1)) for p in panels if isinstance(p.get("id"), int)}
    if 260 in ids or 261 in ids:
        print("open orders panels already present")
        return

    # Insert after Data Health section (starts existing content at y >= 5).
    for panel in panels:
        gp = panel.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int) and int(gp["y"]) >= 5:
            gp["y"] = int(gp["y"]) + 7

    inserts = [
        _make_row_panel(260, "Execution - Open Orders", 5),
        _make_open_orders_table(261, 6),
    ]
    raw["panels"] = inserts + panels
    DASHBOARD_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
