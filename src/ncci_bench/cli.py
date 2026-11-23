"""Command line for the PTP change-file bench."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ncci_bench.payer import PAYER_SESSIONS, build_payer_tasks
from ncci_bench.providers import Client, load_dotenv, missing_keys, parse_arms
from ncci_bench.report import emit_summary
from ncci_bench.runner import append_jsonl, completed_pairs, run_item
from ncci_bench.tasks import GATE_SESSIONS, SESSION_COUNT, load_tasks, slice_sessions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare a baseline, causal reflection, and Claude on PTP edits.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the pinned PTP claims.")
    run.add_argument(
        "--arms",
        default="glm-baseline,glm-causal",
        help=(
            "Comma-separated: glm-baseline, glm-api, glm-causal, deepseek-baseline, "
            "deepseek-causal, inkling-baseline, inkling-causal, claude-haiku, claude-sonnet, claude-opus."
        ),
    )
    run.add_argument(
        "--episode",
        choices=("payer", "table-off"),
        default="payer",
        help=(
            "payer leaves the lookup on and rejects modifier 59 until the claim is resubmitted with XS. "
            "table-off hides the edit after claim 1. payer is the default."
        ),
    )
    run.add_argument(
        "--sessions",
        type=int,
        default=1,
        help=(
            f"First N sessions. payer is 1..{PAYER_SESSIONS}. "
            f"table-off is 1..{SESSION_COUNT} ({GATE_SESSIONS} is 30 claims)."
        ),
    )
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--max-tokens", type=int, default=2048)
    run.add_argument("--feedback-max-tokens", type=int, default=256)
    run.add_argument("--output", default="runs")
    run.add_argument("--run-id", default=None)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--dry-run", action="store_true", help="Print the sample. No API calls.")

    report = sub.add_parser("report", help="Reprint summary.md from a finished run.")
    report.add_argument("run", type=Path)

    args = parser.parse_args(argv)
    load_dotenv()
    if args.command == "report":
        print(emit_summary(args.run), end="")
        return
    _run(args)


def _load_items(args: argparse.Namespace) -> list:
    if args.episode == "payer":
        if args.sessions < 1 or args.sessions > PAYER_SESSIONS:
            raise SystemExit(f"--sessions must be 1..{PAYER_SESSIONS} for --episode payer")
        return slice_sessions(build_payer_tasks(), args.sessions)
    if args.sessions < 1 or args.sessions > SESSION_COUNT:
        raise SystemExit(f"--sessions must be 1..{SESSION_COUNT}")
    return slice_sessions(load_tasks(), args.sessions)


def _run(args: argparse.Namespace) -> None:
    items = _load_items(args)
    arms = parse_arms(args.arms)
    if args.dry_run:
        _print_dry_run(items, arms)
        return
    missing = missing_keys(arms)
    if missing:
        raise SystemExit("Missing API keys: " + ", ".join(missing) + ". Copy .env.example to .env.")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(args.output) / run_id
    if root.exists() and any(root.iterdir()) and not args.resume:
        raise SystemExit(f"{root} already exists. Pass --resume to continue it, or omit --run-id to start a new run.")
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "episode": args.episode,
                "sessions": args.sessions,
                "claims": len(items),
                "arms": [arm.name for arm in arms],
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    path = root / "records.jsonl"
    done = completed_pairs(path) if args.resume else set()
    client = Client()
    try:
        for item in items:
            for arm in arms:
                if (arm.name, item.item_id) in done:
                    continue
                record = run_item(
                    client=client,
                    arm=arm,
                    item=item,
                    run_id=run_id,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    feedback_max_tokens=args.feedback_max_tokens,
                )
                append_jsonl(path, record)
                usage = record.get("usage") or {}
                cost = usage.get("cost_usd")
                if record.get("episode") == "payer":
                    first = "yes" if record.get("first_try") else "no"
                    mark = str(record.get("disposition") or "miss")
                    if record.get("error"):
                        mark = "error"
                    print(
                        f"{arm.name} {item.item_id} {mark} first={first} "
                        f"submits={record.get('round_trips')} lookups={record.get('lookup_count')} "
                        f"${float(cost or 0):.4f}",
                        flush=True,
                    )
                else:
                    mark = "exact" if record.get("exact") else "miss"
                    if record.get("error"):
                        mark = "error"
                    print(
                        f"{arm.name} {item.item_id} {mark} "
                        f"lookups={record.get('lookup_count')} ${float(cost or 0):.4f}",
                        flush=True,
                    )
    finally:
        client.close()
    print(emit_summary(root), end="")


def _print_dry_run(items: list, arms: list) -> None:
    sessions: list[str] = []
    for item in items:
        if item.session_key not in sessions:
            sessions.append(item.session_key)
    episode = items[0].meta.get("episode") if items else "table-off"
    print(f"episode {episode if episode == 'payer' else 'table-off'}")
    print(f"sessions {len(sessions)}")
    print(f"claims {len(items)}")
    print("arms " + ", ".join(arm.name for arm in arms))
    for key in sessions:
        claims = [item for item in items if item.session_key == key]
        first = claims[0]
        print(
            f"{key} {first.meta['edit_type']} {first.meta['column_1']}/{first.meta['column_2']} "
            f"n={len(claims)} gold={first.gold_text.replace(chr(10), ' | ')}"
        )
    print("no API calls")
