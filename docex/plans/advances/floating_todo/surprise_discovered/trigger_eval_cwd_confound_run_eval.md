# `run_eval.py` inherits the trigger-eval cwd confound, and its cwd is load-bearing

Found during mod 135 (advance 006). The `run_suite.py` half was **fixed** in that mod; this file
books the half that could not be fixed the same way.

## The confound

A trigger eval measures whether a skill's *description* routes a query to it. That measurement is
only valid if loading the skill is the **only** route to the doctrine. If the model under test can
reach the doctrine files some other way, it will — and the run scores ∅ or a misroute, indicting a
description that was never at fault.

`subprocess.Popen` inherits the parent's cwd unless told otherwise. Both trigger runners shell out
to `claude -p`, and both were running the child inside the `jean_baudrillard` repo, where
`doctrine/` sits in the working directory. Observed directly in mod 135: for the query *"where in
`infra.yml` does the surfaces block go for a core service, and what actually changes in the
compiled output once i declare one?"*, the model's **first tool call** was

```
Bash  grep -rn "surfaces" doctrine/ --include=*.md | head -50
```

No downstream operator has that shortcut. In a real project the doctrine is reachable only through
the resident stratum and the skills.

## Measured impact — it is not cosmetic in either direction

Mod 135 re-measured two supposed trigger holes on a corrected harness. The confound had corrupted
both, in **opposite** directions:

| Query | repo cwd (confounded) | empty cwd (corrected) |
| ----- | --------------------- | --------------------- |
| `infra-compile` surfaces-authoring | 0/5 → ∅ | **5/5 → `contracts`** |
| `contracts` health diagnostic | 0/5 → ∅ | **4/5 → `contracts`** (passes) |

So the confound both **invented** a hole (`contracts` was fine) and **disguised** a real one
(`infra-compile` was not falling through to ∅, it was being poached 5/5 by a sibling — a far more
serious finding, and invisible while the grep shortcut existed). A confounded instrument is worse
than a missing one: it produced two findings, one false and one mischaracterized, and a description
edit was made on each.

## Fixed in mod 135 — `run_suite.py`

`detect_triggered_skill` now runs each query in its own `tempfile.mkdtemp()` sandbox
(`cwd=sandbox`, removed in the `finally`), and the module docstring's "Confound to keep in mind"
block became a numbered list with this as confound 2, including the instruction never to drop the
argument.

## Not fixed — `run_eval.py`

`run_eval.py:89` passes `cwd=project_root` **deliberately**. It is not an oversight: unlike
`run_suite.py`, which installs the competing set via `--plugin-dir`, `run_eval.py` installs the
single skill under test by writing into `<project_root>/.claude/commands` (line 53) and relies on
the child's cwd to discover it. Pointing its cwd at an empty temp dir would break skill
installation outright.

The fix is therefore a small restructure, not a one-line change. Options, in rough order of
preference:

1. **Switch `run_eval.py` to `--plugin-dir`**, matching `run_suite.py`, then sandbox the cwd
   exactly as `run_suite.py` now does. Removes the `.claude/commands` write entirely and unifies
   the two runners' installation story. Needs a check that the single-skill path does not depend on
   command-style invocation for anything else.
2. **Scaffold the sandbox**: create the temp dir, write `<sandbox>/.claude/commands/<skill>.md`
   into it, and point cwd there. Smaller change, keeps the existing mechanism, but keeps two
   installation stories alive.

`run_loop.py` drives `run_eval.py`, so it inherits whatever is decided and needs no separate fix.

## The outcome-eval path is exposed by the same class, but differently

Outcome evals run as in-session subagents inside the repo, where the doctrine is genuinely present
and reachable; isolation there is enforced by *instruction* ("work only from general knowledge, do
not read doctrine files"), not by cwd. That is a weaker guarantee, and it is now stated plainly
rather than assumed — mod 135 added `### Isolation` to
`skills/skill-iteration/references/evaluation.md`, which fixes a dangling pointer and records the
ceiling: the baseline arm cannot un-read the Resident stratum its system prompt loads, so the
achievable delta is navigation into the conditional stratum only.

No code change is proposed for the outcome path. The honest statement of the limit is the fix,
because the alternative — running outcome arms outside the harness entirely — costs more than the
measurement is worth.

## Why this matters beyond the two runners

Both of this advance's eval gates were run with a confounded instrument, and one of them changed a
durable artifact (a skill description) on the strength of it. The generalizable rule, worth holding
onto when any future eval is built: **an eval that measures navigation must control every route to
the destination, and cwd is a route.** The same question should be asked of any future runner
before its first reported number.
