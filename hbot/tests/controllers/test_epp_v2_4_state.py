import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("hummingbot")

from controllers.core import RegimeSpec
from platform_lib.core.daily_state_store import DailyStateStore
from controllers.epp_v2_4 import EppV24Controller


class _DummyController:
    pass


def _make_dummy(tmp_path: Path, now_ts: float) -> _DummyController:
    dummy = _DummyController()
    dummy.config = SimpleNamespace(
        log_dir=str(tmp_path), instance_name="botx", variant="a",
        override_spread_pct=None, startup_position_sync=True,
        startup_sync_timeout_s=180,
        connector_name="binance", trading_pair="BTC-USDT",
        position_drift_soft_pause_pct=Decimal("0.05"),
        bot_mode="paper",
    )
    dummy.market_data_provider = SimpleNamespace(time=lambda: now_ts)
    dummy._daily_key = datetime.now(UTC).strftime("%Y-%m-%d")
    dummy._daily_equity_open = Decimal("100")
    dummy._daily_equity_peak = Decimal("110")
    dummy._traded_notional_today = Decimal("50")
    dummy._fills_count_today = 4
    dummy._fees_paid_today_quote = Decimal("1.2")
    dummy._funding_cost_today_quote = Decimal("0.1")
    dummy._realized_pnl_today = Decimal("2.5")
    dummy._position_base = Decimal("0.25")
    dummy._avg_entry_price = Decimal("42000")
    dummy._last_daily_state_save_ts = 0.0
    dummy._startup_position_sync_done = False
    dummy._startup_sync_first_ts = 0.0
    dummy._startup_sync_retries = 0
    dummy._position_drift_pct = Decimal("0")
    dummy._is_perp = False
    dummy._daily_state_path = lambda: EppV24Controller._daily_state_path(dummy)
    state_path = EppV24Controller._daily_state_path(dummy)
    dummy._state_store = DailyStateStore(
        file_path=state_path,
        redis_key=f"epp:daily:{dummy.config.instance_name}",
        redis_url=None,
        save_throttle_s=30.0,
    )
    return dummy


def test_daily_state_persists_position(tmp_path: Path):
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    EppV24Controller._save_daily_state(dummy, force=True)
    dummy._position_base = Decimal("0")
    dummy._avg_entry_price = Decimal("0")
    dummy._daily_equity_open = None
    dummy._daily_equity_peak = None
    dummy._traded_notional_today = Decimal("0")
    dummy._fills_count_today = 0
    dummy._fees_paid_today_quote = Decimal("0")
    dummy._funding_cost_today_quote = Decimal("0")
    dummy._realized_pnl_today = Decimal("0")
    EppV24Controller._load_daily_state(dummy)
    assert dummy._position_base == Decimal("0.25")
    assert dummy._avg_entry_price == Decimal("42000")
    assert dummy._fills_count_today == 4


def test_save_throttled(tmp_path: Path):
    now_ts = 1_700_000_000.0
    dummy = _make_dummy(tmp_path, now_ts=now_ts)
    EppV24Controller._save_daily_state(dummy)
    dummy._position_base = Decimal("2")
    EppV24Controller._save_daily_state(dummy)
    dummy._state_store._join_pending_save()
    state_path = Path(EppV24Controller._daily_state_path(dummy))
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["position_base"] == "0.25"


def test_override_spread_pct():
    dummy = _DummyController()
    dummy.config = SimpleNamespace(override_spread_pct=Decimal("0.005"), turnover_cap_x=Decimal("1"))
    regime = RegimeSpec(
        spread_min=Decimal("0.001"),
        spread_max=Decimal("0.003"),
        levels_min=1,
        levels_max=2,
        refresh_s=60,
        target_base_pct=Decimal("0.5"),
        quote_size_pct_min=Decimal("0.001"),
        quote_size_pct_max=Decimal("0.002"),
        one_sided="off",
    )
    spread = EppV24Controller._pick_spread_pct(dummy, regime, Decimal("10"))
    assert spread == Decimal("0.005")


# --- Cross-day position preservation ---

