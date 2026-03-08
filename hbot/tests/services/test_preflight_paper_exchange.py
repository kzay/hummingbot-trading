from __future__ import annotations

from pathlib import Path

from scripts.ops.preflight_paper_exchange import build_report


def test_preflight_paper_exchange_passes_when_wiring_present(tmp_path: Path) -> None:
    (tmp_path / "services" / "paper_exchange_service").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services" / "paper_exchange_service" / "main.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "release" / "check_paper_exchange_thresholds.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "check_paper_exchange_load.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "run_paper_exchange_load_harness.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "ops" / "run_paper_exchange_canary.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "env").mkdir(parents=True, exist_ok=True)
    (tmp_path / "env" / ".env").write_text(
        "PAPER_EXCHANGE_ALLOWED_CONNECTORS=bitget_perpetual\n",
        encoding="utf-8",
    )
    (tmp_path / "env" / ".env.template").write_text(
        "\n".join(
            [
                "PAPER_EXCHANGE_MODE_BOT1=disabled",
                "PAPER_EXCHANGE_MODE_BOT3=disabled",
                "PAPER_EXCHANGE_MODE_BOT4=disabled",
                "PAPER_EXCHANGE_MODE_BOT5=disabled",
                "PAPER_EXCHANGE_MODE_BOT6=disabled",
                "PAPER_EXCHANGE_SERVICE_ONLY=false",
                "PAPER_EXCHANGE_SYNC_TIMEOUT_MS=30000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "compose").mkdir(parents=True, exist_ok=True)
    (tmp_path / "compose" / "docker-compose.yml").write_text(
        (
            "services:\n"
            "  bot1:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT1:-disabled}\n"
            "  bot3:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT3:-disabled}\n"
            "  bot4:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT4:-disabled}\n"
            "  bot5:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT5:-disabled}\n"
            "  bot6:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT6:-disabled}\n"
            "  paper-exchange-service:\n"
            "    command: python /workspace/hbot/services/paper_exchange_service/main.py\n"
            "    healthcheck:\n"
            "      test: [\"CMD\", \"python\", \"-V\"]\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "ops" / "runbooks.md").write_text(
        "## Paper Exchange Service Rollout\n\n### Paper Exchange Rollback\n",
        encoding="utf-8",
    )

    report = build_report(tmp_path)
    assert report["status"] == "pass"
    assert report["failed_checks"] == []


def test_preflight_paper_exchange_fails_when_connectors_missing(tmp_path: Path) -> None:
    (tmp_path / "services" / "paper_exchange_service").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services" / "paper_exchange_service" / "main.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "release" / "check_paper_exchange_thresholds.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "check_paper_exchange_load.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "run_paper_exchange_load_harness.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "ops" / "run_paper_exchange_canary.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "env").mkdir(parents=True, exist_ok=True)
    (tmp_path / "env" / ".env").write_text(
        "PAPER_EXCHANGE_ALLOWED_CONNECTORS=\n",
        encoding="utf-8",
    )
    (tmp_path / "env" / ".env.template").write_text(
        "\n".join(
            [
                "PAPER_EXCHANGE_MODE_BOT1=disabled",
                "PAPER_EXCHANGE_MODE_BOT3=disabled",
                "PAPER_EXCHANGE_MODE_BOT4=disabled",
                "PAPER_EXCHANGE_MODE_BOT5=disabled",
                "PAPER_EXCHANGE_MODE_BOT6=disabled",
                "PAPER_EXCHANGE_SERVICE_ONLY=false",
                "PAPER_EXCHANGE_SYNC_TIMEOUT_MS=30000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "compose").mkdir(parents=True, exist_ok=True)
    (tmp_path / "compose" / "docker-compose.yml").write_text(
        (
            "services:\n"
            "  bot1:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT1:-disabled}\n"
            "  bot3:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT3:-disabled}\n"
            "  bot4:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT4:-disabled}\n"
            "  bot5:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT5:-disabled}\n"
            "  bot6:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT6:-disabled}\n"
            "  paper-exchange-service:\n"
            "    command: python /workspace/hbot/services/paper_exchange_service/main.py\n"
            "    healthcheck:\n"
            "      test: [\"CMD\", \"python\", \"-V\"]\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "ops" / "runbooks.md").write_text(
        "## Paper Exchange Service Rollout\n\n### Paper Exchange Rollback\n",
        encoding="utf-8",
    )

    report = build_report(tmp_path)
    assert report["status"] == "fail"
    assert "paper_exchange_allowed_connectors_non_empty" in report["failed_checks"]


def test_preflight_paper_exchange_fails_when_legacy_internal_paper_enabled_present(tmp_path: Path) -> None:
    (tmp_path / "services" / "paper_exchange_service").mkdir(parents=True, exist_ok=True)
    (tmp_path / "services" / "paper_exchange_service" / "main.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "release" / "check_paper_exchange_thresholds.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "check_paper_exchange_load.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "release" / "run_paper_exchange_load_harness.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "ops" / "run_paper_exchange_canary.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "env").mkdir(parents=True, exist_ok=True)
    (tmp_path / "env" / ".env").write_text(
        "PAPER_EXCHANGE_ALLOWED_CONNECTORS=bitget_perpetual\n",
        encoding="utf-8",
    )
    (tmp_path / "env" / ".env.template").write_text(
        "\n".join(
            [
                "PAPER_EXCHANGE_MODE_BOT1=disabled",
                "PAPER_EXCHANGE_MODE_BOT3=disabled",
                "PAPER_EXCHANGE_MODE_BOT4=disabled",
                "PAPER_EXCHANGE_MODE_BOT5=disabled",
                "PAPER_EXCHANGE_MODE_BOT6=disabled",
                "PAPER_EXCHANGE_SERVICE_ONLY=false",
                "PAPER_EXCHANGE_SYNC_TIMEOUT_MS=30000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "compose").mkdir(parents=True, exist_ok=True)
    (tmp_path / "compose" / "docker-compose.yml").write_text(
        (
            "services:\n"
            "  bot1:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT1:-disabled}\n"
            "  bot3:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT3:-disabled}\n"
            "  bot4:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT4:-disabled}\n"
            "  bot5:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT5:-disabled}\n"
            "  bot6:\n"
            "    environment:\n"
            "      PAPER_EXCHANGE_MODE: ${PAPER_EXCHANGE_MODE_BOT6:-disabled}\n"
            "  paper-exchange-service:\n"
            "    command: python /workspace/hbot/services/paper_exchange_service/main.py\n"
            "    healthcheck:\n"
            "      test: [\"CMD\", \"python\", \"-V\"]\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "ops" / "runbooks.md").write_text(
        "## Paper Exchange Service Rollout\n\n### Paper Exchange Rollback\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "bot1" / "conf" / "controllers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "bot1" / "conf" / "controllers" / "sample.yml").write_text(
        "id: sample\ninternal_paper_enabled: true\n",
        encoding="utf-8",
    )

    report = build_report(tmp_path)
    assert report["status"] == "fail"
    assert "paper_exchange_legacy_internal_paper_enabled_removed" in report["failed_checks"]

