## ADDED Requirements

### Requirement: Service mode SHALL use the same simulation engine as embedded mode

Paper bots running through the paper-exchange service SHALL execute against `PaperDesk`, not a separate accounting or matching implementation.

#### Scenario: Paper bot command executes through PaperDesk

- **WHEN** a paper bot publishes a `submit_order` command in service mode
- **THEN** the service SHALL route that command into a `PaperDesk` instance
- **AND** fill, funding, and risk behavior SHALL come from the `PaperDesk` engine path

### Requirement: Service mode SHALL preserve per-instance isolation

The service SHALL isolate balances, positions, risk state, and open orders by `instance_name`.

#### Scenario: Two bots trade the same pair

- **WHEN** `bot3` and `bot7` both trade `BTC-USDT` through the paper service
- **THEN** their balances, positions, and open orders SHALL remain isolated
- **AND** one bot's fills SHALL NOT change the other bot's portfolio or risk state

### Requirement: Backtesting and replay SHALL remain embedded

Backtesting and replay SHALL continue to use direct in-process `PaperDesk` calls without a Redis dependency.

#### Scenario: Backtest harness runs without service mode

- **WHEN** the replay or backtest harness runs a strategy on historical data
- **THEN** it SHALL instantiate and drive `PaperDesk` directly
- **AND** it SHALL NOT require the paper-exchange service to be running
