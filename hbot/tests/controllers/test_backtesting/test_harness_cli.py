"""Regression tests for harness_cli catalog resolution (Docker / API workers)."""
from __future__ import annotations

from pathlib import Path

from controllers.backtesting import harness_cli


def test_default_catalog_from_yaml():
    assert harness_cli._default_data_catalog_dir({"catalog_dir": "/foo/bar"}) == "/foo/bar"


def test_yaml_catalog_wins_over_env(monkeypatch):
    monkeypatch.setenv("BACKTEST_CATALOG_DIR", "/env/ignored")
    assert harness_cli._default_data_catalog_dir({"catalog_dir": "/yaml/wins"}) == "/yaml/wins"


def test_default_catalog_from_backtest_env(monkeypatch):
    monkeypatch.delenv("HB_DATA_ROOT", raising=False)
    monkeypatch.setenv("BACKTEST_CATALOG_DIR", "/env/catalog")
    assert harness_cli._default_data_catalog_dir({}) == "/env/catalog"


def test_default_catalog_from_hb_data_root(monkeypatch):
    monkeypatch.delenv("BACKTEST_CATALOG_DIR", raising=False)
    monkeypatch.setenv("HB_DATA_ROOT", "/workspace/hbot/data")
    assert harness_cli._default_data_catalog_dir({}) == str(
        Path("/workspace/hbot/data") / "historical"
    )


def test_fallback_string_when_no_dirs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BACKTEST_CATALOG_DIR", raising=False)
    monkeypatch.delenv("HB_DATA_ROOT", raising=False)
    assert harness_cli._default_data_catalog_dir({}) == "data/historical"


def test_prefers_existing_data_historical_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "historical").mkdir(parents=True)
    monkeypatch.delenv("BACKTEST_CATALOG_DIR", raising=False)
    monkeypatch.delenv("HB_DATA_ROOT", raising=False)
    assert harness_cli._default_data_catalog_dir({}) == "data/historical"


def test_prefers_hbot_nested_when_only_that_exists(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hbot" / "data" / "historical").mkdir(parents=True)
    monkeypatch.delenv("BACKTEST_CATALOG_DIR", raising=False)
    monkeypatch.delenv("HB_DATA_ROOT", raising=False)
    assert harness_cli._default_data_catalog_dir({}) == "hbot/data/historical"
