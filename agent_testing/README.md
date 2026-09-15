# agent_testing

Outcome tests for doctrine subagents — does an agent effect the *correct concrete
change* (to code or docs) when it runs? This is distinct from `skill_iter/`, which
measures whether skill *descriptions* trigger and whether a skill routes to the
right doctrine. Agent runs effect real change and are token-heavy, so they are run
**deliberately** — when checking or improving an agent — not on every cut.

## Convention (the only thing mandated)

Each agent under test gets a subfolder named for the agent, containing a
**`test.md`** — the fixed *interface* a test-orchestrator reads to run that agent's
tests. `test.md` is the only required file; everything else in a subfolder is
free-form *interior* that `test.md` references (fixtures, seed repositories, helper
scripts, grading rubrics).

```
agent_testing/
└── <agent-name>/
    ├── test.md        # required — the interface
    └── <anything>     # conditional — interior referenced by test.md
```

Test internals are built **agent by agent**; no shared internal pattern (a
with/without delta, a fixed harness) is imposed yet. A pattern may emerge and be
standardized later — for now, only the `test.md` interface is common.
