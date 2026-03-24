## Context

The workspace has a mature backtesting stack (`BacktestHarness`, `ReplayHarness`, `SweepRunner`, `WalkForwardRunner`) and a paper engine (`PaperDesk` + fill models). Strategies are adapted for backtesting via `BacktestTickAdapter` protocol with 10+ concrete adapters. Experiment results are tracked in manual Markdown ledgers and flat JSON files with no immutable manifests or composite scoring.

The existing infrastructure works for individual runs but lacks the governance layer required to systematically reject overfitted strategies before they consume paper-trading time and capital. The research lab adds this layer on top without replacing anything.

## Goals / Non-Goals

**Goals:**

- Fix broken walk-forward code (fee stress, Holm-BH, DSR) so robustness evaluation actually works.
- Close the candle lookahead hole by enforcing `VisibleCandleRow` at the adapter boundary.
- Align replay and harness fill models so results are comparable.
- Provide a `StrategyCandidate` YAML format that captures hypothesis, logic, parameters, and required tests.
- Build a JSONL experiment registry that creates immutable run manifests (config hash, git SHA, data window, seed, fill model, result path).
- Implement a composite robustness scorer that penalises overfitting signals (IS/OOS gap, parameter instability, fee sensitivity, regime fragility).
- Add strategy lifecycle classification with configurable promotion gates.
- Deliver a CLI for batch evaluation: `python -m controllers.research.evaluate`.

**Non-Goals:**

- Replacing the existing `BacktestTickAdapter` protocol or adapter files — the research layer wraps them.
- Building a web UI or database server — the registry uses flat JSONL files.
- Implementing L2 order-book replay or calibrated microstructure simulation.
- Adding ML-based regime detection or signal generation (ROAD-10/11 scope).
- Modifying `epp_v2_4.py`, production runtime, or live connector code.

## Decisions

### D1: Research module location — `hbot/controllers/research/`

**Choice**: New top-level package under `controllers/`.
**Rationale**: Keeps research code near the backtesting code it wraps while respecting the strategy-isolation boundary (research never imports `bots/*`). Alternative was `hbot/research/` but that breaks the `PYTHONPATH=hbot` convention where all imports start with `controllers.*` or `services.*`.

### D2: StrategyCandidate as YAML + dataclass, not code subclass

**Choice**: Candidates are defined in YAML files parsed into a `StrategyCandidate` dataclass. The YAML references an adapter mode (from the existing adapter registry) and a parameter space.
**Rationale**: Keeps candidate definitions declarative and version-controllable. A code subclass approach would require Python files per candidate and tighter coupling. The adapter registry already maps `adapter_mode` strings to classes.

### D3: JSONL experiment registry, not SQLite

**Choice**: One JSONL file per candidate (`research/experiments/{candidate_name}.jsonl`), each line an immutable experiment manifest.
**Rationale**: JSONL is append-only, diff-friendly, and requires no dependencies. SQLite would add query power but complicates git tracking. The expected volume (hundreds, not millions of experiments) makes JSONL sufficient.

### D4: Composite robustness score formula

**Choice**: Weighted sum with configurable weights, default:

| Component | Weight | Input | Normalisation |
|-----------|--------|-------|---------------|
| OOS Sharpe | 0.25 | Mean OOS Sharpe across walk-forward windows | Clamped to [0, 3], divided by 3 |
| OOS degradation ratio | 0.20 | mean_oos / mean_is | 1.0 if ratio >= threshold, linearly decays to 0 at 0 |
| Parameter stability | 0.15 | 1 - mean CV of best params across windows | Clamped to [0, 1] |
| Fee stress margin | 0.15 | Min Sharpe across fee multipliers / base Sharpe | Clamped to [0, 1] |
| Regime stability | 0.15 | Min regime-conditional Sharpe / overall Sharpe | Clamped to [0, 1] |
| DSR pass | 0.10 | 1 if deflated Sharpe > 0, else 0 | Binary |

Final score in [0, 1]. Promotion gate default: score >= 0.55.

**Rationale**: No single metric captures robustness. The weighting penalises strategies that only work in-sample, in one regime, or with zero fees. Weights are configurable via YAML to allow experimentation on the scoring itself.

### D5: VisibleCandleRow — masking, not copying

**Choice**: `VisibleCandleRow` wraps the original `CandleRow` and returns `math.nan` for `high`, `low`, `close` when `step_index < max_step`. At the final step, it delegates to the real values.
**Rationale**: Zero-copy, zero-allocation on the hot path. Returning `nan` (not 0 or `open`) ensures any accidental use produces obviously wrong results rather than subtle bias. Alternative of creating a new dataclass per tick would increase GC pressure on long backtests.

### D6: Targeted fixes as separate tasks from research infra

**Choice**: Walk-forward fixes, replay fill alignment, and candle guard are implemented first (Phases 1-2), before the research module (Phases 3-5).
**Rationale**: The research module depends on correct walk-forward and fee-stress results. Fixing the foundation first avoids building governance on broken data.

## Risks / Trade-offs

- **[Risk] VisibleCandleRow breaks existing adapters** → Mitigation: adapters that legitimately need bar context (e.g., for warmup ATR) use `warmup()` which receives full candles. During tick, only `open` and `volume` are safe; existing adapters must be audited. A flag `allow_full_candle=True` on the adapter protocol can opt-out for backward compatibility during transition.
- **[Risk] Composite score weights are subjective** → Mitigation: weights are YAML-configurable, not hardcoded. The default set is documented with rationale. Users can run sensitivity analysis on the scorer itself.
- **[Risk] JSONL registry grows large** → Mitigation: one file per candidate, not global. Archiving promoted/rejected candidates moves their JSONL to an archive directory. Expected scale: <1000 lines per candidate.
- **[Risk] Walk-forward fee_stress fix may change existing results** → Mitigation: fee stress was broken (TypeError), so no existing results depend on it. The fix produces new data, not changed data.
- **[Risk] Research module couples to backtesting internals** → Mitigation: research imports only public types from `backtesting.types` and calls `BacktestHarness`, `SweepRunner`, `WalkForwardRunner` via their documented APIs. No monkey-patching of internals.
