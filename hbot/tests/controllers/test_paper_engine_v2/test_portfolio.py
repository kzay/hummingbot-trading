"""Tests for paper_engine_v2 portfolio.

Tests the critical accounting rules:
- Realized PnL is pure price PnL (no fees subtracted).
- Fees tracked separately in total_fees_paid.
- Spot vs perp ledger settlement.
- V6 position flip test vector.
- Available balance clamped to zero.
"""
from datetime import UTC, datetime
from decimal import Decimal

from simulation.portfolio import (
    MultiAssetLedger,
    PaperPortfolio,
    PortfolioConfig,
)
from simulation.types import _ZERO, OrderSide, PositionAction
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_PERP,
    BTC_SPOT,
    make_spec,
)


def make_portfolio(usdt=Decimal("10000"), btc=Decimal("0")) -> PaperPortfolio:
    return PaperPortfolio(
        {"USDT": usdt, "BTC": btc},
        PortfolioConfig(),
    )


def settle(
    portfolio,
    iid,
    side_str,
    qty_str,
    price_str,
    fee="0",
    leverage=1,
    position_action=PositionAction.AUTO,
    position_mode="ONEWAY",
):
    fee_str = str(fee)
    spec = make_spec(iid)
    side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
    return portfolio.settle_fill(
        instrument_id=iid,
        side=side,
        quantity=Decimal(qty_str),
        price=Decimal(price_str),
        fee=Decimal(fee_str),
        source_bot="test",
        now_ns=1_000_000_000,
        spec=spec,
        leverage=leverage,
        position_action=position_action,
        position_mode=position_mode,
    )


def settle_with_action(
    portfolio,
    iid,
    side_str,
    qty_str,
    price_str,
    *,
    position_action: PositionAction,
    fee="0",
    leverage=1,
    position_mode="HEDGE",
):
    fee_str = str(fee)
    spec = make_spec(iid)
    side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
    return portfolio.settle_fill(
        instrument_id=iid,
        side=side,
        quantity=Decimal(qty_str),
        price=Decimal(price_str),
        fee=Decimal(fee_str),
        source_bot="test",
        now_ns=1_000_000_000,
        spec=spec,
        leverage=leverage,
        position_action=position_action,
        position_mode=position_mode,
    )


