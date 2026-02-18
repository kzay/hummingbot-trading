---
name: python-node-api-async-git
description: Guides implementation of core engineering foundations for trading systems using Python and Node.js, including API design, async concurrency, and Git workflows. Use when the user asks about Python architecture, Node services, REST/WebSocket clients, async processing, retries/timeouts, exchange API integration, or repository workflow standards.
---

# Python Node API Async Git

## Focus

Build robust engineering foundations before alpha seeking.

## When Not to Use

Do not use for strategy hypothesis design or performance validation questions unless engineering concerns are the main bottleneck.

## Defaults

- Prefer typed interfaces and explicit contracts.
- Favor idempotent API interactions and retries with backoff.
- Use async patterns that preserve ordering guarantees where required.
- Keep Git history clean with atomic commits by concern.

## Workflow

1. Define service boundaries and API contracts.
2. Choose async model:
   - Python: `asyncio` tasks, bounded queues, cancellation handling.
   - Node: Promise-based pipelines, backpressure-aware streams.
3. Implement resilience:
   - timeouts, retries, circuit breakers, and rate-limit handling.
4. Add observability:
   - structured logs, metrics, and correlation IDs.
5. Enforce Git hygiene:
   - branch naming, commit conventions, and PR test checklist.

## Output Template

```markdown
## Engineering Blueprint

- Language/runtime:
- API integrations:
- Concurrency model:
- Failure handling:
- Logging/metrics:
- Git/CI workflow:
```

## Red Flags

- Fire-and-forget async tasks without lifecycle management.
- Shared mutable state across coroutines without protection.
- API clients lacking timeout and retry policies.
- Large mixed-purpose commits.
