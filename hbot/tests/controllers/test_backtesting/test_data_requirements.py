"""Tests for data_requirements manifest loading and scope computation."""
from __future__ import annotations

from pathlib import Path

import pytest

from controllers.backtesting.data_requirements import compute_refresh_scope, load_manifest


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    p = tmp_path / "data_requirements.yml"
    p.write_text(
        """\
consumers:
  ml_feature_service:
    required_lookback_bars: 20160
    bootstrap_from: "90d"
    canonical_datasets: ["1m"]
    pairs: ["BTC-USDT"]
    exchange: bitget

  backtesting:
    required_lookback_bars: 60
    retention_policy: "full_history"
    canonical_datasets: ["1m"]
    materialized_datasets: ["5m", "15m", "1h"]
    pairs: ["BTC-USDT", "ETH-USDT"]
    exchange: bitget

  ml_training:
    required_lookback_bars: 1000
    canonical_datasets: ["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]
    materialized_datasets: ["5m", "15m", "1h"]
    pairs: ["BTC-USDT", "ETH-USDT"]
    exchange: bitget
""",
        encoding="utf-8",
    )
    return p


class TestLoadManifest:
    def test_valid_manifest(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        assert "consumers" in m
        assert "ml_feature_service" in m["consumers"]

    def test_missing_file(self, tmp_path: Path) -> None:
        m = load_manifest(tmp_path / "nope.yml")
        assert m == {"consumers": {}}

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yml"
        bad.write_text("{{ invalid yaml", encoding="utf-8")
        m = load_manifest(bad)
        assert m == {"consumers": {}}

    def test_missing_consumers_key(self, tmp_path: Path) -> None:
        f = tmp_path / "no_consumers.yml"
        f.write_text("version: 1\n", encoding="utf-8")
        m = load_manifest(f)
        assert m == {"consumers": {}}


class TestComputeRefreshScope:
    def test_union_pairs(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert sorted(scope["pairs"]) == ["BTC-USDT", "ETH-USDT"]

    def test_union_canonical_datasets(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert "1m" in scope["canonical_datasets"]
        assert "mark_1m" in scope["canonical_datasets"]
        assert "funding" in scope["canonical_datasets"]

    def test_union_materialized_datasets(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert sorted(scope["materialized_datasets"]) == ["15m", "1h", "5m"]

    def test_max_lookback(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert scope["max_lookback_bars"] == 20160

    def test_retention_policy(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert scope["retention_policy"] == "full_history"

    def test_bootstrap_from(self, manifest_path: Path) -> None:
        m = load_manifest(manifest_path)
        scope = compute_refresh_scope(m)
        assert scope["bootstrap_from"] == "90d"

    def test_empty_manifest(self) -> None:
        scope = compute_refresh_scope({"consumers": {}})
        assert scope["pairs"] == []
        assert scope["canonical_datasets"] == []
        assert scope["max_lookback_bars"] == 0
