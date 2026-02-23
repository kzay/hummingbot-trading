# Validation Plan

## Purpose
Define validation procedure for strategy and orchestration changes.

## Scope
- Controller behavior
- Event flow
- Risk gating
- Intent enforcement

## Test Layers
- Unit tests:
  - contracts, feature builder, model loader, risk gate logic
- Integration tests:
  - `market_data -> signal/ml_signal -> risk_decision -> execution_intent`
- Paper trade smoke:
  - Bot3 (`--profile test`) runs `paper_test.py` with `bitget_paper_trade` connector.
  - Confirms market data flow, simulated fills, and PaperTradeExchange wrapper.
  - V2 controllers run with `paper_mode: true` on bot1; validate regime detection,
    spread calculations, and CSV log output before promoting to live.
- Runtime smoke:
  - compose profile startup and health checks
  - target matrix:
    - `v2_epp_v2_4_binance_demo_smoke.yml`
    - `v2_epp_v2_4_bitget_paper_smoke.yml`

## Acceptance Checks
- No schema validation regressions.
- Deterministic rejection reasons for invalid/stale/low-confidence signals.
- Local authority rejects unsafe intents.
- Preflight rejects connector/profile mismatches with actionable errors.

## Evidence
- test logs
- audit stream samples
- dead-letter samples
- strategy status snapshots

## Owner
- QA + Engineering
- Last-updated: 2026-02-19

