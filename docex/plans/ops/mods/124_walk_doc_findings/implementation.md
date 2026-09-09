# Mod 124 — Implementation Steps

Documentation-only. **Three files, five edits, zero code, zero tests.**

| File | Edits |
| ---- | ----- |
| `docex/test_projects/PRE_CUT_CHECKLIST.md` | 3 (D.9 box, D.11 box, D.11 new clock box) |
| `doctrine/infrastructure/specifics/clock.md` | 1 (new § Caveats bullet) |
| `doctrine/infrastructure/specifics/migrations.md` | 1 (append to § First-Time Release of an Env) |

All paths below are relative to the repo root `/home/ubuntu/.claude/jean_baudrillard`.

## Hard constraints

1. **Do not touch anything under `docex/test_projects/fixed/` or
   `docex/test_projects/elastic/`.** Those are inner git repos, clean at
   `v0.0.23`, and must stay that way. `PRE_CUT_CHECKLIST.md` lives at
   `docex/test_projects/` — the *outer* repo — and is the only file under that
   directory this mod may modify.
2. **No changes to `docex/src/`, `docex/tests/`, `docex/tables/`, or
   `doctrine_excerpts/`.** This mod introduces, retires, and renames nothing;
   there is no artifact-alignment ripple.
3. **Do not renumber, reorder, or reword any checklist box other than the three
   named below.** In particular, everything *after* the `bash` fence in the D.9
   and D.11 reconcile boxes — the verdict table, the "neither line appearing is
   itself a finding" paragraph, and the "why this box exists" blockquote — is
   correct and stays byte-identical.
4. **Write no `must` into the descriptive clause** about how the clock loop
   handles a failed fire (Step 4). It describes what the shape does; it is not a
   requirement. If a draft of it starts reading as normative, cut the clause
   entirely rather than soften it — that question is logged to advance 006.

---

## Step 1 — `PRE_CUT_CHECKLIST.md` D.9: correct the consumer pair

File: `docex/test_projects/PRE_CUT_CHECKLIST.md`, in `### D.9 Release stage`
(around line 369).

**Replace** these four lines:

```
- [ ] **Record both reconcile operands, and the verdict.** For each consumer
  (`api-web` and `api-worker` — they form a `uses` cycle):
  ```bash
  aws ecs describe-services --cluster docex-smoke-elastic-stage \
    --services api-web api-worker \
```

**with**:

```
- [ ] **Record both reconcile operands, and the verdict.** The consumers are the
  core services that declare a **core-targeted** `uses` entry — here `api-web`
  and `api-clock`, both targeting `api.worker`. `api.worker` itself declares
  `uses: [appdb]` only, and a backing-targeted entry never makes a consumer, so
  the worker is a target and never a consumer; **there is no `uses` cycle in
  this project.** For each consumer:
  ```bash
  aws ecs describe-services --cluster docex-smoke-elastic-stage \
    --services api-web api-clock \
```

Note the two distinct changes: the parenthetical becomes a rule-derived
statement, and `--services api-web api-worker` becomes
`--services api-web api-clock`. The `--query`, the `servicediscovery` call, and
the closing fence are untouched.

## Step 2 — `PRE_CUT_CHECKLIST.md` D.9: add the self-checking clause

Immediately **after** the closing ```` ``` ```` of the same box's `bash` fence
and **before** the existing paragraph that begins `Write both timestamps into
the walk log.`, insert this paragraph (two-space indented to stay inside the
list item, with a blank line on each side):

```
  `release`'s own output states the count it used — `N consumer(s) checked`.
  **If `N` is not 2, the consumer set has changed and this box is stale**;
  re-derive it from `infra.yml` before recording anything.
