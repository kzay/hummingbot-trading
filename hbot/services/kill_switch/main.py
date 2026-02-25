"""Kill switch service — exchange-level emergency order cancellation.

Listens for ``kill_switch`` execution intents on Redis and cancels all open
orders on the target exchange via ccxt.  Optionally flattens positions.

Also exposes an HTTP endpoint (default port 9900) for out-of-process
triggering — survives bot process death since this runs in its own container.

Requires manual container restart to resume trading — there is no auto-recovery.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
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

_kill_switch_state: Dict[str, object] = {"triggered": False, "last_result": None}


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


class _KillSwitchHTTPHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for out-of-process kill switch triggering."""

    exchange_id: str = ""
    api_key: str = ""
    secret: str = ""
    passphrase: str = ""
    dry_run: bool = True
    shutdown: Optional[ShutdownHandler] = None
    redis_client: Optional[RedisStreamClient] = None
    svc_cfg: Optional[ServiceSettings] = None
    report_path: Optional[Path] = None

    def do_POST(self):
        if self.path == "/kill":
            self._handle_kill()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps({"status": "ok", "triggered": _kill_switch_state["triggered"]})
            self.wfile.write(body.encode())
        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps(_kill_switch_state, default=str)
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_kill(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}
        trading_pair = body.get("trading_pair")

        logger.warning("HTTP KILL SWITCH triggered (pair=%s, dry_run=%s)", trading_pair, self.dry_run)

        result = _cancel_all_orders_ccxt(
            exchange_id=self.exchange_id,
            api_key=self.api_key,
            secret=self.secret,
            passphrase=self.passphrase,
            trading_pair=trading_pair,
            dry_run=self.dry_run,
        )

        _kill_switch_state["triggered"] = True
        _kill_switch_state["last_result"] = result

        report = {
            "ts_utc": utc_now(),
            "trigger": "http",
            "exchange": self.exchange_id,
            "trading_pair": trading_pair,
            "dry_run": self.dry_run,
            "result": result,
        }
        if self.report_path:
            write_json(self.report_path, report)

        if self.redis_client and self.svc_cfg:
            _publish_audit(
                client=self.redis_client,
                producer=self.svc_cfg.producer_name,
                instance_name=self.svc_cfg.instance_name,
                action="http_triggered",
                details=report,
            )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(report, default=str).encode())

        if not self.dry_run and self.shutdown:
            logger.warning("HTTP kill switch executed — service will stop.")
            self.shutdown._requested = True

    def log_message(self, format, *args):
        logger.debug(format, *args)


def _start_http_server(
    port: int,
    exchange_id: str,
    api_key: str,
    secret: str,
    passphrase: str,
    dry_run: bool,
    shutdown: ShutdownHandler,
    redis_client: RedisStreamClient,
    svc_cfg: ServiceSettings,
    report_path: Path,
) -> None:
    """Start the HTTP kill switch endpoint in a daemon thread."""
    _KillSwitchHTTPHandler.exchange_id = exchange_id
    _KillSwitchHTTPHandler.api_key = api_key
    _KillSwitchHTTPHandler.secret = secret
    _KillSwitchHTTPHandler.passphrase = passphrase
    _KillSwitchHTTPHandler.dry_run = dry_run
    _KillSwitchHTTPHandler.shutdown = shutdown
    _KillSwitchHTTPHandler.redis_client = redis_client
    _KillSwitchHTTPHandler.svc_cfg = svc_cfg
    _KillSwitchHTTPHandler.report_path = report_path

    server = HTTPServer(("0.0.0.0", port), _KillSwitchHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Kill switch HTTP server listening on port %d", port)


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

    http_port = int(os.getenv("KILL_SWITCH_HTTP_PORT", "9900"))
    _start_http_server(
        port=http_port,
        exchange_id=exchange_id,
        api_key=api_key,
        secret=secret,
        passphrase=passphrase,
        dry_run=dry_run,
        shutdown=shutdown,
        redis_client=client,
        svc_cfg=svc_cfg,
        report_path=report_path,
    )

    logger.info(
        "Kill switch service started: exchange=%s dry_run=%s instance=%s http_port=%d",
        exchange_id, dry_run, svc_cfg.instance_name, http_port,
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
