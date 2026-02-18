"""
Train GRU model for AI Mean Reversion Grid V1.

Input CSV requirements:
  timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except Exception as exc:  # pragma: no cover
    raise ImportError("PyTorch is required for this trainer.") from exc


class GRUForecaster(nn.Module):
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
        return self.head(final)


def _make_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    rsi = ta.rsi(close, length=14).fillna(50.0)
    bb = ta.bbands(close, length=20, std=2.0)
    bbp_col = next((c for c in bb.columns if c.startswith("BBP")), None)
    bb_pctb = bb[bbp_col].fillna(0.5) if bbp_col else pd.Series(0.5, index=df.index)
    adx_df = ta.adx(high, low, close, length=14)
    adx_col = next((c for c in adx_df.columns if c.startswith("ADX")), None)
    adx = adx_df[adx_col].fillna(20.0) if adx_col else pd.Series(20.0, index=df.index)
    stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    stoch_k_col = next((c for c in stoch.columns if c.startswith("STOCHk")), None)
    stoch_k = stoch[stoch_k_col].fillna(50.0) if stoch_k_col else pd.Series(50.0, index=df.index)

    z_len = 40
    rolling_mu = close.rolling(z_len).mean()
    rolling_sd = close.rolling(z_len).std().replace(0.0, np.nan)
    zscore = ((close - rolling_mu) / rolling_sd).fillna(0.0)
    mean_distance = ((close - rolling_mu.fillna(close)) / close.replace(0.0, 1.0)).fillna(0.0)

    out = pd.DataFrame({
        "close": close,
        "rsi": rsi,
        "bb_pctb": bb_pctb,
        "zscore": zscore,
        "adx": adx,
        "stoch_k": stoch_k,
        "mean_distance": mean_distance,
    }).dropna()
    return out


def _build_dataset(features: pd.DataFrame, seq_len: int = 64, horizon: int = 8) -> Tuple[np.ndarray, np.ndarray]:
    x_rows = []
    y_rows = []
    values = features[["rsi", "bb_pctb", "zscore", "adx", "stoch_k", "mean_distance"]].values.astype(np.float32)
    close = features["close"].values.astype(np.float32)

    for i in range(seq_len, len(features) - horizon):
        x = values[i - seq_len:i]
        current = close[i]
        future_window = close[i + 1:i + 1 + horizon]
        future_mean = np.mean(future_window)
        revert_prob = 1.0 if abs((current - future_mean) / max(current, 1e-8)) > 0.0015 else 0.0
        mean_shift = (current - future_mean) / max(current, 1e-8)
        x_rows.append(x)
        y_rows.append([revert_prob, mean_shift])

    return np.array(x_rows, dtype=np.float32), np.array(y_rows, dtype=np.float32)


def train(input_csv: Path, output_model: Path, epochs: int = 20, batch_size: int = 64, lr: float = 1e-3):
    df = pd.read_csv(input_csv)
    features = _make_features(df)
    x, y = _build_dataset(features)
    if len(x) < 100:
        raise ValueError("Not enough rows after feature engineering to train model.")

    split = int(len(x) * 0.8)
    x_train, x_val = x[:split], x[split:]
    y_train, y_val = y[:split], y[split:]

    train_ds = TensorDataset(torch.tensor(x_train), torch.tensor(y_train))
    val_ds = TensorDataset(torch.tensor(x_val), torch.tensor(y_val))
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = GRUForecaster(input_size=6, hidden_size=32)
    optimizer = torch.optim.RMSprop(model.parameters(), lr=lr)
    mse = nn.MSELoss()
    bce = nn.BCEWithLogitsLoss()

    best_val = float("inf")
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for xb, yb in train_dl:
            pred = model(xb)
            loss = bce(pred[:, 0], yb[:, 0]) + mse(torch.tanh(pred[:, 1]), yb[:, 1])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_dl:
                pred = model(xb)
                loss = bce(pred[:, 0], yb[:, 0]) + mse(torch.tanh(pred[:, 1]), yb[:, 1])
                val_loss += float(loss.item())

        train_loss /= max(1, len(train_dl))
        val_loss /= max(1, len(val_dl))
        print(f"epoch={epoch:02d} train_loss={train_loss:.5f} val_loss={val_loss:.5f}")
        if val_loss < best_val:
            best_val = val_loss
            output_model.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), output_model)

    print(f"saved_best_model={output_model}")


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-model", default=Path("hbot/models/ai_mean_reversion_gru_v1.pt"), type=Path)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    return parser.parse_args()


if __name__ == "__main__":
    args = _args()
    train(
        input_csv=args.input_csv,
        output_model=args.output_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )
