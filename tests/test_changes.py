"""The pinned ZIP is the October 2026 practitioner PTP change file."""

from __future__ import annotations

import json

from ncci_bench.changes import (
    OBSERVED_COUNTS,
    changes_path,
    count_rows,
    load_changes,
    load_pin,
    load_zip_rows,
    pin_path,
    sha256_file,
    zip_path,
)


def test_pin_locks_the_downloaded_zip() -> None:
    pin = load_pin()
    assert sha256_file(zip_path()) == pin["sha256"]
    assert pin["url"].endswith("medicare-ncci-2026q4-practitioner-quarterly-additions-deletions-revisions-ptp.zip")
    counts = count_rows(load_zip_rows())
    assert counts == pin["counts"]
    assert counts == OBSERVED_COUNTS
    assert counts["deletions"] == 14
    assert counts["indicator_changes"] == 7
    assert counts["additions"] == 4249
    assert counts["additions_indicator_0"] == 1539
    assert counts["additions_indicator_1"] == 2710


def test_parsed_table_matches_the_zip() -> None:
    zipped = load_zip_rows()
    stored = load_changes()
    for key in ("additions", "deletions", "indicator_changes"):
        assert [row.to_dict() for row in stored[key]] == [row.to_dict() for row in zipped[key]]
    document = json.loads(changes_path().read_text(encoding="utf-8"))
    assert document["effective_date"] == "2026-10-01"
    assert pin_path().exists()
