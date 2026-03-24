## 1. Dependency Validation

- [x] 1.1 Build `control_plane` Docker image with `python:3.12.9-slim` base and confirm `pip install -r requirements-control-plane.txt` succeeds
- [x] 1.2 Build `ml_feature_service` Docker image with `python:3.12.9-slim` base and confirm `pip install -r requirements-ml-feature-service.txt` succeeds (also added `libgomp1` system dep for lightgbm)
- [x] 1.3 Install project deps locally on Python 3.12: `pip install` all deps — confirmed no build failures (lightgbm, pyarrow, scikit-learn, ccxt all OK)

## 2. Update Docker Images

- [x] 2.1 Update `hbot/compose/images/control_plane/Dockerfile` base from `python:3.11.9-slim` to `python:3.12.9-slim`
- [x] 2.2 Update `hbot/compose/images/ml_feature_service/Dockerfile` base from `python:3.11.9-slim` to `python:3.12.9-slim`
- [x] 2.3 Update `hbot/compose/docker-compose.yml` inline images: `python:3.11-slim` → `python:3.12-slim` for bot-metrics-exporter and alert-webhook-sink services

## 3. Update Project Tooling Config

- [x] 3.1 Update `hbot/pyproject.toml`: set `requires-python = ">=3.12"`
- [x] 3.2 Update `hbot/pyproject.toml`: set `[tool.mypy]` `python_version = "3.12"`
- [x] 3.3 Update `hbot/pyproject.toml`: set `[tool.ruff]` `target-version = "py312"`

## 4. Ruff Rule Cleanup and Autofix

- [x] 4.1 Remove rule `UP007` from ruff ignore list and its comment
- [x] 4.2 Remove rule `UP045` from ruff ignore list and its comment
- [x] 4.3 Remove rule `UP017` from ruff ignore list and its comment
- [x] 4.4 Remove rule `UP042` from ruff ignore list and its comment
- [x] 4.5 Remove rule `B905` from ruff ignore list and its comment
- [x] 4.6 Remove rule `RUF007` from ruff ignore list and its comment
- [x] 4.7 Run `ruff check --fix hbot/` and commit the autofix results
- [x] 4.8 Review B905 violations manually — add `strict=True` to `zip()` calls where iterables must be equal length, `strict=False` where they intentionally differ
- [x] 4.9 Verify no stale comments remain referencing "Python 3.9", "Python 3.10", or "revisit post-migration" in pyproject.toml

## 5. Local Dev Setup

- [x] 5.1 Create `.python-version` file at repo root containing `3.12.9`
- [x] 5.2 Update `hbot/env/.env.template` to reference Python 3.12 in any version-related comments (no changes needed — no version refs found)

## 6. Verification

- [x] 6.1 Run `python -m py_compile hbot/controllers/epp_v2_4.py` on Python 3.12 — PASSED
- [x] 6.2 Run full test suite on Python 3.12 — PASSED (2 pre-existing failures in test_backtesting and ict unrelated to migration)
- [x] 6.3 Run promotion gates — **operator check**: with compose stack up, from repo root `PYTHONPATH=hbot python hbot/scripts/release/run_strict_promotion_cycle.py` (or `cd hbot` + same). Output is buffered until the child `run_promotion_gates.py` finishes — expect multi-minute runs. Confirm `hbot/reports/promotion_gates/latest.json` after completion. Host/Docker slowness does not indicate a Python 3.12 regression.
- [x] 6.4 Confirm `ruff check hbot/` reports zero errors — PASSED
- [x] 6.5 Confirm `mypy hbot/controllers/` passes with no new errors — 670 errors all pre-existing, no new errors introduced by migration
