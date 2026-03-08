from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover - optional in lightweight test environments.
    ccxt = None  # type: ignore[assignment]

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover - optional in lightweight test environments.
    websocket = None  # type: ignore[assignment]

from services.common.logging_config import configure_logging
from services.common.models import RedisSettings
from services.contracts.event_schemas import MarketDepthSnapshotEvent, MarketQuoteEvent, MarketTradeEvent
from services.hb_bridge.publisher import HBEventPublisher
from services.hb_bridge.redis_client import RedisStreamClient

configure_logging()
logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _normalize_pair(value: str) -> str:
    raw = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" in raw:
        return raw
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[:-len(quote)]}-{quote}"
    return raw


def _pair_symbol(pair: str) -> str:
    return _normalize_pair(pair).replace("-", "")


def _binance_stream_symbol(pair: str) -> str:
    return _pair_symbol(pair).lower()


def _bitget_inst_id(pair: str) -> str:
    return _pair_symbol(pair)


def _connector_market_type(connector_name: str) -> str:
    normalized = str(connector_name or "").strip().lower()
    if "perpetual" in normalized or "usdm" in normalized or normalized.endswith("_perp"):
        return "perp"
    return "spot"


def _mid_price(best_bid: Optional[float], best_ask: Optional[float], fallback: Optional[float]) -> Optional[float]:
    if best_bid is not None and best_ask is not None and best_ask >= best_bid:
        return (best_bid + best_ask) / 2.0
    return fallback


def _normalize_depth_levels(levels: Any, max_levels: int) -> List[Dict[str, float]]:
    if not isinstance(levels, list):
        return []
    out: List[Dict[str, float]] = []
    for row in levels:
        price = None
        size = None
        if isinstance(row, dict):
            price = _safe_float(row.get("price"))
            size = _safe_float(row.get("size", row.get("qty", row.get("amount"))))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price = _safe_float(row[0])
            size = _safe_float(row[1])
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        out.append({"price": float(price), "size": float(size)})
        if len(out) >= max_levels:
            break
    return out


@dataclass(frozen=True)
class MarketSubscription:
    connector_name: str
    trading_pair: str

    @property
    def normalized_pair(self) -> str:
        return _normalize_pair(self.trading_pair)


