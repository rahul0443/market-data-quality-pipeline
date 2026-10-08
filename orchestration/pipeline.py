"""Dagster asset graph: load feeds -> validate each venue -> reconcile across venues -> report.

Run the graph in-process:   python -m orchestration.pipeline
Browse it in the Dagster UI: dagster dev -f orchestration/pipeline.py
"""

from pathlib import Path

import pandas as pd
from dagster import AssetExecutionContext, Definitions, MaterializeResult, MetadataValue, asset, materialize

from mdq.report import real_data_report
from mdq.sources import load_snapshot
from mdq.validate import Config, reconcile, validate

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"
CFG = Config()


@asset
def venue_bars() -> dict:
    """Hourly bars from each venue (committed snapshot; `python -m mdq fetch` refreshes it)."""
    return load_snapshot(SAMPLE)


@asset
def validation_issues(context: AssetExecutionContext, venue_bars: dict) -> pd.DataFrame:
    """Rule violations across venues, one row per issue."""
    frames = []
    for venue, df in venue_bars.items():
        issues = validate(df, CFG)
        if len(issues):
            frames.append(issues.assign(venue=venue))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["rule", "severity", "ts", "detail", "venue"])
    context.add_output_metadata({"issues": len(out), "errors": int((out["severity"] == "error").sum())})
    return out


@asset
def reconciliation_flags(venue_bars: dict) -> pd.DataFrame:
    """Hours where one venue's close sits beyond tolerance from the cross-venue median."""
    return reconcile(venue_bars, CFG)


@asset
def validation_report(venue_bars: dict, validation_issues: pd.DataFrame, reconciliation_flags: pd.DataFrame) -> MaterializeResult:
    """Markdown report of the run."""
    text = real_data_report(venue_bars, CFG)
    return MaterializeResult(metadata={
        "issues": len(validation_issues),
        "reconciliation_flags": len(reconciliation_flags),
        "report": MetadataValue.md(text),
    })


defs = Definitions(assets=[venue_bars, validation_issues, reconciliation_flags, validation_report])


if __name__ == "__main__":
    result = materialize([venue_bars, validation_issues, reconciliation_flags, validation_report])
    print("success:", result.success)
