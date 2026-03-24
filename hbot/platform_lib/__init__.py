"""Platform library — shared utilities consumed by both controllers and services.

Sub-packages:
    market_data  — canonical market state, data plane, history providers
    execution    — fee adapters/providers
    logging      — structured logging config, log namespaces
    contracts    — inter-service event schemas, stream names, identity
    core         — general utilities (Decimal helpers, retry, rate limiter, models)
"""
