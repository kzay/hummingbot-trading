import importlib
import json
import logging
import os
import sys
import time
import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from hummingbot.client import hummingbot_application as hb_app_module
from hummingbot.client.hummingbot_application import HummingbotApplication
from hummingbot.client.ui import interface_utils as hb_interface_utils
from hummingbot.core import connector_manager as hb_connector_manager
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.event.events import MarketOrderFailureEvent
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction
from controllers.paper_engine_v2.hb_bridge import (
    _canonical_name,
    _paper_exchange_mode_for_instance,
    enable_framework_paper_compat_fallbacks,
    install_paper_desk_bridge as _install_paper_desk_bridge_v2,
)
from services.common.preflight import run_controller_preflight

try:
    from pydantic import ValidationError as PydanticValidationError
except Exception:  # pragma: no cover
    PydanticValidationError = None

try:
    from pydantic_core import ValidationError as PydanticCoreValidationError
except Exception:  # pragma: no cover
    PydanticCoreValidationError = None

try:
    from services.contracts.event_schemas import AuditEvent, MarketDepthSnapshotEvent, MarketSnapshotEvent
    from services.contracts.stream_names import DEFAULT_CONSUMER_GROUP, MARKET_DEPTH_STREAM
    from services.hb_bridge.intent_consumer import HBIntentConsumer
    from services.hb_bridge.publisher import HBEventPublisher
    from services.hb_bridge.redis_client import RedisStreamClient
except Exception:  # pragma: no cover
    AuditEvent = None
    MarketDepthSnapshotEvent = None
    MarketSnapshotEvent = None
    DEFAULT_CONSUMER_GROUP = "hb_group_v1"
    MARKET_DEPTH_STREAM = "hb.market_depth.v1"
    HBIntentConsumer = None
    HBEventPublisher = None
    RedisStreamClient = None


def _install_trade_monitor_guard():
    """
    Hummingbot's UI trade monitor can poll stale connector aliases (e.g. binance_perpetual)
    while testnet connectors are active. Swallow only that known monitor-only error to avoid
    noisy console spam without affecting strategy execution.
    """
    if getattr(hb_interface_utils, "_hbot_trade_monitor_guard_installed", False):
        return
    original_start_trade_monitor = hb_interface_utils.start_trade_monitor

    async def guarded_start_trade_monitor(*args, **kwargs):
        try:
            return await original_start_trade_monitor(*args, **kwargs)
        except ValueError as exc:
            if "Connector " in str(exc) and " not found" in str(exc):
                return None
            raise

    hb_interface_utils.start_trade_monitor = guarded_start_trade_monitor
    if hasattr(hb_app_module, "start_trade_monitor"):
        hb_app_module.start_trade_monitor = guarded_start_trade_monitor
    hb_interface_utils._hbot_trade_monitor_guard_installed = True


def _install_connector_alias_guard():
    if getattr(hb_connector_manager, "_hbot_connector_alias_guard_installed", False):
        return
    original_update_balances = hb_connector_manager.ConnectorManager.update_connector_balances

    async def guarded_update_connector_balances(self, connector_name):
        try:
            return await original_update_balances(self, connector_name)
        except ValueError as exc:
            if connector_name == "binance_perpetual":
                return await original_update_balances(self, "binance_perpetual_testnet")
            raise exc

    hb_connector_manager.ConnectorManager.update_connector_balances = guarded_update_connector_balances
    hb_connector_manager._hbot_connector_alias_guard_installed = True


def _install_transient_bitget_ws_timeout_guard():
    """
    Bitget websocket channels can intermittently timeout under network jitter.
    We keep the reconnect behavior but avoid flooding ERROR logs with full stack traces
    for this specific transient class, while preserving all non-timeout exceptions.
    """
    if os.getenv("HB_SUPPRESS_TRANSIENT_WS_TIMEOUT_ERRORS", "true").lower() not in {"1", "true", "yes"}:
        return
    if getattr(logging, "_hbot_transient_bitget_ws_timeout_guard_installed", False):
        return

    target_logger_names = {
        # Perpetual
        "hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_api_order_book_data_source."
        "BitgetPerpetualAPIOrderBookDataSource",
        "hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_api_user_stream_data_source."
        "BitgetPerpetualUserStreamDataSource",
        # Spot
        "hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source.BitgetAPIOrderBookDataSource",
    }
    target_messages = {
        "Unexpected error occurred when listening to order book streams. Retrying in 5 seconds...",
        "Unexpected error while listening to user stream. Retrying after 5 seconds...",
    }
    min_emit_interval_s = max(1.0, float(os.getenv("HB_TRANSIENT_WS_TIMEOUT_LOG_INTERVAL_S", "120")))
    last_emit_by_logger: Dict[str, float] = {}

    class _TransientBitgetWsTimeoutFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name not in target_logger_names:
                return True
            message = record.getMessage()
            if message not in target_messages:
                return True
            exc = record.exc_info[1] if record.exc_info else None
            # Only suppress/downgrade strict timeout reconnect loops.
            if not isinstance(exc, TimeoutError):
                return True
            now = time.time()
            last = last_emit_by_logger.get(record.name, 0.0)
            if now - last < min_emit_interval_s:
                return False
            last_emit_by_logger[record.name] = now
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
            record.msg = (
                "Transient websocket timeout; reconnecting automatically "
                f"(throttled to >= {int(min_emit_interval_s)}s)."
            )
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            return True

    timeout_filter = _TransientBitgetWsTimeoutFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(timeout_filter)
    for handler in root_logger.handlers:
        handler.addFilter(timeout_filter)
    for logger_name in target_logger_names:
        logging.getLogger(logger_name).addFilter(timeout_filter)
    logging._hbot_transient_bitget_ws_timeout_guard_installed = True


def _to_positive_decimal(value: Any) -> Optional[Decimal]:
    try:
        if value is None:
            return None
        dec = Decimal(str(value))
        if dec.is_nan() or dec <= Decimal("0"):
            return None
        return dec
    except Exception:
        return None


def _extract_depth_level(entry: Any) -> Optional[Dict[str, float]]:
    price_raw = None
    size_raw = None
    if isinstance(entry, dict):
        price_raw = (
            entry.get("price")
            if "price" in entry
            else entry.get("p", entry.get("0"))
        )
        size_raw = (
            entry.get("size")
            if "size" in entry
            else entry.get("amount", entry.get("quantity", entry.get("q", entry.get("1"))))
        )
    elif isinstance(entry, (tuple, list)):
        if len(entry) >= 2:
            price_raw = entry[0]
            size_raw = entry[1]
    else:
        price_raw = getattr(entry, "price", None)
        size_raw = getattr(entry, "size", None)
        if size_raw is None:
            size_raw = getattr(entry, "amount", None)
        if size_raw is None:
            size_raw = getattr(entry, "quantity", None)
    price = _to_positive_decimal(price_raw)
    size = _to_positive_decimal(size_raw)
    if price is None or size is None:
        return None
    return {"price": float(price), "size": float(size)}


def _extract_order_book_depth_snapshot(
    connector_obj: Any,
    pair: str,
    max_levels: int,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "bids": [],
        "asks": [],
        "best_bid": None,
        "best_ask": None,
        "market_sequence": None,
    }
    get_order_book_fn = getattr(connector_obj, "get_order_book", None)
    if not callable(get_order_book_fn):
        return out
    try:
        book = get_order_book_fn(pair)
    except Exception:
        return out

    def _iter_entries(book_obj: Any, side: str) -> List[Any]:
        method_name = f"{side}_entries"
        method = getattr(book_obj, method_name, None)
        if callable(method):
            try:
                return list(method())
            except Exception:
                return []
        attr = getattr(book_obj, side, None)
        if attr is None:
            return []
        if callable(attr):
            try:
                return list(attr())
            except Exception:
                return []
        if isinstance(attr, dict):
            return list(attr.values())
        if isinstance(attr, (list, tuple)):
            return list(attr)
        try:
            return list(attr)
        except Exception:
            return []

    bids_raw = _iter_entries(book, "bid")
    asks_raw = _iter_entries(book, "ask")
    if not bids_raw:
        bids_raw = _iter_entries(book, "bids")
    if not asks_raw:
        asks_raw = _iter_entries(book, "asks")
    bids = [level for level in (_extract_depth_level(entry) for entry in bids_raw) if level is not None]
    asks = [level for level in (_extract_depth_level(entry) for entry in asks_raw) if level is not None]
    bids.sort(key=lambda row: row["price"], reverse=True)
    asks.sort(key=lambda row: row["price"])
    if max_levels > 0:
        bids = bids[:max_levels]
        asks = asks[:max_levels]
    out["bids"] = bids
    out["asks"] = asks
    if bids:
        out["best_bid"] = bids[0]["price"]
    if asks:
        out["best_ask"] = asks[0]["price"]
    for attr_name in ("snapshot_uid", "update_id", "last_update_id", "sequence", "seq_num"):
        raw = getattr(book, attr_name, None)
        if raw is None:
            continue
        try:
            out["market_sequence"] = int(raw)
            break
        except Exception:
            continue
    return out


