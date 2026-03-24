"""Parameter sweep engine — grid, random (LHS), and optional Optuna search.

Generates parameter combinations, runs backtests in parallel via
``multiprocessing.Pool``, and aggregates results ranked by the chosen objective.
"""
from __future__ import annotations

import itertools
import logging
import math
import multiprocessing
import os
import traceback
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import (
    BacktestConfig,
    BacktestResult,
    ParamSpace,
    SweepConfig,
    SweepResult,
)

logger = logging.getLogger(__name__)

_MAX_GRID_WARNING = 10_000


# ---------------------------------------------------------------------------
# Parameter space expansion
# ---------------------------------------------------------------------------

def _expand_grid(space: ParamSpace) -> list[Any]:
    """Expand a single ParamSpace into a list of values."""
    if space.mode == "grid":
        return list(space.values)
    elif space.mode == "range":
        if space.step <= 0:
            raise ValueError(f"range mode requires step > 0; got {space.step}")
        vals = []
        v = space.min_val
        while v <= space.max_val + 1e-12:
            vals.append(round(v, 10))
            v += space.step
        return vals
    elif space.mode == "log_range":
        if space.num_points <= 0:
            raise ValueError(f"log_range mode requires num_points > 0; got {space.num_points}")
        if space.min_val <= 0 or space.max_val <= 0:
            raise ValueError("log_range requires min_val > 0 and max_val > 0")
        log_min = math.log10(space.min_val)
        log_max = math.log10(space.max_val)
        return [
            round(10 ** (log_min + (log_max - log_min) * i / max(1, space.num_points - 1)), 10)
            for i in range(space.num_points)
        ]
    else:
        raise ValueError(f"Unknown param space mode: {space.mode!r}")


def generate_grid(spaces: list[ParamSpace]) -> list[dict[str, Any]]:
    """Generate Cartesian product of all parameter spaces."""
    expanded = {s.name: _expand_grid(s) for s in spaces}
    names = [s.name for s in spaces]
    combos = list(itertools.product(*(expanded[n] for n in names)))
    total = len(combos)
    if total > _MAX_GRID_WARNING:
        logger.warning("Grid search: %d combinations (>%d). Consider random/bayesian.", total, _MAX_GRID_WARNING)
    return [dict(zip(names, vals, strict=True)) for vals in combos]


# ---------------------------------------------------------------------------
# Latin Hypercube Sampling (LHS)
# ---------------------------------------------------------------------------

