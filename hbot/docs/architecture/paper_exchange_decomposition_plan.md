# paper_exchange_service/main.py Decomposition Plan

## Current State

| Metric | Value |
|---|---|
| File | `hbot/services/paper_exchange_service/main.py` |
| Total lines | ~3,478 |
| Classes | `PairSnapshot` (L466), `OrderRecord` (L490), `PositionRecord` (L524), `PaperExchangeState` (L542), `ServiceSettings` (L586), `PersistenceCoordinator` (L633), `FundingSettlementCandidate` (L1024), `FillCandidate` (L1157) |
| Module-level functions | ~75 functions |
| Existing extractions | `order_fsm.py` (state machine, transition validation) |
| Service entry point | `run()` (L2961) and `main()` (L3463) |

### Architecture Role

`paper_exchange_service` is a standalone Redis-stream microservice that simulates an exchange. It:
1. Ingests market data snapshots from `MARKET_DATA_STREAM`
2. Processes order commands from `PAPER_EXCHANGE_COMMAND_STREAM`
3. Matches resting orders against book snapshots
4. Manages position tracking with PnL calculation
5. Settles funding payments
6. Publishes fill/cancel/reject events to `PAPER_EXCHANGE_EVENT_STREAM`
7. Publishes heartbeats to `PAPER_EXCHANGE_HEARTBEAT_STREAM`

---

## Method Inventory by Responsibility Group

### 1. Utilities & Normalization (Top of File)

| Function | Lines | Purpose |
|---|---|---|
| `_now_ms` | L50–51 | Current time in milliseconds |
| `_normalize` | L54–55 | Lowercase string normalization |
| `_canonical_connector_name` | L58–72 | Strip `_paper_trade` suffix |
| `_normalize_connector_name` | L75–76 | Canonical + normalize |
| `_csv_set` | L79–80 | Parse comma-separated set |
| `_namespace_base_key` | L83–88 | Build instance::connector::pair key |
| `_namespace_order_key` | L91–92 | Build instance::connector::pair::order_id key |
| `_pair_key` | L95–96 | Alias for namespace_base_key |
| `_get_pair_snapshot` | L99–111 | Look up pair snapshot with fallback |
| `_resolve_path` | L114–118 | Resolve relative path from root |
| `_D` | L724–728 | Decimal conversion via string |
| `_parse_bool` | L1176–1188 | Robust boolean parser |
| `_try_float` | L1196–1202 | Safe float conversion |
| `_positive_or_none` | L798–805 | Return float if positive, else None |

### 2. Persistence / Journal I/O

| Function | Lines | Purpose |
|---|---|---|
| `_read_json` | L121–128 | Read JSON file to dict |
| `_load_command_journal` | L131–140 | Load command results from disk |
| `_write_json_atomic` | L143–168 | Atomic JSON write with retries |
| `_persist_command_journal` | L171–177 | Write command journal to disk |
| `_load_market_fill_journal` | L180–195 | Load market fill dedup journal |
| `_trim_market_fill_journal` | L198–206 | Trim journal to max entries |
| `_persist_market_fill_journal` | L208–217 | Write market fill journal to disk |
| `_command_result_record` | L220–252 | Build command result dict |
| `_load_state_snapshot` | L377–390 | Load order state from disk |
| `_load_position_snapshot` | L392–405 | Load position state from disk |
| `_persist_state_snapshot` | L407–427 | Write order+position state to disk |
| `_pair_snapshot_to_dict` | L429–454 | Serialize PairSnapshot |
| `_persist_pair_snapshot` | L456–464 | Write pair snapshots to disk |
| `PersistenceCoordinator` class | L633–715 | Coordinated flush with dirty flags and intervals |

### 3. Data Model Serialization

| Function | Lines | Purpose |
|---|---|---|
| `_order_record_to_dict` | L254–296 | Serialize OrderRecord to dict |
| `_position_record_to_dict` | L298–315 | Serialize PositionRecord to dict |
| `_position_record_from_payload` | L317–337 | Deserialize PositionRecord from payload |
| `_order_record_from_payload` | L339–375 | Deserialize OrderRecord from payload |
| `_order_metadata` | L1362–1387 | Build order metadata dict for events |

### 4. Position Management

