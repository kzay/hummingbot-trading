# ICT Test Fixtures

## btc_2000_1m.csv

2000 consecutive 1-minute BTC-USDT candles extracted from Bitget perpetual
historical data (bars 5000-7000 from the full dataset, covering approximately
2025-01-04 to 2025-01-05).

Columns: `timestamp_ms, open, high, low, close, volume`

## btc_2000_reference.json

Pinned reference output from `ICTState(ICTConfig())` processing the 2000-bar
fixture above. Used by `test_fixture_reference.py` to detect regressions.

Any detector logic change that alters event counts or final state must update
this file. Regenerate with:

```bash
PYTHONPATH=hbot python -c "
import csv, json
from decimal import Decimal
from controllers.common.ict.state import ICTState, ICTConfig
cfg = ICTConfig()
state = ICTState(cfg)
with open('hbot/tests/controllers/ict/fixtures/btc_2000_1m.csv') as f:
    for row in csv.DictReader(f):
        state.add_bar(Decimal(row['open']), Decimal(row['high']),
                      Decimal(row['low']), Decimal(row['close']),
                      Decimal(row['volume']))
# ... build ref dict and json.dump() ...
```

## Known divergences from smartmoneyconcepts v0.0.26

The `smartmoneyconcepts` library (PyPI) uses pandas-vectorized detection with
different defaults and swing lookback. Our incremental detectors may produce
different event counts for the same data. The reference here is self-consistent:
it pins *our* detector outputs, not the SMC library's.
