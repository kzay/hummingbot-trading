"""V3 TradingDesk integration into the existing strategy launcher.

This module provides the glue between the legacy v2_with_controllers
tick loop and the v3 TradingDesk.  It reads configuration from env vars
and wraps/creates the appropriate components.

Usage in v2_with_controllers.py::

    from controllers.runtime.v3.desk_integration import V3DeskIntegration

    # In __init__:
    self._v3_desk = V3DeskIntegration.from_env(self)

    # In _on_tick_inner, after super().on_tick():
    self._v3_desk.tick()

Env vars:
    V3_DESK_ENABLED=true|false     — master switch (default: false)
    V3_DESK_MODE=shadow|active     — shadow=observe only, active=drive orders
    V3_STRATEGY=bot7_pullback      — strategy name from STRATEGY_REGISTRY
    V3_DESK_BOT_ID=bot7            — bot ID for migration shim (shadow mode)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class V3DeskIntegration:
    """Manages the v3 TradingDesk lifecycle within the legacy launcher."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str = "shadow",
        strategy_name: str = "",
        bot_id: str = "",
        legacy_strategy: Any = None,
    ) -> None:
        self._enabled = enabled
        self._mode = mode
        self._strategy_name = strategy_name
        self._bot_id = bot_id
        self._legacy = legacy_strategy
        self._desk: Any = None
        self._initialized = False
        self._init_error: str = ""
        self._tick_count: int = 0

    @classmethod
    def from_env(cls, legacy_strategy: Any) -> V3DeskIntegration:
        """Create from environment variables."""
        enabled = os.getenv("V3_DESK_ENABLED", "false").lower() in ("true", "1", "yes")
        mode = os.getenv("V3_DESK_MODE", "shadow").lower()
        strategy_name = os.getenv("V3_STRATEGY", "")
        bot_id = os.getenv("V3_DESK_BOT_ID", "")

        instance = cls(
            enabled=enabled,
            mode=mode,
            strategy_name=strategy_name,
            bot_id=bot_id,
            legacy_strategy=legacy_strategy,
        )

        if enabled:
            logger.info(
                "V3 TradingDesk enabled: mode=%s strategy=%s bot_id=%s",
                mode, strategy_name, bot_id,
            )
        return instance

    def tick(self) -> None:
        """Run one v3 desk tick.  Safe to call even when disabled."""
        if not self._enabled:
            return

        if not self._initialized:
            self._lazy_init()
            if not self._initialized:
                return

        try:
            self._desk.tick()
            self._tick_count += 1
        except Exception:
            logger.exception("V3 desk tick error (tick=%d)", self._tick_count)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def stats(self) -> dict[str, Any]:
        """Shadow mode stats if available."""
        if not self._enabled or self._desk is None:
            return {}
        strategy = getattr(self._desk, "_strategy", None)
        if hasattr(strategy, "stats"):
            return strategy.stats
        return {"tick_count": self._tick_count, "mode": self._mode}

    # ── Lazy initialization ───────────────────────────────────────────

    def _lazy_init(self) -> None:
        """Initialize v3 components on first tick.

        This runs lazily so that import errors don't block the legacy
        strategy from starting.  If init fails, the integration is
        disabled with a warning — the legacy path continues unaffected.
        """
        try:
            self._do_init()
            self._initialized = True
            logger.info("V3 TradingDesk initialized: mode=%s", self._mode)
        except Exception as e:
            self._init_error = str(e)
            self._enabled = False
            logger.warning(
                "V3 TradingDesk init failed — disabling. Error: %s", e,
                exc_info=True,
            )

    def _do_init(self) -> None:
        from controllers.runtime.v3.data_surface import KernelDataSurface
        from controllers.runtime.v3.migration_shim import ShadowComparator, StrategyMigrationShim
        from controllers.runtime.v3.risk.bot_gate import BotRiskGate
        from controllers.runtime.v3.risk.desk_risk_gate import DeskRiskGate
        from controllers.runtime.v3.risk.portfolio_gate import PortfolioRiskGate
        from controllers.runtime.v3.risk.signal_gate import SignalRiskGate
        from controllers.runtime.v3.strategy_registry import load_strategy
        from controllers.runtime.v3.trading_desk import TradingDesk

        # Find the kernel controller from the legacy strategy
        controller = self._find_controller()
        if controller is None:
            raise RuntimeError("No active controller found in legacy strategy")

        # Build data surface wrapping the existing kernel
        surface = KernelDataSurface(controller)

        # Build risk gate (reads thresholds from controller config)
        risk_gate = self._build_risk_gate(controller)

        # Resolve the instance name
        instance_name = os.getenv("INSTANCE_NAME", "")
        if not instance_name:
            instance_name = getattr(controller, "controller_id", "unknown")

        # Build the strategy signal source
        if self._mode == "shadow" and self._bot_id:
            # Shadow mode: compare shim vs native
            shim = StrategyMigrationShim(controller, self._bot_id)
            if self._strategy_name:
                native = load_strategy(self._strategy_name)
                strategy = ShadowComparator(
                    shim, native,
                    instance_name=instance_name,
                )
            else:
                strategy = shim
        elif self._strategy_name:
            # Active mode: use native signal source
            strategy = load_strategy(self._strategy_name)
        else:
            raise RuntimeError(
                "V3_STRATEGY must be set, or use shadow mode with V3_DESK_BOT_ID"
            )

        # Resolve execution family
        execution_family = "mm_grid"
        if self._strategy_name:
            from controllers.runtime.v3.strategy_registry import get_entry
            execution_family = get_entry(self._strategy_name).execution_family

        # Build the desk
        # In shadow mode: no order submitter (observation only)
        # In active mode: TODO wire to HB connector or paper desk
        submitter = None
        if self._mode == "active":
            logger.warning(
                "V3 active mode: order submission not yet wired. "
                "Running in dry-run (signals computed but not executed)."
            )

        self._desk = TradingDesk(
            strategy=strategy,
            data_surface=surface,
            risk_gate=risk_gate,
            execution_family=execution_family,
            order_submitter=submitter,
            instance_name=instance_name,
        )

    def _find_controller(self) -> Any:
        """Extract the kernel controller from the legacy strategy."""
        controllers = getattr(self._legacy, "controllers", {})
        if isinstance(controllers, dict) and controllers:
            # Return the first (and usually only) controller
            return next(iter(controllers.values()))
        return None

    def _build_risk_gate(self, controller: Any) -> Any:
        from controllers.runtime.v3.risk.bot_gate import BotRiskConfig, BotRiskGate
        from controllers.runtime.v3.risk.desk_risk_gate import DeskRiskGate
        from controllers.runtime.v3.risk.portfolio_gate import PortfolioRiskGate
        from controllers.runtime.v3.risk.signal_gate import SignalRiskConfig, SignalRiskGate

        cfg = getattr(controller, "config", None)

        # Extract risk thresholds from controller config
        bot_config = BotRiskConfig()
        signal_config = SignalRiskConfig()
        if cfg is not None:
            from decimal import Decimal
            def _dec(attr, default):
                val = getattr(cfg, attr, None)
                if val is not None:
                    return Decimal(str(val)) if not isinstance(val, Decimal) else val
                return default

            bot_config = BotRiskConfig(
                max_daily_loss_pct_hard=_dec("max_daily_loss_pct_hard", bot_config.max_daily_loss_pct_hard),
                max_drawdown_pct_hard=_dec("max_drawdown_pct_hard", bot_config.max_drawdown_pct_hard),
                max_daily_turnover_x_hard=_dec("max_daily_turnover_x_hard", bot_config.max_daily_turnover_x_hard),
            )
            signal_config = SignalRiskConfig(
                min_net_edge_bps=_dec("min_net_edge_bps", signal_config.min_net_edge_bps),
                edge_resume_bps=_dec("edge_resume_bps", signal_config.edge_resume_bps),
            )

        # Portfolio gate uses Redis if bus client is available
        redis_client = getattr(self._legacy, "_bus_client", None)

        return DeskRiskGate(
            portfolio=PortfolioRiskGate(redis_client=redis_client),
            bot=BotRiskGate(bot_config),
            signal=SignalRiskGate(signal_config),
        )


__all__ = ["V3DeskIntegration"]