def _install_bitget_ws_stability_patch():
    """
    Improve Bitget websocket resilience for both public and private streams by:
    1) enforcing message timeout > heartbeat interval, and
    2) keeping interval ping loops alive across transient transport resets.
    """
    if os.getenv("HB_BITGET_WS_STABILITY_PATCH_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return
    if getattr(logging, "_hbot_bitget_ws_stability_patch_installed", False):
        return

    try:
        from hummingbot.connector.derivative.bitget_perpetual import bitget_perpetual_constants as perp_constants
    except Exception:
        perp_constants = None
    try:
        from hummingbot.connector.exchange.bitget import bitget_constants as spot_constants
    except Exception:
        spot_constants = None

    target_timeout_s = max(15, int(float(os.getenv("HB_BITGET_WS_MESSAGE_TIMEOUT_S", "75"))))
    target_heartbeat_s = max(5, int(float(os.getenv("HB_BITGET_WS_HEARTBEAT_S", "15"))))
    max_consecutive_timeouts = max(1, int(float(os.getenv("HB_BITGET_WS_MAX_CONSEC_TIMEOUTS", "3"))))
    timeout_retry_sleep_s = max(0.0, float(os.getenv("HB_BITGET_WS_TIMEOUT_RETRY_SLEEP_S", "0.5")))
    if target_timeout_s <= target_heartbeat_s:
        target_timeout_s = target_heartbeat_s + 5

    for constants_module in (perp_constants, spot_constants):
        if constants_module is None:
            continue
        if hasattr(constants_module, "WS_HEARTBEAT_TIME_INTERVAL"):
            constants_module.WS_HEARTBEAT_TIME_INTERVAL = target_heartbeat_s
        if hasattr(constants_module, "SECONDS_TO_WAIT_TO_RECEIVE_MESSAGE"):
            constants_module.SECONDS_TO_WAIT_TO_RECEIVE_MESSAGE = max(target_timeout_s, target_heartbeat_s + 5)

    def _is_transient_ping_exc(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionResetError, BrokenPipeError)):
            return True
        exc_text = f"{type(exc).__name__}: {exc}"
        transient_tokens = (
            "ClientConnectionResetError",
            "ServerDisconnectedError",
            "ClientConnectorError",
            "ClientOSError",
            "Cannot write to closing transport",
        )
        return any(token in exc_text for token in transient_tokens)

    def _to_positive_decimal(value: Any) -> Optional[Decimal]:
        try:
            if value is None:
                return None
            dec = Decimal(str(value))
            if dec.is_nan() or dec <= Decimal("0"):
                return None
            return dec
        except Exception:
            return None

    def _mid_from_connector_snapshot(connector_obj: Any, pair: str) -> Optional[Decimal]:
        get_mid_fn = getattr(connector_obj, "get_mid_price", None)
        if callable(get_mid_fn):
            try:
                mid = _to_positive_decimal(get_mid_fn(pair))
                if mid is not None:
                    return mid
            except TypeError:
                try:
                    mid = _to_positive_decimal(get_mid_fn())
                    if mid is not None:
                        return mid
                except Exception:
                    pass
            except Exception:
                pass
        get_price_by_type_fn = getattr(connector_obj, "get_price_by_type", None)
        if callable(get_price_by_type_fn):
            try:
                from hummingbot.core.data_type.common import PriceType as _PriceType
                mid = _to_positive_decimal(get_price_by_type_fn(pair, _PriceType.MidPrice))
                if mid is not None:
                    return mid
            except Exception:
                pass
        get_order_book_fn = getattr(connector_obj, "get_order_book", None)
        if callable(get_order_book_fn):
            try:
                book = get_order_book_fn(pair)
                best_bid = getattr(book, "best_bid", None)
                best_ask = getattr(book, "best_ask", None)
                bid = _to_positive_decimal(getattr(best_bid, "price", best_bid))
                ask = _to_positive_decimal(getattr(best_ask, "price", best_ask))
                if bid is not None and ask is not None:
                    return (bid + ask) / Decimal("2")
            except Exception:
                pass
        return None

    def _extract_depth_level(entry: Any) -> Optional[Dict[str, float]]:
        price_raw = None
        size_raw = None
        if isinstance(entry, dict):
            price_raw = (
                entry.get("price")
                if "price" in entry
                else entry.get("p", entry.get("0"))
            )
            size_raw = (
                entry.get("size")
                if "size" in entry
                else entry.get("amount", entry.get("quantity", entry.get("q", entry.get("1"))))
            )
        elif isinstance(entry, (tuple, list)):
            if len(entry) >= 2:
                price_raw = entry[0]
                size_raw = entry[1]
        else:
            price_raw = getattr(entry, "price", None)
            size_raw = getattr(entry, "size", None)
            if size_raw is None:
                size_raw = getattr(entry, "amount", None)
            if size_raw is None:
                size_raw = getattr(entry, "quantity", None)
        price = _to_positive_decimal(price_raw)
        size = _to_positive_decimal(size_raw)
        if price is None or size is None:
            return None
        return {"price": float(price), "size": float(size)}

    def _extract_order_book_depth_snapshot(
        connector_obj: Any,
        pair: str,
        max_levels: int,
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "bids": [],
            "asks": [],
            "best_bid": None,
            "best_ask": None,
            "market_sequence": None,
        }
        get_order_book_fn = getattr(connector_obj, "get_order_book", None)
        if not callable(get_order_book_fn):
            return out
        try:
            book = get_order_book_fn(pair)
        except Exception:
            return out

        def _iter_entries(book_obj: Any, side: str) -> List[Any]:
            method_name = f"{side}_entries"
            method = getattr(book_obj, method_name, None)
            if callable(method):
                try:
                    return list(method())
                except Exception:
                    return []
            attr = getattr(book_obj, side, None)
            if attr is None:
                return []
            if callable(attr):
                try:
                    return list(attr())
                except Exception:
                    return []
            if isinstance(attr, dict):
                return list(attr.values())
            if isinstance(attr, (list, tuple)):
                return list(attr)
            try:
                return list(attr)
            except Exception:
                return []

        bids_raw = _iter_entries(book, "bid")
        asks_raw = _iter_entries(book, "ask")
        if not bids_raw:
            bids_raw = _iter_entries(book, "bids")
        if not asks_raw:
            asks_raw = _iter_entries(book, "asks")
        bids = [level for level in (_extract_depth_level(entry) for entry in bids_raw) if level is not None]
        asks = [level for level in (_extract_depth_level(entry) for entry in asks_raw) if level is not None]
        bids.sort(key=lambda row: row["price"], reverse=True)
        asks.sort(key=lambda row: row["price"])
        if max_levels > 0:
            bids = bids[:max_levels]
            asks = asks[:max_levels]
        out["bids"] = bids
        out["asks"] = asks
        if bids:
            out["best_bid"] = bids[0]["price"]
        if asks:
            out["best_ask"] = asks[0]["price"]

        for attr_name in ("snapshot_uid", "update_id", "last_update_id", "sequence", "seq_num"):
            raw = getattr(book, attr_name, None)
            if raw is None:
                continue
            try:
                out["market_sequence"] = int(raw)
                break
            except Exception:
                continue
        return out

    def _patch_safe_last_traded_prices(connector_cls: Any) -> bool:
        if connector_cls is None:
            return False
        if getattr(connector_cls, "_hb_safe_last_traded_prices_patch_installed", False):
            return True
        original_get_last_traded_prices = getattr(connector_cls, "get_last_traded_prices", None)
        if not callable(original_get_last_traded_prices):
            return False

        async def _safe_get_last_traded_prices(self, trading_pairs):
            try:
                return await original_get_last_traded_prices(self, trading_pairs)
            except Exception:
                fallback_prices: Dict[str, float] = {}
                for pair in list(trading_pairs or []):
                    mid = _mid_from_connector_snapshot(self, str(pair))
                    if mid is not None:
                        fallback_prices[str(pair)] = float(mid)
                if fallback_prices:
                    now_ts = time.time()
                    last_log_ts = float(getattr(self, "_hb_last_trade_price_fallback_log_ts", 0.0) or 0.0)
                    min_log_interval_s = max(10.0, float(os.getenv("HB_BITGET_LAST_TRADE_FALLBACK_LOG_INTERVAL_S", "120")))
                    if now_ts - last_log_ts >= min_log_interval_s:
                        setattr(self, "_hb_last_trade_price_fallback_log_ts", now_ts)
                        logger_obj = getattr(self, "logger", None)
                        if callable(logger_obj):
                            logger_obj().warning(
                                "Transient last-traded-price fetch failure; using mid/TOB fallback "
                                "(pairs=%s, throttled to >= %ss).",
                                ",".join(sorted(fallback_prices.keys())),
                                int(min_log_interval_s),
                            )
                    return fallback_prices
                raise

        connector_cls.get_last_traded_prices = _safe_get_last_traded_prices
        connector_cls._hb_safe_last_traded_prices_patch_installed = True
        return True

    def _patch_market_data_provider_last_trade_fallback() -> bool:
        try:
            from hummingbot.data_feed.market_data_provider import MarketDataProvider
        except Exception:
            return False
        if getattr(MarketDataProvider, "_hb_last_trade_fallback_patch_installed", False):
            return True

        async def _safe_get_last_traded_price_no_spam(self, connector, trading_pair):
            try:
                last_traded = await connector._get_last_traded_price(trading_pair=trading_pair)
                dec = _to_positive_decimal(last_traded)
                return dec if dec is not None else Decimal("0")
            except Exception:
                return Decimal("0")

        async def _safe_get_last_traded_prices_with_fallback(self, connector, trading_pairs, timeout=5):
            pairs = [str(p) for p in list(trading_pairs or [])]
            try:
                tasks = [_safe_get_last_traded_price_no_spam(self, connector, pair) for pair in pairs]
                prices = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
                resolved: Dict[str, Decimal] = {}
                for pair, price in zip(pairs, prices):
                    dec = _to_positive_decimal(price)
                    if dec is not None:
                        resolved[pair] = dec
                missing_pairs = [pair for pair in pairs if pair not in resolved]
                for pair in missing_pairs:
                    mid = _mid_from_connector_snapshot(connector, pair)
                    if mid is not None:
                        resolved[pair] = mid
                if missing_pairs:
                    now_ts = time.time()
                    last_log_ts = float(getattr(self, "_hb_last_trade_price_provider_fallback_log_ts", 0.0) or 0.0)
                    min_log_interval_s = max(
                        10.0,
                        float(os.getenv("HB_BITGET_LAST_TRADE_FALLBACK_LOG_INTERVAL_S", "120")),
                    )
                    if now_ts - last_log_ts >= min_log_interval_s:
                        setattr(self, "_hb_last_trade_price_provider_fallback_log_ts", now_ts)
                        logging.getLogger(__name__).warning(
                            "MarketDataProvider last-traded-price fallback used "
                            "(pairs=%s, missing=%s, throttled to >= %ss).",
                            ",".join(pairs),
                            ",".join(missing_pairs),
                            int(min_log_interval_s),
                        )
                return resolved
            except Exception:
                resolved: Dict[str, Decimal] = {}
                for pair in pairs:
                    mid = _mid_from_connector_snapshot(connector, pair)
                    if mid is not None:
                        resolved[pair] = mid
                return resolved

        MarketDataProvider._safe_get_last_traded_price = _safe_get_last_traded_price_no_spam
        MarketDataProvider._safe_get_last_traded_prices = _safe_get_last_traded_prices_with_fallback
        MarketDataProvider._hb_last_trade_fallback_patch_installed = True
        return True

    async def _resilient_interval_ping(self, websocket_assistant):
        while True:
            try:
                await self._send_ping(websocket_assistant)
            except asyncio.CancelledError:
                self.logger().info("Interval PING task cancelled")
                raise
            except Exception as exc:
                if _is_transient_ping_exc(exc):
                    now_ts = time.time()
                    last_ts = float(getattr(self, "_hb_last_ping_transient_log_ts", 0.0) or 0.0)
                    min_log_interval_s = max(10.0, float(os.getenv("HB_BITGET_PING_ERROR_LOG_INTERVAL_S", "120")))
                    if (now_ts - last_ts) >= min_log_interval_s:
                        setattr(self, "_hb_last_ping_transient_log_ts", now_ts)
                        self.logger().warning(
                            "Transient websocket ping send failure; keeping ping task alive "
                            "(throttled to >= %ss).",
                            int(min_log_interval_s),
                        )
                else:
                    self.logger().exception("Error sending interval PING")
            await asyncio.sleep(target_heartbeat_s)

    def _log_timeout_retry(self, stream_label: str, consecutive: int) -> None:
        now_ts = time.time()
        last_ts = float(getattr(self, "_hb_last_timeout_retry_log_ts", 0.0) or 0.0)
        min_log_interval_s = max(10.0, float(os.getenv("HB_BITGET_TIMEOUT_RETRY_LOG_INTERVAL_S", "120")))
        if (now_ts - last_ts) >= min_log_interval_s:
            setattr(self, "_hb_last_timeout_retry_log_ts", now_ts)
            self.logger().warning(
                "Transient websocket read timeout on %s stream; attempting in-place keepalive retry "
                "(timeout_retry=%d/%d, throttled to >= %ss).",
                stream_label,
                consecutive,
                max_consecutive_timeouts,
                int(min_log_interval_s),
            )

    async def _resilient_orderbook_process_messages(self, websocket_assistant):
        consecutive_timeouts = 0
        while True:
            try:
                async for ws_response in websocket_assistant.iter_messages():
                    consecutive_timeouts = 0
                    data: Dict[str, Any] = ws_response.data
                    if data is None:
                        continue
                    channel: str = self._channel_originating_message(event_message=data)
                    valid_channels = self._get_messages_queue_keys()
                    if channel in valid_channels:
                        self._message_queue[channel].put_nowait(data)
                    else:
                        await self._process_message_for_unknown_channel(
                            event_message=data, websocket_assistant=websocket_assistant
                        )
                return
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                consecutive_timeouts += 1
                if consecutive_timeouts <= max_consecutive_timeouts:
                    _log_timeout_retry(self, "order_book", consecutive_timeouts)
                    try:
                        await self._send_ping(websocket_assistant)
                    except Exception:
                        pass
                    if timeout_retry_sleep_s > 0:
                        await asyncio.sleep(timeout_retry_sleep_s)
                    continue
                raise

    async def _resilient_user_stream_process_messages(self, websocket_assistant, queue):
        consecutive_timeouts = 0
        while True:
            try:
                async for ws_response in websocket_assistant.iter_messages():
                    consecutive_timeouts = 0
                    data = ws_response.data
                    await self._process_event_message(event_message=data, queue=queue)
                return
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                consecutive_timeouts += 1
                if consecutive_timeouts <= max_consecutive_timeouts:
                    _log_timeout_retry(self, "user", consecutive_timeouts)
                    try:
                        await self._send_ping(websocket_assistant)
                    except Exception:
                        pass
                    if timeout_retry_sleep_s > 0:
                        await asyncio.sleep(timeout_retry_sleep_s)
                    continue
                raise

    patched_classes = []
    patched_last_trade_classes = []
    patched_provider_fallback = False
    try:
        from hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_api_order_book_data_source import (
            BitgetPerpetualAPIOrderBookDataSource,
        )
        BitgetPerpetualAPIOrderBookDataSource.send_interval_ping = _resilient_interval_ping
        BitgetPerpetualAPIOrderBookDataSource._process_websocket_messages = _resilient_orderbook_process_messages
        patched_classes.append("BitgetPerpetualAPIOrderBookDataSource")
    except Exception:
        pass
    try:
        from hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_api_user_stream_data_source import (
            BitgetPerpetualUserStreamDataSource,
        )
        BitgetPerpetualUserStreamDataSource.send_interval_ping = _resilient_interval_ping
        BitgetPerpetualUserStreamDataSource._process_websocket_messages = _resilient_user_stream_process_messages
        patched_classes.append("BitgetPerpetualUserStreamDataSource")
    except Exception:
        pass
    try:
        from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
        BitgetAPIOrderBookDataSource.send_interval_ping = _resilient_interval_ping
        BitgetAPIOrderBookDataSource._process_websocket_messages = _resilient_orderbook_process_messages
        patched_classes.append("BitgetAPIOrderBookDataSource")
    except Exception:
        pass
    try:
        from hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_derivative import (
            BitgetPerpetualDerivative,
        )
        if _patch_safe_last_traded_prices(BitgetPerpetualDerivative):
            patched_last_trade_classes.append("BitgetPerpetualDerivative")
    except Exception:
        pass
    try:
        from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange
        if _patch_safe_last_traded_prices(BitgetExchange):
            patched_last_trade_classes.append("BitgetExchange")
    except Exception:
        pass
    patched_provider_fallback = _patch_market_data_provider_last_trade_fallback()

    logging.getLogger(__name__).warning(
        "Installed Bitget WS stability patch (heartbeat=%ss, message_timeout=%ss, "
        "max_consecutive_timeouts=%s, classes=%s, safe_last_trade_classes=%s, provider_last_trade_fallback=%s).",
        target_heartbeat_s,
        target_timeout_s,
        max_consecutive_timeouts,
        ",".join(patched_classes) if patched_classes else "none",
        ",".join(patched_last_trade_classes) if patched_last_trade_classes else "none",
        str(bool(patched_provider_fallback)).lower(),
    )
    logging._hbot_bitget_ws_stability_patch_installed = True


