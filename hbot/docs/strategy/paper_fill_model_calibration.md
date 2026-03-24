# Paper Fill Model Calibration Analysis

**Date**: 2026-03-17
**Purpose**: Document current fill model parameters and identify calibration gaps against live exchange behavior

---

## 1. Current Fill Model Inventory

The Paper Engine v2 ships **10 fill model implementations** (`fill_models.py`), one **latency model** (`latency_model.py`), three **fee models** (`fee_models.py`), and one **adverse inference module** (`adverse_inference.py`). The production-grade models are:

### 1.1 QueuePositionFillModel (default)

**File**: `controllers/paper_engine_v2/fill_models.py` lines 91–331

Simulates maker queue priority and partial fills. Core logic:

- **Maker (passive) fills**: When market touches the order price (`is_touchable`), a random draw against `prob_fill_on_limit` determines whether the order fills at all (line 182). If the draw passes and optional queue-position tracking is enabled, the order must first work through `queue_ahead` depth before filling. Fill size is `min(remaining, depth_fill, remaining * partial_ratio)` where `depth_fill = reachable_depth * queue_participation * jitter`.
- **Taker (crossing) fills**: Consumes contra-side levels up to `depth_levels`, computing a VWAP. Applied slippage = `(slippage_bps + adverse_selection_bps) / 10000` with an optional 1-tick extra slippage at probability `prob_slippage`.
- **Queue delay**: Approximated as `queue_participation * 1500` ms (line 167, 330).

### 1.2 LatencyAwareFillModel (most realistic)

**File**: `controllers/paper_engine_v2/fill_models.py` lines 523–560

Extends `QueuePositionFillModel` with a depth participation cap: fill quantity is clamped to `top.size * depth_participation_pct` (default 10%). Adds a `post_fill_drift_window_ms` field (default 500 ms) for external drift tracking.

### 1.3 TopOfBookFillModel (smoke tests)

**File**: `controllers/paper_engine_v2/fill_models.py` lines 338–360

Instantly fills full remaining at best bid/ask. No partial fills, no slippage, no queue. **Smoke-test only** — unsuitable for PnL evaluation.

### 1.4 Nautilus-style preset models

| Model | File lines | Behavior |
|---|---|---|
| `BestPriceFillModel` | 367–368 | Alias for `TopOfBookFillModel` |
| `OneTickSlippageFillModel` | 371–389 | Full fill at best ± 1 tick |
| `TwoTierFillModel` | 392–421 | `tier1_size` at best, remainder at best ± 1 tick |
| `ThreeTierFillModel` | 424–454 | Three-tier depth with fixed tick offsets |
| `CompetitionAwareFillModel` | 457–473 | Fills `top.size * liquidity_factor` (30% default) |
| `SizeAwareFillModel` | 476–494 | Impact scales linearly with `order_qty / soft_clip_qty` |
| `MarketHoursAwareFillModel` | 497–516 | Reduces liquidity outside UTC 12:00–20:00 |

### 1.5 Latency Model

**File**: `controllers/paper_engine_v2/latency_model.py`

Models network + exchange processing latency with nanosecond precision:
- `base_latency_ns`: applied to all commands
- `insert_latency_ns`: additional delay for order insertion
- `cancel_latency_ns`: additional delay for cancellation

Orders wait in an inflight queue (`matching_engine.py` lines 97–98, 465–511) and can race with cancels.

### 1.6 Fee Models

**File**: `controllers/paper_engine_v2/fee_models.py`

| Model | Description |
|---|---|
| `MakerTakerFeeModel` | Instrument-spec rates (default: 0.1% / 0.1%) |
| `TieredFeeModel` | Reads from `config/fee_profiles.json` by venue + VIP tier |
| `FixedFeeModel` | Flat per-fill commission |

### 1.7 Adverse Selection / Inference Model

**File**: `controllers/paper_engine_v2/adverse_inference.py`

ML classifier (joblib) that predicts `p_adverse` per tick using features from the controller state (spread, regime, imbalance, edge metrics). Actions:
- `p_adverse > adverse_threshold_skip` (0.85): skip quoting (max 3 consecutive)
- `p_adverse > adverse_threshold_widen` (0.70): widen spread by `(1 + p_adverse * 0.5)`

---

## 2. Parameter Defaults Table

