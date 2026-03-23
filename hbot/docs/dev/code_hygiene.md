# Code hygiene and dead-code passes

## Baseline (enforced / expected before merge)

From repo root, with `PYTHONPATH=hbot`:

- `python -m py_compile hbot/controllers/epp_v2_4.py`
- `python -m pytest hbot/tests/ -q --ignore=hbot/tests/integration`
- `python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py hbot/tests/controllers/test_market_making_shim_contract.py -q`

From `hbot/`:

- `python -m ruff check controllers/ services/ --no-fix`  
  Use `ruff check ... --statistics` to see rule counts when triaging drift.

From `hbot/apps/realtime_ui_v2/`:

- `npm run lint`
- `npm run test:unit`

`mypy` is configured in `pyproject.toml` but is not fully clean on the whole tree; run targeted checks (e.g. `python -m mypy path/to/module.py`) when changing typed surfaces.

## Optional deeper passes (manual judgment)

- **Python unused names across modules**: [vulture](https://github.com/jendrikseipp/vulture) (or similar) with a whitelist file. Expect false positives for YAML-loaded classes, Hummingbot entrypoints, and `getattr` dispatch.
- **TS unused exports / orphan files**: from `realtime_ui_v2`, `npx knip` or `npx ts-prune` with project-specific ignores for Vite entrypoints and barrel files.

Do not delete modules that are only referenced dynamically until entrypoints and configs are grep-checked.

## Generated UI / Playwright artifacts

Do not commit:

- `hbot/apps/realtime_ui_v2/test-results/`, `playwright-report/`, `trace.zip` / `*.trace.zip` — ignored in [`apps/realtime_ui_v2/.gitignore`](../../apps/realtime_ui_v2/.gitignore).
- Ad-hoc `screenshot*.png` / `screenshot_*.js` at the **repo root** or **`hbot/`** root — ignored in the root [`.gitignore`](../../../.gitignore) and [`hbot/.gitignore`](../../.gitignore).

After local E2E or debug runs, delete `test-results` if it reappears; it is not source.
