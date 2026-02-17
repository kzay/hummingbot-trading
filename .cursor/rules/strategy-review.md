---
description: Quantitative trading strategy review — market making, directional, portfolio
globs: "controllers/**/*.py,data/*/conf/controllers/*.yml,scripts/strategies/*.py"
alwaysApply: false
---

# Quantitative Strategy Review Standards

## I. Universal Quant Discipline

**Edge quantification**: Every strategy must have a defined expected value per trade:
  E[PnL] = P(win) × avg_win − P(loss) × avg_loss − fees − slippage
  If you cannot estimate this number, you are gambling, not trading.

**Statistical significance**: No signal goes live without:
  - Minimum 500 trades in backtest (300 for low-frequency)
  - Sharpe ≥ 1.5 after costs (≥ 2.0 preferred for crypto volatility)
  - Out-of-sample validation on ≥ 30% of data
  - Profit factor > 1.5 (gross_profit / gross_loss)

**Overfitting detection**: More parameters = more risk of fitting noise. Heuristic from López de Prado: require at least 10–20 backtest trades per tunable parameter. Our controller has ~15 params → minimum 150–300 trades in backtest before trusting results. Cross-validate with walk-forward or combinatorial purged CV.

**Regime conditioning**: Every strategy implicitly assumes a market regime. Make it explicit:
  - Mean reversion → ranging/oscillating markets (Hurst exponent H < 0.5)
  - Trend following → trending markets (H > 0.5)
  - Market making → liquid, mean-reverting microstructure with stable volatility
  Compute the Hurst exponent on your pair before choosing a strategy type.

**Position sizing — Kelly criterion**:
  f* = (p × b − q) / b
  where p = win rate, q = 1−p, b = avg_win/avg_loss.
  (Source: Kelly, 1956; derivation via max E[ln(wealth)])
  Use fractional Kelly (0.25×) in practice. Full Kelly maximizes geometric growth but with extreme drawdowns (~50% of the time underwater).

## II. Market Making — Microstructure

**Avellaneda-Stoikov framework** (2008, "High-frequency trading in a limit order book"):
  The optimal total bid-ask spread is:
    spread* = γσ²(T−t) + (2/γ) × ln(1 + γ/k)
  The reservation (fair) price given inventory q is:
    r = s − q × γ × σ² × (T−t)
  where s = mid price, γ = risk aversion, σ = volatility, T−t = remaining horizon, k = order arrival intensity, q = inventory.
  Key insight: spread widens with σ² and narrows with k (order flow competition). The reservation price shifts linearly with inventory — this is the correct way to skew, not RSI.

**Guéant-Lehalle-Fernandez-Tapia extension** (2012, "Dealing with the inventory risk"):
  Refines A-S with closed-form approximations using intensity function A×exp(−k×δ) for order arrivals. Decomposes optimal quotes into half-spread + inventory skew terms (c1, c2 coefficients). Use this for production implementations where A-S assumptions are too strong.

**Adverse selection**: Filled limit orders carry negative information — you got filled because the market moved through your price. Expected adverse selection cost scales as σ×√Δt, where Δt = time between quote updates. On BTC with σ_daily ≈ 3% and Δt = 300s: σ_5min = 0.03/√288 ≈ 0.177%, adverse selection ≈ 0.5 × 0.177% ≈ 0.088%. This alone can exceed narrow spreads. Reducing Δt (faster refresh) is the primary lever to reduce adverse selection.

**Minimum profitable spread**:
  S_min > 2 × fee_maker + adverse_selection_cost + inventory_carrying_cost
  On Bitget (maker 0.02%): S_min > 0.04% + 0.088% + ~0.02% ≈ 0.15%
  Any spread below this has negative expected value on a round-trip basis.

**Queue position**: CEX FIFO matching means fill probability depends on queue depth. Placing at best bid = back of queue. Improving by 1 tick = front of queue but tighter spread. This is an empirical tradeoff — model it from fill data.

**Revenue optimization**: Wider spreads → higher edge per fill but lower fill probability. Optimal spread maximizes: fill_rate(S) × (S − total_cost). This must be estimated empirically for your pair/exchange.

## III. Directional Trading — Signal Theory

**RSI is a filter, not a predictor**: RSI(14) on 1m candles is a 14-bar momentum oscillator normalized to [0,100]. It is:
  - Lagging by construction (smoothed ratio of past gains/losses)
  - Non-predictive in trending regimes (stays oversold for days in downtrends)
  - Useful as a regime classifier: RSI 30–70 = ranging, outside = trending
  Never use RSI as a standalone entry signal. Combine with trend filter (price vs 50/200 EMA), volume confirmation, and volatility regime.