### 2.1 Fill Model Parameters (`QueuePositionConfig`)

| Parameter | Default | Description | Realistic range (BTC-USDT perps) |
|---|---|---|---|
| `queue_participation` | 0.35 | Fraction of visible depth our fill consumes | 0.05–0.50 |
| `min_partial_fill_ratio` | 0.15 | Minimum partial fill as fraction of remaining | 0.05–0.30 |
| `max_partial_fill_ratio` | 0.85 | Maximum partial fill as fraction of remaining | 0.50–1.00 |
| `slippage_bps` | 1.0 | Base slippage applied to taker fills (bps) | 0.3–3.0 |
| `adverse_selection_bps` | 1.5 | Additional adverse-selection cost on taker fills (bps) | 0.5–5.0 |
| `prob_fill_on_limit` | 0.40 | Probability of fill when market touches limit price | 0.15–0.70 |
| `prob_slippage` | 0.00 | Probability of 1-tick extra slippage per fill | 0.01–0.10 |
| `queue_jitter_pct` | 0.20 | ±% randomization on queue participation | 0.05–0.40 |
| `depth_levels` | 3 | Number of contra-side levels considered | 1–10 |
| `depth_decay` | 0.70 | Weight decay for farther levels | 0.30–0.95 |
| `queue_position_enabled` | false | Enable explicit queue-position tracking | true/false |
| `queue_ahead_ratio` | 0.50 | Initial fraction of visible depth ahead of us | 0.20–0.80 |
| `queue_trade_through_ratio` | 0.35 | Per-touch fraction of depth considered traded-through | 0.10–0.60 |
| `seed` | 7 | Deterministic RNG seed | any int |

### 2.2 LatencyAware Additions

| Parameter | Default | Description | Realistic range |
|---|---|---|---|
| `depth_participation_pct` | 0.10 | Cap fill to this % of visible top-of-book depth | 0.02–0.30 |
| `post_fill_drift_window_ms` | 500 | Window for measuring post-fill price drift | 100–2000 |

### 2.3 Latency Model

| Parameter | Default | Description | Realistic range |
|---|---|---|---|
| `base_latency_ns` | 0 (150 ms via config) | Base command latency | 50–300 ms |
| `insert_latency_ns` | 0 | Additional insert latency | 10–100 ms |
| `cancel_latency_ns` | 0 | Additional cancel latency | 10–150 ms |

Presets: `NO_LATENCY` (0), `FAST_LATENCY` (50 ms), `REALISTIC_LATENCY` (100+50+30 ms), `PAPER_DEFAULT_LATENCY` (150 ms).

### 2.4 Matching Engine

| Parameter | Default | Description | Realistic range |
|---|---|---|---|
| `latency_ms` | 150 | Min ms between fills on same order | 50–500 |
| `max_fills_per_order` | 8 | Max partial fills per order | 3–20 |
| `max_open_orders` | 50 | Per-instrument open order limit | 10–100 |
| `reject_crossed_maker` | true | Reject LIMIT_MAKER crossing spread | true (exchange behavior) |
| `prune_terminal_after_s` | 60 | Seconds to keep terminal orders in memory | 30–120 |
| `liquidity_consumption` | false | Track consumed depth per tick | true/false |
| `price_protection_points` | 0 | Fill price protection band (0=disabled) | 5–20 |
| `margin_model_type` | "leveraged" | Margin calculation model | "leveraged"/"standard" |

### 2.5 Fee Model

| Parameter | Default | Description | Realistic range |
|---|---|---|---|
| `fee_profile` | "vip0" | VIP tier from `fee_profiles.json` | depends on exchange tier |
| Fallback maker rate | 0.001 (10 bps) | When profile not found | Bitget VIP0: 0.02%/0.06% |
| Fallback taker rate | 0.001 (10 bps) | When profile not found | Bitget VIP0: 0.02%/0.06% |

### 2.6 Adverse Inference

| Parameter | Default | Description | Realistic range |
|---|---|---|---|
| `adverse_classifier_enabled` | false | Toggle adverse ML classifier | true/false |
| `adverse_classifier_model_path` | "" | Path to joblib model | N/A |
| `adverse_threshold_widen` | 0.70 | Spread-widen trigger threshold | 0.50–0.85 |
| `adverse_threshold_skip` | 0.85 | Skip-tick trigger threshold | 0.75–0.95 |

