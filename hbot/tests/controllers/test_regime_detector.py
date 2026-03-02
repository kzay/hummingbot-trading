from decimal import Decimal

from controllers.epp_v2_4 import EppV24Controller
from controllers.regime_detector import RegimeDetector

SPECS = EppV24Controller.PHASE0_SPECS

_ZERO = Decimal("0")


def _make_detector(**overrides) -> RegimeDetector:
    defaults = dict(
        specs=SPECS,
        high_vol_band_pct=Decimal("0.0080"),
        shock_drift_30s_pct=Decimal("0.0100"),
        trend_eps_pct=Decimal("0.0010"),
    )
    defaults.update(overrides)
    return RegimeDetector(**defaults)


def test_neutral_regime_with_flat_prices():
    det = _make_detector()
    name, spec = det.detect(
        mid=Decimal("100"), ema_val=Decimal("100"),
        band_pct=Decimal("0.002"), drift=_ZERO,
    )
    assert name == "neutral_low_vol"
    assert spec.one_sided == "off"


def test_up_regime_when_mid_above_ema():
    det = _make_detector()
    for _ in range(3):
        name, spec = det.detect(
            mid=Decimal("100"), ema_val=Decimal("90"),
            band_pct=Decimal("0.002"), drift=_ZERO,
        )
    assert name == "up"
    assert spec.one_sided == "buy_only"


def test_down_regime_when_mid_below_ema():
    det = _make_detector()
    for _ in range(3):
        name, spec = det.detect(
            mid=Decimal("100"), ema_val=Decimal("110"),
            band_pct=Decimal("0.002"), drift=_ZERO,
        )
    assert name == "down"
    assert spec.one_sided == "sell_only"


def test_shock_regime_on_high_drift():
    det = _make_detector(shock_drift_30s_pct=Decimal("0.001"))
    for _ in range(3):
        name, spec = det.detect(
            mid=Decimal("100"), ema_val=Decimal("100"),
            band_pct=Decimal("0.002"), drift=Decimal("0.005"),
        )
    assert name == "high_vol_shock"


def test_neutral_when_ema_not_ready():
    det = _make_detector()
    name, _ = det.detect(
        mid=Decimal("105"), ema_val=None,
        band_pct=_ZERO, drift=_ZERO,
    )
    assert name == "neutral_low_vol"