def _parse_subscriptions(raw: str) -> List[MarketSubscription]:
    subscriptions: List[MarketSubscription] = []
    for chunk in str(raw or "").split(","):
        item = chunk.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split("|", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue
        subscriptions.append(MarketSubscription(connector_name=parts[0], trading_pair=_normalize_pair(parts[1])))
    return subscriptions


def _ccxt_exchange_id(connector_name: str) -> Optional[str]:
    normalized = str(connector_name or "").strip().lower()
    if normalized.startswith("bitget"):
        return "bitget"
    if normalized == "binance":
        return "binance"
    if normalized.startswith("binance_perpetual") or normalized.startswith("binanceusdm"):
        return "binanceusdm"
    return None


def _fetch_rest_bootstrap_quote(subscription: MarketSubscription) -> Optional[MarketQuoteEvent]:
    if ccxt is None:
        return None
    exchange_id = _ccxt_exchange_id(subscription.connector_name)
    if not exchange_id:
        return None
    try:
        exchange_cls = getattr(ccxt, exchange_id)
    except Exception:
        return None
    try:
        exchange = exchange_cls({"enableRateLimit": True})
        ticker = exchange.fetch_ticker(subscription.normalized_pair.replace("-", "/"))
        best_bid = _safe_float(ticker.get("bid"))
        best_ask = _safe_float(ticker.get("ask"))
        last_trade_price = _safe_float(ticker.get("last"))
        mid_price = _mid_price(best_bid, best_ask, last_trade_price)
        if best_bid is None or best_ask is None:
            return None
        now_ms = _now_ms()
        return MarketQuoteEvent(
            producer="market_data_service_rest_bootstrap",
            connector_name=subscription.connector_name,
            trading_pair=subscription.normalized_pair,
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_size=_safe_float(ticker.get("bidVolume")),
            best_ask_size=_safe_float(ticker.get("askVolume")),
            mid_price=mid_price,
            last_trade_price=last_trade_price,
            exchange_ts_ms=_safe_int(ticker.get("timestamp")),
            ingest_ts_ms=now_ms,
            venue_symbol=_pair_symbol(subscription.normalized_pair),
            extra={"source": "ccxt_rest_bootstrap"},
        )
    except Exception as exc:
        logger.debug("market_data_service rest bootstrap failed for %s: %s", subscription, exc)
        return None


def _build_bitget_quote_event(payload: Dict[str, Any], subscription: MarketSubscription) -> Optional[MarketQuoteEvent]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    row = data[0] if isinstance(data[0], dict) else None
    if not isinstance(row, dict):
        return None
    best_bid = _safe_float(row.get("bidPr"))
    best_ask = _safe_float(row.get("askPr"))
    if best_bid is None or best_ask is None:
        return None
    last_trade_price = _safe_float(row.get("lastPr"))
    now_ms = _now_ms()
    exchange_ts_ms = _safe_int(row.get("ts"))
    return MarketQuoteEvent(
        producer="market_data_service",
        connector_name=subscription.connector_name,
        trading_pair=subscription.normalized_pair,
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=_safe_float(row.get("bidSz")),
        best_ask_size=_safe_float(row.get("askSz")),
        mid_price=_mid_price(best_bid, best_ask, last_trade_price),
        last_trade_price=last_trade_price,
        funding_rate=_safe_float(row.get("fundingRate")),
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=now_ms,
        market_sequence=exchange_ts_ms,
        venue_symbol=str(row.get("instId") or _bitget_inst_id(subscription.normalized_pair)),
        extra={"channel": str(((payload.get("arg") or {}) if isinstance(payload.get("arg"), dict) else {}).get("channel", ""))},
    )


def _build_binance_quote_event(payload: Dict[str, Any], subscription: MarketSubscription) -> Optional[MarketQuoteEvent]:
    best_bid = _safe_float(payload.get("b"))
    best_ask = _safe_float(payload.get("a"))
    if best_bid is None or best_ask is None:
        return None
    last_trade_price = _safe_float(payload.get("c"))
    exchange_ts_ms = _safe_int(payload.get("E")) or _safe_int(payload.get("T"))
    now_ms = _now_ms()
    return MarketQuoteEvent(
        producer="market_data_service",
        connector_name=subscription.connector_name,
        trading_pair=subscription.normalized_pair,
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=_safe_float(payload.get("B")),
        best_ask_size=_safe_float(payload.get("A")),
        mid_price=_mid_price(best_bid, best_ask, last_trade_price),
        last_trade_price=last_trade_price,
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=now_ms,
        market_sequence=_safe_int(payload.get("u")),
        venue_symbol=str(payload.get("s") or _pair_symbol(subscription.normalized_pair)),
        extra={"channel": "bookTicker"},
    )


def _build_bitget_trade_events(payload: Dict[str, Any], subscription: MarketSubscription) -> List[MarketTradeEvent]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    channel = str(((payload.get("arg") or {}) if isinstance(payload.get("arg"), dict) else {}).get("channel", ""))
    venue_symbol = str(((payload.get("arg") or {}) if isinstance(payload.get("arg"), dict) else {}).get("instId", "")) or _bitget_inst_id(subscription.normalized_pair)
    out: List[MarketTradeEvent] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        price = _safe_float(row.get("px", row.get("price")))
        size = _safe_float(row.get("sz", row.get("size")))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        side_text = str(row.get("side", "")).strip().lower()
        trade_side = side_text if side_text in {"buy", "sell"} else None
        exchange_ts_ms = _safe_int(row.get("ts"))
        market_sequence = _safe_int(row.get("tradeId")) or exchange_ts_ms
        out.append(
            MarketTradeEvent(
                producer="market_data_service",
                connector_name=subscription.connector_name,
                trading_pair=subscription.normalized_pair,
                trade_id=str(row.get("tradeId")) if row.get("tradeId") is not None else None,
                side=trade_side,
                price=price,
                size=size,
                exchange_ts_ms=exchange_ts_ms,
                ingest_ts_ms=_now_ms(),
                market_sequence=market_sequence,
                venue_symbol=venue_symbol,
                extra={
                    "channel": channel,
                    "aggressor_side": trade_side or "",
                },
            )
        )
    return out


def _build_binance_trade_event(payload: Dict[str, Any], subscription: MarketSubscription) -> Optional[MarketTradeEvent]:
    price = _safe_float(payload.get("p"))
    size = _safe_float(payload.get("q"))
    if price is None or size is None or price <= 0 or size <= 0:
        return None
    buyer_is_maker = bool(payload.get("m"))
    side = "sell" if buyer_is_maker else "buy"
    exchange_ts_ms = _safe_int(payload.get("T")) or _safe_int(payload.get("E"))
    trade_id = payload.get("t")
    return MarketTradeEvent(
        producer="market_data_service",
        connector_name=subscription.connector_name,
        trading_pair=subscription.normalized_pair,
        trade_id=str(trade_id) if trade_id is not None else None,
        side=side,
        price=price,
        size=size,
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=_now_ms(),
        market_sequence=_safe_int(trade_id) or exchange_ts_ms,
        venue_symbol=str(payload.get("s") or _pair_symbol(subscription.normalized_pair)),
        extra={
            "channel": "trade",
            "buyer_is_maker": "1" if buyer_is_maker else "0",
            "aggressor_side": side,
        },
    )


def _build_bitget_depth_event(
    payload: Dict[str, Any],
    subscription: MarketSubscription,
    *,
    depth_levels: int,
) -> Optional[MarketDepthSnapshotEvent]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    row = data[0] if isinstance(data[0], dict) else None
    if not isinstance(row, dict):
        return None
    bids = _normalize_depth_levels(row.get("bids"), depth_levels)
    asks = _normalize_depth_levels(row.get("asks"), depth_levels)
    if not bids and not asks:
        return None
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    exchange_ts_ms = _safe_int(row.get("ts"))
    return MarketDepthSnapshotEvent(
        producer="market_data_service",
        instance_name="",
        controller_id="",
        connector_name=subscription.connector_name,
        trading_pair=subscription.normalized_pair,
        depth_levels=depth_levels,
        bids=bids,
        asks=asks,
        best_bid=best_bid,
        best_ask=best_ask,
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=_now_ms(),
        market_sequence=exchange_ts_ms,
        extra={"channel": str(((payload.get("arg") or {}) if isinstance(payload.get("arg"), dict) else {}).get("channel", ""))},
    )


def _build_binance_depth_event(
    payload: Dict[str, Any],
    subscription: MarketSubscription,
    *,
    depth_levels: int,
) -> Optional[MarketDepthSnapshotEvent]:
    bids = _normalize_depth_levels(payload.get("b"), depth_levels)
    asks = _normalize_depth_levels(payload.get("a"), depth_levels)
    if not bids and not asks:
        return None
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    exchange_ts_ms = _safe_int(payload.get("E")) or _safe_int(payload.get("T"))
    market_sequence = _safe_int(payload.get("u"))
    return MarketDepthSnapshotEvent(
        producer="market_data_service",
        instance_name="",
        controller_id="",
        connector_name=subscription.connector_name,
        trading_pair=subscription.normalized_pair,
        depth_levels=depth_levels,
        bids=bids,
        asks=asks,
        best_bid=best_bid,
        best_ask=best_ask,
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=_now_ms(),
        market_sequence=market_sequence,
        extra={"channel": "depth20"},
    )


@dataclass
class MarketDataServiceConfig:
    enabled: bool = field(
        default_factory=lambda: os.getenv("MARKET_DATA_SERVICE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )
    subscriptions: List[MarketSubscription] = field(
        default_factory=lambda: _parse_subscriptions(os.getenv("MARKET_DATA_SERVICE_SUBSCRIPTIONS", ""))
    )
    reconnect_delay_sec: float = field(
        default_factory=lambda: max(1.0, float(os.getenv("MARKET_DATA_SERVICE_RECONNECT_SEC", "5")))
    )
    depth_enabled: bool = field(
        default_factory=lambda: os.getenv("MARKET_DATA_SERVICE_DEPTH_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    )
    depth_levels: int = field(default_factory=lambda: max(1, int(os.getenv("MARKET_DATA_SERVICE_DEPTH_LEVELS", "20"))))
    status_dir: Path = field(
        default_factory=lambda: Path(os.getenv("HB_REPORTS_ROOT", "/workspace/hbot/reports")).resolve() / "market_data_service"
    )
    status_max_sec: int = field(default_factory=lambda: int(os.getenv("MARKET_DATA_SERVICE_STATUS_MAX_SEC", "30")))


class _AdapterThread(threading.Thread):
    def __init__(self, subscription: MarketSubscription, cfg: MarketDataServiceConfig, publisher: HBEventPublisher):
        super().__init__(daemon=True, name=f"market-data-{subscription.connector_name}-{subscription.normalized_pair}")
        self._subscription = subscription
        self._cfg = cfg
        self._publisher = publisher
        self._stop = threading.Event()
        self._last_quote_ms: Optional[int] = None
        self._last_depth_ms: Optional[int] = None
        self._last_trade_ms: Optional[int] = None
        self._last_error: str = ""
        self._connected = False

    @property
    def subscription(self) -> MarketSubscription:
        return self._subscription

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> Dict[str, Any]:
        quote_age_ms = None if self._last_quote_ms is None else max(0, _now_ms() - self._last_quote_ms)
        depth_age_ms = None if self._last_depth_ms is None else max(0, _now_ms() - self._last_depth_ms)
        trade_age_ms = None if self._last_trade_ms is None else max(0, _now_ms() - self._last_trade_ms)
        return {
            "connector_name": self._subscription.connector_name,
            "trading_pair": self._subscription.normalized_pair,
            "connected": self._connected,
            "last_quote_ms": self._last_quote_ms,
            "quote_age_ms": quote_age_ms,
            "last_depth_ms": self._last_depth_ms,
            "depth_age_ms": depth_age_ms,
            "last_trade_ms": self._last_trade_ms,
            "trade_age_ms": trade_age_ms,
            "last_error": self._last_error,
        }

    def _publish(self, event: MarketQuoteEvent) -> None:
        result = self._publisher.publish_market_quote(event)
        if result:
            self._last_quote_ms = _now_ms()
            self._last_error = ""

    def _publish_depth(self, event: MarketDepthSnapshotEvent) -> None:
        result = self._publisher.publish_market_depth(event)
        if result:
            self._last_depth_ms = _now_ms()
            self._last_error = ""

    def _publish_trade(self, event: MarketTradeEvent) -> None:
        result = self._publisher.publish_market_trade(event)
        if result:
            self._last_trade_ms = _now_ms()
            self._last_error = ""

    def _on_rest_bootstrap(self) -> None:
        event = _fetch_rest_bootstrap_quote(self._subscription)
        if event is not None:
            self._publish(event)

    def run(self) -> None:
        if websocket is None:
            self._last_error = "websocket_client_not_installed"
            logger.error("market_data_service cannot start adapter without websocket-client")
            return
        self._on_rest_bootstrap()
        while not self._stop.is_set():
            try:
                self._run_ws()
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                logger.warning(
                    "market_data_service adapter failed connector=%s pair=%s error=%s",
                    self._subscription.connector_name,
                    self._subscription.normalized_pair,
                    exc,
                )
            if self._stop.wait(self._cfg.reconnect_delay_sec):
                break

    def _run_ws(self) -> None:
        raise NotImplementedError


class _BitgetQuoteAdapter(_AdapterThread):
    def _run_ws(self) -> None:
        url = "wss://ws.bitget.com/v2/ws/public"
        subscription = self._subscription
        market_type = _connector_market_type(subscription.connector_name)
        inst_type = "USDT-FUTURES" if market_type == "perp" else "SPOT"

        def on_open(ws_app) -> None:  # noqa: ANN001
            self._connected = True
            args = [
                {
                    "instType": inst_type,
                    "channel": "ticker",
                    "instId": _bitget_inst_id(subscription.normalized_pair),
                }
            ]
            if self._cfg.depth_enabled:
                args.append(
                    {
                        "instType": inst_type,
                        "channel": "books15",
                        "instId": _bitget_inst_id(subscription.normalized_pair),
                    }
                )
            args.append(
                {
                    "instType": inst_type,
                    "channel": "trade",
                    "instId": _bitget_inst_id(subscription.normalized_pair),
                }
            )
            ws_app.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "args": args,
                    }
                )
            )

        def on_message(_ws_app, raw: str) -> None:  # noqa: ANN001
            if not raw:
                return
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return
            if payload.get("event") in {"subscribe", "pong"}:
                return
            channel = str(((payload.get("arg") or {}) if isinstance(payload.get("arg"), dict) else {}).get("channel", ""))
            if channel == "ticker":
                event = _build_bitget_quote_event(payload, subscription)
                if event is not None:
                    self._publish(event)
            elif channel == "trade":
                for trade_event in _build_bitget_trade_events(payload, subscription):
                    self._publish_trade(trade_event)
            elif self._cfg.depth_enabled and channel.startswith("books"):
                depth_event = _build_bitget_depth_event(payload, subscription, depth_levels=self._cfg.depth_levels)
                if depth_event is not None:
                    self._publish_depth(depth_event)

        def on_error(_ws_app, err: Any) -> None:  # noqa: ANN001
            self._connected = False
            self._last_error = str(err)

        def on_close(_ws_app, _code: Any, _msg: Any) -> None:  # noqa: ANN001
            self._connected = False

        app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        app.run_forever(ping_interval=20, ping_timeout=10)


class _BinanceQuoteAdapter(_AdapterThread):
    def _run_ws(self) -> None:
        symbol = _binance_stream_symbol(self._subscription.normalized_pair)
        market_type = _connector_market_type(self._subscription.connector_name)
        if market_type == "perp":
            if self._cfg.depth_enabled:
                url = f"wss://fstream.binance.com/stream?streams={symbol}@bookTicker/{symbol}@depth20@100ms/{symbol}@trade"
            else:
                url = f"wss://fstream.binance.com/stream?streams={symbol}@bookTicker/{symbol}@trade"
        else:
            if self._cfg.depth_enabled:
                url = f"wss://stream.binance.com:9443/stream?streams={symbol}@bookTicker/{symbol}@depth20@100ms/{symbol}@trade"
            else:
                url = f"wss://stream.binance.com:9443/stream?streams={symbol}@bookTicker/{symbol}@trade"

        def on_open(_ws_app) -> None:  # noqa: ANN001
            self._connected = True

        def on_message(_ws_app, raw: str) -> None:  # noqa: ANN001
            if not raw:
                return
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            stream_name = str(payload.get("stream", "")) if isinstance(payload.get("stream"), str) else ""
            if not isinstance(data, dict):
                return
            if "bookTicker" in stream_name or data.get("e") == "bookTicker" or ("b" in data and "a" in data and "u" in data and "A" in data):
                event = _build_binance_quote_event(data, self._subscription)
                if event is not None:
                    self._publish(event)
            elif "trade" in stream_name or data.get("e") == "trade":
                trade_event = _build_binance_trade_event(data, self._subscription)
                if trade_event is not None:
                    self._publish_trade(trade_event)
            elif self._cfg.depth_enabled and ("depth" in stream_name or (isinstance(data.get("b"), list) and isinstance(data.get("a"), list))):
                depth_event = _build_binance_depth_event(data, self._subscription, depth_levels=self._cfg.depth_levels)
                if depth_event is not None:
                    self._publish_depth(depth_event)

        def on_error(_ws_app, err: Any) -> None:  # noqa: ANN001
            self._connected = False
            self._last_error = str(err)

        def on_close(_ws_app, _code: Any, _msg: Any) -> None:  # noqa: ANN001
            self._connected = False

        app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        app.run_forever(ping_interval=20, ping_timeout=10)


def _build_adapter(subscription: MarketSubscription, cfg: MarketDataServiceConfig, publisher: HBEventPublisher) -> _AdapterThread:
    connector = subscription.connector_name.strip().lower()
    if connector.startswith("bitget"):
        return _BitgetQuoteAdapter(subscription, cfg, publisher)
    if connector.startswith("binance"):
        return _BinanceQuoteAdapter(subscription, cfg, publisher)
    raise ValueError(f"unsupported connector for market_data_service: {subscription.connector_name}")


def _write_status(cfg: MarketDataServiceConfig, adapters: Iterable[_AdapterThread], redis_available: bool) -> None:
    cfg.status_dir.mkdir(parents=True, exist_ok=True)
    adapter_status = [adapter.status() for adapter in adapters]
    healthy_quotes = [
        status for status in adapter_status if status.get("quote_age_ms") is not None and int(status.get("quote_age_ms") or 0) <= cfg.status_max_sec * 1000
    ]
    payload = {
        "ts_ms": _now_ms(),
        "status": "ok" if redis_available and len(healthy_quotes) == len(adapter_status) else "degraded",
        "redis_available": redis_available,
        "subscriptions": adapter_status,
    }
    latest = cfg.status_dir / "latest.json"
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run() -> None:
    cfg = MarketDataServiceConfig()
    if not cfg.enabled:
        logger.info("market_data_service disabled")
        return
    if not cfg.subscriptions:
        raise RuntimeError("MARKET_DATA_SERVICE_ENABLED=true but MARKET_DATA_SERVICE_SUBSCRIPTIONS is empty")

    redis_cfg = RedisSettings()
    redis_client = RedisStreamClient(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        enabled=redis_cfg.enabled,
    )
    if not redis_client.enabled:
        raise RuntimeError("Redis stream client is disabled. Enable EXT_SIGNAL_RISK_ENABLED and Redis connectivity.")

    publisher = HBEventPublisher(redis_client, "market_data_service")
    adapters = [_build_adapter(subscription, cfg, publisher) for subscription in cfg.subscriptions]
    for adapter in adapters:
        adapter.start()

    try:
        while True:
            _write_status(cfg, adapters, publisher.available)
            time.sleep(5.0)
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("market_data_service stopping")
    finally:
        for adapter in adapters:
            adapter.stop()
        for adapter in adapters:
            adapter.join(timeout=3.0)
        _write_status(cfg, adapters, publisher.available)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish canonical market quotes from venue public feeds.")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
