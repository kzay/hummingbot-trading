"""Tests for safe_decimal() and safety guarantees across the risk pipeline."""
from __future__ import annotations

from decimal import Decimal

from platform_lib.core.utils import safe_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")


class TestSafeDecimalBasicConversions:
    def test_int(self):
        assert safe_decimal(42) == Decimal("42")

    def test_float(self):
        assert safe_decimal(1.5) == Decimal("1.5")

    def test_string(self):
        assert safe_decimal("123.456") == Decimal("123.456")

    def test_decimal_passthrough(self):
        assert safe_decimal(Decimal("99.9")) == Decimal("99.9")


class TestSafeDecimalNaNInfRejection:
    def test_float_nan_returns_default(self):
        assert safe_decimal(float("nan")) == _ZERO

    def test_float_inf_returns_default(self):
        assert safe_decimal(float("inf")) == _ZERO

    def test_float_neg_inf_returns_default(self):
        assert safe_decimal(float("-inf")) == _ZERO

    def test_decimal_nan_returns_default(self):
        assert safe_decimal(Decimal("NaN")) == _ZERO

    def test_decimal_inf_returns_default(self):
        assert safe_decimal(Decimal("Infinity")) == _ZERO

    def test_decimal_neg_inf_returns_default(self):
        assert safe_decimal(Decimal("-Infinity")) == _ZERO

    def test_string_nan_returns_default(self):
        assert safe_decimal("NaN") == _ZERO

    def test_string_inf_returns_default(self):
        assert safe_decimal("Infinity") == _ZERO

    def test_custom_default_on_nan(self):
        assert safe_decimal(float("nan"), default=Decimal("-1")) == Decimal("-1")


class TestSafeDecimalEdgeCases:
    def test_none_returns_default(self):
        assert safe_decimal(None) == _ZERO

    def test_empty_string_returns_default(self):
        assert safe_decimal("") == _ZERO

    def test_garbage_string_returns_default(self):
        assert safe_decimal("not_a_number") == _ZERO

    def test_zero(self):
        assert safe_decimal(0) == _ZERO

    def test_negative(self):
        assert safe_decimal(-5) == Decimal("-5")


class TestClipNaNInfSafety:
    """Verify that core.clip treats NaN/Inf as fail-safe."""

    def test_clip_nan_returns_low(self):
        from controllers.core import clip
        result = clip(Decimal("NaN"), Decimal("1"), Decimal("10"))
        assert result == Decimal("1")

    def test_clip_inf_returns_low(self):
        from controllers.core import clip
        result = clip(Decimal("Infinity"), Decimal("1"), Decimal("10"))
        assert result == Decimal("1")

    def test_clip_neg_inf_returns_low(self):
        from controllers.core import clip
        result = clip(Decimal("-Infinity"), Decimal("1"), Decimal("10"))
        assert result == Decimal("1")

    def test_clip_normal_unchanged(self):
        from controllers.core import clip
        assert clip(Decimal("5"), Decimal("1"), Decimal("10")) == Decimal("5")

    def test_clip_below_low(self):
        from controllers.core import clip
        assert clip(Decimal("0"), Decimal("1"), Decimal("10")) == Decimal("1")

    def test_clip_above_high(self):
        from controllers.core import clip
        assert clip(Decimal("20"), Decimal("1"), Decimal("10")) == Decimal("10")
