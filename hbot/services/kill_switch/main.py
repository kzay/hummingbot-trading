"""Kill switch service — exchange-level emergency order cancellation.

Listens for ``kill_switch`` execution intents on Redis and cancels all open
orders on the target exchange via ccxt.  Optionally flattens positions.

Requires manual container restart to resume trading — there is no auto-recovery.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None

from services.common.graceful_shutdown import ShutdownHandler
from services.common.logging_config import configure_logging
from services.common.models import RedisSettings, ServiceSettings
from services.common.utils import read_json, utc_now, write_json
from services.contracts.event_schemas import AuditEvent
from services.contracts.stream_names import (
    AUDIT_STREAM,
    DEFAULT_CONSUMER_GROUP,
    EXECUTION_INTENT_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)


def _cancel_all_orders_ccxt(
    exchange_id: str,
    api_key: str,
    secret: str,
    passphrase: str,
    trading_pair: Optional[str],
    dry_run: bool,
) -> Dict[str, object]:
    """Cancel all open orders on *exchange_id* via ccxt.

    Returns an evidence dict with cancelled order IDs or error details.
    """
    if ccxt is None:
        return {"status": "error", "error": "ccxt_not_installed", "cancelled": []}

    if not api_key or not secret:
        return {"status": "error", "error": "missing_credentials", "cancelled": []}

    try:
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            return {"status": "error", "error": f"unknown_exchange_{exchange_id}", "cancelled": []}

        exchange_cfg: Dict[str, object] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }
        if passphrase:
            exchange_cfg["password"] = passphrase
        exchange = exchange_cls(exchange_cfg)

        if dry_run:
            logger.info("[DRY RUN] Would cancel all orders on %s", exchange_id)
            return {"status": "dry_run", "error": "", "cancelled": []}

        symbol = trading_pair.replace("-", "/") if trading_pair else None
        cancelled: List[str] = []

        open_orders = exchange.fetch_open_orders(symbol=symbol)
        for order in open_orders:
            oid = order.get("id", "")
            try:
                exchange.cancel_order(oid, symbol=order.get("symbol"))
                cancelled.append(str(oid))
                logger.info("Cancelled order %s on %s", oid, exchange_id)
            except Exception as exc:
                logger.error("Failed to cancel order %s: %s", oid, exc)

        return {"status": "executed", "error": "", "cancelled": cancelled}

    except Exception as exc:
        logger.error("Kill switch cancel_all failed on %s: %s", exchange_id, exc, exc_info=True)
        return {"status": "error", "error": str(exc), "cancelled": []}


def _publish_audit(
    client: RedisStreamClient,
    producer: str,
    instance_name: str,
    action: str,
    details: Dict[str, object],
) -> None:
    """Publish an audit event for kill switch activity."""
    event = AuditEvent(
        producer=producer,
        instance_name=instance_name,
        severity="error",
        category="kill_switch",
        message=f"kill_switch_{action}",
        metadata={"details": json.dumps(details)},
    )
    client.xadd(
        AUDIT_STREAM,
        event.model_dump(),
        maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM),
    )


def run() -> None:
    configure_logging()
    redis_cfg = RedisSettings()
    svc_cfg = ServiceSettings()
    shutdown = ShutdownHandler()

    dry_run = os.getenv("KILL_SWITCH_DRY_RUN", "true").strip().lower() in {"1", "true", "yes"}
    exchange_id = os.getenv("KILL_SWITCH_EXCHANGE", "bitget").strip()
    api_key = os.getenv("KILL_SWITCH_API_KEY", "").strip()
    secret = os.getenv("KILL_SWITCH_SECRET", "").strip()
    passphrase = os.getenv("KILL_SWITCH_PASSPHRASE", "").strip()
    report_path = Path(os.getenv("KILL_SWITCH_REPORT_PATH", "/workspace/hbot/reports/kill_switch/latest.json"))

    client = RedisStreamClient(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        enabled=redis_cfg.enabled,
    )

    group = os.getenv("KILL_SWITCH_CONSUMER_GROUP", "hb_kill_switch_v1")
    consumer = f"kill-switch-{svc_cfg.instance_name}"
    client.create_group(EXECUTION_INTENT_STREAM, group)

    logger.info(
        "Kill switch service started: exchange=%s dry_run=%s instance=%s",
        exchange_id, dry_run, svc_cfg.instance_name,
    )

    while not shutdown.requested:
        entries = client.read_group(
            stream=EXECUTION_INTENT_STREAM,
            group=group,
            consumer=consumer,
            count=10,
            block_ms=2000,
        )
        for entry_id, payload in entries:
            action = str(payload.get("action", "")).strip()
            target_instance = str(payload.get("instance_name", "")).strip()

            if action != "kill_switch":
                client.ack(EXECUTION_INTENT_STREAM, group, entry_id)
                continue

            if target_instance and target_instance != svc_cfg.instance_name:
                client.ack(EXECUTION_INTENT_STREAM, group, entry_id)
                continue

            trading_pair = str(payload.get("trading_pair", "")).strip() or None
            logger.warning(
                "KILL SWITCH TRIGGERED for %s on %s (pair=%s, dry_run=%s)",
                target_instance or "all", exchange_id, trading_pair, dry_run,
            )

            result = _cancel_all_orders_ccxt(
                exchange_id=exchange_id,
                api_key=api_key,
                secret=secret,
                passphrase=passphrase,
                trading_pair=trading_pair,
                dry_run=dry_run,
            )

            report = {
                "ts_utc": utc_now(),
                "trigger": "execution_intent",
                "instance_name": target_instance,
                "exchange": exchange_id,
                "trading_pair": trading_pair,
                "dry_run": dry_run,
                "result": result,
                "entry_id": entry_id,
            }
            write_json(report_path, report)

            _publish_audit(
                client=client,
                producer=svc_cfg.producer_name,
                instance_name=target_instance or svc_cfg.instance_name,
                action="triggered",
                details=report,
            )

            client.ack(EXECUTION_INTENT_STREAM, group, entry_id)

            if not dry_run:
                logger.warning("Kill switch executed — service will now stop. Manual restart required.")
                shutdown._requested = True
                break

        if not entries:
            time.sleep(0.5)

    shutdown.log_exit()


if __name__ == "__main__":
    run()
