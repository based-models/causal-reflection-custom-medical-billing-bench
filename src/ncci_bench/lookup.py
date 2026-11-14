"""Tool result for lookup_edit.

Position 1 returns the pinned row when the arguments name that pair and the
claim's date of service. Every other call returns {"available": false} and
none of the row fields. The result has no outcome, status, or ok key, so the
medical pack does not store it.
"""

from __future__ import annotations

import json
from typing import Any

from ncci_bench.protocol import Item

_DOS_FORMS = {
    "2026-10-15": "2026-10-15",
    "20261015": "2026-10-15",
    "10/15/2026": "2026-10-15",
    "10-15-2026": "2026-10-15",
}

def unavailable() -> dict[str, bool]:
    return {"available": False}


def parse_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _matches(item: Item, arguments: dict[str, Any]) -> bool:
    column_1 = str(arguments.get("column_1") or "").strip()
    column_2 = str(arguments.get("column_2") or "").strip()
    supplied = str(arguments.get("date_of_service") or "").strip()
    date = _DOS_FORMS.get(supplied)
    return (
        column_1 == str(item.meta["column_1"])
        and column_2 == str(item.meta["column_2"])
        and date == str(item.meta["date_of_service"])
    )


def lookup_result(item: Item, arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_arguments(arguments)
    position = int(item.meta["position"])
    if position != 1 or not _matches(item, parsed):
        return unavailable()
    return {
        "column_1": item.meta["column_1"],
        "column_2": item.meta["column_2"],
        "effective_date": item.meta["effective_date"],
        "deletion_date": item.meta["deletion_date"],
        "modifier_indicator": item.meta["modifier_indicator"],
        "rationale": "",
    }


def result_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def row_leaked(payload: str, item: Item) -> bool:
    """True when a position 2-5 tool result contains the edit row."""
    if int(item.meta["position"]) == 1:
        return False
    markers = [
        str(item.meta["column_1"]),
        str(item.meta["column_2"]),
        "modifier_indicator",
        "deletion_date",
        "effective_date",
        "rationale",
        "2026-10-01",
    ]
    return any(marker and marker in payload for marker in markers)
