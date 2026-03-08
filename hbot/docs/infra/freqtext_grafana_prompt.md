# Prompt: Generate/Update FreqText-style Grafana Dashboard JSON

Copy and paste the block below to an LLM to regenerate or update
`hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json`.

---

```
You are a Grafana dashboard JSON expert. Update the existing Grafana dashboard
JSON (uid "kzay-capital-ftui", title "Kzay Capital FTUI Bot Monitor") to replicate the layout and
data shown in a FreqText/FTUI terminal trading dashboard screenshot.

## Existing dashboard to update

File: hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json
The file already has correct settings for: uid, title, timezone (utc), style
(dark), refresh (15s), annotations (hard_stop, derisk Loki annotations),
dashboard links (Trading Desk, Bot Deep Dive), and template variables:
  - $bot  → label_values(hbot_bot_equity_quote, bot)
  - $variant → label_values(hbot_bot_equity_quote{bot=~"$bot"}, variant)

DO NOT change uid, title, timezone, style, refresh, annotations, links, or
the two template variables above.

## Datasources available

- Prometheus datasource uid: "prometheus"
- Loki datasource uid: "loki"

## New Prometheus metrics now available (exported by bot_metrics_exporter.py)

All series carry labels: bot, variant, mode, accounting, exchange, pair,
regime (same as existing hbot_bot_* series).
Per-position series additionally carry: instrument_id, pair.

### From paper_desk_v2.json
  hbot_bot_open_pnl_quote                    — sum unrealized_pnl all positions
  hbot_bot_position_quantity_base{instrument_id,pair}
  hbot_bot_position_avg_entry_price{instrument_id,pair}
  hbot_bot_position_unrealized_pnl_quote{instrument_id,pair}
  hbot_bot_position_opened_at_seconds{instrument_id,pair}
  hbot_bot_position_total_fees_paid_quote{instrument_id,pair}

### From fills.csv (per bot+variant, computed on every scrape)
  hbot_bot_closed_pnl_quote_total            — sum realized_pnl_quote
  hbot_bot_trades_total                      — row count
  hbot_bot_trade_wins_total                  — rows where realized_pnl_quote > 0
  hbot_bot_trade_losses_total                — rows where realized_pnl_quote < 0
  hbot_bot_trade_winrate                     — wins/(wins+losses) in [0,1]
  hbot_bot_trade_expectancy_quote            — mean nonzero realized_pnl
  hbot_bot_trade_expectancy_rate_quote       — avg_win*wr - avg_loss*(1-wr)
  hbot_bot_trade_median_win_quote            — median positive realized_pnl
  hbot_bot_trade_median_loss_quote           — median negative realized_pnl
  hbot_bot_first_fill_timestamp_seconds      — epoch of earliest fill row

### From minute.csv history (computed on every scrape)
  hbot_bot_equity_start_quote                — equity_quote of the first minute row
  hbot_bot_realized_pnl_week_quote           — 7-day day-boundary aggregation
  hbot_bot_realized_pnl_month_quote          — 30-day day-boundary aggregation

### Existing relevant metrics (already exported, keep using them)
  hbot_bot_realized_pnl_today_quote          — daily PnL (current day so far)
  hbot_bot_equity_quote                      — current equity
  hbot_bot_mid_price                         — derived from recording rule

## Target layout (replace the existing panels with these 5 sections)

KEEP the existing panels: "Bot State", "Equity", "Today P&L", "Drawdown",
"Regime", "Turnover", "Active Orders", "Fills Today", "Mid Price",
"Equity Curve", "Realized P&L Today", "Position Side", "Position (base)",
"Avg Entry", "Base % (gross)", "Target Base %", "Position Exposure Over Time",
"Fills Total", "Win Rate", "Notional Traded", "Fees Paid", "Avg Fill Slippage",
"Last Fill", "Fill P&L (last)", "Fill Activity", "Orders / Fills — Last 15 min",
"Time by Regime", "Time by State", "Net Edge vs Floor", "Snapshot Age",
"WS Reconnects", "Order Book Stale", "Cancel / min", "Margin Ratio",
"Funding Rate", "Tick Duration", "Bot Logs (live)".

ADD the following NEW panels BEFORE (above) all existing panels, using
row IDs starting from 200 (to avoid collision with existing panel IDs 1-71):

### SECTION A: FreqText Header (row 200)

Add a collapsed=false row panel (id=200):
  title: "FreqText — Summary"
  gridPos: {h:1, w:24, x:0, y:0}

Then shift ALL existing panels down by 22 (i.e. add 22 to their y coordinate).

Add 5 stat tiles at y=1:

Panel 201 — Open
  type: stat, title: "Open"
  gridPos: {h:4, w:5, x:0, y:1}
  datasource: prometheus
  expr: hbot_bot_open_pnl_quote{bot=~"$bot",variant=~"$variant"}
  reduceOptions.calcs: [lastNotNull]
  unit: currencyUSD, decimals: 2
  colorMode: background
  thresholds: [{color: red, value: null}, {color: green, value: 0}]

Panel 202 — Closed
  type: stat, title: "Closed"
  gridPos: {h:4, w:5, x:5, y:1}
  datasource: prometheus
  expr: hbot_bot_closed_pnl_quote_total{bot=~"$bot",variant=~"$variant"}
  unit: currencyUSD, decimals: 2
  colorMode: background
  thresholds: [{color: red, value: null}, {color: green, value: 0}]

Panel 203 — Daily
  type: stat, title: "Daily"
  gridPos: {h:4, w:4, x:10, y:1}
  datasource: prometheus
  expr: hbot_bot_realized_pnl_today_quote{bot=~"$bot",variant=~"$variant"}
  unit: currencyUSD, decimals: 2
  colorMode: background
  thresholds: [{color: red, value: null}, {color: green, value: 0}]

Panel 204 — Weekly
  type: stat, title: "Weekly"
  gridPos: {h:4, w:5, x:14, y:1}
  datasource: prometheus
  expr: hbot_bot_realized_pnl_week_quote{bot=~"$bot",variant=~"$variant"}
  unit: currencyUSD, decimals: 2
  colorMode: background
  thresholds: [{color: red, value: null}, {color: green, value: 0}]

Panel 205 — Monthly
  type: stat, title: "Monthly"
  gridPos: {h:4, w:5, x:19, y:1}
  datasource: prometheus
  expr: hbot_bot_realized_pnl_month_quote{bot=~"$bot",variant=~"$variant"}
  unit: currencyUSD, decimals: 2
  colorMode: background
  thresholds: [{color: red, value: null}, {color: green, value: 0}]

### SECTION B: Bot Performance Table (row 210)

Add a collapsed=false row panel (id=210):
  title: "FreqText — Bot Performance"
  gridPos: {h:1, w:24, x:0, y:5}

Panel 211 — Bot Performance
  type: table
  title: "Bot Performance"
  gridPos: {h:8, w:24, x:0, y:6}
  datasource: prometheus

  targets (all instant=true, format=table):
    refId A: hbot_bot_open_pnl_quote{bot=~"$bot",variant=~"$variant"}
    refId B: hbot_bot_closed_pnl_quote_total{bot=~"$bot",variant=~"$variant"}
    refId C: hbot_bot_trades_total{bot=~"$bot",variant=~"$variant"}
    refId D: hbot_bot_trade_wins_total{bot=~"$bot",variant=~"$variant"}
    refId E: hbot_bot_trade_losses_total{bot=~"$bot",variant=~"$variant"}
    refId F: hbot_bot_trade_winrate{bot=~"$bot",variant=~"$variant"}
    refId G: hbot_bot_trade_expectancy_quote{bot=~"$bot",variant=~"$variant"}
    refId H: hbot_bot_trade_expectancy_rate_quote{bot=~"$bot",variant=~"$variant"}
    refId I: hbot_bot_trade_median_win_quote{bot=~"$bot",variant=~"$variant"}
    refId J: hbot_bot_trade_median_loss_quote{bot=~"$bot",variant=~"$variant"}
    refId K: hbot_bot_first_fill_timestamp_seconds{bot=~"$bot",variant=~"$variant"}

  transformations:
    1. merge (outer join on Time)
    2. organize (rename + reorder):
         "Value #A" → "Open Profit"
         "Value #B" → "Tot. Profit"
         "Value #C" → "# Trades"
         "Value #D" → "Wins"
         "Value #E" → "Losses"
         "Value #F" → "Winrate"
         "Value #G" → "Exp."
         "Value #H" → "Exp. Rate"
         "Value #I" → "Med. W"
         "Value #J" → "Med. L"
         "Value #K" → "Start"
         hide: Time

  fieldConfig overrides:
    "Open Profit":  unit=currencyUSD, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Tot. Profit":  unit=currencyUSD, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Winrate":      unit=percentunit, decimals=1
    "Exp.":         unit=currencyUSD, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Exp. Rate":    unit=currencyUSD, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Med. W":       unit=currencyUSD, decimals=2, color=fixed, fixedColor=green
    "Med. L":       unit=currencyUSD, decimals=2, color=fixed, fixedColor=red
    "Start":        unit=dateTimeAsIso
    "# Trades":     unit=short, decimals=0
    "Wins":         unit=short, decimals=0
    "Losses":       unit=short, decimals=0

### SECTION C: All Open Trades (row 220)

Add a collapsed=false row panel (id=220):
  title: "FreqText — All Open Trades"
  gridPos: {h:1, w:24, x:0, y:14}

Panel 221 — All Open Trades
  type: table
  title: "All Open Trades"
  gridPos: {h:6, w:24, x:0, y:15}
  datasource: prometheus

  targets (all instant=true, format=table):
    refId A: hbot_bot_position_quantity_base{bot=~"$bot",variant=~"$variant"}
    refId B: hbot_bot_position_avg_entry_price{bot=~"$bot",variant=~"$variant"}
    refId C: hbot_bot_position_unrealized_pnl_quote{bot=~"$bot",variant=~"$variant"}
    refId D: hbot_bot_position_opened_at_seconds{bot=~"$bot",variant=~"$variant"}
    refId E: hbot_bot_mid_price{bot=~"$bot",variant=~"$variant"}

  transformations:
    1. merge (outer join on Time, also join on instrument_id label)
    2. filterByValue: "Value #A" notEqual 0  (exclude flat positions)
    3. addField: "Stake" = abs(Value #A) * Value #B
    4. addField: "Profit %" = Value #C / Stake * 100
    5. addField: "Dur. (s)" = now() - Value #D
    6. organize (rename + reorder):
         "instrument_id" → "ID"
         "pair" → "Pair"
         "bot" + "variant" → "Bot"
         "Stake" → "Stake"
         "Value #B" → "Open Rate"
         "Value #E" → "Rate"
         "Profit %" → "Profit %"
         "Value #C" → "Profit"
         "Dur. (s)" → "Dur."
         "Value #A" → "S/L"
         hide: Time, instrument_id (raw), mode, accounting, exchange, regime

  fieldConfig overrides:
    "Open Rate":  unit=currencyUSD, decimals=2
    "Rate":       unit=currencyUSD, decimals=2
    "Stake":      unit=currencyUSD, decimals=2
    "Profit %":   unit=percent, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Profit":     unit=currencyUSD, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Dur.":       unit=durationS
    "S/L":        mappings=[{type:range,from:0.0001,to:999999,result:{text:"L",color:green}},
                             {type:range,from:-999999,to:-0.0001,result:{text:"S",color:red}}]

### SECTION D: All Closed Trades (row 230)

Add a collapsed=false row panel (id=230):
  title: "FreqText — All Closed Trades"
  gridPos: {h:1, w:24, x:0, y:21}

Panel 231 — All Closed Trades
  type: table
  title: "All Closed Trades"
  gridPos: {h:10, w:24, x:0, y:22}
  datasource: loki

  target:
    refId: A
    queryType: range
    expr: |
      {job="epp_csv", bot=~"$bot", filename=~".*fills\\.csv"}
        | csv
        | realized_pnl_quote != "" and realized_pnl_quote != "0" and realized_pnl_quote != "0.0"
        | bot_variant=~"$variant"
    legendFormat: ""

  transformations:
    1. organize (rename + reorder + hide):
         show: ts, bot_variant, trading_pair, realized_pnl_quote, notional_quote, side, state, order_id
         rename: ts→"Open Date", bot_variant→"Bot", trading_pair→"Pair",
                 realized_pnl_quote→"Profit", notional_quote→"Notional",
                 side→"Enter", state→"Exit", order_id→"ID"
    2. addField "Profit %": Profit / Notional * 100
    3. sortBy: "Open Date" desc
    4. limit: 25

  fieldConfig overrides:
    "Profit":   unit=currencyUSD, decimals=4, color=thresholds, steps=[{red,null},{green,0}]
    "Profit %": unit=percent, decimals=2, color=thresholds, steps=[{red,null},{green,0}]
    "Notional": unit=currencyUSD, decimals=2
    "Open Date": unit=dateTimeAsIso
    "Enter": mappings=[{type:value, options:{buy:{text:"buy",color:green}, sell:{text:"sell",color:red}}}]

### SECTION E: Cumulative Profit (row 240)

Add a collapsed=false row panel (id=240):
  title: "FreqText — Cumulative Profit"
  gridPos: {h:1, w:24, x:0, y:32}

Panel 241 — Cumulative Profit
  type: timeseries
  title: "Cumulative Profit"
  gridPos: {h:10, w:24, x:0, y:33}
  datasource: prometheus

  target:
    refId: A
    expr: |
      hbot_bot_equity_quote{bot=~"$bot",variant=~"$variant"}
      - hbot_bot_equity_start_quote{bot=~"$bot",variant=~"$variant"}
    legendFormat: "{{bot}} cumulative profit"

  fieldConfig:
    defaults:
      unit: currencyUSD
      decimals: 2
      color: {mode: fixed, fixedColor: orange}
      custom:
        lineWidth: 2
        fillOpacity: 30
        gradientMode: opacity
        drawStyle: line
        spanNulls: false

  options:
    tooltip: {mode: single}
    legend: {displayMode: hidden}

## Output format

Emit the complete valid Grafana dashboard JSON object (the content of
ftui_bot_monitor.json) with ALL of the following preserved:
  - uid: "kzay-capital-ftui"
  - title: "FTUI Bot Monitor"
  - All existing panels (IDs 1-71) with y values shifted by +43
    (to place them after the 5 new FreqText sections which occupy y=0..42)
  - All new panels (IDs 200-241) as specified above
  - schemaVersion: 39
  - All annotations, links, and template variables unchanged

Emit ONLY the raw JSON object (no markdown fences, no explanation).
```
