#!/usr/bin/env python3
"""Suite-level trigger eval.

Given the full competing set of skill descriptions, which skill (if any) does Claude reach
for, per query? This is the cross-skill adaptation of the vendored single-skill trigger
eval (`../vendor/skill-creator/scripts/run_eval.py`): instead of testing one description in
isolation and returning a boolean, it installs ALL doctrine skills (via the real plugin),
runs each query, and records WHICH skill triggered — so it surfaces trigger-stealing across
the competing set, not just one skill's hit rate.

Scores each query's detected skill against the `expect` label in queries.json and reports
per-skill recall & precision, overall routing accuracy, and a confusion matrix.

Detection mirrors run_eval: stream-parse `claude -p --include-partial-messages` for the
first `Skill` / `SlashCommand` tool_use (or a `Read` of a skill's SKILL.md) whose input
names one of the competing skills. No competing-skill invocation → recorded as None.

Known confounds (documented in README.md): personal skills under ~/.claude/skills are
visible to `claude -p` regardless of cwd; only `docex-edit` overlaps a plugin skill by bare
name, so its row is the one to read with mild suspicion until the stale copies are gone.
"""

import argparse
import json
import os
import select
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # …/jean_baudrillard
QUERIES = Path(__file__).resolve().parent / "queries.json"


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

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
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
        return None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


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
    args = ap.parse_args()

    spec = json.loads(Path(args.queries).read_text())
    skills = spec["competing_skills"]
    queries = spec["queries"]
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
    for query, gots in runs.items():
        norm = [g if g is not None else "∅" for g in gots]
        modal = Counter(norm).most_common(1)[0][0]
        got = None if modal == "∅" else modal
        expect = by_query[query]["expect"]
        results.append({
            "query": query,
            "expect": expect,
            "got": got,
            "runs": gots,
            "correct": got == expect,
            "note": by_query[query].get("note", ""),
        })

    total = len(results)
    correct = sum(1 for r in results if r["correct"])

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
        "summary": {"total": total, "correct": correct, "accuracy": round(correct / total, 3)},
        "recall": {("none" if k is None else k): v for k, v in recall.items()},
        "precision": {("none" if k is None else k): v for k, v in precision.items()},
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "results": results,
    }

    # Human-readable summary to stderr.
    print(f"\nRouting accuracy: {correct}/{total} ({report['summary']['accuracy']:.0%})", file=sys.stderr)
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
