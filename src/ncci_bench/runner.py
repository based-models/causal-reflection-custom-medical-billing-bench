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
from ncci_bench.payer import adjudicate
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
PAYER_MAX_COMPLETIONS = 5
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
    if item.meta.get("episode") == "payer":
        return _run_payer_item(
            client=client,
            arm=arm,
            item=item,
            run_id=run_id,
            temperature=temperature,
            max_tokens=max_tokens,
            feedback_max_tokens=feedback_max_tokens,
        )
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


def _answer_of(call: ToolCall | None) -> str:
    if call is None:
        return ""
    return str(parse_submission("", [call])["answer_text"])


def _payer_record(
    *,
    arm: Arm,
    item: Item,
    answer: str,
    exact: bool,
    submits: list[ToolCall],
    accepted: bool,
    payloads: list[str],
    completions: int,
    usage: Usage,
    feedback_usage: Usage,
    error: str | None,
) -> dict[str, Any]:
    if not submits:
        disposition = "hold"
    elif accepted:
        disposition = "paid_correct"
    else:
        disposition = "wrong_payment"
    first_try = bool(submits) and is_exact(_answer_of(submits[0]), item.gold_text)
    return {
        "arm": arm.name,
        "item_id": item.item_id,
        "session_key": item.session_key,
        "episode": "payer",
        "position": int(item.meta["position"]),
        "edit_type": item.meta["edit_type"],
        "gold": item.gold_text,
        "answer": answer,
        "exact": exact,
        "first_try": first_try,
        "round_trips": len(submits),
        "disposition": disposition,
        "tool_called": bool(submits),
        "lookup_count": len(payloads),
        "lookup_payloads": payloads,
        "later_row_leak": 0,
        "completions": completions,
        "usage": usage.as_dict(arm.name),
        "feedback_usage": feedback_usage.as_dict(arm.name),
        "error": error,
    }


def _run_payer_item(
    *,
    client: Any,
    arm: Arm,
    item: Item,
    run_id: str,
    temperature: float,
    max_tokens: int,
    feedback_max_tokens: int,
) -> dict[str, Any]:
    """Lookup stays on. submit_answer returns a payer decision and can be called again."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": item.system},
        {"role": "user", "content": item.user},
    ]
    tools = decision_tools(item)
    usage = Usage()
    feedback_usage = Usage()
    payloads: list[str] = []
    submits: list[ToolCall] = []
    completions = 0
    reminded = False
    accepted = False
    accepted_call: ToolCall | None = None
    session_id = session_id_for(run_id, item.session_key) if arm.kind == "causal" else None
    try:
        while completions < PAYER_MAX_COMPLETIONS and not accepted:
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
            lookups = lookup_calls(calls)
            submit = pick_submit(calls)
            if submit is None and not lookups:
                if not reminded:
                    reminded = True
                    messages.append(assistant_message(result.content, calls))
                    messages.append({"role": "user", "content": reminder_text(item)})
                    continue
                break
            messages.append(assistant_message(result.content, calls))
            for call in calls:
                if call.name == "lookup_edit":
                    payload = result_json(lookup_result(item, call.arguments))
                    payloads.append(payload)
                    messages.append(tool_message(call, payload))
                elif call.name == "submit_answer":
                    decision = adjudicate(_answer_of(call))
                    submits.append(call)
                    messages.append(tool_message(call, result_json(decision)))
                    if decision.get("accepted") and accepted_call is None:
                        accepted = True
                        accepted_call = call
            if accepted:
                break
        final_answer = _answer_of(accepted_call or (submits[-1] if submits else None))
        if arm.kind == "causal" and submits:
            outcome = "success" if accepted else "failure"
            stored = accepted_call if accepted_call is not None else submits[-1]
            feedback = client.complete(
                arm=arm,
                messages=feedback_messages(stored, outcome),
                tools=None,
                max_tokens=feedback_max_tokens,
                temperature=temperature,
                session_id=session_id,
                run_id=run_id,
                workload=WORKLOAD,
            )
            feedback_usage = feedback.usage
            usage = usage.add(feedback.usage)
        return _payer_record(
            arm=arm,
            item=item,
            answer=final_answer,
            exact=accepted,
            submits=submits,
            accepted=accepted,
            payloads=payloads,
            completions=completions,
            usage=usage,
            feedback_usage=feedback_usage,
            error=None,
        )
    except ProviderError as exc:
        return _payer_record(
            arm=arm,
            item=item,
            answer="",
            exact=False,
            submits=submits,
            accepted=accepted,
            payloads=payloads,
            completions=completions,
            usage=usage,
            feedback_usage=feedback_usage,
            error=str(exc),
        )
