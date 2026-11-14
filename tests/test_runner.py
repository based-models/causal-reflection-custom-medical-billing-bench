"""The claim loop returns the row once, then grades the submit."""

from __future__ import annotations

import json

from ncci_bench.protocol import ToolCall, feedback_messages, reminder_text
from ncci_bench.providers import Arm, ChatResult, Usage
from ncci_bench.runner import run_item
from ncci_bench.tasks import load_tasks

GLM = Arm("glm-causal", "causal", "glm-5.3-flash:causal-reflection", "GLM causal")


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
        tool_calls=[ToolCall(id=f"id_{name}", name=name, arguments=json.dumps(arguments))],
        usage=Usage(prompt_tokens=10, completion_tokens=5),
    )


def _item(position: int, edit_type: str):
    for item in load_tasks():
        if int(item.meta["position"]) == position and item.meta["edit_type"] == edit_type:
            return item
    raise AssertionError("missing item")


def test_position_1_lookup_then_exact_submit_sends_outcome_only() -> None:
    item = _item(1, "deleted")
    client = Scripted(
        [
            _result(
                "lookup_edit",
                {
                    "column_1": item.meta["column_1"],
                    "column_2": item.meta["column_2"],
                    "date_of_service": "2026-10-15",
                },
            ),
            _result("submit_answer", {"summary": item.meta["summary"], "answer": item.gold_text}),
            ChatResult(content="", tool_calls=[], usage=Usage(prompt_tokens=4, completion_tokens=1)),
        ]
    )
    record = run_item(
        client=client,
        arm=GLM,
        item=item,
        run_id="test",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    assert record["exact"] is True
    assert record["later_row_leak"] == 0
    assert record["error"] is None
    decision = client.calls[1]
    tool_contents = [message["content"] for message in decision["messages"] if message["role"] == "tool"]
    assert len(tool_contents) == 1
    assert item.meta["column_1"] in tool_contents[0]
    assert "modifier_indicator" in tool_contents[0]
    feedback = client.calls[2]
    assert feedback["tools"] is None
    assert feedback["workload"] == "medical"
    assert feedback["session_id"] == f"ncci-test-{item.session_key}"
    tool_result = next(message["content"] for message in feedback["messages"] if message["role"] == "tool")
    assert json.loads(tool_result) == {"outcome": "success"}
    assert item.meta["column_1"] not in tool_result
    assert "2026-10-01" not in tool_result
    assert item.gold_text not in tool_result


def test_later_lookup_does_not_return_the_row() -> None:
    item = _item(3, "indicator_change")
    client = Scripted(
        [
            _result(
                "lookup_edit",
                {
                    "column_1": item.meta["column_1"],
                    "column_2": item.meta["column_2"],
                    "date_of_service": "10/15/2026",
                },
            ),
            _result("submit_answer", {"summary": item.meta["summary"], "answer": "column_2: deny\nmodifier: none"}),
            ChatResult(content="", tool_calls=[], usage=Usage()),
        ]
    )
    record = run_item(
        client=client,
        arm=GLM,
        item=item,
        run_id="test",
        temperature=0.0,
        max_tokens=200,
        feedback_max_tokens=32,
    )
    tool_contents = [
        message["content"] for message in client.calls[1]["messages"] if message["role"] == "tool"
    ]
    assert tool_contents == ['{"available": false}']
    assert record["later_row_leak"] == 0
    assert record["exact"] is False
    outcome = next(message["content"] for message in client.calls[2]["messages"] if message["role"] == "tool")
    assert json.loads(outcome) == {"outcome": "failure"}


def test_reminder_has_no_row_or_gold() -> None:
    item = _item(2, "hard_bundle")
    text = reminder_text(item)
    assert "2026-10-01" not in text
    assert "modifier_indicator" not in text
    assert item.gold_text not in text
    assert item.meta["summary"] in text
    built = feedback_messages(
        ToolCall("id_submit", "submit_answer", json.dumps({"summary": "p", "answer": item.gold_text})),
        "failure",
    )
    assert built[-1]["content"] == '{"outcome": "failure"}'
    assert item.meta["column_1"] not in json.dumps(built[-1])
