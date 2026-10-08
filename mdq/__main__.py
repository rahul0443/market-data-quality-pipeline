"""Command line: python -m mdq fetch | validate | benchmark"""

from __future__ import annotations

import argparse
from pathlib import Path

from mdq.benchmark import reconcile_sensitivity, run_faults, spike_sensitivity, summarize_faults
from mdq.report import real_data_report
from mdq.sources import fetch_all, load_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"
RESULTS = ROOT / "results"


def main() -> None:
    parser = argparse.ArgumentParser(prog="mdq")
    parser.add_argument("command", choices=["fetch", "validate", "benchmark"])
    parser.add_argument("--seeds", type=int, default=20, help="number of injection seeds for the benchmark")
    args = parser.parse_args()

    if args.command == "fetch":
        frames, fetched_at = fetch_all()
        save_snapshot(frames, SAMPLE, fetched_at)
        print({name: len(df) for name, df in frames.items()}, "saved to", SAMPLE)
        return

    frames = load_snapshot(SAMPLE)
    RESULTS.mkdir(exist_ok=True)
    if args.command == "validate":
        (RESULTS / "real_data_report.md").write_text(real_data_report(frames) + "\n")
        print("wrote", RESULTS / "real_data_report.md")
        return

    seeds = range(args.seeds)
    summary = summarize_faults(run_faults(frames, seeds))
    summary.to_csv(RESULTS / "benchmark_faults.csv", index=False)
    spike_sensitivity(frames, seeds).to_csv(RESULTS / "benchmark_spike_sensitivity.csv", index=False)
    reconcile_sensitivity(frames, seeds).to_csv(RESULTS / "benchmark_reconcile.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
