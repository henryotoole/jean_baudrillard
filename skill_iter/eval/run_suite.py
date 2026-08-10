#!/usr/bin/env python3
"""Suite-level trigger eval.

Given the full competing set of skill descriptions, which skill (if any) does Claude reach
for, per query? This is the cross-skill adaptation of the single-skill trigger eval
(`run_eval.py`, forked from Anthropic's skill-creator): instead of testing one description
in isolation and returning a boolean, it installs ALL doctrine skills (via the real plugin),
runs each query, and records WHICH skill triggered — so it surfaces trigger-stealing across
the competing set, not just one skill's hit rate.

Scores each query's detected skill against the `expect` label in queries.json and reports
per-skill recall & precision, overall routing accuracy, and a confusion matrix.

Detection mirrors run_eval: stream-parse `claude -p --include-partial-messages` for the
first `Skill` / `SlashCommand` tool_use (or a `Read` of a skill's SKILL.md) whose input
names one of the competing skills. No competing-skill invocation → recorded as None.

The competing set comes from `competing_skills` in the queries file when present; otherwise
it is auto-discovered from `<plugin_dir>/skills/*/SKILL.md`, so a subset/focused query file
need not restate the list.

Confounds to keep in mind:

1. Personal skills under ~/.claude/skills are visible to `claude -p` regardless of cwd and can
   shadow a plugin skill that shares its bare name. Keep that directory clear of doctrine-skill
   copies before a run.
2. The child's cwd decides whether the doctrine is *greppable*. Run from this repo and the model
   can `grep doctrine/` or open `cicl.md` directly — a filesystem shortcut no downstream
   operator has, which makes a skill look unnecessary and scores as ∅. Each query therefore runs
   in its own empty temp dir (`cwd=` below), so the only route to the conditional stratum is a
   skill. Never drop that argument: without it the child inherits the runner's cwd, and a
   doctrine-file-shaped query measures the harness rather than the description.
3. A timed-out run is NOT a no-fire, and conflating the two makes saturation look like a
   trigger defect. Each `claude -p` is a whole CLI plus model round-trips, so a high
   `--num-workers` on one box drives load average past the point where queries exceed
   `--timeout` wholesale; every one of them would otherwise score ∅, i.e. as a recall failure.
   Timeouts are therefore tracked separately, excluded from the modal vote, and reported loudly.
   **If the report shows any timeouts, lower `--num-workers` and re-run before believing a
   single number in it.** Measured: 8 workers on a 73-query set produced 17% accuracy, while the
   same queries at 2-3 workers passed 3/3.
"""

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from utils import parse_skill_md

REPO_ROOT = Path(__file__).resolve().parents[2]  # …/jean_baudrillard
QUERIES = Path(__file__).resolve().parent / "queries.json"

# WHY: distinct from None so a run killed by the deadline is never scored as "no skill fired" —
# see confound 3 in the module docstring. None means "the model acted and reached for no skill".
TIMEOUT = "__TIMEOUT__"


def discover_competing_skills(plugin_dir: str) -> list[str]:
    """Skill names installed under <plugin_dir>/skills/*/SKILL.md (fallback when the
    queries file doesn't pin its own competing_skills list)."""
    skills_dir = Path(plugin_dir) / "skills"
    names = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            name, _, _ = parse_skill_md(skill_md.parent)
        except (ValueError, OSError):
            continue
        if name:
            names.append(name)
    return names


def _input_names_skill(text: str, skills: list[str]) -> str | None:
    """Return the competing skill named in a tool-input string, longest match first."""
    for name in sorted(skills, key=len, reverse=True):
        if name in text:
            return name
    return None


