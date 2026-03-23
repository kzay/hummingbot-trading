## ADDED Requirements

### Requirement: data/ directory has a README explaining its layout
A `data/README.md` file SHALL exist that documents which subdirectories and files are checked into git and which are generated at runtime.

#### Scenario: README lists tracked content
- **WHEN** a contributor reads `data/README.md`
- **THEN** they see that `bot{1..7}/conf/`, `backtest_configs/`, and `historical/catalog.json` are checked into git

#### Scenario: README lists generated content
- **WHEN** a contributor reads `data/README.md`
- **THEN** they see that `bot{1..7}/logs/`, `bot{1..7}/data/`, `historical/bitget/`, `shared/`, `ml/`, and `backtest_jobs.sqlite3` are runtime-generated and gitignored
