"""Exact match on the two-line disposition."""

from __future__ import annotations


def normalize_answer(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines()]
    kept = [line for line in lines if line]
    return "\n".join(kept)


def is_exact(predicted: str, gold: str) -> bool:
    return bool(gold) and normalize_answer(predicted) == normalize_answer(gold)
