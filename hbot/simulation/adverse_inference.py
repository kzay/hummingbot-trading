"""Adverse fill ML classifier for the HB bridge.

Extracted from hb_bridge.py (DEBT-3). Functions receive bridge state
as a parameter to avoid circular imports with hb_bridge.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _load_adverse_model(bridge_state: Any, model_path: str) -> Any | None:
    """Lazy-load adverse fill classifier from joblib file. Returns None on failure."""
    if bridge_state.adverse_model_loaded and bridge_state.adverse_model_path == model_path:
        return bridge_state.adverse_model
    bridge_state.adverse_model_path = model_path
    bridge_state.adverse_model_loaded = True
    if not model_path:
        return None
    try:
        import joblib as _joblib  # type: ignore[import-untyped]
        bridge_state.adverse_model = _joblib.load(model_path)
        logger.info("Adverse classifier loaded from %s", model_path)
        return bridge_state.adverse_model
    except Exception as exc:
        logger.warning("Adverse classifier load failed (%s): %s — running without adverse classifier", model_path, exc)
        bridge_state.adverse_model = None
        return None


def _build_adverse_features(controller: Any) -> list[float] | None:
    """Build feature vector from controller's processed_data for adverse inference."""
    try:
        custom = controller.get_custom_info() if hasattr(controller, "get_custom_info") else {}
        if not custom:
            return None

        import math
        import time as _t

        side_buy = 0.5
        side_sell = 0.5
        is_maker = 0.5
        now = _t.time()
        hour = int((now % 86400) // 3600)
        time_sin = math.sin(2 * math.pi * hour / 24.0)
        time_cos = math.cos(2 * math.pi * hour / 24.0)

        def _f(key, default=0.0):
            v = custom.get(key, default)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        regime_str = str(custom.get("regime", "neutral_low_vol"))
        regime_labels = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]
        regime_features = {f"regime_{r}": (1.0 if regime_str == r else 0.0) for r in regime_labels}

        base_pct = _f("base_pct")
        feats = {
            "side_buy": side_buy,
            "side_sell": side_sell,
            "is_maker": is_maker,
            "time_sin": time_sin,
            "time_cos": time_cos,
            "spread_pct": _f("spread_pct"),
            "net_edge_pct": _f("net_edge_pct"),
            "adverse_drift_bps": _f("adverse_drift_30s") * 10000,
            "spread_floor_pct": _f("spread_floor_pct"),
            "base_pct": base_pct,
            "ob_imbalance": _f("ob_imbalance"),
            "fill_edge_ewma_bps": _f("fill_edge_ewma_bps"),
            "turnover_x": _f("turnover_x"),
            "base_pct_signed": base_pct,
            **regime_features,
        }

        ordered_keys = sorted(feats.keys())
        return [feats[k] for k in ordered_keys]
    except Exception:
        return None


def _run_adverse_inference(strategy: Any, bridge_state: Any) -> None:
    """Run adverse fill classifier per tick. Calls apply_execution_intent on controllers.

    - p_adverse > adverse_threshold_widen: widens spread by (1 + p_adverse * 0.5)
    - p_adverse > adverse_threshold_skip: skips quoting for this tick (max 3 consecutive)
    - Classifier not loaded or error: no-op (safe fallback)
    """
    controllers = getattr(strategy, "controllers", {})
    for ctrl_key, ctrl in controllers.items():
        try:
            cfg = getattr(ctrl, "config", None)
            if cfg is None:
                continue
            if not getattr(cfg, "adverse_classifier_enabled", False):
                continue
            model_path = str(getattr(cfg, "adverse_classifier_model_path", "") or "")
            model = _load_adverse_model(bridge_state, model_path)
            if model is None:
                continue

            features = _build_adverse_features(ctrl)
            if features is None:
                continue

            try:
                proba = model.predict_proba([features])[0]
                p_adverse = float(max(proba))
                if hasattr(model, "classes_"):
                    adverse_class_idx = list(model.classes_).index(1) if 1 in model.classes_ else 1
                    p_adverse = float(proba[adverse_class_idx])
            except (ValueError, TypeError, IndexError, AttributeError):
                continue

            threshold_widen = float(getattr(cfg, "adverse_threshold_widen", 0.70))
            threshold_skip = float(getattr(cfg, "adverse_threshold_skip", 0.85))

            if p_adverse > threshold_skip:
                skip_count = getattr(ctrl, "_adverse_skip_count", 0)
                if skip_count < 3:
                    if hasattr(ctrl, "apply_execution_intent"):
                        ctrl.apply_execution_intent({"action": "adverse_skip_tick", "metadata": {"p_adverse": str(p_adverse)}})
                    ctrl._adverse_skip_count = skip_count + 1
                    logger.debug("Adverse skip tick: controller=%s p_adverse=%.3f (count=%d)", ctrl_key, p_adverse, ctrl._adverse_skip_count)
                else:
                    ctrl._adverse_skip_count = 0
            elif p_adverse > threshold_widen:
                if hasattr(ctrl, "apply_execution_intent"):
                    ctrl.apply_execution_intent({
                        "action": "adverse_widen_spreads",
                        "metadata": {"p_adverse": str(p_adverse)},
                    })
                ctrl._adverse_skip_count = 0
                logger.debug("Adverse widen: controller=%s p_adverse=%.3f", ctrl_key, p_adverse)
            else:
                ctrl._adverse_skip_count = 0

        except Exception as exc:
            logger.warning("Adverse inference failed for %s: %s", ctrl_key, exc)
