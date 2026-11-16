"""Claim items, the two tools, and the causal feedback transcript."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class Item:
    dataset: str
    item_id: str
    session_key: str
    system: str
    user: str
    gold_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "item_id": self.item_id,
            "session_key": self.session_key,
            "system": self.system,
            "user": self.user,
            "gold_text": self.gold_text,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Item:
        return cls(
            dataset=str(raw["dataset"]),
            item_id=str(raw["item_id"]),
            session_key=str(raw["session_key"]),
            system=str(raw.get("system") or ""),
            user=str(raw.get("user") or ""),
            gold_text=str(raw.get("gold_text") or ""),
            meta=dict(raw.get("meta") or {}),
        )


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


def decision_tools(item: Item) -> list[dict[str, Any]]:
    token = str(item.meta["summary"])
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_edit",
                "description": "Look up the PTP edit row for one code pair on a date of service.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "column_1": {"type": "string", "description": "Column one HCPCS or CPT code."},
                        "column_2": {"type": "string", "description": "Column two HCPCS or CPT code."},
                        "date_of_service": {
                            "type": "string",
                            "description": "Date of service, YYYY-MM-DD.",
                        },
                    },
                    "required": ["column_1", "column_2", "date_of_service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_answer",
                "description": "Submit the column-two disposition for this claim.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "enum": [token],
                            "description": f"Copy this token exactly: {token}.",
                        },
                        "answer": {
                            "type": "string",
                            "description": _answer_description(item),
                        },
                    },
                    "required": ["summary", "answer"],
                },
            },
        },
    ]


def _answer_description(item: Item) -> str:
    if item.meta.get("episode") == "payer":
        return (
            "Exactly two lines. First line column_2: pay or column_2: deny. "
            "Second line modifier: none, modifier: 59, modifier: XE, modifier: XP, "
            "modifier: XS, or modifier: XU. The payer response says whether it was accepted."
        )
    return (
        "Exactly two lines. First line column_2: pay or column_2: deny. "
        "Second line modifier: none or modifier: XS."
    )


def reminder_text(item: Item) -> str:
    token = str(item.meta["summary"])
    if item.meta.get("episode") == "payer":
        return (
            "You must call the submit_answer tool. "
            f"summary must be exactly {token}. "
            'answer is exactly two lines. The first is "column_2: pay" or "column_2: deny". '
            'The second is "modifier: none", "modifier: 59", "modifier: XE", "modifier: XP", '
            '"modifier: XS", or "modifier: XU".'
        )
    return (
        "You must call the submit_answer tool. "
        f"summary must be exactly {token}. "
        'answer is exactly two lines. The first is "column_2: pay" or "column_2: deny". '
        'The second is "modifier: none" or "modifier: XS".'
    )


def load_args(call: ToolCall | None) -> dict[str, Any]:
    if call is None or not call.arguments.strip():
        return {}
    try:
        parsed = json.loads(call.arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_object_in(text: str) -> dict[str, Any] | None:
    source = text or ""
    start = source.find("{")
    while start != -1:
        try:
            parsed, _end = _DECODER.raw_decode(source[start:])
        except json.JSONDecodeError:
            start = source.find("{", start + 1)
            continue
        if isinstance(parsed, dict):
            return parsed
        start = source.find("{", start + 1)
    return None


def pick_submit(tool_calls: list[ToolCall]) -> ToolCall | None:
    for call in tool_calls:
        if call.name == "submit_answer":
            return call
    return None


def lookup_calls(tool_calls: list[ToolCall]) -> list[ToolCall]:
    return [call for call in tool_calls if call.name == "lookup_edit"]


def parse_submission(content: str, tool_calls: list[ToolCall]) -> dict[str, Any]:
    call = pick_submit(tool_calls)
    payload = load_args(call) or json_object_in(content) or {}
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = (content or "").strip()
    return {
        "answer_text": answer.strip(),
        "tool_called": call is not None,
        "call": call,
    }


def feedback_messages(call: ToolCall, outcome: str) -> list[dict[str, Any]]:
    """Transcript whose last message is the outcome. Gold and the edit row are not included."""
    if outcome not in {"success", "failure"}:
        raise ValueError(f"outcome must be success or failure, got {outcome}")
    call_id = call.id or "call_submit"
    return [
        {"role": "user", "content": "Record the outcome of the previous submission."},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments or "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps({"outcome": outcome}),
        },
    ]


def session_id_for(run_id: str, session_key: str) -> str:
    return f"ncci-{run_id}-{session_key}"


def assistant_message(content: str, tool_calls: list[ToolCall]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id or f"call_{index}",
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments or "{}"},
            }
            for index, call in enumerate(tool_calls)
        ]
    return message


def tool_message(call: ToolCall, content: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.id or "call_lookup",
        "content": content,
    }