**Mean reversion half-life**: For an AR(1) process x_t = φ·x_{t-1} + ε:
  Half-life = −ln(2) / ln(φ)
  If half-life > your time_limit, the position will hit the time exit before reverting. Estimate φ by OLS regression of Δx on x_{t-1}. BTC 1-minute microstructure typically shows half-lives of 5–30 minutes (highly regime-dependent — verify on your data).

**Crypto momentum factor**: Liu, Tsyvinski & Wu (2019, "Common Risk Factors in Cryptocurrency") document statistically significant cross-sectional momentum in crypto. The earlier Liu & Tsyvinski (2018/2021, "Risks and Returns of Cryptocurrency", RFS) establish time-series momentum as a predictor. Momentum is one of three identified crypto factors (market, size, momentum). Combine with volatility scaling for risk-adjusted implementation.

**Signal decay**: Every signal has an information half-life. If the signal source updates every T minutes, effective alpha decays well before the next update. LLM sentiment (even if valid) queried every 10 min is stale for most of its life. Match query frequency to signal decay rate.

**Exit management**: Practitioner consensus (Van Tharp et al. — note: not peer-reviewed academic finding, but widely observed in live trading) holds that exit rules contribute more to P&L than entries. Prioritize:
  1. Trailing stop (lock in profits, let winners run)
  2. Volatility-scaled stop: SL = k × ATR (wider in high vol, tighter in low vol)
  3. Time-decay exit (signal was wrong if no move within expected horizon)

## IV. Portfolio / Rebalancing — Quantitative Framework

**Rebalancing premium** (Fernholz, 2002, Stochastic Portfolio Theory):
  Excess growth rate γ* = (1/2) × [Σ_i(w_i × σ_i²) − σ_portfolio²]
  i.e., half the difference between the weighted-average individual variance and the portfolio variance.
  The premium exists when assets have similar expected returns, high individual volatility, and imperfect correlation. It is a mathematical consequence of diversification + rebalancing, not a risk premium.

**When rebalancing fails**: Premium disappears when:
  - One asset dominates (outlier winner — rebalancing sells the winner)
  - Correlation → 1 (no diversification, σ_portfolio² → Σ w_i σ_i², so γ* → 0)
  - Transaction costs > premium captured per rebalance cycle
  - Regime shifts from oscillating to persistent trending

**Optimal rebalancing frequency**: Tradeoff: more frequent = more premium captured, but higher transaction costs. On crypto with 0.06% taker fee per trade: threshold-based rebalancing (rebalance when weight drifts > X% from target) dominates calendar-based. Estimate breakeven threshold from: premium_per_rebalance > N_assets × 2 × fee.

**Long-short rebalancing alpha** (from Quantpedia paper in repo): Long rebalanced equal-weight index + short market-cap benchmark isolates rebalancing premium. Reported best Sharpe at 70% short weight (Sharpe ≈ 2.9 in the 2018–2021 sample). Caution: single sample period, no out-of-sample validation, requires margin and borrowing costs not modeled.

## V. Risk Management — Non-Negotiable

**Value at Risk**: For position sizing under normal assumptions — BTC daily σ ≈ 3%, VaR(95%) ≈ 1.645 × 3% ≈ 4.9%. If max acceptable loss = 2% of capital → max BTC position ≈ 2%/4.9% ≈ 40% of capital. Note: this understates tail risk (see below).

**Correlation risk**: Major altcoins typically show ρ > 0.6 with BTC in normal markets, spiking to ρ > 0.9 in crashes (correlation asymmetry). A "diversified" portfolio of 5 major altcoins behaves as roughly 1–1.5× leveraged BTC in stress scenarios. Crypto is effectively a one-factor market.

**Liquidity risk**: On Bitget BTC-USDT spot, visible top-of-book depth varies by time of day and conditions (estimate $50–300K at best bid/ask during active hours). If your order size > 5% of visible depth, you ARE the market. Size accordingly.

**Fat tails**: Crypto returns are leptokurtic (excess kurtosis >> 0). Normal-distribution VaR understates tail risk by 2–5× at the 99% level. Use empirical/historical VaR, not parametric. Flash crashes can gap through stop-losses — a 1.5% stop on BTC can realize as 3–8% in a liquidation cascade (no fills between).

## VI. Implementation Checkpoints (V2 Framework)

- MM controller: `update_processed_data()` sets `reference_price` (Decimal) + `spread_multiplier` (Decimal)
- Directional controller: `update_processed_data()` sets `signal` (-1/0/+1) in `processed_data`
- Use `pandas_ta` for indicators. Don't rewrite RSI/ATR/MACD.
- `PositionExecutor` handles triple barrier natively — TP, SL, time_limit, trailing_stop
- `executor_refresh_time`: MM = 15–60s, Directional = 60–300s
- Hot-reloadable fields: those with `"is_updatable": True` in Pydantic schema
- Test with `total_amount_quote: 10` on real connector before scaling (paper trade is broken in V2)
