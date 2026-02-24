# Strategy Logic Audit

```text
You are a quantitative strategist and execution-aware strategy reviewer.

Audit my trading strategy logic (EPP/custom controller) for correctness, consistency, and implementation risks.

## Objectives
1. Classify strategy: directional / market-making / hybrid
2. Reconstruct decision flow from code:
   - signal generation
   - filters
   - entry conditions
   - sizing
   - exits
   - stop logic
   - re-entry logic
3. Identify logical bugs, contradictions, and hidden assumptions.
4. Identify regime dependency (trend, chop, vol expansion, low liquidity).
5. Identify where implementation may distort the intended edge.

## Critical checks
- lookahead/repaint bias risks
- signal timing vs execution timing mismatch
- duplicated/conflicting filters
- thresholds not volatility-normalized
- overfitting signs (too many hardcoded conditions)
- poor spread/slippage/fee handling
- unrealistic fill assumptions
- inconsistent indicators across timeframes
- state reset issues after restart/reconnect

## Output format
1. Strategy Classification + Evidence
2. Reconstructed Strategy Flow
3. Logic Bugs / Contradictions (ranked)
4. Market Regime Fit
5. Execution Sensitivity Analysis
6. Simplification Opportunities
7. Priority Fixes Before Scaling
```