### 2.7 Realism Presets (`PaperEngineConfig`)

| Preset | `prob_fill_on_limit` | `slippage_bps` | `adverse_bps` | `queue_participation` | `insert_ms` | `cancel_ms` | `queue_enabled` | `liq_consumption` |
|---|---|---|---|---|---|---|---|---|
| **conservative** | 0.30 | 1.6 | 2.2 | 0.25 | 35 | 120 | yes | yes |
| **balanced** | 0.40 | 1.0 | 1.5 | 0.35 | 20 | 80 | yes | yes |
| **aggressive** | 0.75 | 0.4 | 0.8 | 0.60 | 5 | 30 | no | no |
| **custom** (default) | 0.40 | 1.0 | 1.5 | 0.35 | 0 | 0 | no | no |

---

## 3. Calibration Gaps

### 3.1 Queue Position Model

**What is NOT captured:**
1. **Time-priority within the queue**: Real exchanges use strict price-time priority (FIFO). The model uses a statistical `queue_ahead_ratio` rather than tracking actual arrival time relative to the order book. An order placed when the queue is thin gets the same `queue_ahead_ratio` as one placed into a deep queue.
2. **Queue depletion across multiple touches**: The `queue_trade_through_ratio` is a fixed fraction per touch. In reality, queue depletion depends on the actual trade volume at that price level, which varies by trade.
3. **Iceberg / hidden orders**: Real BTC-USDT books on Bitget have hidden liquidity. The model only sees visible book depth, so queue position estimates are systematically optimistic.
4. **Self-trade prevention (STP)**: Bitget enforces STP rules that can cancel one side of a self-cross. Not modeled.

**Parameters needing empirical calibration:**
- `prob_fill_on_limit`: The single most impactful parameter. Should be calibrated against historical "touch-to-fill" rates.
- `queue_ahead_ratio`: Depends on typical queue depth at the time of order placement.
- `queue_trade_through_ratio`: Should be derived from trade-through volume data at resting price levels.

**Data needed:**
- Historical order book snapshots (L2, 100ms+ resolution) with trade tapes for BTC-USDT on Bitget
- Own historical fills with timestamps and book state at fill time (from live trading or Bitget fill exports)
- Trade volume distribution at touch events (how much volume trades through a price level per touch)

**Impact if mis-calibrated:**
- **HIGH**: `prob_fill_on_limit` directly controls the fill rate. If too high, paper PnL is optimistic (fills that would never happen live). If too low, strategy appears worse than reality. This is the #1 source of paper-to-live PnL divergence for maker strategies.

### 3.2 Fill Probability / Partial Fill Model

**What is NOT captured:**
1. **Correlation between fill probability and market conditions**: `prob_fill_on_limit` is static. In reality, fill probability varies with volatility, spread width, and queue depth. A maker order during high-vol has very different fill characteristics than during low-vol.
2. **Fill size distribution**: Partial fill sizes are drawn uniformly from `[min_partial_fill_ratio, max_partial_fill_ratio]`. Real partial fill sizes follow exchange matching engine rules (match against incoming market orders of varying sizes), producing a different distribution.
3. **Fill clustering**: Real fills often cluster (multiple partial fills in quick succession as a large aggressor sweeps). The `latency_ms` minimum gap between fills (matching_engine.py line 55) is a flat throttle, not a model of fill clustering dynamics.

**Parameters needing empirical calibration:**
- `min_partial_fill_ratio` / `max_partial_fill_ratio`: Should be fitted to historical partial fill size distribution.
- `max_fills_per_order`: Currently 8; should match observed partial fill counts.

**Data needed:**
- Historical fill records with partial fill breakdowns (fill count, fill sizes per order)
- Conditional fill rates by volatility regime, spread width, and queue depth

**Impact if mis-calibrated:**
- **MEDIUM**: Partial fill sizing affects inventory accumulation patterns. Overly generous partial fills can mask inventory management issues.

### 3.3 Adverse Selection Model

