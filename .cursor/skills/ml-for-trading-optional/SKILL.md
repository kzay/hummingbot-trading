---
name: ml-for-trading-optional
description: Applies machine learning selectively to trading systems for regime detection, prediction, and feature engineering with strict baseline comparisons. Use when the user asks for ML models in trading, regime classifiers, return prediction, feature engineering, or guidance on when ML is justified versus simpler approaches.
---

# ML For Trading Optional

## Focus

Use ML only when it clearly outperforms robust non-ML baselines.

## When Not to Use

Do not use when a simple rules-based baseline has not been defined or validated yet.

## Default Policy

- Start with a deterministic baseline before ML.
- Prefer interpretable, stable feature sets over feature explosion.
- Validate under temporal splits only; never random shuffle for market time series.
- Track model drift and retraining triggers.

## Workflow

1. Define target:
   - direction, return bucket, volatility regime, or execution quality.
2. Build baseline:
   - rule-based or linear benchmark.
3. Engineer features:
   - price/volume, volatility state, order book context, cross-asset signals.
4. Evaluate with realistic protocol:
   - walk-forward and transaction-cost-aware post-processing.
5. Plan production controls:
   - model versioning, rollback, and confidence gating.

## Output Template

```markdown
## ML Decision Memo

- Problem framing:
- Baseline:
- Candidate model:
- Feature set:
- Validation protocol:
- Production controls:
- Go/No-go recommendation:
```

## Red Flags

- No baseline comparison.
- Leakage through future-aware feature construction.
- Offline metric gains without tradability impact.
- No monitoring for drift or regime shift.
