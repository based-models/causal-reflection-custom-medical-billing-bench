"""Headline is the later-claim paired delta."""

from __future__ import annotations

from ncci_bench.report import render_markdown, summarize


def _row(arm: str, item: str, position: int, exact: bool, edit_type: str = "deleted") -> dict:
    return {
        "arm": arm,
        "item_id": item,
        "position": position,
        "edit_type": edit_type,
        "exact": exact,
        "tool_called": True,
        "later_row_leak": 0,
        "usage": {"cost_usd": 0.01},
        "error": None,
    }


def test_headline_is_positions_2_through_5() -> None:
    records = []
    for position, base, causal in ((1, False, False), (2, False, True), (3, False, True), (4, True, True), (5, False, False)):
        records.append(_row("glm-baseline", f"c{position}", position, base))
        records.append(_row("glm-causal", f"c{position}", position, causal))
    records.append(_row("glm-causal", "leak", 4, True, "hard_bundle") | {"later_row_leak": 2})
    summary = summarize(records)
    headline = summary["headline_later"]
    assert headline["n"] == 4
    assert headline["baseline"] == 0.25
    assert headline["causal"] == 0.75
    assert headline["delta"] == 0.5
    assert summary["position_1"]["n"] == 1
    assert summary["position_1"]["delta"] == 0
    assert summary["later_row_leaks"] == 2
    text = render_markdown(summary)
    assert "positions 2-5" in text
    assert "Later-claim lookup payloads that contained a row: 2." in text
    assert "hard_bundle" in text
