"""
FastAPI webhook bridge for external grid executors (3Commas/Pionex).

Run:
  uvicorn hbot.scripts.utils.grid_webhook_bridge:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="HBot Grid Webhook Bridge", version="1.0.0")


class GridInstruction(BaseModel):
    symbol: str
    side: str = Field(description="buy|sell")
    expected_mean: float
    grid_levels: int = Field(ge=1, le=100)
    grid_band_pct: float = Field(ge=0.001, le=0.10)
    per_level_size_pct: float = Field(ge=0.0001, le=0.05)
    leverage: int = Field(ge=1, le=5)
    meta: Optional[Dict[str, Any]] = None


def _target_config(target: str) -> Dict[str, str]:
    t = target.lower().strip()
    if t == "3commas":
        return {
            "url": os.getenv("THREECOMMAS_WEBHOOK_URL", ""),
            "token": os.getenv("THREECOMMAS_WEBHOOK_TOKEN", ""),
        }
    if t == "pionex":
        return {
            "url": os.getenv("PIONEX_WEBHOOK_URL", ""),
            "token": os.getenv("PIONEX_WEBHOOK_TOKEN", ""),
        }
    raise HTTPException(status_code=400, detail=f"Unsupported target: {target}")


def _forward(url: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not url:
        raise HTTPException(status_code=500, detail="Webhook URL is not configured.")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    if resp.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Target webhook failed: {resp.status_code} {resp.text[:160]}")
    return {"status": "ok", "target_status": resp.status_code}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/grid/{target}")
def send_grid(target: str, instruction: GridInstruction):
    cfg = _target_config(target)
    payload = {
        "type": "grid_instruction",
        "symbol": instruction.symbol,
        "side": instruction.side,
        "expected_mean": instruction.expected_mean,
        "grid_levels": instruction.grid_levels,
        "grid_band_pct": instruction.grid_band_pct,
        "per_level_size_pct": instruction.per_level_size_pct,
        "leverage": instruction.leverage,
        "meta": instruction.meta or {},
    }
    result = _forward(cfg["url"], cfg["token"], payload)
    return {"forwarded_to": target, **result}
