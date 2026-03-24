"""Walk-forward validation with 6-layer overfitting defense.

Implements:
1. Anchored expanding / rolling window splitting
2. Per-window optimization (sweep on train, evaluate on test)
3. Strategy-type-aware OOS degradation ratio
4. Deflated Sharpe Ratio (DSR) with honest trial counting
5. Block bootstrap permutation test (Politis-Romano)
6. Parameter stability (CV + plateau test)
7. Fee stress test gate
8. Regime-conditional OOS reporting
9. Holm-Bonferroni correction for multi-strategy campaigns
"""
from __future__ import annotations

import copy
import logging
import math
import random
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import (
    WalkForwardConfig,
    WalkForwardResult,
    WindowResult,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# OOS thresholds by strategy type
_OOS_THRESHOLDS = {
    "mm": 0.70,           # Pure market making (bot1, bot5)
    "directional": 0.50,  # Directional hybrids (bot6, bot7)
}
_OOS_ABSOLUTE_SHARPE_FLOOR = 0.5


# ---------------------------------------------------------------------------
# Window splitting
# ---------------------------------------------------------------------------

def _split_windows_anchored(
    total_bars: int,
    n_windows: int,
    train_ratio: float,
    min_train_bars: int,
    min_test_bars: int,
) -> list[tuple[int, int, int, int]]:
    """Anchored expanding windows: train always starts at 0, expands.

    Returns list of (train_start, train_end, test_start, test_end) as bar indices.
    """
    windows = []
    step = max(1, (total_bars - min_train_bars - min_test_bars) // max(1, n_windows))

    for i in range(n_windows):
        train_end = min_train_bars + step * i
        test_start = train_end
        test_end = min(test_start + max(min_test_bars, step), total_bars)

        if train_end > total_bars or test_start >= total_bars:
            break
        if test_end - test_start < min_test_bars:
            break

        windows.append((0, train_end, test_start, test_end))

    return windows


def _split_windows_rolling(
    total_bars: int,
    n_windows: int,
    train_ratio: float,
    min_train_bars: int,
    min_test_bars: int,
) -> list[tuple[int, int, int, int]]:
    """Rolling windows: fixed train size, sliding forward.

    Returns list of (train_start, train_end, test_start, test_end) as bar indices.
    """
    window_size = total_bars // max(1, n_windows)
    train_size = max(min_train_bars, int(window_size * train_ratio))
    test_size = max(min_test_bars, window_size - train_size)

    windows = []
    for i in range(n_windows):
        train_start = i * test_size
        train_end = train_start + train_size
        test_start = train_end
        test_end = test_start + test_size

        if test_end > total_bars:
            break

        windows.append((train_start, train_end, test_start, test_end))

    return windows


def split_windows(
    total_bars: int,
    config: WalkForwardConfig,
) -> list[tuple[int, int, int, int]]:
    """Split data into train/test windows."""
    # Auto-compute number of windows if not specified
    n_windows = config.n_windows
    step_s = max(1, config.sweep_config.base_config.step_interval_s)
    bars_per_day = 86400 // step_s

    if n_windows <= 0:
        total_days = total_bars // max(1, bars_per_day)
        n_windows = max(2, total_days // max(1, config.min_test_days))
        n_windows = min(n_windows, 10)

    min_train_bars = config.min_train_days * bars_per_day
    min_test_bars = config.min_test_days * bars_per_day

    if config.window_mode == "anchored":
        return _split_windows_anchored(total_bars, n_windows, config.train_ratio, min_train_bars, min_test_bars)
    elif config.window_mode == "rolling":
        return _split_windows_rolling(total_bars, n_windows, config.train_ratio, min_train_bars, min_test_bars)
    else:
        raise ValueError(f"Unknown window_mode: {config.window_mode!r}")


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio
# ---------------------------------------------------------------------------

def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_returns: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> tuple[float, float]:
    """Compute the Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    Returns (deflated_sharpe, p_value).

    Accounts for the multiple testing bias: when you try N parameter combos,
    the best Sharpe is inflated by selection bias.
    """
    if n_trials <= 1 or n_returns <= 1:
        return observed_sharpe, 0.0

    from scipy import stats

    # Expected maximum Sharpe under null (Euler-Mascheroni + harmonic correction)
    euler_mascheroni = 0.5772
    e_max_sharpe = (
        (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / n_trials)
        + euler_mascheroni * stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    )

    # Variance of Sharpe estimate (Lo 2002)
    sr_var = (
        1.0
        + 0.5 * observed_sharpe ** 2
        - skewness * observed_sharpe
        + ((kurtosis - 3.0) / 4.0) * observed_sharpe ** 2
    ) / max(1, n_returns - 1)

    if sr_var <= 0:
        return observed_sharpe, 0.0

    sr_std = math.sqrt(sr_var)
    # DSR = P(observed > E[max] | null)
    z = (observed_sharpe - e_max_sharpe) / max(sr_std, 1e-10)
    p_value = 1.0 - stats.norm.cdf(z)
    deflated = observed_sharpe - e_max_sharpe

    return deflated, p_value


# ---------------------------------------------------------------------------
# Block bootstrap
# ---------------------------------------------------------------------------

def block_bootstrap_test(
    daily_returns: list[float],
    observed_sharpe: float,
    block_size: int = 30,
    n_replications: int = 1000,
    seed: int = 42,
) -> float:
    """Block bootstrap permutation test for Sharpe ratio significance.

    Uses Politis-Romano stationary bootstrap with geometric block length.
    Returns the percentile rank of observed_sharpe in the bootstrap distribution
    (higher = more significant; >0.95 is significant at 5%).
    """
    if len(daily_returns) < block_size * 2 or block_size < 2:
        return 0.5  # Insufficient data

    rng = random.Random(seed)
    n = len(daily_returns)
    bootstrap_sharpes: list[float] = []

    for _ in range(n_replications):
        # Generate bootstrap sample using geometric block length
        sample: list[float] = []
        while len(sample) < n:
            # Random starting point
            start = rng.randint(0, n - 1)
            # Geometric block length (mean = block_size)
            length = min(
                rng.expovariate(1.0 / block_size) + 1,
                n - len(sample),
            )
            length = max(1, int(length))
            for j in range(length):
                idx = (start + j) % n
                sample.append(daily_returns[idx])

        sample = sample[:n]

        # Compute Sharpe of bootstrap sample
        mean_r = sum(sample) / len(sample)
        var_r = sum((r - mean_r) ** 2 for r in sample) / max(1, len(sample) - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 1e-10
        bootstrap_sharpes.append(mean_r / std_r * math.sqrt(365))

    # Percentile of observed Sharpe in bootstrap distribution
    count_below = sum(1 for s in bootstrap_sharpes if s < observed_sharpe)
    return count_below / max(1, len(bootstrap_sharpes))


# ---------------------------------------------------------------------------
# Parameter stability
# ---------------------------------------------------------------------------

def param_stability_cv(
    window_params: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute coefficient of variation for each parameter across windows.

    Flag CV > 0.5 as unstable.
    """
    if not window_params:
        return {}

    param_names = set()
    for wp in window_params:
        param_names.update(wp.keys())

    cv_map: dict[str, float] = {}
    for name in param_names:
        values = [float(wp.get(name, 0)) for wp in window_params if name in wp]
        if len(values) < 2:
            cv_map[name] = 0.0
            continue
        mean = sum(values) / len(values)
        if abs(mean) < 1e-10:
            cv_map[name] = 0.0
            continue
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
        cv_map[name] = std / abs(mean)

    return cv_map


def param_plateau_test(
    best_params: dict[str, Any],
    objective_fn: Callable[[dict[str, Any]], float],
    perturbation_pct: float = 0.30,
    steps: int = 6,
) -> dict[str, bool]:
    """Test if optimal params sit on a plateau (robust) vs a spike (fragile).

    Varies each param by ±perturbation_pct in steps and checks if the objective
    stays within 20% of the optimum.  Returns {param_name: passes_plateau}.
    """
    plateau_pass: dict[str, bool] = {}

    for name, val in best_params.items():
        try:
            val_f = float(val)
        except (TypeError, ValueError):
            plateau_pass[name] = True
            continue

        if abs(val_f) < 1e-10:
            plateau_pass[name] = True
            continue

        base_obj = objective_fn(best_params)
        all_within_threshold = True

        for sign in [-1, 1]:
            for step_i in range(1, steps + 1):
                pct = sign * perturbation_pct * step_i / steps
                perturbed = dict(best_params)
                perturbed[name] = val_f * (1 + pct)
                perturbed_obj = objective_fn(perturbed)
                if base_obj > 0 and perturbed_obj < base_obj * 0.80:
                    all_within_threshold = False
                    break
            if not all_within_threshold:
                break

        plateau_pass[name] = all_within_threshold

    return plateau_pass


# ---------------------------------------------------------------------------
# Fee stress test
# ---------------------------------------------------------------------------

def fee_stress_test(
    base_sharpe: float,
    base_fee_drag_pct: float,
    fee_multipliers: list[float],
    stressed_maker_ratio: float,
    base_maker_ratio: float,
) -> tuple[float, dict[str, float], float]:
    """Compute break-even fee and Sharpe under stressed fee levels.

    Returns:
        (fee_margin_of_safety, {mult_label: sharpe}, sharpe_at_stressed_maker)
    """
    # Approximate: Sharpe degrades linearly with fee increase
    if base_fee_drag_pct <= 0:
        return 1.0, {str(m): base_sharpe for m in fee_multipliers}, base_sharpe

    sharpe_at_levels: dict[str, float] = {}
    for mult in fee_multipliers:
        additional_drag = base_fee_drag_pct * (mult - 1.0)
        # Approximate: each 1% fee drag reduces Sharpe by ~0.5
        sharpe_at_levels[f"{mult:.1f}x"] = base_sharpe - additional_drag * 50

    # Break-even fee = fee where Sharpe hits 0
    if base_fee_drag_pct > 0:
        break_even_mult = base_sharpe / (base_fee_drag_pct * 50) + 1.0
        fee_margin = (break_even_mult - 1.0) / 1.0  # margin above current
    else:
        fee_margin = 10.0

    # Stressed maker ratio: shift from maker to taker
    maker_shift = max(0, base_maker_ratio - stressed_maker_ratio)
    taker_premium = maker_shift * 0.0004  # typical maker-taker gap
    sharpe_at_stressed_maker = base_sharpe - taker_premium * 50

    return max(0, fee_margin), sharpe_at_levels, sharpe_at_stressed_maker


# ---------------------------------------------------------------------------
# Holm-Bonferroni correction
# ---------------------------------------------------------------------------

def holm_bonferroni_correction(
    p_values: list[float],
    alpha: float = 0.05,
) -> list[bool]:
    """Apply Holm-Bonferroni step-down correction.

    Returns list of bools: True if the strategy passes at the corrected level.
    """
    n = len(p_values)
    if n == 0:
        return []

    # Sort by p-value (ascending)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    passes = [False] * n

    for rank, (orig_idx, pval) in enumerate(indexed):
        adjusted_alpha = alpha / (n - rank)
        if pval <= adjusted_alpha:
            passes[orig_idx] = True
        else:
            # All remaining fail
            break

    return passes


def bh_fdr_correction(
    p_values: list[float],
    alpha: float = 0.05,
) -> list[bool]:
    """Apply Benjamini-Hochberg FDR correction.

    Returns list of bools: True if the strategy passes at the corrected level.
    Controls the false discovery rate rather than the family-wise error rate.
    """
    n = len(p_values)
    if n == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    passes = [False] * n

    max_rank_passing = -1
    for rank_zero, (orig_idx, pval) in enumerate(indexed):
        rank = rank_zero + 1
        bh_threshold = alpha * rank / n
        if pval <= bh_threshold:
            max_rank_passing = rank_zero

    for i in range(max_rank_passing + 1):
        passes[indexed[i][0]] = True

    return passes


# ---------------------------------------------------------------------------
# Walk-forward runner
# ---------------------------------------------------------------------------

class WalkForwardRunner:
    """Execute walk-forward validation with full overfitting defense suite."""

    def __init__(self, config: WalkForwardConfig) -> None:
        self._config = config

    def run(self) -> WalkForwardResult:
        """Execute walk-forward validation and return results."""
        config = self._config
        oos_threshold = _OOS_THRESHOLDS.get(config.strategy_type, 0.50)

        # Run per-window optimization
        windows = self._run_windows()

        if not windows:
            return WalkForwardResult(warnings=["No valid windows produced"])

        # Aggregate metrics
        is_sharpes = [w.is_sharpe for w in windows if w.is_sharpe != 0]
        oos_sharpes = [w.oos_sharpe for w in windows if w.oos_sharpe != 0]
        mean_is = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0
        mean_oos = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0
        oos_ratio = mean_oos / mean_is if abs(mean_is) > 1e-6 else 0

        result = WalkForwardResult(
            windows=windows,
            mean_is_sharpe=mean_is,
            mean_oos_sharpe=mean_oos,
            oos_degradation_ratio=oos_ratio,
            oos_threshold=oos_threshold,
        )

        # Warnings
        if oos_ratio < oos_threshold:
            result.warnings.append(
                f"OOS degradation ratio {oos_ratio:.2f} < threshold {oos_threshold:.2f} "
                f"(strategy_type={config.strategy_type})"
            )
        if mean_oos < _OOS_ABSOLUTE_SHARPE_FLOOR:
            result.warnings.append(
                f"Mean OOS Sharpe {mean_oos:.2f} < absolute floor {_OOS_ABSOLUTE_SHARPE_FLOOR}"
            )

        # Parameter stability
        all_params = [w.best_params for w in windows if w.best_params]
        result.param_cv = param_stability_cv(all_params)
        for name, cv in result.param_cv.items():
            if cv > 0.5:
                result.warnings.append(f"Parameter '{name}' CV={cv:.2f} > 0.5 (unstable)")

        # Deflated Sharpe (requires scipy — graceful fallback)
        all_oos_returns = self._collect_oos_daily_returns(windows)
        total_trials = sum(
            len(config.sweep_config.param_spaces) * max(1, config.sweep_config.n_samples)
            for _ in windows
        )
        n_returns_actual = max(1, len(all_oos_returns)) if all_oos_returns else max(1, len(oos_sharpes) * 30)
        oos_skew = 0.0
        oos_kurtosis = 3.0
        if all_oos_returns and len(all_oos_returns) >= 10:
            n = len(all_oos_returns)
            mean_r = sum(all_oos_returns) / n
            var_r = sum((r - mean_r) ** 2 for r in all_oos_returns) / max(1, n - 1)
            std_r = math.sqrt(var_r) if var_r > 0 else 1e-10
            if std_r > 1e-10:
                oos_skew = sum((r - mean_r) ** 3 for r in all_oos_returns) / (n * std_r ** 3)
                oos_kurtosis = sum((r - mean_r) ** 4 for r in all_oos_returns) / (n * std_r ** 4)
        try:
            dsr, pval = deflated_sharpe_ratio(
                observed_sharpe=mean_oos,
                n_trials=max(1, total_trials),
                n_returns=n_returns_actual,
                skewness=oos_skew,
                kurtosis=oos_kurtosis,
            )
            result.raw_sharpe = mean_oos
            result.deflated_sharpe = dsr
            result.dsr_n_trials = total_trials
            result.dsr_pvalue = pval
            if pval > 0.05:
                result.warnings.append(
                    f"DSR p-value {pval:.3f} > 0.05 — observed Sharpe may be due to selection bias"
                )
        except ImportError:
            result.warnings.append("scipy not available — skipping Deflated Sharpe Ratio")
            pval = 0.0

        # Holm-Bonferroni and BH FDR multi-strategy correction
        if len(oos_sharpes) >= 2 and pval > 0:
            oos_pvalues = []
            for ws in oos_sharpes:
                try:
                    _, wp = deflated_sharpe_ratio(
                        observed_sharpe=ws,
                        n_trials=max(1, total_trials),
                        n_returns=n_returns_actual,
                        skewness=oos_skew,
                        kurtosis=oos_kurtosis,
                    )
                    oos_pvalues.append(wp)
                except ImportError:
                    oos_pvalues.append(1.0)

            holm_passes = holm_bonferroni_correction(oos_pvalues)
            bh_passes = bh_fdr_correction(oos_pvalues)
            result.holm_bonferroni_pass = any(holm_passes)
            result.bh_fdr_pass = any(bh_passes)

            if not result.holm_bonferroni_pass:
                result.warnings.append(
                    "No OOS window survives Holm-Bonferroni correction — all may be spurious"
                )
            if not result.bh_fdr_pass:
                result.warnings.append(
                    "No OOS window survives BH FDR correction — high false discovery risk"
                )

        # Block bootstrap (uses OOS daily returns collected above)
        if all_oos_returns and len(all_oos_returns) >= 30:
            block_size = max(30, config.block_size_minutes)
            percentile = block_bootstrap_test(
                daily_returns=all_oos_returns,
                observed_sharpe=mean_oos,
                block_size=block_size,
                n_replications=config.block_bootstrap_replications,
                seed=config.monte_carlo_seed,
            )
            result.bootstrap_percentile = percentile
            if percentile < 0.95:
                result.warnings.append(
                    f"Block bootstrap percentile {percentile:.2f} < 0.95 — strategy may not be significant"
                )

        # Fee stress test (over the best OOS window)
        best_oos_window = max(windows, key=lambda w: w.oos_sharpe)
        if best_oos_window.oos_result:
            maker_ratio = best_oos_window.oos_result.maker_fill_ratio
            base_fee_drag = float(best_oos_window.oos_result.avg_slippage_bps) / 100.0
            margin, sharpe_at_levels, sharpe_stressed = fee_stress_test(
                base_sharpe=mean_oos,
                base_fee_drag_pct=base_fee_drag,
                fee_multipliers=config.fee_stress_multipliers,
                stressed_maker_ratio=config.stressed_maker_ratio,
                base_maker_ratio=maker_ratio,
            )
            result.fee_margin_of_safety = margin
            result.sharpe_at_fee_levels = sharpe_at_levels
            result.fee_stress_sharpes = [
                sharpe_at_levels.get(f"{m:.1f}x", 0.0) for m in config.fee_stress_multipliers
            ]
            result.sharpe_at_stressed_maker = sharpe_stressed
            if margin < 0.20:
                result.warnings.append(
                    f"Fee margin of safety {margin:.2f} < 0.20 — edge is fragile to fee changes"
                )

        # Parameter plateau test (uses best params from first window as anchor)
        if all_params and len(all_params) >= 2:
            best_params_anchor = all_params[0]
            if best_params_anchor:
                def _objective_proxy(params: dict[str, Any]) -> float:
                    avg_sharpe = 0.0
                    count = 0
                    for w in windows:
                        if w.best_params:
                            dist = sum(
                                abs(float(params.get(k, 0)) - float(w.best_params.get(k, 0)))
                                for k in params
                            )
                            if dist < 1e-6:
                                avg_sharpe += w.oos_sharpe
                                count += 1
                    return avg_sharpe / count if count else mean_oos

                plateau = param_plateau_test(
                    best_params=best_params_anchor,
                    objective_fn=_objective_proxy,
                )
                result.param_plateau_pass = plateau
                for name, passes in plateau.items():
                    if not passes:
                        result.warnings.append(
                            f"Parameter '{name}' fails plateau test (optimum is a spike, not a plateau)"
                        )

        # Regime-conditional OOS reporting
        regime_oos = self._compute_regime_oos_degradation(windows)
        if regime_oos:
            result.regime_oos_degradation = regime_oos
            overall_oos = mean_oos
            for regime, regime_sharpe in regime_oos.items():
                if abs(overall_oos) > 0.01 and abs(regime_sharpe - overall_oos) / abs(overall_oos) > 0.20:
                    result.warnings.append(
                        f"Regime '{regime}' OOS Sharpe {regime_sharpe:.2f} deviates > 20% "
                        f"from overall OOS Sharpe {overall_oos:.2f}"
                    )

        logger.info(
            "Walk-forward complete: %d windows, IS=%.2f, OOS=%.2f, ratio=%.2f, warnings=%d",
            len(windows), mean_is, mean_oos, oos_ratio, len(result.warnings),
        )
        return result

    def _run_windows(self) -> list[WindowResult]:
        """Run train/test for each window."""
        config = self._config
        base_config = config.sweep_config.base_config

        # Load data to determine total bars
        from controllers.backtesting.harness import BacktestHarness
        harness = BacktestHarness(base_config)
        candles = harness._load_candles()
        total_bars = len(candles)

        windows_spec = split_windows(total_bars, config)
        results: list[WindowResult] = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(windows_spec):
            logger.info(
                "Window %d/%d: train[%d:%d] test[%d:%d]",
                i + 1, len(windows_spec), train_start, train_end, test_start, test_end,
            )

            # Train: run sweep on train slice (save temp file)
            train_candles = candles[train_start:train_end]
            test_candles = candles[test_start:test_end]

            if not train_candles or not test_candles:
                continue

            # Run sweep on train data (simplified: run single backtest per combo)
            import tempfile
            from pathlib import Path

            from controllers.backtesting.data_store import save_candles
            from controllers.backtesting.sweep import SweepRunner

            with tempfile.TemporaryDirectory() as tmpdir:
                train_path = Path(tmpdir) / "train.parquet"
                test_path = Path(tmpdir) / "test.parquet"
                save_candles(train_candles, train_path)
                save_candles(test_candles, test_path)

                # Train sweep
                train_sweep = copy.deepcopy(config.sweep_config)
                train_sweep.base_config.data_source.data_path = str(train_path)
                runner = SweepRunner(train_sweep)
                sweep_results = runner.run()

                if not sweep_results or sweep_results[0].result is None:
                    continue

                best = sweep_results[0]
                is_sharpe = best.result.sharpe_ratio

                # Test: evaluate best params on test slice
                test_config = copy.deepcopy(train_sweep.base_config)
                test_config.data_source.data_path = str(test_path)
                for k, v in best.params.items():
                    test_config.strategy_config[k] = v

                test_harness = BacktestHarness(test_config)
                try:
                    test_result = test_harness.run()
                    oos_sharpe = test_result.sharpe_ratio
                except Exception as e:
                    logger.warning("Window %d test failed: %s", i, e)
                    oos_sharpe = 0.0
                    test_result = None

            # Record window
            train_start_date = datetime.fromtimestamp(
                train_candles[0].timestamp_ms / 1000, tz=UTC
            ).strftime("%Y-%m-%d")
            train_end_date = datetime.fromtimestamp(
                train_candles[-1].timestamp_ms / 1000, tz=UTC
            ).strftime("%Y-%m-%d")
            test_start_date = datetime.fromtimestamp(
                test_candles[0].timestamp_ms / 1000, tz=UTC
            ).strftime("%Y-%m-%d")
            test_end_date = datetime.fromtimestamp(
                test_candles[-1].timestamp_ms / 1000, tz=UTC
            ).strftime("%Y-%m-%d")

            results.append(WindowResult(
                window_index=i,
                train_start=train_start_date,
                train_end=train_end_date,
                test_start=test_start_date,
                test_end=test_end_date,
                best_params=best.params,
                is_sharpe=is_sharpe,
                oos_sharpe=oos_sharpe,
                oos_result=test_result,
            ))

        return results

    @staticmethod
    def _collect_oos_daily_returns(windows: list[WindowResult]) -> list[float]:
        """Collect all OOS daily returns across windows for bootstrap."""
        returns: list[float] = []
        for w in windows:
            if w.oos_result and w.oos_result.equity_curve:
                for snap in w.oos_result.equity_curve:
                    returns.append(float(snap.daily_return_pct))
        return returns

    @staticmethod
    def _compute_regime_oos_degradation(
        windows: list[WindowResult],
    ) -> dict[str, float]:
        """Compute per-regime OOS Sharpe from walk-forward windows.

        Aggregates regime-level metrics across all OOS windows using
        time-weighted averaging.  Returns ``{regime_name: weighted_oos_sharpe}``.
        """
        # Accumulate (sharpe * time_fraction) and total time per regime
        regime_weighted_sharpe: dict[str, float] = {}
        regime_total_time: dict[str, float] = {}

        for w in windows:
            if w.oos_result is None:
                continue
            for rm in w.oos_result.regime_metrics:
                if rm.time_fraction <= 0:
                    continue
                regime_weighted_sharpe[rm.regime_name] = (
                    regime_weighted_sharpe.get(rm.regime_name, 0.0)
                    + rm.sharpe * rm.time_fraction
                )
                regime_total_time[rm.regime_name] = (
                    regime_total_time.get(rm.regime_name, 0.0)
                    + rm.time_fraction
                )

        # Normalise to weighted average
        result: dict[str, float] = {}
        for regime, weighted_sum in regime_weighted_sharpe.items():
            total = regime_total_time.get(regime, 0.0)
            if total > 0:
                result[regime] = weighted_sum / total

        return result
