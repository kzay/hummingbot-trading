# FreqText → Grafana Dashboard Spec

**Target dashboard:** `FTUI Bot Monitor` (uid: `hbot-ftui`,
file: `hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json`)

**Canonical terminal reference:** `hbot/scripts/analysis/ftui_dashboard.py`  
**Screenshot reference:** FreqText TUI as shown in `docs/infra/` assets

---

## 1. Dashboard-level settings

| Setting | Value |
|---|---|
| uid | `hbot-ftui` |
| title | `FTUI Bot Monitor` |
| timezone | `utc` |
| style | `dark` |
| refresh | `15s` |
| schemaVersion | `39` |
| Variables | `bot` (query from `hbot_bot_equity_quote`), `variant` (query from `hbot_bot_equity_quote{bot=~"$bot"}`) |

---

## 2. Section layout (top to bottom)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ROW: Header stats (5 stat tiles, full width)                        │
│  [Open]  [Closed]  [Daily]  [Weekly]  [Monthly]                     │
├─────────────────────────────────────────────────────────────────────┤
│ ROW: Bot Performance Table (full width)                             │
│  Bot | Start | #Trades | Open Profit | W/L | Winrate | Exp |        │
│  Exp.Rate | Med.W | Med.L | Tot.Profit                              │
├─────────────────────────────────────────────────────────────────────┤
│ ROW: All Open Trades (full width)                                   │
│  Bot | ID | Pair | Stake | Open Rate | Rate | Stop% | Profit% |     │
│  Profit | Dur. | S/L | Tag                                          │
├─────────────────────────────────────────────────────────────────────┤
│ ROW: All Closed Trades (full width)                                 │
│  Bot | ID | Pair | Profit% | Profit | Open Date | Dur | Enter | Exit│
├─────────────────────────────────────────────────────────────────────┤
│ ROW: Cumulative Profit chart (full width, orange line + fill)        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Panel specifications

### 3.1 Header — 5 stat tiles

All header tiles share these display settings:
- `type: stat`, `colorMode: background`, `textMode: auto`, `graphMode: none`
- Font size: large
- Threshold steps: red (< 0), green (> 0) — mirroring FreqText color logic in `_color_pnl()`

| Tile | Label | Source metric | Formula / derivation |
|---|---|---|---|
| Open | `Open` | `hbot_bot_open_pnl_quote` | sum of `portfolio.positions.*.unrealized_pnl` from `paper_desk_v2.json`; exported by exporter |
| Closed | `Closed` | `hbot_bot_closed_pnl_quote_total` | sum of `realized_pnl_quote` across all rows in `fills.csv`; exported by exporter |
| Daily | `Daily` | `hbot_bot_realized_pnl_today_quote` | latest `realized_pnl_today_quote` from `minute.csv` (already exported) |
| Weekly | `Weekly` | `hbot_bot_realized_pnl_week_quote` | 7-day boundary aggregation per `DashboardData._pnl_since(7)`; exported by exporter |
| Monthly | `Monthly` | `hbot_bot_realized_pnl_month_quote` | 30-day boundary aggregation per `DashboardData._pnl_since(30)`; exported by exporter |

**Color thresholds (all tiles):**
```
steps:
  - value: null  → red
  - value: 0     → green   (>=0)
```

**gridPos:** 5 equal columns across w=24. Each tile w=4 (plus one w=4 spare shared), typically:
- Open: `{x:0, w:4, h:4}`
- Closed: `{x:4, w:4, h:4}`
- Daily: `{x:8, w:5, h:4}`
- Weekly: `{x:13, w:6, h:4}`
- Monthly: `{x:19, w:5, h:4}`

---

### 3.2 Bot Performance Table

- `type: table`, full width `w:24`, `h:8`
- Datasource: Prometheus (all columns from separate instant queries, merged on `bot`+`variant`)
- Each metric queried with `format: table, instant: true`

