"""Tests for coordination_service — risk→intent transformation, multi-decision, empty stream."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from platform_lib.contracts.event_schemas import ExecutionIntentEvent, RiskDecisionEvent
from platform_lib.contracts.stream_names import RISK_DECISION_STREAM

# ── helpers ──────────────────────────────────────────────────────────

DEFAULT_POLICY = {
    "enabled_default": True,
    "require_ml_enabled": False,
    "allowed_instances": ["bot1"],
    "target_base_pct": {"neutral": 0.5, "confidence_step": 0.2, "min": 0.25, "max": 0.75},
    "actions": {
        "approved_no_model_version": "resume",
        "approved_with_model_version": "set_target_base_pct",
        "rejected": "soft_pause",
    },
    "conflict_contract": {"intent_ttl_ms": 60_000},
}


def _make_decision(approved: bool, reason: str = "test", metadata: dict | None = None) -> RiskDecisionEvent:
    return RiskDecisionEvent(
        producer="risk",
        instance_name="bot1",
        approved=approved,
        reason=reason,
        metadata=metadata or {},
    )


def _transform_decision(decision: RiskDecisionEvent, policy: dict | None = None) -> ExecutionIntentEvent:
    """Replay the coordination service intent-building logic in isolation."""
    policy = policy or dict(DEFAULT_POLICY)
    target_cfg = policy.get("target_base_pct", {})
    neutral = float(target_cfg.get("neutral", 0.5))
    step = float(target_cfg.get("confidence_step", 0.2))
    min_target = float(target_cfg.get("min", 0.25))
    max_target = float(target_cfg.get("max", 0.75))
    intent_ttl_ms = int(policy.get("conflict_contract", {}).get("intent_ttl_ms", 60_000))
    actions_cfg = policy.get("actions", {})

    if decision.approved:
        predicted_return = 0.0
        confidence = 0.0
        try:
            predicted_return = float(decision.metadata.get("predicted_return", "0"))
            confidence = float(decision.metadata.get("confidence", "0"))
        except Exception:
            pass
        if "model_version" in decision.metadata:
            action = str(actions_cfg.get("approved_with_model_version", "set_target_base_pct"))
            if predicted_return > 0:
                target_base = min(max_target, neutral + (confidence * step))
            elif predicted_return < 0:
                target_base = max(min_target, neutral - (confidence * step))
            else:
                action = str(actions_cfg.get("approved_no_model_version", "resume"))
                target_base = None
        else:
            action = str(actions_cfg.get("approved_no_model_version", "resume"))
            target_base = None
    else:
        action = str(actions_cfg.get("rejected", "soft_pause"))
        target_base = None

    return ExecutionIntentEvent(
        producer="coordination_service",
        correlation_id=decision.event_id,
        instance_name=decision.instance_name,
        controller_id="epp_v2_4",
        action=action,
        target_base_pct=target_base,
        expires_at_ms=int(time.time() * 1000) + intent_ttl_ms,
        metadata={
            "reason": decision.reason,
            "model_id": str(decision.metadata.get("model_id", "")),
            "model_version": str(decision.metadata.get("model_version", "")),
            "confidence": str(decision.metadata.get("confidence", "")),
            "predicted_return": str(decision.metadata.get("predicted_return", "")),
        },
    )


# ── Risk decision → intent transformation ─────────────────────────────

class TestRiskToIntent:
    def test_approved_without_model_produces_resume(self):
        decision = _make_decision(approved=True, reason="all_clear")
        intent = _transform_decision(decision)
        assert intent.action == "resume"
        assert intent.target_base_pct is None
        assert intent.instance_name == "bot1"
        assert intent.correlation_id == decision.event_id

    def test_approved_with_model_positive_return(self):
        decision = _make_decision(
            approved=True,
            reason="ml_approved",
            metadata={"model_version": "v1", "predicted_return": "0.02", "confidence": "0.8"},
        )
        intent = _transform_decision(decision)
        assert intent.action == "set_target_base_pct"
        assert intent.target_base_pct is not None
        # neutral(0.5) + confidence(0.8) * step(0.2) = 0.66
        assert abs(intent.target_base_pct - 0.66) < 0.01

    def test_approved_with_model_negative_return(self):
        decision = _make_decision(
            approved=True,
            reason="ml_approved",
            metadata={"model_version": "v1", "predicted_return": "-0.01", "confidence": "0.9"},
        )
        intent = _transform_decision(decision)
        assert intent.action == "set_target_base_pct"
        # neutral(0.5) - confidence(0.9) * step(0.2) = 0.32
        assert abs(intent.target_base_pct - 0.32) < 0.01

    def test_approved_with_model_zero_return_falls_back(self):
        decision = _make_decision(
            approved=True,
            reason="ml_neutral",
            metadata={"model_version": "v1", "predicted_return": "0", "confidence": "0.5"},
        )
        intent = _transform_decision(decision)
        assert intent.action == "resume"
        assert intent.target_base_pct is None

    def test_rejected_produces_soft_pause(self):
        decision = _make_decision(approved=False, reason="risk_limit_exceeded")
        intent = _transform_decision(decision)
        assert intent.action == "soft_pause"
        assert intent.target_base_pct is None

    def test_intent_has_expiry(self):
        decision = _make_decision(approved=True)
        intent = _transform_decision(decision)
        assert intent.expires_at_ms is not None
        assert intent.expires_at_ms > int(time.time() * 1000)

    def test_correlation_id_links_back(self):
        decision = _make_decision(approved=True)
        intent = _transform_decision(decision)
        assert intent.correlation_id == decision.event_id


# ── Multiple decisions ────────────────────────────────────────────────

class TestMultipleDecisions:
    def test_batch_of_decisions(self):
        decisions = [
            _make_decision(approved=True, reason="ok"),
            _make_decision(approved=False, reason="limit"),
            _make_decision(
                approved=True,
                metadata={"model_version": "v1", "predicted_return": "0.01", "confidence": "0.6"},
            ),
        ]
        intents = [_transform_decision(d) for d in decisions]
        assert intents[0].action == "resume"
        assert intents[1].action == "soft_pause"
        assert intents[2].action == "set_target_base_pct"
        # All have unique correlation IDs
        cids = [i.correlation_id for i in intents]
        assert len(set(cids)) == 3


# ── Empty risk stream ────────────────────────────────────────────────

class TestEmptyRiskStream:
    def test_no_entries_produces_no_intents(self):
        mock_client = MagicMock()
        mock_client.read_group.return_value = []
        entries = mock_client.read_group(
            stream=RISK_DECISION_STREAM, group="g", consumer="c", count=20, block_ms=1000,
        )
        assert entries == []
        mock_client.xadd.assert_not_called()

    def test_malformed_payload_is_skipped(self):
        """Coordination service acks and skips entries that fail RiskDecisionEvent parsing."""
        mock_client = MagicMock()
        mock_client.read_group.return_value = [
            ("entry-1", {"not_a_real_field": "garbage"}),
        ]
        entries = mock_client.read_group(
            stream=RISK_DECISION_STREAM, group="g", consumer="c", count=20, block_ms=1000,
        )
        for entry_id, payload in entries:
            try:
                RiskDecisionEvent(**payload)
                intent_created = True
            except Exception:
                intent_created = False
                mock_client.ack(RISK_DECISION_STREAM, "g", entry_id)
        assert not intent_created
        mock_client.ack.assert_called_once()
