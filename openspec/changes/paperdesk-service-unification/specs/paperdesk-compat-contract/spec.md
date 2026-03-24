## ADDED Requirements

### Requirement: Redis paper-exchange contracts SHALL remain stable

The service wrapper SHALL preserve the existing command, event, heartbeat, and audit stream contracts used by runtime and ops consumers.

#### Scenario: Existing event-stream consumer reads paper fills

- **WHEN** a consumer reads `hb.paper_exchange.event.v1`
- **THEN** it SHALL receive `PaperExchangeEvent` payloads with the same schema and expected metadata fields as before the migration

#### Scenario: Promotion gate checks heartbeat freshness

- **WHEN** reliability tooling reads `hb.paper_exchange.heartbeat.v1`
- **THEN** it SHALL receive `PaperExchangeHeartbeatEvent` payloads with the same freshness and metadata contract as before the migration

### Requirement: State snapshot compatibility SHALL preserve open-order readers

The compatibility projection SHALL preserve the current state snapshot structure expected by downstream readers.

#### Scenario: Runtime order hydration reads current state snapshot

- **WHEN** `hb_bridge.py` hydrates runtime orders from `paper_exchange_state_snapshot_latest.json`
- **THEN** the snapshot SHALL include an `orders` mapping with the fields needed to rebuild working orders

#### Scenario: Ops open-order ingestion reads current state snapshot

- **WHEN** ops ingestion reads `paper_exchange_state_snapshot_latest.json`
- **THEN** open orders SHALL still be discoverable from the projected `orders` mapping

### Requirement: Pair snapshot compatibility SHALL remain stable

The compatibility projection SHALL preserve the pair snapshot format used by readers and drift tools.

#### Scenario: Drift and metrics readers inspect pair snapshot

- **WHEN** a consumer reads `paper_exchange_pair_snapshot_latest.json`
- **THEN** the file SHALL preserve the existing path and top-level shape needed by current readers
