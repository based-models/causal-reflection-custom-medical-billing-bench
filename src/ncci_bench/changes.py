"""Parse the pinned practitioner PTP quarterly change ZIP.

The ZIP is the CMS file effective October 1, 2026. Text tables are the source.
The workbook in the same ZIP is not read. Deletion and modifier-indicator
counts match the public change file. The addition count is the number of
code-pair rows in that file.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADDITIONS_NAME = "MCR_NCCI_Additions_Eff_10-01-2026.txt"
DELETIONS_NAME = "MCR_NCCI_Deletions_Eff_10-01-2026.txt"
CHANGES_NAME = "MCR_NCCI_CCMIChgs_Eff_10-01-2026.txt"
ZIP_NAME = "practitioner-q4.zip"
PIN_NAME = "PIN.json"
CHANGES_JSON = "changes.json"

EFFECTIVE_DATE = "2026-10-01"
SOURCE_URL = (
    "https://www.cms.gov/files/zip/"
    "medicare-ncci-2026q4-practitioner-quarterly-additions-deletions-revisions-ptp.zip"
)

# ClaimWork's status paper reported 1,119 additions for this quarter.
# The CMS text file contains 4,249 addition rows. Deletions and indicator
# changes in that paper match this ZIP (14 and 7). The pin locks the file.
OBSERVED_COUNTS = {
    "additions": 4249,
    "additions_indicator_0": 1539,
    "additions_indicator_1": 2710,
    "deletions": 14,
    "indicator_changes": 7,
}


@dataclass(frozen=True)
class ChangeRow:
    action: str
    column_1: str
    column_2: str
    modifier_indicator: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "column_1": self.column_1,
            "column_2": self.column_2,
            "modifier_indicator": self.modifier_indicator,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ChangeRow:
        return cls(
            action=str(raw["action"]),
            column_1=str(raw["column_1"]),
            column_2=str(raw["column_2"]),
            modifier_indicator=str(raw["modifier_indicator"]),
        )


def data_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "ncci"
        if (candidate / ZIP_NAME).exists():
            return candidate
    raise FileNotFoundError(f"data/ncci/{ZIP_NAME} not found")


def zip_path() -> Path:
    return data_dir() / ZIP_NAME


def pin_path() -> Path:
    return data_dir() / PIN_NAME


def changes_path() -> Path:
    return data_dir() / CHANGES_JSON


def parse_change_text(text: str, action: str) -> list[ChangeRow]:
    """Rows whose third column is a modifier indicator. Header and copyright are skipped."""
    rows: list[ChangeRow] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        column_1 = parts[0].strip().strip('"')
        column_2 = parts[1].strip().strip('"')
        indicator = parts[2].strip().strip('"')
        if indicator not in {"0", "1", "9"} or not column_1 or column_1.startswith("Column"):
            continue
        rows.append(
            ChangeRow(
                action=action,
                column_1=column_1,
                column_2=column_2,
                modifier_indicator=indicator,
            )
        )
    return rows


def load_zip_rows(path: Path | None = None) -> dict[str, list[ChangeRow]]:
    source = path or zip_path()
    with zipfile.ZipFile(source) as archive:
        additions = parse_change_text(archive.read(ADDITIONS_NAME).decode("utf-8"), "addition")
        deletions = parse_change_text(archive.read(DELETIONS_NAME).decode("utf-8"), "deletion")
        changes = parse_change_text(archive.read(CHANGES_NAME).decode("utf-8"), "indicator_change")
    return {
        "additions": additions,
        "deletions": deletions,
        "indicator_changes": changes,
    }


def count_rows(rows: dict[str, list[ChangeRow]]) -> dict[str, int]:
    additions = rows["additions"]
    return {
        "additions": len(additions),
        "additions_indicator_0": sum(row.modifier_indicator == "0" for row in additions),
        "additions_indicator_1": sum(row.modifier_indicator == "1" for row in additions),
        "deletions": len(rows["deletions"]),
        "indicator_changes": len(rows["indicator_changes"]),
    }


def load_pin() -> dict[str, Any]:
    return json.loads(pin_path().read_text(encoding="utf-8"))


def load_changes() -> dict[str, list[ChangeRow]]:
    raw = json.loads(changes_path().read_text(encoding="utf-8"))
    return {
        key: [ChangeRow.from_dict(item) for item in raw[key]]
        for key in ("additions", "deletions", "indicator_changes")
    }


def changes_document(rows: dict[str, list[ChangeRow]]) -> dict[str, Any]:
    return {
        "effective_date": EFFECTIVE_DATE,
        "source_url": SOURCE_URL,
        "additions": [row.to_dict() for row in rows["additions"]],
        "deletions": [row.to_dict() for row in rows["deletions"]],
        "indicator_changes": [row.to_dict() for row in rows["indicator_changes"]],
    }


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
