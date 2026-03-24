"""Tests for kill_switch — cancel-all, retry logic, partial cancel, dry run, container stop."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.kill_switch.main import (
    _cancel_all_orders_ccxt,
    _combine_kill_result,
    _flatten_position_ccxt,
    _kill_execution_succeeded,
    _log_escalation_if_needed,
    _publish_audit,
    _stop_bot_container,
)

# ── helpers ──────────────────────────────────────────────────────────

def _mock_exchange(open_orders=None, cancel_raises=None):
    """Create a mock ccxt exchange class and instance."""
    exchange_instance = MagicMock()
    if open_orders is not None:
        exchange_instance.fetch_open_orders.return_value = open_orders
    if cancel_raises:
        exchange_instance.cancel_order.side_effect = cancel_raises
    else:
        exchange_instance.cancel_order.return_value = {"status": "ok"}

    exchange_cls = MagicMock(return_value=exchange_instance)
    return exchange_cls, exchange_instance


# ── Successful cancel-all ────────────────────────────────────────────

class TestCancelAll:
    @patch("services.kill_switch.main.ccxt")
    def test_cancel_all_success(self, mock_ccxt):
        orders = [
            {"id": "order-1", "symbol": "BTC/USDT"},
            {"id": "order-2", "symbol": "BTC/USDT"},
        ]
        exchange_cls, exchange_inst = _mock_exchange(open_orders=orders)
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="pass",
            trading_pair="BTC-USDT",
            dry_run=False,
        )
        assert result["status"] == "executed"
        assert set(result["cancelled"]) == {"order-1", "order-2"}
        assert result.get("failed", []) == []

    @patch("services.kill_switch.main.ccxt")
    def test_cancel_no_open_orders(self, mock_ccxt):
        exchange_cls, _ = _mock_exchange(open_orders=[])
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="pass",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "executed"
        assert result["cancelled"] == []


# ── Position flattening ───────────────────────────────────────────────

class TestFlattenPosition:
    @patch("services.kill_switch.main.ccxt")
    def test_flatten_long_sends_reduce_only_sell(self, mock_ccxt):
        exchange_inst = MagicMock()
        exchange_inst.fetch_positions.return_value = [{"symbol": "BTC/USDT", "side": "long", "contracts": 0.25}]
        exchange_inst.create_order.return_value = {"id": "close-1"}
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _flatten_position_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="pass",
            trading_pair="BTC-USDT",
        )
        assert result["status"] == "executed"
        assert result["side"] == "sell"
        exchange_inst.create_order.assert_called_once_with(
            symbol="BTC/USDT",
            type="market",
            side="sell",
            amount=0.25,
            params={"reduceOnly": True},
        )

    @patch("services.kill_switch.main.ccxt")
    def test_flatten_short_sends_reduce_only_buy(self, mock_ccxt):
        exchange_inst = MagicMock()
        exchange_inst.fetch_positions.return_value = [{"symbol": "BTC/USDT", "side": "short", "contracts": 0.10}]
        exchange_inst.create_order.return_value = {"id": "close-2"}
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _flatten_position_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair="BTC-USDT",
        )
        assert result["status"] == "executed"
        assert result["side"] == "buy"
        exchange_inst.create_order.assert_called_once_with(
            symbol="BTC/USDT",
            type="market",
            side="buy",
            amount=0.1,
            params={"reduceOnly": True},
        )

    @patch("services.kill_switch.main.ccxt")
    def test_flatten_no_position(self, mock_ccxt):
        exchange_inst = MagicMock()
        exchange_inst.fetch_positions.return_value = [{"symbol": "BTC/USDT", "side": "long", "contracts": 0}]
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _flatten_position_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair="BTC-USDT",
        )
        assert result["status"] == "no_position"
        exchange_inst.create_order.assert_not_called()

    @patch("services.kill_switch.main.ccxt")
    def test_flatten_skips_without_trading_pair(self, mock_ccxt):
        result = _flatten_position_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
        )
        assert result["status"] == "skipped"
        assert result["error"] == "missing_trading_pair"


# ── Retry on failure ─────────────────────────────────────────────────

class TestRetryLogic:
    @patch("services.kill_switch.main.ccxt")
    @patch("services.kill_switch.main.time")
    def test_fetch_retries_on_transient_error(self, mock_time, mock_ccxt):
        mock_time.sleep = MagicMock()
        exchange_inst = MagicMock()
        exchange_inst.fetch_open_orders.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            [{"id": "o1", "symbol": "BTC/USDT"}],
        ]
        exchange_inst.cancel_order.return_value = {"status": "ok"}
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair="BTC-USDT",
            dry_run=False,
        )
        assert result["status"] == "executed"
        assert "o1" in result["cancelled"]
        assert exchange_inst.fetch_open_orders.call_count == 3

    @patch("services.kill_switch.main.ccxt")
    @patch("services.kill_switch.main.time")
    def test_fetch_all_retries_exhausted(self, mock_time, mock_ccxt):
        mock_time.sleep = MagicMock()
        exchange_inst = MagicMock()
        exchange_inst.fetch_open_orders.side_effect = Exception("permanent failure")
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "error"
        assert "fetch_open_orders" in result["error"]

    @patch("services.kill_switch.main.ccxt")
    @patch("services.kill_switch.main.time")
    def test_cancel_order_retries(self, mock_time, mock_ccxt):
        mock_time.sleep = MagicMock()
        exchange_inst = MagicMock()
        exchange_inst.fetch_open_orders.return_value = [{"id": "o1", "symbol": "BTC/USDT"}]
        exchange_inst.cancel_order.side_effect = [
            Exception("transient"),
            Exception("transient"),
            {"status": "ok"},
        ]
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "executed"
        assert "o1" in result["cancelled"]
        assert exchange_inst.cancel_order.call_count == 3


# ── Partial cancel ───────────────────────────────────────────────────

class TestPartialCancel:
    @patch("services.kill_switch.main.ccxt")
    @patch("services.kill_switch.main.time")
    @patch("services.kill_switch.main.logger")
    def test_some_orders_fail_partial_status(self, mock_logger, mock_time, mock_ccxt):
        mock_time.sleep = MagicMock()
        exchange_inst = MagicMock()
        exchange_inst.fetch_open_orders.return_value = [
            {"id": "o1", "symbol": "BTC/USDT"},
            {"id": "o2", "symbol": "BTC/USDT"},
        ]
        # o1 succeeds, o2 fails all 3 retries
        exchange_inst.cancel_order.side_effect = [
            {"status": "ok"},          # o1 attempt 1 → success
            Exception("fail"),         # o2 attempt 1
            Exception("fail"),         # o2 attempt 2
            Exception("fail"),         # o2 attempt 3
        ]
        exchange_cls = MagicMock(return_value=exchange_inst)
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "partial"
        assert "o1" in result["cancelled"]
        assert "o2" in result["failed"]

        combined = _combine_kill_result(result, {"status": "disabled", "error": ""})
        _log_escalation_if_needed(combined)
        mock_logger.error.assert_called()
        msg = str(mock_logger.error.call_args[0][0])
        assert "Kill switch escalation" in msg or "non-success" in msg


# ── Dry run mode ─────────────────────────────────────────────────────

class TestDryRun:
    @patch("services.kill_switch.main.ccxt")
    def test_dry_run_no_actual_cancel(self, mock_ccxt):
        exchange_cls, exchange_inst = _mock_exchange(open_orders=[{"id": "o1"}])
        mock_ccxt.bitget = exchange_cls

        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=True,
        )
        assert result["status"] == "dry_run"
        assert result["cancelled"] == []
        exchange_inst.fetch_open_orders.assert_not_called()
        exchange_inst.cancel_order.assert_not_called()


# ── Missing credentials ─────────────────────────────────────────────

class TestMissingCredentials:
    @patch("services.kill_switch.main.ccxt")
    def test_missing_api_key(self, mock_ccxt):
        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "error"
        assert result["error"] == "missing_credentials"

    @patch("services.kill_switch.main.ccxt")
    def test_missing_secret(self, mock_ccxt):
        result = _cancel_all_orders_ccxt(
            exchange_id="bitget",
            api_key="key",
            secret="",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "error"
        assert result["error"] == "missing_credentials"

    def test_ccxt_not_installed(self):
        with patch("services.kill_switch.main.ccxt", None):
            result = _cancel_all_orders_ccxt(
                exchange_id="bitget",
                api_key="key",
                secret="secret",
                passphrase="",
                trading_pair=None,
                dry_run=False,
            )
            assert result["status"] == "error"
            assert result["error"] == "ccxt_not_installed"

    @patch("services.kill_switch.main.ccxt")
    def test_unknown_exchange(self, mock_ccxt):
        mock_ccxt.unknown_exchange = None
        result = _cancel_all_orders_ccxt(
            exchange_id="unknown_exchange",
            api_key="key",
            secret="secret",
            passphrase="",
            trading_pair=None,
            dry_run=False,
        )
        assert result["status"] == "error"
        assert "unknown_exchange" in result["error"]


# ── Container stop ───────────────────────────────────────────────────

class TestContainerStop:
    def test_stop_container_success(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [
            b"HTTP/1.1 204 No Content\r\n\r\n",
            b"",
        ]
        mock_socket_mod = MagicMock()
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1
        mock_socket_mod.socket.return_value = mock_sock

        import sys
        with patch.dict(sys.modules, {"socket": mock_socket_mod}):
            result = _stop_bot_container("bot1")
        assert result is True
        mock_sock.connect.assert_called_once()

    def test_stop_container_failure(self):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = Exception("Docker socket unavailable")
        mock_socket_mod = MagicMock()
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1
        mock_socket_mod.socket.return_value = mock_sock

        import sys
        with patch.dict(sys.modules, {"socket": mock_socket_mod}):
            result = _stop_bot_container("bot1")
        assert result is False


# ── Audit event publishing ──────────────────────────────────────────

class TestAuditPublish:
    def test_publish_audit_calls_xadd(self):
        mock_client = MagicMock()
        _publish_audit(
            client=mock_client,
            producer="kill_switch",
            instance_name="bot1",
            action="triggered",
            details={"test": True},
        )
        mock_client.xadd.assert_called_once()
        call_args = mock_client.xadd.call_args
        payload = call_args[1]["payload"] if "payload" in call_args[1] else call_args[0][1]
        assert payload["event_type"] == "audit"
        assert payload["category"] == "kill_switch"


class TestKillExecutionResult:
    def test_partial_cancel_is_not_success(self):
        result = {"status": "partial", "failed": ["o2"], "flatten": {"status": "disabled"}}
        assert _kill_execution_succeeded(result) is False

    def test_cancel_success_with_no_position_flatten_is_success(self):
        result = {"status": "executed", "failed": [], "flatten": {"status": "no_position"}}
        assert _kill_execution_succeeded(result) is True
