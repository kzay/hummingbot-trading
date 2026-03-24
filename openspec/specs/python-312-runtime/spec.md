## ADDED Requirements

### Requirement: Docker images use Python 3.12.9

All custom Docker images SHALL use `python:3.12.9-slim` as their base image. This applies to `compose/images/control_plane/Dockerfile`, `compose/images/ml_feature_service/Dockerfile`, and any inline image references in `docker-compose.yml`.

#### Scenario: Control plane Dockerfile base image
- **WHEN** the control plane Dockerfile is built
- **THEN** the base image SHALL be `python:3.12.9-slim`

#### Scenario: ML feature service Dockerfile base image
- **WHEN** the ML feature service Dockerfile is built
- **THEN** the base image SHALL be `python:3.12.9-slim`

#### Scenario: Inline compose service images
- **WHEN** docker-compose.yml defines services with inline `python:3.11-slim` images (bot-metrics-exporter, alert-webhook-sink)
- **THEN** those images SHALL be updated to `python:3.12-slim`

### Requirement: pyproject.toml targets Python 3.12

The project metadata SHALL declare Python 3.12 as the minimum and target version across all tooling.

#### Scenario: requires-python field
- **WHEN** `pyproject.toml` is read
- **THEN** `requires-python` SHALL be `">=3.12"`

#### Scenario: mypy python_version
- **WHEN** mypy runs type checking
- **THEN** `python_version` in `[tool.mypy]` SHALL be `"3.12"`

#### Scenario: ruff target-version
- **WHEN** ruff runs linting
- **THEN** `target-version` in `[tool.ruff]` SHALL be `"py312"`

### Requirement: All dependencies build on Python 3.12

Every dependency listed in `pyproject.toml`, `requirements-control-plane.txt`, and `requirements-ml-feature-service.txt` SHALL install successfully under Python 3.12 without build errors.

#### Scenario: Control plane dependencies install
- **WHEN** `pip install -r requirements-control-plane.txt` runs on Python 3.12
- **THEN** all packages SHALL install without errors

#### Scenario: ML feature service dependencies install
- **WHEN** `pip install -r requirements-ml-feature-service.txt` runs on Python 3.12
- **THEN** all packages SHALL install without errors

#### Scenario: Project dependencies install
- **WHEN** `pip install -e ".[dev]"` runs on Python 3.12
- **THEN** all packages SHALL install without errors

### Requirement: Test suite passes on Python 3.12

The full test suite and promotion gates SHALL pass under Python 3.12 with no regressions.

#### Scenario: Unit tests pass
- **WHEN** `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration` runs on Python 3.12
- **THEN** all tests SHALL pass

#### Scenario: Promotion gates pass
- **WHEN** `python scripts/release/run_strict_promotion_cycle.py` runs on Python 3.12 with the compose stack healthy (Redis, event-store, etc.)
- **THEN** the promotion cycle SHALL complete successfully

#### Scenario: py_compile passes
- **WHEN** `python -m py_compile hbot/controllers/epp_v2_4.py` runs on Python 3.12
- **THEN** compilation SHALL succeed without errors

### Requirement: Local dev version documented

The project SHALL include a `.python-version` file at the repository root specifying `3.12.9`, and the `.env.template` SHALL reference Python 3.12 as the required version.

#### Scenario: .python-version file exists
- **WHEN** a developer clones the repository
- **THEN** a `.python-version` file SHALL exist at the repo root containing `3.12.9`

#### Scenario: env template references correct version
- **WHEN** a developer reads `.env.template`
- **THEN** any Python version references SHALL specify 3.12

#### Scenario: pyenv-win without 3.12.9 patch
- **WHEN** a developer uses pyenv-win and `3.12.9` is not in the install list
- **THEN** they MAY install the latest available `3.12.x` (e.g. `3.12.3`) and set `pyenv local` accordingly; Docker images remain the source of truth for patch level
