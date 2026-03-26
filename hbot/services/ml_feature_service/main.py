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
ML_WARMUP_BARS = int(os.getenv("ML_WARMUP_BARS", "20160"))
HISTORICAL_DATA_DIR = os.getenv("HISTORICAL_DATA_DIR", "data/historical")
ML_POLL_INTERVAL_S = int(os.getenv("ML_POLL_INTERVAL_S", "60"))
ML_SENTIMENT_POLL_S = int(os.getenv("ML_SENTIMENT_POLL_S", "300"))
ML_TRADE_TIMEOUT_S = int(os.getenv("ML_TRADE_TIMEOUT_S", "120"))
ML_MARK_INDEX_REFRESH_S = int(os.getenv("ML_MARK_INDEX_REFRESH_S", "60"))
ML_SHADOW_MODE = os.getenv("ML_SHADOW_MODE", "false").lower() in ("1", "true", "yes")

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
_raw_tfs = os.getenv("ML_TIMEFRAMES", "1m,5m,15m,1h")
ML_TIMEFRAMES: list[str] = [t.strip() for t in _raw_tfs.split(",") if t.strip() in _TF_MINUTES]
if not ML_TIMEFRAMES:
    ML_TIMEFRAMES = ["1m", "5m", "15m", "1h"]

_raw_publish_res = os.getenv("ML_PUBLISH_RESOLUTIONS", "1m")
ML_PUBLISH_RESOLUTIONS: list[str] = [r.strip() for r in _raw_publish_res.split(",") if r.strip() in _TF_MINUTES]
if not ML_PUBLISH_RESOLUTIONS:
    ML_PUBLISH_RESOLUTIONS = ["1m"]

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


def _resolve_parquet_path(exchange: str, pair: str, resolution: str, base_dir: str):
    """Resolve the canonical parquet path without importing the backtesting package."""
    from pathlib import Path
    safe_pair = pair.replace("/", "-").replace(":", "-")
    return Path(base_dir) / exchange / safe_pair / resolution / "data.parquet"


def _seed_from_parquet(
    pair: str, exchange: str, base_dir: str, max_bars: int,
) -> pd.DataFrame | None:
    """Load the tail of the local parquet file for seeding.

    Returns up to *max_bars* rows as a DataFrame, or ``None`` on any error.
    """
    try:
        path = _resolve_parquet_path(exchange, pair, "1m", base_dir)
        if not path.exists():
            logger.debug("No parquet found for %s/%s at %s", exchange, pair, path)
            return None
        df = pd.read_parquet(path)
        if df.empty:
            return None
        df = df.sort_values("timestamp_ms").tail(max_bars).reset_index(drop=True)
        logger.info("Loaded %d bars from parquet for %s/%s", len(df), exchange, pair)
        return df
    except Exception as exc:
        logger.warning("Parquet seeding failed for %s/%s: %s", exchange, pair, exc)
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


