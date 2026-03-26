"""Bot7 ML Signal Source — pure ML-driven strategy for the v3 trading desk.

Composes 4 ML model predictions (regime, direction, adverse, sizing) into
a single TradingSignal.  No hand-crafted indicator gates — the ML models
are the signal source.

The strategy defaults to regime-aware symmetric market making.  Directional
bias is applied only when the direction model exceeds a high confidence
threshold.  This is intentional: the regime model (59% OOS accuracy) is the
real edge; the direction model (48.5%) is essentially random and rarely
produces high-confidence predictions.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from controllers.ml.regime_policy import RegimePolicy
from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import MarketSnapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_MODEL_BASE = Path("data/ml/models")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class MlSignalConfig:
    """Configuration for the ML signal source — all tuneable via YAML."""

    # Model paths (relative to project root)
    exchange: str = "bitget"
    pair: str = "BTC-USDT"

    # Confidence thresholds
    direction_high_confidence: float = 0.70
    direction_med_confidence: float = 0.60
    adverse_confidence_threshold: float = 0.60
    regime_min_confidence: float = 0.40

    # Sizing
    use_ml_sizing: bool = False
    base_size_quote: Decimal = Decimal("200")
    max_levels: int = 3
    base_spread_pct: Decimal = Decimal("0.0025")
    spread_step_pct: Decimal = Decimal("0.0015")

    # Position targets
    target_net_base_pct: Decimal = Decimal("0.04")

    # Fallback
    fallback_regime: str = "neutral_low_vol"


# ---------------------------------------------------------------------------
# Loaded model wrapper
# ---------------------------------------------------------------------------


@dataclass
class _LoadedModel:
    model: Any
    feature_columns: list[str]
    label_mapping: dict[str, str] = field(default_factory=dict)


def _load_model(model_dir: Path, model_type: str) -> _LoadedModel | None:
    """Load a joblib model and its metadata from the standard directory."""
    model_path = model_dir / f"{model_type}_v1.joblib"
    meta_path = model_dir / f"{model_type}_v1_metadata.json"
    if not model_path.exists():
        logger.warning("Model not found: %s", model_path)
        return None
    try:
        import joblib
        model = joblib.load(model_path)
        feature_columns: list[str] = []
        label_mapping: dict[str, str] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            feature_columns = meta.get("feature_columns", [])
            label_mapping = meta.get("label_mapping", {})
        logger.info("Loaded %s model from %s (%d features)", model_type, model_path, len(feature_columns))
        return _LoadedModel(model=model, feature_columns=feature_columns, label_mapping=label_mapping)
    except Exception as exc:
        logger.error("Failed to load %s model: %s", model_type, exc)
        return None


def _predict(loaded: _LoadedModel, features: dict[str, Any]) -> tuple[float, float]:
    """Run prediction and return (raw_output, confidence).

    Returns (0.0, 0.0) on any error so the caller can fall through
    to a safe default.
    """
    try:
        import numpy as np
        vec = [float(features.get(col, 0.0) or 0.0) for col in loaded.feature_columns]
        X = np.array([vec])
        # Handle NaN — tree models handle it natively, but be safe
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        pred = loaded.model.predict(X)[0]

        # Confidence from predict_proba if available
        confidence = 0.0
        if hasattr(loaded.model, "predict_proba"):
            proba = loaded.model.predict_proba(X)[0]
            confidence = float(max(proba))
        elif hasattr(loaded.model, "decision_function"):
            df = loaded.model.decision_function(X)[0]
            confidence = float(1.0 / (1.0 + math.exp(-abs(float(df)))))

        return float(pred), confidence
    except Exception as exc:
        logger.debug("Prediction failed for %s: %s", loaded.feature_columns[:3], exc)
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# Regime resolution (matches inference_engine.resolve_composite_regime)
# ---------------------------------------------------------------------------

_VOL_LABELS = {0: "vol_low", 1: "vol_normal", 2: "vol_elevated", 3: "vol_extreme"}


def _resolve_composite_regime(
    vol_label: str,
    direction_pred: float,
    direction_conf: float,
    direction_threshold: float = 0.55,
) -> str:
    """Map vol bucket + direction hint to a composite operating regime."""
    if vol_label == "vol_extreme":
        return "high_vol_shock"
    has_direction = direction_conf >= direction_threshold
    if vol_label in ("vol_low", "vol_normal"):
        if has_direction:
            return "up" if direction_pred >= 0.5 else "down"
        return "neutral_low_vol"
    # vol_elevated
    if has_direction:
        return "up" if direction_pred >= 0.5 else "down"
    return "neutral_high_vol"


# ---------------------------------------------------------------------------
# Signal source
# ---------------------------------------------------------------------------


class MlSignalSource:
    """Pure ML signal-driven strategy for bot7.

    Composes regime, adverse, direction, and sizing model predictions
    into a TradingSignal.  Defaults to regime-aware symmetric MM;
    directional bias applied only at high confidence.
    """

    def __init__(self, config: MlSignalConfig | None = None) -> None:
        self._cfg = config or MlSignalConfig()
        self._policy = RegimePolicy()
        self._models_loaded = False
        self._regime: _LoadedModel | None = None
        self._direction: _LoadedModel | None = None
        self._adverse: _LoadedModel | None = None
        self._sizing: _LoadedModel | None = None

    # -- Protocol: StrategySignalSource ------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        mid = snapshot.mid
        if mid <= _ZERO:
            return TradingSignal.no_trade("no_mid")

        self._ensure_models_loaded()

        # ── Extract ML features from snapshot ────────────────────────
        ml = snapshot.ml
        features: dict[str, Any] = ml.features if ml is not None else {}
        if not features:
            return TradingSignal.no_trade("no_ml_features")

        cfg = self._cfg

        # ── Step 1: Adverse veto ─────────────────────────────────────
        if self._adverse is not None:
            adverse_features = self._build_adverse_features(snapshot)
            adv_pred, adv_conf = _predict(self._adverse, adverse_features)
            if adv_pred >= 0.5 and adv_conf >= cfg.adverse_confidence_threshold:
                return TradingSignal.no_trade("adverse_veto")
        else:
            adv_pred, adv_conf = 0.0, 0.0

        # ── Step 2: Direction prediction ─────────────────────────────
        dir_pred, dir_conf = 0.0, 0.0
        if self._direction is not None:
            dir_pred, dir_conf = _predict(self._direction, features)

        # ── Step 3: Regime prediction ────────────────────────────────
        regime_name = cfg.fallback_regime
        regime_conf = 0.0
        if self._regime is not None:
            reg_pred, regime_conf = _predict(self._regime, features)
            if regime_conf >= cfg.regime_min_confidence:
                vol_label = _VOL_LABELS.get(int(reg_pred), "vol_normal")
                regime_name = _resolve_composite_regime(
                    vol_label, dir_pred, dir_conf,
                    direction_threshold=cfg.direction_med_confidence,
                )

        regime_action = self._policy.get(regime_name)
        if not regime_action.trading_allowed:
            return TradingSignal.no_trade(f"regime_{regime_name}_halted")

        # ── Step 4: Sizing ───────────────────────────────────────────
        sizing_mult = Decimal("1")
        if cfg.use_ml_sizing and self._sizing is not None:
            sz_pred, _ = _predict(self._sizing, features)
            sizing_mult = Decimal(str(max(0.3, min(1.5, sz_pred))))

        # ── Step 5: Compose signal ───────────────────────────────────
        spread_mult = Decimal(str(regime_action.spread_mult))
        size_mult = Decimal(str(regime_action.sizing_mult))

        # Check if regime allows directional strategies at all
        can_directional = (
            regime_action.directional_allowed
            and self._policy.is_strategy_allowed(regime_name, "hybrid")
        )

        if (dir_conf >= cfg.direction_high_confidence and can_directional):
            direction = "buy" if dir_pred >= 0.5 else "sell"
            conviction = Decimal(str(dir_conf)) * size_mult
        elif (dir_conf >= cfg.direction_med_confidence and can_directional):
            direction = "buy" if dir_pred >= 0.5 else "sell"
            conviction = Decimal(str(dir_conf)) * size_mult * Decimal("0.7")
        else:
            direction = "both"
            conviction = Decimal(str(max(regime_conf, 0.3))) * Decimal("0.5")

        conviction = min(conviction * sizing_mult, _ONE)

        # Build levels — for symmetric "both", each iteration creates 2
        # orders (buy+sell), so halve to stay within max_concurrent_positions.
        base_spread = cfg.base_spread_pct * spread_mult
        spread_step = cfg.spread_step_pct * spread_mult
        size_per_level = cfg.base_size_quote * size_mult * sizing_mult
        max_pos = regime_action.max_concurrent_positions
        if direction == "both":
            n_levels = min(cfg.max_levels, max(1, max_pos // 2))
        else:
            n_levels = min(cfg.max_levels, max_pos)

        levels: list[SignalLevel] = []
        for i in range(n_levels):
            spread = base_spread + spread_step * i
            if direction == "both":
                levels.append(SignalLevel(side="buy", spread_pct=spread, size_quote=size_per_level, level_id=f"ml_b{i}"))
                levels.append(SignalLevel(side="sell", spread_pct=spread, size_quote=size_per_level, level_id=f"ml_s{i}"))
            else:
                levels.append(SignalLevel(side=direction, spread_pct=spread, size_quote=size_per_level, level_id=f"ml_{direction[0]}{i}"))

        target = cfg.target_net_base_pct if direction == "buy" else (
            -cfg.target_net_base_pct if direction == "sell" else _ZERO
        )

        return TradingSignal(
            family="hybrid",
            direction=direction,
            conviction=conviction,
            target_net_base_pct=target,
            levels=tuple(levels),
            metadata={
                "regime": regime_name,
                "regime_conf": round(regime_conf, 4),
                "dir_pred": round(dir_pred, 4),
                "dir_conf": round(dir_conf, 4),
                "adv_pred": round(adv_pred, 4),
                "adv_conf": round(adv_conf, 4),
                "sizing_mult": float(sizing_mult),
                "n_levels": len(levels),
            },
            reason=f"ml_{direction}_{regime_name}",
        )

    def warmup_bars_required(self) -> int:
        return 300  # Feature pipeline needs ~240 bars for vol percentiles

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema(fields=(
            TelemetryField(name="ml_regime", key="regime", type="str", default=""),
            TelemetryField(name="ml_regime_conf", key="regime_conf"),
            TelemetryField(name="ml_dir_pred", key="dir_pred"),
            TelemetryField(name="ml_dir_conf", key="dir_conf"),
            TelemetryField(name="ml_adv_pred", key="adv_pred"),
            TelemetryField(name="ml_adv_conf", key="adv_conf"),
            TelemetryField(name="ml_sizing_mult", key="sizing_mult"),
            TelemetryField(name="ml_n_levels", key="n_levels", type="int", default=0),
        ))

    # -- Internals ---------------------------------------------------------

    def _ensure_models_loaded(self) -> None:
        if self._models_loaded:
            return
        self._models_loaded = True
        model_dir = _MODEL_BASE / self._cfg.exchange / self._cfg.pair
        self._regime = _load_model(model_dir, "regime")
        self._direction = _load_model(model_dir, "direction")
        self._adverse = _load_model(model_dir, "adverse")
        if self._cfg.use_ml_sizing:
            self._sizing = _load_model(model_dir, "sizing")

    def _build_adverse_features(self, snapshot: MarketSnapshot) -> dict[str, Any]:
        """Assemble the adverse model's fill-level feature vector from snapshot.

        The adverse model uses a different feature space than the market-level
        models (19 features: spread, edge, position, regime one-hot, etc.).
        """
        ob = snapshot.order_book
        pos = snapshot.position
        eq = snapshot.equity
        regime = snapshot.regime.name

        # Time features (cyclical encoding)
        import time as _time
        hour = _time.gmtime().tm_hour + _time.gmtime().tm_min / 60.0
        time_sin = math.sin(2 * math.pi * hour / 24.0)
        time_cos = math.cos(2 * math.pi * hour / 24.0)

        return {
            "side_buy": 1.0,
            "side_sell": 0.0,
            "is_maker": 1.0,
            "time_sin": time_sin,
            "time_cos": time_cos,
            "spread_pct": float(ob.spread_pct),
            "net_edge_pct": float(ob.spread_pct) * 0.5,  # Approximate
            "adverse_drift_bps": 0.0,
            "spread_floor_pct": float(self._cfg.base_spread_pct),
            "base_pct": float(pos.gross_base_pct),
            "ob_imbalance": float(ob.imbalance),
            "fill_edge_ewma_bps": 0.0,
            "turnover_x": float(eq.daily_turnover_x),
            "regime_neutral_low_vol": 1.0 if regime == "neutral_low_vol" else 0.0,
            "regime_neutral_high_vol": 1.0 if regime == "neutral_high_vol" else 0.0,
            "regime_up": 1.0 if regime == "up" else 0.0,
            "regime_down": 1.0 if regime == "down" else 0.0,
            "regime_high_vol_shock": 1.0 if regime == "high_vol_shock" else 0.0,
            "base_pct_signed": float(pos.net_base_pct),
        }
