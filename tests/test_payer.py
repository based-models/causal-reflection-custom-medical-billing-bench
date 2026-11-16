"""The payer episode leaves the table on and teaches XS only after a rejection."""

from __future__ import annotations

import json

from ncci_bench.cli import main
from ncci_bench.lookup import lookup_result
from ncci_bench.payer import adjudicate, build_payer_tasks
from ncci_bench.protocol import ToolCall, decision_tools
from ncci_bench.providers import Arm, ChatResult, Usage
from ncci_bench.report import render_markdown, summarize
from ncci_bench.runner import run_item

CAUSAL = Arm("glm-causal", "causal", "glm-5.3-flash:causal-reflection", "GLM causal")
BASELINE = Arm("glm-baseline", "fireworks", "accounts/fireworks/models/glm-5p3-flash", "GLM")
FORBIDDEN = {"outcome", "status", "ok", "is_error"}
TEACHING = "Resubmit the column-two line with modifier XS."


class Scripted:
    def __init__(self, steps: list[ChatResult]) -> None:
        self.steps = list(steps)
        self.calls: list[dict] = []

    def complete(self, **kwargs: object) -> ChatResult:
        self.calls.append(kwargs)
        return self.steps.pop(0)


def _result(name: str, arguments: dict, content: str = "") -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=[ToolCall(id=f"id_{name}_{len(arguments)}", name=name, arguments=json.dumps(arguments))],
        usage=Usage(prompt_tokens=10, completion_tokens=5),
    )


def _later_claim():
    item = next(item for item in build_payer_tasks() if int(item.meta["position"]) == 3)
    return item


def _lookup(item):
    return _result(
        "lookup_edit",
        {
            "column_1": item.meta["column_1"],
            "column_2": item.meta["column_2"],
            "date_of_service": "2026-10-15",
        },
    )


def _submit(item, answer: str):
    return _result("submit_answer", {"summary": item.meta["summary"], "answer": answer})


def test_payer_tasks_do_not_name_the_accepted_modifier() -> None:
    items = build_payer_tasks()
    assert len(items) == 20
    sessions = []
    for item in items:
        if item.session_key not in sessions:
            sessions.append(item.session_key)
    assert len(sessions) == 4
    for item in items:
        assert item.meta["episode"] == "payer"
        assert item.meta["separate_site"] is True
        assert item.meta["modifier_indicator"] == "1"
        assert item.gold_text == "column_2: pay\nmodifier: XS"
        assert TEACHING not in item.system
        assert TEACHING not in item.user
        assert "The only modifier" not in item.system
        assert "59, XE, XP, XS, or XU" in item.system
    first = items[0]
    siblings = [item for item in items if item.session_key == first.session_key]
    bodies = [item.user.split("\n", 1)[1] for item in siblings]
    assert len(set(bodies)) == 1
    description = decision_tools(first)[1]["function"]["parameters"]["properties"]["answer"]["description"]
    assert "modifier: 59" in description


def test_lookup_stays_available_on_later_claims() -> None:
    item = _later_claim()
    payload = lookup_result(
        item,
        {
            "column_1": item.meta["column_1"],
            "column_2": item.meta["column_2"],
            "date_of_service": "10/15/2026",
        },
    )
    assert payload["modifier_indicator"] == "1"
    assert payload["column_1"] == item.meta["column_1"]
    assert FORBIDDEN.isdisjoint(payload)
    mismatch = lookup_result(item, {"column_1": "00000", "column_2": "11111", "date_of_service": "2026-10-15"})
    assert mismatch == {"available": False}


def test_adjudication_teaches_xs_without_a_stored_outcome() -> None:
    rejected = adjudicate("column_2: pay\nmodifier: 59")
    accepted = adjudicate("column_2: pay\nmodifier: XS")
    assert rejected["accepted"] is False
    assert TEACHING in str(rejected["reason"])
    assert accepted == {"accepted": True, "column_2": "pay", "modifier": "XS"}
    assert FORBIDDEN.isdisjoint(rejected)
    assert FORBIDDEN.isdisjoint(accepted)


