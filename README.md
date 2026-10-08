# market-data-quality-pipeline

Validation, anomaly detection, and cross-venue reconciliation for market data feeds, **scored against injected faults with known ground truth** so the detection rates are measured, not claimed.

It pulls hourly BTC-USD bars from three public exchange APIs (Coinbase, Kraken, Binance US; no API keys), runs eight validation rules on each feed, reconciles the venues against each other, and runs as a Dagster asset graph.

## Quick start

```bash
pip install -r requirements-dev.txt
python -m mdq fetch        # refresh the committed snapshot from the three exchange APIs
python -m mdq validate     # writes results/real_data_report.md
python -m mdq benchmark    # fault-injection benchmark, writes results/benchmark_*.csv
pytest                     # 20 tests (the Dagster test is skipped if dagster is not installed)
python -m orchestration.pipeline   # run the asset graph in-process
```

## What it checks

Every rule reports issues. Nothing is silently fixed or filled, because fabricated prices hide what actually happened.

| rule | flags | severity |
|---|---|---|
| `null_or_nonpositive` | nulls, non-positive prices, negative volume | error |
| `duplicate_ts` | a timestamp that appears more than once | error |
| `out_of_order` | a timestamp earlier than the row before it | error |
| `ohlc_inconsistent` | high/low that do not bound open and close | error |
| `missing_bar` | an interval with no bar | warning |
| `stale_repeat` | a bar identical to the previous bar in every field | warning |
| `price_spike` | a large log return (robust z > 8) that **reverses on the next bar** | warning |
| `range_outlier` | a bar range far above the trailing norm (robust z > 10) | warning |

Cross-venue reconciliation compares each venue's close with the median across venues and attributes any deviation beyond 25 bps to the venue that moved, so a bad feed can be traced to its source.

## Results on the real feeds

Snapshot fetched 2026-10-08 UTC: Coinbase 349 bars, Kraken 720, Binance US 999. Full output in [`results/real_data_report.md`](results/real_data_report.md).

- **A real gap in a live feed:** Binance US is missing 9 consecutive hourly bars (2026-08-31 04:00 to 12:00 UTC). The other two venues have no gaps.
- **No structural errors** (duplicates, ordering, OHLC, nulls) on any feed.
- **Four volatility flags** (`range_outlier`), each raised on both Kraken and Binance US at the same hour. Corroboration across venues means they are most likely real market moves, not bad data, and the report labels them that way.
- **Venues agree closely:** across 349 shared hours, closes sit within 2.7 bps of the cross-venue median for Coinbase and Kraken and within 12.6 bps for Binance US, so nothing exceeds the 25 bps tolerance.

## Fault-injection benchmark

Clean real bars are corrupted at known places (seeded, 4 faults of each type per run, at least 5 bars apart), and each rule is scored against the ground truth. 20 seeds x 3 feeds = 240 injected faults per type.

| fault | injected | caught | recall | precision |
|---|---:|---:|---:|---:|
| duplicate timestamp | 240 | 240 | 1.000 | 1.000 |
| out-of-order row | 240 | 240 | 1.000 | 1.000 |
| missing bar | 240 | 240 | 1.000 | 1.000 |
| OHLC inconsistent | 240 | 240 | 1.000 | 1.000 |
| stale repeat | 240 | 240 | 1.000 | 1.000 |
| negative volume | 240 | 240 | 1.000 | 1.000 |
| price spike (+4%, reverts) | 240 | 239 | 0.996 | 0.992 |
| phantom wick (+3% high) | 240 | 211 | 0.879 | 0.998 |

Precision counts only *new* flags, so a real gap or real volatility spike already present in the clean feed is not scored against the rule.

**Where detection stops working**, which matters more than the headline numbers:

| injected spike | recall |
|---|---:|
| 1% | 0.038 |
| 2% | 0.579 |
| 3% | 0.962 |
| 4% and above | 0.996 or higher |

A 1% move on a feed whose typical hourly move is about 0.22% is statistically unremarkable for this rule, so it is mostly missed.

| single-venue shift in close | recall | attributed to the correct venue |
|---|---:|---:|
| 10 bps | 0.00 | 0 |
| 20 bps | 0.04 | 4 |
| 30 bps | 0.93 | 93 |
| 50 bps and above | 1.00 | 100 |

Reconciliation cannot see a shift smaller than the tolerance by design (25 bps).

## Orchestration

[`orchestration/pipeline.py`](orchestration/pipeline.py) defines a four-asset Dagster graph: `venue_bars` -> `validation_issues` and `reconciliation_flags` -> `validation_report`. A test materializes it end to end. Browse it with `dagster dev -f orchestration/pipeline.py`.

## Design decisions

- **Flag, never fix.** Gaps are reported, not forward-filled.
- **Trailing robust statistics.** Spike and range scores use the median and MAD of the *previous* 72 bars, so a bar never scores itself and one outlier cannot inflate its own threshold.
- **Spikes must revert.** A large return that persists is a level shift (a real move); only a return that reverses on the next bar looks like a bad tick. A test covers both cases.
- **Drop the in-progress bar.** Exchanges return the current hour as the newest bar; it is not final.
- **Consensus reconciliation.** With three venues the median identifies which one is wrong, not just that they disagree.

## Limitations

- **Crypto, not equities.** Free keyless feeds are crypto, which trades 24/7. So there are no holiday calendars, session boundaries, corporate actions, symbology changes, or survivorship handling. These matter for equity feeds and are not implemented.
- **The faults are mine.** Structural faults are well defined, so 100% recall is expected; it shows the rules work as designed, not that they would catch every real vendor failure. The spike and reconciliation sweeps are the more informative numbers.
- **Thresholds were chosen after looking at this snapshot.** The clean-feed false-positive picture (zero errors, four corroborated volatility warnings) is therefore likely optimistic for new data.
- **Small sample:** three feeds, at most six weeks of hourly bars.
- **Single-venue `range_outlier` flags are review prompts,** not errors.
- Not production software: no retries, alerting, or storage layer.

## Layout

```
mdq/            sources, validate, inject, benchmark, report, CLI
orchestration/  Dagster asset graph
tests/          20 tests, including a floor on benchmark detection rates
data/sample/    committed snapshot of the three feeds
results/        generated report and benchmark CSVs
docs/           data dictionary
```