| Column | Display name | Source metric | Grafana unit / format |
|---|---|---|---|
| Bot | `Bot` | label `bot` from any metric | string |
| Start | `Start` | `hbot_bot_first_fill_timestamp_seconds` | `dateTimeAsIso` |
| # Trades | `# Trades` | `hbot_bot_trades_total` | `short` integer |
| Open Profit | `Open Profit` | `hbot_bot_open_pnl_quote` | `currencyUSD` 2dp; red/green threshold |
| W/L | `W/L` | `hbot_bot_trade_wins_total` + `hbot_bot_trade_losses_total` (transform concat) | string, rendered via value mapping in Grafana transform |
| Winrate | `Winrate` | `hbot_bot_trade_winrate` | `percent` 1dp |
| Exp. | `Exp.` | `hbot_bot_trade_expectancy_quote` | `currencyUSD` 2dp |
| Exp. Rate | `Exp. Rate` | `hbot_bot_trade_expectancy_rate_quote` | `currencyUSD` 2dp |
| Med. W | `Med. W` | `hbot_bot_trade_median_win_quote` | `currencyUSD` 2dp; green |
| Med. L | `Med. L` | `hbot_bot_trade_median_loss_quote` | `currencyUSD` 2dp; red |
| Tot. Profit | `Tot. Profit` | `hbot_bot_closed_pnl_quote_total` | `currencyUSD` 2dp; red/green threshold |

**Prometheus expressions (all instant, format=table):**
```promql
hbot_bot_open_pnl_quote{bot=~"$bot",variant=~"$variant"}
hbot_bot_closed_pnl_quote_total{bot=~"$bot",variant=~"$variant"}
hbot_bot_trades_total{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_wins_total{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_losses_total{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_winrate{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_expectancy_quote{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_expectancy_rate_quote{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_median_win_quote{bot=~"$bot",variant=~"$variant"}
hbot_bot_trade_median_loss_quote{bot=~"$bot",variant=~"$variant"}
hbot_bot_first_fill_timestamp_seconds{bot=~"$bot",variant=~"$variant"}
```

Use Grafana **Transform → Outer join on `Time`** + **Rename by regex** to produce the table.

---

### 3.3 All Open Trades

- `type: table`, full width `w:24`, `h:6`
- Datasource: Prometheus (all instant, format=table)

| Column | Display name | Metric / derivation | Notes |
|---|---|---|---|
| Bot | `Bot` | label `bot` + `variant` | string |
| ID | `ID` | label `instrument_id` on `hbot_bot_position_quantity_base` | short string |
| Pair | `Pair` | label `pair` on `hbot_bot_position_quantity_base` | e.g. `BTC-USDT` |
| Stake | `Stake` | `abs(hbot_bot_position_quantity_base) * hbot_bot_position_avg_entry_price` | `currencyUSD` 2dp |
| Open Rate | `Open Rate` | `hbot_bot_position_avg_entry_price` | `currencyUSD` 2dp |
| Rate | `Rate` | `hbot_bot_mid_price` (derived from best bid/ask recording rule) | `currencyUSD` 2dp |
| Stop % | `Stop %` | `"—"` (not currently exported; use static override) | — |
| Profit % | `Profit %` | `hbot_bot_position_unrealized_pnl_quote / (abs(hbot_bot_position_quantity_base) * hbot_bot_position_avg_entry_price) * 100` | `percent` 2dp; red/green |
| Profit | `Profit` | `hbot_bot_position_unrealized_pnl_quote` | `currencyUSD` 2dp; red/green |
| Dur. | `Dur.` | `(time() - hbot_bot_position_opened_at_seconds)` | `durationMs` or `s`; shown as HH:MM:SS |
| S/L | `S/L` | `hbot_bot_position_quantity_base > 0 → "L", < 0 → "S"` via value mappings | string; green for L, red for S |
| Tag | `Tag` | `"epp_v2_4"` (static label or annotation from exporter) | dim text |

**Prometheus expressions:**
```promql
# Quantity (signed, base asset)
hbot_bot_position_quantity_base{bot=~"$bot",variant=~"$variant"}
# Average entry price
hbot_bot_position_avg_entry_price{bot=~"$bot",variant=~"$variant"}
# Unrealized PnL
hbot_bot_position_unrealized_pnl_quote{bot=~"$bot",variant=~"$variant"}
# Position opened timestamp
hbot_bot_position_opened_at_seconds{bot=~"$bot",variant=~"$variant"}
# Mid price (already available via recording rule)
hbot_bot_mid_price{bot=~"$bot",variant=~"$variant"}
```

**Filter:** only show rows where `hbot_bot_position_quantity_base != 0`.

---

### 3.4 All Closed Trades

- `type: table`, full width `w:24`, `h:10`
- Datasource: **Loki** (`{job="epp_csv", bot=~"$bot"}`)
- Parser: `pattern` or `regexp` on CSV line
- Filter: `realized_pnl_quote != 0` (non-zero means a round-trip was closed)
- Sort: descending time (most recent first)
- Limit: 25 rows (match `DashboardData.closed_trades(n=25)`)

