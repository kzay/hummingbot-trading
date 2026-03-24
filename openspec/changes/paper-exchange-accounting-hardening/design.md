## Context

The Paper Exchange Service (`hbot/services/paper_exchange_service/main.py`) and the in-process PaperDesk (`hbot/controllers/paper_engine_v2/portfolio.py`) are two independent position accounting implementations that must produce identical results for the same fill sequence. Today they diverge in three ways:

1. **Numeric types**: Paper Exchange uses `float`; portfolio uses `Decimal`.
2. **ONEWAY enforcement**: portfolio collapses dual-leg state on every access via `_collapse_oneway_legs`; Paper Exchange only does it at startup.
3. **No shared accounting core**: The Paper Exchange reimplements position math (`_open_long`, `_close_short`, etc.) independently from `accounting.apply_fill`.

There are zero tests covering the Paper Exchange Service's position accounting paths. The ONEWAY netting bug (explicit `position_action` bypassing netting) existed in the Paper Exchange but not in the portfolio because portfolio had a guard that was never replicated.

## Goals / Non-Goals

**Goals:**
- Make it impossible for ONEWAY positions to have dual legs in the Paper Exchange Service after any fill.
- Create a comprehensive regression test suite that covers every position accounting path in the Paper Exchange Service.
- Add cross-validation parity tests proving the Paper Exchange and portfolio produce identical outcomes.
- Add a runtime invariant check after every fill that detects and auto-repairs accounting violations before they accumulate.
- Reach a level of test coverage where any future accounting change either passes all tests or is rejected.

**Non-Goals:**
- Rewriting the Paper Exchange Service's persistence layer (atomic writes are adequate).
- Changing numeric precision from float to Decimal in the Paper Exchange Service (would require a larger migration; float64 precision is sufficient for BTC quantities at our scale).
- Adding HEDGE mode tests (we run ONEWAY exclusively; HEDGE paths are untouched).
- Changing the Paper Exchange Service's event processing architecture (command/market row ingestion).

## Decisions

### 1. Shared accounting adapter vs. full unification

**Decision**: Create a thin adapter function `_apply_fill_oneway` that implements the ONEWAY fill logic (close opposite leg, open remainder) as a single reusable function, used by `_apply_position_fill`. Do NOT merge the two systems into a single codebase.

**Why not full unification**: portfolio.py uses `Decimal` and a ledger; Paper Exchange uses `float` and no ledger. Merging them requires a numeric type migration across the entire service. The adapter approach is lower risk, achieves accounting consistency, and can be tested independently.

**Alternatives considered**:
- Call `accounting.apply_fill` from the Paper Exchange Service: rejected because `accounting.apply_fill` uses `Decimal` and `PositionState` dataclass; marshaling float↔Decimal on every fill adds complexity and latency in a hot path.
- Full port to Decimal: rejected as out of scope -- would touch 50+ functions in the Paper Exchange Service.

### 2. Post-fill ONEWAY invariant enforcement

**Decision**: After every `_apply_position_fill` call, assert `long_base == 0 or short_base == 0` for ONEWAY positions. On violation, log `POSITION_INVARIANT_VIOLATION`, auto-collapse to net, and increment a counter exposed in the heartbeat.

**Why**: Defense in depth. Even if the netting logic is correct, a future code change could introduce a new path that bypasses it. The assertion catches this immediately rather than letting dual-leg state accumulate silently.

### 3. Regression test architecture

**Decision**: Add tests to the existing `hbot/tests/services/test_paper_exchange_service.py` file, organized as a new test class `TestPaperExchangePositionAccounting`. Tests use direct function calls to `_apply_position_fill`, `_preview_fill_realized_pnl`, and `_sanitize_oneway_positions` with synthetic `OrderRecord` and `PositionRecord` objects.

**Test scenarios** (minimum):

| Category | Scenarios |
|----------|-----------|
| ONEWAY netting | Buy closes short first; sell closes long first; explicit `open_long` forced to `auto` |
| Flip-through-zero | Long→short via oversized sell; short→long via oversized buy |
| Reduce-then-open | Partial close + open remainder in single fill |
| Preview PnL | Correct PnL preview for close, open (no PnL), and flip fills |
| Sanitize startup | Dual-leg collapse; single-leg no-op; HEDGE skip |
| Multi-fill sequences | Pyramid entry + partial take + full close; alternating buys/sells |
| Dust handling | Near-zero quantities after close; `_MIN_FILL_EPSILON` boundary |

### 4. Cross-validation parity test

**Decision**: Create a new test file `hbot/tests/services/test_paper_exchange_accounting_parity.py` that replays identical fill sequences through both `_apply_position_fill` (Paper Exchange) and `accounting.apply_fill` (pure core), asserting position quantities and realized PnL match within float64 tolerance.

**Why a separate file**: This test imports from both `services.paper_exchange_service.main` and `controllers.paper_engine_v2.accounting`, crossing module boundaries. Isolating it makes dependencies explicit.

### 5. Mode string normalization

**Decision**: Standardize all ONEWAY/HEDGE mode checks to use `mode != "HEDGE"` (exact match, case-insensitive after upper). The current inconsistency where `_sanitize_oneway_positions` uses `"HEDGE" in mode` (substring) while `_apply_position_fill` uses `mode == "HEDGE"` (exact) is fixed by aligning both to exact match.

## Risks / Trade-offs

- **[Risk] Float precision drift**: Paper Exchange uses float64; portfolio uses Decimal. For BTC at ~$70k with quantities of 0.0001, float64 has ~15 significant digits which provides ample precision. But long accumulation chains (1000+ fills) could accumulate drift. → **Mitigation**: Parity tests use `math.isclose(rel_tol=1e-8)` tolerance; if drift exceeds this in realistic fill counts, we investigate.

- **[Risk] Performance of post-fill assertion**: Adding an `if` check after every fill is negligible compared to the fill processing itself (Redis I/O, JSON serialization). → **Mitigation**: The check is a simple comparison of two floats.

- **[Risk] Auto-repair masking bugs**: The post-fill invariant auto-repair could mask a deeper bug instead of crashing. → **Mitigation**: Every repair is logged as a WARNING with full context (position key, quantities before/after) and a counter is tracked in the heartbeat so alerting can trigger.

- **[Risk] Test maintenance burden**: Adding ~30 tests increases the maintenance surface. → **Mitigation**: Tests are pure function calls with synthetic data, no Docker/Redis dependencies. They run in <1s and are deterministic.
