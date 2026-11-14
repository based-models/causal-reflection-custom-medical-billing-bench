"""Fifty claims from ten pinned PTP edits.

The correct disposition is the same on all five claims in a session. Claim text
names the codes and the date of service. It does not contain the edit row.
"""

from __future__ import annotations

import json
from pathlib import Path

from ncci_bench.changes import EFFECTIVE_DATE, ChangeRow, load_changes
from ncci_bench.protocol import Item

DOS = "2026-10-15"
CLAIMS_PER_SESSION = 5
SESSION_COUNT = 10
GATE_SESSIONS = 6
# Distinct claim ids that do not number the position inside the session.
CLAIM_TAGS = ("north", "ridge", "cedar", "maple", "brook")

SEPARATE_SITE = "The column-two service was performed on a separate anatomic site."

SYSTEM_PROMPT = f"""You adjudicate one practitioner PTP edit for a single date of service.
The edit row is not in this prompt. Call lookup_edit with the column-one code, the column-two code, and the date of service when you need the row. Then call submit_answer.

Apply these rules in order:
1. If the edit row has a deletion_date on or before the date of service, the column-two code is paid and the modifier is none.
2. If the modifier_indicator is 0, the column-two code is denied and the modifier is none. A modifier does not pay it.
3. If the modifier_indicator is 1 and the claim says "{SEPARATE_SITE}", the column-two code is paid with modifier XS.
4. If the modifier_indicator is 1 and the claim does not say that, the column-two code is denied and the modifier is none.
5. If the modifier_indicator is 9, the column-two code is paid and the modifier is none.

The only modifier this bench accepts is XS, and only under rule 3. Modifiers 59, XE, XP, and XU are wrong.

submit_answer.summary is the token printed in the claim, copied exactly.
submit_answer.answer is exactly two lines. The first line is "column_2: pay" or "column_2: deny". The second line is "modifier: none" or "modifier: XS"."""


def summary_token(column_1: str, column_2: str) -> str:
    return f"p{column_1}_{column_2}"


def gold_lines(column_2: str, modifier: str) -> str:
    return f"column_2: {column_2}\nmodifier: {modifier}"


def disposition(action: str, modifier_indicator: str, separate_site: bool) -> tuple[str, str]:
    """Payment of the column-two code, then the modifier. Deletion wins over the indicator."""
    if action == "deletion":
        return "pay", "none"
    if modifier_indicator == "0":
        return "deny", "none"
    if modifier_indicator == "1" and separate_site:
        return "pay", "XS"
    if modifier_indicator == "1":
        return "deny", "none"
    if modifier_indicator == "9":
        return "pay", "none"
    raise ValueError(f"no disposition for {action} indicator {modifier_indicator}")


def _by_code(rows: list[ChangeRow]) -> list[ChangeRow]:
    return sorted(rows, key=lambda row: (row.column_1, row.column_2))


def select_rows(changes: dict[str, list[ChangeRow]]) -> list[ChangeRow]:
    """Ten rows. The first six are two deletions, two indicator changes, and two hard bundles.

    The two indicator changes in that prefix are one new indicator 1 and one new
    indicator 0, so the 30-claim gate includes both dispositions.
    """
    deletions = _by_code(changes["deletions"])
    hard = _by_code([row for row in changes["additions"] if row.modifier_indicator == "0"])
    indicator_1 = _by_code(
        [row for row in changes["indicator_changes"] if row.modifier_indicator == "1"]
    )
    indicator_0 = _by_code(
        [row for row in changes["indicator_changes"] if row.modifier_indicator == "0"]
    )
    if len(deletions) < 4 or len(hard) < 3 or len(indicator_1) < 2 or len(indicator_0) < 1:
        raise ValueError("the pinned change file does not have enough rows for the ten sessions")
    chosen_changes = [indicator_1[0], indicator_0[0], indicator_1[1]]
    return [
        deletions[0],
        deletions[1],
        chosen_changes[0],
        chosen_changes[1],
        hard[0],
        hard[1],
        deletions[2],
        deletions[3],
        chosen_changes[2],
        hard[2],
    ]


def edit_type(row: ChangeRow) -> str:
    if row.action == "deletion":
        return "deleted"
    if row.action == "indicator_change":
        return "indicator_change"
    if row.action == "addition" and row.modifier_indicator == "0":
        return "hard_bundle"
    raise ValueError(f"row is not one of the three bench types: {row}")


def _user_text(claim_id: str, row: ChangeRow, token: str, separate_site: bool) -> str:
    lines = [
        f"Claim {claim_id}.",
        f"Column one code: {row.column_1}",
        f"Column two code: {row.column_2}",
        f"Date of service: {DOS}",
    ]
    if separate_site:
        lines.append(SEPARATE_SITE)
    lines.append(
        "Call lookup_edit when you need the PTP edit row. Then call submit_answer. "
        f"summary must be exactly {token}."
    )
    return "\n".join(lines)


def build_tasks(changes: dict[str, list[ChangeRow]] | None = None) -> list[Item]:
    rows = select_rows(changes if changes is not None else load_changes())
    items: list[Item] = []
    for row in rows:
        kind = edit_type(row)
        token = summary_token(row.column_1, row.column_2)
        separate_site = kind == "indicator_change" and row.modifier_indicator == "1"
        column_2, modifier = disposition(row.action, row.modifier_indicator, separate_site)
        deleted = row.action == "deletion"
        for position in range(1, CLAIMS_PER_SESSION + 1):
            claim_id = f"{token}-{CLAIM_TAGS[position - 1]}"
            items.append(
                Item(
                    dataset="ncci",
                    item_id=claim_id,
                    session_key=token,
                    system=SYSTEM_PROMPT,
                    user=_user_text(claim_id, row, token, separate_site),
                    gold_text=gold_lines(column_2, modifier),
                    meta={
                        "position": position,
                        "edit_type": kind,
                        "column_1": row.column_1,
                        "column_2": row.column_2,
                        "modifier_indicator": row.modifier_indicator,
                        "effective_date": None if deleted else EFFECTIVE_DATE,
                        "deletion_date": EFFECTIVE_DATE if deleted else None,
                        "summary": token,
                        "separate_site": separate_site,
                        "date_of_service": DOS,
                    },
                )
            )
    return items


def tasks_path() -> Path:
    from ncci_bench.changes import data_dir

    return data_dir() / "tasks.jsonl"


def load_tasks() -> list[Item]:
    items: list[Item] = []
    for line in tasks_path().read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(Item.from_dict(json.loads(line)))
    return items


def write_tasks(path: Path | None = None) -> list[Item]:
    items = build_tasks()
    target = path or tasks_path()
    target.write_text(
        "".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )
    return items


def slice_sessions(items: list[Item], sessions: int) -> list[Item]:
    """First N sessions in bench order. Each session is five claims."""
    if sessions < 1 or sessions > SESSION_COUNT:
        raise ValueError(f"sessions must be 1..{SESSION_COUNT}")
    keys: list[str] = []
    for item in items:
        if item.session_key not in keys:
            keys.append(item.session_key)
    keep = set(keys[:sessions])
    return [item for item in items if item.session_key in keep]
