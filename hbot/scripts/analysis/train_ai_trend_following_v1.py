from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ccxt
import pandas as pd
import pandas_ta as ta  # noqa: F401
from sklearn.ensemble import RandomForestRegressor


@dataclass
class TrainingArtifacts:
    lstm_model_path: Path
    rf_model_path: Path
    metrics_path: Path


def fetch_ohlcv_history(
    exchange_name: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    max_rows: int = 100_000,
    limit_per_call: int = 1000,
    sleep_seconds: float = 0.2,
) -> pd.DataFrame:
    exchange_cls = getattr(ccxt, exchange_name)
    exchange = exchange_cls({"enableRateLimit": True})
    rows: List[List[float]] = []
    cursor = since_ms

    while len(rows) < max_rows:
        batch = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=cursor, limit=limit_per_call)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit_per_call:
            break
        cursor = int(batch[-1][0]) + 1
        time.sleep(sleep_seconds)

    if not rows:
        raise RuntimeError("No OHLCV rows fetched.")

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_50"] = ta.ema(out["close"], length=50)
    out["ema_200"] = ta.ema(out["close"], length=200)
    macd = ta.macd(out["close"], fast=12, slow=26, signal=9)
    out["macd"] = macd[[c for c in macd.columns if c.startswith("MACD_")][0]] if macd is not None else None
    out["macd_signal"] = macd[[c for c in macd.columns if c.startswith("MACDs_")][0]] if macd is not None else None
    adx = ta.adx(out["high"], out["low"], out["close"], length=14)
    out["adx"] = adx[[c for c in adx.columns if c.startswith("ADX")][0]] if adx is not None else None
    out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["atr_pct"] = out["atr"] / out["close"]
    out["vol_ema_12"] = ta.ema(out["volume"], length=12)
    out["vol_ema_26"] = ta.ema(out["volume"], length=26)
    out["vol_osc"] = (out["vol_ema_12"] - out["vol_ema_26"]) / out["vol_ema_26"]

    st = ta.supertrend(out["high"], out["low"], out["close"], length=10, multiplier=3.0)
    if st is not None and not st.empty:
        d_col = [c for c in st.columns if c.startswith("SUPERTd_")][0]
        out["supertrend_dir"] = st[d_col]
    else:
        out["supertrend_dir"] = 0.0

    try:
        mesa = ta.mama(out["close"])
        if mesa is not None and not mesa.empty:
            m_col = [c for c in mesa.columns if c.lower().startswith("mama")][0]
            f_col = [c for c in mesa.columns if c.lower().startswith("fama")][0]
            out["mesa_delta"] = (mesa[m_col] - mesa[f_col]) / out["close"]
        else:
            out["mesa_delta"] = 0.0
    except Exception:
        out["mesa_delta"] = 0.0

    out["ret_1"] = out["close"].pct_change(1)
    out["ret_24"] = out["close"].pct_change(24)
    out["target_up"] = (out["close"].shift(-1) > out["close"]).astype(int)
    out["target_size"] = (
        1.0
        - (out["atr_pct"].clip(lower=0.0, upper=0.06) / 0.06) * 0.5
        - out["ret_24"].abs().clip(lower=0.0, upper=0.2) * 1.0
    ).clip(lower=0.5, upper=1.0)

    out = out.dropna().reset_index(drop=True)
    return out


