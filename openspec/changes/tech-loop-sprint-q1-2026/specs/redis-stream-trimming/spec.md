## ADDED Requirements

### Requirement: RedisStreamClient enforces MAXLEN on all xadd calls
The `RedisStreamClient.xadd()` method SHALL accept a `maxlen` parameter and pass it to the underlying Redis `XADD` command with approximate trimming (`~`). When no explicit `maxlen` is provided, the client SHALL use the value from the `STREAM_RETENTION_MAXLEN` environment variable, falling back to `50000`.

#### Scenario: Default maxlen applied on publish
- **WHEN** a service calls `redis_client.xadd(stream_name, data)` without specifying `maxlen`
- **THEN** the underlying Redis command SHALL include `MAXLEN ~ 50000` (or the value of `STREAM_RETENTION_MAXLEN` env var)

#### Scenario: Explicit maxlen overrides default
- **WHEN** a service calls `redis_client.xadd(stream_name, data, maxlen=10000)`
- **THEN** the underlying Redis command SHALL include `MAXLEN ~ 10000`

#### Scenario: Stream length stays bounded under continuous operation
- **WHEN** a stream receives 100,000 messages over 24 hours
- **THEN** the stream length SHALL never exceed `STREAM_RETENTION_MAXLEN` + approximation tolerance (typically < 10% overshoot)

### Requirement: All stream publishers use RedisStreamClient wrapper
All services and bridge modules that publish to Redis streams SHALL use the `RedisStreamClient.xadd()` method rather than calling `redis.xadd()` directly, ensuring uniform trimming.

#### Scenario: No direct redis.xadd calls in production code
- **WHEN** the codebase is searched for direct `self._redis.xadd` or `r.xadd` calls outside of `RedisStreamClient`
- **THEN** zero matches SHALL be found in `hbot/services/`, `hbot/simulation/bridge/`, and `hbot/controllers/`
