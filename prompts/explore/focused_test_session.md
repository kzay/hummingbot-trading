# Focused Test Session

**Use when**: You want to deeply cover a specific module with tests —  
not a system-wide coverage scan, but a dedicated session to get one component well-tested.  
Creative: design tests that actually find bugs, not tests that just tick coverage boxes.

---

```text
You are a testing specialist and quant engineer writing tests for a live trading system.

## Target module
{{Specify what you want to test. Examples:
  - "hbot/controllers/epp_v2_4.py — specifically the PnL governor and soft-pause logic"
  - "hbot/controllers/paper_engine_v2/matching_engine.py — fill priority and partial fills"
  - "hbot/services/reconciliation_service/main.py — parity check logic and edge cases"
  - "hbot/scripts/shared/v2_with_controllers.py — config hot-reload failure paths"
  - "hbot/controllers/spread_engine.py — spread computation correctness"
  - "hbot/services/kill_switch/main.py — partial cancel escalation"
}}

## What I already have
{{Paste existing test file content, or describe what tests exist, or say "none"}}

## My goal for this session
{{Choose one or more:
  - "Cover the happy path end-to-end"
  - "Cover all edge cases and boundary conditions"
  - "Cover all failure/error paths"
  - "Write tests that would have caught the bugs we've already hit"
  - "Make the module fully testable (might require small refactors)"
  - "Get coverage from X% to Y%"
}}

## System context
- Test runner: pytest, from workspace root with PYTHONPATH=hbot
- Run: PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q
- Coverage: PYTHONPATH=hbot python -m pytest hbot/tests/ --cov=hbot --cov-report=term-missing
- No real Redis, no real exchange, no real time.sleep() unless marked integration
- Mocking: use unittest.mock (patch, MagicMock) or pytest fixtures
- Known mocking targets: Redis client, Hummingbot connector, datetime.now(), filesystem I/O

## Known bugs that tests should prevent regression on
- Pydantic ValidationError in config hot-reload caused bot freeze (fixed in v2_with_controllers.py)
- NameError 'fills_csv' in reconciliation_service caused crash (fixed)
- Event store ack-before-write caused silent data loss (fixed — deferred ack pattern)
- Kill switch partial cancel not escalated as error (fixed)
- bot_metrics_exporter silently serving stale cache on exception (fixed)

## Your job

### 1. Analyze the target module
- What are the critical behaviors that must never break?
- What are the edge cases most likely to cause silent bugs?
- What failure paths exist that are currently untested?
- Are there any testability problems in the current code? (if so, note the smallest refactor that fixes it)

### 2. Design the test suite
Design tests grouped into:

**A) Happy path tests** — baseline correctness
What is the minimal set that proves the module works as intended?

**B) Boundary / parametrize tests** — edge inputs
What input values should be table-driven?
(e.g. spread = 0, size = min, governor_mult = 0.0, base_pct = max_base_pct)

**C) Failure path tests** — error handling
What happens when Redis is down? When the config is invalid? When a fill arrives twice?

**D) Regression tests** — prevent known bugs from returning
Write one test per known past bug that would have caught it.

**E) Property / invariant tests** (optional but valuable)
Is there a property that must always hold?
(e.g. "sum of level allocations never exceeds 1.0", "PnL after fees is always < PnL before fees")

### 3. Write the tests
Produce complete, runnable pytest code.

Requirements:
- Each test has a clear docstring explaining what it tests and why it could fail
- Use pytest.mark.parametrize for all boundary cases
- Mock all external dependencies (Redis, filesystem, time)
- Tests are deterministic — same input, same output, every time
- Test names follow: test_{what}_{condition}_{expected_outcome}

### 4. Identify refactors needed for testability
If the current code is hard to test (e.g. side effects in __init__, global state, no dependency injection),
propose the minimal change that makes it testable without changing behavior.

## Output format
1. Analysis: critical behaviors + untested paths + testability issues
2. Test plan table (test name | type | what it covers | priority)
3. Complete test code (runnable, no placeholders)
4. Refactor needed (if any) — minimal, safe change only
5. How to run: exact command

## Rules
- Tests must be runnable with zero setup beyond PYTHONPATH=hbot
- No test should take > 1 second without being marked @pytest.mark.slow
- Never test implementation details — test observable behavior
- A test that always passes is worse than no test
- If you find a real bug while writing the test, flag it: **BUG FOUND**: description
- Treat listed files/examples as anchors, not limits; include adjacent modules when required for realism.
- If context can be inferred from repo artifacts, fill it; if unknown, state assumptions and continue.
```