class TestMultiAssetLedger:
    def test_credit_debit(self):
        ledger = MultiAssetLedger({"USDT": Decimal("1000")})
        ledger.credit("USDT", Decimal("500"))
        assert ledger.total("USDT") == Decimal("1500")
        ledger.debit("USDT", Decimal("200"))
        assert ledger.total("USDT") == Decimal("1300")

    def test_reserve_release(self):
        ledger = MultiAssetLedger({"USDT": Decimal("1000")})
        ledger.reserve("USDT", Decimal("300"))
        assert ledger.available("USDT") == Decimal("700")
        assert ledger.total("USDT") == Decimal("1000")
        ledger.release("USDT", Decimal("300"))
        assert ledger.available("USDT") == Decimal("1000")

    def test_available_clamped_to_zero(self):
        """Nautilus: graceful degradation -- free balance never negative."""
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.reserve("USDT", Decimal("200"))  # over-reserve
        assert ledger.available("USDT") == Decimal("0")

    def test_debit_clamped_to_zero(self):
        """Negative balance guard: debit cannot push total below zero."""
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.debit("USDT", Decimal("200"))
        assert ledger.total("USDT") == Decimal("0")

    def test_debit_exact_to_zero(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.debit("USDT", Decimal("100"))
        assert ledger.total("USDT") == Decimal("0")

    def test_debit_normal_positive(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.debit("USDT", Decimal("30"))
        assert ledger.total("USDT") == Decimal("70")

    def test_can_reserve_insufficient(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        assert ledger.can_reserve("USDT", Decimal("101")) is False

    def test_can_reserve_sufficient(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        assert ledger.can_reserve("USDT", Decimal("99")) is True

    def test_to_dict_from_dict(self):
        ledger = MultiAssetLedger({"USDT": Decimal("1000"), "BTC": Decimal("0.5")})
        d = ledger.to_dict()
        ledger2 = MultiAssetLedger.from_dict(d)
        assert ledger2.total("USDT") == ledger.total("USDT")
        assert ledger2.total("BTC") == ledger.total("BTC")


class TestSpotSettlement:
    def test_open_long_spot(self):
        p = make_portfolio(usdt=Decimal("5000"), btc=Decimal("0"))
        ev = settle(p, BTC_SPOT, "buy", "0.1", "100", fee="0.02")
        pos = p.get_position(BTC_SPOT)
        assert pos.quantity == Decimal("0.1")
        assert pos.avg_entry_price == Decimal("100")
        assert pos.realized_pnl == _ZERO
        assert pos.total_fees_paid == Decimal("0.02")
        # Balance: debit 100*0.1 + 0.02 = 10.02
        assert p.balance("USDT") == Decimal("4989.98")
        assert p.balance("BTC") == Decimal("0.1")

    def test_close_long_spot(self):
        p = make_portfolio(usdt=Decimal("4990"), btc=Decimal("0.1"))
        # Open position state manually
        ev = settle(p, BTC_SPOT, "buy", "0.1", "100")
        ev = settle(p, BTC_SPOT, "sell", "0.1", "110", fee="0.011")
        pos = p.get_position(BTC_SPOT)
        # realized_pnl = pure price: (110 - 100) * 0.1 = 1.0
        assert pos.realized_pnl == Decimal("1.0")
        # fees NOT in realized_pnl
        assert pos.total_fees_paid == Decimal("0.011")

    def test_spot_buy_debits_quote_credits_base(self):
        p = make_portfolio(usdt=Decimal("1000"), btc=Decimal("0"))
        settle(p, BTC_SPOT, "buy", "1", "100", fee="0.10")
        assert p.balance("USDT") == Decimal("899.90")  # 1000 - 100 - 0.10
        assert p.balance("BTC") == Decimal("1")

    def test_spot_sell_debits_base_credits_quote(self):
        p = make_portfolio(usdt=Decimal("0"), btc=Decimal("1"))
        settle(p, BTC_SPOT, "sell", "1", "100", fee="0.10")
        assert p.balance("BTC") == Decimal("0")
        assert p.balance("USDT") == Decimal("99.90")  # 100 - 0.10


class TestPositionFlip:
    def test_v6_position_flip(self):
        """V6 test vector from spec:
        Open long 1.0 @ 100, then sell 2.0 @ 105.
        → close 1.0 long (PnL=5), open 1.0 short @ 105.
        realized_pnl = 5.0 (NO fee subtracted).
        """
        p = make_portfolio(usdt=Decimal("10000"))
        # Open long 1.0 BTC @ 100
        settle(p, BTC_SPOT, "buy", "1.0", "100", fee="0")
        # Sell 2.0 @ 105: close 1.0 long + open 1.0 short
        settle(p, BTC_SPOT, "sell", "2.0", "105", fee="0")
        pos = p.get_position(BTC_SPOT)
        assert pos.quantity == Decimal("-1.0"), f"Expected -1.0, got {pos.quantity}"
        assert pos.avg_entry_price == Decimal("105")
        # Pure price PnL: (105 - 100) * 1.0 = 5.0
        assert pos.realized_pnl == Decimal("5.0")
        assert pos.total_fees_paid == _ZERO  # no fees in this test


class TestMarkToMarket:
    def test_mark_to_market_long(self):
        p = make_portfolio(usdt=Decimal("10000"), btc=Decimal("1"))
        settle(p, BTC_SPOT, "buy", "1.0", "100")
        p.mark_to_market({BTC_SPOT.key: Decimal("110")})
        pos = p.get_position(BTC_SPOT)
        assert pos.unrealized_pnl == Decimal("10")  # (110-100)*1

    def test_mark_to_market_short(self):
        p = make_portfolio(usdt=Decimal("10000"), btc=Decimal("1"))
        settle(p, BTC_SPOT, "buy", "1.0", "100")
        settle(p, BTC_SPOT, "sell", "2.0", "90")  # flip to short 1.0
        p.mark_to_market({BTC_SPOT.key: Decimal("80")})
        pos = p.get_position(BTC_SPOT)
        assert pos.unrealized_pnl > _ZERO  # short profits when price drops

    def test_daily_open_equity_rolls_at_new_utc_day(self):
        p = make_portfolio(usdt=Decimal("250"))
        p._daily_open_equity = Decimal("1000")
        p._daily_open_day_key = "2000-01-01"
        p.mark_to_market({})
        assert p.daily_open_equity == Decimal("250")
        assert p._daily_open_day_key == datetime.now(UTC).strftime("%Y-%m-%d")


class TestPerpLedgerSettlement:
    """Verify that perp fills correctly update the cash ledger (fees + PnL)."""

    def test_perp_open_debits_fee_only(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(p, BTC_PERP, "buy", "0.001", "70000", fee="0.014", leverage=1)
        assert p.balance("USDT") == Decimal("4999.986")

    def test_perp_close_debits_fee_and_loss(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(p, BTC_PERP, "buy", "0.001", "70000", fee="0.014", leverage=1)
        settle(p, BTC_PERP, "sell", "0.001", "69000", fee="0.014", leverage=1)
        expected = Decimal("5000") - Decimal("0.014") - Decimal("0.014") - Decimal("1")
        assert p.balance("USDT") == expected

    def test_perp_close_credits_profit(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(p, BTC_PERP, "buy", "0.001", "70000", fee="0.014", leverage=1)
        settle(p, BTC_PERP, "sell", "0.001", "71000", fee="0.014", leverage=1)
        expected = Decimal("5000") - Decimal("0.014") - Decimal("0.014") + Decimal("1")
        assert p.balance("USDT") == expected

    def test_equity_quote_reflects_settled_loss(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(p, BTC_PERP, "buy", "0.001", "70000", fee="0.014", leverage=1)
        settle(p, BTC_PERP, "sell", "0.001", "69000", fee="0.014", leverage=1)
        eq = p.equity_quote({BTC_PERP.key: Decimal("69000")})
        expected = Decimal("5000") - Decimal("0.028") - Decimal("1")
        assert eq == expected

    def test_snapshot_reflects_settled_balance(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(p, BTC_PERP, "buy", "0.001", "70000", fee="0.014", leverage=1)
        settle(p, BTC_PERP, "sell", "0.001", "69000", fee="0.014", leverage=1)
        snap = p.snapshot()
        expected = Decimal("5000") - Decimal("0.028") - Decimal("1")
        assert Decimal(snap["balances"]["USDT"]) == expected


class TestPerpMaintenanceMargin:
    def test_perp_maintenance_margin_reserved_on_mtm(self):
        p = make_portfolio(usdt=Decimal("1000"), btc=Decimal("0"))
        # Open perp long: ledger does NOT exchange notional (perp margin model)
        settle(p, BTC_PERP, "buy", "1.0", "100", fee="0", leverage=10)
        # Mark to market should lock maintenance margin on quote.
        p.mark_to_market({BTC_PERP.key: Decimal("100")})
        # maint = (notional / leverage) * margin_maint = (100 / 10) * 0.05 = 0.5
        assert p.maintenance_margin_quote() == Decimal("0.5")
        assert p.available("USDT") == Decimal("999.5")

    def test_perp_maintenance_margin_updates_with_price(self):
        p = make_portfolio(usdt=Decimal("1000"), btc=Decimal("0"))
        settle(p, BTC_PERP, "buy", "1.0", "100", fee="0", leverage=10)
        p.mark_to_market({BTC_PERP.key: Decimal("200")})
        # maint = (200 / 10) * 0.05 = 1.0
        assert p.maintenance_margin_quote() == Decimal("1.0")


class TestRiskGuard:
    def test_drawdown_hard_stop(self):

        from simulation.types import OrderStatus, PaperOrder, PaperOrderType
        p = make_portfolio(usdt=Decimal("100"))
        spec = make_spec(BTC_SPOT)
        # Force peak equity and then a large loss
        p._peak_equity = Decimal("1000")
        # Equity at 100 with peak 1000 → drawdown = 90%
        order = PaperOrder(
            order_id="test", instrument_id=BTC_SPOT,
            side=OrderSide.BUY, order_type=PaperOrderType.LIMIT,
            price=Decimal("100"), quantity=Decimal("0.1"),
            status=OrderStatus.OPEN,
            created_at_ns=0, updated_at_ns=0,
        )
        result = p.risk_guard.check_order(order, spec, Decimal("100"))
        assert result == "drawdown_hard_stop"


class TestFundingSettlement:
    def test_negative_funding_charge_credits_quote(self):
        p = make_portfolio(usdt=Decimal("1000"))
        settle(p, BTC_PERP, "buy", "1.0", "100", fee="0", leverage=1)
        before = p.balance("USDT")
        p.apply_funding(BTC_PERP, Decimal("-0.5"), now_ns=1)
        assert p.balance("USDT") == before + Decimal("0.5")
        assert p.get_position(BTC_PERP).funding_paid == Decimal("-0.5")


class TestPortfolioSnapshot:
    def test_snapshot_restore_roundtrip(self):
        p = make_portfolio(usdt=Decimal("5000"), btc=Decimal("1"))
        settle(p, BTC_SPOT, "buy", "0.5", "100")
        p._daily_open_day_key = "2026-03-01"
        snap = p.snapshot()

        p2 = make_portfolio(usdt=Decimal("9999"))
        p2.restore_from_snapshot(snap)
        assert p2.balance("USDT") == p.balance("USDT")
        pos = p2.get_position(BTC_SPOT)
        assert pos.quantity == Decimal("0.5")
        assert p2.daily_open_equity == p.daily_open_equity
        assert p2._daily_open_day_key == "2026-03-01"

    def test_snapshot_restore_preserves_hedge_legs(self):
        p = make_portfolio(usdt=Decimal("5000"))
        settle(
            p,
            BTC_PERP,
            "buy",
            "1.0",
            "100",
            leverage=5,
            position_action=PositionAction.OPEN_LONG,
            position_mode="HEDGE",
        )
        settle(
            p,
            BTC_PERP,
            "sell",
            "0.4",
            "105",
            leverage=5,
            position_action=PositionAction.OPEN_SHORT,
            position_mode="HEDGE",
        )

        snap = p.snapshot()
        p2 = make_portfolio(usdt=Decimal("9999"))
        p2.restore_from_snapshot(snap)
        pos = p2.get_position(BTC_PERP)

        assert pos.position_mode == "HEDGE"
        assert pos.long_quantity == Decimal("1.0")
        assert pos.short_quantity == Decimal("0.4")
        assert pos.quantity == Decimal("0.6")
        assert pos.gross_quantity == Decimal("1.4")

    def test_snapshot_restore_preserves_hedge_legs(self):
        p = make_portfolio(usdt=Decimal("5000"), btc=Decimal("0"))
        settle_with_action(
            p,
            BTC_PERP,
            "buy",
            "0.4",
            "100",
            position_action=PositionAction.OPEN_LONG,
            leverage=5,
        )
        settle_with_action(
            p,
            BTC_PERP,
            "sell",
            "0.2",
            "101",
            position_action=PositionAction.OPEN_SHORT,
            leverage=5,
        )

        snap = p.snapshot()
        p2 = make_portfolio(usdt=Decimal("1"))
        p2.restore_from_snapshot(snap)

        net_pos = p2.get_position(BTC_PERP)
        long_pos = p2.get_position(BTC_PERP, position_action=PositionAction.OPEN_LONG)
        short_pos = p2.get_position(BTC_PERP, position_action=PositionAction.OPEN_SHORT)

        assert net_pos.position_mode == "HEDGE"
        assert net_pos.long_quantity == Decimal("0.4")
        assert net_pos.short_quantity == Decimal("0.2")
        assert long_pos.quantity == Decimal("0.4")
        assert short_pos.quantity == Decimal("-0.2")


class TestOneWayPositionMode:
    def test_oneway_nets_even_with_explicit_leg_actions(self):
        p = make_portfolio(usdt=Decimal("5000"), btc=Decimal("0"))
        settle_with_action(
            p,
            BTC_PERP,
            "buy",
            "1.0",
            "100",
            position_action=PositionAction.OPEN_LONG,
            leverage=5,
            position_mode="ONEWAY",
        )
        settle_with_action(
            p,
            BTC_PERP,
            "sell",
            "0.4",
            "105",
            position_action=PositionAction.OPEN_SHORT,
            leverage=5,
            position_mode="ONEWAY",
        )

        pos = p.get_position(BTC_PERP)
        assert pos.position_mode == "ONEWAY"
        assert pos.quantity == Decimal("0.6")
        assert pos.long_quantity == Decimal("0.6")
        assert pos.short_quantity == _ZERO
        assert pos.gross_quantity == Decimal("0.6")
        assert pos.avg_entry_price == Decimal("100")
        # Realized PnL is pure price PnL on the reduced leg.
        assert pos.realized_pnl == Decimal("2.0")

    def test_oneway_action_scoped_get_position_returns_netted_view(self):
        p = make_portfolio(usdt=Decimal("5000"), btc=Decimal("0"))
        settle_with_action(
            p,
            BTC_PERP,
            "buy",
            "0.7",
            "100",
            position_action=PositionAction.OPEN_LONG,
            leverage=5,
            position_mode="ONEWAY",
        )
        settle_with_action(
            p,
            BTC_PERP,
            "sell",
            "0.2",
            "101",
            position_action=PositionAction.CLOSE_LONG,
            leverage=5,
            position_mode="ONEWAY",
        )

        net_pos = p.get_position(BTC_PERP)
        long_view = p.get_position(BTC_PERP, position_action=PositionAction.OPEN_LONG)
        short_view = p.get_position(BTC_PERP, position_action=PositionAction.OPEN_SHORT)

        assert net_pos.quantity == Decimal("0.5")
        assert long_view.quantity == net_pos.quantity
        assert short_view.quantity == net_pos.quantity
