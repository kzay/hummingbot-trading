from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def _row(panel_id: int, y: int) -> Dict[str, Any]:
    return {
        "type": "row",
        "id": panel_id,
        "title": "Desk KPI Board",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
    }


def _stat(
    panel_id: int,
    title: str,
    expr: str,
    x: int,
    y: int,
    unit: str,
    decimals: int,
    warn: float,
    crit: float,
    reverse: bool = False,
) -> Dict[str, Any]:
    # reverse=True means higher is better (green above crit/warn).
    if reverse:
        steps = [
            {"color": "red", "value": None},
            {"color": "orange", "value": warn},
            {"color": "green", "value": crit},
        ]
    else:
        steps = [
            {"color": "green", "value": None},
            {"color": "orange", "value": warn},
            {"color": "red", "value": crit},
        ]
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
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
            }
        },
        "targets": [{"datasource": ds, "expr": expr, "refId": "A", "instant": True}],
    }


def main() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = dashboard.get("panels", [])
    existing_ids = {int(p.get("id", -1)) for p in panels if isinstance(p.get("id"), int)}
    if 280 in existing_ids:
        print("desk kpi board already present")
        return

    # Insert after Execution Insights block (currently next section starts at y >= 25).
    for panel in panels:
        gp = panel.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int) and int(gp["y"]) >= 25:
            gp["y"] = int(gp["y"]) + 5

    inserts: List[Dict[str, Any]] = [
        _row(280, 25),
        _stat(
            281,
            "Minute Age",
            'hbot_bot_minute_last_age_seconds{bot=~"$bot",variant=~"$variant"}',
            0,
            26,
            "s",
            0,
            warn=60.0,
            crit=180.0,
        ),
        _stat(
            282,
            "Fills Age",
            'hbot_bot_fills_last_age_seconds{bot=~"$bot",variant=~"$variant"}',
            4,
            26,
            "s",
            0,
            warn=300.0,
            crit=1200.0,
        ),
        _stat(
            283,
            "Avg Slippage bps",
            'hbot_bot_fill_slippage_bps_sum{bot=~"$bot",variant=~"$variant"} / clamp_min(hbot_bot_fill_slippage_bps_count{bot=~"$bot",variant=~"$variant"}, 1)',
            8,
            26,
            "short",
            2,
            warn=2.0,
            crit=5.0,
        ),
        _stat(
            284,
            "Fills 5m",
            'hbot_bot_fills_5m_count{bot=~"$bot",variant=~"$variant"}',
            12,
            26,
            "short",
            0,
            warn=1.0,
            crit=3.0,
            reverse=True,
        ),
        _stat(
            285,
            "Turnover x",
            'hbot_bot_turnover_today_x{bot=~"$bot",variant=~"$variant"}',
            16,
            26,
            "short",
            2,
            warn=2.5,
            crit=3.0,
        ),
        _stat(
            286,
            "Book Imbalance",
            'abs(hbot_bot_book_imbalance{bot=~"$bot",variant=~"$variant"})',
            20,
            26,
            "short",
            3,
            warn=0.7,
            crit=0.9,
        ),
    ]

    dashboard["panels"] = inserts + panels
    DASHBOARD_PATH.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
