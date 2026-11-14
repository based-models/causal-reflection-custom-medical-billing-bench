"""List prices used to turn token counts into dollars.

GLM 5.3 Flash and DeepSeek V4.1 Flash match the causal-reflection model API.
Claude rates are the first-party list prices: Haiku 5.5, Sonnet 5.5, and Opus 5.5.
A 1-hour cache write is twice the base input price.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rates:
    input_per_token: float
    cached_per_token: float
    output_per_token: float
    long_prompt_tokens: int | None = None
    long_input_per_token: float | None = None
    long_cached_per_token: float | None = None
    long_output_per_token: float | None = None
    cache_write_multiplier: float = 1.0

    def cost(self, prompt: int, output: int, cached: int = 0, cache_write: int = 0) -> float:
        prompt_n = max(int(prompt), 0)
        output_n = max(int(output), 0)
        cached_n = min(max(int(cached), 0), prompt_n)
        room = prompt_n - cached_n
        write_n = min(max(int(cache_write), 0), room)
        fresh = room - write_n
        input_rate = self.input_per_token
        cached_rate = self.cached_per_token
        output_rate = self.output_per_token
        if self.long_prompt_tokens is not None and prompt_n > self.long_prompt_tokens:
            input_rate = self.long_input_per_token or input_rate
            cached_rate = self.long_cached_per_token or cached_rate
            output_rate = self.long_output_per_token or output_rate
        write_rate = input_rate * self.cache_write_multiplier
        return fresh * input_rate + write_n * write_rate + cached_n * cached_rate + output_n * output_rate


def _per_million(dollars: float) -> float:
    return dollars / 1_000_000


GLM = Rates(
    input_per_token=_per_million(0.15),
    cached_per_token=_per_million(0.03),
    output_per_token=_per_million(0.50),
)
DEEPSEEK = Rates(
    input_per_token=_per_million(0.30),
    cached_per_token=_per_million(0.006),
    output_per_token=_per_million(1.20),
)
HAIKU = Rates(
    input_per_token=_per_million(0.10),
    cached_per_token=_per_million(0.01),
    output_per_token=_per_million(0.50),
    long_prompt_tokens=100_000,
    long_input_per_token=_per_million(0.50),
    long_cached_per_token=_per_million(0.05),
    long_output_per_token=_per_million(2.50),
    cache_write_multiplier=2.0,
)
SONNET = Rates(
    input_per_token=_per_million(2.00),
    cached_per_token=_per_million(0.10),
    output_per_token=_per_million(10.00),
    cache_write_multiplier=2.0,
)
OPUS = Rates(
    input_per_token=_per_million(4.00),
    cached_per_token=_per_million(0.20),
    output_per_token=_per_million(20.00),
    cache_write_multiplier=2.0,
)

RATES: dict[str, Rates] = {
    "glm-baseline": GLM,
    "glm-causal": GLM,
    "deepseek-baseline": DEEPSEEK,
    "deepseek-causal": DEEPSEEK,
    "claude-haiku": HAIKU,
    "claude-sonnet": SONNET,
    "claude-opus": OPUS,
}


def cost_usd(arm_name: str, prompt: int, output: int, cached: int = 0, cache_write: int = 0) -> float | None:
    rates = RATES.get(arm_name)
    if rates is None:
        return None
    return rates.cost(prompt, output, cached, cache_write)
