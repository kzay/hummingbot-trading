---
description: Core project context for Hummingbot V2 trading infrastructure
alwaysApply: true
---

# Project Context

Refer to `.cursor/context.md` for full project documentation. Key rules:

- This is a **Hummingbot V2** project (version 2.12.0) using Docker Compose
- All infrastructure lives under `hbot/`
- Exchange: **Bitget** (spot + perp, same API keys for both)
- Strategy framework: V2 controller pattern (`MarketMakingControllerBase`)
- Custom controller: `controllers/market_making/pmm_rsi_llm.py`
- Hummingbot stderr goes to `data/bot1/logs/errors.log`, NOT docker logs
- Bind mounts REPLACE container directories — local dirs must have all needed files
- Never commit `env/.env` or `data/*/conf/connectors/` — they contain real secrets
- `data/*/scripts/` contains built-in scripts copied from the image (gitignored)
