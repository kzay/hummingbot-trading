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
from decimal import Decimal
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

# ── Config (env) ───────────────────────────────────────────────────────
STOP_BOT_ON_KILL = os.getenv("KILL_SWITCH_STOP_BOT", "true").lower() == "true"
BOT_CONTAINER_NAME = os.getenv("KILL_SWITCH_BOT_CONTAINER", "bot1")
FLATTEN_POSITION_ON_KILL = os.getenv("KILL_SWITCH_FLATTEN_POSITION", "false").lower() == "true"

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
        failed: List[str] = []
        max_retries = 3

        for attempt in range(max_retries):
            try:
                open_orders = exchange.fetch_open_orders(symbol=symbol)
                break
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.error("Kill switch: fetch_open_orders failed after %d attempts: %s", max_retries, exc)
                    return {"status": "error", "error": f"fetch_open_orders: {exc}", "cancelled": cancelled}
                logger.warning("Kill switch: fetch_open_orders attempt %d failed: %s — retrying", attempt + 1, exc)
                time.sleep(2 ** attempt)

        for order in open_orders:
            oid = order.get("id", "")
            cancel_ok = False
            for attempt in range(max_retries):
                try:
                    exchange.cancel_order(oid, symbol=order.get("symbol"))
                    cancelled.append(str(oid))
                    logger.info("Cancelled order %s on %s", oid, exchange_id)
                    cancel_ok = True
                    break
                except Exception as exc:
                    if attempt == max_retries - 1:
                        logger.error("Failed to cancel order %s after %d attempts: %s", oid, max_retries, exc)
                        failed.append(str(oid))
                    else:
                        logger.warning("Cancel order %s attempt %d failed: %s — retrying", oid, attempt + 1, exc)
                        time.sleep(2 ** attempt)

        status = "executed" if not failed else "partial"
        return {"status": status, "error": "", "cancelled": cancelled, "failed": failed}

    except Exception as exc:
        logger.error("Kill switch cancel_all failed on %s: %s", exchange_id, exc, exc_info=True)
        return {"status": "error", "error": str(exc), "cancelled": []}


