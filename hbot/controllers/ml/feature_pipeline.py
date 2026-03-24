"""Strategy-agnostic feature computation for the ML pipeline.

All functions are pure — they accept pandas DataFrames (float64) and return
DataFrames.  The same code is used in offline research and the live
ml-feature-service.  No imports from controllers/bots/*, controllers/epp_*,
controllers/shared_runtime*, or services/signal_service/.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from controllers.ml import _indicators as ind

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_features(
    candles_1m: pd.DataFrame,
    candles_5m: pd.DataFrame | None = None,
    candles_15m: pd.DataFrame | None = None,
    candles_1h: pd.DataFrame | None = None,
    candles_4h: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    funding: pd.DataFrame | None = None,
    ls_ratio: pd.DataFrame | None = None,
    mark_candles_1m: pd.DataFrame | None = None,
    index_candles_1m: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute all ML features aligned to 1m candle timestamps.

    Parameters
    ----------
    candles_1m : DataFrame
        Required. Columns: timestamp_ms, open, high, low, close, volume.
    candles_5m, candles_15m, candles_1h, candles_4h : DataFrame, optional
        Higher-timeframe candles. Same column schema.
    trades : DataFrame, optional
        Columns: timestamp_ms, side, price, size.
    funding : DataFrame, optional
        Columns: timestamp_ms, rate.
    ls_ratio : DataFrame, optional
        Columns: timestamp_ms, long_account_ratio, short_account_ratio,
        long_short_ratio.
    mark_candles_1m, index_candles_1m : DataFrame, optional
        Mark/index price OHLCV for basis computation.

    Returns
    -------
    DataFrame
        Rows aligned to ``candles_1m.timestamp_ms``, feature columns are
        float64.  Leading NaN rows correspond to indicator warmup.
    """
    ts = candles_1m[["timestamp_ms"]].copy()

    parts = [
        compute_price_features(candles_1m, candles_5m, candles_15m, candles_1h, candles_4h),
        compute_volatility_features(candles_1m),
        compute_microstructure_features(candles_1m, trades),
        compute_sentiment_features(candles_1m, funding, ls_ratio, mark_candles_1m, index_candles_1m),
        compute_time_features(candles_1m["timestamp_ms"]),
    ]

    result = pd.concat([ts] + parts, axis=1)
    return result


# ---------------------------------------------------------------------------
# Price features
# ---------------------------------------------------------------------------