def _install_transient_rate_oracle_guard():
    """
    Binance rate-source calls can fail transiently under transport resets.
    Downgrade known transient failures to throttled WARNING messages.
    """
    if os.getenv("HB_SUPPRESS_TRANSIENT_RATE_ORACLE_ERRORS", "true").lower() not in {"1", "true", "yes"}:
        return
    if getattr(logging, "_hbot_transient_rate_oracle_guard_installed", False):
        return

    target_logger_name = "hummingbot.core.rate_oracle.sources.rate_source_base"
    target_message = "Unexpected error while retrieving rates from Binance. Check the log file for more info."
    min_emit_interval_s = max(1.0, float(os.getenv("HB_TRANSIENT_RATE_ORACLE_LOG_INTERVAL_S", "180")))
    transient_tokens = (
        "TimeoutError",
        "ClientConnectionResetError",
        "ConnectionResetError",
        "ServerDisconnectedError",
        "ClientConnectorError",
        "ClientOSError",
        "Cannot write to closing transport",
    )
    last_emit_ts = 0.0

    class _TransientRateOracleFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            nonlocal last_emit_ts
            if record.name != target_logger_name:
                return True
            if record.getMessage() != target_message:
                return True
            exc = record.exc_info[1] if record.exc_info else None
            if exc is None:
                return True
            exc_text = f"{type(exc).__name__}: {exc}"
            if not any(token in exc_text for token in transient_tokens):
                return True
            now = time.time()
            if now - last_emit_ts < min_emit_interval_s:
                return False
            last_emit_ts = now
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
            record.msg = (
                "Transient Binance rate-source request failure; reconnect/retry in progress "
                f"(throttled to >= {int(min_emit_interval_s)}s)."
            )
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            return True

    rate_filter = _TransientRateOracleFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(rate_filter)
    for handler in root_logger.handlers:
        handler.addFilter(rate_filter)
    logging.getLogger(target_logger_name).addFilter(rate_filter)
    logging._hbot_transient_rate_oracle_guard_installed = True


_install_trade_monitor_guard()
_install_connector_alias_guard()
_install_transient_bitget_ws_timeout_guard()
_install_bitget_ws_stability_patch()
_install_transient_rate_oracle_guard()
_BOT_MODE_WARNED_INVALID = False


def _runtime_bot_mode() -> str:
    """Return canonical runtime mode (`paper`|`live`) from BOT_MODE env."""
    global _BOT_MODE_WARNED_INVALID
    mode = str(os.getenv("BOT_MODE", "paper") or "").strip().lower()
    if mode in {"paper", "live"}:
        return mode
    if not _BOT_MODE_WARNED_INVALID:
        logging.getLogger(__name__).warning(
            "Invalid BOT_MODE=%s; defaulting to paper mode.",
            mode or "<empty>",
        )
        _BOT_MODE_WARNED_INVALID = True
    return "paper"


if _runtime_bot_mode() != "live":
    enable_framework_paper_compat_fallbacks()


