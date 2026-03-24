from __future__ import annotations

import os
from dataclasses import dataclass, field

from services.common.utils import env_bool


@dataclass
class RedisSettings:
    host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "redis"))
    port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    db: int = field(default_factory=lambda: int(os.getenv("REDIS_DB", "0")))
    password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", ""))
    enabled: bool = field(default_factory=lambda: env_bool("EXT_SIGNAL_RISK_ENABLED", False))


@dataclass
class ServiceSettings:
    instance_name: str = field(default_factory=lambda: os.getenv("HB_INSTANCE_NAME", "bot1"))
    producer_name: str = field(default_factory=lambda: os.getenv("EVENT_PRODUCER_NAME", "service"))
    consumer_group: str = field(default_factory=lambda: os.getenv("REDIS_CONSUMER_GROUP", "hb_group_v1"))
    poll_ms: int = field(default_factory=lambda: int(os.getenv("EVENT_POLL_MS", "1000")))
