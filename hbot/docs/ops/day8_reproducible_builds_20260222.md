# Day 8 - Reproducible Builds (External Control Plane)

## Scope
Convert external control-plane services to reproducible, pinned images with no runtime dependency installation.

## Build Artifact
- Image tag (default): `hbot-control-plane:20260222`
- Compose variable: `HBOT_CONTROL_PLANE_IMAGE`
- Dockerfile: `hbot/compose/images/control_plane/Dockerfile`
- Dependency lock file: `hbot/compose/images/control_plane/requirements-control-plane.txt`

## Pinned Dependencies
- `redis==7.2.0`
- `pydantic==2.12.5`
- `joblib==1.5.3`
- `scikit-learn==1.8.0`
- `requests==2.32.5`
- `boto3==1.42.54`
- `ccxt==4.5.39`
- `psycopg[binary]==3.2.13`

## Services moved to reproducible control-plane image
- `signal-service`
- `risk-service`
- `coordination-service`
- `event-store-service`
- `event-store-monitor`
- `day2-gate-monitor`
- `reconciliation-service`
- `exchange-snapshot-service`
- `shadow-parity-service`
- `portfolio-risk-service`
- `soak-monitor`
- `daily-ops-reporter`

## Build and Run
1. Build image once:
   - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml build`
2. Start external profile:
   - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml up -d`

## Verification
- Validate compose config:
  - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml config`
- Validate services are up:
  - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml ps`
- Confirm no runtime `pip install` commands remain in external service commands:
  - inspect `compose/docker-compose.yml` command entries under external services.

## Risk/Rollback
- Rollback path:
  - revert external services to `python:3.11-slim` + prior commands if build issues appear.
- Runtime behavior is unchanged by design; only packaging/runtime dependency resolution path changed.
