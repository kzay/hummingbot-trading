"""Realtime in-memory state container for the UI API.

Holds market snapshots, depth data, fills, paper events, positions, and
bot telemetry snapshots received from Redis streams.  Manages pub/sub
for SSE/WebSocket subscribers.
"""
from __future__ import annotations

import queue
import threading
from collections import defaultdict, deque
from typing import Any

from platform_lib.contracts.stream_names import (
    BOT_TELEMETRY_STREAM,
    MARKET_DATA_STREAM,
    MARKET_DEPTH_STREAM,
    MARKET_QUOTE_STREAM,
    ML_FEATURES_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
)
from services.realtime_ui_api._helpers import (
    RealtimeApiConfig,
    _candles_from_points,
    _normalize_pair,
    _now_ms,
    _safe_json,
    _state_key,
    _stream_ms,
    _to_float,
)

# Re-export for backward compatibility
__all__ = ["RealtimeState"]


class RealtimeState:
    def __init__(self, cfg: RealtimeApiConfig):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._market: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._depth: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._market_quote: dict[tuple[str, str], dict[str, Any]] = {}
        self._market_depth: dict[tuple[str, str], dict[str, Any]] = {}
        self._market_ts_ms: dict[tuple[str, str, str], int] = {}
        self._depth_ts_ms: dict[tuple[str, str, str], int] = {}
        self._market_quote_ts_ms: dict[tuple[str, str], int] = {}
        self._market_depth_ts_ms: dict[tuple[str, str], int] = {}
        self._fills_ts_ms: dict[tuple[str, str, str], int] = {}
        self._paper_events_ts_ms: dict[tuple[str, str, str], int] = {}
        self._fills: dict[tuple[str, str, str], deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(20, cfg.max_fills_per_key))
        )
        self._paper_events: dict[tuple[str, str, str], deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(20, cfg.max_events_per_key))
        )
        self._history: dict[tuple[str, str, str], deque[tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=max(100, cfg.max_history_points))
        )
        self._market_history: dict[tuple[str, str], deque[tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=max(100, cfg.max_history_points))
        )
        self._positions: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._positions_ts_ms: dict[tuple[str, str, str], int] = {}
        # Full bot_minute_snapshot payload keyed by (instance_name, controller_id, trading_pair).
        # This is the live source of truth for equity, PnL, fills_count, regime, state.
        self._bot_snapshot: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._bot_snapshot_ts_ms: dict[tuple[str, str, str], int] = {}
        self._ml_features: dict[tuple[str, str], dict[str, Any]] = {}
        self._ml_features_ts_ms: dict[tuple[str, str], int] = {}
        self._stream_watermark_ms: dict[str, int] = {}
        self._subscribers: list[tuple[queue.Queue[str], tuple[str, str, str]]] = []
        self._publish_seq = 0
        self._subscriber_drop_count = 0

    @staticmethod
    def _selection_dict(key: tuple[str, str, str]) -> dict[str, str]:
        return {
            "instance_name": str(key[0] or "").strip(),
            "controller_id": str(key[1] or "").strip(),
            "trading_pair": str(key[2] or "").strip(),
        }

    @staticmethod
    def _selection_from_event(event: dict[str, Any]) -> tuple[str, str, str]:
        event_key = event.get("key")
        if isinstance(event_key, dict):
            return (
                str(event_key.get("instance_name", "") or "").strip(),
                str(event_key.get("controller_id", "") or "").strip(),
                str(event_key.get("trading_pair", "") or "").strip(),
            )
        if isinstance(event_key, (list, tuple)) and len(event_key) >= 3:
            return (
                str(event_key[0] or "").strip(),
                str(event_key[1] or "").strip(),
                str(event_key[2] or "").strip(),
            )
        payload = event.get("event") if isinstance(event.get("event"), dict) else {}
        return _state_key(payload if isinstance(payload, dict) else {})

    @staticmethod
    def _subscriber_matches(
        subscriber_key: tuple[str, str, str],
        event_key: tuple[str, str, str],
    ) -> bool:
        sub_instance, sub_controller, sub_pair = subscriber_key
        ev_instance, ev_controller, ev_pair = event_key
        if sub_instance and ev_instance and sub_instance != ev_instance:
            return False
        if sub_controller and ev_controller and sub_controller != ev_controller:
            return False
        return not (sub_pair and ev_pair and _normalize_pair(sub_pair) != _normalize_pair(ev_pair))

    def _notify(self, event: dict[str, Any]) -> None:
        payload = _safe_json(event)
        event_key = self._selection_from_event(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for q, subscriber_key in subscribers:
            if not self._subscriber_matches(subscriber_key, event_key):
                continue
            try:
                q.put_nowait(payload)
            except queue.Full:
                with self._lock:
                    self._subscriber_drop_count += 1
                continue
            except Exception:
                with self._lock:
                    self._subscriber_drop_count += 1
                continue

    def register_subscriber(
        self,
        instance_name: str = "",
        controller_id: str = "",
        trading_pair: str = "",
    ) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=200)
        subscriber_key = (
            str(instance_name or "").strip(),
            str(controller_id or "").strip(),
            str(trading_pair or "").strip(),
        )
        with self._lock:
            self._subscribers.append((q, subscriber_key))
        return q

    def unregister_subscriber(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item[0] is not q]

    def process(self, stream: str, entry_id: str, payload: dict[str, Any]) -> None:
        ts_ms = _stream_ms(entry_id)
        key = _state_key(payload)
        pair_key = (
            str(payload.get("connector_name", "")).strip(),
            str(payload.get("trading_pair", "")).strip(),
        )
        event_type = str(payload.get("event_type", "")).strip()

        def _depth_mid(snapshot: dict[str, Any]) -> float | None:
            best_bid = _to_float(snapshot.get("best_bid"))
            best_ask = _to_float(snapshot.get("best_ask"))
            if best_bid is None or best_ask is None:
                bids = snapshot.get("bids", [])
                asks = snapshot.get("asks", [])
                if isinstance(bids, list) and bids:
                    best_bid = _to_float((bids[0] or {}).get("price"))
                if isinstance(asks, list) and asks:
                    best_ask = _to_float((asks[0] or {}).get("price"))
            if best_bid is None and best_ask is None:
                return None
            if best_bid is None:
                return best_ask
            if best_ask is None:
                return best_bid
            return (best_bid + best_ask) / 2.0

        with self._lock:
            self._stream_watermark_ms[stream] = max(ts_ms, self._stream_watermark_ms.get(stream, 0))
            if stream == MARKET_QUOTE_STREAM or event_type == "market_quote":
                self._market_quote[pair_key] = payload
                self._market_quote_ts_ms[pair_key] = ts_ms
                ltp = _to_float(payload.get("last_trade_price")) or _to_float(payload.get("mid_price")) or _depth_mid(payload)
                if ltp is not None and ltp > 0:
                    self._market_history[pair_key].append((ts_ms, ltp))
            elif stream == MARKET_DATA_STREAM or event_type == "market_snapshot":
                self._market[key] = payload
                self._market_ts_ms[key] = ts_ms
                ltp = _to_float(payload.get("last_trade_price")) or _to_float(payload.get("mid_price")) or _depth_mid(payload)
                if ltp is not None and ltp > 0:
                    self._history[key].append((ts_ms, ltp))
            elif stream == MARKET_DEPTH_STREAM or event_type == "market_depth_snapshot":
                mid = _depth_mid(payload)
                if pair_key[0] and (not key[0] and not key[1]):
                    self._market_depth[pair_key] = payload
                    self._market_depth_ts_ms[pair_key] = ts_ms
                    if mid is not None and mid > 0:
                        self._market_history[pair_key].append((ts_ms, mid))
                else:
                    self._depth[key] = payload
                    self._depth_ts_ms[key] = ts_ms
                    if mid is not None and mid > 0:
                        self._history[key].append((ts_ms, mid))
            elif stream == BOT_TELEMETRY_STREAM and event_type == "bot_minute_snapshot":
                # Store the full snapshot â€” equity, PnL, fills_count, state, regime etc.
                # are all authoritative live data from the bot/paper-engine and must be
                # preferred over CSV artifacts.
                self._bot_snapshot[key] = payload
                self._bot_snapshot_ts_ms[key] = ts_ms
                position_data = payload.get("position")
                if isinstance(position_data, dict) and position_data:
                    self._positions[key] = position_data
                    self._positions_ts_ms[key] = ts_ms
            elif stream == ML_FEATURES_STREAM and event_type == "ml_features":
                self._ml_features[pair_key] = payload
                self._ml_features_ts_ms[pair_key] = ts_ms
            elif stream == BOT_TELEMETRY_STREAM and event_type == "bot_fill":
                self._fills[key].append(payload)
                self._fills_ts_ms[key] = ts_ms
            elif stream == PAPER_EXCHANGE_EVENT_STREAM:
                self._paper_events[key].append(payload)
                self._paper_events_ts_ms[key] = ts_ms
            self._publish_seq += 1
            seq = self._publish_seq
        selection = self._selection_dict(key)
        self._notify(
            {
                "seq": seq,
                "stream": stream,
                "event_type": event_type,
                "instance_name": selection["instance_name"],
                "controller_id": selection["controller_id"],
                "trading_pair": selection["trading_pair"],
                "key": selection,
                "event": payload,
                "ts_ms": ts_ms,
            }
        )

    def newest_stream_age_ms(self) -> int | None:
        with self._lock:
            if not self._stream_watermark_ms:
                return None
            latest = max(self._stream_watermark_ms.values())
        return max(0, _now_ms() - latest)

    def selected_stream_age_ms(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> int | None:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            candidate_ts: list[int] = []
            connector_name = ""
            connector_candidates: list[tuple[int, str]] = []
            for key, ts_ms in self._market_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
                    connector = str((self._market.get(key, {}) or {}).get("connector_name", "")).strip()
                    if connector:
                        connector_candidates.append((ts_ms, connector))
            for key, ts_ms in self._depth_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
                    connector = str((self._depth.get(key, {}) or {}).get("connector_name", "")).strip()
                    if connector:
                        connector_candidates.append((ts_ms, connector))
            for key, ts_ms in self._fills_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            for key, ts_ms in self._paper_events_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            for key, ts_ms in self._bot_snapshot_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            for key, ts_ms in self._positions_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            if connector_candidates:
                connector_name = max(connector_candidates, key=lambda item: item[0])[1]
            if requested_pair_norm:
                if connector_name:
                    pair_key = next(
                        (key for key in self._market_quote_ts_ms if key[0] == connector_name and requested_pair_norm == _normalize_pair(key[1])),
                        None,
                    )
                    if pair_key is not None:
                        candidate_ts.append(int(self._market_quote_ts_ms.get(pair_key, 0) or 0))
                    depth_pair_key = next(
                        (key for key in self._market_depth_ts_ms if key[0] == connector_name and requested_pair_norm == _normalize_pair(key[1])),
                        None,
                    )
                    if depth_pair_key is not None:
                        candidate_ts.append(int(self._market_depth_ts_ms.get(depth_pair_key, 0) or 0))
                else:
                    candidate_ts.extend(
                        int(ts_ms)
                        for key, ts_ms in self._market_quote_ts_ms.items()
                        if requested_pair_norm == _normalize_pair(key[1]) and ts_ms > 0
                    )
                    candidate_ts.extend(
                        int(ts_ms)
                        for key, ts_ms in self._market_depth_ts_ms.items()
                        if requested_pair_norm == _normalize_pair(key[1]) and ts_ms > 0
                    )
            latest = max(candidate_ts) if candidate_ts else None
        return None if latest is None else max(0, _now_ms() - latest)

    def resolve_connector_name(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> str:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            market_keys = [k for k in self._market if _match(k)]
            if market_keys:
                freshest_market_key = max(market_keys, key=lambda key: int(self._market_ts_ms.get(key, 0) or 0))
                connector_name = str((self._market.get(freshest_market_key, {}) or {}).get("connector_name", "")).strip()
                if connector_name:
                    return connector_name
            depth_keys = [k for k in self._depth if _match(k)]
            if depth_keys:
                freshest_depth_key = max(depth_keys, key=lambda key: int(self._depth_ts_ms.get(key, 0) or 0))
                connector_name = str((self._depth.get(freshest_depth_key, {}) or {}).get("connector_name", "")).strip()
                if connector_name:
                    return connector_name
            pair_matches = [k for k in self._market_quote if (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))]
            if pair_matches:
                freshest_pair_key = max(pair_matches, key=lambda key: int(self._market_quote_ts_ms.get(key, 0) or 0))
                return str(freshest_pair_key[0] or "").strip()
            depth_pair_matches = [k for k in self._market_depth if (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))]
            if depth_pair_matches:
                freshest_depth_pair_key = max(depth_pair_matches, key=lambda key: int(self._market_depth_ts_ms.get(key, 0) or 0))
                return str(freshest_depth_pair_key[0] or "").strip()
        return ""

    def resolve_trading_pair(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> str:
        requested_pair = str(trading_pair or "").strip()
        if requested_pair:
            return requested_pair

        def _match(key: tuple[str, str, str]) -> bool:
            i, c, _p = key
            return (not instance_name or instance_name == i) and (not controller_id or controller_id == c)

        with self._lock:
            matched_keys_with_ts: list[tuple[int, tuple[str, str, str]]] = []
            matched_keys_with_ts.extend((int(self._market_ts_ms.get(k, 0) or 0), k) for k in self._market if _match(k))
            matched_keys_with_ts.extend((int(self._depth_ts_ms.get(k, 0) or 0), k) for k in self._depth if _match(k))
            matched_keys_with_ts.extend((int(self._fills_ts_ms.get(k, 0) or 0), k) for k in self._fills if _match(k))
            matched_keys_with_ts.extend((int(self._paper_events_ts_ms.get(k, 0) or 0), k) for k in self._paper_events if _match(k))
            # bot_minute_snapshot telemetry carries authoritative instance/pair information;
            # check it here so that instances whose market data is not bot-tagged
            # (e.g. published by the shared market-data-service) can still be resolved.
            matched_keys_with_ts.extend(
                (int(self._bot_snapshot_ts_ms.get(k, 0) or 0), k)
                for k in self._bot_snapshot
                if _match(k) and str(k[2] or "").strip()
            )
            if matched_keys_with_ts:
                freshest_key = max(matched_keys_with_ts, key=lambda item: item[0])[1]
                if str(freshest_key[2] or "").strip():
                    return str(freshest_key[2] or "").strip()
                market_pair = str((self._market.get(freshest_key, {}) or {}).get("trading_pair", "")).strip()
                if market_pair:
                    return market_pair
                depth_pair = str((self._depth.get(freshest_key, {}) or {}).get("trading_pair", "")).strip()
                if depth_pair:
                    return depth_pair
        return ""

    def instance_names(self) -> list[str]:
        with self._lock:
            names = {
                key[0]
                for key in (
                    list(self._market.keys())
                    + list(self._depth.keys())
                    + list(self._fills.keys())
                    + list(self._paper_events.keys())
                )
                if key[0]
            }
        return sorted(names, key=lambda value: value.lower())

    def _resolve_pair_from_bot_snapshot(self, instance_name: str = "", controller_id: str = "") -> str:
        """Resolve trading pair from bot_minute_snapshot when no instance-specific
        market data exists (e.g. bots that rely on shared market-data-service)."""
        for k, snap in self._bot_snapshot.items():
            i, c, p = k
            if instance_name and i and instance_name != i:
                continue
            if controller_id and c and controller_id != c:
                continue
            pair = str(p or "").strip()
            if pair:
                return pair
            pair = str((snap or {}).get("trading_pair", "")).strip()
            if pair:
                return pair
        return ""

    def get_state(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> dict[str, Any]:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            matched_keys_with_ts: list[tuple[int, tuple[str, str, str]]] = []
            matched_keys_with_ts.extend((int(self._market_ts_ms.get(k, 0) or 0), k) for k in self._market if _match(k))
            matched_keys_with_ts.extend((int(self._depth_ts_ms.get(k, 0) or 0), k) for k in self._depth if _match(k))
            matched_keys_with_ts.extend((int(self._fills_ts_ms.get(k, 0) or 0), k) for k in self._fills if _match(k))
            matched_keys_with_ts.extend((int(self._paper_events_ts_ms.get(k, 0) or 0), k) for k in self._paper_events if _match(k))
            matched_keys_with_ts.extend((int(self._positions_ts_ms.get(k, 0) or 0), k) for k in self._positions if _match(k))
            key = max(matched_keys_with_ts, key=lambda item: item[0])[1] if matched_keys_with_ts else ("", "", "")
            telemetry_market = self._market.get(key, {})
            telemetry_depth = self._depth.get(key, {})
            resolved_trading_pair = str(
                trading_pair or key[2] or telemetry_market.get("trading_pair") or telemetry_depth.get("trading_pair") or ""
            ).strip()
            if not resolved_trading_pair:
                resolved_trading_pair = self._resolve_pair_from_bot_snapshot(instance_name, controller_id)
            resolved_pair_norm = _normalize_pair(resolved_trading_pair)

            def _related_key(candidate: tuple[str, str, str]) -> bool:
                i, c, p = candidate
                if instance_name and i and instance_name != i:
                    return False
                if controller_id and c and controller_id != c:
                    return False
                return not (resolved_pair_norm and resolved_pair_norm != _normalize_pair(p))

            fills = [
                fill
                for related_key in self._fills
                if _related_key(related_key)
                for fill in list(self._fills.get(related_key, deque()))
            ]
            events = [
                event
                for related_key in self._paper_events
                if _related_key(related_key)
                for event in list(self._paper_events.get(related_key, deque()))
            ]
            connector_name = str(telemetry_market.get("connector_name") or telemetry_depth.get("connector_name") or "").strip()
            effective_pair_norm = resolved_pair_norm or requested_pair_norm
            if not connector_name and effective_pair_norm:
                pair_matches = [k for k in self._market_quote if effective_pair_norm == _normalize_pair(k[1])]
                if pair_matches:
                    freshest_pair_key = max(pair_matches, key=lambda pair_key: int(self._market_quote_ts_ms.get(pair_key, 0) or 0))
                    connector_name = str(freshest_pair_key[0] or "").strip()
            market = telemetry_market
            depth = telemetry_depth
            if connector_name and effective_pair_norm:
                market_pair_matches = [
                    k for k in self._market_quote
                    if k[0] == connector_name and effective_pair_norm == _normalize_pair(k[1])
                ]
                if market_pair_matches:
                    freshest_market_pair_key = max(
                        market_pair_matches, key=lambda pair_key: int(self._market_quote_ts_ms.get(pair_key, 0) or 0)
                    )
                    market = self._market_quote.get(freshest_market_pair_key, {}) or telemetry_market
                depth_pair_matches = [
                    k for k in self._market_depth
                    if k[0] == connector_name and effective_pair_norm == _normalize_pair(k[1])
                ]
                if depth_pair_matches:
                    freshest_depth_pair_key = max(
                        depth_pair_matches, key=lambda pair_key: int(self._market_depth_ts_ms.get(pair_key, 0) or 0)
                    )
                    depth = self._market_depth.get(freshest_depth_pair_key, {}) or telemetry_depth
            position = {}
            for related_key in self._positions:
                if _related_key(related_key):
                    candidate = self._positions.get(related_key, {})
                    if candidate:
                        position = candidate
                        break
            ml_features: dict[str, Any] = {}
            if effective_pair_norm:
                for ml_key, ml_payload in self._ml_features.items():
                    if effective_pair_norm == _normalize_pair(ml_key[1]):
                        ml_features = ml_payload
                        break
            if not ml_features and len(self._ml_features) == 1:
                ml_features = next(iter(self._ml_features.values()))
        return {
            "key": {
                "instance_name": key[0] or instance_name,
                "controller_id": key[1] or controller_id,
                "trading_pair": key[2] or resolved_trading_pair,
            },
            "connector_name": connector_name,
            "market": market,
            "bot_market": telemetry_market,
            "depth": depth,
            "fills": fills,
            "fills_total": len(fills),
            "paper_events": events,
            "position": position,
            "ml_features": ml_features,
        }

    def get_bot_snapshot(self, instance_name: str = "") -> dict[str, Any] | None:
        """Return the most recent live bot_minute_snapshot for *instance_name*.

        This is the authoritative live source for equity, realised PnL,
        fills_count_today, regime and controller state â€” all published directly
        by the bot from its in-memory paper-engine state.  CSV files are only
        the on-disk audit trail and should be used as a fallback when this
        returns ``None``.
        """
        with self._lock:
            best_ts: int = -1
            best: dict[str, Any] | None = None
            for key, snap in self._bot_snapshot.items():
                i, _c, _p = key
                if instance_name and i and instance_name != i:
                    continue
                ts = int(self._bot_snapshot_ts_ms.get(key, 0) or 0)
                if ts > best_ts:
                    best_ts = ts
                    best = snap
            return best

    def get_candles(
        self,
        instance_name: str = "",
        controller_id: str = "",
        trading_pair: str = "",
        timeframe_s: int = 60,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        resolved_trading_pair = self.resolve_trading_pair(instance_name, controller_id, trading_pair)
        requested_pair_norm = _normalize_pair(resolved_trading_pair)

        def _match(key: tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        connector_name = self.resolve_connector_name(instance_name, controller_id, resolved_trading_pair)
        with self._lock:
            pair_points = []
            if connector_name:
                pair_matches = [
                    k for k in self._market_history
                    if k[0] == connector_name and (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))
                ]
                # When the pair is not resolved we must not pick an arbitrary key from
                # _market_history — doing so causes BTC/ETH candle mixing when multiple
                # symbols are tracked.  Only proceed when the pair is explicit OR there is
                # exactly one candidate (unambiguous).
                if pair_matches and (requested_pair_norm or len(pair_matches) == 1):
                    freshest_pair_key = max(
                        pair_matches,
                        key=lambda pk: max(
                            int(self._market_quote_ts_ms.get(pk, 0) or 0),
                            int(self._market_depth_ts_ms.get(pk, 0) or 0),
                        ),
                    )
                    pair_points = list(self._market_history.get(freshest_pair_key, deque()))
            if pair_points:
                return _candles_from_points(pair_points, timeframe_s=timeframe_s, limit=limit)
            keys = [k for k in self._history if _match(k)]
            if not keys:
                return []
            points = list(self._history[keys[-1]])
        return _candles_from_points(points, timeframe_s=timeframe_s, limit=limit)

    def get_connector_candles(
        self,
        connector_name: str,
        trading_pair: str,
        timeframe_s: int = 60,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        requested_pair_norm = _normalize_pair(trading_pair)
        connector_name = str(connector_name or "").strip()
        if not connector_name or not requested_pair_norm:
            return []
        with self._lock:
            pair_matches = [
                key for key in self._market_history
                if key[0] == connector_name and requested_pair_norm == _normalize_pair(key[1])
            ]
            if not pair_matches:
                return []
            freshest_pair_key = max(
                pair_matches,
                key=lambda pair_key: max(
                    int(self._market_quote_ts_ms.get(pair_key, 0) or 0),
                    int(self._market_depth_ts_ms.get(pair_key, 0) or 0),
                ),
            )
            points = list(self._market_history.get(freshest_pair_key, deque()))
        return _candles_from_points(points, timeframe_s=timeframe_s, limit=limit)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "market_keys": len(self._market),
                "depth_keys": len(self._depth),
                "market_quote_keys": len(self._market_quote),
                "market_depth_keys": len(self._market_depth),
                "fills_keys": len(self._fills),
                "paper_event_keys": len(self._paper_events),
                "subscribers": len(self._subscribers),
                "subscriber_drops": int(self._subscriber_drop_count or 0),
            }
