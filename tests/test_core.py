from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mdq.benchmark import reconcile_sensitivity, run_faults, summarize_faults
from mdq.inject import FAULTS, inject
from mdq.report import real_data_report
from mdq.sources import (
    drop_incomplete,
    load_snapshot,
    normalize_binance,
    normalize_coinbase,
    normalize_kraken,
)
from mdq.validate import reconcile, validate

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def make_feed(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50_000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0.0005, 0.002, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.0005, 0.002, n))
    ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(1, 5, n)})


def rules(issues: pd.DataFrame) -> set:
    return set(issues["rule"]) if len(issues) else set()


def test_clean_synthetic_feed_has_no_errors():
    issues = validate(make_feed())
    assert not (issues["severity"] == "error").any() if len(issues) else True


def test_duplicate_timestamp_flagged():
    df = make_feed()
    df = pd.concat([df, df.iloc[[50]]], ignore_index=True)
    issues = validate(df)
    assert "duplicate_ts" in rules(issues)


def test_out_of_order_flagged():
    df = make_feed()
    df.iloc[[60, 61]] = df.iloc[[61, 60]].to_numpy()
    assert "out_of_order" in rules(validate(df))


def test_ohlc_inconsistency_flagged():
    df = make_feed()
    df.loc[70, "high"] = df.loc[70, "low"] * 0.9
    assert "ohlc_inconsistent" in rules(validate(df))


def test_missing_bar_flagged_with_exact_timestamp():
    df = make_feed()
    gone = df.loc[80, "ts"]
    issues = validate(df.drop(index=80))
    assert list(issues.loc[issues["rule"] == "missing_bar", "ts"]) == [gone]


def test_stale_repeat_flagged():
    df = make_feed()
    df.loc[90, ["open", "high", "low", "close", "volume"]] = df.loc[89, ["open", "high", "low", "close", "volume"]].to_numpy()
    assert "stale_repeat" in rules(validate(df))


def test_negative_volume_and_null_flagged():
    df = make_feed()
    df.loc[40, "volume"] = -1.0
    df.loc[41, "close"] = np.nan
    issues = validate(df)
    assert set(issues.loc[issues["rule"] == "null_or_nonpositive", "ts"]) == {df.loc[40, "ts"], df.loc[41, "ts"]}


def test_reverting_spike_flagged_but_persistent_move_is_not():
    spike = make_feed()
    spike.loc[120, "close"] *= 1.05
    spike.loc[120, "high"] = max(spike.loc[120, "high"], spike.loc[120, "close"])
    assert "price_spike" in rules(validate(spike))

    # A genuine level shift that stays is a real move, not a bad tick.
    shift = make_feed()
    shift.loc[120:, ["open", "high", "low", "close"]] *= 1.05
    assert "price_spike" not in rules(validate(shift))


def test_reconcile_attributes_outlier_to_the_right_venue():
    base = make_feed()
    frames = {"a": base.copy(), "b": base.copy(), "c": base.copy()}
    frames["b"].loc[100, "close"] *= 1.01  # 100 bps
    flags = reconcile(frames)
    assert list(flags["venue"]) == ["b"] and list(flags["ts"]) == [base.loc[100, "ts"]]


def test_reconcile_needs_three_venues():
    base = make_feed()
    assert reconcile({"a": base, "b": base}).empty


def test_parsers_match_documented_payload_shapes():
    cb = normalize_coinbase([[1791421200, 83100, 83473.42, 83318.77, 83213.21, 74.1], [1791417600, 83160, 83392, 83275, 83327, 80.4]])
    assert list(cb.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert cb["ts"].is_monotonic_increasing and cb.loc[1, "open"] == 83318.77 and cb.loc[1, "low"] == 83100

    kr = normalize_kraken({"error": [], "result": {"XXBTZUSD": [[1788829200, "79287.0", "79441.3", "79237.9", "79411.9", "79324.1", "57.7", 2874]], "last": 1788829200}})
    assert kr.loc[0, "high"] == 79441.3 and kr.loc[0, "low"] == 79237.9

    bn = normalize_binance([[1791414000000, "83207.19", "83305.91", "83136.57", "83263.98", "0.87", 1791417599999, "72534.38", 80, "0.6", "50635.8", "0"]])
    assert bn.loc[0, "close"] == 83263.98 and bn.loc[0, "volume"] == 0.87


def test_incomplete_current_hour_is_dropped():
    df = make_feed(5)
    now = df["ts"].iloc[-1] + pd.Timedelta(minutes=30)  # last bar still in progress
    assert len(drop_incomplete(df, now)) == 4


def test_injection_is_reproducible_and_places_every_fault():
    clean = make_feed(400)
    a, truth_a = inject(clean, seed=3)
    b, _ = inject(clean, seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert set(truth_a["fault"]) == set(FAULTS)
    assert len(truth_a) == 4 * len(FAULTS)


@pytest.fixture(scope="module")
def real_frames():
    return load_snapshot(SAMPLE)


def test_real_snapshot_has_no_structural_errors(real_frames):
    for name, df in real_frames.items():
        issues = validate(df)
        errors = issues[issues["severity"] == "error"] if len(issues) else issues
        assert errors.empty, f"{name}: {errors.head()}"


def test_real_gap_in_binance_feed_is_found(real_frames):
    issues = validate(real_frames["binance_us"])
    missing = issues[issues["rule"] == "missing_bar"]
    assert len(missing) == 9
    assert missing["ts"].min() == pd.Timestamp("2026-08-31 04:00", tz="UTC")


def test_real_feeds_agree_within_tolerance(real_frames):
    assert reconcile(real_frames).empty


def test_detection_benchmark_meets_floor_on_real_feeds(real_frames):
    summary = summarize_faults(run_faults(real_frames, range(5))).set_index("fault")
    for structural in ("duplicate_ts", "out_of_order", "missing_bar", "ohlc_inconsistent", "stale_repeat", "null_or_nonpositive"):
        assert summary.loc[structural, "recall"] == 1.0, structural
    assert summary.loc["price_spike", "recall"] >= 0.95
    assert summary.loc["range_outlier", "recall"] >= 0.80


def test_reconciliation_catches_large_single_venue_shift(real_frames):
    out = reconcile_sensitivity(real_frames, range(6), magnitudes_bps=(50,)).iloc[0]
    assert out["recall"] == 1.0 and out["attributed_to_correct_venue"] == out["injected"]


def test_report_mentions_the_real_gap(real_frames):
    text = real_data_report(real_frames)
    assert "binance_us" in text and "9 consecutive missing hourly bars" in text
