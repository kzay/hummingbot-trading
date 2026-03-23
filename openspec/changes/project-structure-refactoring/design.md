## Context

The `hbot/` workspace root currently has 15+ top-level directories mixing source code, infra configs, runtime data, web app dependencies, and generated reports. This was organic growth from a single-bot prototype to a multi-bot trading desk with backtesting, monitoring, and a React UI. The layout works but communicates intent poorly — newcomers cannot tell what is source-controlled vs generated, and IDE indexing is polluted by 300+ `node_modules` directories at root.

A nested `hbot/hbot/` directory is silently created by Docker containers because backtesting defaults assume `cwd != hbot/` and prepend `hbot/` to relative paths.

The backtesting harness contains a 289-line `_build_adapter()` method that must be manually extended for each new strategy adapter — a violation of the Open/Closed principle.

## Goals / Non-Goals

**Goals:**
- Fix path defaults that create accidental nested directories in Docker.
- Eliminate `node_modules/` and `package.json` from the Python project root.
- Make adding a new backtesting adapter a 1-file + 1-line change instead of editing a 289-line method.
- Document the `data/` directory layout for contributors.

**Non-Goals:**
- Restructuring `controllers/`, `services/`, or `tests/` — these are already well-organized.
- Moving `data/bot{1..7}/` directories — Docker volume mounts are baked into compose.
- Changing `reports/` location — too many service hardcoded paths.
- Moving `config/` — it is runtime application input, not purely ops config. Moving it forces container path churn with minimal benefit.

## Decisions

### D1: Keep `config/` at root; infra lives under `infra/`

**Choice**: `compose/`, `monitoring/`, and `env/` are consolidated under `hbot/infra/`. Legacy `security/` became `infra/firewall-rules.sh`. `config/` stays at `hbot/` root permanently because services consume it as application input (`/workspace/hbot/config/...`).

**Alternative considered**: Move `config/` under `infra/`. Rejected because it forces container path churn with minimal architectural benefit.

### D2: Add `playwright` to `apps/realtime_ui_v2/` devDependencies

**Choice**: Add `playwright` (the library, not just `@playwright/test`) to the app's `package.json` and delete the root-level `package.json`.

**Alternative considered**: Create a separate `apps/e2e/` directory for Playwright. Rejected because the screenshot scripts already live in `apps/realtime_ui_v2/scripts/` and the app already has `@playwright/test`.

### D3: Fix backtesting path defaults to be cwd-relative

**Choice**: Change defaults from `hbot/data/historical` → `data/historical` and `hbot/reports/backtest` → `reports/backtest` across all 9 affected Python files, 46 YAML configs, and related tests/docstrings. The `harness_cli.py` retains a runtime fallback that checks `hbot/data/historical` if `data/historical` doesn't exist.

**Alternative considered**: Use env vars exclusively. Rejected because defaults should work out of the box; `harness_cli.py` already tries env vars first.

### D4: Adapter registry with behavior-preserving hydration

**Choice**: Create `adapter_registry.py` with a registry dict mapping `adapter_mode` → entry containing module path, adapter class, config class, and explicit attribute lists. A generic `hydrate_config()` function converts YAML values to the correct type. Non-frozen configs use explicit attribute lists for exact behavior preservation. Configs without explicit lists use introspection of dataclass field defaults.

**Critical guard**: Boolean hydration uses `_safe_bool()` to handle string values safely — `bool("false")` evaluates to `True` in Python, so the hydrator checks for string `"false"`/`"true"` explicitly.

**Runtime adapter special case**: The `"runtime"` adapter mode is handled with a dedicated `_build_runtime_adapter` function because it requires loading a strategy class and has a different constructor signature (`strategy=` argument). Its config hydration delegates to the same `hydrate_config()` function via a standalone `_RUNTIME_ENTRY`.

**Alternative considered**: Decorator-based self-registration. Rejected because it requires importing all adapter modules at startup; the current lazy-import pattern is better for startup time.

### D5: Safe `hbot/hbot/` cleanup — inspect before delete

**Choice**: First fix path defaults, then inspect `hbot/hbot/` contents. Only delete after confirming contents are purely generated artifacts (no unique data). If anything unexpected is found, warn and skip deletion.

**Alternative considered**: Blind `rmdir`. Rejected because investigation showed `hbot/hbot/reports/` contains generated analysis outputs that may not exist elsewhere.

### D6: Execution order — low risk first

**Choice**: Execute in order: path defaults fix → adapter registry → data README → node relocation → infra consolidation (compose/monitoring/env under `infra/`, firewall script, doc/script path updates). Track A items are safe internal changes; infra consolidation updates deployment paths and requires compose validation on the target host.

## Risks / Trade-offs

- **[YAML config hardcoded paths]** → Some backtest YAML configs in `data/backtest_configs/` may hardcode `hbot/` prefixes. Need to grep and update.
- **[Adapter registry behavioral regression]** → Mitigated by: preserving exact hydration semantics per adapter type, guarding string booleans, and requiring all existing tests to pass.
- **[`hbot/hbot/` contains useful data]** → Mitigated by: inspecting contents before deletion, only removing after path fix prevents re-creation.

## Open Questions

- None for Track A — all decisions are pre-answered.
- **Post-migration ops**: Confirm VPS cron/systemd and any external automation now use `hbot/infra/compose/`, `hbot/infra/env/.env`, and `hbot/infra/monitoring/` (or run `docker compose` from `hbot/` with `-f infra/compose/docker-compose.yml`).