**What is NOT captured:**
1. **Post-fill price drift**: The `adverse_selection_bps` is applied as a fixed cost to taker fills only (line 316). Maker fills do NOT incorporate adverse selection. In reality, maker fills are **more** subject to adverse selection — the market moved to your price because informed flow is hitting your level.
2. **Asymmetric adverse selection**: Adverse selection is worse on one side depending on trend. A bid fill during a downtrend has worse adverse drift than during an uptrend. The model uses a symmetric constant.
3. **Time-decay of adverse selection**: Post-fill drift is strongest in the first 1–5 seconds and decays. The `post_fill_drift_window_ms` (500ms) exists in `LatencyAwareConfig` but is only used for external metric tracking, not applied to fill prices.
4. **ML adverse inference coverage**: The `adverse_inference.py` classifier is a controller-level overlay that adjusts spreads, NOT a fill-model component. It prevents bad quotes but does not penalize fills that already occurred.

**Parameters needing empirical calibration:**
- `adverse_selection_bps`: Should be measured per-side, per-regime from historical fill-to-drift data.
- A new parameter is needed: **maker adverse selection bps** — currently zero for maker fills.

**Data needed:**
- Post-fill price trajectory: mid-price at fill time, +100ms, +500ms, +1s, +5s, +30s after each fill
- Conditional adverse drift by regime, side, and time-of-day
- Fill-edge EWMA (already tracked as `fill_edge_ewma_bps` in the controller)

**Impact if mis-calibrated:**
- **CRITICAL**: This is the primary source of paper PnL over-estimation. Paper maker fills at the limit price with zero adverse selection creates a systematic positive bias. Real maker fills on BTC-USDT perps typically experience 1–5 bps of adverse mid-price drift within 1 second.

### 3.4 Slippage Model

**What is NOT captured:**
1. **Market-impact as a function of order size relative to book depth**: The current model applies a fixed `slippage_bps` regardless of order size relative to available depth. `SizeAwareFillModel` exists but is not used in the default or realistic profiles.
2. **Slippage correlation with volatility**: During high-vol events, slippage is dramatically higher. The model uses a constant.
3. **Aggressive taker VWAP accuracy**: Taker fills compute VWAP across `depth_levels` (3 by default), but real L2 snapshots may have wider depth with different concentration patterns.

**Parameters needing empirical calibration:**
- `slippage_bps`: Should be measured from live taker fills vs. mid-price at submission time.
- `depth_levels`: Should match the typical number of levels consumed by our order sizes.

**Data needed:**
- Live taker fill price vs. mid-price at order submission
- Book depth snapshots at time of taker execution

**Impact if mis-calibrated:**
- **MEDIUM**: Primarily affects position-rebalance and stop-loss cost estimates. Less critical for maker-dominant strategies.

### 3.5 Latency Model

**What is NOT captured:**
1. **Latency distribution**: Real network latency follows a distribution (often log-normal with fat tails). The model uses a fixed value with no variance.
2. **Latency spikes**: Bitget API latency can spike during high-activity periods (>500ms). Not modeled.
3. **Cancel/fill race resolution**: The inflight queue models cancel races, but the race resolution is deterministic (first-in-wins) rather than probabilistic.
4. **Stale book latency**: The time between the real exchange state and the book snapshot reaching the paper engine is not modeled. In reality, our book snapshot is always slightly stale.

**Parameters needing empirical calibration:**
- `base_latency_ns`: Should match measured median API round-trip time to Bitget.
- Latency variance / P99 tail: Not currently parameterized — a gap.

**Data needed:**
- API round-trip time logs (order submission to acknowledgment) over multiple days
- Latency by time-of-day and market conditions

**Impact if mis-calibrated:**
- **LOW-MEDIUM**: Primarily affects cancel/replace race windows. A strategy that relies on rapid requoting is more sensitive. For slower maker strategies (5s+ quote lifetime), this is less critical.

### 3.6 Fee Model

**What is NOT captured:**
1. **Fee tier changes**: Real VIP tiers change monthly based on volume. The model uses a static profile.
2. **Fee promotions**: Bitget periodically runs fee discount campaigns. Not modeled.
3. **BGB fee discount**: Bitget offers a 20% fee discount when paying with BGB tokens. Not modeled.
4. **Funding rate fees**: Funding payments are modeled separately (`funding_simulator.py`), but interaction with fill-level PnL accounting may have gaps.

**Parameters needing calibration:**
- Verify `fee_profiles.json` matches current Bitget VIP0 rates (maker 0.02%, taker 0.06%).

**Data needed:**
- Current fee schedule from Bitget API or docs
- Historical fee payments from account statements to validate

