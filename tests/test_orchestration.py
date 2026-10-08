import pytest

dagster = pytest.importorskip("dagster")

from orchestration.pipeline import reconciliation_flags, validation_issues, validation_report, venue_bars


def test_asset_graph_materializes_end_to_end():
    result = dagster.materialize([venue_bars, validation_issues, reconciliation_flags, validation_report])
    assert result.success
    issues = result.output_for_node("validation_issues")
    assert (issues["rule"] == "missing_bar").sum() == 9  # the real gap in the Binance US feed
    assert (issues["severity"] == "error").sum() == 0
    assert result.output_for_node("reconciliation_flags").empty