| Function | Lines | Purpose |
|---|---|---|
| `_position_key` | L828–829 | Build position lookup key |
| `_get_or_create_position` | L832–845 | Get existing or create new position |
| `_round_positive` | L847–849 | Clamp to non-negative |
| `_open_long` | L851–864 | Add to long position with avg entry |
| `_open_short` | L866–879 | Add to short position with avg entry |
| `_close_long` | L881–892 | Reduce long position, return realized PnL |
| `_close_short` | L894–905 | Reduce short position, return realized PnL |
| `_is_flat_position` | L907–909 | Check if position is flat |
| `_preview_fill_realized_pnl` | L911–949 | Preview PnL for a fill without mutating |
| `_apply_position_fill` | L951–1011 | Apply fill to position (mutating) |

### 5. Funding Settlement

| Function | Lines | Purpose |
|---|---|---|
| `_funding_summary` | L1013–1035 | Build funding summary dict |
| `FundingSettlementCandidate` | L1024–1034 | Dataclass for pending funding charge |
| `_funding_events_for_snapshot` | L1037–1137 | Generate funding candidates from snapshot |
| `_commit_funding_settlement` | L1140–1153 | Apply funding charge to position |

### 6. Order Validation & Constraints

| Function | Lines | Purpose |
|---|---|---|
| `_coerce_time_in_force` | L1191–1193 | Normalize TIF from metadata |
| `_decimal_from_metadata` | L1205–1215 | Parse Decimal from metadata dict |
| `_is_multiple_of_increment` | L1218–1225 | Check value is multiple of step |
| `_validate_order_constraints` | L1228–1276 | Validate min_quantity, size_increment, price_increment, min_notional |
| `_coerce_margin_mode` | L1279–1281 | Normalize margin mode string |
| `_resolve_accounting_contract` | L1284–1317 | Extract fee/leverage/margin from metadata |

### 7. Fee Calculation

| Function | Lines | Purpose |
|---|---|---|
| `_fee_rate_for_fill` | L1320–1330 | Select maker/taker fee rate |
| `_calc_fill_fee_quote` | L1333–1346 | Calculate fill fee in quote |
| `_calc_margin_reserve_quote` | L1349–1359 | Calculate margin reserve |

### 8. Order Book Matching (Core Engine)

| Function | Lines | Purpose |
|---|---|---|
| `_crosses_book` | L1414–1419 | Check if order crosses top-of-book |
| `_market_execution_price` | L1422–1430 | Resolve market order execution price |
| `_extract_depth_levels` | L1432–1452 | Parse bid/ask depth levels from payload |
| `_contra_levels_for_snapshot` | L1454–1479 | Get contra-side depth levels |
| `_sweep_fill_from_levels` | L1481–1503 | Sweep fill across depth levels |
| `_effective_depth_from_levels` | L1505–1520 | Sum available depth |
| `_consume_levels` | L1522–1539 | Consume liquidity from depth levels |
| `_filter_levels_for_limit` | L1541–1558 | Filter levels by limit price |
| `_order_matches_snapshot` | L1560–1568 | Check if order matches a snapshot's connector/pair |
| `_ordered_active_orders_for_snapshot` | L1570–1578 | Get active orders sorted by creation time |
| `_build_fill_candidates_for_snapshot` | L1580–1707 | Main matching loop — build fill candidates |
| `FillCandidate` dataclass | L1157–1173 | Candidate fill with amounts, fees |

### 9. Fill Application & Events

| Function | Lines | Purpose |
|---|---|---|
| `_market_fill_event_from_candidate` | L1710–1767 | Build PaperExchangeEvent from fill candidate |
| `_apply_fill_candidate` | L1769–1790 | Apply fill to order record (state transition) |
| `_prune_orders` | L1793–1831 | Remove terminal orders beyond TTL |
| `_event_for_command` | L1390–1411 | Build event response for a command |
| `_snapshot_best_bid` / `_best_ask` / sizes | L808–823 | Extract top-of-book from snapshot |
| `_remaining_amount_base` | L824–826 | Calculate remaining order amount |

### 10. Market Data Ingestion

| Function | Lines | Purpose |
|---|---|---|
| `ingest_market_snapshot_payload` | L1833–1945 | Validate and store market snapshot (~110 lines) |

### 11. Heartbeat

| Function | Lines | Purpose |
|---|---|---|
| `build_heartbeat_event` | L1948–2029 | Build heartbeat event with metrics |

### 12. Command Handling

