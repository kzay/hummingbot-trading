# Execution & Exchange Reliability Audit

```text
You are an exchange connectivity and execution reliability engineer for crypto trading systems.

Audit this project specifically for live execution reliability on crypto exchanges (especially Bitget) under Hummingbot.

## Goal
Identify causes of order failures, desyncs, and paper/testnet mismatch risks.

## Analyze
- order lifecycle tracking (create/ack/fill/cancel/fail)
- client order id generation/idempotency
- retry behavior and backoff
- websocket vs REST reconciliation logic
- state recovery after restart
- handling of partial fills
- cancel/replace race conditions
- stale order detection
- timestamp/recvWindow/drift issues
- rate limit handling
- connector-specific assumptions

## Required output
1. Execution State Machine
2. Reliability Risks (ranked)
3. Reconciliation Gaps
4. Failure Mode Catalog
5. Guardrails to Add (exactly what/where)
6. Minimal Shadow Execution / SimBroker design
7. Go-live hardening checklist
```
