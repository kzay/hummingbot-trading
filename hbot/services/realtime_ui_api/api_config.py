"""Realtime UI API configuration dataclass and validation.

Split from ``_helpers.py`` to keep each module focused.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _state_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("instance_name", "")).strip(),
        str(payload.get("controller_id", "")).strip(),
        str(payload.get("trading_pair", "")).strip(),
    )


@dataclass
class RealtimeApiConfig:
    mode: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_MODE", "disabled").strip().lower())
    bind_host: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_BIND_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_PORT", "9910")))
    cors_allow_origin: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_CORS_ALLOW_ORIGIN", "*"))
    allowed_origins: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_ALLOWED_ORIGINS", "").strip())
    auth_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )
    auth_token: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_AUTH_TOKEN", "").strip())
    allow_query_token: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_ALLOW_QUERY_TOKEN", "false").strip().lower() in {"1", "true", "yes"}
    )
    poll_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_POLL_MS", "200")))
    consumer_group: str = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CONSUMER_GROUP", "hb_realtime_ui_api_v1").strip()
    )
    consumer_name: str = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CONSUMER_NAME", "realtime-ui-api-1").strip()
    )
    stream_stale_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_STREAM_STALE_MS", "15000")))
    fallback_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_FALLBACK_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    )
    degraded_mode_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_DEGRADED_MODE_ENABLED", "false").strip().lower()
        in {"1", "true", "yes"}
    )
    fallback_root: Path = field(
        default_factory=lambda: Path(os.getenv("HB_REPORTS_ROOT", "/workspace/hbot/reports")).resolve()
    )
    data_root: Path = field(default_factory=lambda: Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data")).resolve())
    max_fills_per_key: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FILLS_PER_KEY", "200")))
    max_events_per_key: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_EVENTS_PER_KEY", "200")))
    max_history_points: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_HISTORY_POINTS", "5000")))
    max_fallback_fills: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FALLBACK_FILLS", "120")))
    max_fallback_orders: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FALLBACK_ORDERS", "40")))
    db_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_DB_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    )
    csv_failover_only: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CSV_FAILOVER_ONLY", "true").strip().lower()
        in {"1", "true", "yes"}
    )
    use_csv_for_operator_api: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_USE_CSV", "false").strip().lower()
        in {"1", "true", "yes"}
    )
    db_lookback_hours: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_LOOKBACK_HOURS", "168")))
    db_max_points_multiplier: int = field(
        default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_MAX_POINTS_MULTIPLIER", "20"))
    )
    db_statement_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_STATEMENT_TIMEOUT_MS", "1500"))
    )
    db_lock_timeout_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_LOCK_TIMEOUT_MS", "750")))
    sse_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_SSE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )
    history_ui_read_mode: str = field(
        default_factory=lambda: os.getenv("HB_HISTORY_UI_READ_MODE", "legacy").strip().lower()
    )

    def normalized_mode(self) -> str:
        if self.mode not in {"disabled", "shadow", "active"}:
            return "disabled"
        return self.mode

    def normalized_history_ui_read_mode(self) -> str:
        if self.history_ui_read_mode not in {"legacy", "shadow", "shared"}:
            return "legacy"
        return self.history_ui_read_mode


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _validate_runtime_config(cfg: RealtimeApiConfig) -> None:
    if cfg.auth_enabled and not cfg.auth_token:
        raise RuntimeError("REALTIME_UI_API_AUTH_ENABLED requires REALTIME_UI_API_AUTH_TOKEN")
    bind_ip = str(os.getenv("REALTIME_UI_API_BIND_IP", "")).strip()
    externally_exposed = bool(bind_ip and not _is_loopback_host(bind_ip))
    internal_non_loopback = not _is_loopback_host(cfg.bind_host) and str(cfg.bind_host).strip() not in {"0.0.0.0", "::"}
    if cfg.normalized_mode() != "disabled" and (externally_exposed or internal_non_loopback) and not cfg.auth_enabled:
        raise RuntimeError("non-loopback realtime_ui_api bind requires REALTIME_UI_API_AUTH_ENABLED=true")