| Function | Lines | Purpose |
|---|---|---|
| `handle_command_payload` | L2031–2507 | Main command handler (~475 lines) — submit, cancel, cancel_all, sync_state |
| `_is_privileged_command` | L732–733 | Check if command is privileged |
| `_missing_privileged_metadata` | L736–737 | Check required metadata for privileged commands |
| `_build_privileged_audit_event` | L749–783 | Build audit event for privileged commands |
| `_bool_from_record` | L740–746 | Boolean from record dict |
| `_entry_sequence_from_stream_id` | L784–795 | Extract sequence from Redis stream ID |

### 13. Stream Processing (Service Loop)

| Function | Lines | Purpose |
|---|---|---|
| `_ack_entries` | L2509–2517 | Acknowledge Redis stream entries |
| `process_command_rows` | L2520–2723 | Process batch of command stream entries (~200 lines) |
| `process_market_rows` | L2725–2959 | Process batch of market data entries + matching (~235 lines) |
| `run` | L2961–3181 | Main service loop (~220 lines) — group creation, reclaim, heartbeat, flush |
| `_parse_args` | L3183–3461 | CLI argument parsing (~280 lines) |
| `main` | L3463–3478 | Entry point |

---

## Proposed Target Modules

```
hbot/services/paper_exchange_service/
├── main.py                        # SLIM: run(), main(), _parse_args() — service loop only
├── order_fsm.py                   # (already extracted)
├── state.py                       # PaperExchangeState, PairSnapshot, OrderRecord, PositionRecord, ServiceSettings
├── persistence.py                 # PersistenceCoordinator, all _load_*, _persist_*, _write_json_atomic
├── serialization.py               # _order_record_to_dict, _order_record_from_payload, _position_record_*
├── position_manager.py            # Position open/close, PnL calculation, _apply_position_fill
├── funding.py                     # FundingSettlementCandidate, _funding_events_for_snapshot, _commit_funding_settlement
├── order_validation.py            # _validate_order_constraints, _resolve_accounting_contract, constraint helpers
├── fee_engine.py                  # _fee_rate_for_fill, _calc_fill_fee_quote, _calc_margin_reserve_quote
├── matching_engine.py             # _crosses_book, depth level operations, _build_fill_candidates_for_snapshot
├── fill_pipeline.py               # FillCandidate, _market_fill_event_from_candidate, _apply_fill_candidate
├── market_ingest.py               # ingest_market_snapshot_payload
├── command_handler.py             # handle_command_payload
├── stream_processor.py            # process_command_rows, process_market_rows, _ack_entries
├── heartbeat.py                   # build_heartbeat_event
├── utils.py                       # _now_ms, _normalize, _canonical_connector_name, _D, _parse_bool, etc.
```

### Method-to-Module Mapping

| Target Module | Functions |
|---|---|
| `state.py` | `PairSnapshot`, `OrderRecord`, `PositionRecord`, `PaperExchangeState`, `ServiceSettings`, `FillCandidate`, `FundingSettlementCandidate` |
| `persistence.py` | `PersistenceCoordinator`, `_read_json`, `_write_json_atomic`, `_load_command_journal`, `_persist_command_journal`, `_load_market_fill_journal`, `_trim_market_fill_journal`, `_persist_market_fill_journal`, `_load_state_snapshot`, `_load_position_snapshot`, `_persist_state_snapshot`, `_pair_snapshot_to_dict`, `_persist_pair_snapshot` |
| `serialization.py` | `_order_record_to_dict`, `_order_record_from_payload`, `_position_record_to_dict`, `_position_record_from_payload`, `_command_result_record`, `_order_metadata` |
| `position_manager.py` | `_position_key`, `_get_or_create_position`, `_round_positive`, `_open_long`, `_open_short`, `_close_long`, `_close_short`, `_is_flat_position`, `_preview_fill_realized_pnl`, `_apply_position_fill` |
| `funding.py` | `_funding_summary`, `_funding_events_for_snapshot`, `_commit_funding_settlement` |
| `order_validation.py` | `_coerce_time_in_force`, `_decimal_from_metadata`, `_is_multiple_of_increment`, `_validate_order_constraints`, `_coerce_margin_mode`, `_resolve_accounting_contract` |
| `fee_engine.py` | `_fee_rate_for_fill`, `_calc_fill_fee_quote`, `_calc_margin_reserve_quote` |
| `matching_engine.py` | `_crosses_book`, `_market_execution_price`, `_extract_depth_levels`, `_contra_levels_for_snapshot`, `_sweep_fill_from_levels`, `_effective_depth_from_levels`, `_consume_levels`, `_filter_levels_for_limit`, `_order_matches_snapshot`, `_ordered_active_orders_for_snapshot`, `_build_fill_candidates_for_snapshot` |
| `fill_pipeline.py` | `_market_fill_event_from_candidate`, `_apply_fill_candidate`, `_prune_orders`, `_remaining_amount_base` |
| `market_ingest.py` | `ingest_market_snapshot_payload` |
| `command_handler.py` | `handle_command_payload`, `_event_for_command`, `_is_privileged_command`, `_missing_privileged_metadata`, `_build_privileged_audit_event`, `_bool_from_record`, `_entry_sequence_from_stream_id` |
| `stream_processor.py` | `process_command_rows`, `process_market_rows`, `_ack_entries` |
| `heartbeat.py` | `build_heartbeat_event` |
| `utils.py` | `_now_ms`, `_normalize`, `_canonical_connector_name`, `_normalize_connector_name`, `_csv_set`, `_namespace_base_key`, `_namespace_order_key`, `_pair_key`, `_get_pair_snapshot`, `_resolve_path`, `_D`, `_parse_bool`, `_try_float`, `_positive_or_none`, `_snapshot_best_bid`, `_snapshot_best_ask`, `_snapshot_best_bid_size`, `_snapshot_best_ask_size` |
| `main.py` (slim) | `run`, `_parse_args`, `main`, re-exports for backward compat |

