# Execution Quality Dashboard Specification

## Dashboard: Trading Desk Execution Quality
**UID:** `execution-quality-v1`
**Datasource:** Prometheus

### Row 1: Fill Performance
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Fill Rate | Time series | `rate(hbot_bot_fills_total[1h])` | Fills per hour per bot |
| Maker Ratio | Gauge | Derive from fills.csv `is_maker` column (Postgres query) | % of fills that are maker |
| Spread Capture | Stat | From `edge_report.json` → `avg_capture_bps` | Average bps captured per fill |
| Fill Factor | Stat | From `fill_factor_calibration.json` → `realized_fill_factor` | Realized vs configured |

### Row 2: Execution Timing
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Tick Duration | Time series | `hbot_bot_tick_duration_seconds` | Total tick wall time |
| Component Breakdown | Stacked area | `hbot_bot_tick_indicator_seconds`, `hbot_bot_tick_connector_io_seconds` | What's slow? |
| Connector I/O | Time series | `hbot_bot_tick_connector_io_seconds` | Balance/book read latency |
| WS Reconnects | Counter | `hbot_bot_ws_reconnect_total` | Connectivity stability |

### Row 3: Adverse Selection
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Adverse Drift | Time series | From `processed_data.adverse_drift_30s` | 30s price drift at fill time |
| Order Book Stale | State timeline | `hbot_bot_order_book_stale` | WS feed health |

---

## Dashboard: Trading Desk Risk & Exposure
**UID:** `risk-exposure-v1`
**Datasource:** Prometheus

### Row 1: Position Risk
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Position Drift | Gauge | `hbot_bot_position_drift_pct` | Local vs exchange position divergence |
| Margin Ratio | Gauge | `hbot_bot_margin_ratio` | Distance from liquidation (perps) |
| Funding Rate | Time series | `hbot_bot_funding_rate` | Current 8h funding rate |

### Row 2: Loss Controls
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Daily Loss vs Limit | Bar gauge | `hbot_bot_daily_loss_pct` vs 0.03 threshold | % of daily limit used |
| Drawdown vs Limit | Bar gauge | `hbot_bot_drawdown_pct` vs 0.05 threshold | % of drawdown limit used |
| Realized PnL Today | Stat | `hbot_bot_realized_pnl_today_quote` | Fill-level PnL (not mark-to-market) |

### Row 3: Portfolio
| Panel | Type | Metric | Description |
|-------|------|--------|-------------|
| Cross-Bot Equity | Table | `hbot_bot_equity_quote` grouped by bot | Total desk equity |
| Base Allocation | Time series | `hbot_bot_base_pct` per bot | Inventory distribution |
| Risk Reasons | Table | `hbot_bot_risk_reasons_info` | Active risk flags |
