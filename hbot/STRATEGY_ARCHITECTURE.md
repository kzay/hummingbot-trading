# Strategy Architecture

This repository uses Hummingbot V2 with a three-layer strategy architecture:

1. **Controller code** (`controllers/**/*.py`)
2. **Controller config** (`data/bot1/conf/controllers/*.yml`)
3. **Script config** (`data/bot1/conf/scripts/*.yml`)

The runtime command ties these layers together:

```text
start --script v2_with_controllers.py --conf <script_config>.yml
```

`v2_with_controllers.py` reads `controllers_config` from the script config and loads the referenced controller config(s), then instantiates the Python controller class by `controller_name`.

## Current Registry (Bot 1)

| Strategy | Controller Code | Controller Config | Script Config (Live) | Script Config (Paper) |
|---|---|---|---|---|
| AI Trend Following V1 | `controllers/directional_trading/ai_trend_following_v1.py` | `data/bot1/conf/controllers/ai_trend_following_v1_1.yml` | `data/bot1/conf/scripts/v2_ai_trend_following_v1.yml` | `data/bot1/conf/scripts/v2_ai_trend_following_v1_paper.yml` |
| Directional MAX/MIN V1 | `controllers/directional_trading/directional_max_min_v1.py` | `data/bot1/conf/controllers/directional_max_min_v1_1.yml` | `data/bot1/conf/scripts/v2_directional_max_min.yml` | `data/bot1/conf/scripts/v2_directional_max_min_paper.yml` |
| Systematic Alpha V1 | `controllers/directional_trading/systematic_alpha_v1.py` | `data/bot1/conf/controllers/systematic_alpha_v1_1.yml` | `data/bot1/conf/scripts/v2_systematic_alpha.yml` | `data/bot1/conf/scripts/v2_systematic_alpha_paper.yml` |
| Systematic Alpha V2 | `controllers/directional_trading/systematic_alpha_v2.py` | `data/bot1/conf/controllers/systematic_alpha_v2_1.yml` | `data/bot1/conf/scripts/v2_systematic_alpha_v2.yml` | `data/bot1/conf/scripts/v2_systematic_alpha_v2_paper.yml` |
| PMM RSI LLM | `controllers/market_making/pmm_rsi_llm.py` | `data/bot1/conf/controllers/pmm_rsi_llm_1.yml` | `data/bot1/conf/scripts/v2_pmm_rsi_llm.yml` | `data/bot1/conf/scripts/v2_pmm_rsi_llm_paper.yml` |
| PMM Avellaneda V2 | `controllers/market_making/pmm_avellaneda_v2.py` | `data/bot1/conf/controllers/pmm_avellaneda_v2_1.yml` | `data/bot1/conf/scripts/v2_pmm_avellaneda_v2.yml` | `data/bot1/conf/scripts/v2_pmm_avellaneda_v2_paper.yml` |

## Compose Design Choices

- Controller directories are mounted read-only:
  - `../controllers/market_making -> /home/hummingbot/controllers/market_making`
  - `../controllers/directional_trading -> /home/hummingbot/controllers/directional_trading`
- Built-in script path `/home/hummingbot/scripts` is **not overridden**. This preserves built-in scripts such as `v2_with_controllers.py`.
- Bot-specific custom scripts are mounted to `/home/hummingbot/custom_scripts`.

## Naming Conventions

- Controller file: `<strategy_name>_vN.py`
- Controller config:
  - live: `<strategy_name>_vN_1.yml`
  - paper: `<strategy_name>_vN_paper.yml`
- Script config:
  - live: `v2_<strategy_name>_vN.yml`
  - paper: `v2_<strategy_name>_vN_paper.yml`

## Run Commands

Baseline paper:

```text
start --script v2_with_controllers.py --conf v2_directional_max_min_paper.yml
```

Candidate paper:

```text
start --script v2_with_controllers.py --conf v2_systematic_alpha_v2_paper.yml
```

AI trend following paper:

```text
start --script v2_with_controllers.py --conf v2_ai_trend_following_v1_paper.yml
```