def _fetch_mark_index(pair: str, exchange_id: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch mark and index price candles from exchange REST API."""
    mark_df = None
    index_df = None
    try:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            return None, None
        exchange = exchange_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        symbol = _pair_to_ccxt_symbol(pair)

        since_ms = int((time.time() - 3600) * 1000)
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", since=since_ms, limit=60)
            if ohlcv:
                mark_df = pd.DataFrame(ohlcv, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        except Exception:
            pass  # Justification: exchange REST is optional — continue without OHLCV series

        try:
            if hasattr(exchange, "fetch_mark_ohlcv"):
                mark_ohlcv = exchange.fetch_mark_ohlcv(symbol, timeframe="1m", since=since_ms, limit=60)
                if mark_ohlcv:
                    mark_df = pd.DataFrame(mark_ohlcv, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        except Exception:
            pass  # Justification: exchange REST is optional — continue without mark OHLCV

        try:
            if hasattr(exchange, "fetch_index_ohlcv"):
                index_ohlcv = exchange.fetch_index_ohlcv(symbol, timeframe="1m", since=since_ms, limit=60)
                if index_ohlcv:
                    index_df = pd.DataFrame(index_ohlcv, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        except Exception:
            pass  # Justification: exchange REST is optional — continue without index OHLCV

    except Exception as exc:
        logger.debug("Mark/index fetch failed for %s: %s", pair, exc)
    return mark_df, index_df


def _validate_seeding_against_manifest(pair_states: dict[str, PairFeatureState]) -> None:
    """Log coverage vs. manifest-declared requirements."""
    try:
        import yaml
        from pathlib import Path
        manifest_path = Path(__file__).resolve().parent.parent.parent / "config" / "data_requirements.yml"
        if not manifest_path.exists():
            logger.debug("No data requirements manifest found — skipping validation")
            return
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        ml_spec = manifest.get("consumers", {}).get("ml_feature_service", {})
        required = ml_spec.get("required_lookback_bars", 20160)
        for pair, state in pair_states.items():
            if state.bar_count >= required:
                logger.info(
                    "Manifest OK: %s seeded %d bars (required %d)",
                    pair, state.bar_count, required,
                )
            else:
                logger.warning(
                    "Manifest PARTIAL: %s seeded %d bars (required %d — features may have NaN)",
                    pair, state.bar_count, required,
                )
    except Exception as exc:
        logger.debug("Manifest validation skipped: %s", exc)


def _safe_hot_reload(
    state: PairFeatureState,
    base_dir: str,
    max_bars: int,
) -> None:
    """Rebuild the rolling window from parquet + retained live bars.

    Combines the parquet tail with current deque contents, deduplicates,
    sorts, and keeps the newest *max_bars* entries.
    """
    from services.ml_feature_service.bar_builder import Bar

    parquet_df = _seed_from_parquet(state.pair, state.exchange, base_dir, max_bars)
    if parquet_df is None or parquet_df.empty:
        return

    existing_bars = list(state._bars)
    existing_data = [
        {
            "timestamp_ms": b.timestamp_ms,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in existing_bars
    ]
    existing_df = pd.DataFrame(existing_data) if existing_data else pd.DataFrame()
    combined = pd.concat([parquet_df, existing_df], ignore_index=True) if not existing_df.empty else parquet_df
    combined = combined.drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms")
    combined = combined.tail(max_bars).reset_index(drop=True)

    state._bars.clear()
    loaded = state.seed_from_candles(combined)
    logger.info("Hot-reloaded %d bars from parquet for %s/%s", loaded, state.exchange, state.pair)


_MODEL_TYPES = ["regime", "direction", "sizing", "adverse"]


def _load_models(model_dir: str, exchange: str, pairs: list[str]) -> dict[str, dict]:
    """Load all available models from the registry.

    Models whose metadata contains ``deployment_ready: false`` are logged as
    gated-out and excluded from inference.
    """
    models: dict[str, dict] = {}
    for pair in pairs:
        pair_models: dict[str, Any] = {}
        for model_type in _MODEL_TYPES:
            try:
                meta = model_registry.load_metadata(model_dir, exchange, pair, model_type)
                if not meta.get("deployment_ready", False):
                    gate_msgs = meta.get("gate_results", [])
                    logger.warning(
                        "GATED-OUT %s/%s/%s — deployment_ready=false (%s)",
                        exchange, pair, model_type,
                        "; ".join(gate_msgs) if gate_msgs else "no gate info",
                    )
                    continue
                model = model_registry.load_model(model_dir, exchange, pair, model_type)
                pair_models[model_type] = {"model": model, "metadata": meta}
                logger.info("Loaded %s/%s/%s model (deployment_ready=true)", exchange, pair, model_type)
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.warning("Model load failed %s/%s/%s: %s", exchange, pair, model_type, exc)
        models[pair] = pair_models
    return models


def _load_shadow_models(model_dir: str, exchange: str, pairs: list[str]) -> dict[str, dict]:
    """Load shadow models (metadata has ``shadow: true``) for comparison."""
    shadow: dict[str, dict] = {}
    for pair in pairs:
        pair_shadow: dict[str, Any] = {}
        for model_type in _MODEL_TYPES:
            try:
                meta = model_registry.load_metadata(model_dir, exchange, pair, f"{model_type}_shadow")
                if meta.get("shadow", False):
                    model = model_registry.load_model(model_dir, exchange, pair, f"{model_type}_shadow")
                    pair_shadow[model_type] = {"model": model, "metadata": meta}
                    logger.info("Loaded shadow %s/%s/%s", exchange, pair, model_type)
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.debug("Shadow load skipped %s/%s/%s: %s", exchange, pair, model_type, exc)
        shadow[pair] = pair_shadow
    return shadow


def _infer_single(
    model: Any,
    meta: dict,
    feature_row: pd.DataFrame,
) -> dict | None:
    """Run inference for a single model on one feature row. Returns result dict or None."""
    feature_cols = meta.get("feature_columns", [])
    if not feature_cols:
        return None
    available_cols = [c for c in feature_cols if c in feature_row.columns]
    missing_cols = [c for c in feature_cols if c not in feature_row.columns]
    if len(available_cols) < len(feature_cols) * 0.8:
        return None
    # Build X with ALL expected columns in the correct order.
    # Missing columns are filled with NaN — LightGBM handles NaN natively
    # but requires the exact feature count from training.
    X = feature_row.reindex(columns=feature_cols)
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)[0]
            pred_class = int(model.predict(X)[0])
            return {
                "class": pred_class,
                "probabilities": {str(c): float(p) for c, p in zip(model.classes_, proba, strict=True)},
                "confidence": float(max(proba)),
                "deployment_ready": bool(meta.get("deployment_ready", False)),
                "missing_features": missing_cols,
            }
        else:
            pred = float(model.predict(X)[0])
            return {
                "value": pred,
                "deployment_ready": bool(meta.get("deployment_ready", False)),
                "missing_features": missing_cols,
            }
    except Exception as exc:
        logger.warning("Inference error: %s", exc)
        return None


def _run_inference(
    features_df: pd.DataFrame,
    pair_models: dict[str, dict],
    shadow_models: dict[str, dict] | None = None,
) -> tuple[dict[str, dict], dict[str, str], list[dict]]:
    """Run all loaded models on the latest feature row.

    Returns (predictions, versions, shadow_comparisons).
    """
    predictions: dict[str, dict] = {}
    versions: dict[str, str] = {}
    shadow_comparisons: list[dict] = []

    if features_df.empty:
        return predictions, versions, shadow_comparisons

    feature_row = features_df.iloc[[-1]]
    ts_ms = int(features_df.iloc[-1].get("timestamp_ms", 0))

    for model_type, entry in pair_models.items():
        result = _infer_single(entry["model"], entry.get("metadata", {}), feature_row)
        if result is not None:
            predictions[model_type] = result
            versions[model_type] = str(entry.get("metadata", {}).get("training_date", "unknown"))

    if shadow_models:
        for model_type, shadow_entry in shadow_models.items():
            shadow_result = _infer_single(shadow_entry["model"], shadow_entry.get("metadata", {}), feature_row)
            if shadow_result is None:
                continue
            active_result = predictions.get(model_type)
            if active_result is None:
                continue
            active_class = active_result.get("class", active_result.get("value"))
            shadow_class = shadow_result.get("class", shadow_result.get("value"))
            active_conf = active_result.get("confidence", 0)
            shadow_conf = shadow_result.get("confidence", 0)
            shadow_comparisons.append({
                "timestamp_ms": ts_ms,
                "model_type": model_type,
                "active_pred": active_class,
                "shadow_pred": shadow_class,
                "agreement": active_class == shadow_class,
                "active_confidence": active_conf,
                "shadow_confidence": shadow_conf,
                "confidence_delta": shadow_conf - active_conf,
            })

    return predictions, versions, shadow_comparisons


def _publish_features(
    r: Any,
    exchange: str,
    pair: str,
    timestamp_ms: int,
    features: dict[str, float],
    predictions: dict[str, dict],
    model_versions: dict[str, str],
    resolution: str = "1m",
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
        "resolution": resolution,
        "timestamp_ms": timestamp_ms,
        "features": features,
        "predictions": predictions,
        "model_versions": model_versions,
    }
    try:
        r.xadd(ML_FEATURES_STREAM, {"payload": json.dumps(event, default=str)}, maxlen=50_000, approximate=True)
    except Exception as exc:
        logger.warning("Failed to publish ML features for %s/%s: %s", pair, resolution, exc)


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

    # Seed from parquet (primary) with API bridge for gap, fallback to API-only
    for pair in ML_PAIRS:
        parquet_df = _seed_from_parquet(pair, ML_EXCHANGE, HISTORICAL_DATA_DIR, ML_WARMUP_BARS)
        if parquet_df is not None and not parquet_df.empty:
            last_parquet_ts = int(parquet_df["timestamp_ms"].max())
            bridge_since = last_parquet_ts - 5 * 60_000
            bridge_df = _seed_pair(pair, ML_EXCHANGE, bars=max(1, int((time.time() * 1000 - bridge_since) / 60_000)))
            if bridge_df is not None and not bridge_df.empty:
                combined = pd.concat([parquet_df, bridge_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms")
                combined = combined.tail(ML_WARMUP_BARS).reset_index(drop=True)
                seed_df = combined
            else:
                seed_df = parquet_df
            logger.info("Seeded %d bars from parquet+API bridge for %s", len(seed_df), pair)
        else:
            seed_df = _seed_pair(pair, ML_EXCHANGE, ML_WARMUP_BARS)
            if seed_df is not None:
                logger.info("Seeded %d bars from API only for %s (no parquet)", len(seed_df), pair)

        if seed_df is not None:
            pair_states[pair].seed_from_candles(seed_df)

    # Manifest-based startup validation
    _validate_seeding_against_manifest(pair_states)

    # Load models
    models = _load_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
    if ML_SHADOW_MODE:
        global _shadow_models
        _shadow_models = _load_shadow_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
        logger.info("Shadow mode ON — loaded %d shadow model sets", sum(1 for v in _shadow_models.values() if v))
    last_model_refresh = time.time()

    # Seed mark/index prices
    last_mark_index_poll: dict[str, float] = {p: 0 for p in ML_PAIRS}
    for pair in ML_PAIRS:
        try:
            mark_df, index_df = _fetch_mark_index(pair, ML_EXCHANGE)
            pair_states[pair].update_mark_index(mark_df, index_df)
            if mark_df is not None or index_df is not None:
                logger.info("Seeded mark/index prices for %s", pair)
        except Exception as exc:
            logger.debug("Mark/index seed skipped for %s: %s", pair, exc)

    # Track which pairs are using fallback
    fallback_pairs: set[str] = set()
    pair_first_trade_ts: dict[str, float] = {}
    startup_ts = time.time()
    last_fallback_poll: dict[str, float] = {p: 0 for p in ML_PAIRS}
    last_sentiment_poll: dict[str, float] = {p: 0 for p in ML_PAIRS}
    last_parquet_check: dict[str, float] = {p: 0 for p in ML_PAIRS}
    _pending_hot_reloads: set[str] = set()

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

    try:
        from platform_lib.contracts.stream_names import DATA_CATALOG_STREAM
    except ImportError:
        DATA_CATALOG_STREAM = "hb.data_catalog.v1"

    try:
        r.xgroup_create(DATA_CATALOG_STREAM, CONSUMER_GROUP, id="$", mkstream=True)
    except Exception:
        pass  # Justification: consumer group creation is idempotent — group may already exist

    last_trade_id = ">"

    logger.info("ML Feature Service ready. Entering main loop.")

    while True:
        now = time.time()

        # Periodic model refresh
        if now - last_model_refresh > ML_REFRESH_INTERVAL_S:
            models = _load_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
            if ML_SHADOW_MODE:
                _shadow_models = _load_shadow_models(ML_MODEL_DIR, ML_EXCHANGE, ML_PAIRS)
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
                        side = str(payload.get("side", "unknown"))

                        pair_states[trade_pair_key].append_trade(price, size, ts_ms, side)

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
                    last_bar = state._bars[-1] if state._bars else None
                    bar_ts_s = (last_bar.timestamp_ms / 1000) if last_bar else 0
                    for res_label in ML_PUBLISH_RESOLUTIONS:
                        res_minutes = _TF_MINUTES.get(res_label, 1)
                        if res_minutes == 1:
                            _compute_and_publish(state, models.get(pair, {}), r, resolution=res_label)
                        elif bar_ts_s > 0 and int(bar_ts_s) % (res_minutes * 60) == 0:
                            _compute_and_publish(state, models.get(pair, {}), r, resolution=res_label)

        # Data catalog stream: check for hot-reload triggers
        try:
            catalog_result = r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {DATA_CATALOG_STREAM: ">"},
                count=10, block=0,
            )
            if catalog_result:
                for _stream, entries in catalog_result:
                    for entry_id, data in entries:
                        try:
                            payload = json.loads(data.get("data", "{}"))
                            if payload.get("event_type") == "data_catalog_updated":
                                ev_pair = payload.get("pair", "")
                                ev_res = payload.get("resolution", "")
                                if ev_pair in pair_states and ev_res == "1m":
                                    _pending_hot_reloads.add(ev_pair)
                                    logger.info("Catalog update received for %s/%s — staging hot-reload", ev_pair, ev_res)
                            r.xack(DATA_CATALOG_STREAM, CONSUMER_GROUP, entry_id)
                        except Exception:
                            pass  # Justification: malformed catalog stream entry — skip and continue
        except Exception:
            pass  # Justification: Redis catalog read is non-critical — hot-reload retries on next loop

        # Execute pending hot-reloads
        from services.ml_feature_service.pair_state import ROLLING_WINDOW
        for pair in list(_pending_hot_reloads):
            _safe_hot_reload(pair_states[pair], HISTORICAL_DATA_DIR, ROLLING_WINDOW)
            _pending_hot_reloads.discard(pair)

        # Periodic parquet freshness check (fallback for missed Redis events)
        for pair in ML_PAIRS:
            if now - last_parquet_check.get(pair, 0) < ML_REFRESH_INTERVAL_S:
                continue
            last_parquet_check[pair] = now
            try:
                pq_path = _resolve_parquet_path(ML_EXCHANGE, pair, "1m", HISTORICAL_DATA_DIR)
                if pq_path.exists():
                    check_df = pd.read_parquet(pq_path, columns=["timestamp_ms"])
                    if not check_df.empty:
                        pq_last_ts = int(check_df["timestamp_ms"].max())
                        state = pair_states[pair]
                        current_bars = list(state._bars)
                        if current_bars:
                            deque_last_parquet_ts = max(
                                (b.timestamp_ms for b in current_bars),
                                default=0,
                            )
                            if pq_last_ts > deque_last_parquet_ts:
                                _safe_hot_reload(state, HISTORICAL_DATA_DIR, ROLLING_WINDOW)
            except Exception as exc:
                logger.debug("Parquet freshness check failed for %s: %s", pair, exc)

        # Periodic mark/index refresh
        for pair in ML_PAIRS:
            if now - last_mark_index_poll.get(pair, 0) < ML_MARK_INDEX_REFRESH_S:
                continue
            last_mark_index_poll[pair] = now
            try:
                mark_df, index_df = _fetch_mark_index(pair, ML_EXCHANGE)
                pair_states[pair].update_mark_index(mark_df, index_df)
            except Exception as exc:
                logger.debug("Mark/index refresh failed for %s: %s", pair, exc)

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
    """Handle a completed 1m bar: append, compute features, publish at each configured resolution."""
    state.append_bar(bar)
    if not state.is_warm:
        return
    bar_ts_ms = getattr(bar, "timestamp_ms", 0)
    bar_ts_s = bar_ts_ms / 1000 if bar_ts_ms > 0 else 0
    for res_label in ML_PUBLISH_RESOLUTIONS:
        res_minutes = _TF_MINUTES.get(res_label, 1)
        if res_minutes == 1:
            _compute_and_publish(state, pair_models, r, resolution=res_label)
        elif bar_ts_s > 0 and int(bar_ts_s) % (res_minutes * 60) == 0:
            _compute_and_publish(state, pair_models, r, resolution=res_label)


_last_published: dict[str, int] = {}


_shadow_models: dict[str, dict] = {}


def _compute_and_publish(
    state: PairFeatureState,
    pair_models: dict,
    r: Any,
    resolution: str = "1m",
) -> None:
    """Compute features from state and publish to Redis.

    Skips duplicate publishes when the bar timestamp has not advanced.
    """
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
        trades=state.trades_df(),
        funding=state._cached_funding,
        ls_ratio=state._cached_ls_ratio,
        mark_candles_1m=state._mark_candles,
        index_candles_1m=state._index_candles,
    )

    if features_df.empty:
        return

    last_row = features_df.iloc[-1]
    ts_ms = int(last_row["timestamp_ms"])

    dedup_key = f"{state.pair}:{resolution}"
    if _last_published.get(dedup_key) == ts_ms:
        return
    _last_published[dedup_key] = ts_ms

    pair_shadow = _shadow_models.get(state.pair, {}) if ML_SHADOW_MODE else {}
    predictions, versions, shadow_comps = _run_inference(features_df, pair_models, pair_shadow)

    if shadow_comps:
        for sc in shadow_comps:
            logger.info(
                "SHADOW %s/%s: agree=%s active=%s shadow=%s Δconf=%.4f",
                state.pair, sc["model_type"], sc["agreement"],
                sc["active_pred"], sc["shadow_pred"], sc["confidence_delta"],
            )

    feature_dict = {}
    for col in features_df.columns:
        if col == "timestamp_ms":
            continue
        val = last_row[col]
        if pd.notna(val):
            feature_dict[col] = float(val)

    state._last_feature_ts_ms = ts_ms

    _publish_features(
        r, state.exchange, state.pair,
        ts_ms, feature_dict, predictions, versions,
        resolution=resolution,
    )


if __name__ == "__main__":
    main()