**Loki query:**
```logql
{job="epp_csv", bot=~"$bot"}
  | csv
  | realized_pnl_quote != "0" and realized_pnl_quote != "" and realized_pnl_quote != "0.0"
  | bot_variant=~"$variant"
  | line_format "{{ .ts }},{{ .bot_variant }},{{ .trading_pair }},{{ .realized_pnl_quote }},{{ .notional_quote }},{{ .side }},{{ .state }},{{ .order_id }}"
```

**Alternative (if fills.csv has a header row and Loki CSV parser handles it):**
```logql
{job="epp_csv", bot=~"$bot", filename=~".*fills.csv"}
  | csv
  | realized_pnl_quote != "0" and realized_pnl_quote != ""
```

| Column | Loki field | Unit | Notes |
|---|---|---|---|
| Bot | `bot` label + `bot_variant` | string | |
| ID | `order_id` (last segment after `_`) | string | |
| Pair | `trading_pair` | string | |
| Profit % | `realized_pnl_quote / notional_quote * 100` | `percent` 2dp | red/green |
| Profit | `realized_pnl_quote` | `currencyUSD` 4dp | red/green |
| Open Date | `ts` | `dateTimeAsIso` | |
| Dur. | `"—"` | — | duration not in fills.csv |
| Enter | `side` | buy=green / sell=red | |
| Exit | `state` | dim text | e.g. `closed_filled` |

---

### 3.5 Cumulative Profit (timeseries chart)

- `type: timeseries`, full width `w:24`, `h:10`
- Datasource: Prometheus
- Style: orange line, fill opacity 30, gradient mode `opacity`, dark background

**Prometheus expression:**
```promql
hbot_bot_equity_quote{bot=~"$bot",variant=~"$variant"}
- hbot_bot_equity_start_quote{bot=~"$bot",variant=~"$variant"}
```

Where `hbot_bot_equity_start_quote` is the first `equity_quote` row observed in `minute.csv` (lowest timestamp entry), matching `DashboardData.equity_series()` which subtracts `raw[0]`.

**Field config:**
```json
{
  "unit": "currencyUSD",
  "decimals": 2,
  "color": {"mode": "fixed", "fixedColor": "orange"},
  "custom": {
    "lineWidth": 2,
    "fillOpacity": 30,
    "gradientMode": "opacity",
    "drawStyle": "line",
    "spanNulls": false
  }
}
```

**Y-axis:** labels at top, mid, bottom (matching the ASCII chart in `ftui_dashboard.py`).

---

## 4. Metric definitions (new exports needed)

These metrics must be added to `hbot/services/bot_metrics_exporter.py`.

### 4.1 From `paper_desk_v2.json`

Read path: `data/<bot>/logs/epp_v24/<variant>/paper_desk_v2.json`

| Metric | Type | Labels | Formula |
|---|---|---|---|
| `hbot_bot_open_pnl_quote` | gauge | `bot,variant,...` | `sum(portfolio.positions.*.unrealized_pnl)` |
| `hbot_bot_position_quantity_base` | gauge | `+instrument_id,pair` | `portfolio.positions[key].quantity` |
| `hbot_bot_position_avg_entry_price` | gauge | `+instrument_id,pair` | `portfolio.positions[key].avg_entry_price` |
| `hbot_bot_position_unrealized_pnl_quote` | gauge | `+instrument_id,pair` | `portfolio.positions[key].unrealized_pnl` |
| `hbot_bot_position_opened_at_seconds` | gauge | `+instrument_id,pair` | `portfolio.positions[key].opened_at_ns / 1e9` |
| `hbot_bot_position_total_fees_paid_quote` | gauge | `+instrument_id,pair` | `portfolio.positions[key].total_fees_paid` |

`instrument_id`: the JSON key (e.g. `bitget:BTC-USDT:perp`).  
`pair`: extracted as `key.split(":")[1]` (e.g. `BTC-USDT`).

### 4.2 From `fills.csv` (per bot+variant)

Computed by scanning all rows in `fills.csv` (same scan already done in `_compute_fill_stats()`).

