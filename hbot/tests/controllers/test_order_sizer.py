from decimal import Decimal
from types import SimpleNamespace

from controllers.order_sizer import OrderSizer


def _rule(**overrides):
    defaults = dict(
        min_order_size=Decimal("0.0001"),
        min_base_amount=Decimal("0.0001"),
        min_amount=Decimal("0.0001"),
        min_base_amount_increment=Decimal("0.0001"),
        min_notional_size=Decimal("10"),
        min_price_increment=Decimal("0.01"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _sizer(**overrides) -> OrderSizer:
    defaults = dict(
        max_order_notional_quote=Decimal("250"),
        max_total_notional_quote=Decimal("1000"),
    )
    defaults.update(overrides)
    return OrderSizer(**defaults)


def test_quantize_price_rounds_buy_down():
    from hummingbot.core.data_type.common import TradeType
    sizer = _sizer()
    rule = _rule(min_price_increment=Decimal("0.01"))
    result = sizer.quantize_price(Decimal("100.555"), TradeType.BUY, rule)
    assert result == Decimal("100.55")


def test_quantize_price_rounds_sell_up():
    from hummingbot.core.data_type.common import TradeType
    sizer = _sizer()
    rule = _rule(min_price_increment=Decimal("0.01"))
    result = sizer.quantize_price(Decimal("100.551"), TradeType.SELL, rule)
    assert result == Decimal("100.56")


def test_quantize_amount_respects_min():
    sizer = _sizer()
    rule = _rule(min_order_size=Decimal("0.01"))
    result = sizer.quantize_amount(Decimal("0.001"), rule)
    assert result >= Decimal("0.01")


def test_quantize_amount_respects_step():
    sizer = _sizer()
    rule = _rule(min_base_amount_increment=Decimal("0.001"))
    result = sizer.quantize_amount(Decimal("0.1234"), rule)
    assert result * Decimal("1000") == int(result * Decimal("1000"))


def test_min_notional_quote():
    sizer = _sizer()
    rule = _rule(min_notional_size=Decimal("15"))
    result = sizer.min_notional_quote(rule)
    assert result == Decimal("15")


def test_project_total_amount_respects_cap():
    sizer = _sizer(max_total_notional_quote=Decimal("500"))
    rule = _rule()
    result = sizer.project_total_amount_quote(
        equity_quote=Decimal("10000"),
        mid=Decimal("100"),
        quote_size_pct=Decimal("0.01"),
        total_levels=8,
        rule=rule,
    )
    assert result <= Decimal("500")


def test_project_total_amount_meets_min_notional():
    sizer = _sizer(max_total_notional_quote=Decimal("0"))
    rule = _rule(min_notional_size=Decimal("50"))
    result = sizer.project_total_amount_quote(
        equity_quote=Decimal("100"),
        mid=Decimal("100"),
        quote_size_pct=Decimal("0.001"),
        total_levels=2,
        rule=rule,
    )
    assert result >= Decimal("50")


def test_none_rule_returns_original():
    sizer = _sizer()
    assert sizer.quantize_price(Decimal("100.5"), None, None) == Decimal("100.5")
    assert sizer.quantize_amount(Decimal("1.5"), None) == Decimal("1.5")
    assert sizer.min_notional_quote(None) == Decimal("0")