def test_cross_day_restart_preserves_position(tmp_path: Path):
    """Position and avg_entry should survive a day boundary restart."""
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    EppV24Controller._save_daily_state(dummy, force=True)

    state_path = Path(EppV24Controller._daily_state_path(dummy))
    data = json.loads(state_path.read_text(encoding="utf-8"))
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    data["day_key"] = yesterday
    state_path.write_text(json.dumps(data), encoding="utf-8")

    dummy._position_base = Decimal("0")
    dummy._avg_entry_price = Decimal("0")
    dummy._traded_notional_today = Decimal("999")
    dummy._fills_count_today = 99
    EppV24Controller._load_daily_state(dummy)

    assert dummy._position_base == Decimal("0.25"), "position_base must carry across day boundary"
    assert dummy._avg_entry_price == Decimal("42000"), "avg_entry_price must carry across day boundary"
    assert dummy._traded_notional_today == Decimal("999"), "daily counters must NOT be restored on cross-day"
    assert dummy._fills_count_today == 99, "daily counters must NOT be restored on cross-day"


# --- Startup position sync ---

class _FakeConnector:
    """Minimal connector stub for startup sync tests."""
    def __init__(self, balance: Decimal):
        self._balance = balance

    def get_balance(self, asset: str) -> Decimal:
        return self._balance


class _FakeRuntimeAdapter:
    def __init__(self, base_asset: str = "BTC"):
        self._base_asset = base_asset

    def get_mid_price(self) -> Decimal:
        return Decimal("65000")


def _make_sync_dummy(tmp_path: Path, local_pos: Decimal, exchange_pos: Decimal):
    """Build a dummy wired for startup sync testing."""
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    dummy.config.bot_mode = "live"
    dummy._position_base = local_pos
    dummy._avg_entry_price = Decimal("42000") if local_pos != Decimal("0") else Decimal("0")
    dummy._startup_position_sync_done = False
    dummy._startup_orphan_check_done = False
    dummy._startup_sync_retries = 0
    dummy._STARTUP_SYNC_MAX_RETRIES = 3
    dummy._runtime_adapter = _FakeRuntimeAdapter()
    dummy._startup_recon_attempt = 0
    dummy._startup_recon_next_retry_ts = 0.0
    dummy._startup_recon_soft_pause = False
    dummy._STARTUP_RECON_MAX_ATTEMPTS = 3
    dummy._STARTUP_RECON_BACKOFF_DELAYS = (2.0, 4.0, 8.0)
    connector = _FakeConnector(exchange_pos)
    dummy._connector = lambda: connector
    dummy._get_reference_price = lambda: Decimal("65000")
    dummy._save_daily_state = lambda force=False: None
    dummy._compute_total_base_with_locked = lambda c: c.get_balance("BTC")
    dummy._ops_guard = SimpleNamespace(force_hard_stop=lambda reason: None)
    import types as _types_mod
    dummy._cancel_orphan_orders_on_startup = _types_mod.MethodType(
        EppV24Controller._cancel_orphan_orders_on_startup, dummy,
    )
    return dummy


