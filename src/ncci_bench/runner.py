"""Run one arm over the frozen claims.

Each claim starts from the system prompt and the user text. A lookup_edit call
is answered by the harness and the model is called again. submit_answer ends
the claim. The causal arm then sends a second call whose last message is
{"outcome": "success"} or {"outcome": "failure"}. That object does not contain
the edit row or the gold disposition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ncci_bench.grading import is_exact
from ncci_bench.lookup import lookup_result, result_json, row_leaked
from ncci_bench.protocol import (
    Item,
    ToolCall,
    assistant_message,
    decision_tools,
    feedback_messages,
    lookup_calls,
    parse_submission,
    pick_submit,
    reminder_text,
    session_id_for,
    tool_message,
)
from ncci_bench.providers import Arm, ChatResult, ProviderError, Usage

MAX_COMPLETIONS = 4
WORKLOAD = "medical"


def completed_pairs(path: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not path.exists():
        return done
    for record in read_jsonl(path):
        if not record.get("error"):
            done.add((str(record.get("arm")), str(record.get("item_id"))))
    return done


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def _ensure_ids(calls: list[ToolCall]) -> list[ToolCall]:
    ensured: list[ToolCall] = []
    for index, call in enumerate(calls):
        ensured.append(
            ToolCall(
                id=call.id or f"call_{index}",
                name=call.name,
                arguments=call.arguments,
            )
        )
    return ensured


def run_item(
    *,
    client: Any,
    arm: Arm,
    item: Item,
    run_id: str,
    temperature: float,
    max_tokens: int,
    feedback_max_tokens: int,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": item.system},
        {"role": "user", "content": item.user},
    ]
    tools = decision_tools(item)
    usage = Usage()
    feedback_usage = Usage()
    payloads: list[str] = []
    completions = 0
    reminded = False
    submit: ToolCall | None = None
    content = ""
    session_id = session_id_for(run_id, item.session_key) if arm.kind == "causal" else None
    try:
        while completions < MAX_COMPLETIONS and submit is None:
            result: ChatResult = client.complete(
                arm=arm,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                session_id=session_id,
                run_id=run_id if arm.kind == "causal" else None,
                workload=WORKLOAD,
            )
            completions += 1
            usage = usage.add(result.usage)
            calls = _ensure_ids(result.tool_calls)
            content = result.content
            submit = pick_submit(calls)
            if submit is not None:
                break
            lookups = lookup_calls(calls)
            if lookups:
                messages.append(assistant_message(result.content, calls))
                for call in lookups:
                    payload = result_json(lookup_result(item, call.arguments))
                    payloads.append(payload)
                    messages.append(tool_message(call, payload))
                continue
            if not reminded:
                reminded = True
                messages.append(assistant_message(result.content, calls))
                messages.append({"role": "user", "content": reminder_text(item)})
                continue
            break
        parsed = parse_submission(content, [submit] if submit else [])
        answer = parsed["answer_text"]
        exact = is_exact(answer, item.gold_text)
        if arm.kind == "causal" and submit is not None:
            outcome = "success" if exact else "failure"
            feedback = client.complete(
                arm=arm,
                messages=feedback_messages(submit, outcome),
                tools=None,
                max_tokens=feedback_max_tokens,
                temperature=temperature,
                session_id=session_id,
                run_id=run_id,
                workload=WORKLOAD,
            )
            feedback_usage = feedback.usage
            usage = usage.add(feedback.usage)
        leaked = sum(1 for payload in payloads if row_leaked(payload, item))
        return {
            "arm": arm.name,
            "item_id": item.item_id,
            "session_key": item.session_key,
            "position": int(item.meta["position"]),
            "edit_type": item.meta["edit_type"],
            "gold": item.gold_text,
            "answer": answer,
            "exact": exact,
            "tool_called": submit is not None,
            "lookup_count": len(payloads),
            "lookup_payloads": payloads,
            "later_row_leak": leaked,
            "completions": completions,
            "usage": usage.as_dict(arm.name),
            "feedback_usage": feedback_usage.as_dict(arm.name),
            "error": None,
        }
    except ProviderError as exc:
        return {
            "arm": arm.name,
            "item_id": item.item_id,
            "session_key": item.session_key,
            "position": int(item.meta["position"]),
            "edit_type": item.meta["edit_type"],
            "gold": item.gold_text,
            "answer": "",
            "exact": False,
            "tool_called": False,
            "lookup_count": len(payloads),
            "lookup_payloads": payloads,
            "later_row_leak": sum(1 for payload in payloads if row_leaked(payload, item)),
            "completions": completions,
            "usage": usage.as_dict(arm.name),
            "feedback_usage": feedback_usage.as_dict(arm.name),
            "error": str(exc),
        }
