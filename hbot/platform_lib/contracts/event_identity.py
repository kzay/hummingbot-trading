from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Identity fields required to route bot-scoped events safely.
_REQUIRED_FIELDS_BY_EVENT_TYPE = {
    "bot_fill": ("instance_name", "connector_name", "trading_pair", "order_id"),
    "bot_minute_snapshot": ("instance_name", "controller_id", "connector_name", "trading_pair"),
    "paper_exchange_event": ("instance_name", "connector_name", "trading_pair"),
    "paper_exchange_command": ("instance_name", "connector_name", "trading_pair"),
    "execution_intent": ("instance_name", "controller_id"),
    "strategy_signal": ("instance_name",),
    "audit": ("instance_name",),
}


def required_identity_fields(event_type: str) -> tuple[str, ...]:
    return _REQUIRED_FIELDS_BY_EVENT_TYPE.get(str(event_type or "").strip().lower(), ())


def _field_text(payload: Mapping[str, Any], key: str, *, allow_nested_payload: bool) -> str:
    value = payload.get(key)
    if value not in (None, ""):
        return str(value).strip()
    if allow_nested_payload:
        nested = payload.get("payload")
        if isinstance(nested, Mapping):
            nested_value = nested.get(key)
            if nested_value not in (None, ""):
                return str(nested_value).strip()
    return ""


def validate_event_identity(
    payload: Mapping[str, Any],
    *,
    event_type: str | None = None,
    allow_nested_payload: bool = False,
) -> tuple[bool, str]:
    """Validate identity fields for event payloads.

    Returns `(True, "")` when identity is valid or not required for the
    event type. Returns `(False, "<reason>")` when required identity is
    missing, where reason is `<event_type>_missing_<field>`.
    """
    resolved_event_type = str(event_type or payload.get("event_type", "")).strip().lower()
    if not resolved_event_type:
        # Not all stream payloads are schema-typed events.
        return True, ""

    required_fields = required_identity_fields(resolved_event_type)
    for field in required_fields:
        if not _field_text(payload, field, allow_nested_payload=allow_nested_payload):
            return False, f"{resolved_event_type}_missing_{field}"
    return True, ""
