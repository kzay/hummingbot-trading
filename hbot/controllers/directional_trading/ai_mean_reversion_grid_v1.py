"""
AI Mean Reversion Grid V1
=========================

AI-augmented range strategy for crypto assets:
  - Mean-reversion entries gated by indicators + AI probability.
  - Dynamic grid envelope around AI-predicted mean.
  - Optional pair/hedge diagnostics with cointegration checks.
  - Built for paper/live adaptation with conservative defaults.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pandas_ta as ta  # noqa: F401
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig,
    TripleBarrierConfig,
)

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
except Exception:  # pragma: no cover
    torch = None
    nn = None

try:
    from sklearn.cluster import KMeans
except Exception:  # pragma: no cover
    KMeans = None

try:
    from statsmodels.tsa.stattools import adfuller, coint
except Exception:  # pragma: no cover
    adfuller = None
    coint = None


@dataclass
class AIPrediction:
    reversion_probability: float
    expected_mean: float


class _GRUForecaster(nn.Module):
    def __init__(self, input_size: int = 6, hidden_size: int = 32):
        super().__init__()
        self.gru = nn.GRU(input_size=input_size, hidden_size=hidden_size, batch_first=True)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 2),
        )

    def forward(self, x):
        out, _ = self.gru(x)
        final = out[:, -1, :]
        raw = self.head(final)
        return raw


class AiMeanReversionGridV1Config(DirectionalTradingControllerConfigBase):
    controller_name: str = "ai_mean_reversion_grid_v1"

    candles_connector: Optional[str] = Field(default=None, json_schema_extra={"prompt_on_new": True})
    candles_trading_pair: Optional[str] = Field(default=None, json_schema_extra={"prompt_on_new": True})
    interval_fast: str = Field(default="15m", json_schema_extra={"prompt_on_new": True})
    interval_slow: str = Field(default="1h", json_schema_extra={"prompt_on_new": True})
    interval_confirm: str = Field(default="4h", json_schema_extra={"prompt_on_new": True})

    rsi_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    bb_length: int = Field(default=20, json_schema_extra={"is_updatable": True})
    bb_std: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    zscore_length: int = Field(default=40, json_schema_extra={"is_updatable": True})
    adx_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    adx_range_threshold: float = Field(default=20.0, json_schema_extra={"is_updatable": True})
    adx_breakout_threshold: float = Field(default=25.0, json_schema_extra={"is_updatable": True})
    stoch_k: int = Field(default=14, json_schema_extra={"is_updatable": True})
    stoch_d: int = Field(default=3, json_schema_extra={"is_updatable": True})
    stoch_smooth_k: int = Field(default=3, json_schema_extra={"is_updatable": True})
    atr_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    kalman_process_var: float = Field(default=1e-5, json_schema_extra={"is_updatable": True})
    kalman_measurement_var: float = Field(default=1e-2, json_schema_extra={"is_updatable": True})

    ai_model_path: str = Field(default="", json_schema_extra={"is_updatable": True})
    ai_probability_threshold: float = Field(default=0.80, json_schema_extra={"is_updatable": True})
    expected_mean_blend: float = Field(default=0.65, json_schema_extra={"is_updatable": True})
    ai_feature_window: int = Field(default=64, json_schema_extra={"is_updatable": True})

    grid_levels_min: int = Field(default=10, json_schema_extra={"is_updatable": True})
    grid_levels_max: int = Field(default=20, json_schema_extra={"is_updatable": True})
    grid_band_min_pct: float = Field(default=0.010, json_schema_extra={"is_updatable": True})
    grid_band_max_pct: float = Field(default=0.020, json_schema_extra={"is_updatable": True})
    dca_max_levels: int = Field(default=5, json_schema_extra={"is_updatable": True})

    max_total_exposure_ratio: float = Field(default=0.05, json_schema_extra={"is_updatable": True})
    level_size_min_pct: float = Field(default=0.002, json_schema_extra={"is_updatable": True})
    level_size_max_pct: float = Field(default=0.005, json_schema_extra={"is_updatable": True})
    max_leverage: int = Field(default=2, json_schema_extra={"is_updatable": True})
    halt_drawdown_ratio: float = Field(default=0.10, json_schema_extra={"is_updatable": True})

    pairs_candidates_csv: str = Field(default="", json_schema_extra={"is_updatable": True})
    pairs_corr_threshold: float = Field(default=0.80, json_schema_extra={"is_updatable": True})
    coint_pvalue_threshold: float = Field(default=0.05, json_schema_extra={"is_updatable": True})
    adf_pvalue_threshold: float = Field(default=0.10, json_schema_extra={"is_updatable": True})
    pairs_refresh_minutes: int = Field(default=120, json_schema_extra={"is_updatable": True})
    hedge_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})

    short_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})
    min_signal_strength: float = Field(default=0.2, json_schema_extra={"is_updatable": True})

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_conn(cls, v, info: ValidationInfo):
        return info.data.get("connector_name") if not v else v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        return info.data.get("trading_pair") if not v else v


class AiMeanReversionGridV1Controller(DirectionalTradingControllerBase):
    def __init__(self, config: AiMeanReversionGridV1Config, *args, **kwargs):
        self.config = config
        self._model = None
        self._model_loaded = False
        self._last_pair_scan_ts: int = 0
        self._pairs_snapshot: Dict[str, float] = {}

        self._fast_lb = max(config.bb_length, config.rsi_length, config.stoch_k, config.ai_feature_window) + 20
        self._slow_lb = max(config.adx_length, config.atr_length, config.zscore_length) + 40
        self._confirm_lb = max(config.adx_length, 40) + 20

        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_fast,
                    max_records=self._fast_lb,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_slow,
                    max_records=self._slow_lb,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_confirm,
                    max_records=self._confirm_lb,
                ),
            ]

        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        df_fast = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_fast,
            max_records=self._fast_lb,
        )
        df_slow = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_slow,
            max_records=self._slow_lb,
        )
        df_confirm = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_confirm,
            max_records=self._confirm_lb,
        )

        if df_fast is None or df_slow is None or df_fast.empty or df_slow.empty:
            self.processed_data = {"signal": 0.0, "signal_type": "warmup", "meta": "waiting for candles"}
            return

        if len(df_fast) < self.config.bb_length + 5 or len(df_slow) < self.config.adx_length + 5:
            self.processed_data = {"signal": 0.0, "signal_type": "warmup", "meta": "insufficient lookback"}
            return

        close_f = df_fast["close"].astype(float)
        high_f = df_fast["high"].astype(float)
        low_f = df_fast["low"].astype(float)
        close_s = df_slow["close"].astype(float)
        high_s = df_slow["high"].astype(float)
        low_s = df_slow["low"].astype(float)

        price = float(close_f.iloc[-1])
        kalman_mean = self._kalman_last(close_f)
        bb_lower, bb_mid, bb_upper, bb_pctb = self._bollinger_values(close_f)
        rsi_val = self._last(ta.rsi(close_f, length=self.config.rsi_length), 50.0)
        zscore = self._zscore(close_f)
        adx_val = self._adx_value(high_s, low_s, close_s)
        adx_confirm = self._adx_confirm(df_confirm)
        stoch_k, stoch_d = self._stochastic_values(high_f, low_f, close_f)
        atr_price = self._last(ta.atr(high_s, low_s, close_s, length=self.config.atr_length), price * 0.01)
        atr_pct = atr_price / max(price, 1e-12)

        features = self._feature_frame(close_f, rsi_val, bb_pctb, zscore, adx_val, stoch_k, kalman_mean)
        ai_pred = self._ai_predict(features=features, fallback_mean=kalman_mean, fallback_prob=self._heuristic_prob(
            rsi=rsi_val, bb_pctb=bb_pctb, zscore=zscore, adx=adx_val, stoch_k=stoch_k, stoch_d=stoch_d
        ))

        expected_mean = (
            self.config.expected_mean_blend * ai_pred.expected_mean +
            (1.0 - self.config.expected_mean_blend) * bb_mid
        )
        mean_distance = (price - expected_mean) / max(price, 1e-12)

        adf_pvalue = self._adf_pvalue(close_f)
        pair_meta = self._refresh_pair_diagnostics(close_f)
        stationarity_ok = adf_pvalue <= self.config.adf_pvalue_threshold
        in_range_regime = adx_val < self.config.adx_range_threshold and adx_confirm < self.config.adx_breakout_threshold

        stoch_up = stoch_k > stoch_d
        stoch_down = stoch_k < stoch_d
        long_setup = rsi_val < 30 and price <= bb_lower and zscore <= -2.0 and in_range_regime and stoch_up
        short_setup = rsi_val > 70 and price >= bb_upper and zscore >= 2.0 and in_range_regime and stoch_down

        ai_gate = ai_pred.reversion_probability >= self.config.ai_probability_threshold
        risk_gate = self._risk_gate(adx_val=adx_val, stationarity_ok=stationarity_ok)
        signal = 0.0
        signal_type = "flat"
        if risk_gate and ai_gate:
            if long_setup:
                signal = min(1.0, abs(mean_distance) * 50.0 + 0.35)
                signal_type = "long_reversion"
            elif short_setup and self.config.short_enabled:
                signal = -min(1.0, abs(mean_distance) * 50.0 + 0.35)
                signal_type = "short_reversion"

        if abs(signal) < self.config.min_signal_strength:
            signal = 0.0
            if signal_type not in ("warmup",):
                signal_type = "flat"

        grid_band_pct = self._dynamic_grid_band(atr_pct=atr_pct, zscore=abs(zscore))
        grid_levels = self._dynamic_grid_levels(atr_pct=atr_pct, stationarity_p=adf_pvalue)
        per_level_size = self._dynamic_level_size(atr_pct=atr_pct, stationarity_p=adf_pvalue)
        dca_levels = min(self.config.dca_max_levels, max(1, int(grid_levels / 4)))

        if self.config.hedge_enabled and pair_meta.get("cointegrated", 0.0) > 0.5:
            signal *= 0.85

        signal = max(-1.0, min(1.0, signal))
        stop_loss = max(0.004, min(0.06, 2.0 * atr_pct))
        take_profit = max(0.005, min(0.05, abs(mean_distance) + 0.002))

        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "meta": "ai-gated mean reversion grid",
            "current_price": price,
            "expected_mean": expected_mean,
            "reversion_prob": ai_pred.reversion_probability,
            "rsi": rsi_val,
            "bb_lower": bb_lower,
            "bb_mid": bb_mid,
            "bb_upper": bb_upper,
            "bb_pctb": bb_pctb,
            "zscore": zscore,
            "adx": adx_val,
            "adx_confirm": adx_confirm,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
            "atr_pct": atr_pct * 100.0,
            "mean_distance_pct": mean_distance * 100.0,
            "grid_band_pct": grid_band_pct * 100.0,
            "grid_levels": grid_levels,
            "dca_levels": dca_levels,
            "per_level_size_pct": per_level_size * 100.0,
            "risk_gate": risk_gate,
            "ai_gate": ai_gate,
            "stationarity_pvalue": adf_pvalue,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "pair_meta": pair_meta,
        }

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        signal = float(self.processed_data.get("signal", 0.0))
        side = TradeType.BUY if signal >= 0 else TradeType.SELL

        leverage = min(max(1, int(self.config.leverage)), self.config.max_leverage)
        sl = Decimal(str(self.processed_data.get("stop_loss", 0.015)))
        tp = Decimal(str(self.processed_data.get("take_profit", 0.015)))
        time_limit = self.config.time_limit if self.config.time_limit > 0 else 8 * 3600

        tb = TripleBarrierConfig(
            stop_loss=sl,
            take_profit=tp,
            time_limit=time_limit,
            trailing_stop=None,
            open_order_type=OrderType.MARKET,
            take_profit_order_type=OrderType.LIMIT,
            stop_loss_order_type=OrderType.MARKET,
        )

        per_level_size = float(self.processed_data.get("per_level_size_pct", self.config.level_size_min_pct * 100.0)) / 100.0
        exposure_cap = float(self.config.total_amount_quote) * self.config.max_total_exposure_ratio
        desired_amount = float(amount) * abs(signal) * max(0.1, min(1.0, per_level_size / self.config.level_size_max_pct))
        clipped_amount = min(desired_amount, exposure_cap)
        adj_amount = Decimal(str(max(0.0, clipped_amount)))

        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=adj_amount,
            triple_barrier_config=tb,
            leverage=leverage,
            side=side,
        )

    def to_format_status(self) -> List[str]:
        d = self.processed_data
        pair_meta = d.get("pair_meta", {})
        return [
            "AI Mean Reversion Grid V1",
            f"Signal: {d.get('signal', 0.0):+.3f} ({d.get('signal_type', 'flat')})",
            f"P(reversion): {d.get('reversion_prob', 0.0):.2f} | AI gate={d.get('ai_gate', False)}",
            f"Price={d.get('current_price', 0.0):.4f} Mean={d.get('expected_mean', 0.0):.4f} Dist={d.get('mean_distance_pct', 0.0):+.2f}%",
            f"RSI={d.get('rsi', 50.0):.1f} Z={d.get('zscore', 0.0):+.2f} ADX={d.get('adx', 0.0):.1f}/{d.get('adx_confirm', 0.0):.1f}",
            f"Grid {d.get('grid_levels', 0)} levels, +/-{d.get('grid_band_pct', 0.0):.2f}% | DCA={d.get('dca_levels', 0)}",
            f"SL={d.get('stop_loss', 0.0):.2%} TP={d.get('take_profit', 0.0):.2%} | ADF p={d.get('stationarity_pvalue', 1.0):.3f}",
            f"Pair hedge: {pair_meta.get('pair', 'n/a')} corr={pair_meta.get('correlation', 0.0):.2f} coint={pair_meta.get('cointegrated', 0.0):.0f}",
        ]

    def get_custom_info(self) -> dict:
        keys = [
            "signal",
            "signal_type",
            "reversion_prob",
            "expected_mean",
            "grid_levels",
            "grid_band_pct",
            "dca_levels",
            "per_level_size_pct",
            "stationarity_pvalue",
            "pair_meta",
            "risk_gate",
            "ai_gate",
        ]
        return {k: self.processed_data.get(k) for k in keys}

    def _feature_frame(
        self,
        close: pd.Series,
        rsi_val: float,
        bb_pctb: float,
        zscore: float,
        adx_val: float,
        stoch_k: float,
        kalman_mean: float,
    ) -> pd.DataFrame:
        base = pd.DataFrame({"close": close.astype(float)})
        base["ret"] = base["close"].pct_change().fillna(0.0)
        base["rsi"] = rsi_val
        base["bb_pctb"] = bb_pctb
        base["zscore"] = zscore
        base["adx"] = adx_val
        base["stoch_k"] = stoch_k
        base["mean_distance"] = (base["close"] - kalman_mean) / base["close"].replace(0.0, 1.0)
        return base.tail(max(8, self.config.ai_feature_window)).fillna(0.0)

    def _ai_predict(self, features: pd.DataFrame, fallback_mean: float, fallback_prob: float) -> AIPrediction:
        if torch is None:
            return AIPrediction(reversion_probability=fallback_prob, expected_mean=fallback_mean)

        if not self._model_loaded:
            self._model = self._load_model()
            self._model_loaded = True

        if self._model is None:
            return AIPrediction(reversion_probability=fallback_prob, expected_mean=fallback_mean)

        try:
            cols = ["rsi", "bb_pctb", "zscore", "adx", "stoch_k", "mean_distance"]
            x = features[cols].astype(float).values
            x_t = torch.tensor(x, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                raw = self._model(x_t)[0]
                prob = torch.sigmoid(raw[0]).item()
                mean_shift = torch.tanh(raw[1]).item() * float(features["close"].iloc[-1]) * 0.01
                expected_mean = float(features["close"].iloc[-1]) - mean_shift
            return AIPrediction(
                reversion_probability=max(0.0, min(1.0, float(prob))),
                expected_mean=float(expected_mean),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("AI inference fallback: %s", exc)
            return AIPrediction(reversion_probability=fallback_prob, expected_mean=fallback_mean)

    def _load_model(self):
        if torch is None or nn is None:
            return None
        model_path = str(self.config.ai_model_path or "").strip()
        if not model_path:
            return None
        p = Path(model_path)
        if not p.exists():
            logger.warning("AI model file not found: %s", model_path)
            return None
        try:
            model = _GRUForecaster(input_size=6, hidden_size=32)
            state = torch.load(str(p), map_location="cpu")
            model.load_state_dict(state)
            model.eval()
            logger.info("Loaded AI model: %s", model_path)
            return model
        except Exception as exc:  # pragma: no cover
            logger.warning("Unable to load AI model %s: %s", model_path, exc)
            return None

    def _heuristic_prob(
        self,
        rsi: float,
        bb_pctb: float,
        zscore: float,
        adx: float,
        stoch_k: float,
        stoch_d: float,
    ) -> float:
        score = 0.0
        score += max(0.0, (30.0 - rsi) / 30.0)
        score += max(0.0, (rsi - 70.0) / 30.0)
        score += max(0.0, abs(zscore) / 2.5)
        score += max(0.0, abs(bb_pctb - 0.5) * 2.0)
        score += max(0.0, (20.0 - adx) / 20.0)
        score += max(0.0, abs(stoch_k - stoch_d) / 30.0)
        return max(0.05, min(0.95, 0.25 + score / 5.0))

    def _refresh_pair_diagnostics(self, close_f: pd.Series) -> Dict[str, float]:
        now = int(self.market_data_provider.time())
        refresh_seconds = max(300, self.config.pairs_refresh_minutes * 60)
        if self._pairs_snapshot and now - self._last_pair_scan_ts < refresh_seconds:
            return self._pairs_snapshot

        candidates = [p.strip() for p in self.config.pairs_candidates_csv.split(",") if p.strip()]
        if not candidates:
            self._pairs_snapshot = {"pair": "n/a", "correlation": 0.0, "cointegrated": 0.0}
            self._last_pair_scan_ts = now
            return self._pairs_snapshot

        best = {"pair": "n/a", "correlation": 0.0, "cointegrated": 0.0}
        base_ret = close_f.pct_change().dropna()
        all_vectors = [base_ret.values]
        pair_rows: List[Tuple[str, float, float]] = []

        for pair in candidates:
            try:
                df = self.market_data_provider.get_candles_df(
                    connector_name=self.config.candles_connector,
                    trading_pair=pair,
                    interval=self.config.interval_slow,
                    max_records=self._slow_lb,
                )
                if df is None or df.empty:
                    continue
                close = df["close"].astype(float)
                ret = close.pct_change().dropna()
                joined = pd.concat([base_ret, ret], axis=1, join="inner").dropna()
                if len(joined) < 40:
                    continue
                corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
                coint_flag = 0.0
                if coint is not None:
                    try:
                        _t, pvalue, _ = coint(joined.iloc[:, 0], joined.iloc[:, 1])
                        coint_flag = 1.0 if pvalue <= self.config.coint_pvalue_threshold else 0.0
                    except Exception:
                        coint_flag = 0.0
                pair_rows.append((pair, corr, coint_flag))
                all_vectors.append(joined.iloc[:, 1].values)
            except Exception:
                continue

        if not pair_rows:
            self._pairs_snapshot = {"pair": "n/a", "correlation": 0.0, "cointegrated": 0.0}
            self._last_pair_scan_ts = now
            return self._pairs_snapshot

        if KMeans is not None and len(all_vectors) >= 3:
            try:
                min_len = min(len(v) for v in all_vectors)
                matrix = pd.DataFrame([v[-min_len:] for v in all_vectors]).fillna(0.0).values
                n_clusters = min(3, matrix.shape[0])
                _ = KMeans(n_clusters=n_clusters, random_state=7, n_init=10).fit(matrix)
            except Exception:
                pass

        for pair, corr, coint_flag in pair_rows:
            if corr >= self.config.pairs_corr_threshold and coint_flag > 0.5:
                best = {"pair": pair, "correlation": corr, "cointegrated": coint_flag}
                break
            if corr > best["correlation"]:
                best = {"pair": pair, "correlation": corr, "cointegrated": coint_flag}

        self._pairs_snapshot = best
        self._last_pair_scan_ts = now
        return best

    def _risk_gate(self, adx_val: float, stationarity_ok: bool) -> bool:
        if self.config.leverage > self.config.max_leverage:
            return False
        if adx_val > self.config.adx_breakout_threshold:
            return False
        if not stationarity_ok:
            return False
        return True

    def _adf_pvalue(self, close: pd.Series) -> float:
        if adfuller is None:
            return 0.5
        try:
            arr = close.astype(float).tail(max(self.config.zscore_length, 60)).values
            if len(arr) < 25:
                return 1.0
            _stat, pvalue, *_ = adfuller(arr)
            return float(pvalue)
        except Exception:
            return 1.0

    def _dynamic_grid_band(self, atr_pct: float, zscore: float) -> float:
        base = self.config.grid_band_min_pct + min(0.01, atr_pct * 0.5)
        z_adj = min(0.01, max(0.0, zscore - 1.0) * 0.0025)
        return max(self.config.grid_band_min_pct, min(self.config.grid_band_max_pct, base + z_adj))

    def _dynamic_grid_levels(self, atr_pct: float, stationarity_p: float) -> int:
        vol_factor = max(0.0, min(1.0, atr_pct / 0.02))
        st_factor = max(0.0, min(1.0, 1.0 - stationarity_p / max(self.config.adf_pvalue_threshold, 1e-6)))
        raw = self.config.grid_levels_min + int((self.config.grid_levels_max - self.config.grid_levels_min) * (0.6 * st_factor + 0.4 * vol_factor))
        return max(self.config.grid_levels_min, min(self.config.grid_levels_max, raw))

    def _dynamic_level_size(self, atr_pct: float, stationarity_p: float) -> float:
        st_score = max(0.0, min(1.0, 1.0 - stationarity_p))
        vol_score = max(0.0, min(1.0, atr_pct / 0.02))
        pct = self.config.level_size_min_pct + (self.config.level_size_max_pct - self.config.level_size_min_pct) * (0.7 * st_score + 0.3 * (1.0 - vol_score))
        return max(self.config.level_size_min_pct, min(self.config.level_size_max_pct, pct))

    def _kalman_last(self, close: pd.Series) -> float:
        estimate = float(close.iloc[0])
        p = 1.0
        q = max(1e-8, self.config.kalman_process_var)
        r = max(1e-8, self.config.kalman_measurement_var)
        for value in close.astype(float).values[1:]:
            p = p + q
            k = p / (p + r)
            estimate = estimate + k * (value - estimate)
            p = (1 - k) * p
        return float(estimate)

    def _bollinger_values(self, close: pd.Series) -> Tuple[float, float, float, float]:
        bb = ta.bbands(close, length=self.config.bb_length, std=self.config.bb_std)
        if bb is not None and not bb.empty:
            lower_col = next((c for c in bb.columns if c.startswith("BBL")), None)
            mid_col = next((c for c in bb.columns if c.startswith("BBM")), None)
            upper_col = next((c for c in bb.columns if c.startswith("BBU")), None)
            pctb_col = next((c for c in bb.columns if c.startswith("BBP")), None)
            lower = float(bb[lower_col].iloc[-1]) if lower_col else float(close.iloc[-1])
            mid = float(bb[mid_col].iloc[-1]) if mid_col else float(close.iloc[-1])
            upper = float(bb[upper_col].iloc[-1]) if upper_col else float(close.iloc[-1])
            pctb = float(bb[pctb_col].iloc[-1]) if pctb_col else 0.5
            return lower, mid, upper, pctb
        p = float(close.iloc[-1])
        return p, p, p, 0.5

    def _stochastic_values(self, high: pd.Series, low: pd.Series, close: pd.Series) -> Tuple[float, float]:
        stoch = ta.stoch(high, low, close, k=self.config.stoch_k, d=self.config.stoch_d, smooth_k=self.config.stoch_smooth_k)
        if stoch is not None and not stoch.empty:
            k_col = next((c for c in stoch.columns if c.startswith("STOCHk")), None)
            d_col = next((c for c in stoch.columns if c.startswith("STOCHd")), None)
            k_val = float(stoch[k_col].iloc[-1]) if k_col else 50.0
            d_val = float(stoch[d_col].iloc[-1]) if d_col else 50.0
            return k_val, d_val
        return 50.0, 50.0

    def _zscore(self, close: pd.Series) -> float:
        if len(close) < self.config.zscore_length + 2:
            return 0.0
        w = close.tail(self.config.zscore_length).astype(float)
        mu = float(w.mean())
        sd = float(w.std())
        if sd <= 1e-12:
            return 0.0
        return (float(w.iloc[-1]) - mu) / sd

    def _adx_value(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        adx_df = ta.adx(high, low, close, length=self.config.adx_length)
        if adx_df is not None and not adx_df.empty:
            col = next((c for c in adx_df.columns if c.startswith("ADX")), None)
            if col:
                return float(adx_df[col].iloc[-1])
        return 20.0

    def _adx_confirm(self, df_confirm: Optional[pd.DataFrame]) -> float:
        if df_confirm is None or df_confirm.empty:
            return 20.0
        high = df_confirm["high"].astype(float)
        low = df_confirm["low"].astype(float)
        close = df_confirm["close"].astype(float)
        return self._adx_value(high=high, low=low, close=close)

    def _last(self, series: Optional[pd.Series], fallback: float) -> float:
        if series is not None and not series.empty and pd.notna(series.iloc[-1]):
            return float(series.iloc[-1])
        return fallback

    def _utc_hour(self) -> int:
        try:
            return datetime.datetime.utcfromtimestamp(self.market_data_provider.time()).hour
        except Exception:
            return datetime.datetime.utcnow().hour