def detect_triggered_skill(
    query: str, skills: list[str], plugin_dir: str, timeout: int, model: str | None
) -> str | None:
    """Run one query with all skills installed; return the skill that triggered, or None."""
    cmd = [
        "claude", "-p", query,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--plugin-dir", plugin_dir,
    ]
    if model:
        cmd.extend(["--model", model])

    # The CLAUDECODE guard blocks nesting claude -p inside a session; safe to drop here.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    # WHY: an empty cwd is part of the measurement — see confound 2 in the module docstring.
    sandbox = tempfile.mkdtemp(prefix="trigger_eval_")
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=sandbox
    )
    start = time.time()
    buffer = ""
    pending_tool = None
    accumulated = ""
    try:
        while time.time() - start < timeout:
            if process.poll() is not None:
                rest = process.stdout.read()
                if rest:
                    buffer += rest.decode("utf-8", errors="replace")
                # drain remaining lines below, then stop
            else:
                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "stream_event":
                    se = event.get("event", {})
                    se_type = se.get("type", "")
                    if se_type == "content_block_start":
                        cb = se.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            tname = cb.get("name", "")
                            if tname in ("Skill", "SlashCommand", "Read"):
                                pending_tool = tname
                                accumulated = ""
                            else:
                                # First action is a non-routing tool → no skill triggered.
                                # Return now, before it executes (the finally kills the proc).
                                return None
                    elif se_type == "content_block_delta" and pending_tool:
                        delta = se.get("delta", {})
                        if delta.get("type") == "input_json_delta":
                            accumulated += delta.get("partial_json", "")
                            hit = _input_names_skill(accumulated, skills)
                            if hit:
                                return hit
                    elif se_type in ("content_block_stop", "message_stop"):
                        if pending_tool:
                            # First routing-tool block resolved; its match (or None) is the answer.
                            return _input_names_skill(accumulated, skills)
                        if se_type == "message_stop":
                            return None

                elif event.get("type") == "assistant":
                    # Fallback when partial messages aren't available: the first tool_use decides.
                    for ci in event.get("message", {}).get("content", []):
                        if ci.get("type") != "tool_use":
                            continue
                        if ci.get("name") in ("Skill", "SlashCommand", "Read"):
                            return _input_names_skill(json.dumps(ci.get("input", {})), skills)
                        return None

                elif event.get("type") == "result":
                    return None

            if process.poll() is not None and "\n" not in buffer:
                break
        else:
            # while-loop fell through on its condition → the deadline expired, not a decision.
            return TIMEOUT
        return None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        shutil.rmtree(sandbox, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Suite-level trigger eval for doctrine skills")
    ap.add_argument("--queries", default=str(QUERIES))
    ap.add_argument("--plugin-dir", default=str(REPO_ROOT))
    ap.add_argument("--runs-per-query", type=int, default=3)
    ap.add_argument("--num-workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--model", default=None, help="model id for claude -p (default: configured)")
    ap.add_argument("--out", default=None, help="write full JSON report here")
    ap.add_argument("--limit", type=int, default=None, help="only run the first N queries (smoke test)")
    ap.add_argument("--grep", default=None,
                    help="only run queries whose query text or note contains this substring "
                         "(case-insensitive); the full competing set is still installed")
    args = ap.parse_args()

    spec = json.loads(Path(args.queries).read_text())
    # competing_skills is optional: pinned in the queries file, else auto-discovered from the plugin.
    skills = spec.get("competing_skills") or discover_competing_skills(args.plugin_dir)
    if not skills:
        sys.exit(
            f"error: no competing skills — add a 'competing_skills' list to {args.queries} "
            f"or ensure {args.plugin_dir}/skills/*/SKILL.md exist."
        )
    queries = spec["queries"]
    if args.grep:
        needle = args.grep.lower()
        queries = [q for q in queries
                   if needle in q["query"].lower() or needle in q.get("note", "").lower()]
        if not queries:
            sys.exit(f"error: --grep {args.grep!r} matched no queries.")
    if args.limit:
        queries = queries[:args.limit]

    # Fan out runs_per_query runs of every query.
    jobs = []
    with ProcessPoolExecutor(max_workers=args.num_workers) as pool:
        fut_to_q = {}
        for q in queries:
            for _ in range(args.runs_per_query):
                fut = pool.submit(
                    detect_triggered_skill,
                    q["query"], skills, args.plugin_dir, args.timeout, args.model,
                )
                fut_to_q[fut] = q["query"]
        runs: dict[str, list] = defaultdict(list)
        done = 0
        for fut in as_completed(fut_to_q):
            try:
                runs[fut_to_q[fut]].append(fut.result())
            except Exception as e:
                print(f"warn: query failed: {e}", file=sys.stderr)
                runs[fut_to_q[fut]].append(None)
            done += 1
            print(f"\r  {done}/{len(fut_to_q)} runs complete", end="", file=sys.stderr)
        print("", file=sys.stderr)

    # Aggregate each query to its modal detected skill.
    by_query = {q["query"]: q for q in queries}
    results = []
    unscored = []
    for query, gots in runs.items():
        # Timeouts are not evidence about the description; drop them before the vote.
        scored = [g for g in gots if g != TIMEOUT]
        n_timeout = len(gots) - len(scored)
        expect = by_query[query]["expect"]
        row = {
            "query": query,
            "expect": expect,
            "runs": gots,
            "timeouts": n_timeout,
            "note": by_query[query].get("note", ""),
        }
        if not scored:
            # Every run died on the deadline — this query produced no measurement at all.
            row.update({"got": None, "correct": None, "unscored": True})
            unscored.append(row)
            continue
        norm = [g if g is not None else "∅" for g in scored]
        modal = Counter(norm).most_common(1)[0][0]
        got = None if modal == "∅" else modal
        row.update({"got": got, "correct": got == expect})
        results.append(row)

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    total_timeouts = sum(r["timeouts"] for r in results) + sum(r["timeouts"] for r in unscored)

    labels = skills + [None]
    recall, precision = {}, {}
    for s in labels:
        exp = [r for r in results if r["expect"] == s]
        gt = [r for r in results if r["got"] == s]
        recall[s] = (sum(1 for r in exp if r["got"] == s) / len(exp)) if exp else None
        precision[s] = (sum(1 for r in gt if r["expect"] == s) / len(gt)) if gt else None

    confusion = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r["expect"] if r["expect"] else "∅"][r["got"] if r["got"] else "∅"] += 1

    report = {
        "summary": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 3) if total else None,
            "timed_out_runs": total_timeouts,
            "unscored_queries": len(unscored),
        },
        "unscored": unscored,
        "recall": {("none" if k is None else k): v for k, v in recall.items()},
        "precision": {("none" if k is None else k): v for k, v in precision.items()},
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "results": results,
    }

    # Human-readable summary to stderr.
    acc = report["summary"]["accuracy"]
    print(f"\nRouting accuracy: {correct}/{total} ({acc:.0%})" if acc is not None
          else "\nRouting accuracy: n/a — nothing was scored", file=sys.stderr)
    if total_timeouts:
        # Loud on purpose: saturation is the one failure that mimics a trigger defect.
        print(
            f"\n*** WARNING: {total_timeouts} run(s) hit the {args.timeout}s deadline"
            f"{f', and {len(unscored)} quer(y/ies) produced NO measurement at all' if unscored else ''}."
            f"\n*** A timeout is not a no-fire. Lower --num-workers (currently {args.num_workers})"
            f" or raise --timeout and re-run;\n*** do not trust the numbers above until this reads 0.",
            file=sys.stderr,
        )
    print("\nMisroutes:", file=sys.stderr)
    any_miss = False
    for r in results:
        if not r["correct"]:
            any_miss = True
            print(f"  expect={r['expect']!s:<16} got={r['got']!s:<16} | {r['query'][:64]}", file=sys.stderr)
    if not any_miss:
        print("  (none)", file=sys.stderr)

    out = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(out)
        print(f"\nFull report → {args.out}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
