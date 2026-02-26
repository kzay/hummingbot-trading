"""Performance metrics helpers (inspired by Chris Conlan's pypm metrics).

Upstream reference:
- Repo: `chrisconlan/algorithmic-trading-with-python`
- Files: `src/pypm/metrics.py` (and related modules)

This is an internal, dependency-light reimplementation tailored for runtime
use in controllers (no pandas/numpy/sklearn required).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple, Union

_ZERO = Decimal("0")
_SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


class MetricsError(ValueError):
    pass


def _to_decimal_list(values: Iterable[Decimal]) -> List[Decimal]:
    out: List[Decimal] = []
    for v in values:
        if v is None:
            continue
        if not isinstance(v, Decimal):
            v = Decimal(str(v))
        out.append(v)
    return out


def percent_return(price_series: Sequence[Decimal]) -> Decimal:
    """(last / first) - 1, assuming chronological order."""
    prices = _to_decimal_list(price_series)
    if len(prices) < 2:
        return _ZERO
    first = prices[0]
    last = prices[-1]
    if first <= _ZERO:
        return _ZERO
    return (last / first) - Decimal("1")


def simple_return_series(price_series: Sequence[Decimal]) -> List[Decimal]:
    """Per-step simple returns: r_t = p_t / p_{t-1} - 1."""
    prices = _to_decimal_list(price_series)
    if len(prices) < 2:
        return []
    rets: List[Decimal] = []
    prev = prices[0]
    for p in prices[1:]:
        if prev <= _ZERO:
            rets.append(_ZERO)
        else:
            rets.append((p / prev) - Decimal("1"))
        prev = p
    return rets


def log_return_series(price_series: Sequence[Decimal]) -> List[Decimal]:
    """Per-step log returns: lr_t = ln(p_t / p_{t-1})."""
    prices = _to_decimal_list(price_series)
    if len(prices) < 2:
        return []
    out: List[Decimal] = []
    prev = prices[0]
    for p in prices[1:]:
        if prev <= _ZERO or p <= _ZERO:
            out.append(_ZERO)
        else:
            out.append(Decimal(str(math.log(float(p / prev)))))
        prev = p
    return out


def mean_std(values: Sequence[Decimal]) -> Tuple[Decimal, Decimal]:
    """Sample std (ddof=1) over non-empty list; returns (mean, std)."""
    xs = _to_decimal_list(values)
    n = len(xs)
    if n == 0:
        return _ZERO, _ZERO
    if n == 1:
        return xs[0], _ZERO
    mean = sum(xs, _ZERO) / Decimal(n)
    # use float for sqrt stability; return Decimal
    var = sum([(x - mean) ** 2 for x in xs], _ZERO) / Decimal(n - 1)
    std = Decimal(str(math.sqrt(float(var)))) if var > _ZERO else _ZERO
    return mean, std


def drawdown_series(price_series: Sequence[Decimal], method: str = "percent") -> List[Decimal]:
    """Drawdown series as positive numbers (0 = at peak)."""
    prices = _to_decimal_list(price_series)
    if not prices:
        return []
    method = str(method).lower()
    if method not in ("dollar", "percent", "log"):
        raise MetricsError(f"Unsupported drawdown method: {method}")

    peak = prices[0]
    out: List[Decimal] = []
    for p in prices:
        if p > peak:
            peak = p
        if method == "dollar":
            out.append(max(_ZERO, peak - p))
        elif method == "percent":
            if peak <= _ZERO:
                out.append(_ZERO)
            else:
                out.append(max(_ZERO, (peak - p) / peak))
        else:  # log
            if peak <= _ZERO or p <= _ZERO:
                out.append(_ZERO)
            else:
                out.append(max(_ZERO, Decimal(str(math.log(float(peak)) - math.log(float(p))))))
    return out


@dataclass(frozen=True)
class MaxDrawdownMetadata:
    max_drawdown: Decimal
    peak_index: int
    trough_index: int
    peak_price: Decimal
    trough_price: Decimal
    peak_ts: Optional[str] = None
    trough_ts: Optional[str] = None


def max_drawdown_with_metadata(
    price_series: Sequence[Decimal],
    *,
    method: str = "percent",
    timestamps: Optional[Sequence[str]] = None,
) -> MaxDrawdownMetadata:
    prices = _to_decimal_list(price_series)
    if not prices:
        return MaxDrawdownMetadata(
            max_drawdown=_ZERO,
            peak_index=0,
            trough_index=0,
            peak_price=_ZERO,
            trough_price=_ZERO,
            peak_ts=None,
            trough_ts=None,
        )
    if timestamps is not None and len(timestamps) != len(prices):
        raise MetricsError("timestamps length must match price_series length")

    method = str(method).lower()
    if method not in ("dollar", "percent", "log"):
        raise MetricsError(f"Unsupported drawdown method: {method}")

    peak_price = prices[0]
    peak_index = 0
    best_peak_index = 0
    best_trough_index = 0
    best_dd = _ZERO

    for i, p in enumerate(prices):
        if p > peak_price:
            peak_price = p
            peak_index = i

        if method == "dollar":
            dd = max(_ZERO, peak_price - p)
        elif method == "percent":
            dd = max(_ZERO, (peak_price - p) / peak_price) if peak_price > _ZERO else _ZERO
        else:
            dd = (
                max(_ZERO, Decimal(str(math.log(float(peak_price / p)))))
                if peak_price > _ZERO and p > _ZERO
                else _ZERO
            )

        if dd > best_dd:
            best_dd = dd
            best_peak_index = peak_index
            best_trough_index = i

    best_peak_price = prices[best_peak_index]
    best_trough_price = prices[best_trough_index]
    peak_ts = timestamps[best_peak_index] if timestamps is not None else None
    trough_ts = timestamps[best_trough_index] if timestamps is not None else None
    return MaxDrawdownMetadata(
        max_drawdown=best_dd,
        peak_index=best_peak_index,
        trough_index=best_trough_index,
        peak_price=best_peak_price,
        trough_price=best_trough_price,
        peak_ts=peak_ts,
        trough_ts=trough_ts,
    )


def max_drawdown(price_series: Sequence[Decimal], method: str = "percent") -> Decimal:
    return max_drawdown_with_metadata(price_series, method=method).max_drawdown


def _to_datetimes(timestamps: Sequence[Union[str, datetime, float, int]]) -> List[datetime]:
    out: List[datetime] = []
    for ts in timestamps:
        if isinstance(ts, datetime):
            out.append(ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))
        elif isinstance(ts, (int, float)):
            out.append(datetime.fromtimestamp(float(ts), tz=timezone.utc))
        else:
            s = str(ts).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            out.append(datetime.fromisoformat(s))
    return out


def years_past(timestamps: Sequence[Union[str, datetime, float, int]]) -> float:
    dts = _to_datetimes(timestamps)
    if len(dts) < 2:
        return 0.0
    delta_s = (dts[-1] - dts[0]).total_seconds()
    return max(0.0, delta_s / _SECONDS_PER_YEAR)


def entries_per_year(timestamps: Sequence[Union[str, datetime, float, int]]) -> float:
    yp = years_past(timestamps)
    if yp <= 0:
        return 0.0
    # n-1 returns for n prices
    return (max(0, len(timestamps) - 1)) / yp


def cagr(
    price_series: Sequence[Decimal],
    *,
    timestamps: Sequence[Union[str, datetime, float, int]],
) -> Decimal:
    prices = _to_decimal_list(price_series)
    if len(prices) < 2:
        return _ZERO
    first = prices[0]
    last = prices[-1]
    if first <= _ZERO or last <= _ZERO:
        return _ZERO
    yp = years_past(timestamps)
    if yp <= 0:
        return _ZERO
    value_factor = float(last / first)
    return Decimal(str((value_factor ** (1.0 / yp)) - 1.0))


def annualized_volatility(
    return_series: Sequence[Decimal],
    *,
    timestamps: Sequence[Union[str, datetime, float, int]],
) -> Decimal:
    _, std = mean_std(return_series)
    epy = entries_per_year(timestamps)
    if epy <= 0:
        return _ZERO
    return Decimal(str(float(std) * math.sqrt(epy)))


def sharpe_ratio(
    price_series: Sequence[Decimal],
    *,
    timestamps: Sequence[Union[str, datetime, float, int]],
    benchmark_rate_annual: Decimal = _ZERO,
    use_log_returns: bool = False,
) -> Decimal:
    prices = _to_decimal_list(price_series)
    if len(prices) < 3:
        return _ZERO
    _cagr = cagr(prices, timestamps=timestamps)
    rets = log_return_series(prices) if use_log_returns else simple_return_series(prices)
    vol = annualized_volatility(rets, timestamps=timestamps)
    if vol <= _ZERO:
        return _ZERO
    return (_cagr - benchmark_rate_annual) / vol


def annualized_downside_deviation(
    return_series: Sequence[Decimal],
    *,
    timestamps: Sequence[Union[str, datetime, float, int]],
    benchmark_rate_annual: Decimal = _ZERO,
) -> Decimal:
    rets = _to_decimal_list(return_series)
    if len(rets) < 2:
        return _ZERO
    epy = entries_per_year(timestamps)
    if epy <= 0:
        return _ZERO
    # de-annualize benchmark to per-entry rate
    br = float(benchmark_rate_annual)
    adj_benchmark = (1.0 + br) ** (1.0 / epy) - 1.0

    downside_sq_sum = 0.0
    n = 0
    for r in rets:
        d = adj_benchmark - float(r)
        if d > 0:
            downside_sq_sum += d * d
        n += 1
    denom = max(1, n - 1)
    downside_dev = math.sqrt(downside_sq_sum / denom)
    return Decimal(str(downside_dev * math.sqrt(epy)))


def sortino_ratio(
    price_series: Sequence[Decimal],
    *,
    timestamps: Sequence[Union[str, datetime, float, int]],
    benchmark_rate_annual: Decimal = _ZERO,
    use_log_returns: bool = False,
) -> Decimal:
    prices = _to_decimal_list(price_series)
    if len(prices) < 3:
        return _ZERO
    _cagr = cagr(prices, timestamps=timestamps)
    rets = log_return_series(prices) if use_log_returns else simple_return_series(prices)
    dd = annualized_downside_deviation(rets, timestamps=timestamps, benchmark_rate_annual=benchmark_rate_annual)
    if dd <= _ZERO:
        return _ZERO
    return (_cagr - benchmark_rate_annual) / dd


def jensens_alpha(
    return_series: Sequence[Decimal],
    benchmark_return_series: Sequence[Decimal],
) -> Decimal:
    """OLS intercept of y on x (alpha), no risk-free adjustment."""
    y = _to_decimal_list(return_series)
    x = _to_decimal_list(benchmark_return_series)
    n = min(len(x), len(y))
    if n < 2:
        return _ZERO
    xf = [float(v) for v in x[:n]]
    yf = [float(v) for v in y[:n]]
    mx = sum(xf) / n
    my = sum(yf) / n
    varx = sum((xi - mx) ** 2 for xi in xf)
    if varx <= 0:
        return _ZERO
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(xf, yf))
    beta = cov / varx
    alpha = my - beta * mx
    return Decimal(str(alpha))


