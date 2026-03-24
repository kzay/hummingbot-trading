## Why

The project declares `requires-python = ">=3.11"` and targets Python 3.11 across Dockerfiles, mypy, and ruff — but the local development machine still runs **Python 3.9.13**, a version the project itself doesn't support. Meanwhile, the ruff config suppresses 6 lint rules (UP007, UP017, UP042, UP045, B905, RUF007) solely because they rely on features unavailable in 3.9/3.10. Migrating the entire stack to **Python 3.12** resolves this mismatch, unlocks modern Python idioms project-wide, and delivers a measurable performance uplift (~5%) before any code changes.

## What Changes

- **Dockerfiles**: Bump `python:3.11.9-slim` → `python:3.12.x-slim` in `compose/images/control_plane/Dockerfile`, `compose/images/ml_feature_service/Dockerfile`, and the `realtime_ui_v2/Dockerfile` if applicable.
- **docker-compose.yml**: Bump inline `python:3.11-slim` images (bot-metrics-exporter, alert-webhook-sink) → `python:3.12-slim`.
- **pyproject.toml**: Update `requires-python`, `python_version` (mypy), `target-version` (ruff) to 3.12.
- **Ruff rule cleanup**: Remove suppressions for UP007, UP017, UP045, UP042, B905, RUF007 and run autofix to modernize existing code (union types `X | Y`, `datetime.UTC`, `StrEnum`, `zip(strict=)`, `itertools.pairwise`).
- **Dependency validation**: Verify all pinned deps (lightgbm, scikit-learn, ccxt, pyarrow, hummingbot) build and pass tests under 3.12.
- **CI / local dev docs**: Update any documented Python version references (env templates, README, BACKLOG).

## Capabilities

### New Capabilities

- `python-312-runtime`: Covers the runtime upgrade across Docker images, compose services, and tooling config (pyproject.toml, mypy, ruff targets). Includes dependency compatibility validation.
- `modern-python-idioms`: Covers the ruff rule un-suppression and codebase-wide autofix pass to adopt 3.12 idioms (union type syntax, StrEnum, datetime.UTC, zip strict, pairwise).

### Modified Capabilities

_(No existing specs have requirement-level changes — this migration is infrastructure-only.)_

## Impact

- **Docker images**: All custom images rebuild with new base. Requires pulling `python:3.12.x-slim`.
- **Dependencies**: C-extension packages (lightgbm, scikit-learn, pyarrow, ccxt) must be verified. Risk is low — all have 3.12 wheels published.
- **Hummingbot**: Runs in its own container with its own Python; not directly affected, but the bridge code must remain compatible.
- **Code changes**: The ruff autofix pass will touch many files (type annotations, datetime imports). Changes are mechanical and reviewable via diff.
- **Tests**: Full test suite must pass post-migration. Promotion gates (`run_strict_promotion_cycle.py`) must be green.
- **Local dev**: Developers need Python 3.12 installed locally. The `.env.template` and any setup docs should reflect this.
