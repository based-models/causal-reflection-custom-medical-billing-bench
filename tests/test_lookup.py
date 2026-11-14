"""lookup_edit returns the row on position 1 only."""

from __future__ import annotations

import json

from ncci_bench.lookup import lookup_result, result_json, row_leaked
from ncci_bench.tasks import load_tasks


def _pair(position: int, edit_type: str | None = None):
    for item in load_tasks():
        if int(item.meta["position"]) != position:
            continue
        if edit_type is not None and item.meta["edit_type"] != edit_type:
            continue
        return item
    raise AssertionError("missing item")


def test_position_1_returns_the_pinned_row() -> None:
    item = _pair(1, "deleted")
    payload = lookup_result(
        item,
        {
            "column_1": item.meta["column_1"],
            "column_2": item.meta["column_2"],
            "date_of_service": "2026-10-15",
        },
    )
    assert payload["deletion_date"] == "2026-10-01"
    assert payload["effective_date"] is None
    assert payload["modifier_indicator"] == item.meta["modifier_indicator"]
    assert payload["rationale"] == ""
    for key in ("outcome", "status", "ok", "is_error", "available"):
        assert key not in payload
    assert row_leaked(result_json(payload), item) is False


def test_later_positions_and_mismatches_hide_the_row() -> None:
    item = _pair(1, "hard_bundle")
    later = _pair(4, "hard_bundle")
    assert later.session_key == item.session_key
    args = {
        "column_1": item.meta["column_1"],
        "column_2": item.meta["column_2"],
        "date_of_service": "20261015",
    }
    hidden = lookup_result(later, args)
    assert hidden == {"available": False}
    encoded = result_json(hidden)
    assert row_leaked(encoded, later) is False
    assert item.meta["column_1"] not in encoded
    assert "2026-10-01" not in encoded
    wrong_pair = lookup_result(item, {**args, "column_2": "00000"})
    assert wrong_pair == {"available": False}
    wrong_date = lookup_result(item, {**args, "date_of_service": "2026-10-01"})
    assert wrong_date == {"available": False}
    compact = lookup_result(item, json.dumps(args))
    assert compact["column_1"] == item.meta["column_1"]
    assert compact["effective_date"] == "2026-10-01"
    assert compact["deletion_date"] is None
