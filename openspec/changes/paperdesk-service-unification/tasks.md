## 1. Freeze contracts and migration scope

- [x] 1.1 Inventory all consumers of `hb.paper_exchange.command.v1`, `hb.paper_exchange.event.v1`, `hb.paper_exchange.heartbeat.v1`, and verification snapshots
- [x] 1.2 Capture the minimum required fields for state snapshot compatibility, especially `orders` used by runtime hydration and ops ingestion
- [x] 1.3 Document rollback expectations and shadow-run comparison rules before code changes

## 2. Build tenant-isolated service wrapper

- [x] 2.1 Create a tenant runtime/router that owns one `PaperDesk` per `instance_name`
- [x] 2.2 Ensure balances, positions, risk state, and open orders are isolated per tenant
- [x] 2.3 Add lifecycle management for creating, looking up, and pruning idle tenant desks

## 3. Add instrument registration/bootstrap

- [x] 3.1 Create an instrument registry that resolves `InstrumentSpec` from command metadata and trading-rule hints
- [x] 3.2 Lazily register instruments before accepting the first command for a tenant/pair
- [x] 3.3 Reject commands deterministically when an instrument spec cannot be resolved

## 4. Add Redis market-data feed adapter

- [x] 4.1 Implement a service-side market-data adapter conforming to the `PaperDesk` feed protocol
- [x] 4.2 Route market snapshots to the correct tenant desk(s) without mixing bot state
- [x] 4.3 Drive `desk.tick()` from market updates and preserve funding-rate ingestion

## 5. Add command and event translation layer

- [x] 5.1 Parse `PaperExchangeCommandEvent` payloads into `PaperDesk` calls
- [x] 5.2 Translate `EngineEvent`s into `PaperExchangeEvent` payloads with the existing contract
- [x] 5.3 Preserve audit behavior for privileged commands
- [x] 5.4 Preserve heartbeat semantics and counters expected by promotion gates

## 6. Build compatibility projection

- [x] 6.1 Project tenant desk state into `paper_exchange_state_snapshot_latest.json`
- [x] 6.2 Include open orders in the projected state snapshot
- [x] 6.3 Project market state into `paper_exchange_pair_snapshot_latest.json`
- [x] 6.4 Preserve any required journals or metadata used by existing tooling

## 7. Shadow validation and cutover

- [x] 7.1 Run the new service alongside the legacy one in shadow mode
- [ ] 7.2 Compare event outputs and snapshot outputs for the same command/market sequences
- [ ] 7.3 Run the existing `paper-exchange-accounting-hardening` regression suites against the new service path
- [x] 7.4 Switch compose entrypoint only after parity and contract checks pass
- [x] 7.5 Keep a rollback path to the legacy service until the new wrapper is proven

## 8. Simplify runtime paper routing

- [ ] 8.1 Remove in-process desk ownership for paper bots from `hb_bridge.py` active mode (deferred: requires live shadow validation first)
- [x] 8.2 Keep embedded `PaperDesk` usage for backtesting and replay unchanged
- [x] 8.3 Verify that `BOT_MODE=paper|live` and connector naming stay unchanged from the strategy's point of view