**Impact if mis-calibrated:**
- **MEDIUM**: Fee errors directly affect net PnL. A 2 bps maker fee error on 100 fills/day × $50K notional = $10/day systematic bias.

---

## 4. Recommended Calibration Procedure

### 4.1 Data Collection Requirements

| Data Source | Format | Minimum History | Refresh Frequency |
|---|---|---|---|
| Bitget L2 order book snapshots | JSON/Parquet, 100ms resolution | 7 days | Weekly |
| Bitget trade tape (public trades) | CSV/Parquet, tick-level | 7 days | Weekly |
| Own fill records (from live or paper) | CSV from `fills_log_*.jsonl` | 30 days | Continuous |
| API latency logs | CSV with timestamps | 7 days | Weekly |
| Bitget fee schedule | Manual/API check | Current | Monthly |
| Post-fill mid-price trajectories | Computed from book + fills | 7 days | Weekly |

### 4.2 Calibration Methodology

#### Step 1: Fill Rate Calibration (`prob_fill_on_limit`)

1. From historical book snapshots + trade tape, identify all "touch events" where the best bid or ask reaches a given price level.
2. For each touch event, determine whether a resting order at that price would have filled based on trade-through volume.
3. Compute `empirical_fill_rate = count(filled_touches) / count(all_touches)`.
4. Set `prob_fill_on_limit = empirical_fill_rate`.
5. Validate by regime: compute separate fill rates for low-vol, high-vol, trending, and mean-reverting regimes.

#### Step 2: Queue Position Calibration

1. Using the trade tape, measure the volume traded at a price level between when a hypothetical order was placed and when it would have been reached in the queue.
2. Fit `queue_ahead_ratio` to the empirical distribution of "depth ahead at placement time / total visible depth."
3. Fit `queue_trade_through_ratio` to the empirical fraction of depth that clears per touch.

#### Step 3: Adverse Selection Calibration

1. For each historical fill, record the mid-price at fill time.
2. Compute the mid-price change at +100ms, +500ms, +1s, +5s, +30s after each fill.
3. **Maker fills**: Compute `adverse_drift_bps = (mid_after - mid_at_fill) / mid_at_fill * 10000`, signed by side.
4. **Taker fills**: Compute `taker_slippage_bps = (fill_price - mid_at_fill) / mid_at_fill * 10000`, signed by side.
5. Set `adverse_selection_bps` (and a new `maker_adverse_bps`) to the median adverse drift at the 1-second horizon.
6. Condition on regime for more accurate modeling.

#### Step 4: Partial Fill Sizing

1. From historical fill records, extract the distribution of `fill_qty / order_qty` for each partial fill.
2. Fit `min_partial_fill_ratio` and `max_partial_fill_ratio` to the 10th and 90th percentiles.
3. Verify `max_fills_per_order` against historical partial fill counts.

#### Step 5: Latency Calibration

1. From API latency logs, compute P50, P90, P99 of round-trip times.
2. Set `base_latency_ns` to P50.
3. Consider adding a latency variance parameter to capture P90/P99 behavior.

#### Step 6: Fee Verification

1. Cross-check `fee_profiles.json` against current Bitget fee schedule.
2. Validate against historical fee payments from account statements.

### 4.3 Validation Approach

1. **Replay validation**: Replay a 24-hour historical period through the calibrated paper engine. Compare:
   - Fill count (paper vs. hypothetical fills from book+tape)
   - Fill rate (fills per touch event)
   - PnL distribution shape (mean, std, skew)
2. **A/B comparison**: Run the same strategy with calibrated vs. default parameters. Compare strategy decision quality (not just PnL magnitude).
3. **Walk-forward check**: Calibrate on days 1–5, validate on days 6–7. Repeat with rolling windows. If parameters drift >20% between windows, the calibration is unstable and needs more data or a different model structure.

### 4.4 Recommended Refresh Frequency

| Parameter Group | Refresh Frequency | Trigger |
|---|---|---|
| `prob_fill_on_limit` | Weekly | If fill rate changes >15% |
| `queue_ahead_ratio`, `queue_trade_through_ratio` | Bi-weekly | If queue dynamics shift |
| `adverse_selection_bps` | Weekly | If drift patterns change |
| `slippage_bps` | Monthly | If market microstructure changes |
| Latency parameters | Monthly | After infrastructure changes |
| Fee profiles | Monthly | After VIP tier review |
| Adverse ML classifier | Monthly | After retraining |

