from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def _gate_row(y: int) -> Dict[str, Any]:
    return {
        "type": "row",
        "id": 290,
        "title": "Gate Control",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
    }


def _gate_stat(panel_id: int, title: str, expr: str, x: int, y: int) -> Dict[str, Any]:
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
                "unit": "short",
                "decimals": 0,
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "green", "value": 1},
                    ],
                },
                "mappings": [
                    {"type": "value", "options": {"0": {"text": "HOLD"}, "1": {"text": "GO"}}}
                ],
            }
        },
        "targets": [{"datasource": ds, "expr": expr, "refId": "A", "instant": True}],
    }


def _gate_matrix(y: int) -> Dict[str, Any]:
    ds = {"type": "prometheus", "uid": "prometheus"}
    return {
        "id": 293,
        "type": "table",
        "title": "Promotion Gate Matrix",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": y},
        "datasource": ds,
        "options": {"showHeader": True, "footer": {"show": False}},
        "targets": [
            {
                "datasource": ds,
                "expr": 'hbot_control_plane_gate_status{source="promotion_latest"}',
                "refId": "A",
                "format": "table",
                "instant": True,
            }
        ],
        "transformations": [
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True,
                        "__name__": True,
                        "job": True,
                        "instance": True,
                        "source": True,
                    },
                    "renameByName": {"gate": "Gate", "severity": "Severity", "Value": "Status"},
                    "indexByName": {"Gate": 0, "Severity": 1, "Status": 2},
                },
            }
        ],
        "fieldConfig": {
            "defaults": {},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Status"},
                    "properties": [
                        {
                            "id": "mappings",
                            "value": [
                                {"type": "value", "options": {"0": {"text": "FAIL"}, "1": {"text": "PASS"}}}
                            ],
                        }
                    ],
                }
            ],
        },
    }


def main() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = dashboard.get("panels", [])

    # Remove duplicates / lower-value copies.
    remove_ids = {
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,      # old overview status row
        20, 21, 22,                           # old profit chart block (already covered)
        271, 272, 273, 274, 275, 276,         # duplicated stat cards covered by KPI board
    }
    panels = [p for p in panels if int(p.get("id", -1)) not in remove_ids]

    # Remove previous gate control if rerun.
    panels = [p for p in panels if int(p.get("id", -1)) not in {290, 291, 292, 293}]

    # Insert Gate Control block after Data Health section.
    for p in panels:
        gp = p.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int) and int(gp["y"]) >= 5:
            gp["y"] = int(gp["y"]) + 7

    inserts: List[Dict[str, Any]] = [
        _gate_row(5),
        _gate_stat(291, "Global Gate", 'hbot_control_plane_gate_status{gate="promotion_latest"}', 0, 6),
        _gate_stat(292, "Strict Cycle", 'hbot_control_plane_gate_status{gate="strict_cycle"}', 4, 6),
        _gate_matrix(6),
    ]

    dashboard["panels"] = inserts + panels
    dashboard["version"] = int(dashboard.get("version", 1)) + 1
    DASHBOARD_PATH.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
