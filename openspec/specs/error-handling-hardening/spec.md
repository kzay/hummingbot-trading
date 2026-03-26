## ADDED Requirements

### Requirement: Zero silent exception swallowing in hot paths
Every `except Exception: pass` block in `controllers/` and `services/` hot paths (paper engine, bridge, desk, data feeds, runtime kernel, fill handling) SHALL be replaced with one of:
- Typed exception catch (`except ValueError`, `except ConnectionError`, etc.)
- Logging at `WARNING` or `ERROR` level with context
- A Prometheus counter increment for observability
- A degraded-mode flag that downstream code can check

#### Scenario: Paper engine event fire — no silent swallow
- **WHEN** `hb_event_fire.py` catches an exception during fill event processing
- **THEN** it SHALL log the exception with fill context (order_id, price, quantity) at `WARNING` level AND increment a `paper_engine_event_fire_errors_total` counter

#### Scenario: Data feeds — no silent swallow
- **WHEN** `data_feeds.py` catches an exception during candle/tick processing
- **THEN** it SHALL log at `WARNING` with feed identifier AND set a `_feed_degraded` flag that consumers can check

#### Scenario: Bridge Redis operations — typed catch
- **WHEN** `hb_bridge.py` catches a Redis connection error
- **THEN** it SHALL catch `redis.ConnectionError` or `redis.TimeoutError` specifically, not bare `Exception`

### Requirement: Exception hierarchy for trading operations
A `simulation/exceptions.py` module SHALL define a hierarchy of typed exceptions:
- `SimulationError` (base)
- `MatchingEngineError` — order matching failures
- `PortfolioError` — position/balance inconsistencies
- `BridgeError` — HB bridge communication failures
- `FeedError` — data feed staleness or corruption

#### Scenario: Typed exceptions used in matching engine
- **WHEN** `matching_engine.py` detects an invalid order state
- **THEN** it SHALL raise `MatchingEngineError` with order context, not a bare `Exception` or `ValueError`

### Requirement: Non-critical paths may use broad catch with logging
Non-hot paths (telemetry serialization, UI formatting, report generation) MAY use `except Exception` if they:
1. Log the exception at `DEBUG` or higher
2. Return a safe default
3. Do NOT silently drop the error

#### Scenario: Telemetry serialization fallback
- **WHEN** telemetry minute-row serialization fails
- **THEN** it SHALL log at `DEBUG`, return an empty dict, and NOT crash the tick loop

### Requirement: `except Exception: pass` count reaches zero in hot paths
After hardening, `grep -rn "except Exception" hbot/controllers/paper_engine_v2/ hbot/controllers/shared_runtime_v24.py hbot/controllers/runtime/` piped through `grep "pass$"` SHALL return zero matches.

#### Scenario: Audit script validates
- **WHEN** the hardening is complete
- **THEN** a grep for `except Exception` followed by `pass` in hot-path files SHALL return zero matches