---

## 5. Priority Ranking

### P1: Must calibrate before trusting paper PnL

| # | Task | Current Gap | Impact |
|---|---|---|---|
| 1 | **Maker adverse selection** | Zero adverse penalty on maker fills (`fill_models.py` line 280 — maker fills at `order.price` with no drift) | Paper PnL over-estimates by 1–5 bps per maker fill. For a strategy doing 50+ maker fills/day, this is the dominant source of paper-to-live PnL divergence. |
| 2 | **`prob_fill_on_limit` empirical calibration** | Default 0.40 is a guess (`config.py` line 29) | Wrong fill rate inflates or deflates both PnL and fill count. Strategy appears unrealistically profitable or unprofitable. |
| 3 | **Fee profile verification** | Fallback rate of 0.1% (10 bps) is 5× higher than Bitget VIP0 maker rate | If `fee_profiles.json` is missing or misconfigured, fees are wildly wrong. Verify the JSON matches current Bitget schedule. |

### P2: Should calibrate for accurate fill rate

| # | Task | Current Gap | Impact |
|---|---|---|---|
| 4 | **Regime-conditional fill probability** | `prob_fill_on_limit` is static across all market conditions | Fill rate accuracy varies ±30% across volatility regimes. Strategy appears robust in paper but fails in specific real regimes. |
| 5 | **Queue position model enablement** | `queue_position_enabled` defaults to `false` (`config.py` line 35) | Without queue simulation, every touch potentially fills. Enabling and calibrating this reduces phantom fills. |
| 6 | **Partial fill distribution** | Uniform draw between `[0.15, 0.85]` | Real partial fills are not uniformly distributed. Affects inventory build-up patterns and position management accuracy. |
| 7 | **Latency distribution modeling** | Fixed latency, no variance | Cancel/requote races are deterministic rather than probabilistic. Matters for strategies with tight requote windows. |

### P3: Nice to have for simulation realism

| # | Task | Current Gap | Impact |
|---|---|---|---|
| 8 | **Size-dependent market impact** | `SizeAwareFillModel` exists but is not used in default/balanced profiles | Only matters for larger clip sizes. Current bot1 sizes are small relative to book depth. |
| 9 | **Iceberg / hidden liquidity** | Not modeled | Queue position estimates are systematically optimistic. Minor impact for small orders. |
| 10 | **Time-of-day liquidity profile** | `MarketHoursAwareFillModel` exists but not used in production profile | BTC is 24/7 but liquidity varies. Minor impact for BTC, larger for altcoins. |
| 11 | **Latency spikes / tail events** | No tail-latency modeling | Rare but impactful for risk. Low priority for average PnL calibration. |
| 12 | **Self-trade prevention** | Not modeled | Only matters if bot sends opposing orders close in price, which the strategy should avoid anyway. |

---

## 6. Quick Reference: File Locations

| Component | File | Key Lines |
|---|---|---|
| Fill model protocol + decisions | `controllers/paper_engine_v2/fill_models.py` | 48–66 |
| QueuePositionConfig defaults | `controllers/paper_engine_v2/fill_models.py` | 73–88 |
| QueuePosition evaluate (maker path) | `controllers/paper_engine_v2/fill_models.py` | 136–203 |
| QueuePosition evaluate (taker path) | `controllers/paper_engine_v2/fill_models.py` | 287–331 |
| LatencyAware depth cap | `controllers/paper_engine_v2/fill_models.py` | 542–560 |
| Fill model factory | `controllers/paper_engine_v2/fill_models.py` | 567–618 |
| Matching engine config | `controllers/paper_engine_v2/matching_engine.py` | 53–63 |
| Matching engine fill loop | `controllers/paper_engine_v2/matching_engine.py` | 537–789 |
| Latency model + presets | `controllers/paper_engine_v2/latency_model.py` | 12–80 |
| Fee model protocol + impls | `controllers/paper_engine_v2/fee_models.py` | 27–143 |
| PaperEngineConfig + presets | `controllers/paper_engine_v2/config.py` | 14–116 |
| Adverse inference classifier | `controllers/paper_engine_v2/adverse_inference.py` | 87–145 |
