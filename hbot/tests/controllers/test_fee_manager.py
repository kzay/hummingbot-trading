from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from controllers.fee_manager import FeeManager


def test_manual_mode_resolves_immediately():
    fm = FeeManager(
        fee_mode="manual",
        fee_profile="vip0",
        require_fee_resolution=False,
        fee_refresh_s=300,
        spot_fee_pct=Decimal("0.001"),
    )
    fm.ensure_fees(100.0, None, "bitget", "BTC-USDT", None)
    assert fm.fee_resolved is True
    assert fm.fee_source == "manual:spot_fee_pct"
    assert fm.maker_fee_pct == Decimal("0.001")


def test_manual_mode_zero_fee_not_resolved():
    fm = FeeManager(
        fee_mode="manual",
        fee_profile="vip0",
        require_fee_resolution=True,
        fee_refresh_s=300,
        spot_fee_pct=Decimal("0"),
    )
    fm.ensure_fees(100.0, None, "bitget", "BTC-USDT", None)
    assert fm.fee_resolved is False
    assert fm.fee_resolution_error == "manual_fee_non_positive"


def test_auto_mode_falls_back_to_project_profile():
    fm = FeeManager(
        fee_mode="auto",
        fee_profile="vip0",
        require_fee_resolution=False,
        fee_refresh_s=300,
        spot_fee_pct=Decimal("0.001"),
    )
    with patch("controllers.fee_manager.FeeResolver") as mock_resolver:
        mock_resolver.from_exchange_api.return_value = None
        mock_resolver.from_connector_runtime.return_value = None
        profile_rates = SimpleNamespace(maker=Decimal("0.0008"), taker=Decimal("0.0010"), source="project:vip0")
        mock_resolver.from_project_profile.return_value = profile_rates

        fm.ensure_fees(100.0, MagicMock(), "bitget", "BTC-USDT", MagicMock())

    assert fm.fee_resolved is True
    assert fm.fee_source == "project:vip0"
    assert fm.maker_fee_pct == Decimal("0.0008")


def test_require_resolution_blocks_on_failure():
    fm = FeeManager(
        fee_mode="auto",
        fee_profile="vip0",
        require_fee_resolution=True,
        fee_refresh_s=300,
        spot_fee_pct=Decimal("0.001"),
    )
    with patch("controllers.fee_manager.FeeResolver") as mock_resolver:
        mock_resolver.from_exchange_api.return_value = None
        mock_resolver.from_connector_runtime.return_value = None
        mock_resolver.from_project_profile.return_value = None

        fm.ensure_fees(100.0, MagicMock(), "bitget", "BTC-USDT", MagicMock())

    assert fm.fee_resolved is False
    assert fm.fee_resolution_error == "resolver_failed_with_require_true"


def test_refresh_respects_cooldown():
    fm = FeeManager(
        fee_mode="manual",
        fee_profile="vip0",
        require_fee_resolution=False,
        fee_refresh_s=300,
        spot_fee_pct=Decimal("0.001"),
    )
    fm.ensure_fees(100.0, None, "bitget", "BTC-USDT", None)
    assert fm.fee_resolved is True
    fm.fee_resolved = False
    fm.ensure_fees(200.0, None, "bitget", "BTC-USDT", None)
    assert fm.fee_resolved is False
