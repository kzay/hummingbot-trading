# Deployment Profiles

## Purpose
Define compose profile usage and safe startup sequences.

## Scope
Profile combinations for baseline and external orchestration operation.

## Profiles
- Default (no explicit profile): `bot1` + monitoring stack.
- `multi`: adds `bot2` as the hardened reserved/no-trade scale slot.
- `test`: includes the validation lanes `bot3`, `bot4`, and `bot5`.
  `bot3` and `bot5` run their production connector mappings in paper mode via
  Paper Engine v2, while `bot4` remains the Binance testnet validation lane.
- `external`: enables Redis + signal/risk/coordination services.

## Recommended Commands
- Baseline:
  - `docker compose --env-file ../env/.env up -d`
- Include reserved slot:
  - `docker compose --env-file ../env/.env --profile multi up -d`
- Bring up validation lanes:
  - `docker compose --env-file ../env/.env --profile test up -d`
- Full external orchestration with all bot lanes:
  - `docker compose --env-file ../env/.env --profile multi --profile test --profile external up -d`

## Rollback
- Disable external layer quickly:
  - restart without `--profile external`.

## Failure Modes
- Service startup loops from invalid env vars.
- Network mismatch if Redis host/port do not match profile runtime.

## Owner
- Engineering/Infrastructure
- Last-updated: 2026-03-06