---

## Shared State Between Modules

### PaperExchangeState (Mutable In-Memory State)

All processing functions receive `state: PaperExchangeState` as a parameter. This is the central shared state:

| State Field | Writers | Readers |
|---|---|---|
| `pairs` (PairSnapshot dict) | market_ingest | matching_engine, funding, heartbeat |
| `orders_by_id` (OrderRecord dict) | command_handler, fill_pipeline, matching_engine | matching_engine, fill_pipeline, heartbeat, persistence |
| `positions_by_key` (PositionRecord dict) | position_manager, funding | funding, persistence, heartbeat |
| `command_results_by_id` | command_handler, stream_processor | persistence |
| `market_fill_events_by_id` | stream_processor | persistence |
| Counter fields (accepted_snapshots, etc.) | various | heartbeat |

### ServiceSettings (Immutable After Startup)

Parsed once by `_parse_args` and passed to `run()`. Read-only for all processing functions.

### PersistenceCoordinator

Owns flush logic and dirty flags. Called from `run()` after each batch of processing.

### No Module-Level Mutable State

Unlike `hb_bridge.py`, `paper_exchange_service/main.py` has no module-level mutable state. All state is passed through `PaperExchangeState` and `ServiceSettings` parameters. This makes decomposition significantly cleaner.

---

## Migration Phases (Safest First)

### Phase 1: `utils.py` — Risk: **Very Low**

- ~20 pure functions, ~200 lines
- Zero state dependencies — pure string/math helpers
- Every other module will import from here
- Test impact: none (behavior-preserving move)

### Phase 2: `state.py` — Risk: **Very Low**

- 6 dataclass definitions, ~200 lines
- No logic, just data structures
- Enables all other modules to import types from a dedicated location
- Test impact: import path changes only

### Phase 3: `serialization.py` — Risk: **Low**

- 6 functions, ~150 lines
- Pure data transformation (dict ↔ dataclass)
- Dependencies: state types, utils
- Test impact: serialization round-trip tests

### Phase 4: `fee_engine.py` — Risk: **Low**

- 3 functions, ~50 lines
- Pure math: fee rate selection, fee/margin calculation
- No state mutation
- Test impact: trivial unit tests

### Phase 5: `order_validation.py` — Risk: **Low**

- 6 functions, ~100 lines
- Pure validation logic — returns rejection reason or None
- Dependencies: `_D` from utils
- Test impact: validation tests exist

### Phase 6: `persistence.py` — Risk: **Low**

- `PersistenceCoordinator` + 10 I/O functions, ~300 lines
- Self-contained file I/O with atomic writes
- Dependencies: state types, serialization
- Test impact: mock filesystem in tests

### Phase 7: `position_manager.py` — Risk: **Low-Medium**

