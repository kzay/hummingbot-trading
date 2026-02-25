from decimal import Decimal

from controllers.core import RegimeSpec
from controllers.epp_v2_4 import EppV24Controller
from controllers.price_buffer import MidPriceBuffer
from controllers.regime_detector import RegimeDetector

SPECS = EppV24Controller.PHASE0_SPECS


def _make_detector(**overrides) -> RegimeDetector:
    defaults = dict(
        specs=SPECS,
        high_vol_band_pct=Decimal("0.0080"),
        shock_drift_30s_pct=Decimal("0.0100"),
        trend_eps_pct=Decimal("0.0010"),
        ema_period=50,
        atr_period=14,
    )
    defaults.update(overrides)
    return RegimeDetector(**defaults)


def _buffer_with_price(price: Decimal, n: int = 360) -> MidPriceBuffer:
    buf = MidPriceBuffer(sample_interval_sec=10)
    for i in range(n):
        buf.add_sample(float(i * 10), price)
    return buf


def test_neutral_regime_with_flat_prices():
    det = _make_detector()
    buf = _buffer_with_price(Decimal("100"))
    name, spec = det.detect(Decimal("100"), buf, 600.0)
    assert name == "neutral_low_vol"
    assert spec.one_sided == "off"


def test_up_regime_when_mid_above_ema():
    det = _make_detector()
    buf = MidPriceBuffer(sample_interval_sec=10)
    for i in range(360):
        buf.add_sample(float(i * 10), Decimal("90"))
    name, spec = det.detect(Decimal("100"), buf, 3600.0)
    assert name == "up"
    assert spec.one_sided == "buy_only"


def test_down_regime_when_mid_below_ema():
    det = _make_detector()
    buf = MidPriceBuffer(sample_interval_sec=10)
    for i in range(360):
        buf.add_sample(float(i * 10), Decimal("110"))
    name, spec = det.detect(Decimal("100"), buf, 3600.0)
    assert name == "down"
    assert spec.one_sided == "sell_only"


def test_shock_regime_on_high_drift():
    det = _make_detector(shock_drift_30s_pct=Decimal("0.001"))
    buf = MidPriceBuffer(sample_interval_sec=10)
    for i in range(60):
        price = Decimal("100") + Decimal(str(i)) * Decimal("0.5")
        buf.add_sample(float(i * 10), price)
    name, spec = det.detect(Decimal("130"), buf, 600.0)
    assert name == "high_vol_shock"


def test_neutral_when_ema_not_ready():
    det = _make_detector(ema_period=200)
    buf = _buffer_with_price(Decimal("100"), n=10)
    name, _ = det.detect(Decimal("105"), buf, 100.0)
    assert name == "neutral_low_vol"
