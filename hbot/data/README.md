# data/ Directory Layout

This directory contains bot configuration, historical market data, and
runtime-generated artifacts. Some contents are tracked by git; others are
generated at runtime and excluded via `.gitignore`.

## Tracked (committed to git)

| Path | Description |
|---|---|
| `bot{1..7}/conf/` | Per-bot YAML configuration (controllers, strategy) |
| `backtest_configs/` | YAML configs for backtest, sweep, and walk-forward runs |
| `historical/catalog.json` | Data catalog index — lists available datasets |

## Generated at runtime (gitignored)

| Path | Description |
|---|---|
| `bot{1..7}/logs/` | CSV minute logs, fill logs, state snapshots, event journals |
| `bot{1..7}/data/` | SQLite databases, runtime state |
| `bot{1..7}/scripts/` | Built-in Hummingbot scripts copied from image |
| `historical/bitget/` | Downloaded OHLCV parquet files (via `download_data` script) |
| `shared/` | Cross-bot shared runtime data |
| `ml/` | ML model artifacts and feature data |
| `backtest_jobs.sqlite3` | Backtest job queue database |
| `ops_writer.db` | Ops database writer state |
