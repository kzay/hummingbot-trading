from __future__ import annotations

import importlib.util
from decimal import Decimal
from types import SimpleNamespace

import pytest

HUMMINGBOT_AVAILABLE = importlib.util.find_spec("hummingbot") is not None

if HUMMINGBOT_AVAILABLE:
    from hummingbot.core.data_type.common import PositionAction

    from controllers.connector_runtime_adapter import ConnectorRuntimeAdapter
else:  # pragma: no cover - stripped environments
    PositionAction = object
    ConnectorRuntimeAdapter = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_get_position_amount_reads_hedge_leg_amounts_from_account_positions_dict() -> None:
    connector = SimpleNamespace(
        account_positions=lambda *_args, **_kwargs: {
            "BTC-USDT": {
                "amount": Decimal("0.15"),
                "long_amount": Decimal("0.40"),
                "short_amount": Decimal("-0.25"),
            }
        }
    )
    controller = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        strategy=SimpleNamespace(connectors={"bitget_perpetual": connector}),
        market_data_provider=SimpleNamespace(get_connector=lambda _name: connector),
    )

    adapter = ConnectorRuntimeAdapter(controller)
    adapter.refresh_connector_cache()

    assert adapter.get_position_amount() == Decimal("0.15")
    assert adapter.get_position_amount(position_action=PositionAction.OPEN_LONG) == Decimal("0.40")
    assert adapter.get_position_amount(position_action=PositionAction.CLOSE_SHORT) == Decimal("-0.25")
