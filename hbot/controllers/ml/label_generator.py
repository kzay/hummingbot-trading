"""Forward-looking label computation from raw OHLCV data.

All labels represent pure market outcomes — no dependency on strategy signals,
regime labels, or bot state.  Input is a float64 DataFrame from
``load_candles_df()``; output is a DataFrame of label columns aligned to the
same timestamps.

Trailing rows where forward data is insufficient are NaN.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def compute_labels(
    candles_1m: pd.DataFrame,
    horizons: Sequence[int] = (5, 15, 60),
    *,
    bucket_window: int = 1440,
    epsilon: float = 1e-10,
) -> pd.DataFrame:
    """Compute forward-looking labels at the given minute horizons.

    Parameters
    ----------
    candles_1m
        Columns: timestamp_ms, open, high, low, close, volume.
    horizons
        Forward-looking windows in minutes.
    bucket_window
        Rolling window size for percentile-based bucket boundaries.
    epsilon
        Small value to prevent division by zero in tradability.

    Returns
    -------
    DataFrame
        Columns: ``timestamp_ms`` plus label columns for each horizon.
    """
    close = candles_1m["close"].values.astype(np.float64)
    high = candles_1m["high"].values.astype(np.float64)
    low = candles_1m["low"].values.astype(np.float64)
    n = len(close)

    out: dict[str, np.ndarray] = {
        "timestamp_ms": candles_1m["timestamp_ms"].values,
    }

    for h in horizons:
        fwd_ret = _forward_returns(close, h)
        out[f"fwd_return_{h}m"] = fwd_ret

        out[f"fwd_return_sign_{h}m"] = _return_sign(fwd_ret, deadzone=0.0001)

        out[f"fwd_return_bucket_{h}m"] = _rolling_percentile_buckets(
            fwd_ret, window=bucket_window, n_buckets=5,
        )

        fwd_vol = _forward_volatility(close, h)
        out[f"fwd_vol_{h}m"] = fwd_vol

        out[f"fwd_vol_bucket_{h}m"] = _volatility_buckets(
            fwd_vol, window=bucket_window,
        )

        mae_long, mfe_long = _forward_mae_mfe_long(close, high, low, h)
        mae_short, mfe_short = _forward_mae_mfe_short(close, high, low, h)
        out[f"fwd_mae_long_{h}m"] = mae_long
        out[f"fwd_mfe_long_{h}m"] = mfe_long
        out[f"fwd_mae_short_{h}m"] = mae_short
        out[f"fwd_mfe_short_{h}m"] = mfe_short

        out[f"tradability_long_{h}m"] = mfe_long / (mae_long + epsilon)
        out[f"tradability_short_{h}m"] = mfe_short / (mae_short + epsilon)

    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _forward_returns(close: np.ndarray, horizon: int) -> np.ndarray:
    n = len(close)
    result = np.full(n, np.nan)
    valid = n - horizon
    if valid > 0:
        result[:valid] = (close[horizon:] - close[:valid]) / close[:valid]
    return result


def _return_sign(returns: np.ndarray, deadzone: float) -> np.ndarray:
    result = np.full(len(returns), np.nan)
    valid = ~np.isnan(returns)
    result[valid] = np.where(
        returns[valid] > deadzone, 1,
        np.where(returns[valid] < -deadzone, -1, 0),
    )
    return result


def _rolling_percentile_buckets(
    values: np.ndarray,
    window: int,
    n_buckets: int,
) -> np.ndarray:
    """Quantize values into buckets using rolling percentile boundaries."""
    s = pd.Series(values)
    result = np.full(len(values), np.nan)

    percentiles = np.linspace(0, 100, n_buckets + 1)[1:-1]

    for i in range(window, len(values)):
        if np.isnan(values[i]):
            continue
        lookback = values[max(0, i - window):i]
        lookback = lookback[~np.isnan(lookback)]
        if len(lookback) < 10:
            continue
        thresholds = np.percentile(lookback, percentiles)
        result[i] = np.searchsorted(thresholds, values[i])

    return result


def _forward_volatility(close: np.ndarray, horizon: int) -> np.ndarray:
    """Standard deviation of 1m log returns over the next *horizon* bars."""
    n = len(close)
    log_ret = np.log(close[1:] / close[:-1])
    result = np.full(n, np.nan)
    for i in range(n - horizon):
        segment = log_ret[i:i + horizon]
        if len(segment) == horizon:
            result[i] = np.std(segment)
    return result


def _volatility_buckets(
    vol: np.ndarray,
    window: int,
) -> np.ndarray:
    """Classify volatility into {low=0, normal=1, elevated=2, extreme=3}."""
    s = pd.Series(vol)
    result = np.full(len(vol), np.nan)

    for i in range(window, len(vol)):
        if np.isnan(vol[i]):
            continue
        lookback = vol[max(0, i - window):i]
        lookback = lookback[~np.isnan(lookback)]
        if len(lookback) < 10:
            continue
        p25 = np.percentile(lookback, 25)
        p75 = np.percentile(lookback, 75)
        p95 = np.percentile(lookback, 95)
        if vol[i] <= p25:
            result[i] = 0
        elif vol[i] <= p75:
            result[i] = 1
        elif vol[i] <= p95:
            result[i] = 2
        else:
            result[i] = 3

    return result


def _forward_mae_mfe_long(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """MAE/MFE for a hypothetical long entry at each bar's close."""
    n = len(close)
    mae = np.full(n, np.nan)
    mfe = np.full(n, np.nan)
    for i in range(n - horizon):
        future_high = np.max(high[i + 1:i + 1 + horizon])
        future_low = np.min(low[i + 1:i + 1 + horizon])
        mfe[i] = (future_high - close[i]) / close[i]
        mae[i] = (close[i] - future_low) / close[i]
    return np.clip(mae, 0, None), np.clip(mfe, 0, None)


def _forward_mae_mfe_short(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """MAE/MFE for a hypothetical short entry at each bar's close."""
    n = len(close)
    mae = np.full(n, np.nan)
    mfe = np.full(n, np.nan)
    for i in range(n - horizon):
        future_high = np.max(high[i + 1:i + 1 + horizon])
        future_low = np.min(low[i + 1:i + 1 + horizon])
        mfe[i] = (close[i] - future_low) / close[i]
        mae[i] = (future_high - close[i]) / close[i]
    return np.clip(mae, 0, None), np.clip(mfe, 0, None)
