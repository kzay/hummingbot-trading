"""
One-shot script: update ftui_bot_monitor.json with FreqText-style panels.
Run from workspace root: python hbot/scripts/ops/inject_freqtext_panels.py
"""
import json
import pathlib

DASHBOARD_PATH = pathlib.Path(
    "hbot/monitoring/grafana/dashboards/ftui_bot_monitor.json"
)

DS_PROM = {"type": "prometheus", "uid": "prometheus"}
DS_LOKI = {"type": "loki", "uid": "loki"}
THRESH_PNL = {
    "mode": "absolute",
    "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}],
}

Y_SHIFT = 43  # existing panels shifted down by this many rows


def stat_panel(id_, title, expr, x, w, y=1, h=4, unit="currencyUSD", decimals=2):
    return {
        "id": id_,
        "type": "stat",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": DS_PROM,
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "horizontal",
            "textMode": "auto",
            "graphMode": "none",
            "colorMode": "background",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "color": {"mode": "thresholds"},
                "thresholds": THRESH_PNL,
            }
        },
        "targets": [
            {
                "datasource": DS_PROM,
                "expr": expr,
                "legendFormat": "{{bot}}",
                "refId": "A",
                "instant": True,
            }
        ],
    }


def row_panel(id_, title, y):
    return {
        "type": "row",
        "id": id_,
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
    }


