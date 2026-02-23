# Event Schema v1 (Option 4)

## Purpose
Define a canonical, append-only event contract for:
- execution auditability
- reconciliation
- shadow execution parity
- portfolio risk aggregation

## Scope
This schema covers the minimum event set required to start Day 2:
- `order_created`
- `order_cancelled`
- `order_failed`
- `order_filled`
- `risk_decision`
- `state_snapshot`

## Envelope (Required for all events)

```json
{
  "event_id": "uuid-v4",
  "event_type": "string",
  "event_version": "v1",
  "ts_utc": "ISO-8601",
  "producer": "service-or-controller-name",
  "instance_name": "bot1",
  "controller_id": "epp_v2_4",
  "connector_name": "bitget|bitget_paper_trade|...",
  "trading_pair": "BTC-USDT",
  "correlation_id": "uuid-or-empty",
  "payload": {}
}
```

## Correlation Rules
- `correlation_id` links one decision/action chain across services.
- For first event in a chain, `correlation_id == event_id`.
- Downstream events must carry upstream `correlation_id`.
- Missing `correlation_id` is allowed only for legacy ingestion and must be backfilled as `event_id`.

## Event Definitions

### 1) `order_created`
Payload:
- `client_order_id` (required)
- `side` (`buy`/`sell`, required)
- `order_type` (`limit`/`market`/`limit_maker`, required)
- `price` (required for limit-like)
- `amount_base` (required)
- `amount_quote` (optional)
- `is_live` (required)

### 2) `order_cancelled`
Payload:
- `client_order_id` (required)
- `reason` (optional)
- `cancel_source` (`strategy`/`risk`/`ops`/`exchange`, optional)

### 3) `order_failed`
Payload:
- `client_order_id` (optional if unavailable)
- `error_code` (optional)
- `error_message` (required)
- `failure_stage` (`create`/`cancel`/`update`, optional)

### 4) `order_filled`
Payload:
- `client_order_id` (required)
- `fill_id` (optional)
- `fill_price` (required)
- `fill_qty_base` (required)
- `fill_qty_quote` (required)
- `fee_asset` (required)
- `fee_amount` (required)
- `liquidity_side` (`maker`/`taker`/`unknown`, required)

### 5) `risk_decision`
Payload:
- `approved` (required)
- `decision` (`allow`/`soft_pause`/`hard_stop`/`reduce`, required)
- `reason` (required)
- `max_notional_quote` (optional)
- `policy_name` (optional)

### 6) `state_snapshot`
Payload:
- `state` (`running`/`soft_pause`/`hard_stop`, required)
- `regime` (optional)
- `net_edge_pct` (optional)
- `spread_pct` (optional)
- `base_pct` (optional)
- `target_base_pct` (optional)
- `equity_quote` (optional)

## Validation Rules (v1)
- Reject event if missing required envelope fields.
- Reject event if `event_type` unknown.
- Reject event if `ts_utc` is not parseable UTC timestamp.
- Reject event if required payload keys for `event_type` are missing.
- Accept additional payload keys for forward compatibility.

## Storage Contract (Append-Only)
- Write-only append semantics (no in-place mutation).
- Recommended partition key: `date(ts_utc)` + `instance_name`.
- Retain raw event payload and parsed columns.
- Store ingest metadata:
  - `ingest_ts_utc`
  - `ingest_source`
  - `schema_validation_status`

## Day 2 Acceptance Hooks
- Source-to-store event count delta by type.
- Missing correlation ratio.
- Invalid schema ratio.
- Event lag (ingest_ts_utc - ts_utc).

## Next Step
Implement `services/event_store/` ingestion path using this contract and map current producers to `event_type` values.
