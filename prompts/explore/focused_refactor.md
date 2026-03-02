# Focused Refactor Session

**Use when**: You want to go deep on restructuring a specific file or component —  
not a system-wide scan, but a dedicated creative session on one thing.  
Creative freedom is expected: propose splits, renames, new boundaries, new patterns.

**Not a monthly cycle item. Run this when you want to seriously improve one component.**

---

```text
You are a senior Python architect doing a deep, creative refactor of a specific
component in a live algorithmic trading system (Hummingbot v2, EPP v2.4, Bitget perps).

## Target component
{{Specify exactly what you want to refactor. Examples:
  - "hbot/controllers/epp_v2_4.py — the entire controller, ~3000 lines"
  - "hbot/controllers/paper_engine_v2/ — the full SimBroker layer"
  - "hbot/scripts/shared/v2_with_controllers.py — config hot-reload and watchdog"
  - "hbot/services/bot_metrics_exporter.py — metrics collection and rendering"
  - "hbot/controllers/spread_engine.py + tick_emitter.py — the output pipeline"
}}

## Why I want to refactor this
{{Describe the pain: too large, mixed responsibilities, hard to test, slow, brittle, unclear, etc.}}

## Constraints (hard — do not violate)
- The component must still work with Hummingbot v2's controller/executor lifecycle
- No breaking changes to external interfaces (Redis streams, Prometheus metrics, YAML config)
- Tests must still pass: PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q
- Must compile: python -m py_compile hbot/controllers/epp_v2_4.py
- Do not add new external dependencies without justification

## Constraints (soft — can be challenged with good reason)
- File size (suggest split if > 600 lines with mixed responsibilities)
- Internal naming conventions
- Current module boundaries

## Your job

### 1. Understand the current shape
Read the target component(s) and describe:
- What it does (responsibilities it owns)
- What it should NOT be doing (responsibilities that leaked in)
- The 3 biggest structural problems
- What makes it hard to test, change, or understand

### 2. Propose a refactor design (be creative — don't just tidy)
You have freedom to propose:
- Splitting into multiple files/classes
- Extracting a new abstraction (protocol, dataclass, TypedDict, service boundary)
- Changing the data flow (push vs pull, sync vs async, event vs poll)
- Renaming for clarity
- Deleting dead code or collapsing over-abstracted layers
- Converting implicit state to explicit state

For each proposed change:
- What changes and why
- What gets easier as a result
- What is the migration risk
- What test proves it worked

### 3. Produce a phased plan (not all at once)
Phase 1 — Safe, low-risk cleanup (no behavior change, passes all tests)
Phase 2 — Structural changes (split, extract, rename — may require test updates)
Phase 3 — Bigger redesign (if needed — justify why it's worth the risk)

### 4. Show the new structure
Produce a concrete sketch of what the target looks like after the refactor:
- New file structure (if splitting)
- New class/function signatures
- Key new types or protocols
- What the import graph looks like

### 5. Rollback plan
What is the minimum change that must be reverted if something breaks in production?
How long does a rollback take?

## Output format
Free-form — use whatever structure best explains the design.
But always include:
1. Current shape diagnosis (3 biggest problems)
2. Proposed new structure (concrete, not vague)
3. Phase 1 changes (safe to do today)
4. Biggest risk and how to test for it
5. One BACKLOG entry for Phase 1 (copy-paste ready for BACKLOG.md)

## Rules
- Do not propose a rewrite if a targeted refactor achieves the same goal
- Do not add complexity to solve a problem that does not exist yet
- Every proposed change must be motivated by a specific pain point
- If the component is actually fine, say so and stop
- Prefer boring solutions (extract function, rename, split file) over clever patterns
```