def build_new_panels():
    panels = []

    # ── Section A: FreqText Summary (y=0..4) ─────────────────────────────────
    panels.append(row_panel(200, "FreqText — Summary", y=0))
    panels.append(stat_panel(201, "Open",    'hbot_bot_open_pnl_quote{bot=~"$bot",variant=~"$variant"}',           x=0,  w=5))
    panels.append(stat_panel(202, "Closed",  'hbot_bot_closed_pnl_quote_total{bot=~"$bot",variant=~"$variant"}',   x=5,  w=5))
    panels.append(stat_panel(203, "Daily",   'hbot_bot_realized_pnl_today_quote{bot=~"$bot",variant=~"$variant"}', x=10, w=4))
    panels.append(stat_panel(204, "Weekly",  'hbot_bot_realized_pnl_week_quote{bot=~"$bot",variant=~"$variant"}',  x=14, w=5))
    panels.append(stat_panel(205, "Monthly", 'hbot_bot_realized_pnl_month_quote{bot=~"$bot",variant=~"$variant"}', x=19, w=5))

    # ── Section B: Bot Performance Table (y=5..13) ───────────────────────────
    panels.append(row_panel(210, "FreqText — Bot Performance", y=5))
    panels.append(
        {
            "id": 211,
            "type": "table",
            "title": "Bot Performance",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": 6},
            "datasource": DS_PROM,
            "options": {"showHeader": True, "footer": {"show": False}},
            "targets": [
                {"datasource": DS_PROM, "expr": 'hbot_bot_open_pnl_quote{bot=~"$bot",variant=~"$variant"}',               "format": "table", "instant": True, "legendFormat": "", "refId": "A"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_closed_pnl_quote_total{bot=~"$bot",variant=~"$variant"}',       "format": "table", "instant": True, "legendFormat": "", "refId": "B"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trades_total{bot=~"$bot",variant=~"$variant"}',                 "format": "table", "instant": True, "legendFormat": "", "refId": "C"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_wins_total{bot=~"$bot",variant=~"$variant"}',             "format": "table", "instant": True, "legendFormat": "", "refId": "D"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_losses_total{bot=~"$bot",variant=~"$variant"}',           "format": "table", "instant": True, "legendFormat": "", "refId": "E"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_winrate{bot=~"$bot",variant=~"$variant"}',                "format": "table", "instant": True, "legendFormat": "", "refId": "F"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_expectancy_quote{bot=~"$bot",variant=~"$variant"}',       "format": "table", "instant": True, "legendFormat": "", "refId": "G"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_expectancy_rate_quote{bot=~"$bot",variant=~"$variant"}',  "format": "table", "instant": True, "legendFormat": "", "refId": "H"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_median_win_quote{bot=~"$bot",variant=~"$variant"}',       "format": "table", "instant": True, "legendFormat": "", "refId": "I"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_trade_median_loss_quote{bot=~"$bot",variant=~"$variant"}',      "format": "table", "instant": True, "legendFormat": "", "refId": "J"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_first_fill_timestamp_seconds{bot=~"$bot",variant=~"$variant"}', "format": "table", "instant": True, "legendFormat": "", "refId": "K"},
            ],
            "transformations": [
                {"id": "merge", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "renameByName": {
                            "Value #A": "Open Profit",
                            "Value #B": "Tot. Profit",
                            "Value #C": "# Trades",
                            "Value #D": "Wins",
                            "Value #E": "Losses",
                            "Value #F": "Winrate",
                            "Value #G": "Exp.",
                            "Value #H": "Exp. Rate",
                            "Value #I": "Med. W",
                            "Value #J": "Med. L",
                            "Value #K": "Start",
                        },
                        "excludeByName": {
                            "Time": True,
                            "mode": True,
                            "accounting": True,
                            "exchange": True,
                            "pair": True,
                            "regime": True,
                        },
                        "indexByName": {
                            "bot": 0, "variant": 1, "Value #K": 2,
                            "Value #C": 3, "Value #A": 4,
                            "Value #D": 5, "Value #E": 6, "Value #F": 7,
                            "Value #G": 8, "Value #H": 9,
                            "Value #I": 10, "Value #J": 11, "Value #B": 12,
                        },
                    },
                },
            ],
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Open Profit"}, "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "thresholds"}}, {"id": "thresholds", "value": THRESH_PNL}]},
                    {"matcher": {"id": "byName", "options": "Tot. Profit"},  "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "thresholds"}}, {"id": "thresholds", "value": THRESH_PNL}]},
                    {"matcher": {"id": "byName", "options": "Winrate"},      "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]},
                    {"matcher": {"id": "byName", "options": "Exp."},         "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "thresholds"}}, {"id": "thresholds", "value": THRESH_PNL}]},
                    {"matcher": {"id": "byName", "options": "Exp. Rate"},    "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "thresholds"}}, {"id": "thresholds", "value": THRESH_PNL}]},
                    {"matcher": {"id": "byName", "options": "Med. W"},       "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
                    {"matcher": {"id": "byName", "options": "Med. L"},       "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                    {"matcher": {"id": "byName", "options": "Start"},        "properties": [{"id": "unit", "value": "dateTimeAsIso"}]},
                    {"matcher": {"id": "byName", "options": "# Trades"},     "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}]},
                    {"matcher": {"id": "byName", "options": "Wins"},         "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}]},
                    {"matcher": {"id": "byName", "options": "Losses"},       "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0}]},
                ],
            },
        }
    )

    # ── Section C: All Open Trades (y=14..20) ────────────────────────────────
    panels.append(row_panel(220, "FreqText — All Open Trades", y=14))
    panels.append(
        {
            "id": 221,
            "type": "table",
            "title": "All Open Trades",
            "description": (
                "Live positions from paper_desk_v2.json. "
                "Flat positions (quantity=0) are excluded by the exporter."
            ),
            "gridPos": {"h": 6, "w": 24, "x": 0, "y": 15},
            "datasource": DS_PROM,
            "options": {"showHeader": True, "footer": {"show": False}},
            "targets": [
                {"datasource": DS_PROM, "expr": 'hbot_bot_position_quantity_base{bot=~"$bot",variant=~"$variant"}',        "format": "table", "instant": True, "legendFormat": "", "refId": "A"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_position_avg_entry_price{bot=~"$bot",variant=~"$variant"}',      "format": "table", "instant": True, "legendFormat": "", "refId": "B"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_position_unrealized_pnl_quote{bot=~"$bot",variant=~"$variant"}', "format": "table", "instant": True, "legendFormat": "", "refId": "C"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_position_opened_at_seconds{bot=~"$bot",variant=~"$variant"}',    "format": "table", "instant": True, "legendFormat": "", "refId": "D"},
                {"datasource": DS_PROM, "expr": 'hbot_bot_mid_price{bot=~"$bot",variant=~"$variant"}',                    "format": "table", "instant": True, "legendFormat": "", "refId": "E"},
            ],
            "transformations": [
                {"id": "merge", "options": {}},
                {
                    "id": "calculateField",
                    "options": {
                        "alias": "Stake",
                        "mode": "binary",
                        "binary": {
                            "left": "Value #A",
                            "right": "Value #B",
                            "operator": "*",
                            "reducer": "sum",
                        },
                    },
                },
                {
                    "id": "calculateField",
                    "options": {
                        "alias": "Profit %",
                        "mode": "binary",
                        "binary": {
                            "left": "Value #C",
                            "right": "Stake",
                            "operator": "/",
                            "reducer": "sum",
                        },
                    },
                },
                {
                    "id": "organize",
                    "options": {
                        "renameByName": {
                            "instrument_id": "ID",
                            "pair": "Pair",
                            "bot": "Bot",
                            "variant": "Variant",
                            "Value #A": "Qty (S/L)",
                            "Value #B": "Open Rate",
                            "Value #C": "Profit",
                            "Value #D": "Opened (epoch)",
                            "Value #E": "Rate",
                            "Stake": "Stake",
                            "Profit %": "Profit %",
                        },
                        "excludeByName": {
                            "Time": True,
                            "mode": True,
                            "accounting": True,
                            "exchange": True,
                            "regime": True,
                            "Opened (epoch)": True,
                        },
                    },
                },
            ],
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Open Rate"}, "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}]},
                    {"matcher": {"id": "byName", "options": "Rate"},      "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}]},
                    {"matcher": {"id": "byName", "options": "Stake"},     "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}]},
                    {"matcher": {"id": "byName", "options": "Profit %"},  "properties": [
                        {"id": "unit", "value": "percent"},
                        {"id": "decimals", "value": 2},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": THRESH_PNL},
                    ]},
                    {"matcher": {"id": "byName", "options": "Profit"},    "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "decimals", "value": 2},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": THRESH_PNL},
                    ]},
                    {"matcher": {"id": "byName", "options": "Qty (S/L)"}, "properties": [
                        {"id": "unit", "value": "short"},
                        {"id": "decimals", "value": 6},
                        {
                            "id": "mappings",
                            "value": [
                                {"type": "range", "options": {"from": 0.000001, "to": 999999, "result": {"text": "L", "color": "green", "index": 0}}},
                                {"type": "range", "options": {"from": -999999, "to": -0.000001, "result": {"text": "S", "color": "red", "index": 1}}},
                            ],
                        },
                    ]},
                ],
            },
        }
    )

    # ── Section D: All Closed Trades (y=21..31) ───────────────────────────────
    panels.append(row_panel(230, "FreqText — All Closed Trades", y=21))
    panels.append(
        {
            "id": 231,
            "type": "table",
            "title": "All Closed Trades",
            "description": (
                "Recent fills with non-zero realized PnL from fills.csv (Loki). "
                "Same 25-row logic as ftui_dashboard.py closed_trades()."
            ),
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 22},
            "datasource": DS_LOKI,
            "options": {
                "showHeader": True,
                "footer": {"show": False},
                "sortBy": [{"displayName": "Open Date", "desc": True}],
            },
            "targets": [
                {
                    "datasource": DS_LOKI,
                    "expr": (
                        '{job="epp_csv", bot=~"$bot", filename=~".*fills\\.csv"}'
                        " | csv"
                        ' | realized_pnl_quote != ""'
                        ' | realized_pnl_quote != "0"'
                        ' | realized_pnl_quote != "0.0"'
                        ' | bot_variant=~"$variant"'
                    ),
                    "queryType": "range",
                    "legendFormat": "",
                    "refId": "A",
                    "maxLines": 25,
                }
            ],
            "transformations": [
                {
                    "id": "organize",
                    "options": {
                        "renameByName": {
                            "ts": "Open Date",
                            "bot_variant": "Bot",
                            "trading_pair": "Pair",
                            "realized_pnl_quote": "Profit",
                            "notional_quote": "Notional",
                            "side": "Enter",
                            "state": "Exit",
                            "order_id": "ID",
                        },
                        "excludeByName": {
                            "labels": True, "Line": True, "id": True,
                            "exchange": True, "price": True, "amount_base": True,
                            "fee_quote": True, "is_maker": True, "mid_ref": True,
                            "expected_spread_pct": True, "adverse_drift_30s": True,
                            "bot_mode": True,
                        },
                    },
                }
            ],
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Profit"},   "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "decimals", "value": 4},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": THRESH_PNL},
                    ]},
                    {"matcher": {"id": "byName", "options": "Notional"}, "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}]},
                    {"matcher": {"id": "byName", "options": "Enter"},    "properties": [
                        {"id": "mappings", "value": [
                            {"type": "value", "options": {
                                "buy":  {"color": "green", "text": "buy",  "index": 0},
                                "sell": {"color": "red",   "text": "sell", "index": 1},
                            }},
                        ]},
                    ]},
                ],
            },
        }
    )

    # ── Section E: Cumulative Profit chart (y=32..42) ─────────────────────────
    panels.append(row_panel(240, "FreqText — Cumulative Profit", y=32))
    panels.append(
        {
            "id": 241,
            "type": "timeseries",
            "title": "Cumulative Profit",
            "description": (
                "equity_quote minus the first equity row in minute.csv "
                "(hbot_bot_equity_start_quote). Matches ftui_dashboard.py equity_series()."
            ),
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 33},
            "datasource": DS_PROM,
            "options": {
                "tooltip": {"mode": "single"},
                "legend": {"displayMode": "hidden"},
            },
            "targets": [
                {
                    "datasource": DS_PROM,
                    "expr": (
                        'hbot_bot_equity_quote{bot=~"$bot",variant=~"$variant"}'
                        " - "
                        'hbot_bot_equity_start_quote{bot=~"$bot",variant=~"$variant"}'
                    ),
                    "legendFormat": "{{bot}} cumulative profit",
                    "refId": "A",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "currencyUSD",
                    "decimals": 2,
                    "color": {"mode": "fixed", "fixedColor": "orange"},
                    "custom": {
                        "lineWidth": 2,
                        "fillOpacity": 30,
                        "gradientMode": "opacity",
                        "drawStyle": "line",
                        "spanNulls": False,
                    },
                }
            },
        }
    )

    return panels


