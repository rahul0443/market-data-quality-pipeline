# Validation report: real feeds

| venue | bars | errors | warnings |
|---|---:|---:|---:|
| coinbase | 349 | 0 | 0 |
| kraken | 720 | 0 | 4 |
| binance_us | 999 | 0 | 13 |

## Missing bars

- **binance_us**: 9 consecutive missing hourly bars, 2026-08-31 04:00 to 2026-08-31 12:00 UTC

## Volatility flags and cross-venue corroboration

A flag raised on several venues at the same hour is most likely a real market move, not bad data.

| hour (UTC) | rule | venues flagging | reading |
|---|---|---|---|
| 2026-09-11 12:00 | range_outlier | kraken, binance_us | corroborated, likely a real market move |
| 2026-09-11 13:00 | range_outlier | kraken, binance_us | corroborated, likely a real market move |
| 2026-09-18 13:00 | range_outlier | kraken, binance_us | corroborated, likely a real market move |
| 2026-09-21 08:00 | range_outlier | kraken, binance_us | corroborated, likely a real market move |

## Cross-venue reconciliation

349 hours present on all venues. Deviation of each venue's close from the cross-venue median, in basis points:

| venue | median | 99th pct (abs) | max (abs) |
|---|---:|---:|---:|
| coinbase | 0.00 | 1.95 | 2.69 |
| kraken | 0.00 | 1.83 | 2.50 |
| binance_us | 0.12 | 10.67 | 12.58 |

Hours beyond the 25 bps tolerance: **0**