- 10 functions, ~200 lines
- Mutates `PositionRecord` — correctness is critical for PnL
- `_apply_position_fill` has complex PnL accounting
- Dependencies: state types, utils
- Test impact: position accounting tests are critical

### Phase 8: `funding.py` — Risk: **Low-Medium**

- 3 functions, ~150 lines
- Mutates position records and state counters
- Dependencies: position_manager, state, utils
- Test impact: funding settlement accuracy

### Phase 9: `matching_engine.py` — Risk: **Medium**

- 11 functions, ~300 lines
- Core order matching logic — fills are generated here
- `_build_fill_candidates_for_snapshot` is the most complex function (~130 lines)
- Dependencies: utils, state, order_fsm, fee_engine
- Test impact: matching correctness directly affects all fill events

### Phase 10: `fill_pipeline.py` — Risk: **Medium**

- 4 functions, ~150 lines
- `_apply_fill_candidate` mutates order state and must respect FSM transitions
- Event generation for downstream consumers
- Dependencies: state, order_fsm, fee_engine, position_manager
- Test impact: fill events are consumed by hb_bridge; must be exact

### Phase 11: `market_ingest.py` — Risk: **Medium**

- 1 function, ~110 lines
- Validates and stores market snapshots with ordering guarantees
- Dependencies: state, utils
- Test impact: snapshot rejection logic affects matching availability

### Phase 12: `heartbeat.py` — Risk: **Low**

- 1 function, ~80 lines
- Read-only aggregation from state
- Can be extracted at any time
- Test impact: heartbeat format

### Phase 13: `command_handler.py` — Risk: **Medium-High**

- `handle_command_payload` is 475 lines — the largest function
- Handles submit_order, cancel_order, cancel_all, sync_state
- Interacts with: matching_engine (crossing limits), position_manager (fills), order_fsm (state transitions)
- Dependencies: nearly all other modules
- Should be extracted after its dependencies are stable
- Internal decomposition (split submit/cancel/sync into sub-handlers) should follow

### Phase 14: `stream_processor.py` — Risk: **Medium-High**

- 2 functions, ~435 lines
- `process_command_rows` and `process_market_rows` orchestrate batch processing
- Call command_handler, matching_engine, fill_pipeline, funding, persistence
- Dependencies: all processing modules + Redis client
- Extract after command_handler and matching_engine

### Phase 15: `main.py` (slim) — Risk: **High** (Extract Last)

- `run()` is 220 lines — service main loop
- Creates Redis groups, runs reclaim, heartbeat, flush
- `_parse_args` is 280 lines — CLI setup
- Must be the final extraction after all processing modules are stable

---

## Risks

### handle_command_payload Size
At 475 lines, `handle_command_payload` is the single largest function. It should eventually be decomposed into `_handle_submit_order`, `_handle_cancel_order`, `_handle_cancel_all`, `_handle_sync_state` sub-handlers, but this is a second-order decomposition after the module extraction.

### Matching Engine Correctness
The matching engine generates fills that are the source of truth for all paper trading. Any bug in depth-level consumption, partial fill logic, or replay guards will cause position drift. Extensive test coverage must be maintained during extraction.

### PnL Calculation Chain
Fill → position update → realized PnL spans three proposed modules (`fill_pipeline` → `position_manager` → `funding`). The chain must produce identical results after extraction. Integration tests should verify end-to-end PnL for known scenarios.

### Redis Stream Semantics
`process_command_rows` and `process_market_rows` depend on Redis consumer group semantics (XREADGROUP, XACK, pending entry reclaim). These must remain in `stream_processor.py` with the Redis client. Processing functions should be pure (receive parsed data, return events to publish).

### Backward Compatibility
`main.py` is imported by the compose service entry point. The slim `main.py` must re-export `run`, `main`, `_parse_args`, `ServiceSettings` for backward compatibility.

### No Module-Level State Advantage
Unlike the other two files, `paper_exchange_service/main.py` passes state explicitly through function parameters. This makes extraction cleaner — no singleton concerns, no monkey-patching. The main risk is getting the import DAG right to avoid circular dependencies.

### process_market_rows Complexity
`process_market_rows` combines market ingestion, order matching, fill application, position updates, funding settlement, and event publishing in a single function. It should be decomposed into a pipeline: ingest → match → fill → position → fund → publish. Each stage maps cleanly to a proposed module.
