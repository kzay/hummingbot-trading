from __future__ import annotations

import json

from scripts.release import check_alerting_health as alerting_health


def _read_evidence(tmp_path):
    evidence_path = tmp_path / "reports" / "reconciliation" / "last_webhook_sent.json"
    return json.loads(evidence_path.read_text(encoding="utf-8"))


def test_run_check_fails_closed_when_telegram_configured_and_unhealthy(monkeypatch, tmp_path) -> None:
    def _fake_probe_telegram(token: str, chat_id: str, timeout: float = 8.0):
        return False, "Telegram 403 Forbidden (token revoked?)"

    def _fake_probe_http_get(url: str, timeout: float = 4.0):
        return True, "HTTP 200"

    monkeypatch.setattr(alerting_health, "_probe_telegram", _fake_probe_telegram)
    monkeypatch.setattr(alerting_health, "_probe_http_get", _fake_probe_http_get)

    rc = alerting_health.run_check(
        sink_url="http://127.0.0.1:19093/healthz",
        alertmanager_url="http://127.0.0.1:9093/-/healthy",
        slack_url="",
        telegram_token="1234:token_body_for_tests_abcdefghijk",
        telegram_chat_id="-10012345",
        strict=False,
        root=tmp_path,
    )
    assert rc == 2
    evidence = _read_evidence(tmp_path)
    assert evidence["status"] == "error"
    assert evidence["mode"] == "telegram_configured_unhealthy"
    assert bool(evidence["telegram_configured"]) is True
    assert bool(evidence["telegram_probe_ok"]) is False
    assert bool(evidence["telegram_required_failure"]) is True


def test_run_check_allows_local_dev_degraded_when_not_strict(monkeypatch, tmp_path) -> None:
    def _fake_probe_http_get(url: str, timeout: float = 4.0):
        return False, "connection refused"

    monkeypatch.setattr(alerting_health, "_probe_http_get", _fake_probe_http_get)

    rc = alerting_health.run_check(
        sink_url="http://127.0.0.1:19093/healthz",
        alertmanager_url="http://127.0.0.1:9093/-/healthy",
        slack_url="",
        telegram_token="",
        telegram_chat_id="",
        strict=False,
        root=tmp_path,
    )
    assert rc == 0
    evidence = _read_evidence(tmp_path)
    assert evidence["status"] == "local_dev_degraded"
    assert evidence["mode"] == "local_dev_degraded"
    assert bool(evidence["telegram_configured"]) is False


def test_run_check_requires_real_endpoint_in_strict_mode(monkeypatch, tmp_path) -> None:
    def _fake_probe_http_get(url: str, timeout: float = 4.0):
        return False, "timeout"

    monkeypatch.setattr(alerting_health, "_probe_http_get", _fake_probe_http_get)

    rc = alerting_health.run_check(
        sink_url="http://127.0.0.1:19093/healthz",
        alertmanager_url="http://127.0.0.1:9093/-/healthy",
        slack_url="",
        telegram_token="",
        telegram_chat_id="",
        strict=True,
        root=tmp_path,
    )
    assert rc == 2
    evidence = _read_evidence(tmp_path)
    assert evidence["status"] == "local_dev_degraded"
    assert evidence["mode"] == "local_dev_degraded"
