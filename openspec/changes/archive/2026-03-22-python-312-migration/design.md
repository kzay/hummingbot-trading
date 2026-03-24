## Context

The project currently targets Python 3.11 in Docker images and tooling config, but the local dev environment runs 3.9.13. Six ruff lint rules are suppressed because the codebase was written for 3.9 runtime compatibility. All custom services (control_plane, ml_feature_service, bot-metrics-exporter, alert-webhook-sink) run `python:3.11.x-slim` base images. Hummingbot itself ships its own container and is not affected by this migration.

The migration is purely infrastructure — no strategy logic, risk engine, or runtime behavior changes.

## Goals / Non-Goals

**Goals:**
- Unify local dev and Docker runtime on Python 3.12
- Unlock modern Python idioms via ruff autofix (union types, StrEnum, datetime.UTC, zip strict, pairwise)
- Validate all C-extension dependencies build cleanly on 3.12
- Keep full test suite and promotion gates green throughout

**Non-Goals:**
- Migrating to Python 3.13 or 3.14 (evaluate in Q3-Q4 2026 once deps confirm support)
- Adopting free-threaded Python (experimental, not useful for this async codebase)
- Refactoring strategy logic — this is a mechanical migration only
- Changing Hummingbot's own container or its internal Python version

## Decisions

### 1. Target Python 3.12 (not 3.13/3.14)

**Choice**: Python 3.12.x

**Rationale**: 3.12 has been stable for 1.5+ years. All key dependencies (lightgbm, scikit-learn, pyarrow, ccxt, pandas, pydantic) have published 3.12 wheels. 3.13's free-threading is irrelevant (we use async), and 3.14 is too new for C-extension-heavy stacks.

**Alternatives considered**:
- 3.13: Experimental JIT, free-threading not useful, some deps still catching up
- 3.14: Just released, high risk with lightgbm/pyarrow C extensions

### 2. Ruff autofix for idiom migration (not manual rewrite)

**Choice**: Un-suppress lint rules and run `ruff check --fix` to mechanically transform code.

**Rationale**: Ruff's autofix handles `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, `datetime.timezone.utc` → `datetime.UTC`, etc. deterministically. Manual rewrite risks errors and is unnecessarily slow. The diff is large but 100% reviewable.

**Alternatives considered**:
- Manual rewrite: Slow, error-prone, no advantage
- Incremental per-file: Unnecessary — ruff autofix is atomic and safe

### 3. Pin `python:3.12.9-slim` in Dockerfiles (not floating `3.12-slim`)

**Choice**: Use a specific patch version `3.12.9-slim` (latest 3.12 patch as of March 2026).

**Rationale**: Reproducible builds. Floating tags can pull different patches between builds, introducing subtle behavior differences. Upgrade patches explicitly.

### 4. Migrate in a single branch, not staged rollout

**Choice**: One branch that updates all config + Dockerfiles + ruff fixes together.

**Rationale**: The changes are tightly coupled — changing the ruff target without changing the Docker base creates a mismatch. Splitting creates a state where config says 3.12 but runtime is 3.11. The migration is safe to land atomically because it's infrastructure-only.

## Risks / Trade-offs

**[Risk] A dependency doesn't work on 3.12** → Mitigation: Build all Docker images and run the full test suite before merging. All critical deps already publish 3.12 wheels; this risk is low but must be validated.

**[Risk] Ruff autofix produces a large diff** → Mitigation: The diff is mechanical (type annotations, imports). Review by sampling — if ruff's transformations are correct in a handful of files, they're correct everywhere. Commit the autofix separately from config changes for clean git blame.

**[Risk] Hummingbot bridge incompatibility** → Mitigation: Hummingbot runs in its own container with its own Python. The bridge code (`paper_engine_v2/hb_bridge.py`) uses standard Python — no 3.11-specific APIs. Run integration tests to confirm.

**[Risk] Local dev environment fragmentation** → Mitigation: Document the required Python version in `.env.template` and README. Consider adding a `.python-version` file for pyenv users.

## Migration Plan

1. **Validate deps**: Build Docker images with `python:3.12.9-slim`, run `pip install` for all requirements files, confirm no build failures.
2. **Update config**: Bump `pyproject.toml` (requires-python, mypy python_version, ruff target-version).
3. **Update Dockerfiles**: Change base images in all Dockerfiles and docker-compose.yml inline images.
4. **Ruff autofix**: Remove suppressed rules, run `ruff check --fix`, commit the result.
5. **Test**: Run full test suite (`pytest`), promotion gates, and `py_compile` checks.
6. **Docs**: Update `.env.template`, README, any setup instructions referencing Python version.

**Rollback**: Revert the branch. All changes are config/annotation-only — no runtime behavior changes.

## Open Questions

- **Exact 3.12 patch**: Pin to `3.12.9` (latest as of March 2026) or let the team choose? → Default: `3.12.9`.
- **`.python-version` file**: Add one for pyenv/asdf users? → Default: yes, add it.
- **UP042 (StrEnum)**: The suppress comment says "separate effort". Should the autofix migrate existing string enums to `StrEnum`, or keep that suppressed? → Default: include it in this migration since 3.12 makes StrEnum stable.
