"""ML Feature Service — live feature computation and prediction publishing.

Autonomous microservice that:
1. Seeds rolling 1m bar windows per pair from exchange API on startup
2. Subscribes to ``hb.market_trade.v1`` for live bar building
3. Falls back to ccxt polling if no trade stream within 2 minutes
4. Computes features on each bar close via the same pipeline used offline
5. Runs inference with models from the registry
6. Publishes ``MlFeatureEvent`` to ``hb.ml_features.v1``
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ml_feature_service")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
ML_PAIRS = [p.strip() for p in os.getenv("ML_PAIRS", "BTC-USDT").split(",") if p.strip()]
ML_MODEL_DIR = os.getenv("ML_MODEL_DIR", "data/ml/models")
ML_EXCHANGE = os.getenv("ML_EXCHANGE", "bitget")
ML_REFRESH_INTERVAL_S = int(os.getenv("ML_REFRESH_INTERVAL_S", "3600"))
ML_WARMUP_BARS = int(os.getenv("ML_WARMUP_BARS", "1440"))
ML_POLL_INTERVAL_S = int(os.getenv("ML_POLL_INTERVAL_S", "60"))
ML_SENTIMENT_POLL_S = int(os.getenv("ML_SENTIMENT_POLL_S", "300"))
ML_TRADE_TIMEOUT_S = int(os.getenv("ML_TRADE_TIMEOUT_S", "120"))

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
_raw_tfs = os.getenv("ML_TIMEFRAMES", "5m,15m,1h")
ML_TIMEFRAMES: list[str] = [t.strip() for t in _raw_tfs.split(",") if t.strip() in _TF_MINUTES]
if not ML_TIMEFRAMES:
    ML_TIMEFRAMES = ["5m", "15m", "1h"]

CONSUMER_GROUP = "hb_group_ml_features"
CONSUMER_NAME = "ml_feature_svc_1"

from controllers.ml import model_registry
from controllers.ml.feature_pipeline import compute_features
from services.ml_feature_service.bar_builder import BarBuilder
from services.ml_feature_service.pair_state import PairFeatureState


def _pair_to_ccxt_symbol(pair: str) -> str:
    """Convert 'BTC-USDT' to 'BTC/USDT:USDT' for ccxt perp."""
    parts = pair.split("-")
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    return pair


def _get_redis():
    """Create Redis connection."""
    try:
        import redis
        return redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            password=REDIS_PASSWORD, decode_responses=True,
            socket_timeout=5, socket_connect_timeout=5,
        )
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        return None


def _seed_pair(pair: str, exchange_id: str, bars: int = 1440) -> pd.DataFrame | None:
    """Fetch recent 1m candles from exchange API to seed rolling window."""
    try:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            logger.error("Unknown exchange: %s", exchange_id)
            return None
        exchange = exchange_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        symbol = _pair_to_ccxt_symbol(pair)

        all_bars: list[list] = []
        until_ms = int(time.time() * 1000)
        remaining = bars

        while remaining > 0:
            batch_size = min(remaining, 200)
            since_ms = until_ms - remaining * 60_000
            batch = exchange.fetch_ohlcv(symbol, timeframe="1m", since=since_ms, limit=batch_size)
            if not batch:
                break
            all_bars.extend(batch)
            remaining -= len(batch)
            if batch[-1][0] >= until_ms:
                break
            until_ms = batch[-1][0] + 60_000
            time.sleep(0.3)

        if not all_bars:
            return None

        seen: set[int] = set()
        unique = []
        for b in all_bars:
            ts = int(b[0])
            if ts not in seen:
                seen.add(ts)
                unique.append(b)
        unique.sort(key=lambda b: b[0])

        df = pd.DataFrame(unique, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        logger.info("Seeded %d candles for %s from %s", len(df), pair, exchange_id)
        return df
    except Exception as exc:
        logger.error("Seed failed for %s: %s", pair, exc)
        return None


def _poll_fresh_candles(pair: str, exchange_id: str) -> pd.DataFrame | None:
    """Fetch the latest 5 1m candles from exchange API (fallback mode)."""
    try:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        symbol = _pair_to_ccxt_symbol(pair)
        since_ms = int((time.time() - 300) * 1000)
        batch = exchange.fetch_ohlcv(symbol, timeframe="1m", since=since_ms, limit=5)
        if not batch:
            return None
        df = pd.DataFrame(batch, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        return df
    except Exception as exc:
        logger.warning("Fallback candle poll failed for %s: %s", pair, exc)
        return None


def _poll_sentiment(pair: str, exchange_id: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch latest funding rate and LS ratio from exchange."""
    funding_df = None
    ls_df = None
    try:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        symbol = _pair_to_ccxt_symbol(pair)

        if exchange.has.get("fetchFundingRateHistory"):
            since_ms = int((time.time() - 86400) * 1000)
            rates = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=100)
            if rates:
                funding_df = pd.DataFrame([
                    {"timestamp_ms": int(r["timestamp"]), "rate": float(r.get("fundingRate", 0))}
                    for r in rates if r.get("timestamp")
                ])

        if exchange.has.get("fetchLongShortRatioHistory"):
            since_ms = int((time.time() - 86400) * 1000)
            ls_data = exchange.fetch_long_short_ratio_history(symbol, timeframe="5m", since=since_ms, limit=100)
            if ls_data:
                ls_df = pd.DataFrame([
                    {
                        "timestamp_ms": int(r["timestamp"]),
                        "long_account_ratio": float(r.get("longAccount", 0)),
                        "short_account_ratio": float(r.get("shortAccount", 0)),
                        "long_short_ratio": float(r.get("longShortRatio", 0)),
                    }
                    for r in ls_data if r.get("timestamp")
                ])
    except Exception as exc:
        logger.warning("Sentiment poll failed for %s: %s", pair, exc)

    return funding_df, ls_df


