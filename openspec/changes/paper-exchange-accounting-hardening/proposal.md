## Why

The Paper Exchange Service is the authoritative ledger for all paper-trading fills, positions, and PnL. It must behave identically to a real exchange -- that is the entire point of paper trading. A critical ONEWAY netting bug was discovered where explicit `position_action` hints (`open_long`/`open_short`) bypassed the netting logic, causing both long and short legs to accumulate simultaneously with zero realized PnL. This affected bot3, bot5, bot6, and bot7. The root cause is that the Paper Exchange Service's `_apply_position_fill` has its own independent position accounting implementation that diverged from the PaperDesk v2 (`portfolio.py`) which had the correct guard. There are zero regression tests covering the Paper Exchange Service's position logic, meaning any future change can silently re-introduce accounting bugs. A paper engine that silently loses track of positions and PnL is worse than no paper engine at all.

## What Changes

- **Unify accounting**: Extract position fill logic into a single shared function used by both the Paper Exchange Service (`main.py`) and the in-process PaperDesk (`portfolio.py`), eliminating the current two independent implementations that can silently diverge.
- **Enforce ONEWAY invariants continuously**: Add a post-fill ONEWAY collapse check in the Paper Exchange Service (not just at startup), matching `portfolio.py`'s behavior of collapsing on every access.
- **Comprehensive regression test suite**: Add deterministic tests for every position accounting path in the Paper Exchange Service: ONEWAY netting, flip-through-zero, reduce-then-open, explicit action normalization, `_preview_fill_realized_pnl`, and `_sanitize_oneway_positions`.
- **Cross-validation parity tests**: Add tests that replay identical fill sequences through both the Paper Exchange Service and `portfolio.py`/`accounting.py`, asserting identical position state and realized PnL.
- **Position state assertion harness**: Add a runtime assertion after every `_apply_position_fill` call that verifies ONEWAY invariants hold (at most one leg non-zero), logging and auto-repairing violations with a `POSITION_INVARIANT_VIOLATION` warning.

## Capabilities

### New Capabilities
- `pe-oneway-accounting`: Deterministic ONEWAY position netting, flip-through-zero, and reduce-then-open logic in the Paper Exchange Service with continuous invariant enforcement.
- `pe-accounting-parity`: Cross-validation contract between Paper Exchange Service and PaperDesk portfolio ensuring identical position/PnL outcomes for any fill sequence.
- `pe-regression-suite`: Comprehensive regression test suite covering all position accounting paths in the Paper Exchange Service.

### Modified Capabilities

## Impact

- `hbot/services/paper_exchange_service/main.py` -- position accounting functions (`_apply_position_fill`, `_preview_fill_realized_pnl`, `_open_long`, `_open_short`, `_close_long`, `_close_short`, `_sanitize_oneway_positions`)
- `hbot/controllers/paper_engine_v2/portfolio.py` -- `settle_fill`, `_collapse_oneway_legs` (potential refactor to share accounting core)
- `hbot/controllers/paper_engine_v2/accounting.py` -- may be extended to serve both systems
- `hbot/tests/services/test_paper_exchange_service.py` -- major additions
- New test file(s) for cross-validation parity
- All running bots (bot1-bot7) benefit from corrected accounting; no config changes needed
