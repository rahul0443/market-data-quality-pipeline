# Data dictionary

## Normalized bar (`data/sample/<venue>.csv`, and the frame every rule consumes)

| column | type | meaning |
|---|---|---|
| `ts` | UTC timestamp | start of the hourly interval the bar covers |
| `open` | float | first trade price in the interval |
| `high` | float | highest trade price in the interval |
| `low` | float | lowest trade price in the interval |
| `close` | float | last trade price in the interval |
| `volume` | float | base-asset (BTC) volume traded in the interval |

Source mappings, because each venue orders the same fields differently:

| venue | endpoint | raw row layout | notes |
|---|---|---|---|
| Coinbase | `GET /products/BTC-USD/candles?granularity=3600` | `[time, low, high, open, close, volume]` | newest first |
| Kraken | `GET /0/public/OHLC?pair=XBTUSD&interval=60` | `[time, open, high, low, close, vwap, volume, count]` | last row is the in-progress hour |
| Binance US | `GET /api/v3/klines?symbol=BTCUSD&interval=1h&limit=1000` | `[open_time_ms, open, high, low, close, volume, ...]` | millisecond timestamps |

The newest bar from every venue is dropped when its interval has not finished at fetch time.

## Validation issue (`validate()` output)

| column | meaning |
|---|---|
| `rule` | one of the eight rule names in the README |
| `severity` | `error` (structurally invalid) or `warning` (needs review) |
| `ts` | the bar the issue is attached to (for `missing_bar`, the missing interval) |
| `detail` | short reason |

## Reconciliation flag (`reconcile()` output)

| column | meaning |
|---|---|
| `venue` | the venue whose close deviates from the cross-venue median |
| `ts` | the hour |
| `deviation_bps` | `10000 * (close - median) / median` |

## Benchmark outputs (`results/`)

| file | columns |
|---|---|
| `benchmark_faults.csv` | `fault`, `injected`, `caught`, `recall`, `precision` |
| `benchmark_spike_sensitivity.csv` | `spike_pct`, `injected`, `caught`, `recall` |
| `benchmark_reconcile.csv` | `shift_bps`, `injected`, `caught`, `recall`, `attributed_to_correct_venue` |

`recall` = caught / injected. `precision` = new flags landing on injected bars / all new flags, where a flag already present on the clean feed is not counted.