def _load_models(model_dir: str, exchange: str, pairs: list[str]) -> dict[str, dict]:
    """Load all available models from the registry. Returns {pair: {model_type: model}}."""
    models: dict[str, dict] = {}
    for pair in pairs:
        pair_models: dict[str, Any] = {}
        for model_type in ["regime", "direction", "sizing"]:
            try:
                model = model_registry.load_model(model_dir, exchange, pair, model_type)
                meta = model_registry.load_metadata(model_dir, exchange, pair, model_type)
                pair_models[model_type] = {"model": model, "metadata": meta}
                logger.info("Loaded %s/%s/%s model", exchange, pair, model_type)
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.warning("Model load failed %s/%s/%s: %s", exchange, pair, model_type, exc)
        models[pair] = pair_models
    return models


def _run_inference(
    features_df: pd.DataFrame,
    pair_models: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, str]]:
    """Run all loaded models on the latest feature row."""
    predictions: dict[str, dict] = {}
    versions: dict[str, str] = {}

    if features_df.empty:
        return predictions, versions

    feature_row = features_df.iloc[[-1]]

    for model_type, entry in pair_models.items():
        model = entry["model"]
        meta = entry.get("metadata") or {}
        feature_cols = meta.get("feature_columns", [])

        if not feature_cols:
            continue

        available_cols = [c for c in feature_cols if c in feature_row.columns]
        if len(available_cols) < len(feature_cols) * 0.8:
            continue

        X = feature_row[available_cols].values
        try:
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X)[0]
                pred_class = int(model.predict(X)[0])
                predictions[model_type] = {
                    "class": pred_class,
                    "probabilities": {str(c): float(p) for c, p in zip(model.classes_, proba, strict=True)},
                    "confidence": float(max(proba)),
                }
            else:
                pred = float(model.predict(X)[0])
                predictions[model_type] = {"value": pred}
            versions[model_type] = str(meta.get("training_date", "unknown"))
        except Exception as exc:
            logger.warning("Inference failed for %s: %s", model_type, exc)

    return predictions, versions


