# Nautilus Reuse Boundary v1

## Purpose
Define the selective reuse boundary for NautilusTrader-inspired logic in `paper_engine_v2`,
including provenance, license attribution, and anti-lock-in guardrails.

## Upstream
- Project: `nautilus_trader`
- URL: <https://github.com/nautechsystems/nautilus_trader>
- License family used for attribution: `LGPL-3.0-or-later`

## Decision Matrix Location
- Machine-readable matrix: `docs/validation/nautilus_reuse_matrix.json`
- Third-party attribution: `docs/legal/nautilus_trader.LICENSE.txt`

## Boundary Rules
1. Reuse is contract-level (`adopt|adapt|reimplement`) and must be documented per module.
2. No implicit framework lock-in:
   - direct `nautilus*` imports are forbidden unless explicitly documented and approved.
3. Each documented module must include:
   - upstream component reference,
   - rationale and local integration boundary,
   - attribution file reference,
   - linked regression tests.
4. Runtime ownership stays local:
   - no direct dependency on Nautilus internal runtime objects in paper engine hot paths.

## Compliance Checkpoints
- `build_paper_exchange_threshold_inputs.py` generates:
  - `reports/verification/paper_exchange_nautilus_reuse_latest.json`
- The report feeds `p2_10_*` thresholds:
  - provenance coverage,
  - license compliance failures,
  - adopted-module parity test rate,
  - undocumented external dependency count.

## Operator Notes
- Update the matrix whenever a module adds or removes Nautilus-inspired behavior.
- If an explicit upstream import becomes necessary, document it in the matrix first and add
  dedicated regression coverage before promotion.
