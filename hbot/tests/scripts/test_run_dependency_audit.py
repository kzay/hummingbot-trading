from __future__ import annotations

import json
from pathlib import Path

from scripts.release.run_dependency_audit import (
    _collect_outdated,
    _collect_pip_audit,
    _parse_requirements,
    run,
)


def test_parse_requirements_ignores_comments_and_flags(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "--extra-index-url https://example.invalid/simple",
                "redis==5.0.1",
                "pydantic>=2.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = _parse_requirements(req)

    assert [row["name"] for row in rows] == ["redis", "pydantic"]
    assert rows[0]["specifier"] == "==5.0.1"
    assert rows[1]["specifier"] == ">=2.0"


def test_collect_outdated_filters_to_tracked_packages(tmp_path: Path) -> None:
    def _runner(cmd):  # noqa: ANN001
        return (
            0,
            json.dumps(
                [
                    {"name": "redis", "version": "5.0.1", "latest_version": "5.1.0", "latest_filetype": "wheel"},
                    {"name": "pytest", "version": "8.0.0", "latest_version": "8.1.0", "latest_filetype": "wheel"},
                ]
            ),
            "",
        )

    result = _collect_outdated(["redis"], root=tmp_path, runner=_runner)

    assert result["available"] is True
    assert result["packages"] == [
        {
            "name": "redis",
            "current_version": "5.0.1",
            "latest_version": "5.1.0",
            "latest_filetype": "wheel",
        }
    ]


def test_collect_pip_audit_parses_vulnerabilities(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("redis==5.0.1\n", encoding="utf-8")

    def _runner(cmd):  # noqa: ANN001
        return (
            0,
            json.dumps(
                {
                    "dependencies": [
                        {
                            "name": "redis",
                            "version": "5.0.1",
                            "vulns": [
                                {
                                    "id": "PYSEC-TEST-1",
                                    "fix_versions": ["5.0.2"],
                                    "description": "sample vulnerability",
                                }
                            ],
                        }
                    ]
                }
            ),
            "",
        )

    result = _collect_pip_audit(req, root=tmp_path, runner=_runner)

    assert result["available"] is True
    assert result["vulnerability_count"] == 1
    assert result["vulnerabilities"][0]["id"] == "PYSEC-TEST-1"


def test_run_writes_dependency_audit_artifact(tmp_path: Path, monkeypatch) -> None:
    requirements = tmp_path / "compose" / "images" / "control_plane"
    requirements.mkdir(parents=True, exist_ok=True)
    (requirements / "requirements-control-plane.txt").write_text("redis==5.0.1\n", encoding="utf-8")

    def _fake_run_command(cmd, *, cwd):  # noqa: ANN001
        joined = " ".join(str(part) for part in cmd)
        if "pip list --outdated" in joined:
            return 0, "[]", ""
        if "pip_audit" in joined:
            return 1, "", "pip_audit not installed"
        raise AssertionError(f"unexpected command: {joined}")

    monkeypatch.setattr("scripts.release.run_dependency_audit._run_command", _fake_run_command)
    monkeypatch.setattr("scripts.release.run_dependency_audit._installed_versions", lambda packages: {"redis": "5.0.1"})

    report = run(tmp_path)

    latest = tmp_path / "reports" / "security" / "dependency_audit_latest.json"
    assert latest.exists()
    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert report["status"] == "warning"
    assert saved["tracked_package_count"] == 1
    assert saved["packages"][0]["installed_version"] == "5.0.1"
    assert saved["cves"]["available"] is False
