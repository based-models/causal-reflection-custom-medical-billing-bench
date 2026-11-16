"""Payer-rejection episode. The PTP table stays available on every claim.

The row says a modifier is allowed. Modifier 59 and the other X modifiers are
legal NCCI modifiers in the prompt. This payer accepts XS and rejects the
others. The rejection is returned by submit_answer, so a model can correct
itself inside the claim. The next claim still has the table. Remembering the
accepted modifier avoids a rejected first submission.
"""

from __future__ import annotations

from ncci_bench.changes import EFFECTIVE_DATE, load_changes
from ncci_bench.grading import normalize_answer
from ncci_bench.protocol import Item
from ncci_bench.tasks import CLAIM_TAGS, CLAIMS_PER_SESSION, DOS, SEPARATE_SITE, gold_lines, summary_token

PAYER_SESSIONS = 4
EPISODE = "payer"
ACCEPTED_MODIFIER = "XS"
REJECTED_MODIFIERS = ("59", "XE", "XP", "XU")

PAYER_SYSTEM = f"""You adjudicate one practitioner PTP edit for a single date of service.
Call lookup_edit for the column-one code, the column-two code, and the date of service. The edit table is available on every claim. Then call submit_answer. If the payer rejects that submission, call submit_answer again.

Apply the edit row as follows:
1. A deletion_date on or before the date of service pays the column-two code with modifier none.
2. Modifier indicator 0 denies the column-two code. A modifier does not pay it.
3. Modifier indicator 1, when the claim says "{SEPARATE_SITE}", can pay the column-two code with one NCCI-associated modifier: 59, XE, XP, XS, or XU.
4. Modifier indicator 9 pays the column-two code with modifier none.

This payer decides which of those modifiers it will pay. The response to submit_answer is that decision.

submit_answer.summary is the token printed in the claim, copied exactly.
submit_answer.answer is exactly two lines. The first line is "column_2: pay" or "column_2: deny". The second line is "modifier: none", "modifier: 59", "modifier: XE", "modifier: XP", "modifier: XS", or "modifier: XU"."""

def parse_disposition(answer: str) -> tuple[str, str]:
    column_2 = ""
    modifier = ""
    for line in normalize_answer(answer).splitlines():
        if line.startswith("column_2:"):
            column_2 = line.split(":", 1)[1].strip()
        elif line.startswith("modifier:"):
            modifier = line.split(":", 1)[1].strip()
    return column_2, modifier


def adjudicate(answer: str) -> dict[str, object]:
    """Payer response. No outcome, status, or ok key, so a rejection is not stored as a fact."""
    column_2, modifier = parse_disposition(answer)
    if column_2 == "pay" and modifier == ACCEPTED_MODIFIER:
        return {"accepted": True, "column_2": "pay", "modifier": ACCEPTED_MODIFIER}
    if column_2 == "pay" and modifier in REJECTED_MODIFIERS:
        return {
            "accepted": False,
            "reason": "Payer rejected this modifier. Resubmit the column-two line with modifier XS.",
        }
    return {
        "accepted": False,
        "reason": "Payer did not accept this disposition. Resubmit the column-two line with modifier XS.",
    }


def build_payer_tasks() -> list[Item]:
    """Four indicator-1 additions. Every claim says the service was on a separate site."""
    additions = sorted(
        (row for row in load_changes()["additions"] if row.modifier_indicator == "1"),
        key=lambda row: (row.column_1, row.column_2),
    )
    if len(additions) < PAYER_SESSIONS:
        raise ValueError("the pinned change file does not have four indicator-1 additions")
    items: list[Item] = []
    for row in additions[:PAYER_SESSIONS]:
        token = summary_token(row.column_1, row.column_2)
        for position in range(1, CLAIMS_PER_SESSION + 1):
            claim_id = f"{token}-{CLAIM_TAGS[position - 1]}"
            user = "\n".join(
                [
                    f"Claim {claim_id}.",
                    f"Column one code: {row.column_1}",
                    f"Column two code: {row.column_2}",
                    f"Date of service: {DOS}",
                    SEPARATE_SITE,
                    "The edit table is available. Call lookup_edit, then submit_answer. "
                    "If the payer rejects the submission, submit_answer again. "
                    f"summary must be exactly {token}.",
                ]
            )
            items.append(
                Item(
                    dataset="ncci",
                    item_id=claim_id,
                    session_key=token,
                    system=PAYER_SYSTEM,
                    user=user,
                    gold_text=gold_lines("pay", ACCEPTED_MODIFIER),
                    meta={
                        "episode": EPISODE,
                        "position": position,
                        "edit_type": "payer_rejection",
                        "column_1": row.column_1,
                        "column_2": row.column_2,
                        "modifier_indicator": "1",
                        "effective_date": EFFECTIVE_DATE,
                        "deletion_date": None,
                        "summary": token,
                        "separate_site": True,
                        "date_of_service": DOS,
                    },
                )
            )
    return items