def _publish_features(
    r: Any,
    exchange: str,
    pair: str,
    timestamp_ms: int,
    features: dict[str, float],
    predictions: dict[str, dict],
    model_versions: dict[str, str],
) -> None:
    """Publish MlFeatureEvent to the ML features stream."""
    try:
        from platform_lib.contracts.stream_names import ML_FEATURES_STREAM
    except ImportError:
        ML_FEATURES_STREAM = "hb.ml_features.v1"

    event = {
        "event_type": "ml_features",
        "producer": "ml_feature_service",
        "exchange": exchange,
        "trading_pair": pair,
        "timestamp_ms": timestamp_ms,
        "features": features,
        "predictions": predictions,
        "model_versions": model_versions,
    }
    try:
        r.xadd(ML_FEATURES_STREAM, {"payload": json.dumps(event, default=str)}, maxlen=50_000, approximate=True)
    except Exception as exc:
        logger.warning("Failed to publish ML features for %s: %s", pair, exc)


def main() -> None:
    """Entry point for the ML feature service."""
    logger.info(
        "Starting ML Feature Service (pairs=%s, exchange=%s, timeframes=%s)",
        ML_PAIRS, ML_EXCHANGE, ML_TIMEFRAMES,
    )

    # Initialize per-pair state
    pair_states: dict[str, PairFeatureState] = {}
    bar_builders: dict[str, BarBuilder] = {}
    for pair in ML_PAIRS:
        pair_states[pair] = PairFeatureState(pair, ML_EXCHANGE)
        bar_builders[pair] = BarBuilder(pair)

    # Seed from exchange API
    for pair in ML_PAIRS:
        seed_df = _seed_pair(pair, ML_EXCHANGE, ML_WARMUP_BARS)
        if seed_df is not None:
            pair_states[pair].seed_from_candles(seed_df)

    # Load models
    models = _load_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
    last_model_refresh = time.time()

    # Track which pairs are using fallback
    fallback_pairs: set[str] = set()
    pair_first_trade_ts: dict[str, float] = {}
    startup_ts = time.time()
    last_fallback_poll: dict[str, float] = {p: 0 for p in ML_PAIRS}
    last_sentiment_poll: dict[str, float] = {p: 0 for p in ML_PAIRS}

    r = _get_redis()
    if r is None:
        logger.error("Cannot connect to Redis. Exiting.")
        sys.exit(1)

    # Ensure consumer group exists
    try:
        from platform_lib.contracts.stream_names import MARKET_TRADE_STREAM
    except ImportError:
        MARKET_TRADE_STREAM = "hb.market_trade.v1"

    try:
        r.xgroup_create(MARKET_TRADE_STREAM, CONSUMER_GROUP, id="$", mkstream=True)
    except Exception:
        pass  # Group already exists

    last_trade_id = ">"

    logger.info("ML Feature Service ready. Entering main loop.")

    while True:
        now = time.time()

        # Periodic model refresh
        if now - last_model_refresh > ML_REFRESH_INTERVAL_S:
            models = _load_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
            last_model_refresh = now

        # Read from trade stream
        try:
            result = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {MARKET_TRADE_STREAM: last_trade_id},
                count=100, block=1000,
            )
        except Exception as exc:
            logger.warning("xreadgroup failed: %s", exc)
            time.sleep(1)
            continue

        if result:
            for _stream, entries in result:
                for entry_id, data in entries:
                    try:
                        raw = data.get("payload", "")
                        if not raw:
                            continue
                        payload = json.loads(raw)
                        if payload.get("event_type") != "market_trade":
                            continue
                        trade_pair_raw = payload.get("trading_pair", "")
                        trade_pair = trade_pair_raw.replace("/", "-").replace(":", "-").split("-")
                        trade_pair_key = f"{trade_pair[0]}-{trade_pair[1]}" if len(trade_pair) >= 2 else trade_pair_raw

                        if trade_pair_key not in bar_builders:
                            continue

                        if trade_pair_key not in pair_first_trade_ts:
                            pair_first_trade_ts[trade_pair_key] = now
                            logger.info("First trade received for %s", trade_pair_key)

                        if trade_pair_key in fallback_pairs:
                            fallback_pairs.discard(trade_pair_key)
                            logger.info("Switching %s from fallback to live bar building", trade_pair_key)

                        price = float(payload.get("price", 0))
                        size = float(payload.get("size", 0))
                        ts_ms = int(payload.get("timestamp_ms", payload.get("exchange_ts_ms", 0)))
                        if ts_ms == 0:
                            ts_ms = int(now * 1000)

                        completed_bar = bar_builders[trade_pair_key].on_trade(price, size, ts_ms)
                        if completed_bar is not None:
                            _on_bar_complete(pair_states[trade_pair_key], completed_bar, models.get(trade_pair_key, {}), r)

                        r.xack(MARKET_TRADE_STREAM, CONSUMER_GROUP, entry_id)
                    except Exception as exc:
                        logger.warning("Trade processing error: %s", exc)

        # Check for fallback activation (no trades within timeout)
        for pair in ML_PAIRS:
            if pair in pair_first_trade_ts:
                continue
            if now - startup_ts > ML_TRADE_TIMEOUT_S:
                if pair not in fallback_pairs:
                    fallback_pairs.add(pair)
                    logger.warning(
                        "%s: no trades within %ds of startup — activating exchange API fallback",
                        pair, ML_TRADE_TIMEOUT_S,
                    )

        # Fallback polling for pairs without trade stream
        for pair in fallback_pairs:
            if now - last_fallback_poll.get(pair, 0) < ML_POLL_INTERVAL_S:
                continue
            last_fallback_poll[pair] = now
            fresh_df = _poll_fresh_candles(pair, ML_EXCHANGE)
            if fresh_df is not None and not fresh_df.empty:
                state = pair_states[pair]
                existing_ts = {b.timestamp_ms for b in state._bars}
                for row in fresh_df.itertuples(index=False):
                    if int(row.timestamp_ms) not in existing_ts:
                        from services.ml_feature_service.bar_builder import Bar
                        bar = Bar(
                            timestamp_ms=int(row.timestamp_ms),
                            open=float(row.open), high=float(row.high),
                            low=float(row.low), close=float(row.close),
                            volume=float(row.volume), trade_count=0,
                        )
                        state.append_bar(bar)
                if state.is_warm:
                    _compute_and_publish(state, models.get(pair, {}), r)

        # Periodic sentiment polling
        for pair in ML_PAIRS:
            if now - last_sentiment_poll.get(pair, 0) < ML_SENTIMENT_POLL_S:
                continue
            last_sentiment_poll[pair] = now
            funding, ls = _poll_sentiment(pair, ML_EXCHANGE)
            pair_states[pair].update_sentiment_cache(funding, ls)


