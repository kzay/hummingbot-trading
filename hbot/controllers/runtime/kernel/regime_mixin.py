"""Regime detection mixin for SharedRuntimeKernel."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from controllers.runtime.kernel.config import _ONE, _TWO, _ZERO, _clip
from platform_lib.core.utils import to_decimal

if TYPE_CHECKING:
    from controllers.core import RegimeSpec

logger = logging.getLogger(__name__)


class RegimeMixin:

    def _resolve_regime_and_targets(self, mid: Decimal) -> tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        """Detect regime and resolve target base pct (spot vs perp).

        Returns ``(regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct)``
        where ``band_pct`` is the volatility measure actually used for regime classification,
        ensuring spread/edge and high-vol checks use the same ATR source.
        """
        regime_name, regime_spec, band_pct = self._detect_regime(mid)
        target_base_pct = regime_spec.target_base_pct
        if self._external_target_base_pct_override is not None:
            target_base_pct = _clip(self._external_target_base_pct_override, _ZERO, _ONE)
        if self._is_perp:
            target_net_base_pct = to_decimal(self.config.perp_target_net_base_pct) if self.config.perp_target_net_base_pct is not None else _ZERO
        else:
            target_net_base_pct = target_base_pct
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _get_ohlcv_ema_and_atr(self) -> tuple[Decimal | None, Decimal | None]:
        """Fetch OHLCV candles at indicator_resolution and compute EMA/band_pct."""
        connector = self.config.candles_connector
        if not connector:
            return None, None
        pair = self.config.candles_trading_pair or self.config.trading_pair
        resolution = getattr(self.config, "indicator_resolution", "1m")
        resolution_sec = getattr(self, "_resolution_minutes", 1) * 60
        needed = self.config.ema_period + 5
        try:
            df = self.market_data_provider.get_candles_df(connector, pair, resolution, needed)
        except Exception:
            return None, None
        if df is None or df.empty or len(df) < self.config.ema_period:
            return None, None
        try:
            if "timestamp" in df.columns:
                now_s = float(self.market_data_provider.time())
                last_ts = float(df["timestamp"].iloc[-1])
                last_ts_s = last_ts / 1000.0 if last_ts > 1e10 else last_ts
                if now_s - last_ts_s < float(resolution_sec):
                    df = df.iloc[:-1]
        except Exception:
            pass  # Justification: timestamp trim is best-effort — keep dataframe if time parsing fails
        if df.empty or len(df) < self.config.ema_period:
            return None, None
        try:
            closes = [to_decimal(c) for c in df["close"].values]
            alpha = _TWO / Decimal(self.config.ema_period + 1)
            ema_val = closes[0]
            for c in closes[1:]:
                ema_val = alpha * c + (_ONE - alpha) * ema_val
            highs = [to_decimal(h) for h in df["high"].values]
            lows = [to_decimal(lo) for lo in df["low"].values]
            trs: list[Decimal] = []
            for i in range(1, len(closes)):
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
                trs.append(tr)
            atr_period = min(self.config.atr_period, len(trs))
            if atr_period <= 0 or closes[-1] <= _ZERO:
                return ema_val, None
            atr_val = sum(trs[-atr_period:], _ZERO) / Decimal(atr_period)
            band_pct = atr_val / closes[-1]
            return ema_val, band_pct
        except Exception:
            return None, None

    def _detect_regime(self, mid: Decimal) -> tuple[str, RegimeSpec, Decimal]:
        """Classify regime and return the band_pct that was actually used.

        Returns ``(regime_name, regime_spec, band_pct)`` so callers can thread
        the same volatility measure into spread/edge and high-vol checks, ensuring
        all three consumers see a consistent view of current volatility.
        """
        if self.config.ml_regime_enabled and self._external_regime_override:
            now = float(self.market_data_provider.time())
            if now < self._external_regime_override_expiry:
                regime = self._external_regime_override
                self._active_regime = regime
                self._regime_source = "ml"
                # ML path: derive band_pct from price buffer (OHLCV not used here).
                ml_band = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
                return regime, self._resolved_specs[regime], ml_band
            else:
                self._external_regime_override = None

        ohlcv_ema, ohlcv_band = self._get_ohlcv_ema_and_atr()
        if ohlcv_ema is not None and ohlcv_band is not None:
            ema_val, band_pct, source_tag = ohlcv_ema, ohlcv_band, "ohlcv"
        else:
            ema_val = self._price_buffer.ema(self.config.ema_period)
            band_pct = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
            source_tag = "price_buffer"
        drift = self._price_buffer.adverse_drift_30s(float(self.market_data_provider.time()))
        self._regime_ema_value = ema_val

        regime_name, regime_spec = self._regime_detector.detect(
            mid, ema_val, band_pct, drift, source_tag,
        )
        self._active_regime = self._regime_detector._active_regime
        self._pending_regime = self._regime_detector._pending_regime
        self._regime_hold_counter = self._regime_detector._regime_hold_counter
        self._regime_source = self._regime_detector._regime_source

        if self._regime_detector.changed_one_sided is not None:
            self.replace_stale_cancels(self._cancel_stale_side_executors(
                self._regime_detector.changed_one_sided, regime_spec.one_sided,
            ))

        return regime_name, regime_spec, band_pct

    def _compute_ob_imbalance(self, depth: int = 5) -> Decimal:
        """Compute order book imbalance from top-N levels: (bid_depth - ask_depth) / (bid_depth + ask_depth).

        Returns value in [-1, +1]. Positive = more bids (buy pressure). Guarded by try/except.
        """
        try:
            return _clip(self._runtime_adapter.get_depth_imbalance(depth=depth), Decimal("-1"), _ONE)
        except Exception:
            return _ZERO
