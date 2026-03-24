## 1. ONEWAY Netting Guard and Mode Normalization

- [ ] 1.1 Align `_sanitize_oneway_positions` mode check from `"HEDGE" in mode` to `mode != "HEDGE"` (exact match after `.strip().upper()`) in `hbot/services/paper_exchange_service/main.py`
- [ ] 1.2 Verify that the existing ONEWAY netting guard in `_apply_position_fill` (action forced to `auto` when `mode != "HEDGE"`) is correctly placed before the HEDGE/ONEWAY branch
- [ ] 1.3 Verify that the existing ONEWAY netting guard in `_preview_fill_realized_pnl` is correctly placed before the HEDGE/ONEWAY branch

## 2. Post-Fill ONEWAY Invariant Enforcement

- [ ] 2.1 Add `_enforce_oneway_invariant(position, mode, key)` function that checks `long_base > epsilon and short_base > epsilon`, auto-collapses to net, logs `POSITION_INVARIANT_VIOLATION`, and increments `state.oneway_invariant_violations` counter
- [ ] 2.2 Call `_enforce_oneway_invariant` at the end of `_apply_position_fill` for non-HEDGE positions
- [ ] 2.3 Add `oneway_invariant_violations` counter to `PaperExchangeState` dataclass and expose it in the heartbeat payload
- [ ] 2.4 Compile and verify no syntax errors: `python -m py_compile services/paper_exchange_service/main.py`

## 3. Regression Tests — ONEWAY Netting

- [ ] 3.1 Create `TestPaperExchangePositionAccounting` test class in `hbot/tests/services/test_paper_exchange_service.py` with helper to create synthetic `OrderRecord` and `PositionRecord`
- [ ] 3.2 Test: buy closes short then opens long (reduce-then-open)
- [ ] 3.3 Test: sell closes long then opens short (reduce-then-open)
- [ ] 3.4 Test: buy with no opposing position opens long
- [ ] 3.5 Test: sell with no opposing position opens short
- [ ] 3.6 Test: exact close to flat (buy exactly matches short, sell exactly matches long)
- [ ] 3.7 Test: explicit `open_long` action normalized to `auto` in ONEWAY (netting occurs)
- [ ] 3.8 Test: explicit `open_short` action normalized to `auto` in ONEWAY (netting occurs)

## 4. Regression Tests — Flip-Through-Zero

- [ ] 4.1 Test: long to short flip (sell qty > long_base): correct PnL on close leg, correct short_base and avg_entry on open leg
- [ ] 4.2 Test: short to long flip (buy qty > short_base): correct PnL on close leg, correct long_base and avg_entry on open leg

## 5. Regression Tests — Preview PnL

- [ ] 5.1 Test: `_preview_fill_realized_pnl` for ONEWAY close (sell closing long)
- [ ] 5.2 Test: `_preview_fill_realized_pnl` for ONEWAY open (buy from flat, PnL = 0)
- [ ] 5.3 Test: `_preview_fill_realized_pnl` with explicit `open_short` action against long position in ONEWAY (normalized to auto, PnL computed)

## 6. Regression Tests — Sanitize Startup

- [ ] 6.1 Test: `_sanitize_oneway_positions` collapses dual-leg ONEWAY to net
- [ ] 6.2 Test: `_sanitize_oneway_positions` leaves single-leg ONEWAY unchanged
- [ ] 6.3 Test: `_sanitize_oneway_positions` skips HEDGE positions
- [ ] 6.4 Test: `_sanitize_oneway_positions` handles net-zero (both legs equal) correctly

## 7. Regression Tests — Multi-Fill Sequences and Dust

- [ ] 7.1 Test: pyramid entry (3 buys at increasing prices) then full unwind (3 sells): correct VWAP, correct total PnL
- [ ] 7.2 Test: 10 alternating same-size buy/sell at same price: final position flat, PnL ≈ 0
- [ ] 7.3 Test: fill quantity below `_MIN_FILL_EPSILON` is no-op
- [ ] 7.4 Test: close leaving dust below `_MIN_FILL_EPSILON` results in flat position

## 8. Cross-Validation Parity Tests

- [ ] 8.1 Create `hbot/tests/services/test_paper_exchange_accounting_parity.py` with helper to run same fill sequence through Paper Exchange `_apply_position_fill` and `accounting.apply_fill`
- [ ] 8.2 Parity test: simple open-add-close sequence (position qty and PnL match within tolerance)
- [ ] 8.3 Parity test: flip-through-zero sequence
- [ ] 8.4 Parity test: 10-fill pyramid and unwind
- [ ] 8.5 Parity test: 20 alternating direction fills of varying sizes
- [ ] 8.6 Parity test: VWAP entry price matches after same-direction accumulation

## 9. Post-Fill Invariant Tests

- [ ] 9.1 Test: `_enforce_oneway_invariant` no-op when single leg
- [ ] 9.2 Test: `_enforce_oneway_invariant` collapses dual-leg and logs warning
- [ ] 9.3 Test: invariant violation counter increments

## 10. Final Verification

- [ ] 10.1 Run full regression suite: `PYTHONPATH=hbot python -m pytest hbot/tests/services/test_paper_exchange_service.py -x -q -k "TestPaperExchangePositionAccounting"`
- [ ] 10.2 Run parity suite: `PYTHONPATH=hbot python -m pytest hbot/tests/services/test_paper_exchange_accounting_parity.py -x -q`
- [ ] 10.3 Run existing PE tests to confirm no regressions: `PYTHONPATH=hbot python -m pytest hbot/tests/services/test_paper_exchange_service.py -x -q`
- [ ] 10.4 Compile main module: `python -m py_compile hbot/services/paper_exchange_service/main.py`
- [ ] 10.5 Restart paper-exchange-service and verify no startup errors in logs
- [ ] 10.6 Verify heartbeat includes `oneway_invariant_violations: 0` after restart
