"""Tests for ML config resolution, event schema contracts, and governance policy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _hbot_root() -> Path:
    """Resolve the hbot workspace root (two levels above tests/controllers/)."""
    return Path(__file__).resolve().parent.parent.parent


class TestMlGovernancePolicy:
    @pytest.fixture()
    def policy(self) -> dict:
        path = _hbot_root() / "config" / "ml_governance_policy_v1.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_version_bumped(self, policy: dict) -> None:
        assert policy["version"] >= 2

    def test_model_types_includes_adverse(self, policy: dict) -> None:
        assert "adverse" in policy["model_types"]

    def test_promotion_thresholds_per_model_type(self, policy: dict) -> None:
        thresholds = policy["promotion_thresholds"]
        assert "min_oos_accuracy" in thresholds
        assert thresholds["min_oos_accuracy"]["adverse"] >= 0.60
        assert thresholds["min_improvement_over_baseline"]["adverse"] < thresholds["min_improvement_over_baseline"]["default"]

    def test_shadow_evaluation_section(self, policy: dict) -> None:
        shadow = policy["shadow_evaluation"]
        assert "min_soak_bars" in shadow
        assert shadow["min_soak_bars"] > 0

    def test_feature_importance_config(self, policy: dict) -> None:
        fi = policy["feature_importance"]
        assert fi["top_k"] > 0
        assert 0 < fi["min_stability"] < 1.0


class TestEventSchemaContracts:
    def test_ml_feature_event_roundtrip(self) -> None:
        from platform_lib.contracts.event_schemas import MlFeatureEvent
        event = MlFeatureEvent(
            producer="test",
            exchange="bitget",
            trading_pair="BTC-USDT",
            features={"rsi_14_1m": 55.0},
            predictions={"regime": {"class": 2}},
            model_versions={"regime": "2026-03-24"},
        )
        d = event.model_dump()
        assert d["event_type"] == "ml_features"
        restored = MlFeatureEvent(**d)
        assert restored.features["rsi_14_1m"] == 55.0

    def test_shadow_comparison_event_roundtrip(self) -> None:
        from platform_lib.contracts.event_schemas import MlShadowComparisonEvent
        event = MlShadowComparisonEvent(
            producer="ml_feature_service",
            exchange="bitget",
            trading_pair="BTC-USDT",
            model_type="regime",
            active_pred=1,
            shadow_pred=0,
            agreement=False,
        )
        d = event.model_dump()
        assert d["agreement"] is False
        restored = MlShadowComparisonEvent(**d)
        assert restored.model_type == "regime"

    def test_market_trade_event_has_side(self) -> None:
        from platform_lib.contracts.event_schemas import MarketTradeEvent
        event = MarketTradeEvent(
            producer="test",
            connector_name="bitget",
            trading_pair="BTC-USDT",
            price=50000.0,
            size=0.1,
            side="buy",
        )
        assert event.side == "buy"


class TestDataRequirements:
    def test_ml_feature_service_has_live_streams(self) -> None:
        import yaml
        path = _hbot_root() / "config" / "data_requirements.yml"
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        ml_spec = manifest["consumers"]["ml_feature_service"]
        assert "live_streams" in ml_spec
        assert "hb.market_trade.v1" in ml_spec["live_streams"]

    def test_ml_feature_service_has_optional_inputs(self) -> None:
        import yaml
        path = _hbot_root() / "config" / "data_requirements.yml"
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        ml_spec = manifest["consumers"]["ml_feature_service"]
        assert "mark_candles_1m" in ml_spec.get("optional_inputs", [])
