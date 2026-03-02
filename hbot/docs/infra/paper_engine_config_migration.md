# Paper Engine Config Migration

This project now uses a nested `paper_engine` block in `EppV24Config`.

Legacy top-level `paper_*` keys are no longer migrated automatically.

## New structure

Use:

```yaml
paper_engine:
  paper_realism_profile: balanced
  paper_latency_ms: 150
  paper_queue_participation: 0.35
  # ...other paper_* keys...
```

`paper_edge_gate_bypass` remains a top-level strategy key (not part of `paper_engine`).

## Key mapping

All listed legacy keys move under `paper_engine` with the same name:

- `paper_equity_quote` -> `paper_engine.paper_equity_quote`
- `paper_seed` -> `paper_engine.paper_seed`
- `paper_realism_profile` -> `paper_engine.paper_realism_profile`
- `paper_fill_model` -> `paper_engine.paper_fill_model`
- `paper_latency_model` -> `paper_engine.paper_latency_model`
- `paper_latency_ms` -> `paper_engine.paper_latency_ms`
- `paper_insert_latency_ms` -> `paper_engine.paper_insert_latency_ms`
- `paper_cancel_latency_ms` -> `paper_engine.paper_cancel_latency_ms`
- `paper_liquidity_consumption` -> `paper_engine.paper_liquidity_consumption`
- `paper_queue_participation` -> `paper_engine.paper_queue_participation`
- `paper_slippage_bps` -> `paper_engine.paper_slippage_bps`
- `paper_adverse_selection_bps` -> `paper_engine.paper_adverse_selection_bps`
- `paper_partial_fill_min_ratio` -> `paper_engine.paper_partial_fill_min_ratio`
- `paper_partial_fill_max_ratio` -> `paper_engine.paper_partial_fill_max_ratio`
- `paper_depth_levels` -> `paper_engine.paper_depth_levels`
- `paper_depth_decay` -> `paper_engine.paper_depth_decay`
- `paper_queue_position_enabled` -> `paper_engine.paper_queue_position_enabled`
- `paper_queue_ahead_ratio` -> `paper_engine.paper_queue_ahead_ratio`
- `paper_queue_trade_through_ratio` -> `paper_engine.paper_queue_trade_through_ratio`
- `paper_price_protection_points` -> `paper_engine.paper_price_protection_points`
- `paper_margin_model_type` -> `paper_engine.paper_margin_model_type`
- `paper_max_fills_per_order` -> `paper_engine.paper_max_fills_per_order`

Context keys are also copied into the nested block when creating explicit config objects:

- `fee_profile` -> `paper_engine.fee_profile`
- `instance_name` -> `paper_engine.instance_name`
- `variant` -> `paper_engine.variant`
- `log_dir` -> `paper_engine.log_dir`

## Validation behavior

- Missing `paper_engine` in runtime controller wiring now fails fast.
- `PaperDesk.from_epp_config(...)` expects `cfg.paper_engine` to exist.
- `PaperDesk.from_paper_config(...)` remains the recommended constructor.
