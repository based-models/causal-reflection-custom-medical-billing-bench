"""Decision calls leave the tool choice on auto."""

from __future__ import annotations

import json

from ncci_bench.providers import ARMS, anthropic_body, env_var_for, openai_body, plain_headers


def test_every_arm_can_choose_lookup_before_submit() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "claim"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "lookup_1",
                    "type": "function",
                    "function": {
                        "name": "lookup_edit",
                        "arguments": json.dumps({"column_1": "23473", "column_2": "20704", "date_of_service": "2026-10-15"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "lookup_1", "content": '{"available": false}'},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_edit",
                "description": "look up",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    fireworks = openai_body(
        model="accounts/fireworks/models/glm-5p3-flash",
        messages=messages,
        tools=tools,
        max_tokens=100,
        temperature=0.0,
    )
    assert fireworks["tool_choice"] == "auto"
    haiku = anthropic_body(
        model="claude-haiku-5-5",
        messages=messages,
        tools=tools,
        max_tokens=100,
        temperature=0.2,
    )
    sonnet = anthropic_body(
        model="claude-sonnet-5-5",
        messages=messages,
        tools=tools,
        max_tokens=100,
        temperature=0.2,
    )
    assert "temperature" not in haiku
    assert "temperature" not in sonnet
    assert haiku["tool_choice"] == {"type": "auto"}
    assert sonnet["tool_choice"] == {"type": "auto"}
    assert haiku["system"] == "rules"
    assistant = haiku["messages"][1]
    assert assistant["content"][0]["type"] == "tool_use"
    assert assistant["content"][0]["name"] == "lookup_edit"
    result = haiku["messages"][2]
    assert result["content"][0]["type"] == "tool_result"
    assert result["content"][0]["content"] == '{"available": false}'


def test_plain_glm_uses_the_model_api_without_a_session() -> None:
    arm = ARMS["glm-api"]
    assert arm.model == "glm-5.3-flash"
    assert arm.kind == "plain"
    assert env_var_for(arm) == "BASED_API_KEY"
    headers = plain_headers("test-key")
    assert headers["Authorization"] == "Bearer test-key"
    assert "X-Session-Id" not in headers
    assert "X-Workload" not in headers
