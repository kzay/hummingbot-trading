from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RedisSettings:
    host: str = os.getenv("REDIS_HOST", "redis")
    port: int = int(os.getenv("REDIS_PORT", "6379"))
    db: int = int(os.getenv("REDIS_DB", "0"))
    password: str = os.getenv("REDIS_PASSWORD", "")
    enabled: bool = _env_bool("EXT_SIGNAL_RISK_ENABLED", False)


@dataclass
class ServiceSettings:
    instance_name: str = os.getenv("HB_INSTANCE_NAME", "bot1")
    producer_name: str = os.getenv("EVENT_PRODUCER_NAME", "service")
    consumer_group: str = os.getenv("REDIS_CONSUMER_GROUP", "hb_group_v1")
    poll_ms: int = int(os.getenv("EVENT_POLL_MS", "1000"))

