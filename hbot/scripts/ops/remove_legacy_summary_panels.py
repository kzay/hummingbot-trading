from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DASHBOARD_PATH = Path("hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json")


def main() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels: List[Dict[str, Any]] = dashboard.get("panels", [])

    # Remove legacy duplicated summary row/cards (already covered by KPI board + data health).
    remove_ids = {200, 201, 202, 203, 204, 205}
    panels = [p for p in panels if int(p.get("id", -1)) not in remove_ids]

    # Pull up remaining panels to close the empty space.
    for p in panels:
        gp = p.get("gridPos")
        if isinstance(gp, dict) and isinstance(gp.get("y"), int) and int(gp["y"]) >= 37:
            gp["y"] = int(gp["y"]) - 5

    dashboard["panels"] = panels
    dashboard["version"] = int(dashboard.get("version", 1)) + 1
    DASHBOARD_PATH.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    print(str(DASHBOARD_PATH))


if __name__ == "__main__":
    main()
