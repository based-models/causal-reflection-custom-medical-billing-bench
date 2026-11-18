"""One plain GLM completion through the model API.

Calls `glm-5.3-flash` on BASED_API_BASE with BASED_API_KEY. No session header,
so the call is not attached to a causal-reflection graph and cannot collide
with one. Fireworks is not called from this machine.

    .venv/bin/python scripts/probe_glm_api.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ncci_bench.providers import load_dotenv  # noqa: E402

MODEL = "glm-5.3-flash"
PROMPT = "Reply with the single token glm-plain-ok."


def main() -> int:
    os.chdir(ROOT)
    load_dotenv()
    key = os.environ.get("BASED_API_KEY", "").strip() or os.environ.get("CRA_API_KEY", "").strip()
    base = os.environ.get("BASED_API_BASE", "https://api.basedmodels.com/v1").rstrip("/")
    if not key:
        print("Missing BASED_API_KEY. Copy .env.example to .env.", file=sys.stderr)
        return 1
    url = base + "/chat/completions"
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "max_tokens": 512,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    started = time.perf_counter()
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=httpx.Timeout(900.0, connect=20.0))
    except httpx.HTTPError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    latency_ms = int((time.perf_counter() - started) * 1000)
    print(f"http {response.status_code}")
    print(f"latency_ms {latency_ms}")
    if response.status_code >= 400:
        print(response.text[:800], file=sys.stderr)
        return 1
    try:
        payload = response.json()
    except json.JSONDecodeError:
        print(response.text[:800], file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("response JSON was not an object", file=sys.stderr)
        return 1
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice, dict) else {}
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    reasoning = message.get("reasoning_content")
    reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    returned = str(payload.get("model") or "")
    print(f"model {returned}")
    print(f"prompt_tokens {usage.get('prompt_tokens')}")
    print(f"completion_tokens {usage.get('completion_tokens')}")
    print(f"reasoning_chars {reasoning_chars}")
    preview = " ".join(text.split())
    print(f"content {preview[:400]}")
    if returned != MODEL:
        print(f"expected model {MODEL}", file=sys.stderr)
        return 1
    if not text.strip() and reasoning_chars == 0:
        print("empty completion", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