def test_recovery_inside_the_claim_is_not_a_first_try() -> None:
    item = _later_claim()
    client = Scripted(
        [
            _lookup(item),
            _submit(item, "column_2: pay\nmodifier: 59"),
            _submit(item, item.gold_text),
            ChatResult(content="", tool_calls=[], usage=Usage(prompt_tokens=4, completion_tokens=1)),
        ]
    )
    record = run_item(
        client=client,
        arm=CAUSAL,
        item=item,
        run_id="payer",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    assert record["first_try"] is False
    assert record["exact"] is True
    assert record["round_trips"] == 2
    assert record["disposition"] == "paid_correct"
    assert record["lookup_count"] == 1
    seen = client.calls[2]["messages"]
    rejection = next(message["content"] for message in seen if message["role"] == "tool" and "rejected" in message["content"])
    parsed = json.loads(rejection)
    assert parsed["accepted"] is False
    assert FORBIDDEN.isdisjoint(parsed)
    assert item.meta["column_1"] in json.dumps(seen)
    assert "modifier_indicator" in json.dumps(seen)
    feedback = client.calls[3]
    tool_result = next(message["content"] for message in feedback["messages"] if message["role"] == "tool")
    assert json.loads(tool_result) == {"outcome": "success"}
    stored = json.dumps(feedback["messages"])
    assert "modifier: XS" in stored
    assert "modifier: 59" not in stored
    assert item.meta["column_1"] not in tool_result


def test_first_submission_of_xs_is_the_headline_hit() -> None:
    item = _later_claim()
    client = Scripted(
        [
            _submit(item, item.gold_text),
            ChatResult(content="", tool_calls=[], usage=Usage()),
        ]
    )
    record = run_item(
        client=client,
        arm=BASELINE,
        item=item,
        run_id="payer",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    assert record["first_try"] is True
    assert record["exact"] is True
    assert record["round_trips"] == 1
    assert len(client.calls) == 1


def test_hold_is_not_scored_as_a_rejected_payment() -> None:
    item = _later_claim()
    client = Scripted(
        [
            _lookup(item),
            ChatResult(content="I need to think.", tool_calls=[], usage=Usage()),
            ChatResult(content="Still thinking.", tool_calls=[], usage=Usage()),
        ]
    )
    record = run_item(
        client=client,
        arm=CAUSAL,
        item=item,
        run_id="payer",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    assert record["disposition"] == "hold"
    assert record["exact"] is False
    assert record["first_try"] is False
    assert record["round_trips"] == 0
    assert len(client.calls) == 3


def test_an_unaccepted_final_submission_is_not_a_hold() -> None:
    item = _later_claim()
    client = Scripted(
        [
            _submit(item, "column_2: deny\nmodifier: none"),
            ChatResult(content="", tool_calls=[], usage=Usage()),
            ChatResult(content="", tool_calls=[], usage=Usage()),
            ChatResult(content="", tool_calls=[], usage=Usage()),
        ]
    )
    record = run_item(
        client=client,
        arm=CAUSAL,
        item=item,
        run_id="payer",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    assert record["disposition"] == "wrong_payment"
    assert record["exact"] is False
    assert record["first_try"] is False
    outcome = next(message["content"] for message in client.calls[-1]["messages"] if message["role"] == "tool")
    assert json.loads(outcome) == {"outcome": "failure"}


def test_payer_report_headline_is_first_try() -> None:
    records = []
    for position, base_first, causal_first, base_final, causal_final in (
        (1, False, False, True, True),
        (2, False, True, True, True),
        (3, False, True, True, True),
        (4, True, True, True, True),
        (5, False, False, False, True),
    ):
        for arm, first, final in (
            ("glm-baseline", base_first, base_final),
            ("glm-causal", causal_first, causal_final),
        ):
            records.append(
                {
                    "arm": arm,
                    "item_id": f"c{position}",
                    "episode": "payer",
                    "position": position,
                    "edit_type": "payer_rejection",
                    "exact": final,
                    "first_try": first,
                    "round_trips": 1 if first else 2,
                    "disposition": "paid_correct" if final else "wrong_payment",
                    "lookup_count": 1,
                    "tool_called": True,
                    "later_row_leak": 0,
                    "usage": {"cost_usd": 0.01},
                    "error": None,
                }
            )
    summary = summarize(records)
    assert summary["headline_later"]["baseline"] == 0.25
    assert summary["headline_later"]["causal"] == 0.75
    assert summary["headline_later"]["delta"] == 0.5
    assert summary["final_later"]["causal"] == 1.0
    assert summary["final_later"]["baseline"] == 0.75
    text = render_markdown(summary)
    assert "First submission already correct" in text
    assert "Holds" in text
    assert "positions 2-5" not in text


def test_payer_dry_run(capsys: object) -> None:
    main(["run", "--episode", "payer", "--sessions", "1", "--arms", "glm-baseline,glm-causal", "--dry-run"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "episode payer" in out
    assert "sessions 1" in out
    assert "claims 5" in out
    assert "payer_rejection" in out
    assert "no API calls" in out
