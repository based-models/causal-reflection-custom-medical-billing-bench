"""Fifty claims, ten sessions, and no edit row in the user text."""

from __future__ import annotations

from ncci_bench.tasks import (
    CLAIMS_PER_SESSION,
    SEPARATE_SITE,
    SESSION_COUNT,
    SYSTEM_PROMPT,
    build_tasks,
    disposition,
    load_tasks,
    slice_sessions,
)


def _session_keys(items: list) -> list[str]:
    keys: list[str] = []
    for item in items:
        if item.session_key not in keys:
            keys.append(item.session_key)
    return keys


def test_fifty_claims_and_gate_balance() -> None:
    items = load_tasks()
    assert items == build_tasks()
    assert len(items) == SESSION_COUNT * CLAIMS_PER_SESSION
    keys = _session_keys(items)
    assert len(keys) == SESSION_COUNT
    for key in keys:
        claims = [item for item in items if item.session_key == key]
        assert [item.meta["position"] for item in claims] == [1, 2, 3, 4, 5]
        assert len({item.gold_text for item in claims}) == 1
        assert len({item.system for item in claims}) == 1
    gate = slice_sessions(items, 6)
    gate_keys = _session_keys(gate)
    kinds = [next(item.meta["edit_type"] for item in gate if item.session_key == key) for key in gate_keys]
    assert kinds == [
        "deleted",
        "deleted",
        "indicator_change",
        "indicator_change",
        "hard_bundle",
        "hard_bundle",
    ]
    change_sites = [
        next(item.meta["separate_site"] for item in gate if item.session_key == key)
        for key, kind in zip(gate_keys, kinds)
        if kind == "indicator_change"
    ]
    assert change_sites == [True, False]
    full_kinds = [next(item.meta["edit_type"] for item in items if item.session_key == key) for key in keys]
    assert full_kinds.count("deleted") == 4
    assert full_kinds.count("indicator_change") == 3
    assert full_kinds.count("hard_bundle") == 3


def test_user_text_omits_the_row_and_gold_matches_the_rule() -> None:
    items = load_tasks()
    assert items[0].system == SYSTEM_PROMPT
    for item in items:
        assert item.system == SYSTEM_PROMPT
        user = item.user
        assert "2026-10-01" not in user
        assert "modifier_indicator" not in user
        assert "deletion_date" not in user
        assert "effective_date" not in user
        assert "rationale" not in user
        assert "position" not in user.lower()
        assert item.meta["column_1"] in user
        assert item.meta["column_2"] in user
        assert "2026-10-15" in user
        separate = bool(item.meta["separate_site"])
        assert (SEPARATE_SITE in user) is separate
        column_2, modifier = disposition(
            "deletion" if item.meta["edit_type"] == "deleted" else (
                "indicator_change" if item.meta["edit_type"] == "indicator_change" else "addition"
            ),
            str(item.meta["modifier_indicator"]),
            separate,
        )
        assert item.gold_text == f"column_2: {column_2}\nmodifier: {modifier}"
        bodies = []
        for claim in items:
            if claim.session_key != item.session_key:
                continue
            bodies.append("\n".join(claim.user.splitlines()[1:]))
        assert len(set(bodies)) == 1
