# Cursor Output Files Add-on Prompt

```text
Please output results as separate files (or sections clearly labeled as files).

Compatibility requirements:
1) Preserve the base prompt's mandatory output structure first (phases, scorecards, BACKLOG entries, gates, etc.).
2) Keep existing ID/entry formats exactly as required by the base prompt.
3) Do not force a fixed filename set across all prompt types.

File planning step (mandatory):
- First output a FILE_PLAN table: file_name | content_scope | source_sections.
- Generate only files relevant to this session.

Suggested file sets by prompt family (choose adaptively):
- loops/*:
  - LOOP_SCORECARD.md
  - FINDINGS_AND_RISKS.md
  - SPRINT_OR_NEXT_CYCLE_PLAN.md
  - BACKLOG_ENTRIES.md
  - METRICS_NEXT_CYCLE.md
- architecture/*:
  - DESK_ARCHITECTURE.md
  - EVENT_FLOW_DESIGN.md
  - RISK_FRAMEWORK.md
  - ROADMAP_30_60_90.md
  - MIGRATION_OR_HARDENING_DECISION.md
- strategy/*:
  - STRATEGY_SPEC.md
  - EXECUTION_AND_RISK_RULES.md
  - VALIDATION_PLAN.md
  - IMPLEMENTATION_BLUEPRINT.md
- ops/*:
  - OPS_HEALTH_REPORT.md
  - INCIDENT_OR_GAP_ANALYSIS.md
  - RUNBOOK_UPDATES.md
  - BACKLOG_ENTRIES.md

Per-file requirements:
- include a short executive summary
- include assumptions and data gaps
- include concrete implementation details
- include a prioritized task list

If a planned file would be empty, skip it and explain why in FILE_PLAN notes.
```
