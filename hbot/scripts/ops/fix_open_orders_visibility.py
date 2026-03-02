from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def main() -> None:
    dash = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = dash.get("panels", [])
    by_id = {int(p.get("id", -1)): p for p in panels if isinstance(p.get("id"), int)}

    table = by_id.get(261)
    if table:
        table["gridPos"] = {"h": 6, "w": 20, "x": 0, "y": 6}

    if 262 not in by_id:
        panels.append(
            {
                "id": 262,
                "type": "stat",
                "title": "Open Orders Count",
                "gridPos": {"h": 6, "w": 4, "x": 20, "y": 6},
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
                        "unit": "short",
                        "decimals": 0,
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "mode": "absolute",
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "orange", "value": 1},
                                {"color": "red", "value": 5},
                            ],
                        },
                    }
                },
                "targets": [
                    {
                        "datasource": {"type": "prometheus", "uid": "prometheus"},
                        "expr": 'hbot_bot_open_orders_total{bot=~"$bot",variant=~"$variant"}',
                        "refId": "A",
                        "instant": True,
                    }
                ],
            }
        )

    dash["panels"] = panels
    DASHBOARD_PATH.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