def _flatten_position_ccxt(
    exchange_id: str,
    api_key: str,
    secret: str,
    passphrase: str,
    trading_pair: Optional[str],
) -> Dict[str, object]:
    """Flatten net position for *trading_pair* using a reduce-only market order."""
    if ccxt is None:
        return {"status": "error", "error": "ccxt_not_installed"}
    if not api_key or not secret:
        return {"status": "error", "error": "missing_credentials"}
    if not trading_pair:
        return {"status": "skipped", "error": "missing_trading_pair"}

    symbol = trading_pair.replace("-", "/")
    try:
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            return {"status": "error", "error": f"unknown_exchange_{exchange_id}"}
        exchange_cfg: Dict[str, object] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }
        if passphrase:
            exchange_cfg["password"] = passphrase
        exchange = exchange_cls(exchange_cfg)

        fetch_positions = getattr(exchange, "fetch_positions", None)
        if not callable(fetch_positions):
            return {"status": "error", "error": "fetch_positions_not_supported"}
        positions = fetch_positions([symbol])

        net_position = Decimal("0")
        for pos in positions or []:
            if not isinstance(pos, dict):
                continue
            pos_symbol = str(pos.get("symbol") or "").strip()
            if pos_symbol and pos_symbol != symbol:
                continue
            amount_raw = None
            for key in ("contracts", "positionAmt", "amount", "size", "qty", "quantity"):
                if key in pos and pos.get(key) is not None:
                    amount_raw = pos.get(key)
                    break
            if amount_raw is None:
                continue
            try:
                amount = Decimal(str(amount_raw))
            except Exception:
                continue
            side = str(pos.get("side", "")).strip().lower()
            if side in {"short", "sell"}:
                amount = -abs(amount)
            elif side in {"long", "buy"}:
                amount = abs(amount)
            net_position += amount

        if abs(net_position) <= Decimal("1e-12"):
            return {"status": "no_position", "error": "", "symbol": symbol, "net_position": "0"}

        close_side = "sell" if net_position > 0 else "buy"
        amount = abs(net_position)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                order = exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=close_side,
                    amount=float(amount),
                    params={"reduceOnly": True},
                )
                return {
                    "status": "executed",
                    "error": "",
                    "symbol": symbol,
                    "side": close_side,
                    "amount": str(amount),
                    "order_id": str((order or {}).get("id", "")),
                }
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.error(
                        "Kill switch: flatten failed after %d attempts (%s %s): %s",
                        max_retries, symbol, close_side, exc,
                    )
                    return {
                        "status": "error",
                        "error": f"flatten_create_order: {exc}",
                        "symbol": symbol,
                        "side": close_side,
                        "amount": str(amount),
                    }
                time.sleep(2 ** attempt)
        return {"status": "error", "error": "flatten_unknown"}
    except Exception as exc:
        logger.error("Kill switch flatten failed on %s: %s", exchange_id, exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


def _combine_kill_result(cancel_result: Dict[str, object], flatten_result: Dict[str, object]) -> Dict[str, object]:
    combined = dict(cancel_result)
    combined["flatten"] = flatten_result
    return combined


def _kill_execution_succeeded(result: Dict[str, object]) -> bool:
    """True only when order cancellation succeeded and optional flatten did not fail."""
    cancel_status = str(result.get("status", "")).strip().lower()
    if cancel_status not in {"executed", "dry_run"}:
        return False
    flatten = result.get("flatten")
    if not isinstance(flatten, dict):
        return True
    flatten_status = str(flatten.get("status", "")).strip().lower()
    return flatten_status in {"executed", "dry_run", "disabled", "no_position", "skipped"}


def _stop_bot_container(container_name: str, timeout: int = 10) -> bool:
    """Stop the bot container via Docker API (Unix socket).

    Returns True on success, False on failure. Does not raise — wraps in try/except
    so the kill switch does not crash if Docker is unavailable.
    """
    import socket as _socket
    _DOCKER_SOCK_PATH = "/var/run/docker.sock"
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(timeout + 5)
        sock.connect(_DOCKER_SOCK_PATH)
        path = f"/containers/{container_name}/stop?t={timeout}"
        request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Length: 0\r\n"
            f"Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode())
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        decoded = raw.decode("utf-8", errors="replace")
        first_line = decoded.split("\r\n")[0]
        try:
            code = int(first_line.split(" ")[1])
        except Exception:
            code = 0
        if code in (204, 200):
            logger.info("Kill switch: stopped bot container %s", container_name)
            return True
        logger.warning("Kill switch: failed to stop container %s (HTTP %s)", container_name, code)
        return False
    except Exception as exc:
        logger.warning("Kill switch: could not stop container %s (Docker unavailable?): %s", container_name, exc)
        return False


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
    flatten_position_on_kill: bool = False
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
        try:
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
            flatten_result: Dict[str, object] = {"status": "disabled", "error": ""}
            if self.flatten_position_on_kill:
                if self.dry_run:
                    flatten_result = {"status": "dry_run", "error": ""}
                else:
                    flatten_result = _flatten_position_ccxt(
                        exchange_id=self.exchange_id,
                        api_key=self.api_key,
                        secret=self.secret,
                        passphrase=self.passphrase,
                        trading_pair=trading_pair,
                    )
            result = _combine_kill_result(result, flatten_result)

            if STOP_BOT_ON_KILL and not self.dry_run:
                _stop_bot_container(BOT_CONTAINER_NAME)

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

            ok = _kill_execution_succeeded(result)
            if not ok:
                logger.error("HTTP kill switch completed with non-success result: %s", result)
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(report, default=str).encode())

            if not self.dry_run and self.shutdown:
                logger.warning("HTTP kill switch executed — service will stop.")
                self.shutdown._requested = True
        except Exception as exc:
            logger.error("HTTP kill switch handler failed: %s", exc, exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "error": str(exc)}).encode())

    def log_message(self, format, *args):
        logger.debug(format, *args)


def _start_http_server(
    port: int,
    exchange_id: str,
    api_key: str,
    secret: str,
    passphrase: str,
    dry_run: bool,
    flatten_position_on_kill: bool,
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
    _KillSwitchHTTPHandler.flatten_position_on_kill = flatten_position_on_kill
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
        flatten_position_on_kill=FLATTEN_POSITION_ON_KILL,
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
            flatten_result: Dict[str, object] = {"status": "disabled", "error": ""}
            if FLATTEN_POSITION_ON_KILL:
                if dry_run:
                    flatten_result = {"status": "dry_run", "error": ""}
                else:
                    flatten_result = _flatten_position_ccxt(
                        exchange_id=exchange_id,
                        api_key=api_key,
                        secret=secret,
                        passphrase=passphrase,
                        trading_pair=trading_pair,
                    )
            result = _combine_kill_result(result, flatten_result)
            if not _kill_execution_succeeded(result):
                logger.error("Kill switch escalation: non-success cancellation result=%s", result)

            if STOP_BOT_ON_KILL and not dry_run:
                _stop_bot_container(BOT_CONTAINER_NAME)

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
