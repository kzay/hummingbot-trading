import os
import time
from decimal import Decimal
from typing import Dict, List, Optional, Set

from hummingbot.client import hummingbot_application as hb_app_module
from hummingbot.client.hummingbot_application import HummingbotApplication
from hummingbot.client.ui import interface_utils as hb_interface_utils
from hummingbot.core import connector_manager as hb_connector_manager
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.event.events import MarketOrderFailureEvent
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction
from controllers.paper_engine import (
    PaperExecutionAdapter,
    PaperEngineConfig,
    enable_framework_paper_compat_fallbacks,
    install_paper_adapter,
    install_paper_adapter_on_connector,
    install_paper_adapter_on_strategy,
)
from services.common.exchange_profiles import resolve_profile
from services.common.preflight import run_controller_preflight

try:
    from services.contracts.event_schemas import AuditEvent, MarketSnapshotEvent
    from services.contracts.stream_names import DEFAULT_CONSUMER_GROUP
    from services.hb_bridge.intent_consumer import HBIntentConsumer
    from services.hb_bridge.publisher import HBEventPublisher
    from services.hb_bridge.redis_client import RedisStreamClient
except Exception:  # pragma: no cover
    AuditEvent = None
    MarketSnapshotEvent = None
    DEFAULT_CONSUMER_GROUP = "hb_group_v1"
    HBIntentConsumer = None
    HBEventPublisher = None
    RedisStreamClient = None


def _install_trade_monitor_guard():
    """
    Hummingbot's UI trade monitor can poll stale connector aliases (e.g. binance_perpetual)
    while testnet connectors are active. Swallow only that known monitor-only error to avoid
    noisy console spam without affecting strategy execution.
    """
    if getattr(hb_interface_utils, "_hbot_trade_monitor_guard_installed", False):
        return
    original_start_trade_monitor = hb_interface_utils.start_trade_monitor

    async def guarded_start_trade_monitor(*args, **kwargs):
        try:
            return await original_start_trade_monitor(*args, **kwargs)
        except ValueError as exc:
            if "Connector " in str(exc) and " not found" in str(exc):
                return None
            raise

    hb_interface_utils.start_trade_monitor = guarded_start_trade_monitor
    if hasattr(hb_app_module, "start_trade_monitor"):
        hb_app_module.start_trade_monitor = guarded_start_trade_monitor
    hb_interface_utils._hbot_trade_monitor_guard_installed = True


def _install_connector_alias_guard():
    if getattr(hb_connector_manager, "_hbot_connector_alias_guard_installed", False):
        return
    original_update_balances = hb_connector_manager.ConnectorManager.update_connector_balances

    async def guarded_update_connector_balances(self, connector_name):
        try:
            return await original_update_balances(self, connector_name)
        except ValueError as exc:
            if connector_name == "binance_perpetual":
                return await original_update_balances(self, "binance_perpetual_testnet")
            raise exc

    hb_connector_manager.ConnectorManager.update_connector_balances = guarded_update_connector_balances
    hb_connector_manager._hbot_connector_alias_guard_installed = True


_install_trade_monitor_guard()
_install_connector_alias_guard()
enable_framework_paper_compat_fallbacks()


