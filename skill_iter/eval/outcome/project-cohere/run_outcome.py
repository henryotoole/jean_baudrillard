#!/usr/bin/env python3
"""One-command outcome eval for the `project-cohere` skill.

Runs the whole loop the folder README describes, per state and per configuration
(with-skill and no-skill baseline), and prints the delta-driver pass gap that is
the skill's measured value.

    assemble ─(Python)→  scratch git repo for the state
    run      ─(claude -p)→ cohere the scratch project (skill / baseline prompt)
    capture  ─(Python)→  diff the run produced vs the fixture baseline
    grade    ─(claude -p)→ grade the diff against the case's expectations
    rollup   ─(Python)→  with-skill vs baseline, over N runs

The two LLM steps are headless `claude -p` subprocesses — the same mechanism the
trigger runners (run_eval.py / run_suite.py) use — so grading needs an LLM but
not an interactive agent. Runs happen with `--permission-mode bypassPermissions`
inside a throwaway scratch repo created OUTSIDE this repository, so the model can
edit fixture docs without prompts and nothing it does touches the doctrine repo.

Runs fan out across `--num-workers` threads (default 4); each unit is independent
(own scratch repo, own run + grade), so parallelism only compresses wall-clock —
same results, same cost. Keep the worker count modest: each worker drives a cohere
run AND a grader, so it caps concurrent `claude -p` load. Timed-out / errored runs
are recorded separately and excluded from the pass rate (shown as `(N errored)`) —
watch that count as the canary for too many workers or hitting API limits.

Examples:
    python3 run_outcome.py --runs 3                       # full suite, 3 runs/config
    python3 run_outcome.py --runs 3 --num-workers 6       # ...faster, more concurrent load
    python3 run_outcome.py --num-workers 1                # force sequential
    python3 run_outcome.py --state unimplemented --runs 1 # one case, smoke
    python3 run_outcome.py --state coherent --configs with_skill --runs 1
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import run_fixture

HERE = Path(__file__).resolve().parent
EVALS = HERE / "evals.json"
GRADER_MD = HERE.parents[1] / "agents" / "grader.md"          # skill_iter/eval/agents/grader.md
DEFAULT_SKILL = HERE.parents[3] / "skills" / "project-cohere"  # $jb/skills/project-cohere

CONFIGS = ("with_skill", "baseline")


def _claude(prompt: str, cwd: str | None, model: str | None, timeout: int,
            permission_mode: str | None = None, stdin: bool = False) -> str:
    """Invoke `claude -p` headless and return its stdout (the final text)."""
    cmd = ["claude", "-p"]
    if not stdin:
        cmd.append(prompt)
    if model:
        cmd += ["--model", model]
    if permission_mode:
        cmd += ["--permission-mode", permission_mode]
    # WHY: the CLAUDECODE guard blocks nesting `claude -p` inside a Claude Code
    # session; safe to drop for programmatic subprocess use (see run_eval.py).
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.run(
        cmd,
        input=prompt if stdin else None,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def _claude_run(prompt: str, cwd: str, model: str | None, timeout: int,
                permission_mode: str) -> dict:
    """Run a cohere via `claude -p` and return a distilled transcript.

    Uses stream-json so the grader gets both the tool-call trace (which files
    the run actually inspected/edited) and the final report text. This is what
    lets grading distinguish "noticed the issue and deferred to the operator"
    from "never noticed" — both leave an empty diff, but only the former shows
    the run inspecting the relevant files and naming the conflict in its report.
    (Headless `claude -p` offers no interactive question tool, so a deferral can
    only appear as final-report text, never as a tool call — verified empirically.)
    """
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", permission_mode]
    if model:
        cmd += ["--model", model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p run failed (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
    return _distill_stream(proc.stdout)


def _distill_stream(raw: str) -> dict:
    """Parse stream-json stdout into {final_text, tool_calls, usage, cost_usd, num_turns}.

    Usage/cost come from the harness's terminal `result` event — the harness already
    reports them; we just keep them instead of dropping them on the floor. `usage` is
    the run's cumulative token breakdown; `cost_usd` is the harness's own dollar figure.
    """
    texts: list[str] = []
    tool_calls: list[dict] = []
    final_text = ""
    usage: dict = {}
    cost_usd = None
    num_turns = None
    session_id = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not session_id and e.get("session_id"):
            session_id = e["session_id"]
        etype = e.get("type")
        if etype == "assistant":
            for c in e.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    texts.append(c["text"])
                elif c.get("type") == "tool_use":
                    tool_calls.append({
                        "name": c.get("name"),
                        "target": _summarize_input(c.get("input", {})),
                    })
        elif etype == "result":
            if isinstance(e.get("result"), str):
                final_text = e["result"]
            if isinstance(e.get("usage"), dict):
                usage = e["usage"]
            if isinstance(e.get("total_cost_usd"), (int, float)):
                cost_usd = e["total_cost_usd"]
            if isinstance(e.get("num_turns"), int):
                num_turns = e["num_turns"]
    return {"final_text": final_text or "\n".join(texts), "tool_calls": tool_calls,
            "usage": usage, "cost_usd": cost_usd, "num_turns": num_turns,
            "session_id": session_id}


# WHY: cache-read/creation tokens are billed and dominate a doc-reading run's footprint,
# so a meaningful "tokens" total sums all four buckets, not just input+output.
_TOKEN_KEYS = ("input_tokens", "output_tokens",
               "cache_creation_input_tokens", "cache_read_input_tokens")


def _total_tokens(usage: dict) -> int:
    return sum(int(usage.get(k, 0) or 0) for k in _TOKEN_KEYS)


def _sum_transcript(path: Path) -> tuple[int, int]:
    """Sum billed tokens (all buckets) and count assistant turns in one transcript.

    WHY dedupe on message id: Claude Code writes the same assistant message to
    the transcript 2-3 times (streaming/continuation artifacts), each copy
    carrying the identical `usage`. Each API response is billed once, so counting
    every copy over-states tokens ~3x. Deduping by `message.id` matches the
    harness's own `total_cost_usd` to within ~0.1% when the deduped tokens are
    priced (validated 2026-07-21 against token_metrics.py across 24 sessions).
    """
    total = turns = 0
    seen: set[str] = set()
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "assistant":
                    continue
                msg = e.get("message") or {}
                u = msg.get("usage")
                if not u:
                    continue
                mid = msg.get("id")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)
                total += _total_tokens(u)
                turns += 1
    except OSError:
        pass
    return total, turns


def _true_consumption(session_id: str | None) -> dict:
    """Real billed tokens for a run: the per-turn SUM over the main session PLUS every
    subagent it spawned. The `result` event's `usage` is only a final-turn snapshot and
    misses both the per-turn accumulation and all subagent work; `cost_usd` bills on this
    true total. Subagent transcripts live at <projects>/<dir>/<session_id>/subagents/
    agent-*.jsonl — a sibling subdir of the main transcript, NOT inline — so they must be
    summed separately. Located by session_id (unique) to avoid path-encoding guesswork."""
    if not session_id:
        return {}
    base = Path.home() / ".claude" / "projects"
    mains = list(base.glob(f"*/{session_id}.jsonl"))
    if not mains:
        return {}
    main = mains[0]
    main_tok, main_turns = _sum_transcript(main)
    subdir = main.parent / session_id / "subagents"
    subs = sorted(subdir.glob("*.jsonl")) if subdir.is_dir() else []
    sub_tok = sub_turns = 0
    for s in subs:
        t, tn = _sum_transcript(s)
        sub_tok += t
        sub_turns += tn
    return {"total_tokens": main_tok + sub_tok, "main_tokens": main_tok,
            "main_turns": main_turns, "subagent_tokens": sub_tok,
            "subagent_turns": sub_turns, "n_subagents": len(subs)}


def _summarize_input(inp: dict) -> str:
    """Compact one-line summary of a tool_use input for the trace."""
    if not isinstance(inp, dict):
        return ""
    for k in ("file_path", "path", "pattern", "command", "query", "prompt"):
        if k in inp:
            v = " ".join(str(inp[k]).split())
            return v if len(v) <= 120 else v[:117] + "..."
    return ", ".join(sorted(inp.keys()))[:120]


def _run_prompt(config: str, skill_path: Path) -> str:
    """The operator-style instruction for a cohere run, per configuration."""
    if config == "with_skill":
        return (
            "You are running a skill against a test project. Operate ONLY inside your "
            "current working directory; do not read or modify anything elsewhere on the machine.\n\n"
            f"Read the skill at {skill_path}/SKILL.md and follow its process exactly to "
            "\"cohere\" this project's core planning docs. When the skill directs running its "
            f"word-count executor, it lives at {skill_path}/executor/word_count.py — run it with "
            "`--root` set to your current working directory.\n\n"
            "Make whatever documentation edits the skill directs. Do not run `git commit`; leave "
            "your changes in the working tree. When done, give a concise summary of exactly what "
            "you changed and why (which files, which sections)."
        )
    return (
        "Operate ONLY inside your current working directory; do not read or modify anything "
        "elsewhere on the machine.\n\n"
        "This is a small hexagonal backend project. Its architecture and module documentation "
        "live under plans/core/ and the actual code lives under core/. Make the core planning "
        "docs internally consistent and consistent with what the code actually does; where a doc "
        "and the code disagree, correct the discrepancy. Work ONLY from general software-"
        "engineering knowledge — do NOT read any skill files or doctrine files.\n\n"
        "Do not run `git commit`; leave your changes in the working tree. When done, give a "
        "concise summary of exactly what you changed and why (which files, which sections)."
    )


def _grade(expectations: list[str], run_out: dict, cap: dict, model: str | None,
           timeout: int) -> dict:
    """Grade the captured diff + distilled transcript against the case expectations."""
    grader_role = GRADER_MD.read_text()
    numbered = "\n".join(f"[{i}] {e}" for i, e in enumerate(expectations))
    diff_block = cap.get("diff", "") or "(no diff — the run produced NO changes)"
    trace = run_out.get("tool_calls", [])
    trace_block = "\n".join(f"- {t['name']} {t['target']}" for t in trace) or "(no tool calls recorded)"
    prompt = (
        f"{grader_role}\n\n"
        "---\n\n"
        "# This grading run\n\n"
        "You are grading the `project-cohere` skill. Its output is not files in an outputs_dir "
        "— it is the DIFF the run produced against the project's baseline, plus the run's "
        "tool-call trace and final report below. Grade each expectation against that evidence. "
        "A `DELTA DRIVER` expectation is the doctrine-specific behavior the skill must get right; "
        "a `CONFIRMATORY` one is inferable and expected to pass either way.\n\n"
        "IMPORTANT — deferral vs. oversight. Some expectations require the run to DEFER a judgment "
        "to the operator (e.g. leave the masterplan alone, or not invent a doc for undocumented "
        "code) rather than act. Headless runs have NO interactive question tool, so a correct "
        "deferral appears ONLY as final-report text that (a) names the specific conflict/gap and "
        "(b) explicitly leaves the decision to the operator. An empty diff is NOT sufficient "
        "evidence of correct deferral — an agent that never noticed the issue also leaves an empty "
        "diff. Grade such an expectation PASS only with positive evidence: the final report names "
        "the specific issue AND the tool trace shows the run actually inspected the relevant files "
        "(e.g. Read the undocumented module, or diffed the two docs). If the report claims "
        "everything is consistent / found no issues, that is a FAIL for a deferral expectation.\n\n"
        f"## Run summary\n- files_changed: {cap['files_changed']}\n"
        f"- is_empty (no changes at all): {cap['is_empty']}\n"
        f"- insertions: {cap['insertions']}, deletions: {cap['deletions']}\n\n"
        f"## The diff\n```diff\n{diff_block}\n```\n\n"
        f"## The run's tool-call trace ({len(trace)} calls)\n{trace_block}\n\n"
        f"## The run's final report (its own words)\n{run_out.get('final_text', '')}\n\n"
        f"## Expectations to grade (preserve these indices)\n{numbered}\n\n"
        "# Output\n"
        "Do NOT write any file. Output ONLY a JSON object, no prose before or after, shaped:\n"
        '{\"expectations\": [{\"index\": 0, \"text\": \"...\", \"passed\": true, \"evidence\": \"...\"}]}\n'
        "One entry per expectation above, same indices, in order."
    )
    raw = _claude(prompt, cwd=None, model=model, timeout=timeout, stdin=True)
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    """Best-effort extraction of a JSON object from a model's stdout."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start:end + 1])
    raise ValueError(f"could not parse grader JSON from: {raw[:300]}")


