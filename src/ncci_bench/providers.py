"""Fireworks, Together, the causal-reflection API, and Anthropic.

Decision calls send tool_choice auto so the model can call lookup_edit before
submit_answer. The production API ignores tool_choice. Claude 5.5 rejects
temperature, so Anthropic bodies omit it. Sonnet and Opus stay on auto as well.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ncci_bench.pricing import cost_usd
from ncci_bench.protocol import ToolCall

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
TOGETHER_URL = "https://api.together.ai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = {429, 500, 502, 503, 529}


@dataclass(frozen=True)
class Arm:
    name: str
    kind: str
    model: str
    label: str


ARMS: dict[str, Arm] = {
    "glm-baseline": Arm(
        "glm-baseline",
        "fireworks",
        "accounts/fireworks/models/glm-5p3-flash",
        "GLM 5.3 Flash",
    ),
    "glm-causal": Arm(
        "glm-causal",
        "causal",
        "glm-5.3-flash:causal-reflection",
        "GLM 5.3 Flash + causal reflection",
    ),
    "glm-api": Arm(
        "glm-api",
        "plain",
        "glm-5.3-flash",
        "GLM 5.3 Flash via model API",
    ),
    "deepseek-baseline": Arm(
        "deepseek-baseline",
        "fireworks",
        "accounts/fireworks/models/deepseek-v4p1-flash",
        "DeepSeek V4.1 Flash",
    ),
    "deepseek-causal": Arm(
        "deepseek-causal",
        "causal",
        "deepseek-v4.1-flash:causal-reflection",
        "DeepSeek V4.1 Flash + causal reflection",
    ),
    "inkling-baseline": Arm(
        "inkling-baseline",
        "together",
        "thinkingmachines/Inkling-2-Small",
        "Inkling 2 Small",
    ),
    "inkling-causal": Arm(
        "inkling-causal",
        "causal",
        "inkling-2-small:causal-reflection",
        "Inkling 2 Small + causal reflection",
    ),
    "claude-haiku": Arm(
        "claude-haiku",
        "anthropic",
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
    ),
    "claude-sonnet": Arm(
        "claude-sonnet",
        "anthropic",
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
    ),
    "claude-opus": Arm(
        "claude-opus",
        "anthropic",
        "claude-opus-5-5",
        "Claude Opus 5.5",
    ),
}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0

    def add(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
        )

    def as_dict(self, arm_name: str) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": cost_usd(
                arm_name,
                self.prompt_tokens,
                self.completion_tokens,
                self.cached_tokens,
                self.cache_write_tokens,
            ),
        }


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    usage: Usage
    reasoning_chars: int = 0


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_var_for(arm: Arm) -> str:
    if arm.kind == "fireworks":
        return "FIREWORKS_API_KEY"
    if arm.kind == "together":
        return "TOGETHER_API_KEY"
    if arm.kind in {"causal", "plain"}:
        return "BASED_API_KEY"
    return "ANTHROPIC_API_KEY"


def key_for(arm: Arm) -> str:
    if arm.kind in {"causal", "plain"}:
        return os.environ.get("BASED_API_KEY", "").strip() or os.environ.get("CRA_API_KEY", "").strip()
    return os.environ.get(env_var_for(arm), "").strip()


def plain_headers(api_key: str) -> dict[str, str]:
    """Auth only. A session header would attach the call to a recorded session."""
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def missing_keys(arms: list[Arm]) -> list[str]:
    missing = []
    for arm in arms:
        if not key_for(arm):
            missing.append(f"{arm.name} ({env_var_for(arm)})")
    return missing


def causal_base_url() -> str:
    return os.environ.get("BASED_API_BASE", "https://api.basedmodels.com/v1").rstrip("/")


def causal_headers(api_key: str, session_id: str, run_id: str, workload: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Session-Id": session_id,
        "X-Run-Id": run_id,
        "X-Workload": workload,
    }


def parse_arms(raw: str) -> list[Arm]:
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise SystemExit("pass at least one arm")
    unknown = [name for name in names if name not in ARMS]
    if unknown:
        known = ", ".join(ARMS)
        raise SystemExit(f"unknown arm {', '.join(unknown)}. Known arms: {known}")
    return [ARMS[name] for name in names]


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return ""


def _usage_from(payload: dict[str, Any], latency_ms: int) -> Usage:
    usage = payload.get("usage") or {}
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cache_read_input_tokens") or 0
    cached_tokens = int(cached or 0)
    cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
    if "prompt_tokens" in usage:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
    else:
        prompt_tokens = int(usage.get("input_tokens") or 0) + cached_tokens + cache_write_tokens
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        latency_ms=latency_ms,
    )


def plain_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plain: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            plain.append(message)
            continue
        text = "".join(str(block.get("text") or "") if isinstance(block, dict) else str(block) for block in content)
        plain.append({**message, "content": text})
    return plain


def openai_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": plain_messages(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return body


def _tool_input(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def anthropic_messages(messages: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """Convert OpenAI-style tool turns into Anthropic content blocks."""
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system_parts.append(str(message.get("content") or ""))
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": str(message.get("content") or ""),
            }
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = message.get("content")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or "call"),
                        "name": str(function.get("name") or ""),
                        "input": _tool_input(function.get("arguments")),
                    }
                )
            if not blocks:
                blocks.append({"type": "text", "text": text if isinstance(text, str) else ""})
            converted.append({"role": "assistant", "content": blocks})
            continue
        converted.append({"role": "user", "content": _anthropic_content(message.get("content"))})
    return system_parts, converted


def anthropic_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """Messages API body. Claude 5.5 rejects temperature, so that argument is dropped."""
    del temperature
    system_parts, converted = anthropic_messages(messages)
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": converted,
    }
    if system_parts:
        body["system"] = "\n\n".join(part for part in system_parts if part)
    if tools:
        body["tools"] = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description") or "",
                "input_schema": tool["function"]["parameters"],
            }
            for tool in tools
        ]
        body["tool_choice"] = {"type": "auto"}
    return body


def _anthropic_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str) or content is None:
        return content or ""
    if not isinstance(content, list):
        return _text_content(content)
    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            blocks.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"tool_result", "tool_use"}:
            blocks.append(block)
            continue
        blocks.append({"type": "text", "text": str(block.get("text") or "")})
    return blocks


def _openai_result(payload: dict[str, Any], latency_ms: int) -> ChatResult:
    choices = payload.get("choices") or []
    if not choices:
        raise ProviderError("completion had no choices")
    message = choices[0].get("message") or {}
    calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        calls.append(
            ToolCall(
                id=str(call.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=arguments,
            )
        )
    reasoning = _text_content(message.get("reasoning_content"))
    return ChatResult(
        content=_text_content(message.get("content")),
        tool_calls=calls,
        usage=_usage_from(payload, latency_ms),
        reasoning_chars=len(reasoning),
    )


def _anthropic_result(payload: dict[str, Any], latency_ms: int) -> ChatResult:
    content_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            content_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            calls.append(
                ToolCall(
                    id=str(block.get("id") or ""),
                    name=str(block.get("name") or ""),
                    arguments=json.dumps(block.get("input") or {}),
                )
            )
    return ChatResult(
        content="".join(content_parts),
        tool_calls=calls,
        usage=_usage_from(payload, latency_ms),
    )


class Client:
    def __init__(self) -> None:
        self._http = httpx.Client(timeout=httpx.Timeout(900.0, connect=20.0))

    def close(self) -> None:
        self._http.close()

    def complete(
        self,
        *,
        arm: Arm,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        session_id: str | None,
        run_id: str | None,
        workload: str = "medical",
    ) -> ChatResult:
        api_key = key_for(arm)
        if not api_key:
            raise ProviderError(f"missing {env_var_for(arm)}")
        if arm.kind == "anthropic":
            url = ANTHROPIC_URL
            headers = {
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            }
            body = anthropic_body(
                model=arm.model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            payload = self._post(url, headers, body)
            return _anthropic_result(payload, payload.pop("_latency_ms", 0))
        if arm.kind == "causal":
            url = causal_base_url() + "/chat/completions"
            headers = causal_headers(api_key, session_id or "", run_id or "", workload)
        elif arm.kind == "plain":
            url = causal_base_url() + "/chat/completions"
            headers = plain_headers(api_key)
        elif arm.kind == "together":
            url = TOGETHER_URL
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        else:
            url = FIREWORKS_URL
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = openai_body(
            model=arm.model,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        payload = self._post(url, headers, body)
        return _openai_result(payload, payload.pop("_latency_ms", 0))

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        last_error = "request failed"
        last_status: int | None = None
        for attempt in range(4):
            started = time.perf_counter()
            try:
                response = self._http.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                last_status = None
                time.sleep(2**attempt)
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code in RETRY_STATUS:
                last_error = response.text[:500]
                last_status = response.status_code
                time.sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    f"HTTP {response.status_code}: {response.text[:500]}",
                    status=response.status_code,
                )
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise ProviderError(f"response was not JSON: {response.text[:300]}") from exc
            if not isinstance(payload, dict):
                raise ProviderError("response JSON was not an object")
            payload["_latency_ms"] = latency_ms
            return payload
        raise ProviderError(last_error, status=last_status)
