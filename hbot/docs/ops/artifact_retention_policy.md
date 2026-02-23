# Artifact Retention Policy (Day 13)

## Purpose
Define retention and auditability standards for operational evidence artifacts.

## Scope
- Event store snapshots and source-compare outputs.
- Reconciliation/parity/portfolio-risk reports.
- Promotion gate and replay regression artifacts.
- Readiness and soak outputs.

## Retention Rules
Policy source:
- `config/artifact_retention_policy.json`

Current retention windows:
- Event store: 14 days
- Reconciliation: 30 days
- Parity: 30 days
- Portfolio risk: 30 days
- Promotion gates: 60 days
- Replay regression: 60 days
- Readiness: 90 days
- Soak: 30 days
- Dev checks: 14 days

Protected files (`latest`/anchor artifacts) are never deleted by retention:
- examples: `reports/*/latest.json`, strict/day2/readiness anchors

## Retention Executor
- Script:
  - `scripts/release/run_artifact_retention.py`
- Dry run:
  - `python scripts/release/run_artifact_retention.py`
- Apply deletions:
  - `python scripts/release/run_artifact_retention.py --apply`
- Output:
  - `reports/ops_retention/latest.json`
  - `reports/ops_retention/artifact_retention_<timestamp>.json`

## Auditability Contract
- Promotion gate output includes stable evidence references:
  - `evidence_bundle.evidence_bundle_id`
  - file refs with `path`, `sha256`, `size_bytes`
  - `release_manifest_ref` tied to baseline manifest
- This creates a queryable chain:
  - release manifest -> gate decision -> exact evidence files

## Operator Query Examples
- “What happened yesterday?”:
  - read latest daily ops report + promotion gate latest + soak latest
  - use `evidence_bundle_id` and `artifacts[]` to trace exact files
- “Why did promotion fail?”:
  - `reports/promotion_gates/latest.json` -> `critical_failures`
  - inspect corresponding evidence refs in the bundle

## Day 13 Verification Checklist
- [ ] Retention policy file exists and is versioned.
- [ ] Dry-run retention report generated successfully.
- [ ] Gate output exposes stable evidence references and manifest tie-in.
- [ ] Operators can trace failure reasons without raw log scraping.
