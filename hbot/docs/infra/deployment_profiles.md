# Deployment Profiles

## Purpose
Define compose profile usage and safe startup sequences.

## Scope
Profile combinations for baseline and external orchestration operation.

## Profiles
- Default (no explicit profile): `bot1` + monitoring stack.
- `multi`: adds `bot2` (Phase-0 monitor/no-trade role).
- `test`: includes `bot3` paper trade smoke-test instance.
  Bot3 uses `bitget_paper_trade` connector (framework `PaperTradeExchange` wrapper)
  to verify market data flow and simulated fills before promoting strategies to live.
- `external`: enables Redis + signal/risk/coordination services.

## Recommended Commands
- Baseline:
  - `docker compose --env-file ../env/.env up -d`
- Multi-bot:
  - `docker compose --env-file ../env/.env --profile multi up -d`
- External orchestration:
  - `docker compose --env-file ../env/.env --profile multi --profile external up -d`

## Rollback
- Disable external layer quickly:
  - restart without `--profile external`.

## Failure Modes
- Service startup loops from invalid env vars.
- Network mismatch if Redis host/port do not match profile runtime.

## Owner
- Engineering/Infrastructure
- Last-updated: 2026-02-19

