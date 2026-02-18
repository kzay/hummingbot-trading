---
name: backtesting-validation
description: Defines rigorous backtesting and validation practices for trading systems, including fees, slippage, overfitting controls, and walk-forward analysis. Use when the user asks to evaluate strategy credibility, build realistic simulators, tune validation splits, or design robust performance validation pipelines.
---

# Backtesting Validation

## Focus

Measure realistic performance and reduce false positives.

## When Not to Use

Do not use for exchange integration bugs or runtime infrastructure incidents unless they affect simulation assumptions directly.

## Minimum Standards

- Include all relevant costs: maker/taker fees, borrow/funding where applicable.
- Model slippage and execution delay explicitly.
- Separate in-sample development from out-of-sample evaluation.
- Use walk-forward or rolling windows for non-stationary markets.

## Workflow

1. Define simulation assumptions:
   - order types, fill model, latency, fees, and slippage regime.
2. Build split protocol:
   - train/validate/test or anchored/rolling walk-forward.
3. Evaluate metrics:
   - CAGR, Sharpe, max drawdown, Calmar, turnover, hit ratio.
4. Stress-test:
   - volatility spikes, spread widening, liquidity drought.
5. Document overfitting controls and model selection logic.

## Output Template

```markdown
## Validation Report

- Data period and splits:
- Cost model:
- Slippage model:
- Core metrics:
- Walk-forward results:
- Stress scenarios:
- Overfitting checks:
```

## Red Flags

- Ignoring costs and assuming perfect fills.
- Hyperparameter tuning on the final test set.
- Reporting only best run instead of distribution.
- No stability checks across regimes.
