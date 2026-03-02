You are a principal quant strategist + execution engineer + risk manager designing a NEW crypto strategy to be implemented as a production-grade “semi-pro” bot.

## Hard requirements
- The strategy must be **novel relative to my repo**: do not reuse any existing strategy patterns I already have (EPP variants, simple EMA/RSI crossover, basic BB mean-reversion, basic grid, generic MM, etc.).
- It must be **implementable** with realistic exchange constraints (fees, slippage, maker/taker, min notional, tick/step size).
- It must be suitable for **semi-pro operations**: risk controls, monitoring, incident handling, and verification plan are mandatory.
- Prefer **free/open-source** tooling and practical engineering.
- It should be designed for crypto spot and/or perps (you must specify which is best and why).
- Assume I can run multiple bots; your strategy can be single-bot or multi-bot, but you must justify it.

## Inputs I will provide (use if present; otherwise make conservative assumptions)
- Exchange(s): Bitget
- Markets allowed: Both
- Pairs universe: Open
- Timeframes available: ALL
- My execution engine/framework constraints: Hummingbot
- My paper-trade logs schema: TBD
- Fee tier assumption: VIP0
- Risk budget: 2%É
- Operational constraints: look repo

## Your mission
Invent and fully specify ONE new strategy with potential for strong performance. You must be creative, but disciplined.

### 1) Strategy Concept (make it original)
- Give the strategy a name.
- Explain the edge hypothesis (why it could work in crypto).
- Explain what market regime it targets and which regimes it avoids.
- Explain why it is not a common “off-the-shelf” strategy.

### 2) Market & Instrument Choice
- Choose: spot / perps / both.
- Choose leverage rules (if perps) and when leverage is reduced to 1x.
- Define pair selection rules (liquidity, spread, volume, funding constraints, volatility bands).
- Define when to exclude a pair (news volatility proxy, spread spike, funding extreme, low depth).

### 3) Signals & Features (precise)
Define:
- inputs (candles, order book, trades, funding, open interest if available)
- core features and transformations (normalized by volatility when possible)
- signal rules with exact thresholds and conditions
- regime filters (trend strength, vol regime, spread/liquidity regime)
- entry/exit logic with state machine (flat → entering → in-position → de-risk → exit)
- re-entry rules and cooldowns

### 4) Execution Model (semi-pro quality)
Define:
- order types (limit/market), maker/taker rules and when taker is allowed
- quote placement logic (for limits), refresh cadence, cancel/replace rules
- partial fill handling
- timeouts / stale order handling
- slippage model assumptions and protection (max slippage bps)
- reconciliation loop (REST vs WS desync)
- idempotency (client order ids), retry with backoff, error cooldown

### 5) Risk Framework (mandatory)
Define hard limits:
- max position size
- max leverage and margin safety buffer
- max daily loss / max drawdown
- max open orders
- max order rate
- exposure caps across correlated assets
- stop logic (soft stop vs hard kill switch)
- circuit breakers (API errors, volatility spikes, spread spikes, funding spikes)
- “safe mode” rules (reduce size, maker-only, pause trading)

### 6) Portfolio / Multi-bot Integration (if relevant)
If your strategy benefits from multiple bots, define:
- bot roles (signal bot, execution bot, hedge bot, allocator)
- what data they share
- conflict rules (who wins if two bots want opposite positions)
- capital allocation and risk budgeting per bot

### 7) Validation & Verification Plan (do not skip)
Provide:
- backtest approach (including how to avoid lookahead/repaint)
- paper simulation approach (what assumptions are needed)
- live validation ladder (small-size live)
- KPIs to track (PnL, Sharpe proxy, win rate is not enough)
- execution KPIs (slippage, spread capture, maker/taker %, cancel ratio)
- risk KPIs (DD, exposure time, tail losses)
- acceptance gates (criteria to scale up)
- falsification tests (“if this happens, the edge hypothesis is wrong”)

### 8) Observability & Ops (semi-pro readiness)
Define:
- required logs/events schema (orders, fills, position snapshots, risk events)
- required metrics (at least 20) and alert thresholds
- dashboards (what panels)
- runbook for incidents (disconnect, stuck orders, desync, runaway exposure)
- deployment pattern (Docker + restart policy, version pinning, config management)
- rollback plan (revert config / revert code safely)

### 9) Implementation Blueprint (ready to build)
Provide:
- module structure (files/classes) suitable for {{FRAMEWORK}}
- pseudocode for main loop/state machine
- configuration schema (YAML/JSON) with sensible defaults + parameter ranges
- a “first MVP version” and “v2 improvements roadmap”

## Output format (strict)
Return in this structure:

1. Strategy Name + One-Line Thesis
2. Edge Hypothesis & Why It’s Original
3. Instruments & Pair Selection Rules
4. Regimes: Trade / Reduce / Pause
5. Signals & State Machine (detailed)
6. Execution Design (detailed)
7. Risk Framework (hard limits + circuit breakers)
8. Validation Plan (backtest → sim → live)
9. Observability & Ops Checklist
10. Implementation Blueprint (modules, configs, pseudocode)
11. MVP Build Plan (7 days) + Upgrade Plan (30 days)
12. Failure Modes (top 15) + Mitigations

## Extra rules
- Be realistic about fees/slippage. If the strategy only works with unrealistically perfect fills, reject it and propose an alternative.
- Avoid strategies that are basically “indicator salad”.
- Prefer strategies with a clear causal mechanism and measurable edge.
- Propose parameter ranges and explain sensitivity.