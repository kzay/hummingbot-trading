"""Performance metrics computation for backtesting.

Computes Sharpe, Sortino, Calmar, drawdown, win rate, profit factor,
edge decay, turnover, regime-conditional performance, spread capture
efficiency, and inventory half-life.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from controllers.backtesting.types import (
    BacktestResult,
    EquitySnapshot,
    FillRecord,
    RegimeMetrics,
)

_ZERO = Decimal("0")
_TRADING_DAYS_PER_YEAR = 365  # crypto


# ---------------------------------------------------------------------------
# Core return-based metrics
# ---------------------------------------------------------------------------

def daily_returns(equity_curve: list[EquitySnapshot]) -> list[float]:
    """Compute daily return series from equity snapshots."""
    if len(equity_curve) < 2:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = float(equity_curve[i - 1].equity)
        curr = float(equity_curve[i].equity)
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio. Returns 0.0 if insufficient data."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_rate / _TRADING_DAYS_PER_YEAR for r in returns]
    mean_r = sum(excess) / len(excess)
    var = sum((r - mean_r) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean_r / std) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def sortino_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_rate / _TRADING_DAYS_PER_YEAR for r in returns]
    mean_r = sum(excess) / len(excess)
    downside = [min(r, 0.0) ** 2 for r in excess]
    downside_var = sum(downside) / len(downside)
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0
    if downside_std == 0:
        return 0.0
    return (mean_r / downside_std) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def total_return_pct(equity_curve: list[EquitySnapshot]) -> float:
    """Total return as percentage."""
    if len(equity_curve) < 2:
        return 0.0
    start = float(equity_curve[0].equity)
    end = float(equity_curve[-1].equity)
    if start <= 0:
        return 0.0
    return ((end - start) / start) * 100.0


def cagr_pct(equity_curve: list[EquitySnapshot]) -> float:
    """Compound annual growth rate."""
    if len(equity_curve) < 2:
        return 0.0
    start = float(equity_curve[0].equity)
    end = float(equity_curve[-1].equity)
    if start <= 0 or end <= 0:
        return 0.0
    days = len(equity_curve) - 1
    if days <= 0:
        return 0.0
    years = days / _TRADING_DAYS_PER_YEAR
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

@dataclass
class DrawdownInfo:
    max_drawdown_pct: float
    max_drawdown_duration_days: int


def compute_drawdown(equity_curve: list[EquitySnapshot]) -> DrawdownInfo:
    """Compute max drawdown % and max drawdown duration in days."""
    if len(equity_curve) < 2:
        return DrawdownInfo(0.0, 0)

    peak = float(equity_curve[0].equity)
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_duration = 0

    for snap in equity_curve:
        val = float(snap.equity)
        if val > peak:
            peak = val
            current_dd_duration = 0
        else:
            dd = (peak - val) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            current_dd_duration += 1
            max_dd_duration = max(max_dd_duration, current_dd_duration)

    return DrawdownInfo(max_dd * 100.0, max_dd_duration)


def calmar_ratio(cagr: float, max_dd_pct: float) -> float:
    """Calmar ratio = CAGR / max drawdown."""
    if max_dd_pct <= 0:
        return 0.0
    return cagr / max_dd_pct


# ---------------------------------------------------------------------------
# Trade-level metrics
# ---------------------------------------------------------------------------

@dataclass
class RoundTripResult:
    """Aggregated round-trip PnL from FIFO fill matching."""
    gross_profit: Decimal
    gross_loss: Decimal
    win_count: int
    loss_count: int

    @property
    def total_count(self) -> int:
        return self.win_count + self.loss_count

    @property
    def rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.win_count / self.total_count

    @property
    def realized_net(self) -> Decimal:
        return self.gross_profit - self.gross_loss

    @property
    def avg_win(self) -> Decimal:
        if self.win_count <= 0:
            return _ZERO
        return self.gross_profit / Decimal(self.win_count)

    @property
    def avg_loss(self) -> Decimal:
        if self.loss_count <= 0:
            return _ZERO
        return self.gross_loss / Decimal(self.loss_count)

    @property
    def expectancy(self) -> Decimal:
        if self.total_count <= 0:
            return _ZERO
        return self.realized_net / Decimal(self.total_count)


def compute_round_trips(fills: list[FillRecord]) -> RoundTripResult:
    """FIFO round-trip matching: pair buys against sells in order.

    Walks through fills chronologically, maintaining a position queue.
    When a fill reduces the position (sell after buys, or buy after sells),
    it closes out the oldest entries first (FIFO) and records PnL per
    closed quantity slice.  Both the entry and exit fills' fees are
    pro-rated by matched quantity and deducted from each round-trip's PnL.
    """
    gross_profit = _ZERO
    gross_loss = _ZERO
    win_count = 0
    loss_count = 0

    queue: deque[list] = deque()  # [side, price, remaining_qty, fee_per_unit]

    for fill in fills:
        remaining = fill.fill_quantity
        is_buy = fill.side == "buy"
        exit_fee_per_unit = fill.fee / fill.fill_quantity if fill.fill_quantity > _ZERO else _ZERO

        while remaining > _ZERO and queue:
            entry = queue[0]
            entry_is_buy = entry[0] == "buy"

            if entry_is_buy == is_buy:
                break

            match_qty = min(remaining, entry[2])
            entry_price = entry[1]
            entry_fee_per_unit = entry[3]

            if entry_is_buy:
                pnl = (fill.fill_price - entry_price) * match_qty
            else:
                pnl = (entry_price - fill.fill_price) * match_qty

            pnl -= (entry_fee_per_unit + exit_fee_per_unit) * match_qty

            if pnl > _ZERO:
                gross_profit += pnl
                win_count += 1
            else:
                gross_loss += abs(pnl)
                loss_count += 1

            entry[2] -= match_qty
            remaining -= match_qty
            if entry[2] <= _ZERO:
                queue.popleft()

        if remaining > _ZERO:
            fee_per_unit = fill.fee / fill.fill_quantity if fill.fill_quantity > _ZERO else _ZERO
            queue.append([fill.side, fill.fill_price, remaining, fee_per_unit])

    return RoundTripResult(
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        win_count=win_count,
        loss_count=loss_count,
    )


def win_rate(fills: list[FillRecord]) -> float:
    """Win rate from FIFO round-trip fill pairs."""
    if not fills:
        return 0.0
    return compute_round_trips(fills).rate


def profit_factor(gross_profit: Decimal, gross_loss: Decimal) -> float:
    """Gross profit / gross loss. Returns 0.0 if no losses."""
    if gross_loss <= _ZERO:
        return 0.0 if gross_profit <= _ZERO else float("inf")
    return float(gross_profit / abs(gross_loss))


# ---------------------------------------------------------------------------
# Fee attribution
# ---------------------------------------------------------------------------

def fee_attribution(fills: list[FillRecord]) -> dict[str, Decimal]:
    """Compute fee breakdown from fill records."""
    maker_fees = _ZERO
    taker_fees = _ZERO
    maker_count = 0
    taker_count = 0

    for f in fills:
        if f.is_maker:
            maker_fees += f.fee
            maker_count += 1
        else:
            taker_fees += f.fee
            taker_count += 1

    total = maker_fees + taker_fees
    total_count = maker_count + taker_count
    maker_ratio = maker_count / total_count if total_count > 0 else 0.0

    return {
        "maker_fees": maker_fees,
        "taker_fees": taker_fees,
        "total_fees": total,
        "maker_fill_ratio": Decimal(str(maker_ratio)),
        "maker_count": Decimal(str(maker_count)),
        "taker_count": Decimal(str(taker_count)),
    }


# ---------------------------------------------------------------------------
# Execution quality
# ---------------------------------------------------------------------------

def execution_quality(fills: list[FillRecord], order_count: int) -> dict[str, float]:
    """Compute execution quality metrics."""
    if not fills:
        return {
            "fill_rate": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_mid_slippage_bps": 0.0,
            "partial_fill_ratio": 0.0,
        }

    avg_slip = sum(float(f.slippage_bps) for f in fills) / len(fills)
    avg_mid_slip = sum(float(f.mid_slippage_bps) for f in fills) / len(fills)
    fill_rate = len(fills) / order_count if order_count > 0 else 0.0

    return {
        "fill_rate": fill_rate,
        "avg_slippage_bps": avg_slip,
        "avg_mid_slippage_bps": avg_mid_slip,
        "partial_fill_ratio": 0.0,  # Requires order-level tracking
    }


# ---------------------------------------------------------------------------
# Edge decay curve
# ---------------------------------------------------------------------------

def edge_decay_curve(
    equity_curve: list[EquitySnapshot],
    window_days: int = 30,
) -> list[tuple[str, float]]:
    """Compute rolling Sharpe ratio over time."""
    returns = daily_returns(equity_curve)
    if len(returns) < window_days:
        return []

    curve = []
    for i in range(window_days, len(returns) + 1):
        window = returns[i - window_days:i]
        sr = sharpe_ratio(window)
        date = equity_curve[i].date  # i, not i-1, because returns[0] corresponds to equity_curve[1]
        curve.append((date, sr))

    return curve


def edge_decay_warnings(curve: list[tuple[str, float]], threshold_days: int = 30) -> list[str]:
    """Check for extended negative edge periods."""
    warnings = []
    consecutive_negative = 0
    max_negative = 0

    for _, sr in curve:
        if sr < 0:
            consecutive_negative += 1
            max_negative = max(max_negative, consecutive_negative)
        else:
            consecutive_negative = 0

    if max_negative >= threshold_days:
        warnings.append(f"WARNING: Extended negative edge detected ({max_negative} days)")

    return warnings


# ---------------------------------------------------------------------------
# Turnover metrics
# ---------------------------------------------------------------------------

def turnover_metrics(
    fills: list[FillRecord],
    equity_curve: list[EquitySnapshot],
) -> dict[str, float]:
    """Compute turnover-related metrics."""
    total_notional = sum(float(f.fill_price * f.fill_quantity) for f in fills)
    n_days = max(len(equity_curve) - 1, 1)
    avg_equity = sum(float(s.equity) for s in equity_curve) / len(equity_curve) if equity_curve else 1.0

    daily_turnover = total_notional / n_days
    turnover_ratio = total_notional / avg_equity if avg_equity > 0 else 0.0
    annualized_turnover = turnover_ratio * (_TRADING_DAYS_PER_YEAR / n_days)

    warnings = []
    if annualized_turnover > 100:
        warnings.append(f"WARNING: High turnover ({annualized_turnover:.0f}x) — fee sensitivity is elevated")

    return {
        "total_notional": total_notional,
        "avg_daily_turnover": daily_turnover,
        "turnover_ratio": turnover_ratio,
        "annualized_turnover": annualized_turnover,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Spread capture efficiency
# ---------------------------------------------------------------------------

def spread_capture_efficiency(
    fills: list[FillRecord],
    actual_pnl: Decimal,
    total_fees: Decimal,
) -> tuple[float, Decimal, list[str]]:
    """Compute spread capture efficiency = actual_pnl / theoretical_max_pnl.

    theoretical_max_pnl = sum(mid_slippage_bps / 10000 * notional) for each fill
    Approximation: assumes each fill captures half the spread.

    Returns: (efficiency, theoretical_max_pnl, warnings)
    """
    if not fills:
        return 0.0, _ZERO, []

    # Theoretical max: each fill captures the spread at fill time
    # mid_slippage_bps tells us how far from mid the fill was
    theoretical = _ZERO
    for f in fills:
        notional = f.fill_price * f.fill_quantity
        # For a maker fill, the theoretical capture is the distance from mid
        # Use absolute mid_slippage_bps as the spread captured
        capture_bps = abs(f.mid_slippage_bps) if f.mid_slippage_bps else Decimal("2.5")
        theoretical += notional * capture_bps / Decimal("10000")

    theoretical_net = theoretical - total_fees

    if theoretical_net <= _ZERO:
        return 0.0, theoretical_net, []

    efficiency = float(actual_pnl / theoretical_net) if theoretical_net > _ZERO else 0.0

    warnings = []
    if efficiency > 0.8:
        warnings.append(
            f"WARNING: Spread capture efficiency ({efficiency:.2f}) exceeds 0.80 "
            "— fill model may be unrealistically generous"
        )
    elif efficiency < 0.2:
        warnings.append(
            f"WARNING: Spread capture efficiency ({efficiency:.2f}) below 0.20 "
            "— severe adverse selection"
        )

    return efficiency, theoretical_net, warnings


# ---------------------------------------------------------------------------
# Inventory half-life (OU process fit)
# ---------------------------------------------------------------------------

def inventory_half_life(
    position_series: list[float],
    dt_minutes: float = 1.0,
) -> tuple[float, list[str]]:
    """Estimate inventory mean-reversion half-life via OLS on OU process.

    Fits: Δq(t) = -θ * q(t-1) + ε
    Half-life = ln(2) / θ

    Returns: (half_life_minutes, warnings)
    """
    if len(position_series) < 30:
        return 0.0, ["Insufficient data for inventory half-life estimation"]

    n = len(position_series) - 1
    ps = position_series

    # Two-pass OLS without allocating intermediate lists.
    sum_q = 0.0
    sum_dq = 0.0
    for i in range(n):
        sum_q += ps[i]
        sum_dq += ps[i + 1] - ps[i]
    mean_q = sum_q / n
    mean_dq = sum_dq / n

    cov = 0.0
    var = 0.0
    for i in range(n):
        q_c = ps[i] - mean_q
        var += q_c * q_c
        cov += (ps[i + 1] - ps[i] - mean_dq) * q_c
    cov /= n
    var /= n

    if var < 1e-15:
        return 0.0, ["Zero variance in position series — inventory is flat"]

    theta = -cov / var

    if theta <= 0:
        return float("inf"), ["WARNING: Inventory is not mean-reverting (θ ≤ 0)"]

    half_life = math.log(2) / theta * dt_minutes

    warnings = []
    if half_life < 3:
        warnings.append(
            f"WARNING: Inventory half-life very short ({half_life:.1f}min < 3min) "
            "— strategy may be over-rebalancing"
        )
    elif half_life > 90:
        warnings.append(
            f"WARNING: Inventory accumulating (half-life {half_life:.0f}min > 90min threshold)"
        )

    return half_life, warnings


# ---------------------------------------------------------------------------
# Regime-conditional performance
# ---------------------------------------------------------------------------

def regime_conditional_metrics(
    returns_by_regime: dict[str, list[float]],
    fills_by_regime: dict[str, list[FillRecord]],
    total_returns: int,
) -> tuple[list[RegimeMetrics], list[str]]:
    """Compute per-regime performance metrics.

    Args:
        returns_by_regime: daily returns keyed by regime name
        fills_by_regime: fills keyed by regime name
        total_returns: total number of return observations

    Returns: (regime_metrics, warnings)
    """
    metrics = []
    warnings = []

    for regime_name, rets in returns_by_regime.items():
        n_days = len(rets)
        time_frac = n_days / total_returns if total_returns > 0 else 0.0
        sr = sharpe_ratio(rets) if len(rets) >= 2 else 0.0
        fills = fills_by_regime.get(regime_name, [])

        # Max drawdown for this regime (simplified: use cumulative returns)
        max_dd = 0.0
        peak = 0.0
        cum = 0.0
        for r in rets:
            cum += r
            if cum > peak:
                peak = cum
            dd = peak - cum
            max_dd = max(max_dd, dd)

        # Net edge per fill
        net_edge = 0.0
        if fills:
            net_edge = sum(float(f.mid_slippage_bps) for f in fills) / len(fills)

        metrics.append(RegimeMetrics(
            regime_name=regime_name,
            time_fraction=time_frac,
            sharpe=sr,
            max_drawdown_pct=max_dd * 100,
            fill_count=len(fills),
            net_edge_bps=net_edge,
            num_days=n_days,
        ))

        if sr < -0.5:
            warnings.append(
                f"CRITICAL: Negative Sharpe in {regime_name} regime ({sr:.2f} < -0.5 threshold)"
            )

    # Check weighted Sharpe deviation
    if metrics and total_returns > 0:
        overall_rets = []
        for rets_list in returns_by_regime.values():
            overall_rets.extend(rets_list)
        overall_sr = sharpe_ratio(overall_rets) if len(overall_rets) >= 2 else 0.0

        weighted_sr = sum(m.sharpe * m.time_fraction for m in metrics)
        if overall_sr != 0:
            deviation = abs(weighted_sr - overall_sr) / abs(overall_sr)
            if deviation > 0.20:
                warnings.append(
                    f"WARNING: Edge is regime-dependent ({deviation:.0%} weighted deviation > 20% threshold)"
                )

    return metrics, warnings


# ---------------------------------------------------------------------------
# Assemble full result
# ---------------------------------------------------------------------------

def compute_all_metrics(
    equity_curve: list[EquitySnapshot],
    fills: list[FillRecord],
    order_count: int,
    actual_pnl: Decimal,
    total_fees: Decimal,
    funding_paid: Decimal,
    funding_received: Decimal,
    position_series: list[float],
    returns_by_regime: dict[str, list[float]] | None = None,
    fills_by_regime: dict[str, list[FillRecord]] | None = None,
    risk_free_rate: float = 0.0,
) -> BacktestResult:
    """Compute all metrics and return a BacktestResult."""
    result = BacktestResult()
    result.equity_curve = equity_curve
    result.fills = fills

    # Daily returns
    rets = daily_returns(equity_curve)

    # Core metrics
    result.total_return_pct = total_return_pct(equity_curve)
    result.cagr_pct = cagr_pct(equity_curve)
    result.sharpe_ratio = sharpe_ratio(rets, risk_free_rate)
    result.sortino_ratio = sortino_ratio(rets, risk_free_rate)

    dd = compute_drawdown(equity_curve)
    result.max_drawdown_pct = dd.max_drawdown_pct
    result.max_drawdown_duration_days = dd.max_drawdown_duration_days
    result.calmar_ratio = calmar_ratio(result.cagr_pct, dd.max_drawdown_pct)

    # Fee attribution
    fees = fee_attribution(fills)
    result.total_fees = fees["total_fees"]
    result.maker_fees = fees["maker_fees"]
    result.taker_fees = fees["taker_fees"]
    result.maker_fill_ratio = float(fees["maker_fill_ratio"])
    result.funding_paid = funding_paid
    result.funding_received = funding_received
    gross_profit = actual_pnl + total_fees  # PnL before fees
    result.fee_drag_pct = float(total_fees / gross_profit * 100) if gross_profit > _ZERO else 0.0

    # Execution quality
    eq = execution_quality(fills, order_count)
    result.fill_count = len(fills)
    result.order_count = order_count
    result.fill_rate = eq["fill_rate"]
    result.avg_slippage_bps = eq["avg_slippage_bps"]
    result.avg_mid_slippage_bps = eq["avg_mid_slippage_bps"]
    result.partial_fill_ratio = eq["partial_fill_ratio"]

    # Edge decay
    result.edge_decay_curve = edge_decay_curve(equity_curve)
    result.warnings.extend(edge_decay_warnings(result.edge_decay_curve))

    # Turnover
    turn = turnover_metrics(fills, equity_curve)
    result.total_notional_traded = Decimal(str(turn["total_notional"]))
    result.avg_daily_turnover = Decimal(str(turn["avg_daily_turnover"]))
    result.turnover_ratio = turn["turnover_ratio"]
    result.warnings.extend(turn.get("warnings", []))

    # Spread capture efficiency
    eff, theo_max, eff_warnings = spread_capture_efficiency(fills, actual_pnl, total_fees)
    result.spread_capture_efficiency = eff
    result.theoretical_max_pnl = theo_max
    result.warnings.extend(eff_warnings)

    # Inventory half-life
    if position_series:
        hl, hl_warnings = inventory_half_life(position_series)
        result.inventory_half_life_minutes = hl
        result.warnings.extend(hl_warnings)

    # Regime-conditional
    if returns_by_regime and fills_by_regime:
        regime_m, regime_w = regime_conditional_metrics(
            returns_by_regime, fills_by_regime, len(rets),
        )
        result.regime_metrics = regime_m
        result.warnings.extend(regime_w)

    # Win rate and profit factor from round-trip matching
    if fills:
        rt = compute_round_trips(fills)
        result.win_rate = rt.rate
        result.profit_factor = profit_factor(rt.gross_profit, rt.gross_loss)
        result.avg_win_loss_ratio = (
            float(rt.gross_profit / Decimal(rt.win_count) / (rt.gross_loss / Decimal(rt.loss_count)))
            if rt.win_count > 0 and rt.loss_count > 0 and rt.gross_loss > _ZERO
            else 0.0
        )
    else:
        result.warnings.append("No trades executed — check strategy configuration")

    return result
