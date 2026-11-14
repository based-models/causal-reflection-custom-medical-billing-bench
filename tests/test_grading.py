"""Two-line exact match."""

from __future__ import annotations

from ncci_bench.grading import is_exact


def test_exact_match_ignores_outer_whitespace_only() -> None:
    gold = "column_2: pay\nmodifier: none"
    assert is_exact(gold, gold)
    assert is_exact("  column_2: pay\nmodifier: none\n", gold)
    assert not is_exact("column_2: pay\nmodifier: XS", gold)
    assert not is_exact("column_2: pay modifier: none", gold)
    assert not is_exact("column_2: Pay\nmodifier: none", gold)
    assert not is_exact("", gold)
