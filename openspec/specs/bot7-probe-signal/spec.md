## MODIFIED Requirements

### Requirement: Probe signal requires primary signal confirmation

The probe entry path (`probe_long`, `probe_short`) SHALL require a primary signal (`absorption_long`/`delta_trap_long` for long, `absorption_short`/`delta_trap_short` for short) to be `True`. Secondary signal (depth imbalance) alone MUST NOT activate a probe. Secondary signal may contribute to signal scoring but cannot independently gate a probe entry.

The previous behaviour — where `long_probe = ... and (primary_long OR secondary_long)` — is replaced with:

```
long_probe  = probe_enabled and regime_active and not trade_stale
              and touch_lower and rsi <= rsi_probe_buy_threshold
              and primary_long

short_probe = probe_enabled and regime_active and not trade_stale
              and touch_upper and rsi >= rsi_probe_sell_threshold
              and primary_short
```

Depth imbalance (`secondary_long`, `secondary_short`) MUST continue to be used in signal-score computation (adds +1 to signal_components) but MUST NOT appear in the probe gate condition.

#### Scenario: Probe fires when primary signal is present

- **WHEN** `touch_lower` is True, `rsi <= rsi_probe_buy_threshold`, `regime_active` is True, `absorption_long` is True (primary), and depth imbalance >= threshold (secondary)
- **THEN** `probe_mode = True`, `side = "buy"`, `reason = "probe_long"`

#### Scenario: Probe does NOT fire on depth imbalance alone

- **WHEN** `touch_lower` is True, `rsi <= rsi_probe_buy_threshold`, depth imbalance >= threshold, but `absorption_long = False` and `delta_trap_long = False`
- **THEN** `side = "off"`, probe does not activate

#### Scenario: Secondary signal still improves signal score

- **WHEN** probe fires with both primary and secondary signals present
- **THEN** `signal_score` is higher than if only primary were present (secondary adds 1 to signal_components numerator)

#### Scenario: Full signal (not probe) still fires with only primary signal

- **WHEN** `rsi <= rsi_buy_threshold` (full threshold) and `primary_long = True` and all other gates pass
- **THEN** `probe_mode = False`, `side = "buy"`, `reason = "mean_reversion_long"` — secondary signal does not affect full signal activation