def main():
    dash = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    # Check if FreqText panels already injected (idempotent)
    existing_ids = {p.get("id") for p in dash["panels"]}
    if 200 in existing_ids:
        print("FreqText panels (id 200+) already present — re-injecting (replacing).")
        dash["panels"] = [p for p in dash["panels"] if p.get("id", 0) < 200]
        # Re-unshift y values that were shifted in a previous run
        for p in dash["panels"]:
            gp = p.get("gridPos", {})
            if gp.get("y", 0) >= Y_SHIFT:
                gp["y"] = gp["y"] - Y_SHIFT
            p["gridPos"] = gp

    # Shift all existing panels down
    for p in dash["panels"]:
        gp = p.get("gridPos", {})
        gp["y"] = gp.get("y", 0) + Y_SHIFT
        p["gridPos"] = gp

    new_panels = build_new_panels()
    dash["panels"] = new_panels + dash["panels"]
    dash["version"] = dash.get("version", 1) + 1

    out = json.dumps(dash, indent=2, ensure_ascii=False)
    DASHBOARD_PATH.write_text(out, encoding="utf-8")
    print(
        f"Done. {len(dash['panels'])} panels total "
        f"({len(new_panels)} new FreqText + {len(dash['panels']) - len(new_panels)} existing)."
    )


if __name__ == "__main__":
    main()