```

> **WHY this clause is the point of the mod.** The defect being repaired is a
> *static claim about `infra.yml`* that drifted silently when `infra.yml` moved.
> Correcting the pair without adding this clause would leave the drift mechanism
> fully intact. A clause keyed on what the executor prints cannot drift away
> from what the executor does. Do not drop it as redundant.

## Step 3 — `PRE_CUT_CHECKLIST.md` D.11: the same two edits

In `### D.11 Release prod` (around line 418) the reconcile box is identical to
D.9's except for the cluster name. Apply **Step 1 and Step 2 verbatim**, with the
one difference that the cluster stays `docex-smoke-elastic-prod`:

```
    --services api-web api-clock \
```

After this step, `grep -n 'api-web api-worker' docex/test_projects/PRE_CUT_CHECKLIST.md`
must return **nothing**, and `grep -c 'N consumer(s) checked' docex/test_projects/PRE_CUT_CHECKLIST.md`
must return **2**.

## Step 4 — `clock.md`: the cold-schema caveat

File: `doctrine/infrastructure/specifics/clock.md`, `## Caveats` (line 110).

**Append** a fourth bullet after the existing "A clock is invisible to staging
tests" bullet. Match the file's existing style: one bullet, one paragraph, no
sub-bullets, bold lead-in.

```md
- **A scheduled job may fire before migrations have run.** Nothing gates a core service's startup on its backing services, and migrations run *after* the stack is up: in `dev` and `test` on both foundations ([`migrations.md § Invocation Timing`](./migrations.md#invocation-timing)), and after `tofu apply` on an elastic env's [first release](./migrations.md#first-time-release-of-an-env) — where a clock is **guaranteed** to meet the window rather than merely liable to. Because a clock fires on its own schedule rather than in response to a request, it is the service most likely to reach a cold schema first, and a `relation "…" does not exist` stack trace in a clock's log on a first bring-up is expected rather than a fault. Recovery is automatic: the loop treats a failed fire as a failed fire and not a failed loop, so the job retries on its own next slot — no operator action, and no effect on the clock's health probe. **The obligation this places on a job is that a fire must tolerate a cold schema**: it may fail before doing anything at all, and the next attempt must be able to proceed as if it had never been made.
```

Three properties of this text are load-bearing and must survive any
reformatting:

1. **It is a property of the *ordering*, not a pair of observations.** The
   `dev`/`test` window is derived from the documented invocation timing plus the
   absence of any core-service readiness gate since mod 113. Only the elastic
   first release was *observed*, which is why that clause says **guaranteed**
   while the general statement says *may*. Do not rewrite this into "we saw it
   on elastic and it probably also happens in dev."
2. **The obligation is narrow on purpose.** "A fire must tolerate a cold schema"
   — not "a fire may fail for any reason". The broad form duplicates the
   idempotence caveat two bullets above and teaches less.
3. **"the loop treats a failed fire as a failed fire and not a failed loop" is
   descriptive.** It states the mechanism that makes recovery automatic. It
   names no file, cites no path, and carries no `must` — deliberately, because
   no doctrine file currently references `test_projects/`, and a globbed seed
   path would fail `linkcheck` besides.

## Step 5 — `migrations.md`: name the clock in the first-release window

File: `doctrine/infrastructure/specifics/migrations.md`,
`### First-Time Release of an Env`.

**Append** these two sentences to the end of the existing paragraph that begins
`The transient consequence:` (line 98) — same paragraph, no new blank line, no
new heading:

```md
A [`clock`](./clock.md) core service is the one guaranteed to exercise this window, because it fires on its own schedule rather than in response to a request: a job due inside it will fire, fail against the missing schema, and log a stack trace before the migration lands. That is expected and self-healing — see [`clock.md § Caveats`](./clock.md#caveats).
```

The paragraph's existing final sentence (`Subsequent releases find the env's ECS
service present …`) stays where it is; append **after** it.

## Step 6 — `PRE_CUT_CHECKLIST.md` D.11: the expectation-setting clock box

File: `docex/test_projects/PRE_CUT_CHECKLIST.md`.

In `### D.11 Release prod`, find the blockquote beginning
`> **Clock — fire → defer → drain.**` (around line 458). **Insert a new box as
the first item of that group** — after the blockquote, before the existing
`- [ ] The clock started and its schedule arrived.` box:

