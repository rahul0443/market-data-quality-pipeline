"""Markdown report for a validation run over real feeds."""

from __future__ import annotations

import pandas as pd

from mdq.validate import DEFAULT_CONFIG, Config, reconcile, validate


def _gaps(missing_ts: pd.Series, interval: pd.Timedelta) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    ts = sorted(pd.to_datetime(missing_ts))
    gaps = []
    for t in ts:
        if gaps and t - gaps[-1][1] == interval:
            gaps[-1] = (gaps[-1][0], t, gaps[-1][2] + 1)
        else:
            gaps.append((t, t, 1))
    return gaps


def real_data_report(frames: dict[str, pd.DataFrame], cfg: Config = DEFAULT_CONFIG) -> str:
    issues = {name: validate(df, cfg) for name, df in frames.items()}
    lines = ["# Validation report: real feeds", ""]
    lines += ["| venue | bars | errors | warnings |", "|---|---:|---:|---:|"]
    for name, df in frames.items():
        iss = issues[name]
        errors = int((iss["severity"] == "error").sum()) if len(iss) else 0
        warns = int((iss["severity"] == "warning").sum()) if len(iss) else 0
        lines.append(f"| {name} | {len(df)} | {errors} | {warns} |")

    lines += ["", "## Missing bars", ""]
    found = False
    for name, iss in issues.items():
        miss = iss[iss["rule"] == "missing_bar"] if len(iss) else iss
        for start, end, count in _gaps(miss["ts"], cfg.interval) if len(miss) else []:
            found = True
            lines.append(f"- **{name}**: {count} consecutive missing hourly bars, {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC")
    if not found:
        lines.append("- none")

    lines += ["", "## Volatility flags and cross-venue corroboration", "",
              "A flag raised on several venues at the same hour is most likely a real market move, not bad data.", ""]
    flagged: dict[tuple[str, pd.Timestamp], list[str]] = {}
    for name, iss in issues.items():
        for _, row in (iss[iss["rule"].isin(["price_spike", "range_outlier"])] if len(iss) else iss).iterrows():
            flagged.setdefault((row["rule"], row["ts"]), []).append(name)
    if flagged:
        lines += ["| hour (UTC) | rule | venues flagging | reading |", "|---|---|---|---|"]
        for (rule, ts), venues in sorted(flagged.items(), key=lambda kv: kv[0][1]):
            reading = "corroborated, likely a real market move" if len(venues) > 1 else "single venue, review as possible bad data"
            lines.append(f"| {ts:%Y-%m-%d %H:%M} | {rule} | {', '.join(venues)} | {reading} |")
    else:
        lines.append("- none")

    lines += ["", "## Cross-venue reconciliation", ""]
    closes = pd.concat({n: f.drop_duplicates("ts").set_index("ts")["close"] for n, f in frames.items()}, axis=1, sort=True).dropna()
    median = closes.median(axis=1)
    dev = 1e4 * closes.sub(median, axis=0).div(median, axis=0)
    lines += [f"{len(closes)} hours present on all venues. Deviation of each venue's close from the cross-venue median, in basis points:", "",
              "| venue | median | 99th pct (abs) | max (abs) |", "|---|---:|---:|---:|"]
    for venue in dev.columns:
        lines.append(f"| {venue} | {dev[venue].median():.2f} | {dev[venue].abs().quantile(0.99):.2f} | {dev[venue].abs().max():.2f} |")
    flags = reconcile(frames, cfg)
    lines += ["", f"Hours beyond the {cfg.recon_tol_bps:.0f} bps tolerance: **{len(flags)}**", ""]
    return "\n".join(lines)