def train_lstm_classifier(
    features: pd.DataFrame,
    feature_cols: List[str],
    target_col: str,
    epochs: int,
    lr: float,
    hidden_size: int = 128,
) -> Tuple[object, Dict[str, float]]:
    import torch
    import torch.nn as nn

    class LSTMClassifier(nn.Module):
        def __init__(self, input_size: int, hidden_dim: int = 128, num_layers: int = 2, dropout: float = 0.2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_dim,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout,
            )
            self.out = nn.Linear(hidden_dim, 1)

        def forward(self, x):
            x, _ = self.lstm(x)
            return self.out(x[:, -1, :])

    n = len(features)
    split = int(n * 0.8)
    train_df = features.iloc[:split]
    test_df = features.iloc[split:]

    x_train = torch.tensor(train_df[feature_cols].values, dtype=torch.float32).reshape(-1, 1, len(feature_cols))
    y_train = torch.tensor(train_df[target_col].values, dtype=torch.float32).reshape(-1, 1)
    x_test = torch.tensor(test_df[feature_cols].values, dtype=torch.float32).reshape(-1, 1, len(feature_cols))
    y_test = torch.tensor(test_df[target_col].values, dtype=torch.float32).reshape(-1, 1)

    model = LSTMClassifier(input_size=len(feature_cols), hidden_dim=hidden_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss()

    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        logits = model(x_train)
        loss = loss_fn(logits, y_train)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        train_prob = torch.sigmoid(model(x_train))
        test_prob = torch.sigmoid(model(x_test))
        train_pred = (train_prob >= 0.5).float()
        test_pred = (test_prob >= 0.5).float()
        train_acc = float((train_pred.eq(y_train)).float().mean().item())
        test_acc = float((test_pred.eq(y_test)).float().mean().item())

    metrics = {
        "train_accuracy": train_acc,
        "test_accuracy": test_acc,
        "test_rows": float(len(test_df)),
    }
    return model, metrics


def train_rf_position_sizer(features: pd.DataFrame, feature_cols: List[str], target_col: str) -> Tuple[RandomForestRegressor, Dict[str, float]]:
    n = len(features)
    split = int(n * 0.8)
    train_df = features.iloc[:split]
    test_df = features.iloc[split:]

    rf = RandomForestRegressor(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=20,
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(train_df[feature_cols], train_df[target_col])
    pred = rf.predict(test_df[feature_cols])
    mse = float(((pred - test_df[target_col].values) ** 2).mean())
    rmse = math.sqrt(mse)
    return rf, {"rf_rmse": rmse}


def save_artifacts(
    output_dir: Path,
    lstm_model: object,
    rf_model: RandomForestRegressor,
    metrics: Dict[str, float],
) -> TrainingArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    lstm_path = output_dir / "lstm_trend.pt"
    rf_path = output_dir / "rf_position_sizer.pkl"
    metrics_path = output_dir / "training_metrics.json"

    import torch

    scripted = torch.jit.script(lstm_model)
    scripted.save(str(lstm_path))
    with open(rf_path, "wb") as f:
        pickle.dump(rf_model, f)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return TrainingArtifacts(lstm_model_path=lstm_path, rf_model_path=rf_path, metrics_path=metrics_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train AI Trend Following V1 artifacts (LSTM + RF size model).")
    parser.add_argument("--exchange", default="binance", help="ccxt exchange id (default: binance)")
    parser.add_argument("--symbol", default="BTC/USDT", help="ccxt symbol (default: BTC/USDT)")
    parser.add_argument("--timeframe", default="1h", help="OHLCV timeframe (default: 1h)")
    parser.add_argument("--years", type=int, default=5, help="History years (default: 5)")
    parser.add_argument("--epochs", type=int, default=20, help="LSTM epochs (default: 20)")
    parser.add_argument("--lr", type=float, default=0.001, help="LSTM learning rate (default: 1e-3)")
    parser.add_argument(
        "--output-dir",
        default="hbot/data/models/ai_trend_following_v1",
        help="Directory to store model artifacts",
    )
    args = parser.parse_args()

    since_ms = int((time.time() - args.years * 365 * 24 * 3600) * 1000)
    df = fetch_ohlcv_history(
        exchange_name=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        since_ms=since_ms,
    )
    feat = build_feature_frame(df)

    feature_cols = [
        "ema_50",
        "ema_200",
        "macd",
        "macd_signal",
        "adx",
        "atr_pct",
        "vol_osc",
        "supertrend_dir",
        "mesa_delta",
        "ret_1",
        "ret_24",
    ]
    lstm_model, lstm_metrics = train_lstm_classifier(
        feat,
        feature_cols=feature_cols,
        target_col="target_up",
        epochs=args.epochs,
        lr=args.lr,
    )
    rf_model, rf_metrics = train_rf_position_sizer(
        feat,
        feature_cols=["atr_pct", "ret_24", "vol_osc", "adx", "ret_1"],
        target_col="target_size",
    )

    all_metrics = {
        "exchange": args.exchange,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "rows": float(len(feat)),
        **lstm_metrics,
        **rf_metrics,
    }
    artifacts = save_artifacts(
        output_dir=Path(args.output_dir),
        lstm_model=lstm_model,
        rf_model=rf_model,
        metrics=all_metrics,
    )
    print(f"Saved LSTM artifact: {artifacts.lstm_model_path}")
    print(f"Saved RF artifact:   {artifacts.rf_model_path}")
    print(f"Saved metrics:       {artifacts.metrics_path}")


if __name__ == "__main__":
    main()