```md
- [ ] **Expect one failed fire before the migration lands, and do not read it as a regression.** The first-release ordering is `SSM → tofu apply → migrate`, so `api-clock` starts before the schema exists; its first `heartbeat` logs `psycopg2.errors.UndefinedTable: relation "jobs" does not exist`. This is the documented ordering ([`migrations.md § First-Time Release of an Env`](../../doctrine/infrastructure/specifics/migrations.md#first-time-release-of-an-env)) and it self-heals ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats)); the next tick ~60 s later succeeds. The same happens on the D.9 `stage` release, where no box reads the clock's log. **A clock still failing two ticks after the migration completed is a genuine finding.**
```

**No equivalent box goes in fixed C.9.** On fixed, `stage`/`prod` migrations run
inside the Ansible playbook *before* `docker compose up -d`
(`migrations.md § Stage and Prod on Fixed Foundation`), so a fixed prod clock
never meets a cold schema. Adding the box there would be false.

---

## Verification

Run from the repo root. All four must pass.

1. **Unit suite unchanged.**
   ```bash
   cd docex && python3 -m pytest tests/unit -q
   ```
   Expect **1009 passed**. This mod changes no code; any movement in this number
   is a finding and must be reported rather than absorbed.

2. **Integration suite unchanged.**
   ```bash
   cd docex && python3 -m pytest -m integration -q
   ```
   Expect **20 passed, 0 failed**.

3. **Doctrine + skills links green** — run this *after* Steps 4 and 5 have
   landed, never against the drafts.
   ```bash
   python3 skills/cohere/executor/linkcheck.py
   ```
   Must exit 0. The four new links (`./migrations.md#invocation-timing`,
   `./migrations.md#first-time-release-of-an-env`, `./clock.md`,
   `./clock.md#caveats`) are all sibling links inside
   `doctrine/infrastructure/specifics/` and all four anchors already exist.

4. **Checklist links validated separately.** `PRE_CUT_CHECKLIST.md` sits outside
   `linkcheck`'s default scan root — a known gap logged for advance 006 — so the
   root must be *widened*, not replaced. Passing `docex/test_projects` alone
   would leave every link into `doctrine/` fail-open, because the anchor table is
   built only from scanned files.
   ```bash
   python3 skills/cohere/executor/linkcheck.py doctrine skills docex/test_projects
   ```
   Must exit 0. This is what proves the two new
   `../../doctrine/infrastructure/specifics/…` links in Step 6 resolve, anchors
   included.

5. **Inner repos untouched.**
   ```bash
   git status --short docex/test_projects/fixed docex/test_projects/elastic
   ```
   Must print nothing.

6. **Greps.**
   ```bash
   grep -n 'api-web api-worker'        docex/test_projects/PRE_CUT_CHECKLIST.md   # → nothing
   grep -n 'they form a `uses` cycle'  docex/test_projects/PRE_CUT_CHECKLIST.md   # → nothing
   grep -c 'N consumer(s) checked'     docex/test_projects/PRE_CUT_CHECKLIST.md   # → 2
   grep -c 'api-web api-clock'         docex/test_projects/PRE_CUT_CHECKLIST.md   # → 2
   ```
   Leave `PRE_CUT_CHECKLIST.md:196` (`the `uses` graph may legally cycle`)
   **alone** — it is a correct general statement about the one-hop fan-out rule,
   not a claim about this project's topology.

## Do not

- Do not update any core planning doc (`docex/plans/core/*.md`). That is the mod
  cycle's documentation step, not the implementor's.
- Do not touch `CHANGELOG.md`, `VERSION`, `docex/pyproject.toml`,
  `docex/src/docex/__init__.py`, or `.claude-plugin/plugin.json`.
- Do not touch the advance's `report.md` or `advance_plan.md`.
- Do not commit. The corporal handles commits, path-scoped.
