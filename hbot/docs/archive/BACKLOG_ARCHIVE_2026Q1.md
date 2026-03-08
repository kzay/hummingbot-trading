# Backlog Archive — 2026 Q1

This archive captures the completed tracks removed from `hbot/BACKLOG.md` during active-backlog cleanup.

- Cleanup date: `2026-03-05`
- Scope: move completed work out of the operational queue so only active/blocked items remain in the main backlog.
- Full historical task-level detail remains available in repository history before this cleanup revision.

---

## Completed Program Tracks

### BUILD_SPEC — Multi-Bot Desk Audit Follow-Up
- Status at cleanup: `done`
- Focus delivered:
  - preflight reconciliation gate
  - checklist evidence collector
  - Telegram alerting validator
  - promotion gate integration and supporting tests

### BUILD_SPEC — Canonical Data Plane Migration (Timescale)
- Status at cleanup: `done`
- Focus delivered:
  - Timescale-capable baseline and schema/bootstrap
  - event-store dual-write and DB-first fallback reads
  - cutover guardrails and rollback drill support

### BUILD_SPEC — Pro Quality Upgrade Program (ARCH/TECH/PERF/FUNC)
- Status at cleanup: `done`
- Focus delivered:
  - architecture/service-interface contract refresh
  - strict-cycle default-on gate hardening
  - threshold-input completeness and diagnostics
  - load/perf regression and functional validation ladder

### BUILD_SPEC — Semi-Pro Paper Exchange Service (exchange mirror)
- Status at cleanup: `done`
- Focus delivered:
  - contract-first service extraction and adapter shadow/active modes
  - deterministic matching, recovery, idempotency, namespace isolation
  - parity/replay/load/reliability/security/DR thresholds wired to strict cycle
  - runtime compatibility and license-boundary documentation artifacts

---

## Completed Roadmap / Reliability Tracks

- P0/P1/P2 foundational backlog items (safety, reliability, docs, alerting, testing): `done`
- ROAD-2 walk-forward backtest engine: `done`
- ROAD-3 order-book imbalance signal: `done`
- ROAD-4 Kelly sizing infrastructure: `done` (default-off)
- ROAD-6 TCA report: `done`
- ROAD-7 incident playbooks: `done`
- ROAD-8 secrets hygiene docs and procedure: `done` (human operations continue)
- ROAD-9 second strategy lane and portfolio allocation wiring: `done`
- STRATEGY_LOOP — Iteration (2026-03-02): `done`

---

## Archive Usage

- Use `hbot/BACKLOG.md` for execution planning and current go/no-go decisions.
- Use this archive for program-level historical context.
- For forensic task-by-task detail (including old acceptance text), use git history around the pre-cleanup `BACKLOG.md`.