def _on_bar_complete(
    state: PairFeatureState,
    bar: Any,
    pair_models: dict,
    r: Any,
) -> None:
    """Handle a completed 1m bar: append, compute features, publish."""
    state.append_bar(bar)
    if not state.is_warm:
        return
    _compute_and_publish(state, pair_models, r)


def _compute_and_publish(
    state: PairFeatureState,
    pair_models: dict,
    r: Any,
) -> None:
    """Compute features from state and publish to Redis."""
    candles_1m = state.to_candles_df()
    if candles_1m.empty:
        return

    tf_candles: dict[str, pd.DataFrame | None] = {}
    for tf_label in ML_TIMEFRAMES:
        minutes = _TF_MINUTES.get(tf_label, 0)
        if minutes > 0:
            resampled = state.resample(minutes)
            tf_candles[tf_label] = resampled if not resampled.empty else None
        else:
            tf_candles[tf_label] = None

    features_df = compute_features(
        candles_1m=candles_1m,
        candles_5m=tf_candles.get("5m"),
        candles_15m=tf_candles.get("15m"),
        candles_1h=tf_candles.get("1h"),
        candles_4h=tf_candles.get("4h"),
        funding=state._cached_funding,
        ls_ratio=state._cached_ls_ratio,
    )

    if features_df.empty:
        return

    predictions, versions = _run_inference(features_df, pair_models)

    last_row = features_df.iloc[-1]
    feature_dict = {}
    for col in features_df.columns:
        if col == "timestamp_ms":
            continue
        val = last_row[col]
        if pd.notna(val):
            feature_dict[col] = float(val)

    ts_ms = int(last_row["timestamp_ms"])
    state._last_feature_ts_ms = ts_ms

    _publish_features(
        r, state.exchange, state.pair,
        ts_ms, feature_dict, predictions, versions,
    )


if __name__ == "__main__":
    main()