def compute_price_features(
    candles_1m: pd.DataFrame,
    candles_5m: pd.DataFrame | None = None,
    candles_15m: pd.DataFrame | None = None,
    candles_1h: pd.DataFrame | None = None,
    candles_4h: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Multi-timeframe price features."""
    out: dict[str, pd.Series] = {}
    tf_map = {"1m": candles_1m, "5m": candles_5m, "15m": candles_15m, "1h": candles_1h, "4h": candles_4h}
    n = len(candles_1m)

    for tf_label, df in tf_map.items():
        if df is None:
            for col in [
                f"return_{tf_label}", f"atr_{tf_label}", f"close_in_range_{tf_label}",
                f"body_ratio_{tf_label}",
            ]:
                out[col] = pd.Series(np.nan, index=range(n))
            continue

        close = df["close"].reset_index(drop=True)
        high = df["high"].reset_index(drop=True)
        low = df["low"].reset_index(drop=True)
        opn = df["open"].reset_index(drop=True)

        # If higher TF, reindex to 1m length with forward fill
        if len(df) != n:
            close = close.reindex(range(n), method="ffill")
            high = high.reindex(range(n), method="ffill")
            low = low.reindex(range(n), method="ffill")
            opn = opn.reindex(range(n), method="ffill")

        out[f"return_{tf_label}"] = close.pct_change()
        out[f"atr_{tf_label}"] = ind.atr(high, low, close, 14)

        bar_range = high - low
        out[f"close_in_range_{tf_label}"] = np.where(
            bar_range > 0, (close - low) / bar_range, 0.5,
        )
        out[f"body_ratio_{tf_label}"] = np.where(
            bar_range > 0, (close - opn).abs() / bar_range, 0.0,
        )

    # Cross-timeframe ATR ratios (dynamic: all provided higher TFs vs 1m)
    atr_1m = out.get("atr_1m")
    higher_tfs = [tf for tf in tf_map if tf != "1m" and tf_map[tf] is not None]
    if atr_1m is not None:
        for tf in higher_tfs:
            key = f"atr_{tf}"
            if key in out and not out[key].isna().all():
                out[f"atr_ratio_{tf}_1m"] = out[key] / atr_1m.replace(0, np.nan)
            else:
                out[f"atr_ratio_{tf}_1m"] = pd.Series(np.nan, index=range(n))

    # Trend alignment (1m vs 1h always present for backward compat)
    ret_1m = out.get("return_1m", pd.Series(np.nan, index=range(n)))
    ret_1h = out.get("return_1h", pd.Series(np.nan, index=range(n)))
    out["trend_alignment_1m_1h"] = np.sign(ret_1m) * np.sign(ret_1h)
    for tf in higher_tfs:
        if tf == "1h":
            continue
        ret_tf = out.get(f"return_{tf}", pd.Series(np.nan, index=range(n)))
        out[f"trend_alignment_1m_{tf}"] = np.sign(ret_1m) * np.sign(ret_tf)

    # Bollinger band position (1m, period=20)
    close_1m = candles_1m["close"].reset_index(drop=True)
    lower, basis, upper = ind.bollinger_bands(close_1m, 20, 2.0)
    bb_width = upper - lower
    out["bb_position_1m"] = np.where(
        bb_width > 0, (close_1m - lower) / bb_width, 0.5,
    )

    # RSI and ADX (1m)
    out["rsi_1m"] = ind.rsi(close_1m, 14)
    out["adx_1m"] = ind.adx(
        candles_1m["high"].reset_index(drop=True),
        candles_1m["low"].reset_index(drop=True),
        close_1m,
        14,
    )

    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Volatility features
# ---------------------------------------------------------------------------


def compute_volatility_features(candles_1m: pd.DataFrame) -> pd.DataFrame:
    """Volatility structure features from 1m candles."""
    close = candles_1m["close"].reset_index(drop=True)
    high = candles_1m["high"].reset_index(drop=True)
    low = candles_1m["low"].reset_index(drop=True)
    out: dict[str, pd.Series] = {}

    log_ret = np.log(close / close.shift(1))

    # Realized vol at different windows
    for window, label in [(15, "15m"), (60, "1h"), (240, "4h")]:
        out[f"realized_vol_{label}"] = log_ret.rolling(window, min_periods=window).std()

    # Parkinson volatility (uses high/low)
    hl_ratio = np.log(high / low)
    out["parkinson_vol"] = (hl_ratio ** 2).rolling(60, min_periods=60).mean().apply(
        lambda x: np.sqrt(x / (4.0 * np.log(2.0))) if not np.isnan(x) else np.nan
    )

    # Garman-Klass volatility
    opn = candles_1m["open"].reset_index(drop=True)
    gk = 0.5 * (np.log(high / low)) ** 2 - (2.0 * np.log(2.0) - 1.0) * (np.log(close / opn)) ** 2
    out["garman_klass_vol"] = gk.rolling(60, min_periods=60).mean().apply(
        lambda x: np.sqrt(x) if not np.isnan(x) and x >= 0 else np.nan
    )

    # Vol-of-vol
    rv_1h = out["realized_vol_1h"]
    out["vol_of_vol"] = rv_1h.rolling(60, min_periods=60).std()

    # ATR percentile vs 24h and 7d
    atr_vals = ind.atr(high, low, close, 14)
    out["atr_pctl_24h"] = atr_vals.rolling(1440, min_periods=60).rank(pct=True)
    out["atr_pctl_7d"] = atr_vals.rolling(10080, min_periods=1440).rank(pct=True)

    # Range expansion ratio
    bar_range = high - low
    median_range = bar_range.rolling(60, min_periods=60).median()
    out["range_expansion"] = bar_range / median_range.replace(0, np.nan)

    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Microstructure features
# ---------------------------------------------------------------------------


def compute_microstructure_features(
    candles_1m: pd.DataFrame,
    trades: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Order-flow features aligned to 1m timestamps."""
    n = len(candles_1m)
    nan_series = pd.Series(np.nan, index=range(n))
    out: dict[str, pd.Series] = {}

    if trades is None or trades.empty:
        for col in ["cvd", "flow_imbalance", "large_trade_ratio", "trade_arrival_rate", "vwap_deviation"]:
            out[col] = nan_series
        return pd.DataFrame(out)

    ts_1m = candles_1m["timestamp_ms"].reset_index(drop=True)
    close_1m = candles_1m["close"].reset_index(drop=True)

    trades = trades.copy()
    trades["signed_volume"] = np.where(
        trades["side"] == "buy", trades["size"], -trades["size"],
    )
    trades["notional"] = trades["price"] * trades["size"]
    trades["minute_bin"] = trades["timestamp_ms"] // 60_000 * 60_000

    agg = trades.groupby("minute_bin").agg(
        buy_volume=("size", lambda s: s[trades.loc[s.index, "side"] == "buy"].sum()),
        total_volume=("size", "sum"),
        cvd=("signed_volume", "sum"),
        trade_count=("size", "count"),
        vwap_notional=("notional", "sum"),
        median_size=("size", "median"),
    ).reset_index()
    agg["vwap"] = np.where(
        agg["total_volume"] > 0, agg["vwap_notional"] / agg["total_volume"], np.nan,
    )

    # Compute large trade ratio per minute
    large_threshold = trades.groupby("minute_bin")["size"].transform(
        lambda s: s.rolling(len(s), min_periods=1).median() * 2.0
    )
    trades["is_large"] = trades["size"] > large_threshold
    large_agg = trades.groupby("minute_bin").agg(
        large_volume=("size", lambda s: s[trades.loc[s.index, "is_large"]].sum()),
    ).reset_index()

    merged = agg.merge(large_agg, on="minute_bin", how="left")

    # Align to 1m candle timestamps
    aligned = pd.merge_asof(
        ts_1m.to_frame("timestamp_ms").reset_index(drop=True),
        merged.rename(columns={"minute_bin": "timestamp_ms"}),
        on="timestamp_ms",
        direction="backward",
        tolerance=60_000,
    )

    out["cvd"] = aligned["cvd"].cumsum().reset_index(drop=True)
    out["flow_imbalance"] = np.where(
        aligned["total_volume"] > 0,
        aligned["buy_volume"] / aligned["total_volume"],
        0.5,
    )
    out["flow_imbalance"] = pd.Series(out["flow_imbalance"]).rolling(5, min_periods=1).mean()
    out["large_trade_ratio"] = np.where(
        aligned["total_volume"] > 0,
        aligned["large_volume"].fillna(0) / aligned["total_volume"],
        0.0,
    )
    out["trade_arrival_rate"] = aligned["trade_count"].fillna(0).reset_index(drop=True)
    out["vwap_deviation"] = np.where(
        aligned["vwap"].notna() & (aligned["vwap"] > 0),
        (close_1m - aligned["vwap"].reset_index(drop=True)) / aligned["vwap"].reset_index(drop=True),
        0.0,
    )

    return pd.DataFrame({k: pd.Series(v).reset_index(drop=True) for k, v in out.items()})


# ---------------------------------------------------------------------------
# Sentiment features
# ---------------------------------------------------------------------------


def compute_sentiment_features(
    candles_1m: pd.DataFrame,
    funding: pd.DataFrame | None = None,
    ls_ratio: pd.DataFrame | None = None,
    mark_candles: pd.DataFrame | None = None,
    index_candles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Derivatives sentiment features forward-filled to 1m alignment."""
    n = len(candles_1m)
    ts = candles_1m["timestamp_ms"].reset_index(drop=True)
    out: dict[str, pd.Series] = {}
    nan_s = pd.Series(np.nan, index=range(n))

    # Funding rate features
    if funding is not None and not funding.empty:
        f_aligned = pd.merge_asof(
            ts.to_frame("timestamp_ms"),
            funding[["timestamp_ms", "rate"]].sort_values("timestamp_ms"),
            on="timestamp_ms",
            direction="backward",
        )
        rate = f_aligned["rate"].reset_index(drop=True)
        out["funding_rate"] = rate
        out["funding_momentum"] = rate.diff(3)
        out["annualized_funding"] = rate * 3 * 365
    else:
        out["funding_rate"] = nan_s
        out["funding_momentum"] = nan_s
        out["annualized_funding"] = nan_s

    # LS ratio features
    if ls_ratio is not None and not ls_ratio.empty:
        ls_aligned = pd.merge_asof(
            ts.to_frame("timestamp_ms"),
            ls_ratio[["timestamp_ms", "long_short_ratio"]].sort_values("timestamp_ms"),
            on="timestamp_ms",
            direction="backward",
        )
        lsr = ls_aligned["long_short_ratio"].reset_index(drop=True)
        out["ls_ratio"] = lsr
        out["ls_ratio_momentum"] = lsr.diff(3)
    else:
        out["ls_ratio"] = nan_s
        out["ls_ratio_momentum"] = nan_s

    # Basis features (mark - index)
    if mark_candles is not None and index_candles is not None and not mark_candles.empty and not index_candles.empty:
        mark_aligned = pd.merge_asof(
            ts.to_frame("timestamp_ms"),
            mark_candles[["timestamp_ms", "close"]].rename(columns={"close": "mark_close"}).sort_values("timestamp_ms"),
            on="timestamp_ms",
            direction="backward",
        )
        idx_aligned = pd.merge_asof(
            ts.to_frame("timestamp_ms"),
            index_candles[["timestamp_ms", "close"]].rename(columns={"close": "index_close"}).sort_values("timestamp_ms"),
            on="timestamp_ms",
            direction="backward",
        )
        mark_c = mark_aligned["mark_close"].reset_index(drop=True)
        idx_c = idx_aligned["index_close"].reset_index(drop=True)
        basis = (mark_c - idx_c) / idx_c.replace(0, np.nan)
        out["basis"] = basis
        out["basis_momentum"] = basis.diff(3)
    else:
        out["basis"] = nan_s
        out["basis_momentum"] = nan_s

    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Time features
# ---------------------------------------------------------------------------


def compute_time_features(timestamps_ms: pd.Series) -> pd.DataFrame:
    """Cyclical time encoding features."""
    ts = timestamps_ms.reset_index(drop=True)
    dt = pd.to_datetime(ts, unit="ms", utc=True)

    hour = dt.dt.hour + dt.dt.minute / 60.0
    day = dt.dt.dayofweek

    out: dict[str, pd.Series] = {}
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    out["day_sin"] = np.sin(2 * np.pi * day / 7.0)
    out["day_cos"] = np.cos(2 * np.pi * day / 7.0)

    # Session flag: Asia=0, Europe=1, US=2, overlap=3
    h = dt.dt.hour
    session = pd.Series(0, index=range(len(ts)))
    session = session.where(~((h >= 0) & (h < 8)), 0)    # Asia (00-08 UTC)
    session = session.where(~((h >= 8) & (h < 13)), 1)    # Europe (08-13 UTC)
    session = session.where(~((h >= 13) & (h < 16)), 3)   # EU/US overlap
    session = session.where(~((h >= 16) & (h < 21)), 2)   # US (16-21 UTC)
    session = session.where(~((h >= 21) | (h < 0)), 0)    # Late = Asia
    out["session_flag"] = session

    # Minutes since last funding (8h cycle)
    out["minutes_since_funding"] = (ts % (8 * 60 * 60 * 1000)) / 60_000.0

    return pd.DataFrame(out)
