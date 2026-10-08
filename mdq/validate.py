"""Rule-based validation for OHLCV bars. Every rule reports issues; none silently fixes data."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ISSUE_COLUMNS = ["rule", "severity", "ts", "detail"]

RULES = (
    "null_or_nonpositive",
    "duplicate_ts",
    "out_of_order",
    "ohlc_inconsistent",
    "missing_bar",
    "stale_repeat",
    "price_spike",
    "range_outlier",
)


@dataclass(frozen=True)
class Config:
    interval: pd.Timedelta = field(default_factory=lambda: pd.Timedelta(hours=1))
    window: int = 72  # trailing bars used for robust return and range statistics
    min_periods: int = 24
    spike_z: float = 8.0  # robust z-score of a log return
    reversion_frac: float = 0.6  # next bar must give back at least this share of a spike
    range_z: float = 10.0  # robust z-score of (high - low) / close
    recon_tol_bps: float = 25.0  # cross-venue close deviation tolerance


DEFAULT_CONFIG = Config()


def _issues(rule: str, severity: str, ts, detail) -> pd.DataFrame:
    ts = pd.Series(ts)
    if ts.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)
    detail = detail if isinstance(detail, (list, pd.Series, np.ndarray)) else [detail] * len(ts)
    return pd.DataFrame({"rule": rule, "severity": severity, "ts": ts.to_numpy(), "detail": list(detail)})


def _robust_z(series: pd.Series, cfg: Config) -> pd.Series:
    """Robust z-score against the *trailing* median and MAD, so a bar never scores itself."""
    prior = series.shift(1)
    med = prior.rolling(cfg.window, min_periods=cfg.min_periods).median()
    mad = (prior - med).abs().rolling(cfg.window, min_periods=cfg.min_periods).median() * 1.4826
    return (series - med) / mad.clip(lower=1e-9)


def validate(df: pd.DataFrame, cfg: Config = DEFAULT_CONFIG) -> pd.DataFrame:
    """Run all rules on one source's bars (columns: ts, open, high, low, close, volume)."""
    out = []
    ohlcv = ["open", "high", "low", "close", "volume"]

    bad = df[df[ohlcv].isna().any(axis=1) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1) | (df["volume"] < 0)]
    out.append(_issues("null_or_nonpositive", "error", bad["ts"], "null, non-positive price, or negative volume"))

    dup = df.loc[df["ts"].duplicated(keep=False), "ts"].drop_duplicates()
    out.append(_issues("duplicate_ts", "error", dup, "timestamp appears more than once"))

    backwards = df.loc[df["ts"].diff() < pd.Timedelta(0), "ts"]
    out.append(_issues("out_of_order", "error", backwards, "timestamp earlier than the row before it"))

    # Remaining rules need a canonical series: sorted by time, first occurrence kept.
    c = df.sort_values("ts", kind="stable").drop_duplicates("ts").reset_index(drop=True)
    c = c[(c[ohlcv].notna().all(axis=1)) & (c[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    if len(c) < 3:
        return pd.concat(out, ignore_index=True)

    broken = c[(c["high"] < c[["open", "close"]].max(axis=1)) | (c["low"] > c[["open", "close"]].min(axis=1)) | (c["high"] < c["low"])]
    out.append(_issues("ohlc_inconsistent", "error", broken["ts"], "high/low do not bound open and close"))

    grid = pd.date_range(c["ts"].min(), c["ts"].max(), freq=cfg.interval)
    out.append(_issues("missing_bar", "warning", grid.difference(pd.DatetimeIndex(c["ts"])), "no bar for this interval"))

    repeat = (c[ohlcv] == c[ohlcv].shift(1)).all(axis=1)
    out.append(_issues("stale_repeat", "warning", c.loc[repeat, "ts"], "bar identical to the previous bar in all fields"))

    ret = np.log(c["close"]).diff()
    z = _robust_z(ret, cfg)
    nxt = ret.shift(-1)
    reverted = (np.sign(nxt) == -np.sign(ret)) & (nxt.abs() >= cfg.reversion_frac * ret.abs())
    spike = (z.abs() > cfg.spike_z) & reverted
    out.append(_issues("price_spike", "warning", c.loc[spike, "ts"], "large return that reverses on the next bar"))

    rng = (c["high"] - c["low"]) / c["close"]
    wide = _robust_z(rng, cfg) > cfg.range_z
    out.append(_issues("range_outlier", "warning", c.loc[wide, "ts"], "bar range far above trailing norm"))

    return pd.concat([o for o in out if not o.empty], ignore_index=True) if any(not o.empty for o in out) else pd.DataFrame(columns=ISSUE_COLUMNS)


def reconcile(frames: dict[str, pd.DataFrame], cfg: Config = DEFAULT_CONFIG) -> pd.DataFrame:
    """Compare each venue's close with the cross-venue median and attribute outliers to a venue."""
    closes = pd.concat({n: f.drop_duplicates("ts").set_index("ts")["close"] for n, f in frames.items()}, axis=1, sort=True).dropna()
    if closes.shape[1] < 3 or closes.empty:
        return pd.DataFrame(columns=["venue", "ts", "deviation_bps"])
    median = closes.median(axis=1)
    dev = 1e4 * closes.sub(median, axis=0).div(median, axis=0)
    flagged = dev.abs() > cfg.recon_tol_bps
    rows = [(venue, ts, dev.loc[ts, venue]) for venue in dev.columns for ts in dev.index[flagged[venue]]]
    return pd.DataFrame(rows, columns=["venue", "ts", "deviation_bps"])