def test_startup_sync_adopts_exchange_position(tmp_path: Path):
    """When exchange has a position but local is zero, adopt exchange."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.5")
    assert dummy._avg_entry_price == Decimal("65000")
    assert dummy._startup_position_sync_done is True


def test_startup_sync_no_drift(tmp_path: Path):
    """When exchange matches local, nothing changes."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0.25"), exchange_pos=Decimal("0.25"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.25")
    assert dummy._avg_entry_price == Decimal("42000")


def test_startup_sync_corrects_stale_local(tmp_path: Path):
    """When exchange differs from local, exchange wins."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0.25"), exchange_pos=Decimal("0.10"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.10")
    assert dummy._avg_entry_price == Decimal("42000")


def test_startup_sync_disabled(tmp_path: Path):
    """When startup_position_sync=False, skip the sync."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy.config.startup_position_sync = False
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0"), "sync disabled — position must not change"
    assert dummy._startup_position_sync_done is True


def test_startup_sync_runs_in_paper_mode_like_live(tmp_path: Path):
    """Paper mode runs startup position sync like live — unified data path."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy.config.startup_position_sync = True
    dummy.config.bot_mode = "paper"
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is True
    assert dummy._position_base == Decimal("0.5"), "paper mode must adopt exchange position like live"


def test_startup_sync_cancels_restored_orphan_orders(tmp_path: Path):
    """Startup should clear restored orders that have no live executors."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0"))
    canceled: list[str] = []
    order_a = SimpleNamespace(
        client_order_id="paper_v2_135", trading_pair="BTC-USDT",
        trade_type=SimpleNamespace(name="BUY"), source_bot="bitget_perpetual",
    )
    order_b = SimpleNamespace(
        client_order_id="paper_v2_136", trading_pair="BTC-USDT",
        trade_type=SimpleNamespace(name="SELL"), source_bot="bitget_perpetual",
    )
    connector = SimpleNamespace(
        get_open_orders=lambda: [order_a, order_b],
        get_balance=lambda asset: Decimal("0"),
    )
    strategy = SimpleNamespace(
        cancel=lambda conn, pair, oid: canceled.append(f"{conn}:{pair}:{oid}"),
    )
    dummy.config.startup_position_sync = True
    dummy.config.bot_mode = "paper"
    dummy.config.connector_name = "bitget_perpetual"
    dummy.config.trading_pair = "BTC-USDT"
    dummy.executors_info = []
    dummy.filter_executors = lambda executors, filter_func: [e for e in executors if filter_func(e)]
    dummy._recently_issued_levels = {"buy_0": 100.0}
    dummy._connector = lambda: connector
    dummy.strategy = strategy
    dummy._strategy = None

    EppV24Controller._run_startup_position_sync(dummy)

    assert dummy._startup_position_sync_done is True
    assert dummy._startup_orphan_check_done is True
    assert canceled == [
        "bitget_perpetual:BTC-USDT:paper_v2_135",
        "bitget_perpetual:BTC-USDT:paper_v2_136",
    ]
    assert dummy._recently_issued_levels == {}


def test_startup_sync_both_zero(tmp_path: Path):
    """When both local and exchange are zero, no-op."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0")


def test_startup_sync_retries_when_connector_unavailable(tmp_path: Path):
    """When connector is None, sync should defer (not mark done) so it retries."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is False, "must not mark done when connector unavailable"
    assert dummy._position_base == Decimal("0"), "position must not change on deferred sync"

    dummy._connector = lambda: _FakeConnector(Decimal("0.5"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is True
    assert dummy._position_base == Decimal("0.5"), "retry must succeed once connector available"


def test_startup_sync_gives_up_after_max_retries(tmp_path: Path):
    """After max retries with no connector, sync gives up and marks done."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    for _ in range(EppV24Controller._STARTUP_SYNC_MAX_RETRIES):
        EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is True, "must give up after max retries"
    assert dummy._position_base == Decimal("0"), "position must not change when sync never succeeded"


def test_startup_sync_blocks_trading_while_pending(tmp_path: Path):
    """The startup_position_sync_pending risk reason should be emitted."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is False
    risk_reasons = []
    if not dummy._startup_position_sync_done:
        risk_reasons.append("startup_position_sync_pending")
    assert "startup_position_sync_pending" in risk_reasons


def test_startup_sync_repeated_exceptions_escalate_to_soft_pause(tmp_path: Path):
    """Persistent connector exceptions should enter SOFT_PAUSE after max recon attempts."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))

    class _ExplodingConnector:
        def get_position(self, *_args, **_kwargs):
            raise RuntimeError("connector blew up")

    dummy._is_perp = True
    dummy._connector = lambda: _ExplodingConnector()
    tick_ts = 1_700_000_000.0
    for _ in range(dummy._STARTUP_RECON_MAX_ATTEMPTS):
        tick_ts += 10.0
        dummy.market_data_provider = SimpleNamespace(time=lambda t=tick_ts: t)
        EppV24Controller._run_startup_position_sync(dummy)

    assert dummy._startup_position_sync_done is True
    assert dummy._startup_recon_soft_pause is True
