"""Baseline tests for ops-scheduler — pure functions and job config validation."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.ops_scheduler.main import JOBS, _get_interval, _write_heartbeat


class TestGetInterval:
    def test_default_when_env_unset(self):
        job = {"interval_env": "TEST_INTERVAL_UNUSED_12345", "interval_default": 600}
        with patch.dict("os.environ", {}, clear=False):
            result = _get_interval(job)
        assert result == 600

    def test_reads_from_env(self):
        job = {"interval_env": "TEST_SCHED_INTERVAL", "interval_default": 600}
        with patch.dict("os.environ", {"TEST_SCHED_INTERVAL": "120"}):
            assert _get_interval(job) == 120

    def test_clamps_to_minimum_30(self):
        job = {"interval_env": "TEST_SCHED_LOW", "interval_default": 10}
        with patch.dict("os.environ", {"TEST_SCHED_LOW": "5"}):
            assert _get_interval(job) == 30

    def test_non_digit_falls_to_default(self):
        job = {"interval_env": "TEST_SCHED_BAD", "interval_default": 900}
        with patch.dict("os.environ", {"TEST_SCHED_BAD": "not_a_number"}):
            assert _get_interval(job) == 900


class TestJobConfig:
    """Structural checks on the JOBS list."""

    def test_jobs_not_empty(self):
        assert len(JOBS) >= 6

    @pytest.mark.parametrize("job", JOBS, ids=[j["name"] for j in JOBS])
    def test_job_has_required_keys(self, job):
        assert "name" in job
        assert "command" in job
        assert "interval_env" in job
        assert "interval_default" in job

    @pytest.mark.parametrize("job", JOBS, ids=[j["name"] for j in JOBS])
    def test_job_interval_positive(self, job):
        assert job["interval_default"] >= 30

    @pytest.mark.parametrize("job", JOBS, ids=[j["name"] for j in JOBS])
    def test_job_command_is_list(self, job):
        assert isinstance(job["command"], list)
        assert len(job["command"]) >= 1

    def test_unique_job_names(self):
        names = [j["name"] for j in JOBS]
        assert len(names) == len(set(names)), f"Duplicate job names: {names}"


class TestWriteHeartbeat:
    def test_writes_valid_json(self, tmp_path: Path):
        hb_path = tmp_path / "heartbeat.json"
        with patch("services.ops_scheduler.main.HEARTBEAT_PATH", hb_path):
            _write_heartbeat({"status": "ok", "alive_threads": 5})
        data = json.loads(hb_path.read_text())
        assert data["status"] == "ok"
        assert data["alive_threads"] == 5