| Metric | Formula |
|---|---|
| `hbot_bot_closed_pnl_quote_total` | `sum(realized_pnl_quote)` over all rows |
| `hbot_bot_trades_total` | row count |
| `hbot_bot_trade_wins_total` | count rows where `realized_pnl_quote > 0` |
| `hbot_bot_trade_losses_total` | count rows where `realized_pnl_quote < 0` |
| `hbot_bot_trade_winrate` | `wins / (wins + losses)` |
| `hbot_bot_trade_expectancy_quote` | `mean(nonzero realized_pnl_quote)` |
| `hbot_bot_trade_expectancy_rate_quote` | `avg_win * winrate - avg_loss * (1-winrate)` |
| `hbot_bot_trade_median_win_quote` | median of positive `realized_pnl_quote` |
| `hbot_bot_trade_median_loss_quote` | median of negative `realized_pnl_quote` |
| `hbot_bot_first_fill_timestamp_seconds` | epoch of first row's `ts` field |

### 4.3 From `minute.csv` history

| Metric | Formula |
|---|---|
| `hbot_bot_equity_start_quote` | `equity_quote` from the **first** (oldest) row in `minute.csv` |
| `hbot_bot_realized_pnl_week_quote` | 7-day day-boundary aggregation (see note below) |
| `hbot_bot_realized_pnl_month_quote` | 30-day day-boundary aggregation |

**Day-boundary aggregation (matches `_pnl_since()`):**
```
For each day boundary transition in minute.csv rows within the last N days,
  accumulate the last `realized_pnl_today_quote` value of each completed day.
Add current day's latest `realized_pnl_today_quote` for the partial day.
Total = sum of all completed days + current day.
```

This is computed once per scrape by scanning all rows of `minute.csv`.

---

## 5. Data-to-metric mapping summary (no mystery numbers)

| FreqText widget | `ftui_dashboard.py` method | Grafana source |
|---|---|---|
| `Open` header | `DashboardData.open_pnl()` | `hbot_bot_open_pnl_quote` |
| `Closed` header | `DashboardData.closed_pnl()` | `hbot_bot_closed_pnl_quote_total` |
| `Daily` header | `DashboardData.daily_pnl()` | `hbot_bot_realized_pnl_today_quote` |
| `Weekly` header | `DashboardData._pnl_since(7)` | `hbot_bot_realized_pnl_week_quote` |
| `Monthly` header | `DashboardData._pnl_since(30)` | `hbot_bot_realized_pnl_month_quote` |
| Bot table — Start | `fills[0]['ts']` | `hbot_bot_first_fill_timestamp_seconds` |
| Bot table — #Trades | `len(fills)` | `hbot_bot_trades_total` |
| Bot table — W/L | `len(wins)`, `len(losses)` | `hbot_bot_trade_wins_total`, `hbot_bot_trade_losses_total` |
| Bot table — Winrate | `winrate` | `hbot_bot_trade_winrate` |
| Bot table — Exp. | `mean(nonzero_pnl)` | `hbot_bot_trade_expectancy_quote` |
| Bot table — Exp. Rate | `avg_win*wr - avg_loss*(1-wr)` | `hbot_bot_trade_expectancy_rate_quote` |
| Bot table — Med.W/L | `median(wins/losses)` | `hbot_bot_trade_median_win_quote`, `hbot_bot_trade_median_loss_quote` |
| Bot table — Tot.Profit | `sum(pnl_list)` | `hbot_bot_closed_pnl_quote_total` |
| Open Trades — table | `DashboardData.open_trades()` | per-position metrics (`hbot_bot_position_*`) |
| Closed Trades — table | `DashboardData.closed_trades()` | Loki `{job="epp_csv"}` fills.csv rows |
| Cumulative Profit chart | `DashboardData.equity_series()` | `hbot_bot_equity_quote - hbot_bot_equity_start_quote` |

---

## 6. Styling rules (match the dark FreqText terminal aesthetic)

- Dashboard background: dark (Grafana dark theme)
- Header values: large font, white text, colored background (red/green)
- Tables: compact, monospace-style, no padding
  - Positive PnL values: green (`#73BF69`)
  - Negative PnL values: red (`#F2495C`)
  - Neutral / zero: white text
  - Column headers: cyan (`bold cyan` in Rich → `header_style` override in Grafana)
- Chart:
  - Background: dark
  - Line: orange (`#FF9900` or Grafana `orange`)
  - Fill: orange with 30% opacity
  - Y-axis labels: left-aligned, 3 ticks (top, mid, bottom) matching ASCII chart labels
  - X-axis: UTC timestamp
