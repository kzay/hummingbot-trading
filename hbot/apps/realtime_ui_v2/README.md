# Realtime UI v2 (React + TypeScript)

Production-oriented migration target for the trading supervision frontend.

## Implemented phases

### Phase 1

- Realtime transport (`/api/v1/ws`) with reconnect backoff
- API health polling and `/api/v1/state` fallback refresh
- Data ingress diagnostics panel
- Orders and fills tables with dedicated filters
- Live feed search + pause + auto-scroll controls
- Payload inspector for raw websocket payloads

### Phase 2

- Realtime candlestick chart (`lightweight-charts`) with order/position overlays
- Position / exposure panel
- Account / PnL panel with risk context
- L2 depth ladder with spread and imbalance metrics

### Phase 3

- Top-level mode tabs: realtime / history / service / daily / weekly / journal
- Bot gate board panel in realtime view
- Daily review view (summary, hourly table, fill tape, gate timeline)
- Weekly review view (performance/risk cards + per-day breakdown)
- Journal view with range controls, trade table selection, and drilldown (fills/path/gates)
- History monitor view for shared-history quality and shadow parity
- Service monitor view for API health and instance coverage

## Compose run (no manual frontend step)

From `hbot/compose`:

```bash
docker compose --env-file ../env/.env --profile external up -d --build realtime-ui-api realtime-ui-web
```

Then open `http://localhost:8088` (or your configured `REALTIME_UI_WEB_PORT`).

`realtime-ui-web` builds and serves `apps/realtime_ui_v2` automatically through Docker.

## Local run (optional)

```bash
cd hbot/apps/realtime_ui_v2
npm install
npm run dev
```

Then open the Vite URL and point API URL to `http://localhost:9910`.

## Auth behavior

- API bearer tokens are stored in browser session storage only.
- Browser websocket auth is intentionally disabled when a bearer token is set.
- In authenticated mode, the UI keeps using authenticated HTTP requests and falls back to periodic `/api/v1/state` polling instead of `/api/v1/ws`.
- In the default local compose posture where browser auth is off, websocket streaming remains active.

This avoids persisting operator tokens in `localStorage` and avoids relying on query-string websocket tokens in hardened deployments.

## Verification

```bash
npm run lint
npm run test:unit
npm run test:e2e
npm run build
```

`npm run test:e2e` rebuilds the app and runs a mocked Playwright smoke flow against the operator shell.

## Build check

```bash
npm run lint
npm run build
```

## Notes

- Legacy `hbot/apps/realtime_ui` remains available as fallback during migration.
- Remaining parity work is mostly visual polish and optional charting enhancements for review modes.
- Feed pause and auto-scroll are session-only controls and reset on reload.
- View-level error boundaries now keep a panel failure from blanking the entire operator app.
