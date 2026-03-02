from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def _stat_panel(
    panel_id: int,
    title: str,
    expr: str,
    x: int,
    y: int,
    width: int = 6,
    unit: str = "s",
    decimals: int = 0,
    threshold_value: float = 60.0,
) -> Dict[str, Any]:
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "gridPos": {"h": 4, "w": width, "x": x, "y": y},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "horizontal",
            "textMode": "auto",
            "graphMode": "none",
            "colorMode": "background",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": threshold_value},
                        {"color": "red", "value": threshold_value * 2},
                    ],
                },
            }
        },
        "targets": [
            {
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "expr": expr,
                "legendFormat": "{{bot}}",
                "refId": "A",
                "instant": True,
            }
        ],
    }


def main() -> None:
    raw = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = raw.get("panels", [])

    # Normalize row/panel titles and remove unreadable replacement chars.
    title_rewrites = {
        "Dashboard — Status": "Overview - Status",
        "Performance — Profit Chart": "Overview - Profit Chart",
        "View Bot — Open Position": "Positions - Open",
        "View Bot — Closed Trades (Fills)": "Trades - Closed Fills",
        "View Bot — Performance / Tag Summary": "Performance - Regime Summary",
        "View Bot — Sysinfo / General": "System - Runtime",
    }
    for panel in panels:
        title = str(panel.get("title", ""))
        title = title.replace("\ufffd", "-").replace("�?", "-")
        panel["title"] = title_rewrites.get(title, title)
        gp = panel.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int):
            gp["y"] = int(gp["y"]) + 5

    # Data health section at the top for readability and quick triage.
    top_panels: List[Dict[str, Any]] = [
        {
            "type": "row",
            "id": 250,
            "title": "Data Health",
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
            "collapsed": False,
        },
        _stat_panel(
            panel_id=251,
            title="Minute Freshness",
            expr='hbot_bot_minute_last_age_seconds{bot=~"$bot",variant=~"$variant"}',
            x=0,
            y=1,
            unit="s",
            decimals=0,
            threshold_value=60.0,
        ),
        _stat_panel(
            panel_id=252,
            title="Fills Freshness",
            expr='hbot_bot_fills_last_age_seconds{bot=~"$bot",variant=~"$variant"}',
            x=6,
            y=1,
            unit="s",
            decimals=0,
            threshold_value=120.0,
        ),
        _stat_panel(
            panel_id=253,
            title="Fills 24h",
            expr='hbot_bot_fills_24h_count{bot=~"$bot",variant=~"$variant"}',
            x=12,
            y=1,
            unit="short",
            decimals=0,
            threshold_value=1.0,
        ),
        _stat_panel(
            panel_id=254,
            title="Realized PnL 24h",
            expr='hbot_bot_realized_pnl_24h_quote{bot=~"$bot",variant=~"$variant"}',
            x=18,
            y=1,
            unit="currencyUSD",
            decimals=2,
            threshold_value=0.0,
        ),
    ]

    raw["panels"] = top_panels + panels
    DASHBOARD_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
