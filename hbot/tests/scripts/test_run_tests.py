from __future__ import annotations

import json
from pathlib import Path

from scripts.release.run_tests import _compute_critical_path_coverage


def test_compute_critical_path_coverage_aggregates_selected_files(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "files": {
                    "scripts/shared/v2_with_controllers.py": {
                        "summary": {
                            "covered_lines": 10,
                            "num_statements": 20,
                            "percent_covered": 50.0,
                        }
                    },
                    "services/event_store/main.py": {
                        "summary": {
                            "covered_lines": 40,
                            "num_statements": 50,
                            "percent_covered": 80.0,
                        }
                    },
                    "services/bot_metrics_exporter.py": {
                        "summary": {
                            "covered_lines": 30,
                            "num_statements": 40,
                            "percent_covered": 75.0,
                        }
                    },
                    "services/other.py": {
                        "summary": {
                            "covered_lines": 1,
                            "num_statements": 10,
                            "percent_covered": 10.0,
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = _compute_critical_path_coverage(coverage_path)

    assert result["selected_files"] == 3
    assert result["covered_lines"] == 80
    assert result["num_statements"] == 110
    assert result["percent_covered"] == 72.73


def test_compute_critical_path_coverage_returns_defaults_when_missing(tmp_path: Path) -> None:
    result = _compute_critical_path_coverage(tmp_path / "missing.json")

    assert result["selected_files"] == 0
    assert result["covered_lines"] == 0
    assert result["num_statements"] == 0
    assert result["percent_covered"] == 0.0