class V2WithControllersConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    candles_config: List[CandlesConfig] = []
    markets: Dict[str, Set[str]] = {}
    max_global_drawdown_quote: Optional[float] = None
    max_controller_drawdown_quote: Optional[float] = None
    external_signal_risk_enabled: bool = os.getenv("EXT_SIGNAL_RISK_ENABLED", "false").lower() in {"1", "true", "yes"}
    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")
    redis_consumer_group: str = os.getenv("REDIS_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP)
    event_poll_ms: int = int(os.getenv("EVENT_POLL_MS", "1000"))
    bus_soft_pause_on_outage: bool = os.getenv("BUS_SOFT_PAUSE_ON_OUTAGE", "true").lower() in {"1", "true", "yes"}


class V2WithControllers(StrategyV2Base):
    """
    This script runs a generic strategy with cash out feature. Will also check if the controllers configs have been
    updated and apply the new settings.
    The cash out of the script can be set by the time_to_cash_out parameter in the config file. If set, the script will
    stop the controllers after the specified time has passed, and wait until the active executors finalize their
    execution.
    The controllers will also have a parameter to manually cash out. In that scenario, the main strategy will stop the
    specific controller and wait until the active executors finalize their execution. The rest of the executors will
    wait until the main strategy stops them.
    """
    performance_report_interval: int = 1

    def __init__(self, connectors: Dict[str, ConnectorBase], config: V2WithControllersConfig):
        super().__init__(connectors, config)
        self.config = config
        self.max_pnl_by_controller = {}
        self.max_global_pnl = Decimal("0")
        self.drawdown_exited_controllers = []
        self.closed_executors_buffer: int = 30
        self._last_performance_report_timestamp = 0
        self._bus_ping_tick_counter: int = 0
        self._bus_client = None
        self._bus_publisher = None
        self._bus_consumer = None
        self._last_bus_ok_ts = 0.0
        # Depth snapshots can carry sparse/repeated exchange-side sequence IDs.
        # Keep a local monotonic sequence for downstream stream-integrity checks.
        self._depth_market_sequence_by_key: Dict[str, int] = {}
        self._preflight_checked = False
        self._preflight_failed = False
        self._paper_adapter_installed: Set[str] = set()
        self._paper_adapter_pending_logged: Set[str] = set()
        self._paper_desk_v2 = None  # PaperDesk v2 -- created on first paper adapter install
        self._heartbeat_write_interval_s: float = float(os.getenv("HB_HEARTBEAT_INTERVAL_S", "5"))
        self._last_heartbeat_write_ts: float = 0.0
        self._heartbeat_path: Path = Path(
            os.getenv("HB_HEARTBEAT_PATH", "/home/hummingbot/logs/heartbeat/strategy_heartbeat.json")
        )
        self._open_orders_write_interval_s: float = float(os.getenv("HB_OPEN_ORDERS_SNAPSHOT_INTERVAL_S", "5"))
        self._last_open_orders_write_ts: float = 0.0
        self._open_orders_snapshot_path: Path = Path(
            os.getenv("HB_OPEN_ORDERS_SNAPSHOT_PATH", "/home/hummingbot/logs/recovery/open_orders_latest.json")
        )
        self._artifact_write_failures: Dict[str, int] = {}
        self._config_reload_retry_interval_s: float = float(os.getenv("HB_CONFIG_RELOAD_RETRY_S", "30"))
        self._config_reload_retry_after_ts: float = 0.0
        self._config_reload_error_count: int = 0
        self._config_reload_last_error: str = ""
        self._config_reload_last_error_ts: float = 0.0
        self._config_reload_degraded: bool = False
        self._config_reload_last_success_ts: float = time.time()
        self._config_reload_validation_error_types = tuple(
            cls for cls in (PydanticValidationError, PydanticCoreValidationError) if cls is not None
        )
        self._controller_module_mtime_by_name: Dict[str, float] = {}
        self._hard_stop_kill_switch_last_reason_by_controller: Dict[str, str] = {}
        self._hard_stop_kill_switch_last_ts_by_controller: Dict[str, float] = {}
        self._hard_stop_kill_switch_latched_by_controller: Dict[str, bool] = {}
        self._hard_stop_kill_switch_republish_s: float = float(
            os.getenv("HB_HARD_STOP_KILL_SWITCH_REPUBLISH_S", "300")
        )
        self._hard_stop_clear_candidate_since_by_controller: Dict[str, float] = {}
        self._hard_stop_resume_last_ts_by_controller: Dict[str, float] = {}
        self._hard_stop_clear_cooldown_s: float = float(
            os.getenv("HB_HARD_STOP_CLEAR_COOLDOWN_S", "30")
        )
        self._controller_actions_buffer: List[Any] = []
        self._action_trace_enabled: bool = os.getenv("HB_ACTION_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
        self._action_trace_cooldown_s: float = max(1.0, float(os.getenv("HB_ACTION_TRACE_COOLDOWN_S", "10")))
        self._action_trace_last_ts: float = 0.0
        self._executor_dispatch_trace_enabled: bool = (
            os.getenv("HB_EXECUTOR_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
        )
        self._executor_dispatch_trace_cooldown_s: float = max(
            1.0, float(os.getenv("HB_EXECUTOR_TRACE_COOLDOWN_S", "5"))
        )
        self._executor_dispatch_trace_last_ts: float = 0.0
        self._order_exec_trace_enabled: bool = (
            os.getenv("HB_ORDER_EXEC_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
        )
        self._order_exec_trace_all_levels: bool = (
            os.getenv("HB_ORDER_EXEC_TRACE_ALL_LEVELS", "false").lower() in {"1", "true", "yes"}
        )
        self._paper_engine_probe_enabled: bool = (
            os.getenv("HB_PAPER_ENGINE_PROBE_ENABLED", "true").lower() in {"1", "true", "yes"}
        )
        self._paper_engine_probe_cooldown_s: float = max(
            1.0, float(os.getenv("HB_PAPER_ENGINE_PROBE_COOLDOWN_S", "10"))
        )
        self._paper_engine_probe_last_ts: float = 0.0
        default_auto_resume = "true" if _runtime_bot_mode() == "paper" else "false"
        self._hard_stop_auto_resume_on_clear: bool = (
            os.getenv("HB_HARD_STOP_AUTO_RESUME_ON_CLEAR", default_auto_resume).strip().lower() in {"1", "true", "yes"}
        )
        self._startup_sync_report_path: Path = Path(
            os.getenv("HB_STARTUP_SYNC_REPORT_PATH", "/home/hummingbot/logs/recovery/startup_sync_latest.json")
        )
        self._install_executor_dispatch_trace()
        self._init_external_bus()
        self._install_internal_paper_adapters()

    @staticmethod
    def _action_level_id(action: Any) -> str:
        cfg = getattr(action, "executor_config", None)
        return str(getattr(cfg, "level_id", "") or "")

    @staticmethod
    def _executor_level_id(executor: Any) -> str:
        cfg = getattr(executor, "config", None)
        return str(getattr(cfg, "level_id", "") or "")

    @staticmethod
    def _executor_runtime_id(executor: Any) -> str:
        cfg = getattr(executor, "config", None)
        # Runtime executors expose different IDs depending on stage/type; use first non-empty.
        return str(
            getattr(executor, "executor_id", "")
            or getattr(executor, "id", "")
            or getattr(cfg, "id", "")
            or ""
        )

    def _is_position_rebalance_create(self, action: Any) -> bool:
        return isinstance(action, CreateExecutorAction) and self._action_level_id(action) == "position_rebalance"

    def _log_executor_dispatch_trace(
        self,
        *,
        stage: str,
        actions: List[Any],
        before_count: int,
        after_count: int,
        new_executor_ids: List[str],
        force: bool = False,
    ) -> None:
        if not self._executor_dispatch_trace_enabled:
            return
        now = time.time()
        if not force and (now - self._executor_dispatch_trace_last_ts) < self._executor_dispatch_trace_cooldown_s:
            return
        self._executor_dispatch_trace_last_ts = now
        create_actions = [a for a in actions if isinstance(a, CreateExecutorAction)]
        stop_actions = [a for a in actions if isinstance(a, StopExecutorAction)]
        create_levels = [self._action_level_id(a) for a in create_actions]
        self.logger().warning(
            "EXECUTOR_TRACE stage=%s total=%d create=%d stop=%d before=%d after=%d "
            "create_levels=%s new_executor_ids=%s",
            stage,
            len(actions),
            len(create_actions),
            len(stop_actions),
            before_count,
            after_count,
            ",".join(create_levels[:8]),
            ",".join(new_executor_ids[:8]),
        )

    def _install_executor_dispatch_trace(self) -> None:
        if not self._executor_dispatch_trace_enabled:
            return
        orchestrator = getattr(self, "executor_orchestrator", None)
        if orchestrator is None or getattr(orchestrator, "_hb_executor_trace_installed", False):
            return
        original_execute_actions = getattr(orchestrator, "execute_actions", None)
        if not callable(original_execute_actions):
            return
        original_execute_action = getattr(orchestrator, "execute_action", None)
        original_create_executor = getattr(orchestrator, "create_executor", None)

        def _runtime_executors() -> List[Any]:
            active_map = getattr(orchestrator, "active_executors", {}) or {}
            flattened: List[Any] = []
            for executor_list in active_map.values():
                if isinstance(executor_list, list):
                    flattened.extend(executor_list)
            return flattened

        def _wrapped_execute_actions(actions):
            action_list = list(actions or [])
            rebalance_present = any(self._is_position_rebalance_create(a) for a in action_list)
            before_executors = _runtime_executors()
            before_ids = {self._executor_runtime_id(ex) for ex in before_executors if self._executor_runtime_id(ex)}
            before_rebalance = [ex for ex in before_executors if self._executor_level_id(ex) == "position_rebalance"]
            self._log_executor_dispatch_trace(
                stage="dispatch_before",
                actions=action_list,
                before_count=len(before_executors),
                after_count=len(before_executors),
                new_executor_ids=[],
                force=rebalance_present,
            )
            result = original_execute_actions(action_list)
            after_executors = _runtime_executors()
            after_ids = {self._executor_runtime_id(ex) for ex in after_executors if self._executor_runtime_id(ex)}
            new_ids = sorted(ex_id for ex_id in (after_ids - before_ids) if ex_id)
            self._log_executor_dispatch_trace(
                stage="dispatch_after",
                actions=action_list,
                before_count=len(before_executors),
                after_count=len(after_executors),
                new_executor_ids=new_ids,
                force=True,
            )
            if rebalance_present and not new_ids:
                # Rebalance creates can be intentionally deduplicated if one is already active.
                rebalance_action_summaries: List[str] = []
                for action in action_list:
                    if not self._is_position_rebalance_create(action):
                        continue
                    cfg = getattr(action, "executor_config", None)
                    if cfg is None:
                        rebalance_action_summaries.append("missing_config")
                        continue
                    rebalance_action_summaries.append(
                        "side=%s amount=%s pair=%s entry=%s order_type=%s"
                        % (
                            str(getattr(cfg, "side", "")),
                            str(getattr(cfg, "amount", "")),
                            str(getattr(cfg, "trading_pair", "")),
                            str(getattr(cfg, "entry_price", "")),
                            str(getattr(getattr(cfg, "triple_barrier_config", None), "open_order_type", "")),
                        )
                    )
                msg = (
                    "EXECUTOR_TRACE stage=position_rebalance_create_not_added "
                    "reason=no_new_runtime_executor_after_dispatch "
                    "active_before=%d active_after=%d existing_rebalance=%d rebalance_action=%s"
                )
                args = (
                    len(before_executors),
                    len(after_executors),
                    len(before_rebalance),
                    " | ".join(rebalance_action_summaries[:3]),
                )
                if len(before_rebalance) > 0:
                    self.logger().warning(msg, *args)
                else:
                    self.logger().error(msg, *args)
            return result

        def _wrapped_execute_action(action: Any):
            level_id = self._action_level_id(action)
            is_create = isinstance(action, CreateExecutorAction)
            if level_id == "position_rebalance":
                self.logger().warning(
                    "EXECUTOR_TRACE stage=execute_action_enter action_cls=%s is_create=%s controller_id=%s",
                    type(action).__name__,
                    str(is_create),
                    str(getattr(action, "controller_id", "")),
                )
            try:
                return original_execute_action(action) if callable(original_execute_action) else None
            except Exception:
                if level_id == "position_rebalance":
                    self.logger().error(
                        "EXECUTOR_TRACE stage=execute_action_exception controller_id=%s",
                        str(getattr(action, "controller_id", "")),
                        exc_info=True,
                    )
                raise

        def _wrapped_create_executor(action: Any):
            level_id = self._action_level_id(action)
            cfg = getattr(action, "executor_config", None)
            should_trace_level = level_id == "position_rebalance" or self._order_exec_trace_all_levels
            if should_trace_level:
                self.logger().warning(
                    "EXECUTOR_TRACE stage=create_executor_enter level_id=%s cfg_type=%s cfg_class=%s side=%s amount=%s entry_price=%s open_order_type=%s",
                    level_id,
                    str(getattr(cfg, "type", "")),
                    type(cfg).__name__ if cfg is not None else "None",
                    str(getattr(cfg, "side", "")),
                    str(getattr(cfg, "amount", "")),
                    str(getattr(cfg, "entry_price", "")),
                    str(getattr(getattr(cfg, "triple_barrier_config", None), "open_order_type", "")),
                )
            try:
                result = original_create_executor(action) if callable(original_create_executor) else None
            except Exception:
                if should_trace_level:
                    self.logger().error("EXECUTOR_TRACE stage=create_executor_exception", exc_info=True)
                raise
            if should_trace_level:
                active_now = len(_runtime_executors())
                self.logger().warning(
                    "EXECUTOR_TRACE stage=create_executor_done level_id=%s active_now=%d",
                    level_id,
                    active_now,
                )
            return result

        orchestrator.execute_actions = _wrapped_execute_actions
        if callable(original_execute_action):
            orchestrator.execute_action = _wrapped_execute_action
        if callable(original_create_executor):
            orchestrator.create_executor = _wrapped_create_executor

        if self._order_exec_trace_enabled:
            try:
                from hummingbot.strategy_v2.executors.order_executor.order_executor import OrderExecutor
                def _should_trace_level(level_id: str) -> bool:
                    if not level_id:
                        return False
                    return level_id == "position_rebalance" or self._order_exec_trace_all_levels

                if not getattr(OrderExecutor, "_hb_order_exec_trace_installed", False):
                    original_place_open_order = getattr(OrderExecutor, "place_open_order", None)
                    original_place_order = getattr(OrderExecutor, "place_order", None)

                    if callable(original_place_open_order):
                        def _wrapped_place_open_order(executor_self: Any):
                            cfg = getattr(executor_self, "config", None)
                            level_id = str(getattr(cfg, "level_id", "") or "")
                            should_trace = _should_trace_level(level_id)
                            if should_trace:
                                executor_self.logger().warning(
                                    "ORDER_EXEC_TRACE stage=place_open_order_enter level_id=%s side=%s amount=%s strategy=%s",
                                    level_id,
                                    str(getattr(cfg, "side", "")),
                                    str(getattr(cfg, "amount", "")),
                                    str(getattr(cfg, "execution_strategy", "")),
                                )
                            try:
                                return original_place_open_order(executor_self)
                            except Exception:
                                if should_trace:
                                    executor_self.logger().error(
                                        "ORDER_EXEC_TRACE stage=place_open_order_exception level_id=%s",
                                        level_id,
                                        exc_info=True,
                                    )
                                raise
                            finally:
                                if should_trace:
                                    tracked_order = getattr(executor_self, "_order", None)
                                    order_id = str(getattr(tracked_order, "order_id", "") or "")
                                    executor_self.logger().warning(
                                        "ORDER_EXEC_TRACE stage=place_open_order_done level_id=%s order_id=%s",
                                        level_id,
                                        order_id,
                                    )

                        OrderExecutor.place_open_order = _wrapped_place_open_order

                    if callable(original_place_order):
                        def _wrapped_place_order(
                            executor_self: Any,
                            connector_name: str,
                            trading_pair: str,
                            order_type: Any,
                            side: Any,
                            amount: Decimal,
                            position_action: Any = None,
                            price: Decimal = Decimal("NaN"),
                        ):
                            cfg = getattr(executor_self, "config", None)
                            level_id = str(getattr(cfg, "level_id", "") or "")
                            should_trace = _should_trace_level(level_id)
                            strategy_obj = getattr(executor_self, "_strategy", None)
                            desk_obj = getattr(strategy_obj, "_paper_desk_v2", None)
                            desk_events_before = -1
                            if desk_obj is not None and hasattr(desk_obj, "event_log"):
                                try:
                                    desk_events_before = len(desk_obj.event_log())
                                except Exception:
                                    desk_events_before = -1
                            if should_trace:
                                buy_callable = getattr(strategy_obj, "buy", None)
                                buy_func = getattr(buy_callable, "__func__", buy_callable)
                                buy_name = str(getattr(buy_func, "__name__", type(buy_callable).__name__))
                                buy_module = str(getattr(buy_func, "__module__", ""))
                                bridges = getattr(strategy_obj, "_paper_desk_v2_bridges", {}) or {}
                                bridge_keys = ",".join(sorted(bridges.keys()))
                                bridge_found = connector_name in bridges
                                executor_self.logger().warning(
                                    "ORDER_EXEC_TRACE stage=place_order_enter level_id=%s connector=%s pair=%s side=%s "
                                    "amount=%s order_type=%s price=%s position_action=%s strategy_buy=%s strategy_buy_module=%s bridge_found=%s "
                                    "bridge_keys=%s",
                                    level_id,
                                    connector_name,
                                    trading_pair,
                                    str(side),
                                    str(amount),
                                    str(order_type),
                                    str(price),
                                    str(position_action),
                                    buy_name,
                                    buy_module,
                                    str(bridge_found),
                                    bridge_keys,
                                )
                            try:
                                order_id = original_place_order(
                                    executor_self,
                                    connector_name,
                                    trading_pair,
                                    order_type,
                                    side,
                                    amount,
                                    position_action=position_action,
                                    price=price,
                                )
                            except Exception:
                                if should_trace:
                                    executor_self.logger().error(
                                        "ORDER_EXEC_TRACE stage=place_order_exception level_id=%s",
                                        level_id,
                                        exc_info=True,
                                    )
                                raise
                            if should_trace:
                                desk_events_after = -1
                                desk_last_event = ""
                                desk_last_reason = ""
                                desk_last_order_id = ""
                                desk_engine_open = -1
                                desk_engine_market_open = -1
                                desk_engine_inflight = -1
                                desk_best_bid = ""
                                desk_best_ask = ""
                                desk_best_bid_size = ""
                                desk_best_ask_size = ""
                                probe_order_status = ""
                                probe_order_remaining = ""
                                probe_order_price = ""
                                probe_order_type = ""
                                probe_order_id = ""
                                probe_fill_count = ""
                                probe_last_fill_ns = ""
                                probe_updated_ns = ""
                                probe_eval_qty = ""
                                probe_eval_price = ""
                                if desk_obj is not None:
                                    try:
                                        events = desk_obj.event_log()
                                        desk_events_after = len(events)
                                        if events:
                                            desk_last_event = type(events[-1]).__name__
                                            desk_last_reason = str(getattr(events[-1], "reason", "") or "")
                                            desk_last_order_id = str(getattr(events[-1], "order_id", "") or "")
                                    except Exception:
                                        pass
                                    try:
                                        bridges = getattr(strategy_obj, "_paper_desk_v2_bridges", {}) or {}
                                        bridge = bridges.get(connector_name) or {}
                                        instrument_id = bridge.get("instrument_id")
                                        engine = getattr(desk_obj, "_engines", {}).get(getattr(instrument_id, "key", ""))
                                        if engine is not None:
                                            open_orders = engine.open_orders() if hasattr(engine, "open_orders") else []
                                            desk_engine_open = len(open_orders)
                                            desk_engine_market_open = len(
                                                [
                                                    o for o in open_orders
                                                    if str(getattr(getattr(o, "order_type", None), "value", "")) == "market"
                                                ]
                                            )
                                            desk_engine_inflight = len(getattr(engine, "_inflight", []) or [])
                                            book = getattr(engine, "_book", None)
                                            desk_best_bid = str(getattr(getattr(book, "best_bid", None), "price", ""))
                                            desk_best_ask = str(getattr(getattr(book, "best_ask", None), "price", ""))
                                            desk_best_bid_size = str(getattr(getattr(book, "best_bid", None), "size", ""))
                                            desk_best_ask_size = str(getattr(getattr(book, "best_ask", None), "size", ""))
                                            probe = engine.get_order(str(order_id or "")) if hasattr(engine, "get_order") else None
                                            if probe is None and open_orders:
                                                probe = open_orders[0]
                                            if probe is not None:
                                                probe_order_id = str(getattr(probe, "order_id", ""))
                                                probe_order_status = str(getattr(getattr(probe, "status", None), "value", ""))
                                                probe_order_remaining = str(getattr(probe, "remaining_quantity", ""))
                                                probe_order_price = str(getattr(probe, "price", ""))
                                                probe_order_type = str(getattr(getattr(probe, "order_type", None), "value", ""))
                                                probe_fill_count = str(getattr(probe, "fill_count", ""))
                                                probe_updated_ns = str(getattr(probe, "updated_at_ns", ""))
                                                probe_last_fill_ns = str(
                                                    (getattr(engine, "_last_fill_ns", {}) or {}).get(probe_order_id, "")
                                                )
                                                try:
                                                    fill_model = getattr(engine, "_fill_model", None)
                                                    book = getattr(engine, "_book", None)
                                                    if fill_model is not None and book is not None:
                                                        decision = fill_model.evaluate(
                                                            probe,
                                                            book,
                                                            int(time.time() * 1_000_000_000),
                                                        )
                                                        probe_eval_qty = str(getattr(decision, "fill_quantity", ""))
                                                        probe_eval_price = str(getattr(decision, "fill_price", ""))
                                                except Exception:
                                                    pass
                                    except Exception:
                                        pass
                                executor_self.logger().warning(
                                    "ORDER_EXEC_TRACE stage=place_order_done level_id=%s order_id=%s "
                                    "desk_events_before=%d desk_events_after=%d desk_last_event=%s desk_last_reason=%s "
                                    "desk_last_order_id=%s "
                                    "engine_open=%d engine_market_open=%d engine_inflight=%d best_bid=%s best_ask=%s "
                                    "best_bid_size=%s best_ask_size=%s probe_order_id=%s probe_status=%s probe_remaining=%s probe_price=%s probe_type=%s "
                                    "probe_fill_count=%s probe_last_fill_ns=%s probe_updated_ns=%s probe_eval_qty=%s probe_eval_price=%s",
                                    level_id,
                                    str(order_id or ""),
                                    desk_events_before,
                                    desk_events_after,
                                    desk_last_event,
                                    desk_last_reason,
                                    desk_last_order_id,
                                    desk_engine_open,
                                    desk_engine_market_open,
                                    desk_engine_inflight,
                                    desk_best_bid,
                                    desk_best_ask,
                                    desk_best_bid_size,
                                    desk_best_ask_size,
                                    probe_order_id,
                                    probe_order_status,
                                    probe_order_remaining,
                                    probe_order_price,
                                    probe_order_type,
                                    probe_fill_count,
                                    probe_last_fill_ns,
                                    probe_updated_ns,
                                    probe_eval_qty,
                                    probe_eval_price,
                                )
                            return order_id

                        OrderExecutor.place_order = _wrapped_place_order

                    OrderExecutor._hb_order_exec_trace_installed = True

                try:
                    from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor

                    if not getattr(PositionExecutor, "_hb_position_exec_trace_installed", False):
                        original_pos_place_open_order = getattr(PositionExecutor, "place_open_order", None)
                        original_pos_place_order = getattr(PositionExecutor, "place_order", None)

                        if callable(original_pos_place_open_order):
                            def _wrapped_pos_place_open_order(executor_self: Any, *args: Any, **kwargs: Any):
                                cfg = getattr(executor_self, "config", None)
                                level_id = str(getattr(cfg, "level_id", "") or "")
                                should_trace = _should_trace_level(level_id)
                                if should_trace:
                                    executor_self.logger().warning(
                                        "POS_EXEC_TRACE stage=place_open_order_enter level_id=%s side=%s amount=%s entry_price=%s activation_bounds=%s",
                                        level_id,
                                        str(getattr(cfg, "side", "")),
                                        str(getattr(cfg, "amount", "")),
                                        str(getattr(cfg, "entry_price", "")),
                                        str(getattr(cfg, "activation_bounds", "")),
                                    )
                                try:
                                    return original_pos_place_open_order(executor_self, *args, **kwargs)
                                except Exception:
                                    if should_trace:
                                        executor_self.logger().error(
                                            "POS_EXEC_TRACE stage=place_open_order_exception level_id=%s",
                                            level_id,
                                            exc_info=True,
                                        )
                                    raise
                                finally:
                                    if should_trace:
                                        tracked_order = getattr(executor_self, "_open_order", None) or getattr(executor_self, "_order", None)
                                        order_id = str(getattr(tracked_order, "order_id", "") or "")
                                        executor_self.logger().warning(
                                            "POS_EXEC_TRACE stage=place_open_order_done level_id=%s order_id=%s",
                                            level_id,
                                            order_id,
                                        )

                            PositionExecutor.place_open_order = _wrapped_pos_place_open_order

                        if callable(original_pos_place_order):
                            def _wrapped_pos_place_order(executor_self: Any, *args: Any, **kwargs: Any):
                                cfg = getattr(executor_self, "config", None)
                                level_id = str(getattr(cfg, "level_id", "") or "")
                                should_trace = _should_trace_level(level_id)
                                if should_trace:
                                    executor_self.logger().warning(
                                        "POS_EXEC_TRACE stage=place_order_enter level_id=%s args=%s kwargs=%s",
                                        level_id,
                                        str(args),
                                        str(kwargs),
                                    )
                                try:
                                    order_id = original_pos_place_order(executor_self, *args, **kwargs)
                                except Exception:
                                    if should_trace:
                                        executor_self.logger().error(
                                            "POS_EXEC_TRACE stage=place_order_exception level_id=%s",
                                            level_id,
                                            exc_info=True,
                                        )
                                    raise
                                if should_trace:
                                    connector_name = str(kwargs.get("connector_name", "") or "")
                                    trading_pair = str(kwargs.get("trading_pair", "") or "")
                                    desk_engine_open = -1
                                    desk_engine_inflight = -1
                                    probe_order_id = ""
                                    probe_order_status = ""
                                    probe_order_remaining = ""
                                    probe_order_price = ""
                                    probe_fill_count = ""
                                    try:
                                        strategy_obj = getattr(executor_self, "_strategy", None)
                                        desk_obj = getattr(strategy_obj, "_paper_desk_v2", None)
                                        if desk_obj is not None and connector_name:
                                            bridges = getattr(strategy_obj, "_paper_desk_v2_bridges", {}) or {}
                                            bridge = bridges.get(connector_name) or {}
                                            instrument_id = bridge.get("instrument_id")
                                            engine = getattr(desk_obj, "_engines", {}).get(getattr(instrument_id, "key", ""))
                                            if engine is not None:
                                                open_orders = engine.open_orders() if hasattr(engine, "open_orders") else []
                                                desk_engine_open = len(open_orders)
                                                desk_engine_inflight = len(getattr(engine, "_inflight", []) or [])
                                                probe = engine.get_order(str(order_id or "")) if hasattr(engine, "get_order") else None
                                                if probe is not None:
                                                    probe_order_id = str(getattr(probe, "order_id", ""))
                                                    probe_order_status = str(getattr(getattr(probe, "status", None), "value", ""))
                                                    probe_order_remaining = str(getattr(probe, "remaining_quantity", ""))
                                                    probe_order_price = str(getattr(probe, "price", ""))
                                                    probe_fill_count = str(getattr(probe, "fill_count", ""))
                                    except Exception:
                                        pass
                                    executor_self.logger().warning(
                                        "POS_EXEC_TRACE stage=place_order_done level_id=%s order_id=%s connector=%s pair=%s "
                                        "engine_open=%d engine_inflight=%d probe_id=%s probe_status=%s probe_remaining=%s "
                                        "probe_price=%s probe_fill_count=%s",
                                        level_id,
                                        str(order_id or ""),
                                        connector_name,
                                        trading_pair,
                                        desk_engine_open,
                                        desk_engine_inflight,
                                        probe_order_id,
                                        probe_order_status,
                                        probe_order_remaining,
                                        probe_order_price,
                                        probe_fill_count,
                                    )
                                return order_id

                            PositionExecutor.place_order = _wrapped_pos_place_order

                        PositionExecutor._hb_position_exec_trace_installed = True
                except Exception:
                    self.logger().debug("PositionExecutor trace patch install failed", exc_info=True)
            except Exception:
                self.logger().debug("OrderExecutor trace patch install failed", exc_info=True)

        orchestrator._hb_executor_trace_installed = True
        self.logger().info("Executor dispatch trace installed.")

    def on_tick(self):
        self._write_watchdog_heartbeat(reason="tick_start")
        self._install_internal_paper_adapters()
        self._tick_paper_adapters()
        if not self._preflight_checked:
            self._run_preflight_once()
            if self._preflight_failed:
                self._write_watchdog_heartbeat(reason="preflight_failed")
                return
        super().on_tick()
        self._tick_paper_adapters()
        self._log_paper_engine_probe()
        self._publish_market_state_to_bus()
        self._consume_execution_intents()
        if not self._is_stop_triggered:
            self.check_manual_kill_switch()
            self.control_max_drawdown()
            self.send_performance_report()
            self._handle_bus_outage_soft_pause()
            self._check_hard_stop_kill_switch()
        self._write_open_orders_snapshot(reason="tick_end")
        self._write_watchdog_heartbeat(reason="tick_end")

    def _log_paper_engine_probe(self) -> None:
        if not self._paper_engine_probe_enabled or not self._order_exec_trace_all_levels:
            return
        now = time.time()
        if now - self._paper_engine_probe_last_ts < self._paper_engine_probe_cooldown_s:
            return
        self._paper_engine_probe_last_ts = now
        desk = getattr(self, "_paper_desk_v2", None)
        bridges = getattr(self, "_paper_desk_v2_bridges", {}) or {}
        if desk is None or not isinstance(bridges, dict) or not bridges:
            return
        engines = getattr(desk, "_engines", {}) or {}
        for connector_name, bridge in bridges.items():
            if not isinstance(bridge, dict):
                continue
            instrument_id = bridge.get("instrument_id")
            engine_key = getattr(instrument_id, "key", "")
            trading_pair = str(getattr(instrument_id, "trading_pair", "") or "")
            engine = engines.get(engine_key)
            if engine is None:
                continue
            open_orders = engine.open_orders() if hasattr(engine, "open_orders") else []
            inflight = list(getattr(engine, "_inflight", []) or [])
            open_ids = [str(getattr(o, "order_id", "")) for o in open_orders[:5]]
            inflight_ids = [str(getattr(getattr(t, "__getitem__", lambda *_: None)(2), "order_id", "")) for t in inflight[:5]]
            active_runtime_ids: List[str] = []
            try:
                controller_instance_name = ""
                target_connector = _canonical_name(str(connector_name))
                for controller_id, controller in (getattr(self, "controllers", {}) or {}).items():
                    cfg = getattr(controller, "config", None)
                    if cfg is None:
                        continue
                    cfg_connector = _canonical_name(str(getattr(cfg, "connector_name", "") or ""))
                    cfg_pair = str(getattr(cfg, "trading_pair", "") or "")
                    if cfg_connector == target_connector and (not trading_pair or cfg_pair == trading_pair):
                        controller_instance_name = str(getattr(cfg, "instance_name", "") or controller_id)
                        break
                if controller_instance_name and _paper_exchange_mode_for_instance(controller_instance_name) == "active":
                    runtime_store = getattr(self, "_paper_exchange_runtime_orders", {}) or {}
                    for bucket_name, bucket in runtime_store.items():
                        if _canonical_name(str(bucket_name or "")) != target_connector:
                            continue
                        if not isinstance(bucket, dict):
                            continue
                        for order in bucket.values():
                            if not bool(getattr(order, "is_open", False)):
                                continue
                            order_pair = str(getattr(order, "trading_pair", "") or "")
                            if trading_pair and order_pair and order_pair != trading_pair:
                                continue
                            active_runtime_ids.append(str(getattr(order, "order_id", "") or getattr(order, "client_order_id", "") or ""))
            except Exception:
                active_runtime_ids = []
            book = getattr(engine, "_book", None)
            best_bid = str(getattr(getattr(book, "best_bid", None), "price", ""))
            best_ask = str(getattr(getattr(book, "best_ask", None), "price", ""))
            order_samples: List[str] = []
            for order in open_orders[:4]:
                side = str(getattr(getattr(order, "side", None), "value", ""))
                price = str(getattr(order, "price", ""))
                remaining = str(getattr(order, "remaining_quantity", ""))
                fill_count = str(getattr(order, "fill_count", ""))
                touchable = ""
                try:
                    order_price = Decimal(price)
                    ask_dec = Decimal(best_ask) if best_ask else None
                    bid_dec = Decimal(best_bid) if best_bid else None
                    if side == "buy" and ask_dec is not None:
                        touchable = f" touch={str(order_price >= ask_dec).lower()}"
                    elif side == "sell" and bid_dec is not None:
                        touchable = f" touch={str(order_price <= bid_dec).lower()}"
                except Exception:
                    touchable = ""
                order_samples.append(
                    f"{str(getattr(order, 'order_id', ''))}:{side}@{price} rem={remaining} fills={fill_count}{touchable}"
                )
            self.logger().warning(
                "PAPER_ENGINE_PROBE connector=%s engine_key=%s open=%d inflight=%d active_runtime_open=%d best_bid=%s best_ask=%s "
                "open_ids=%s inflight_ids=%s active_runtime_ids=%s orders=%s",
                str(connector_name),
                str(engine_key),
                len(open_orders),
                len(inflight),
                len(active_runtime_ids),
                best_bid,
                best_ask,
                ",".join(open_ids),
                ",".join(inflight_ids),
                ",".join(active_runtime_ids[:5]),
                " | ".join(order_samples),
            )

    def update_controllers_configs(self):
        """
        Keep strategy ticks alive even if a hot-reloaded controller config is invalid.
        """
        now = time.time()
        if now < self._config_reload_retry_after_ts:
            return
        self._reload_controller_modules_if_changed(force=False)
        try:
            super().update_controllers_configs()
            self._mark_config_reload_recovered(now=now, reason="Controller config reload recovered; hot reload resumed.")
            return
        except Exception as exc:
            if not self._is_controller_config_reload_validation_error(exc):
                raise
            # Hot code edits can leave import-cached controller classes stale.
            # Force module reload and retry once before entering degraded mode.
            reloaded = self._reload_controller_modules_if_changed(force=True)
            if reloaded:
                try:
                    super().update_controllers_configs()
                    self._mark_config_reload_recovered(
                        now=now,
                        reason="Controller modules reloaded; config hot reload recovered.",
                    )
                    return
                except Exception as retry_exc:
                    if not self._is_controller_config_reload_validation_error(retry_exc):
                        raise
                    exc = retry_exc
            self._config_reload_error_count += 1
            self._config_reload_degraded = True
            self._config_reload_last_error = f"{type(exc).__name__}: {exc}"
            self._config_reload_last_error_ts = now
            self._config_reload_retry_after_ts = now + max(1.0, self._config_reload_retry_interval_s)
            self.logger().error(
                "Controller config reload rejected; using last known-good config. "
                f"retry_in_s={int(self._config_reload_retry_interval_s)} "
                f"errors={self._config_reload_error_count} error={self._config_reload_last_error}"
            )
            self.logger().debug("Controller config reload rejection details.", exc_info=True)
            self._write_watchdog_heartbeat(reason="config_reload_validation_error")

    def _mark_config_reload_recovered(self, now: float, reason: str) -> None:
        self._config_reload_last_success_ts = now
        if self._config_reload_degraded:
            self.logger().info(reason)
        self._config_reload_degraded = False
        self._config_reload_last_error = ""
        self._config_reload_last_error_ts = 0.0
        self._config_reload_retry_after_ts = 0.0

    def _collect_controller_module_paths(self) -> List[str]:
        module_paths: Set[str] = set()
        for controller in self.controllers.values():
            controller_module = str(getattr(controller.__class__, "__module__", "") or "").strip()
            if controller_module:
                module_paths.add(controller_module)
            cfg = getattr(controller, "config", None)
            controller_type = str(getattr(cfg, "controller_type", "") or "").strip()
            controller_name = str(getattr(cfg, "controller_name", "") or "").strip()
            if controller_type and controller_name:
                module_paths.add(f"controllers.{controller_type}.{controller_name}")
        return sorted(module_paths)

    def _reload_controller_modules_if_changed(self, force: bool) -> bool:
        module_paths = self._collect_controller_module_paths()
        reloaded_any = False
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
                module_file = str(getattr(module, "__file__", "") or "")
                source_file = module_file[:-1] if module_file.endswith(".pyc") else module_file
                source_mtime = os.path.getmtime(source_file) if source_file and os.path.exists(source_file) else 0.0
                previous_mtime = self._controller_module_mtime_by_name.get(module_path, 0.0)
                should_reload = force or source_mtime > previous_mtime
                if should_reload and module_path in sys.modules:
                    module = importlib.reload(module)
                    reloaded_any = True
                    module_file = str(getattr(module, "__file__", "") or "")
                    source_file = module_file[:-1] if module_file.endswith(".pyc") else module_file
                    source_mtime = os.path.getmtime(source_file) if source_file and os.path.exists(source_file) else source_mtime
                self._controller_module_mtime_by_name[module_path] = source_mtime
            except Exception:
                continue
        return reloaded_any

    def _is_controller_config_reload_validation_error(self, exc: Exception) -> bool:
        if self._config_reload_validation_error_types and isinstance(exc, self._config_reload_validation_error_types):
            return True
        msg = str(exc)
        if "validation errors for" in msg:
            return True
        if "Extra inputs are not permitted" in msg:
            return True
        if "extra_forbidden" in msg:
            return True
        return False

    def _write_watchdog_heartbeat(self, reason: str) -> None:
        now = time.time()
        if now - self._last_heartbeat_write_ts < self._heartbeat_write_interval_s:
            return
        self._last_heartbeat_write_ts = now
        payload = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "reason": reason,
            "preflight_checked": bool(self._preflight_checked),
            "preflight_failed": bool(self._preflight_failed),
            "controller_count": len(self.controllers) if isinstance(self.controllers, dict) else 0,
            "is_stop_triggered": bool(getattr(self, "_is_stop_triggered", False)),
            "config_reload_degraded": bool(self._config_reload_degraded),
            "config_reload_error_count": int(self._config_reload_error_count),
            "config_reload_last_error": str(self._config_reload_last_error),
            "config_reload_last_error_ts_utc": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._config_reload_last_error_ts))
                if self._config_reload_last_error_ts > 0
                else ""
            ),
            "config_reload_last_success_ts_utc": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._config_reload_last_success_ts))
                if self._config_reload_last_success_ts > 0
                else ""
            ),
            "artifact_write_failures": dict(getattr(self, "_artifact_write_failures", {})),
        }
        self._write_runtime_json_artifact(
            path=self._heartbeat_path,
            payload=payload,
            artifact_name="watchdog_heartbeat",
        )

    def _write_startup_sync_report(self, status: str, errors: List[str], scan_summary: Dict[str, object]) -> None:
        payload = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
            "status": status,
            "errors": errors,
            "scan_summary": scan_summary,
        }
        self._write_runtime_json_artifact(
            path=self._startup_sync_report_path,
            payload=payload,
            artifact_name="startup_sync_report",
        )

    def _write_runtime_json_artifact(self, *, path: Path, payload: Dict[str, object], artifact_name: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            failures = dict(getattr(self, "_artifact_write_failures", {}))
            failures[artifact_name] = int(failures.get(artifact_name, 0) or 0) + 1
            self._artifact_write_failures = failures
            self.logger().warning(
                "%s write failed; continuing degraded mode count=%s path=%s error=%s",
                artifact_name,
                failures[artifact_name],
                path,
                exc,
            )

    def _append_open_order_snapshot_entry(
        self,
        *,
        orders: List[Dict[str, object]],
        seen_order_ids: Set[str],
        controller_id: str,
        connector_name: str,
        trading_pair: str,
        order: Any,
    ) -> None:
        order_pair = str(getattr(order, "trading_pair", "") or "")
        instrument_id = getattr(order, "instrument_id", None)
        if not order_pair and instrument_id is not None:
            order_pair = str(getattr(instrument_id, "trading_pair", "") or "")
        if trading_pair and order_pair and order_pair != trading_pair:
            return
        order_id = str(getattr(order, "client_order_id", "") or getattr(order, "order_id", "") or "")
        if order_id and order_id in seen_order_ids:
            return
        side_raw = getattr(order, "trade_type", None)
        if side_raw is None:
            side_raw = getattr(order, "side", None)
        side = str(getattr(side_raw, "value", side_raw) or "").upper()
        if not side:
            side = "BUY" if bool(getattr(order, "is_buy", False)) else "SELL"
        amount = (
            getattr(order, "remaining_quantity", None)
            or getattr(order, "amount", None)
            or getattr(order, "quantity", None)
            or ""
        )
        age_sec = float(getattr(order, "age", 0.0) or 0.0)
        if age_sec <= 0.0:
            created_at_ns = getattr(order, "created_at_ns", None)
            try:
                if created_at_ns:
                    age_sec = max(0.0, time.time() - (float(created_at_ns) / 1e9))
            except Exception:
                age_sec = 0.0
        if age_sec <= 0.0:
            creation_timestamp = getattr(order, "creation_timestamp", None)
            try:
                if creation_timestamp:
                    age_sec = max(0.0, time.time() - float(creation_timestamp))
            except Exception:
                age_sec = 0.0
        orders.append(
            {
                "controller_id": controller_id,
                "connector_name": connector_name,
                "trading_pair": order_pair or trading_pair,
                "order_id": order_id,
                "state": str(getattr(order, "current_state", "") or ""),
                "side": side,
                "price": str(getattr(order, "price", "")),
                "amount": str(amount),
                "age_sec": age_sec,
            }
        )
        if order_id:
            seen_order_ids.add(order_id)

    def _iter_connector_open_orders(self, connector: Any) -> List[Any]:
        try:
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return []
            return list(open_orders_fn() or [])
        except Exception:
            return []

    def _iter_bridge_open_orders(self, connector: Any, connector_name: str) -> List[Any]:
        try:
            bridges = getattr(self, "_paper_desk_v2_bridges", {})
            bridge = bridges.get(connector_name, {}) if isinstance(bridges, dict) else {}
            if not isinstance(bridge, dict):
                bridge = {}
            desk = bridge.get("desk")
            iid = bridge.get("instrument_id")
            if desk is None or iid is None:
                desk = getattr(connector, "_paper_desk_v2", None)
                iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
            if desk is None or iid is None:
                return []
            engine = getattr(desk, "_engines", {}).get(getattr(iid, "key", ""))
            open_orders_fn = getattr(engine, "open_orders", None)
            if not callable(open_orders_fn):
                return []
            return list(open_orders_fn() or [])
        except Exception:
            return []

    def _iter_runtime_open_orders(self, instance_name: str, connector_name: str) -> List[Any]:
        try:
            if _paper_exchange_mode_for_instance(instance_name) != "active":
                return []
            runtime_store = getattr(self, "_paper_exchange_runtime_orders", {}) or {}
            target_connector = _canonical_name(connector_name)
            out: List[Any] = []
            for bucket_name, bucket in runtime_store.items():
                if _canonical_name(str(bucket_name or "")) != target_connector:
                    continue
                if not isinstance(bucket, dict):
                    continue
                for order in bucket.values():
                    if bool(getattr(order, "is_open", False)):
                        out.append(order)
            return out
        except Exception:
            return []

    def _collect_open_orders_snapshot(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
            "controllers_checked": 0,
            "orders": [],
        }
        orders: List[Dict[str, object]] = []
        for controller_id, controller in self.controllers.items():
            payload["controllers_checked"] = int(payload["controllers_checked"]) + 1
            connector_name = str(getattr(controller.config, "connector_name", "") or "")
            trading_pair = str(getattr(controller.config, "trading_pair", "") or "")
            connector = self.connectors.get(connector_name) if connector_name else None
            if connector is None:
                continue
            seen_order_ids: Set[str] = set()
            instance_name = str(getattr(controller.config, "instance_name", "") or controller_id)
            for order in self._iter_connector_open_orders(connector):
                self._append_open_order_snapshot_entry(
                    orders=orders,
                    seen_order_ids=seen_order_ids,
                    controller_id=controller_id,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    order=order,
                )
            for order in self._iter_bridge_open_orders(connector, connector_name):
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                self._append_open_order_snapshot_entry(
                    orders=orders,
                    seen_order_ids=seen_order_ids,
                    controller_id=controller_id,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    order=order,
                )
            for order in self._iter_runtime_open_orders(instance_name, connector_name):
                self._append_open_order_snapshot_entry(
                    orders=orders,
                    seen_order_ids=seen_order_ids,
                    controller_id=controller_id,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    order=order,
                )
        payload["orders"] = orders
        payload["orders_count"] = len(orders)
        return payload

    def _write_open_orders_snapshot(self, reason: str) -> None:
        now = time.time()
        if now - self._last_open_orders_write_ts < self._open_orders_write_interval_s:
            return
        self._last_open_orders_write_ts = now
        payload = self._collect_open_orders_snapshot()
        payload["reason"] = reason
        self._write_runtime_json_artifact(
            path=self._open_orders_snapshot_path,
            payload=payload,
            artifact_name="open_orders_snapshot",
        )

    def control_max_drawdown(self):
        if self.config.max_controller_drawdown_quote:
            self.check_max_controller_drawdown()
        if self.config.max_global_drawdown_quote:
            self.check_max_global_drawdown()

    def check_max_controller_drawdown(self):
        for controller_id, controller in self.controllers.items():
            if controller.status != RunnableStatus.RUNNING:
                continue
            controller_pnl = self.get_performance_report(controller_id).global_pnl_quote
            last_max_pnl = self.max_pnl_by_controller[controller_id]
            if controller_pnl > last_max_pnl:
                self.max_pnl_by_controller[controller_id] = controller_pnl
            else:
                current_drawdown = last_max_pnl - controller_pnl
                if current_drawdown > self.config.max_controller_drawdown_quote:
                    self.logger().info(f"Controller {controller_id} reached max drawdown. Stopping the controller.")
                    controller.stop()
                    executors_order_placed = self.filter_executors(
                        executors=self.get_executors_by_controller(controller_id),
                        filter_func=lambda x: x.is_active and not x.is_trading,
                    )
                    self.executor_orchestrator.execute_actions(
                        actions=[StopExecutorAction(controller_id=controller_id, executor_id=executor.id) for executor in executors_order_placed]
                    )
                    self.drawdown_exited_controllers.append(controller_id)

    def check_max_global_drawdown(self):
        current_global_pnl = sum([self.get_performance_report(controller_id).global_pnl_quote for controller_id in self.controllers.keys()])
        if current_global_pnl > self.max_global_pnl:
            self.max_global_pnl = current_global_pnl
        else:
            current_global_drawdown = self.max_global_pnl - current_global_pnl
            if current_global_drawdown > self.config.max_global_drawdown_quote:
                self.drawdown_exited_controllers.extend(list(self.controllers.keys()))
                self.logger().info("Global drawdown reached. Stopping the strategy.")
                self._is_stop_triggered = True
                HummingbotApplication.main_application().stop()

    def get_controller_report(self, controller_id: str) -> dict:
        """
        Get the full report for a controller including performance and custom info.
        """
        performance_report = self.controller_reports.get(controller_id, {}).get("performance")
        return {
            "performance": performance_report.dict() if performance_report else {},
            "custom_info": self.controllers[controller_id].get_custom_info()
        }

    def send_performance_report(self):
        if self.current_timestamp - self._last_performance_report_timestamp >= self.performance_report_interval and self._pub:
            controller_reports = {controller_id: self.get_controller_report(controller_id) for controller_id in self.controllers.keys()}
            self._pub(controller_reports)
            self._last_performance_report_timestamp = self.current_timestamp

    def check_manual_kill_switch(self):
        for controller_id, controller in self.controllers.items():
            if controller.config.manual_kill_switch and controller.status == RunnableStatus.RUNNING:
                self.logger().info(f"Manual cash out for controller {controller_id}.")
                controller.stop()
                executors_to_stop = self.get_executors_by_controller(controller_id)
                self.executor_orchestrator.execute_actions(
                    [StopExecutorAction(executor_id=executor.id,
                                        controller_id=executor.controller_id) for executor in executors_to_stop])
            if not controller.config.manual_kill_switch and controller.status == RunnableStatus.TERMINATED:
                if controller_id in self.drawdown_exited_controllers:
                    continue
                self.logger().info(f"Restarting controller {controller_id}.")
                controller.start()

    def check_executors_status(self):
        # Controller-driven market making requires executors to rest while not "trading"
        # (e.g., passive orders waiting for touch/fill). The base auto-stop behavior
        # can prematurely cancel those executors and create fill starvation loops.
        if os.getenv("HB_CONTROLLER_OWNS_EXECUTOR_LIFECYCLE", "true").strip().lower() in {"1", "true", "yes"}:
            return
        active_executors = self.filter_executors(
            executors=self.get_all_executors(),
            filter_func=lambda executor: executor.status == RunnableStatus.RUNNING
        )
        if not active_executors:
            self.logger().info("All executors have finalized their execution. Stopping the strategy.")
            HummingbotApplication.main_application().stop()
        else:
            non_trading_executors = self.filter_executors(
                executors=active_executors,
                filter_func=lambda executor: not executor.is_trading
            )
            self.executor_orchestrator.execute_actions(
                [StopExecutorAction(executor_id=executor.id,
                                    controller_id=executor.controller_id) for executor in non_trading_executors])

    def _log_action_trace(self, stage: str, actions: List[Any], force: bool = False) -> None:
        if not self._action_trace_enabled:
            return
        now = time.time()
        if not force and (now - self._action_trace_last_ts) < self._action_trace_cooldown_s:
            return
        self._action_trace_last_ts = now
        create_actions = [a for a in actions if isinstance(a, CreateExecutorAction)]
        stop_actions = [a for a in actions if isinstance(a, StopExecutorAction)]
        level_ids: List[str] = []
        for action in create_actions:
            cfg = getattr(action, "executor_config", None)
            level_id = getattr(cfg, "level_id", None) if cfg is not None else None
            if level_id is not None:
                level_ids.append(str(level_id))
        stop_ids = [str(getattr(a, "executor_id", "")) for a in stop_actions]
        self.logger().warning(
            "ACTION_TRACE stage=%s total=%d create=%d stop=%d level_ids=%s stop_ids=%s",
            stage,
            len(actions),
            len(create_actions),
            len(stop_actions),
            ",".join(level_ids[:6]),
            ",".join(stop_ids[:6]),
        )

    def create_actions_proposal(self) -> List[CreateExecutorAction]:
        self._controller_actions_buffer = []
        for controller in self.controllers.values():
            if controller.status != RunnableStatus.RUNNING:
                continue
            try:
                self._controller_actions_buffer.extend(controller.determine_executor_actions())
            except Exception:
                self.logger().error(
                    "Controller action proposal failed for controller_id=%s",
                    getattr(getattr(controller, "config", None), "id", "unknown"),
                    exc_info=True,
                )
        force_log = any(
            str(getattr(getattr(action, "executor_config", None), "level_id", "")) == "position_rebalance"
            for action in self._controller_actions_buffer
            if isinstance(action, CreateExecutorAction)
        )
        self._log_action_trace("buffered", self._controller_actions_buffer, force=force_log)
        return [a for a in self._controller_actions_buffer if isinstance(a, CreateExecutorAction)]

    def stop_actions_proposal(self) -> List[StopExecutorAction]:
        if not self._controller_actions_buffer:
            return []
        stop_actions = [a for a in self._controller_actions_buffer if isinstance(a, StopExecutorAction)]
        if stop_actions:
            self._log_action_trace("stop_dispatch", stop_actions, force=True)
        self._controller_actions_buffer = []
        return stop_actions

    def apply_initial_setting(self):
        connectors_position_mode = {}
        for controller_id, controller in self.controllers.items():
            self.max_pnl_by_controller[controller_id] = Decimal("0")
            config_dict = controller.config.model_dump()
            if "connector_name" in config_dict:
                if self.is_perpetual(config_dict["connector_name"]):
                    if "position_mode" in config_dict:
                        connectors_position_mode[config_dict["connector_name"]] = config_dict["position_mode"]
                    if "leverage" in config_dict and "trading_pair" in config_dict:
                        self.connectors[config_dict["connector_name"]].set_leverage(
                            leverage=config_dict["leverage"],
                            trading_pair=config_dict["trading_pair"])
        for connector_name, position_mode in connectors_position_mode.items():
            self.connectors[connector_name].set_position_mode(position_mode)

    def _install_internal_paper_adapters(self):
        bot_mode = _runtime_bot_mode()
        for controller_id, controller in self.controllers.items():
            if controller_id in self._paper_adapter_installed:
                continue
            cfg = getattr(controller, "config", None)
            if cfg is None:
                continue
            connector_name = str(getattr(cfg, "connector_name", ""))
            trading_pair = str(getattr(cfg, "trading_pair", ""))
            # BOT_MODE is the single runtime source of truth for paper/live path.
            is_paper = bot_mode == "paper"
            if not is_paper or not trading_pair:
                if bot_mode == "live" and controller_id not in self._paper_adapter_pending_logged:
                    self.logger().info(f"LIVE MODE: paper engine disabled for {connector_name}/{trading_pair}")
                    self._paper_adapter_pending_logged.add(controller_id)
                continue

            # Paper Engine v2 — pure bridge, no v1 adapter
            success = self._install_paper_engine_v2(controller, cfg, connector_name, trading_pair)
            if success:
                self._paper_adapter_installed.add(controller_id)
                self.logger().info(
                    f"Paper Engine v2 installed for {connector_name}/{trading_pair} (controller={controller_id})"
                )
            else:
                if controller_id not in self._paper_adapter_pending_logged:
                    available = ",".join(sorted(self.connectors.keys())) if isinstance(self.connectors, dict) else "unknown"
                    self.logger().warning(
                        f"Paper Engine v2 pending for {connector_name}/{trading_pair} "
                        f"(available_connectors={available})"
                    )
                    self._paper_adapter_pending_logged.add(controller_id)

    def _install_paper_engine_v2(
        self, controller: Any, cfg: Any, connector_name: str, trading_pair: str
    ) -> bool:
        """Install Paper Engine v2 as the sole paper simulation layer.

        Replaces paper_engine.py (v1) entirely. Provides:
        - PaperDesk: multi-instrument portfolio, position tracking, funding, persistence
        - PaperBudgetChecker: HB collateral system bypass
        - Strategy delegation: buy/sell/cancel routing through PaperDesk
        - Balance reporting: get_balance returns PaperPortfolio values
        """
        try:
            from controllers.paper_engine_v2.desk import PaperDesk
            from controllers.paper_engine_v2.config import PaperEngineConfig
            from controllers.paper_engine_v2.types import InstrumentId

            connector_type = str(getattr(cfg, "resolved_connector_type", "spot"))
            instrument_type = "perp" if connector_type == "perp" else "spot"
            # Keep legacy venue mapping stable to preserve PaperDesk state keys.
            # Fee lookup is handled in paper_engine_v2 fee model selection.
            venue = connector_name.replace("_paper_trade", "").replace("_perpetual", "")
            iid = InstrumentId(venue=venue, trading_pair=trading_pair, instrument_type=instrument_type)

            # Create shared PaperDesk on first paper controller
            if self._paper_desk_v2 is None:
                paper_cfg = PaperEngineConfig.from_controller_config(cfg)
                self._paper_desk_v2 = PaperDesk.from_paper_config(paper_cfg)
                self.logger().info("PaperDesk v2 created (shared across all paper controllers)")

            return _install_paper_desk_bridge_v2(
                strategy=self,
                desk=self._paper_desk_v2,
                connector_name=connector_name,
                instrument_id=iid,
                trading_pair=trading_pair,
            )
        except Exception as exc:
            self.logger().warning(f"Paper Engine v2 install failed: {exc}")
            return False

    def _tick_paper_adapters(self):
        """Drive Paper Engine v2 tick on each HB on_tick cycle."""
        if self._paper_desk_v2 is not None:
            try:
                from controllers.paper_engine_v2.hb_bridge import drive_desk_tick
                drive_desk_tick(self, self._paper_desk_v2)
            except Exception as exc:
                self.logger().debug(f"Paper desk tick failed: {exc}")

    def did_fail_order(self, order_failed_event: MarketOrderFailureEvent):
        """
        Handle order failure events by logging the error and stopping the strategy if necessary.
        """
        self.logger().error(
            "ORDER_FAIL_TRACE order_id=%s trading_pair=%s message=%s",
            str(getattr(order_failed_event, "order_id", "")),
            str(getattr(order_failed_event, "trading_pair", "")),
            str(getattr(order_failed_event, "error_message", "")),
        )
        if order_failed_event.error_message and "position side" in order_failed_event.error_message.lower():
            connectors_position_mode = {}
            for controller_id, controller in self.controllers.items():
                config_dict = controller.config.model_dump()
                if "connector_name" in config_dict:
                    if self.is_perpetual(config_dict["connector_name"]):
                        if "position_mode" in config_dict:
                            connectors_position_mode[config_dict["connector_name"]] = config_dict["position_mode"]
            for connector_name, position_mode in connectors_position_mode.items():
                self.connectors[connector_name].set_position_mode(position_mode)

    def _init_external_bus(self):
        if not self.config.external_signal_risk_enabled:
            return
        if RedisStreamClient is None or HBEventPublisher is None or HBIntentConsumer is None:
            self.logger().warning("External signal/risk enabled but service bridge modules are unavailable.")
            return
        self._bus_client = RedisStreamClient(
            host=self.config.redis_host,
            port=self.config.redis_port,
            db=self.config.redis_db,
            password=self.config.redis_password,
            enabled=True,
        )
        self._bus_publisher = HBEventPublisher(self._bus_client, producer=f"hb:{self.config.script_file_name}")
        self._bus_consumer = HBIntentConsumer(
            self._bus_client,
            group=self.config.redis_consumer_group,
            consumer_name=f"hb-{self.config.script_file_name}",
        )
        if self._bus_client.ping():
            self._last_bus_ok_ts = time.time()

    def _resolve_depth_market_sequence(
        self,
        instance_name: str,
        controller_id: str,
        connector_name: str,
        trading_pair: str,
        source_market_sequence: Optional[int],
    ) -> int:
        def _safe_int(value: Any) -> Optional[int]:
            try:
                return int(float(value))
            except Exception:
                return None

        key = "|".join(
            [
                str(instance_name).strip(),
                str(controller_id).strip(),
                str(connector_name).strip(),
                str(trading_pair).strip(),
            ]
        )
        prev = self._depth_market_sequence_by_key.get(key)
        if prev is None:
            seed: Optional[int] = None
            bus_client = getattr(self, "_bus_client", None)
            read_latest = getattr(bus_client, "read_latest", None)
            if callable(read_latest):
                latest = read_latest(MARKET_DEPTH_STREAM)
                if isinstance(latest, tuple) and len(latest) == 2 and isinstance(latest[1], dict):
                    latest_payload = latest[1]
                    latest_key = "|".join(
                        [
                            str(latest_payload.get("instance_name", "")).strip(),
                            str(latest_payload.get("controller_id", "")).strip(),
                            str(latest_payload.get("connector_name", "")).strip(),
                            str(latest_payload.get("trading_pair", "")).strip(),
                        ]
                    )
                    latest_seq = _safe_int(latest_payload.get("market_sequence"))
                    if latest_key == key and latest_seq is not None and latest_seq >= 0:
                        seed = latest_seq + 1
            if seed is None:
                seed = int(source_market_sequence) if source_market_sequence is not None else int(time.time() * 1000)
            self._depth_market_sequence_by_key[key] = seed
            return seed
        next_seq = int(prev) + 1
        self._depth_market_sequence_by_key[key] = next_seq
        return next_seq

    def _publish_market_state_to_bus(self):
        if self._bus_publisher is None or MarketSnapshotEvent is None:
            return
        if not self._bus_publisher.available:
            return
        self._last_bus_ok_ts = time.time()
        max_depth_levels = max(1, int(os.getenv("HB_MARKET_DEPTH_LEVELS", "20")))
        publish_public_depth = os.getenv("HB_CONTROLLER_PUBLISH_PUBLIC_DEPTH", "false").strip().lower() in {
            "1",
            "true",
            "yes",
        }

        def _opt_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    return None
            try:
                return float(value)
            except Exception:
                return None

        def _opt_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    return None
            try:
                return int(float(value))
            except Exception:
                return None

        for controller_id, controller in self.controllers.items():
            custom = controller.get_custom_info() if hasattr(controller, "get_custom_info") else {}
            connector_name = getattr(controller.config, "connector_name", "unknown")
            trading_pair = getattr(controller.config, "trading_pair", "unknown")
            instance_name = str(getattr(controller.config, "instance_name", "bot"))
            depth_snapshot = {
                "bids": [],
                "asks": [],
                "best_bid": None,
                "best_ask": None,
                "market_sequence": None,
            }
            connector_obj = self.connectors.get(connector_name) if isinstance(self.connectors, dict) else None
            if connector_obj is not None:
                depth_snapshot = _extract_order_book_depth_snapshot(
                    connector_obj=connector_obj,
                    pair=trading_pair,
                    max_levels=max_depth_levels,
                )
            source_market_sequence = _opt_int(custom.get("market_sequence"))
            if source_market_sequence is None:
                source_market_sequence = _opt_int(depth_snapshot.get("market_sequence"))
            depth_market_sequence = self._resolve_depth_market_sequence(
                instance_name=instance_name,
                controller_id=controller_id,
                connector_name=connector_name,
                trading_pair=trading_pair,
                source_market_sequence=source_market_sequence,
            )
            exchange_ts_ms = _opt_int(custom.get("exchange_ts_ms", custom.get("reference_ts_ms")))
            ingest_ts_ms = int(time.time() * 1000)
            best_bid = _opt_float(custom.get("best_bid_price", custom.get("best_bid")))
            best_ask = _opt_float(custom.get("best_ask_price", custom.get("best_ask")))
            if best_bid is None:
                best_bid = _opt_float(depth_snapshot.get("best_bid"))
            if best_ask is None:
                best_ask = _opt_float(depth_snapshot.get("best_ask"))
            event = MarketSnapshotEvent(
                producer="hb",
                instance_name=instance_name,
                controller_id=controller_id,
                connector_name=connector_name,
                trading_pair=trading_pair,
                mid_price=float(custom.get("reference_price", custom.get("mid", 0)) or 0),
                equity_quote=float(custom.get("equity_quote", 0) or 0),
                base_pct=float(custom.get("base_pct", 0) or 0),
                target_base_pct=float(custom.get("target_base_pct", 0) or 0),
                spread_pct=float(custom.get("spread_pct", 0) or 0),
                net_edge_pct=float(custom.get("net_edge_pct", 0) or 0),
                turnover_x=float(custom.get("turnover_x", 0) or 0),
                state=str(custom.get("state", "unknown")),
                best_bid=best_bid,
                best_ask=best_ask,
                best_bid_size=_opt_float(custom.get("best_bid_size")),
                best_ask_size=_opt_float(custom.get("best_ask_size")),
                last_trade_price=_opt_float(custom.get("last_trade_price")),
                mark_price=_opt_float(custom.get("mark_price")),
                funding_rate=_opt_float(custom.get("funding_rate")),
                exchange_ts_ms=exchange_ts_ms,
                ingest_ts_ms=ingest_ts_ms,
                market_sequence=source_market_sequence,
                extra={
                    "origin": "hummingbot_controller_runtime",
                    "provenance_origin": "hummingbot_controller_runtime",
                    "reference_ts_ms": str(exchange_ts_ms or ingest_ts_ms),
                    "provenance_connector": str(connector_name),
                    "provenance_trading_pair": str(trading_pair),
                    "provenance_market_sequence": str(int(source_market_sequence or 0)),
                    "regime": str(custom.get("regime", "n/a")),
                    "band_pct": str(float(custom.get("spread_floor_pct", 0) or 0)),
                    "adverse_drift_bps": str(float(custom.get("adverse_drift_30s", 0) or 0) * 10000),
                    "funding_rate_bps": str(float(custom.get("funding_rate", 0) or 0) * 10000),
                    "ob_imbalance": str(float(custom.get("ob_imbalance", 0) or 0)),
                    "fill_edge_ewma_bps": str(float(custom.get("fill_edge_ewma_bps", 0) or 0)),
                    "drawdown_pct": str(float(custom.get("drawdown_pct", 0) or 0)),
                    "daily_loss_pct": str(float(custom.get("daily_loss_pct", 0) or 0)),
                    "regime_source": str(custom.get("regime_source", "price_buffer")),
                    "depth_levels": str(max_depth_levels),
                },
            )
            self._bus_publisher.publish_market_snapshot(event)
            if publish_public_depth and MarketDepthSnapshotEvent is not None:
                depth_event = MarketDepthSnapshotEvent(
                    producer="hb",
                    instance_name=instance_name,
                    controller_id=controller_id,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    depth_levels=max_depth_levels,
                    bids=depth_snapshot.get("bids", []),
                    asks=depth_snapshot.get("asks", []),
                    best_bid=best_bid,
                    best_ask=best_ask,
                    last_trade_price=_opt_float(custom.get("last_trade_price")),
                    mark_price=_opt_float(custom.get("mark_price")),
                    funding_rate=_opt_float(custom.get("funding_rate")),
                    exchange_ts_ms=exchange_ts_ms,
                    ingest_ts_ms=ingest_ts_ms,
                    market_sequence=depth_market_sequence,
                    extra={
                        "origin": "hummingbot_controller_runtime",
                        "provenance_origin": "hummingbot_controller_runtime",
                        "provenance_connector": str(connector_name),
                        "provenance_trading_pair": str(trading_pair),
                        "provenance_market_sequence": str(int(source_market_sequence or 0)),
                        "resolved_market_sequence": str(int(depth_market_sequence)),
                        "state": str(custom.get("state", "unknown")),
                    },
                )
                self._bus_publisher.publish_market_depth(depth_event)

    def _consume_execution_intents(self):
        if self._bus_consumer is None:
            return
        for entry_id, intent in self._bus_consumer.poll(count=20, block_ms=self.config.event_poll_ms):
            target_instance = str(intent.instance_name).strip()
            local_instances = {
                str(getattr(getattr(ctrl, "config", None), "instance_name", "")).strip()
                for ctrl in self.controllers.values()
            }
            local_instances.discard("")
            # With per-bot consumer groups, each bot receives the full stream.
            # Skip intents not addressed to this bot instance.
            if target_instance and local_instances and target_instance not in local_instances:
                self._bus_consumer.ack(entry_id, intent.event_id)
                continue
            resolved_controller_id = str(intent.controller_id)
            controller = self.controllers.get(resolved_controller_id)
            if controller is None:
                # Fallback route: some producers emit a generic controller_id.
                # Resolve by instance_name so desk-level intents still reach the right bot.
                for candidate_id, candidate in self.controllers.items():
                    cfg = getattr(candidate, "config", None)
                    candidate_instance = str(getattr(cfg, "instance_name", "")).strip()
                    if candidate_instance and candidate_instance == str(intent.instance_name).strip():
                        controller = candidate
                        resolved_controller_id = str(candidate_id)
                        break
            if controller is None:
                self._bus_consumer.reject(entry_id, intent.event_id, reason="controller_not_found")
                continue
            if not self._intent_passes_local_authority(controller, intent.model_dump()):
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="warning",
                    category="intent_rejected",
                    message="Intent rejected by local Hummingbot authority checks.",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": resolved_controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                    },
                )
                self._bus_consumer.reject(entry_id, intent.event_id, reason="local_authority_reject")
                continue
            applied = False
            reason = "not_supported"
            apply_method = getattr(controller, "apply_execution_intent", None)
            if callable(apply_method):
                applied, reason = apply_method(intent.model_dump())
            if applied:
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="info",
                    category="intent_applied",
                    message="Execution intent applied.",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": resolved_controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                        "reason": str(intent_meta.get("reason", "")),
                    },
                )
                self._bus_consumer.ack(entry_id, intent.event_id)
            else:
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="warning",
                    category="intent_rejected",
                    message=f"Intent rejected by controller: {reason}",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": resolved_controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                    },
                )
                self._bus_consumer.reject(entry_id, intent.event_id, reason=reason)

    def _intent_passes_local_authority(self, controller, intent: Dict[str, object]) -> bool:
        connector_ready_fn = getattr(controller, "_connector_ready", None)
        if callable(connector_ready_fn):
            try:
                if not bool(connector_ready_fn()):
                    return False
            except Exception:
                return False
        action = str(intent.get("action", ""))
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            try:
                if value is None:
                    return False
                target = Decimal(str(value))
            except Exception:
                return False
            if target < Decimal("0") or target > Decimal("1"):
                return False
        if action == "set_daily_pnl_target_pct":
            value = intent.get("daily_pnl_target_pct")
            metadata = intent.get("metadata", {})
            if value is None and isinstance(metadata, dict):
                value = metadata.get("daily_pnl_target_pct")
            try:
                if value is None:
                    return False
                target = Decimal(str(value))
            except Exception:
                return False
            if target < Decimal("0") or target > Decimal("100"):
                return False
        return True

    def _publish_audit(self, instance_name: str, severity: str, category: str, message: str, metadata: Dict[str, str]):
        if self._bus_publisher is None or AuditEvent is None:
            return
        event = AuditEvent(
            producer="hb",
            instance_name=instance_name,
            severity=severity,
            category=category,
            message=message,
            metadata=metadata,
        )
        self._bus_publisher.publish_audit(event)

    def _check_hard_stop_kill_switch(self):
        """Publish one-shot kill_switch on HARD_STOP risk transition."""
        if self._bus_publisher is None:
            return
        now = time.time()
        for controller_id, controller in self.controllers.items():
            custom = controller.get_custom_info() if hasattr(controller, "get_custom_info") else {}
            state = str(custom.get("state", ""))
            risk_reasons = str(custom.get("risk_reasons", ""))
            if state != "hard_stop":
                self._hard_stop_kill_switch_latched_by_controller.pop(controller_id, None)
                self._hard_stop_kill_switch_last_reason_by_controller.pop(controller_id, None)
                self._hard_stop_kill_switch_last_ts_by_controller.pop(controller_id, None)
                self._hard_stop_clear_candidate_since_by_controller.pop(controller_id, None)
                self._hard_stop_resume_last_ts_by_controller.pop(controller_id, None)
                continue
            risk_triggers = {"daily_loss_hard_limit", "drawdown_hard_limit", "daily_turnover_hard_limit",
                             "margin_ratio_critical", "cancel_budget_repeated_breach"}
            active_reasons = set(risk_reasons.split("|")) if risk_reasons else set()
            hard_reasons_active = bool(active_reasons & risk_triggers)
            if hard_reasons_active:
                self._hard_stop_clear_candidate_since_by_controller.pop(controller_id, None)
                if self._hard_stop_kill_switch_latched_by_controller.get(controller_id, False):
                    continue
                reason_key = risk_reasons.strip() or "hard_stop_triggered"
                try:
                    from services.contracts.event_schemas import ExecutionIntentEvent
                    from services.contracts.stream_names import EXECUTION_INTENT_STREAM, STREAM_RETENTION_MAXLEN
                    intent = ExecutionIntentEvent(
                        producer=f"hb:{self.config.script_file_name}",
                        instance_name=str(getattr(controller.config, "instance_name", "bot1")),
                        controller_id=controller_id,
                        action="kill_switch",
                        expires_at_ms=int(time.time() * 1000) + 300_000,
                        metadata={"reason": risk_reasons},
                    )
                    self._bus_client.xadd(
                        EXECUTION_INTENT_STREAM,
                        intent.model_dump(),
                        maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
                    )
                    self._hard_stop_kill_switch_last_reason_by_controller[controller_id] = reason_key
                    self._hard_stop_kill_switch_last_ts_by_controller[controller_id] = now
                    self._hard_stop_kill_switch_latched_by_controller[controller_id] = True
                    self.logger().error(f"HARD_STOP kill_switch published for {controller_id}: {risk_reasons}")
                except Exception:
                    pass
                continue

            # Recovery policy: if controller still reports HARD_STOP but hard risk triggers
            # are no longer active, wait for cooldown and publish a one-shot resume intent.
            self._hard_stop_kill_switch_last_reason_by_controller.pop(controller_id, None)
            self._hard_stop_kill_switch_last_ts_by_controller.pop(controller_id, None)
            clear_since = self._hard_stop_clear_candidate_since_by_controller.get(controller_id)
            if clear_since is None:
                self._hard_stop_clear_candidate_since_by_controller[controller_id] = now
                clear_since = now
            if not self._hard_stop_auto_resume_on_clear:
                continue
            if (now - clear_since) < self._hard_stop_clear_cooldown_s:
                continue
            last_resume_ts = self._hard_stop_resume_last_ts_by_controller.get(controller_id, 0.0)
            if (now - last_resume_ts) < self._hard_stop_kill_switch_republish_s:
                continue
            try:
                from services.contracts.event_schemas import ExecutionIntentEvent
                from services.contracts.stream_names import EXECUTION_INTENT_STREAM, STREAM_RETENTION_MAXLEN
                resume_intent = ExecutionIntentEvent(
                    producer=f"hb:{self.config.script_file_name}",
                    instance_name=str(getattr(controller.config, "instance_name", "bot1")),
                    controller_id=controller_id,
                    action="resume",
                    metadata={
                        "reason": "hard_stop_recovered",
                        "risk_reasons": risk_reasons,
                    },
                )
                self._bus_client.xadd(
                    EXECUTION_INTENT_STREAM,
                    resume_intent.model_dump(),
                    maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
                )
                self._hard_stop_resume_last_ts_by_controller[controller_id] = now
                self.logger().info(
                    "HARD_STOP recovery resume published for %s after %.0fs (reasons=%s).",
                    controller_id,
                    now - clear_since,
                    risk_reasons or "none",
                )
            except Exception:
                pass

    def _handle_bus_outage_soft_pause(self):
        if not self.config.external_signal_risk_enabled or not self.config.bus_soft_pause_on_outage:
            return
        if self._bus_client is None:
            return
        self._bus_ping_tick_counter += 1
        if self._bus_ping_tick_counter % 30 != 0:
            return
        if self._bus_client.ping():
            self._last_bus_ok_ts = time.time()
            for controller in self.controllers.values():
                set_pause = getattr(controller, "set_external_soft_pause", None)
                if callable(set_pause):
                    set_pause(False, "bus_healthy")
            return
        outage_s = time.time() - self._last_bus_ok_ts if self._last_bus_ok_ts > 0 else 0
        if outage_s < 10:
            return
        for controller in self.controllers.values():
            set_pause = getattr(controller, "set_external_soft_pause", None)
            if callable(set_pause):
                set_pause(True, "bus_outage")

    def _run_preflight_once(self):
        self._preflight_checked = True
        errors: List[str] = []
        for controller_id, controller in self.controllers.items():
            controller_errors = run_controller_preflight(controller.config)
            for err in controller_errors:
                errors.append(f"{controller_id}: {err}")
        if not errors:
            self.logger().info("Preflight validation passed.")
        else:
            for err in errors:
                self.logger().error(f"Preflight failed: {err}")
            self._write_startup_sync_report("fail", errors, {"scan_executed": False})
            self._preflight_failed = True
            self._is_stop_triggered = True
            HummingbotApplication.main_application().stop()
            return
        summary = self._scan_orphan_orders()
        self._write_startup_sync_report("pass", [], summary)

    def _scan_orphan_orders(self) -> Dict[str, object]:
        """Cancel any open orders on the exchange that are not tracked by executors."""
        summary: Dict[str, object] = {
            "scan_executed": True,
            "controllers_checked": 0,
            "orphans_canceled": 0,
            "errors": 0,
        }
        for controller_id, controller in self.controllers.items():
            summary["controllers_checked"] = int(summary["controllers_checked"]) + 1
            connector_name = str(getattr(controller.config, "connector_name", ""))
            trading_pair = str(getattr(controller.config, "trading_pair", ""))
            if not connector_name or not trading_pair:
                continue
            connector = self.connectors.get(connector_name)
            if connector is None:
                continue
            try:
                open_orders_fn = getattr(connector, "get_open_orders", None)
                if not callable(open_orders_fn):
                    continue
                open_orders = open_orders_fn()
                if not open_orders:
                    continue
                tracked_ids = set()
                executors = getattr(controller, "executors_info", [])
                for ex in executors:
                    order_id = getattr(ex, "order_id", None) or str(getattr(ex, "id", ""))
                    if order_id:
                        tracked_ids.add(str(order_id))
                orphans_canceled = 0
                for order in open_orders:
                    order_id = str(getattr(order, "client_order_id", getattr(order, "order_id", "")))
                    order_pair = str(getattr(order, "trading_pair", ""))
                    if order_pair != trading_pair:
                        continue
                    if order_id not in tracked_ids:
                        try:
                            connector.cancel(trading_pair, order_id)
                            orphans_canceled += 1
                            summary["orphans_canceled"] = int(summary["orphans_canceled"]) + 1
                            self.logger().warning(f"Orphan order canceled: {order_id} on {connector_name}/{trading_pair}")
                        except Exception:
                            summary["errors"] = int(summary["errors"]) + 1
                            self.logger().error(f"Failed to cancel orphan order: {order_id}", exc_info=True)
                if orphans_canceled > 0:
                    self.logger().warning(f"Startup scan: canceled {orphans_canceled} orphan order(s) for {controller_id}")
                    if self._bus_publisher is not None and AuditEvent is not None:
                        try:
                            self._publish_audit_event(
                                "warning", "orphan_order_scan",
                                f"canceled_{orphans_canceled}_orphan_orders",
                                {"controller_id": controller_id, "connector": connector_name, "pair": trading_pair, "count": str(orphans_canceled)},
                            )
                        except Exception:
                            pass
            except Exception:
                summary["errors"] = int(summary["errors"]) + 1
                self.logger().warning(f"Orphan order scan failed for {controller_id}", exc_info=True)
        return summary
