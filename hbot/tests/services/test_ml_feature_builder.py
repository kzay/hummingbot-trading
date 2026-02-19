from services.contracts.event_schemas import MarketSnapshotEvent
from services.signal_service.feature_builder import build_features


def test_build_features_v1_outputs_vector_and_hash():
    event = MarketSnapshotEvent(
        producer="hb",
        instance_name="bot1",
        controller_id="epp_v2_4",
        connector_name="bitget",
        trading_pair="BTC-USDT",
        mid_price=100.0,
        equity_quote=10000.0,
        base_pct=0.45,
        target_base_pct=0.50,
        spread_pct=0.003,
        net_edge_pct=0.0005,
        turnover_x=1.1,
        state="running",
    )
    vec, fmap, fhash = build_features(event, "v1")
    assert len(vec) == len(fmap)
    assert "inventory_gap" in fmap
    assert len(fhash) == 64