class V2WithControllersConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    candles_config: List[CandlesConfig] = []
    markets: Dict[str, Set[str]] = {}
    max_global_drawdown_quote: Optional[float] = None
    max_controller_drawdown_quote: Optional[float] = None
    external_signal_risk_enabled: bool = os.getenv("EXT_SIGNAL_RISK_ENABLED", "false").lower() in {"1", "true", "yes"}
    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")
    redis_consumer_group: str = os.getenv("REDIS_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP)
    event_poll_ms: int = int(os.getenv("EVENT_POLL_MS", "1000"))
    bus_soft_pause_on_outage: bool = os.getenv("BUS_SOFT_PAUSE_ON_OUTAGE", "true").lower() in {"1", "true", "yes"}


class V2WithControllers(StrategyV2Base):
    """
    This script runs a generic strategy with cash out feature. Will also check if the controllers configs have been
    updated and apply the new settings.
    The cash out of the script can be set by the time_to_cash_out parameter in the config file. If set, the script will
    stop the controllers after the specified time has passed, and wait until the active executors finalize their
    execution.
    The controllers will also have a parameter to manually cash out. In that scenario, the main strategy will stop the
    specific controller and wait until the active executors finalize their execution. The rest of the executors will
    wait until the main strategy stops them.
    """
    performance_report_interval: int = 1

    def __init__(self, connectors: Dict[str, ConnectorBase], config: V2WithControllersConfig):
        super().__init__(connectors, config)
        self.config = config
        self.max_pnl_by_controller = {}
        self.max_global_pnl = Decimal("0")
        self.drawdown_exited_controllers = []
        self.closed_executors_buffer: int = 30
        self._last_performance_report_timestamp = 0
        self._bus_ping_tick_counter: int = 0
        self._bus_client = None
        self._bus_publisher = None
        self._bus_consumer = None
        self._last_bus_ok_ts = 0.0
        self._preflight_checked = False
        self._preflight_failed = False
        self._paper_adapter_installed: Set[str] = set()
        self._paper_adapter_pending_logged: Set[str] = set()
        self._init_external_bus()
        self._install_internal_paper_adapters()

    def on_tick(self):
        self._install_internal_paper_adapters()
        if not self._preflight_checked:
            self._run_preflight_once()
            if self._preflight_failed:
                return
        super().on_tick()
        self._publish_market_state_to_bus()
        self._consume_execution_intents()
        if not self._is_stop_triggered:
            self.check_manual_kill_switch()
            self.control_max_drawdown()
            self.send_performance_report()
            self._handle_bus_outage_soft_pause()
            self._check_hard_stop_kill_switch()

    def control_max_drawdown(self):
        if self.config.max_controller_drawdown_quote:
            self.check_max_controller_drawdown()
        if self.config.max_global_drawdown_quote:
            self.check_max_global_drawdown()

    def check_max_controller_drawdown(self):
        for controller_id, controller in self.controllers.items():
            if controller.status != RunnableStatus.RUNNING:
                continue
            controller_pnl = self.get_performance_report(controller_id).global_pnl_quote
            last_max_pnl = self.max_pnl_by_controller[controller_id]
            if controller_pnl > last_max_pnl:
                self.max_pnl_by_controller[controller_id] = controller_pnl
            else:
                current_drawdown = last_max_pnl - controller_pnl
                if current_drawdown > self.config.max_controller_drawdown_quote:
                    self.logger().info(f"Controller {controller_id} reached max drawdown. Stopping the controller.")
                    controller.stop()
                    executors_order_placed = self.filter_executors(
                        executors=self.get_executors_by_controller(controller_id),
                        filter_func=lambda x: x.is_active and not x.is_trading,
                    )
                    self.executor_orchestrator.execute_actions(
                        actions=[StopExecutorAction(controller_id=controller_id, executor_id=executor.id) for executor in executors_order_placed]
                    )
                    self.drawdown_exited_controllers.append(controller_id)

    def check_max_global_drawdown(self):
        current_global_pnl = sum([self.get_performance_report(controller_id).global_pnl_quote for controller_id in self.controllers.keys()])
        if current_global_pnl > self.max_global_pnl:
            self.max_global_pnl = current_global_pnl
        else:
            current_global_drawdown = self.max_global_pnl - current_global_pnl
            if current_global_drawdown > self.config.max_global_drawdown_quote:
                self.drawdown_exited_controllers.extend(list(self.controllers.keys()))
                self.logger().info("Global drawdown reached. Stopping the strategy.")
                self._is_stop_triggered = True
                HummingbotApplication.main_application().stop()

    def get_controller_report(self, controller_id: str) -> dict:
        """
        Get the full report for a controller including performance and custom info.
        """
        performance_report = self.controller_reports.get(controller_id, {}).get("performance")
        return {
            "performance": performance_report.dict() if performance_report else {},
            "custom_info": self.controllers[controller_id].get_custom_info()
        }

    def send_performance_report(self):
        if self.current_timestamp - self._last_performance_report_timestamp >= self.performance_report_interval and self._pub:
            controller_reports = {controller_id: self.get_controller_report(controller_id) for controller_id in self.controllers.keys()}
            self._pub(controller_reports)
            self._last_performance_report_timestamp = self.current_timestamp

    def check_manual_kill_switch(self):
        for controller_id, controller in self.controllers.items():
            if controller.config.manual_kill_switch and controller.status == RunnableStatus.RUNNING:
                self.logger().info(f"Manual cash out for controller {controller_id}.")
                controller.stop()
                executors_to_stop = self.get_executors_by_controller(controller_id)
                self.executor_orchestrator.execute_actions(
                    [StopExecutorAction(executor_id=executor.id,
                                        controller_id=executor.controller_id) for executor in executors_to_stop])
            if not controller.config.manual_kill_switch and controller.status == RunnableStatus.TERMINATED:
                if controller_id in self.drawdown_exited_controllers:
                    continue
                self.logger().info(f"Restarting controller {controller_id}.")
                controller.start()

    def check_executors_status(self):
        active_executors = self.filter_executors(
            executors=self.get_all_executors(),
            filter_func=lambda executor: executor.status == RunnableStatus.RUNNING
        )
        if not active_executors:
            self.logger().info("All executors have finalized their execution. Stopping the strategy.")
            HummingbotApplication.main_application().stop()
        else:
            non_trading_executors = self.filter_executors(
                executors=active_executors,
                filter_func=lambda executor: not executor.is_trading
            )
            self.executor_orchestrator.execute_actions(
                [StopExecutorAction(executor_id=executor.id,
                                    controller_id=executor.controller_id) for executor in non_trading_executors])

    def create_actions_proposal(self) -> List[CreateExecutorAction]:
        return []

    def stop_actions_proposal(self) -> List[StopExecutorAction]:
        return []

    def apply_initial_setting(self):
        connectors_position_mode = {}
        for controller_id, controller in self.controllers.items():
            self.max_pnl_by_controller[controller_id] = Decimal("0")
            config_dict = controller.config.model_dump()
            if "connector_name" in config_dict:
                if self.is_perpetual(config_dict["connector_name"]):
                    if "position_mode" in config_dict:
                        connectors_position_mode[config_dict["connector_name"]] = config_dict["position_mode"]
                    if "leverage" in config_dict and "trading_pair" in config_dict:
                        self.connectors[config_dict["connector_name"]].set_leverage(
                            leverage=config_dict["leverage"],
                            trading_pair=config_dict["trading_pair"])
        for connector_name, position_mode in connectors_position_mode.items():
            self.connectors[connector_name].set_position_mode(position_mode)

    def _install_internal_paper_adapters(self):
        for controller_id, controller in self.controllers.items():
            if controller_id in self._paper_adapter_installed:
                continue
            cfg = getattr(controller, "config", None)
            if cfg is None:
                continue
            connector_name = str(getattr(cfg, "connector_name", ""))
            trading_pair = str(getattr(cfg, "trading_pair", ""))
            internal_paper_enabled = bool(getattr(cfg, "internal_paper_enabled", False))
            if not connector_name.endswith("_paper_trade") or not internal_paper_enabled or not trading_pair:
                continue
            paper_cfg = PaperEngineConfig(
                enabled=True,
                seed=int(getattr(cfg, "paper_seed", 7)),
                latency_ms=int(getattr(cfg, "paper_latency_ms", 150)),
                queue_participation=Decimal(str(getattr(cfg, "paper_queue_participation", "0.35"))),
                slippage_bps=Decimal(str(getattr(cfg, "paper_slippage_bps", "1.0"))),
                adverse_selection_bps=Decimal(str(getattr(cfg, "paper_adverse_selection_bps", "1.5"))),
                min_partial_fill_ratio=Decimal(str(getattr(cfg, "paper_partial_fill_min_ratio", "0.15"))),
                max_partial_fill_ratio=Decimal(str(getattr(cfg, "paper_partial_fill_max_ratio", "0.85"))),
                max_fills_per_order=int(getattr(cfg, "paper_max_fills_per_order", 8)),
                maker_fee_bps=Decimal(str(getattr(cfg, "spot_fee_pct", "0.0010"))) * Decimal("10000"),
                taker_fee_bps=Decimal(str(getattr(cfg, "spot_fee_pct", "0.0010"))) * Decimal("10000"),
            )
            adapter = install_paper_adapter(
                controller=controller,
                connector_name=connector_name,
                trading_pair=trading_pair,
                cfg=paper_cfg,
            )
            if adapter is None:
                # Fallback install path for HB builds where controller.strategy is not bound
                # during early ticks; we can still install using this strategy's connectors map.
                paper_connector = self.connectors.get(connector_name)
                if paper_connector is not None:
                    canonical_name = connector_name
                    if connector_name.endswith("_paper_trade"):
                        profile = resolve_profile(connector_name)
                        if isinstance(profile, dict):
                            canonical_name = str(profile.get("requires_paper_trade_exchange") or connector_name[:-12])
                        else:
                            canonical_name = connector_name[:-12]
                    market_connector = self.connectors.get(canonical_name) or paper_connector
                    adapter = PaperExecutionAdapter(
                        connector_name=connector_name,
                        trading_pair=trading_pair,
                        paper_connector=paper_connector,
                        market_connector=market_connector,
                        config=paper_cfg,
                        time_fn=lambda: float(self.market_data_provider.time()),
                        on_fill=getattr(controller, "did_fill_order", None),
                    )
                    native_ok = install_paper_adapter_on_connector(paper_connector=paper_connector, adapter=adapter)
                    strategy_ok = False
                    if not native_ok:
                        strategy_ok = install_paper_adapter_on_strategy(
                            strategy=self,
                            connector_name=connector_name,
                            adapter=adapter,
                        )
                    if not native_ok and not strategy_ok:
                        self.connectors[connector_name] = adapter
            if adapter is not None:
                self._paper_adapter_installed.add(controller_id)
                connector_obj = self.connectors.get(connector_name)
                strategy_adapters = getattr(self, "_epp_internal_paper_adapters", {})
                if bool(getattr(connector_obj, "_epp_internal_paper_delegate_installed", False)):
                    mode = "native-delegation"
                elif isinstance(strategy_adapters, dict) and connector_name in strategy_adapters:
                    mode = "strategy-delegation"
                else:
                    mode = "legacy-replacement"
                self.logger().info(f"Internal paper adapter installed for {connector_name}/{trading_pair} mode={mode}.")
            else:
                if controller_id not in self._paper_adapter_pending_logged:
                    available = ",".join(sorted(self.connectors.keys())) if isinstance(self.connectors, dict) else "unknown"
                    self.logger().warning(
                        f"Internal paper adapter pending for {connector_name}/{trading_pair} "
                        f"(available_connectors={available})."
                    )
                    self._paper_adapter_pending_logged.add(controller_id)

    def did_fail_order(self, order_failed_event: MarketOrderFailureEvent):
        """
        Handle order failure events by logging the error and stopping the strategy if necessary.
        """
        if order_failed_event.error_message and "position side" in order_failed_event.error_message.lower():
            connectors_position_mode = {}
            for controller_id, controller in self.controllers.items():
                config_dict = controller.config.model_dump()
                if "connector_name" in config_dict:
                    if self.is_perpetual(config_dict["connector_name"]):
                        if "position_mode" in config_dict:
                            connectors_position_mode[config_dict["connector_name"]] = config_dict["position_mode"]
            for connector_name, position_mode in connectors_position_mode.items():
                self.connectors[connector_name].set_position_mode(position_mode)

    def _init_external_bus(self):
        if not self.config.external_signal_risk_enabled:
            return
        if RedisStreamClient is None or HBEventPublisher is None or HBIntentConsumer is None:
            self.logger().warning("External signal/risk enabled but service bridge modules are unavailable.")
            return
        self._bus_client = RedisStreamClient(
            host=self.config.redis_host,
            port=self.config.redis_port,
            db=self.config.redis_db,
            password=self.config.redis_password,
            enabled=True,
        )
        self._bus_publisher = HBEventPublisher(self._bus_client, producer=f"hb:{self.config.script_file_name}")
        self._bus_consumer = HBIntentConsumer(
            self._bus_client,
            group=self.config.redis_consumer_group,
            consumer_name=f"hb-{self.config.script_file_name}",
        )
        if self._bus_client.ping():
            self._last_bus_ok_ts = time.time()

    def _publish_market_state_to_bus(self):
        if self._bus_publisher is None or MarketSnapshotEvent is None:
            return
        if not self._bus_publisher.available:
            return
        self._last_bus_ok_ts = time.time()
        for controller_id, controller in self.controllers.items():
            custom = controller.get_custom_info() if hasattr(controller, "get_custom_info") else {}
            event = MarketSnapshotEvent(
                producer="hb",
                instance_name=getattr(controller.config, "instance_name", "bot"),
                controller_id=controller_id,
                connector_name=getattr(controller.config, "connector_name", "unknown"),
                trading_pair=getattr(controller.config, "trading_pair", "unknown"),
                mid_price=float(custom.get("reference_price", custom.get("mid", 0)) or 0),
                equity_quote=float(custom.get("equity_quote", 0) or 0),
                base_pct=float(custom.get("base_pct", 0) or 0),
                target_base_pct=float(custom.get("target_base_pct", 0) or 0),
                spread_pct=float(custom.get("spread_pct", 0) or 0),
                net_edge_pct=float(custom.get("net_edge_pct", 0) or 0),
                turnover_x=float(custom.get("turnover_x", 0) or 0),
                state=str(custom.get("state", "unknown")),
                extra={"regime": str(custom.get("regime", "n/a"))},
            )
            self._bus_publisher.publish_market_snapshot(event)

    def _consume_execution_intents(self):
        if self._bus_consumer is None:
            return
        for entry_id, intent in self._bus_consumer.poll(count=20, block_ms=self.config.event_poll_ms):
            controller = self.controllers.get(intent.controller_id)
            if controller is None:
                self._bus_consumer.reject(entry_id, intent.event_id, reason="controller_not_found")
                continue
            if not self._intent_passes_local_authority(controller, intent.model_dump()):
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="warning",
                    category="intent_rejected",
                    message="Intent rejected by local Hummingbot authority checks.",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": intent.controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                    },
                )
                self._bus_consumer.reject(entry_id, intent.event_id, reason="local_authority_reject")
                continue
            applied = False
            reason = "not_supported"
            apply_method = getattr(controller, "apply_execution_intent", None)
            if callable(apply_method):
                applied, reason = apply_method(intent.model_dump())
            if applied:
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="info",
                    category="intent_applied",
                    message="Execution intent applied.",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": intent.controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                        "reason": str(intent_meta.get("reason", "")),
                    },
                )
                self._bus_consumer.ack(entry_id, intent.event_id)
            else:
                intent_meta = intent.metadata if isinstance(intent.metadata, dict) else {}
                self._publish_audit(
                    instance_name=getattr(controller.config, "instance_name", "bot"),
                    severity="warning",
                    category="intent_rejected",
                    message=f"Intent rejected by controller: {reason}",
                    metadata={
                        "event_id": intent.event_id,
                        "controller_id": intent.controller_id,
                        "action": intent.action,
                        "model_version": str(intent_meta.get("model_version", "")),
                    },
                )
                self._bus_consumer.reject(entry_id, intent.event_id, reason=reason)

    def _intent_passes_local_authority(self, controller, intent: Dict[str, object]) -> bool:
        connector_ready_fn = getattr(controller, "_connector_ready", None)
        if callable(connector_ready_fn):
            try:
                if not bool(connector_ready_fn()):
                    return False
            except Exception:
                return False
        action = str(intent.get("action", ""))
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            try:
                if value is None:
                    return False
                target = float(value)
            except Exception:
                return False
            if target < 0.0 or target > 1.0:
                return False
        return True

    def _publish_audit(self, instance_name: str, severity: str, category: str, message: str, metadata: Dict[str, str]):
        if self._bus_publisher is None or AuditEvent is None:
            return
        event = AuditEvent(
            producer="hb",
            instance_name=instance_name,
            severity=severity,
            category=category,
            message=message,
            metadata=metadata,
        )
        self._bus_publisher.publish_audit(event)

    def _check_hard_stop_kill_switch(self):
        """If any controller entered HARD_STOP with a risk reason, publish kill_switch intent."""
        if self._bus_publisher is None:
            return
        for controller_id, controller in self.controllers.items():
            custom = controller.get_custom_info() if hasattr(controller, "get_custom_info") else {}
            state = str(custom.get("state", ""))
            risk_reasons = str(custom.get("risk_reasons", ""))
            if state != "hard_stop":
                continue
            risk_triggers = {"daily_loss_hard_limit", "drawdown_hard_limit", "daily_turnover_hard_limit",
                             "margin_ratio_critical", "cancel_budget_repeated_breach"}
            active_reasons = set(risk_reasons.split("|")) if risk_reasons else set()
            if active_reasons & risk_triggers:
                try:
                    from services.contracts.event_schemas import ExecutionIntentEvent
                    from services.contracts.stream_names import EXECUTION_INTENT_STREAM, STREAM_RETENTION_MAXLEN
                    intent = ExecutionIntentEvent(
                        producer=f"hb:{self.config.script_file_name}",
                        instance_name=str(getattr(controller.config, "instance_name", "bot1")),
                        controller_id=controller_id,
                        action="kill_switch",
                        metadata={"reason": risk_reasons},
                    )
                    self._bus_client.xadd(
                        EXECUTION_INTENT_STREAM,
                        intent.model_dump(),
                        maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
                    )
                    self.logger().error(f"HARD_STOP kill_switch published for {controller_id}: {risk_reasons}")
                except Exception:
                    pass

    def _handle_bus_outage_soft_pause(self):
        if not self.config.external_signal_risk_enabled or not self.config.bus_soft_pause_on_outage:
            return
        if self._bus_client is None:
            return
        self._bus_ping_tick_counter += 1
        if self._bus_ping_tick_counter % 30 != 0:
            return
        if self._bus_client.ping():
            self._last_bus_ok_ts = time.time()
            for controller in self.controllers.values():
                set_pause = getattr(controller, "set_external_soft_pause", None)
                if callable(set_pause):
                    set_pause(False, "bus_healthy")
            return
        outage_s = time.time() - self._last_bus_ok_ts if self._last_bus_ok_ts > 0 else 0
        if outage_s < 10:
            return
        for controller in self.controllers.values():
            set_pause = getattr(controller, "set_external_soft_pause", None)
            if callable(set_pause):
                set_pause(True, "bus_outage")

    def _run_preflight_once(self):
        self._preflight_checked = True
        errors: List[str] = []
        for controller_id, controller in self.controllers.items():
            controller_errors = run_controller_preflight(controller.config)
            for err in controller_errors:
                errors.append(f"{controller_id}: {err}")
        if not errors:
            self.logger().info("Preflight validation passed.")
        else:
            for err in errors:
                self.logger().error(f"Preflight failed: {err}")
            self._preflight_failed = True
            self._is_stop_triggered = True
            HummingbotApplication.main_application().stop()
            return
        self._scan_orphan_orders()

    def _scan_orphan_orders(self):
        """Cancel any open orders on the exchange that are not tracked by executors."""
        for controller_id, controller in self.controllers.items():
            connector_name = str(getattr(controller.config, "connector_name", ""))
            trading_pair = str(getattr(controller.config, "trading_pair", ""))
            if not connector_name or not trading_pair:
                continue
            connector = self.connectors.get(connector_name)
            if connector is None:
                continue
            try:
                open_orders_fn = getattr(connector, "get_open_orders", None)
                if not callable(open_orders_fn):
                    continue
                open_orders = open_orders_fn()
                if not open_orders:
                    continue
                tracked_ids = set()
                executors = getattr(controller, "executors_info", [])
                for ex in executors:
                    order_id = getattr(ex, "order_id", None) or str(getattr(ex, "id", ""))
                    if order_id:
                        tracked_ids.add(str(order_id))
                orphans_canceled = 0
                for order in open_orders:
                    order_id = str(getattr(order, "client_order_id", getattr(order, "order_id", "")))
                    order_pair = str(getattr(order, "trading_pair", ""))
                    if order_pair != trading_pair:
                        continue
                    if order_id not in tracked_ids:
                        try:
                            connector.cancel(trading_pair, order_id)
                            orphans_canceled += 1
                            self.logger().warning(f"Orphan order canceled: {order_id} on {connector_name}/{trading_pair}")
                        except Exception:
                            self.logger().error(f"Failed to cancel orphan order: {order_id}", exc_info=True)
                if orphans_canceled > 0:
                    self.logger().warning(f"Startup scan: canceled {orphans_canceled} orphan order(s) for {controller_id}")
                    if self._bus_publisher is not None and AuditEvent is not None:
                        try:
                            self._publish_audit_event(
                                "warning", "orphan_order_scan",
                                f"canceled_{orphans_canceled}_orphan_orders",
                                {"controller_id": controller_id, "connector": connector_name, "pair": trading_pair, "count": str(orphans_canceled)},
                            )
                        except Exception:
                            pass
            except Exception:
                self.logger().warning(f"Orphan order scan failed for {controller_id}", exc_info=True)
