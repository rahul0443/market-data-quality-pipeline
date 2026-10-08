"""Seeded fault injection: corrupt a clean feed at known places so detection can be scored."""

from __future__ import annotations

import numpy as np
import pandas as pd

FAULTS = (
    "duplicate_ts",
    "out_of_order",
    "missing_bar",
    "ohlc_inconsistent",
    "stale_repeat",
    "price_spike",
    "range_outlier",
    "null_or_nonpositive",
)


def inject(
    clean: pd.DataFrame,
    seed: int,
    per_fault: int = 4,
    spike_pct: float = 0.04,
    wick_pct: float = 0.03,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (corrupted_frame, truth) where truth has columns [fault, ts].

    Faults are placed on distinct bars at least 5 bars apart so they cannot mask each other.
    Value faults are applied first; ordering/duplicate/removal faults last, on the raw row order.
    """
    rng = np.random.default_rng(seed)
    df = clean.sort_values("ts").reset_index(drop=True).copy()
    n = len(df)

    slots = []
    candidates = list(range(80, n - 10))  # leave a warm-up for trailing statistics
    rng.shuffle(candidates)
    for pos in candidates:
        if all(abs(pos - s) >= 5 for s in slots):
            slots.append(pos)
        if len(slots) == per_fault * len(FAULTS):
            break
    if len(slots) < per_fault * len(FAULTS):
        raise ValueError("feed too short to place all faults")
    plan = {fault: slots[i * per_fault:(i + 1) * per_fault] for i, fault in enumerate(FAULTS)}

    truth = []

    def mark(fault: str, pos: int) -> None:
        truth.append((fault, df.loc[pos, "ts"]))

    for pos in plan["price_spike"]:
        df.loc[pos, "close"] *= 1 + spike_pct
        df.loc[pos, "high"] = max(df.loc[pos, "high"], df.loc[pos, "close"])
        mark("price_spike", pos)
    for pos in plan["range_outlier"]:
        df.loc[pos, "high"] *= 1 + wick_pct
        mark("range_outlier", pos)
    for pos in plan["ohlc_inconsistent"]:
        df.loc[pos, "high"] = min(df.loc[pos, "open"], df.loc[pos, "close"]) * 0.995
        mark("ohlc_inconsistent", pos)
    for pos in plan["null_or_nonpositive"]:
        df.loc[pos, "volume"] = -abs(df.loc[pos, "volume"])
        mark("null_or_nonpositive", pos)
    for pos in plan["stale_repeat"]:
        df.loc[pos, ["open", "high", "low", "close", "volume"]] = df.loc[pos - 1, ["open", "high", "low", "close", "volume"]].to_numpy()
        mark("stale_repeat", pos)

    missing_positions = set(plan["missing_bar"])
    for pos in plan["missing_bar"]:
        mark("missing_bar", pos)
    swap_positions = plan["out_of_order"]
    for pos in swap_positions:
        mark("out_of_order", pos)  # the earlier-timestamp row ends up second, so it is the one that goes backwards
    duplicate_positions = plan["duplicate_ts"]
    for pos in duplicate_positions:
        mark("duplicate_ts", pos)

    rows = df.to_dict("records")
    for pos in swap_positions:
        rows[pos], rows[pos + 1] = rows[pos + 1], rows[pos]
    out_rows = []
    for pos, row in enumerate(rows):
        if pos in missing_positions:
            continue
        out_rows.append(row)
        if pos in duplicate_positions:
            out_rows.append(dict(row))
    corrupted = pd.DataFrame(out_rows, columns=df.columns)
    return corrupted, pd.DataFrame(truth, columns=["fault", "ts"])