def _lhs_samples(
    spaces: list[ParamSpace],
    n_samples: int,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate Latin Hypercube Samples for continuous parameter spaces.

    For grid-mode params, samples uniformly from the discrete set.
    For range/log_range params, uses proper LHS stratification.
    """
    import random as rng_mod
    rng = rng_mod.Random(seed)
    n = n_samples
    results: list[dict[str, Any]] = []

    # Build per-dimension intervals
    dims: list[tuple[str, list[float]]] = []
    for space in spaces:
        if space.mode == "grid":
            # Uniform sampling from discrete set
            values = [float(v) if isinstance(v, (int, float, Decimal)) else v for v in space.values]
            samples = [rng.choice(values) for _ in range(n)]
            dims.append((space.name, samples))
        else:
            # LHS stratification
            lo = space.min_val
            hi = space.max_val
            is_log = space.mode == "log_range"
            if is_log:
                lo = math.log10(lo)
                hi = math.log10(hi)
            # Create n strata and sample one point from each
            perm = list(range(n))
            rng.shuffle(perm)
            samples = []
            for i in range(n):
                u = (perm[i] + rng.random()) / n
                val = lo + u * (hi - lo)
                if is_log:
                    val = 10 ** val
                samples.append(round(val, 10))
            dims.append((space.name, samples))

    # Assemble into list of dicts
    for i in range(n):
        results.append({name: samples[i] for name, samples in dims})
    return results


# ---------------------------------------------------------------------------
# Worker function (must be top-level for pickle)
# ---------------------------------------------------------------------------

def _run_single_backtest(args: tuple[dict[str, Any], dict]) -> tuple[dict[str, Any], dict | None, str]:
    """Worker function for multiprocessing.Pool.

    Args is (params_dict, base_config_dict).
    Returns (params, result_dict_or_None, error_string).
    """
    params, base_cfg_dict = args
    try:
        from controllers.backtesting.config_loader import _parse_backtest_config
        from controllers.backtesting.harness import BacktestHarness

        config = _parse_backtest_config(base_cfg_dict)
        for key, val in params.items():
            config.strategy_config[key] = val

        harness = BacktestHarness(config)
        result = harness.run()
        return params, _result_to_dict(result), ""
    except Exception as exc:
        return params, None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


def _result_to_dict(result: BacktestResult) -> dict:
    """Convert BacktestResult to a simple dict for pickling across processes."""
    return {
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "total_return_pct": result.total_return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "calmar_ratio": result.calmar_ratio,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "fill_count": result.fill_count,
        "total_ticks": result.total_ticks,
        "run_duration_s": result.run_duration_s,
    }


# ---------------------------------------------------------------------------
# Sweep runner
# ---------------------------------------------------------------------------

class SweepRunner:
    """Run parameter sweeps with grid, random, or bayesian search."""

    def __init__(self, config: SweepConfig) -> None:
        self._config = config

    def run(self) -> list[SweepResult]:
        """Execute the sweep and return ranked results."""
        config = self._config

        # Generate parameter combinations
        if config.sweep_mode == "grid":
            param_combos = generate_grid(config.param_spaces)
        elif config.sweep_mode == "random":
            param_combos = _lhs_samples(
                config.param_spaces, config.n_samples, config.seed,
            )
        elif config.sweep_mode == "bayesian":
            return self._run_bayesian()
        else:
            raise ValueError(f"Unknown sweep_mode: {config.sweep_mode!r}")

        logger.info("Sweep: %d parameter combinations, mode=%s", len(param_combos), config.sweep_mode)

        # Prepare worker args
        base_cfg_dict = _backtest_config_to_dict(config.base_config)
        worker_args = [(params, base_cfg_dict) for params in param_combos]

        # Run with multiprocessing
        n_workers = config.workers if config.workers > 0 else max(1, os.cpu_count() - 1)
        n_workers = min(n_workers, len(param_combos))

        results: list[SweepResult] = []
        if n_workers <= 1 or len(param_combos) <= 2:
            # Sequential for small sweeps or single worker
            for i, args in enumerate(worker_args):
                logger.info("Sweep run %d/%d", i + 1, len(param_combos))
                params, result_dict, error = _run_single_backtest(args)
                results.append(_make_sweep_result(params, result_dict, error))
        else:
            logger.info("Sweep: launching %d workers", n_workers)
            with multiprocessing.Pool(processes=n_workers) as pool:
                for i, (params, result_dict, error) in enumerate(
                    pool.imap_unordered(_run_single_backtest, worker_args)
                ):
                    results.append(_make_sweep_result(params, result_dict, error))
                    if (i + 1) % 10 == 0:
                        logger.info("Sweep progress: %d/%d", i + 1, len(param_combos))

        # Rank by objective (descending)
        objective = config.objective
        results.sort(
            key=lambda r: _get_objective(r, objective),
            reverse=True,
        )
        for i, r in enumerate(results):
            r.rank = i + 1

        logger.info(
            "Sweep complete: %d runs, best %s=%.4f",
            len(results), objective,
            _get_objective(results[0], objective) if results else 0,
        )
        return results

    def _run_bayesian(self) -> list[SweepResult]:
        """Run Optuna-based bayesian optimization."""
        try:
            import optuna
        except ImportError as exc:
            raise ImportError(
                "Optuna not installed. Install with: pip install optuna"
            ) from exc

        config = self._config
        base_cfg_dict = _backtest_config_to_dict(config.base_config)
        results: list[SweepResult] = []

        def objective(trial: optuna.Trial) -> float:
            params: dict[str, Any] = {}
            for space in config.param_spaces:
                if space.mode == "grid":
                    params[space.name] = trial.suggest_categorical(space.name, space.values)
                elif space.mode == "log_range":
                    params[space.name] = trial.suggest_float(
                        space.name, space.min_val, space.max_val, log=True,
                    )
                else:
                    params[space.name] = trial.suggest_float(
                        space.name, space.min_val, space.max_val,
                    )

            p, result_dict, error = _run_single_backtest((params, base_cfg_dict))
            sr = _make_sweep_result(p, result_dict, error)
            results.append(sr)

            if result_dict is None:
                return float("-inf")
            return result_dict.get(config.objective, 0.0)

        sampler = optuna.samplers.TPESampler(seed=config.seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=config.n_samples, show_progress_bar=False)

        # Rank results
        results.sort(key=lambda r: _get_objective(r, config.objective), reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backtest_config_to_dict(config: BacktestConfig) -> dict:
    """Serialize BacktestConfig to a dict for cross-process pickling."""
    return {
        "strategy_class": config.strategy_class,
        "strategy_config": dict(config.strategy_config),
        "data_source": {
            "exchange": config.data_source.exchange,
            "pair": config.data_source.pair,
            "resolution": config.data_source.resolution,
            "start_date": config.data_source.start_date,
            "end_date": config.data_source.end_date,
            "instrument_type": config.data_source.instrument_type,
            "data_path": config.data_source.data_path,
        },
        "initial_equity": str(config.initial_equity),
        "fill_model": config.fill_model,
        "fill_model_preset": config.fill_model_preset,
        "seed": config.seed,
        "leverage": config.leverage,
        "step_interval_s": config.step_interval_s,
        "warmup_bars": config.warmup_bars,
        "synthesis": {
            "base_spread_bps": str(config.synthesis.base_spread_bps),
            "vol_spread_mult": str(config.synthesis.vol_spread_mult),
            "depth_levels": config.synthesis.depth_levels,
            "depth_decay": str(config.synthesis.depth_decay),
            "base_depth_size": str(config.synthesis.base_depth_size),
            "steps_per_bar": config.synthesis.steps_per_bar,
            "seed": config.synthesis.seed,
        },
        "output_dir": config.output_dir,
        "run_id": config.run_id,
    }


def _make_sweep_result(params: dict[str, Any], result_dict: dict | None, error: str) -> SweepResult:
    """Build a SweepResult from worker output."""
    sr = SweepResult(params=params, error=error)
    if result_dict is not None:
        result = BacktestResult()
        for k, v in result_dict.items():
            if hasattr(result, k):
                setattr(result, k, v)
        sr.result = result
    return sr


def _get_objective(sr: SweepResult, objective: str) -> float:
    """Extract the objective metric from a SweepResult for ranking."""
    if sr.result is None:
        return float("-inf")
    return getattr(sr.result, objective, 0.0)
