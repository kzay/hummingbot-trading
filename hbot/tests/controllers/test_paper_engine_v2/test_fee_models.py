"""Tests for paper_engine_v2 fee models."""
from decimal import Decimal
import pytest

from controllers.paper_engine_v2.fee_models import (
    FixedFeeModel, MakerTakerFeeModel, TieredFeeModel,
)
from tests.controllers.test_paper_engine_v2.conftest import BTC_SPOT, make_spec


class TestMakerTakerFeeModel:
    def test_maker_rate(self):
        model = MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006"))
        fee = model.compute(Decimal("1000"), is_maker=True)
        assert fee == Decimal("0.20")

    def test_taker_rate(self):
        model = MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006"))
        fee = model.compute(Decimal("1000"), is_maker=False)
        assert fee == Decimal("0.60")

    def test_from_spec(self):
        spec = make_spec(BTC_SPOT, maker="0.0001", taker="0.0005")
        model = MakerTakerFeeModel.from_spec(spec)
        assert model.compute(Decimal("10000"), True) == Decimal("1.00")
        assert model.compute(Decimal("10000"), False) == Decimal("5.00")

    def test_zero_notional(self):
        model = MakerTakerFeeModel(Decimal("0.001"), Decimal("0.001"))
        assert model.compute(Decimal("0"), True) == Decimal("0")


class TestTieredFeeModel:
    def test_loads_from_fee_profiles(self):
        model = TieredFeeModel(
            venue="bitget_perpetual",
            profile="vip0",
            profiles_path="config/fee_profiles.json",
        )
        # Bitget perp vip0: maker=0.0002, taker=0.0006
        fee_maker = model.compute(Decimal("10000"), is_maker=True)
        fee_taker = model.compute(Decimal("10000"), is_maker=False)
        assert fee_maker == Decimal("2.00")
        assert fee_taker == Decimal("6.00")

    def test_falls_back_on_missing_profile(self):
        """Missing profile falls back to default 0.001."""
        model = TieredFeeModel("nonexistent_exchange", "vip99")
        fee = model.compute(Decimal("1000"), True)
        assert fee == Decimal("1.00")  # 0.001 fallback


class TestFixedFeeModel:
    def test_flat_commission(self):
        model = FixedFeeModel(Decimal("0.50"))
        assert model.compute(Decimal("100"), True) == Decimal("0.50")
        assert model.compute(Decimal("100"), False) == Decimal("0.50")

    def test_notional_irrelevant(self):
        model = FixedFeeModel(Decimal("1.00"))
        assert model.compute(Decimal("999999"), True) == Decimal("1.00")
        assert model.compute(Decimal("0"), False) == Decimal("1.00")
