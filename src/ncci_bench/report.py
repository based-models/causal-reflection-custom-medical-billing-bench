"""Exact-match report. The headline is positions 2-5, causal minus its own baseline."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ncci_bench.runner import read_jsonl

ARM_ORDER = (
    "glm-baseline",
    "glm-causal",
    "deepseek-baseline",
    "deepseek-causal",
    "claude-haiku",
    "claude-sonnet",
    "claude-opus",
)
ARM_LABELS = {
    "glm-baseline": "GLM 5.3 Flash",
    "glm-causal": "GLM 5.3 Flash + causal reflection",
    "deepseek-baseline": "DeepSeek V4.1 Flash",
    "deepseek-causal": "DeepSeek V4.1 Flash + causal reflection",
    "claude-haiku": "Claude Haiku 5.5",
    "claude-sonnet": "Claude Sonnet 5.5",
    "claude-opus": "Claude Opus 5.5",
}


def _label(arm: str) -> str:
    return ARM_LABELS.get(arm, arm)


def _ok(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if not record.get("error")]


def _rate(records: list[dict[str, Any]]) -> float | None:
    if not records:
        return None
    return sum(1 for record in records if record.get("exact")) / len(records)


def _model_pair(arms: list[str]) -> tuple[str, str] | None:
    present = set(arms)
    pairs = []
    for name in arms:
        if not name.endswith("-causal"):
            continue
        baseline = name.removesuffix("causal") + "baseline"
        if baseline in present:
            pairs.append((baseline, name))
    if not pairs:
        return None
    pairs.sort(key=lambda pair: ARM_ORDER.index(pair[0]) if pair[0] in ARM_ORDER else 99)
    return pairs[0]


def _aligned(records: list[dict[str, Any]], arm: str, predicate: Any) -> dict[str, dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for record in _ok(records):
        if record.get("arm") != arm or not predicate(record):
            continue
        chosen[str(record["item_id"])] = record
    return chosen


def _paired(
    records: list[dict[str, Any]],
    baseline: str,
    causal: str,
    predicate: Any,
) -> dict[str, Any] | None:
    base = _aligned(records, baseline, predicate)
    caus = _aligned(records, causal, predicate)
    keys = sorted(set(base) & set(caus))
    if not keys:
        return None
    base_rate = sum(1 for key in keys if base[key].get("exact")) / len(keys)
    caus_rate = sum(1 for key in keys if caus[key].get("exact")) / len(keys)
    return {
        "n": len(keys),
        "baseline": base_rate,
        "causal": caus_rate,
        "delta": caus_rate - base_rate,
    }


def _cost(records: list[dict[str, Any]]) -> float:
    total = 0.0
    for record in records:
        usage = record.get("usage") or {}
        total += float(usage.get("cost_usd") or 0.0)
    return total


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_arm[str(record.get("arm"))].append(record)
    arms = sorted(by_arm, key=lambda name: ARM_ORDER.index(name) if name in ARM_ORDER else 99)
    pair = _model_pair(arms)
    later = lambda record: int(record.get("position") or 0) >= 2
    first = lambda record: int(record.get("position") or 0) == 1
    headline = None
    position_1 = None
    by_type: dict[str, dict[str, Any] | None] = {}
    if pair is not None:
        headline = _paired(records, pair[0], pair[1], later)
        position_1 = _paired(records, pair[0], pair[1], first)
        types = sorted({str(record.get("edit_type")) for record in records if record.get("edit_type")})
        for kind in types:
            by_type[kind] = _paired(
                records,
                pair[0],
                pair[1],
                lambda record, kind=kind: int(record.get("position") or 0) >= 2 and record.get("edit_type") == kind,
            )
    leaks = sum(int(record.get("later_row_leak") or 0) for record in records)
    arm_rows = []
    for arm in arms:
        rows = by_arm[arm]
        scored = _ok(rows)
        arm_rows.append(
            {
                "arm": arm,
                "label": _label(arm),
                "n": len(scored),
                "errors": sum(1 for row in rows if row.get("error")),
                "exact": _rate(scored),
                "later_exact": _rate([row for row in scored if int(row.get("position") or 0) >= 2]),
                "position_1_exact": _rate([row for row in scored if int(row.get("position") or 0) == 1]),
                "cost_usd": _cost(rows),
                "tool_called": (
                    sum(1 for row in scored if row.get("tool_called")) / len(scored) if scored else None
                ),
            }
        )
    return {
        "arms": arm_rows,
        "pair": {"baseline": pair[0], "causal": pair[1]} if pair else None,
        "headline_later": headline,
        "position_1": position_1,
        "later_by_type": by_type,
        "later_row_leaks": leaks,
    }


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f} pp"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = ["# NCCI PTP change bench", ""]
    pair = summary.get("pair")
    headline = summary.get("headline_later")
    if pair and headline:
        lines.append(
            f"Paired headline, positions 2-5, {_label(pair['causal'])} minus {_label(pair['baseline'])}: "
            f"{_signed(headline['delta'])} "
            f"({_pct(headline['causal'])} vs {_pct(headline['baseline'])}, n={headline['n']})."
        )
    else:
        lines.append("Paired headline needs a baseline arm and its matching causal arm on the same claims.")
    lines.append("")
    lines.append(f"Later-claim lookup payloads that contained a row: {summary['later_row_leaks']}.")
    lines.append("")
    lines.append("| Arm | Exact | Positions 2-5 | Position 1 | Tool | Cost | Errors |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in summary["arms"]:
        lines.append(
            f"| {row['label']} | {_pct(row['exact'])} | {_pct(row['later_exact'])} | "
            f"{_pct(row['position_1_exact'])} | {_pct(row['tool_called'])} | "
            f"${row['cost_usd']:.4f} | {row['errors']} |"
        )
    lines.append("")
    position_1 = summary.get("position_1")
    if position_1:
        lines.append(
            f"Position 1 paired delta: {_signed(position_1['delta'])} "
            f"({_pct(position_1['causal'])} vs {_pct(position_1['baseline'])}, n={position_1['n']}). "
            "Position 1 is reported and is not the win."
        )
        lines.append("")
    if summary["later_by_type"]:
        lines.append("## Positions 2-5 by edit type")
        lines.append("")
        lines.append("| Edit type | Causal | Baseline | Delta | n |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for kind, paired in summary["later_by_type"].items():
            if not paired:
                lines.append(f"| {kind} | n/a | n/a | n/a | 0 |")
                continue
            lines.append(
                f"| {kind} | {_pct(paired['causal'])} | {_pct(paired['baseline'])} | "
                f"{_signed(paired['delta'])} | {paired['n']} |"
            )
        lines.append("")
    return "\n".join(lines)


def emit_summary(run_dir: Path) -> str:
    records = read_jsonl(run_dir / "records.jsonl")
    text = render_markdown(summarize(records))
    (run_dir / "summary.md").write_text(text + "\n", encoding="utf-8")
    return text
