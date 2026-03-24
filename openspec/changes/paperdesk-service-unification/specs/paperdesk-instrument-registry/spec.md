## ADDED Requirements

### Requirement: Service mode SHALL register instruments before accepting orders

The service wrapper SHALL resolve and register an `InstrumentSpec` before an order is accepted for a tenant/pair.

#### Scenario: First command for a new tenant/pair

- **WHEN** the service receives the first `submit_order` command for a previously unseen `instance_name` and trading pair
- **THEN** it SHALL resolve an `InstrumentSpec`
- **AND** it SHALL register the instrument with that tenant's `PaperDesk` before evaluating the order

### Requirement: Instrument resolution SHALL use deterministic inputs

Instrument registration SHALL come from explicit metadata and configured defaults, not hidden implicit state.

#### Scenario: Trading-rule metadata is present

- **WHEN** a command includes trading-rule metadata needed to derive quantity, price, and notional limits
- **THEN** the service SHALL use that metadata as the primary source when constructing the `InstrumentSpec`

#### Scenario: Trading-rule metadata is incomplete

- **WHEN** required instrument inputs are missing
- **THEN** the service SHALL either resolve them from configured deterministic defaults or reject the command with a clear reason
- **AND** it SHALL NOT silently create a guessed instrument with ambiguous rules

### Requirement: Paper/live routing SHALL remain transparent to strategies

Strategies SHALL not need a different connector name to access the paper service.

#### Scenario: Strategy runs in paper mode

- **WHEN** a strategy is configured with `connector_name: bitget_perpetual` and `BOT_MODE=paper`
- **THEN** order routing SHALL go to the service-backed paper path
- **AND** the strategy SHALL NOT require a renamed connector such as `paper_bitget`