def _is_delta(text: str) -> bool:
    return "DELTA DRIVER" in text.upper()


def run_case(case: dict, config: str, run_idx: int, skill_path: Path, model: str | None,
             run_timeout: int, grade_timeout: int) -> dict:
    """Assemble → run → capture → grade one (case, config, run)."""
    state = case["fixture"]
    scratch = Path(tempfile.mkdtemp(prefix=f"cohere-{state}-{config}-{run_idx}-"))
    info = run_fixture.assemble(state, out=str(scratch), force=True)

    prompt = _run_prompt(config, skill_path)
    run_out = _claude_run(prompt, cwd=info["scratch"], model=model, timeout=run_timeout,
                          permission_mode="bypassPermissions")

    cons = _true_consumption(run_out.get("session_id"))

    cap = run_fixture.capture(info["scratch"], baseline=info["baseline_commit"], with_diff=True)
    grading = _grade(case["expectations"], run_out, cap, model, grade_timeout)

    graded = grading.get("expectations", [])
    # Match grader results back to originals by index (fall back to order).
    by_index = {g.get("index", i): g for i, g in enumerate(graded)}
    results = []
    for i, text in enumerate(case["expectations"]):
        g = by_index.get(i, {})
        results.append({
            "text": text,
            "delta_driver": _is_delta(text),
            "passed": bool(g.get("passed")),
            "evidence": g.get("evidence", "(no grader entry)"),
        })
    delta = [r for r in results if r["delta_driver"]]
    return {
        "state": state, "config": config, "run": run_idx,
        "is_empty": cap["is_empty"], "files_changed": cap["files_changed"],
        "expectations": results,
        "delta_pass": sum(r["passed"] for r in delta),
        "delta_total": len(delta),
        "all_pass": sum(r["passed"] for r in results),
        "all_total": len(results),
        "tool_calls": run_out["tool_calls"],
        "final_text": run_out["final_text"],
        # Cost of the cohere run itself (grader run excluded). total_tokens is the TRUE
        # per-turn sum over the main session + every subagent (from the transcripts);
        # cost_usd bills on this. final_ctx_snapshot is the result-event `usage` figure,
        # kept only for reference — it is a final-turn snapshot and undercounts ~4x.
        "total_tokens": cons.get("total_tokens", _total_tokens(run_out.get("usage", {}))),
        "main_tokens": cons.get("main_tokens"),
        "subagent_tokens": cons.get("subagent_tokens"),
        "n_subagents": cons.get("n_subagents"),
        "num_turns": run_out.get("num_turns"),
        "cost_usd": run_out.get("cost_usd"),
        "final_ctx_snapshot": _total_tokens(run_out.get("usage", {})),
        "session_id": run_out.get("session_id"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", help="one state (default: every case in evals.json)")
    ap.add_argument("--configs", default="with_skill,baseline",
                    help="comma-separated: with_skill,baseline (default: both)")
    ap.add_argument("--runs", type=int, default=1, help="runs per config (default 1)")
    ap.add_argument("--model", default=None, help="model for the claude -p calls")
    ap.add_argument("--skill-path", default=str(DEFAULT_SKILL), help="path to the project-cohere skill dir")
    ap.add_argument("--run-timeout", type=int, default=600, help="seconds per cohere run")
    ap.add_argument("--grade-timeout", type=int, default=300, help="seconds per grade")
    ap.add_argument("--num-workers", type=int, default=4,
                    help="concurrent runs (default 4). Each worker spawns a cohere run AND a "
                         "grader, so this also caps concurrent claude -p load; keep it modest to "
                         "avoid API rate limits / contention that could time a run out.")
    ap.add_argument("--out", help="write full results JSON here")
    args = ap.parse_args()
    if args.num_workers < 1:
        sys.exit("error: --num-workers must be >= 1")

    cases = json.loads(EVALS.read_text())["evals"]
    if args.state:
        cases = [c for c in cases if c["fixture"] == args.state]
        if not cases:
            sys.exit(f"error: no case with fixture '{args.state}' in {EVALS}")
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    for c in configs:
        if c not in CONFIGS:
            sys.exit(f"error: unknown config '{c}' (choose from {CONFIGS})")
    skill_path = Path(args.skill_path).resolve()

    # Each (case, config, run) is fully independent — its own mkdtemp scratch repo,
    # its own claude -p run and grade, no shared mutable state — so they fan out
    # safely. Threads (not processes): each unit just blocks on subprocesses.
    work = [(case, config, r + 1)
            for case in cases for config in configs for r in range(args.runs)]
    print(f"dispatching {len(work)} run(s) across {args.num_workers} worker(s)...",
          file=sys.stderr, flush=True)

    all_runs = []
    with ThreadPoolExecutor(max_workers=args.num_workers) as ex:
        fut_to_item = {
            ex.submit(run_case, case, config, run_idx, skill_path,
                      args.model, args.run_timeout, args.grade_timeout): (case, config, run_idx)
            for case, config, run_idx in work
        }
        for fut in as_completed(fut_to_item):
            case, config, run_idx = fut_to_item[fut]
            label = f"{case['fixture']}/{config}/run{run_idx}"
            try:
                res = fut.result()
                all_runs.append(res)
                tok = res.get("total_tokens") or 0
                sub = res.get("subagent_tokens") or 0
                ns = res.get("n_subagents")
                cost = res.get("cost_usd")
                cost_s = f", ${cost:.3f}" if isinstance(cost, (int, float)) else ""
                sub_s = f", {sub/1000:.0f}k in {ns} sub" if ns else ""
                print(f"    done {label}: delta {res['delta_pass']}/{res['delta_total']}, "
                      f"all {res['all_pass']}/{res['all_total']}, {tok/1000:.0f}k tok{sub_s}{cost_s}",
                      file=sys.stderr, flush=True)
            except Exception as e:
                print(f"    FAILED {label}: {e}", file=sys.stderr, flush=True)
                all_runs.append({"state": case["fixture"], "config": config, "run": run_idx,
                                 "error": str(e)})

    _summarize(cases, configs, all_runs)
    if args.out:
        Path(args.out).write_text(json.dumps({"runs": all_runs}, indent=2))
        print(f"\nfull results: {args.out}", file=sys.stderr)


def _rate(runs: list[dict], key_pass: str, key_total: str) -> float | None:
    vals = [r[key_pass] / r[key_total] for r in runs if r.get(key_total)]
    return sum(vals) / len(vals) if vals else None


def _cost_line(runs: list[dict]) -> dict:
    """Mean tokens/cost per run for a config. tok/cost are None when unreported."""
    toks = [r["total_tokens"] for r in runs if r.get("total_tokens")]
    subs = [r["subagent_tokens"] for r in runs if r.get("subagent_tokens") is not None]
    costs = [r["cost_usd"] for r in runs if isinstance(r.get("cost_usd"), (int, float))]
    tok = sum(toks) / len(toks) if toks else None
    sub = sum(subs) / len(subs) if subs else None
    usd = sum(costs) / len(costs) if costs else None
    label = "no token data" if tok is None else f"{tok/1000:.0f}k tok/run"
    if sub is not None and tok:
        label += f" ({sub/tok*100:.0f}% subagent)"
    if usd is not None:
        label += f"  ${usd:.3f}/run"
    return {"tok": tok, "sub": sub, "usd": usd, "label": label}


def _summarize(cases: list[dict], configs: list[str], all_runs: list[dict]) -> None:
    print("\n=== project-cohere outcome eval ===")
    for case in cases:
        state = case["fixture"]
        print(f"\n[{state}]")
        rates = {}
        cost = {}
        for config in configs:
            runs = [r for r in all_runs if r["state"] == state and r["config"] == config and "error" not in r]
            errs = [r for r in all_runs if r["state"] == state and r["config"] == config and "error" in r]
            dr = _rate(runs, "delta_pass", "delta_total")
            ar = _rate(runs, "all_pass", "all_total")
            rates[config] = dr
            dr_s = "n/a" if dr is None else f"{dr*100:.0f}%"
            ar_s = "n/a" if ar is None else f"{ar*100:.0f}%"
            err_s = f"  ({len(errs)} errored)" if errs else ""
            cost[config] = _cost_line(runs)
            print(f"  {config:11s} delta-driver={dr_s:>5}  all={ar_s:>5}  "
                  f"n={len(runs)}  {cost[config]['label']}{err_s}")
        if "with_skill" in rates and "baseline" in rates and None not in rates.values():
            gap = rates["with_skill"] - rates["baseline"]
            print(f"  {'DELTA':11s} {gap*100:+.0f} pts (skill value on delta drivers)")
        # Overhead of the skill vs baseline — the price of that value. Lead with $:
        # the skill fans out to subagents, whose tokens the parent session's `usage`
        # event does NOT include but whose spend `total_cost_usd` DOES. So $ is the
        # honest cross-config figure; the token delta only compares parent sessions.
        if cost.get("with_skill") and cost.get("baseline"):
            ws, bl = cost["with_skill"], cost["baseline"]
            if ws["usd"] is not None and bl["usd"]:
                print(f"  {'COST':11s} {ws['usd']/bl['usd']:.1f}x cost/run "
                      f"(${ws['usd']:.3f} vs ${bl['usd']:.3f})")
            elif ws["tok"] is not None and bl["tok"]:
                print(f"  {'COST':11s} {ws['tok']/bl['tok']:.1f}x parent-session tok/run "
                      f"({(ws['tok']-bl['tok'])/1000:+.0f}k)")


if __name__ == "__main__":
    main()