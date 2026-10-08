"""Score the validators against injected faults with known ground truth."""

from __future__ import annotations

import numpy as np
import pandas as pd

from mdq.inject import FAULTS, inject
from mdq.validate import DEFAULT_CONFIG, Config, reconcile, validate


def _flag_set(issues: pd.DataFrame, rule: str) -> set:
    return set(issues.loc[issues["rule"] == rule, "ts"]) if len(issues) else set()


def run_faults(
    frames: dict[str, pd.DataFrame],
    seeds: range,
    cfg: Config = DEFAULT_CONFIG,
    spike_pct: float = 0.04,
) -> pd.DataFrame:
    """One row per (source, seed, fault): how many injected faults the matching rule caught.

    Precision is measured only on *new* flags: anything the rule already raised on the clean
    feed (for example a real gap or a real volatility spike) is excluded from both sides.
    """
    rows = []
    for source, clean in frames.items():
        baseline = validate(clean, cfg)
        for seed in seeds:
            corrupted, truth = inject(clean, seed, spike_pct=spike_pct)
            issues = validate(corrupted, cfg)
            truth_all = set(truth["ts"])
            for fault in FAULTS:
                injected = set(truth.loc[truth["fault"] == fault, "ts"])
                flagged = _flag_set(issues, fault)
                new_flags = flagged - _flag_set(baseline, fault)
                rows.append({
                    "source": source,
                    "seed": seed,
                    "fault": fault,
                    "injected": len(injected),
                    "caught": len(injected & flagged),
                    "new_flags": len(new_flags),
                    "new_flags_on_injected_bars": len(new_flags & truth_all),
                })
    return pd.DataFrame(rows)


def summarize_faults(results: pd.DataFrame) -> pd.DataFrame:
    g = results.groupby("fault", sort=False).sum(numeric_only=True)
    out = pd.DataFrame({
        "injected": g["injected"],
        "caught": g["caught"],
        "recall": (g["caught"] / g["injected"]).round(3),
        "precision": (g["new_flags_on_injected_bars"] / g["new_flags"].replace(0, np.nan)).round(3),
    })
    return out.reset_index()


def spike_sensitivity(frames: dict[str, pd.DataFrame], seeds: range, magnitudes=(0.01, 0.02, 0.03, 0.04, 0.06, 0.08)) -> pd.DataFrame:
    rows = []
    for pct in magnitudes:
        res = run_faults(frames, seeds, spike_pct=pct)
        spikes = res[res["fault"] == "price_spike"]
        rows.append({"spike_pct": pct, "injected": int(spikes["injected"].sum()), "caught": int(spikes["caught"].sum()),
                     "recall": round(spikes["caught"].sum() / spikes["injected"].sum(), 3)})
    return pd.DataFrame(rows)


def reconcile_sensitivity(frames: dict[str, pd.DataFrame], seeds: range, magnitudes_bps=(10, 20, 30, 50, 100), per_run: int = 5, cfg: Config = DEFAULT_CONFIG) -> pd.DataFrame:
    """Shift one venue's close by a known amount at random hours; check the right venue is flagged."""
    overlap = None
    for f in frames.values():
        idx = pd.DatetimeIndex(f["ts"])
        overlap = idx if overlap is None else overlap.intersection(idx)
    overlap = overlap.sort_values()
    rows = []
    venues = list(frames)
    for bps in magnitudes_bps:
        caught = attributed = injected = 0
        for seed in seeds:
            rng = np.random.default_rng(seed)
            venue = venues[seed % len(venues)]
            hours = pd.DatetimeIndex(rng.choice(overlap, size=per_run, replace=False))
            mutated = {n: f.copy() for n, f in frames.items()}
            mask = mutated[venue]["ts"].isin(hours)
            mutated[venue].loc[mask, "close"] *= 1 + bps / 1e4
            flags = reconcile(mutated, cfg)
            injected += per_run
            hit = flags[flags["ts"].isin(hours)]
            caught += hit["ts"].nunique()
            attributed += int((hit["venue"] == venue).sum())
        rows.append({"shift_bps": bps, "injected": injected, "caught": caught,
                     "recall": round(caught / injected, 3),
                     "attributed_to_correct_venue": attributed})
    return pd.DataFrame(rows)
