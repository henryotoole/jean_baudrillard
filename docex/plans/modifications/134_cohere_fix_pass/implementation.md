# Mod 134 — Implementation Steps

Repo root: `/home/ubuntu/.claude/jean_baudrillard` (referred to below as `$jb`). All
paths absolute. Branch `006_surfaces_and_health`.

## Governing constraint — read before the first edit

**No edit may change what any rule means.** Every step below is one of: repair prose,
correct a factual claim to match measured behavior, fix an example so it obeys a rule
already written, complete a list that has silently lost a member, or repoint a citation.

If any step looks like it requires deciding what a rule *should* say, **stop and
report** rather than deciding. Three such decisions were already escalated and answered
during design; they are baked into the steps below and need no further judgement.

**Do not edit `$jb/doctrine/infrastructure/cicl.md`.** Rule 33 was corrected at the
source in `7f8d261` and is the text everything else aligns *to*. Rules 32 and 33 are
quoted below where needed so you never have to reword them.

**Do not touch anything inside `$jb/docex/test_projects/fixed/` or
`.../elastic/`** — their inner repos are on `main`, clean, with tags at HEAD, and that
is a walk precondition (A.2.1). Editing `PRE_CUT_CHECKLIST.md` is fine: it lives at
`$jb/docex/test_projects/PRE_CUT_CHECKLIST.md`, outside both inner repos. If you
believe a step requires editing inside a seed, **stop and report** — it does not.

## Verification (run at the end, report all four counts)

```bash
cd $jb && docex/.venv/bin/python -m pytest docex/tests -q
cd $jb && docex/.venv/bin/python -m pytest docex/tests -q -m integration
cd $jb && python skills/cohere/executor/linkcheck.py
cd $jb && python skills/cohere/executor/verify_examples.py
```

Baselines to match or beat: **1199 passed, 21 deselected**; integration **21**;
`linkcheck` and `verify_examples` both green. Never bare `pytest`. Run the integration
pass **alone**, not appended to the first.

---

# TIER 1

## Step 1 — `cicd.md:60`: restore rule 32's `web`-network exemption

File: `$jb/doctrine/infrastructure/cicd.md`

Current line 60 (a numbered list item, tab-indented):

```
	3. Every core-service [`uses`](./cicl.md#uses-relationships) target declares at least one surface. A core service that declares none is not a provider and cannot be used. A target that is **directly addressed** also declares a `port`, because a consumer reaching it needs an address; a target reached only through a queue or broker declares none.
```

The defect: this restates rule 32 without its `web`-network exemption, which is the
form that made rules 15 and 32 contradict each other on the `frontend`/`api` topology.
Rule 32 (`cicl.md:618`) carries the exemption thus: *"A **`web`-network target is exempt
from the second sentence**, because [rule 15](#validation-rules) requires a `port` there
regardless."*

Append the exemption to the end of the item, in rule 32's own terms and no stronger.
Keep it one sentence; do not restate rule 32's whole rationale. Target text:

```
	3. Every core-service [`uses`](./cicl.md#uses-relationships) target declares at least one surface. A core service that declares none is not a provider and cannot be used. A target that is **directly addressed** also declares a `port`, because a consumer reaching it needs an address; a target reached only through a queue or broker declares none. A `web`-network target is exempt from that last clause — [rule 15](./cicl.md#validation-rules) requires a `port` there regardless, so a consumer that reaches a public edge by its URL rather than by an internal name still finds one.
```

## Step 2 — `cicd.md:61` and `healthchecks.md:73`: narrow the `health_check_path` consumer

Rule 33 (`cicl.md:619`) now reads, in the load-bearing part: *"It is consumed by the ALB
target group on `elastic` **with the default `reverse_proxy: alb`**, and there alone.
**Everywhere else it has no consumer at all**, uniformly."*

### 2a. `$jb/doctrine/infrastructure/cicd.md` line 61

Current:

```
	4. Every `web`-network core service declares `health_check_path`. That field is the declaration — it is what the load balancer probes. Where the service *also* declares an `openapi` surface, its contract declares that path too. A `web`-network core service with no surface (a frontend, say) has no contract for the path to appear in, and needs none.
```

Replace only the unqualified consumer clause. Target text:

```
	4. Every `web`-network core service declares `health_check_path`. That field is the declaration — on `elastic` with the default `reverse_proxy: alb` it is what the ALB target group probes, and per [rule 33](./cicl.md#validation-rules) it has no consumer anywhere else. Where the service *also* declares an `openapi` surface, its contract declares that path too. A `web`-network core service with no surface (a frontend, say) has no contract for the path to appear in, and needs none.
```

### 2b. `$jb/doctrine/infrastructure/healthchecks.md` line 73

**Note the line number: 73, not 71.** Current:

```
The path is declared by the core service's `health_check_path` field, which compiles to the ALB target group's health check. **That field is the declaration** — it is what the load balancer reads, and the [check step](./cicd.md#check-step) asserts it. A core service that is not on the `web` network has no load balancer in front of it, declares no `health_check_path`, and needs no HTTP surface of any kind — a queue consumer built under this doctrine listens on nothing.
```

Target text:

```
The path is declared by the core service's `health_check_path` field, which on `elastic` with the default `reverse_proxy: alb` compiles to the ALB target group's health check. **That field is the declaration** — on that one configuration it is what the ALB reads, per [rule 33](./cicl.md#validation-rules) it has no consumer on any other, and the [check step](./cicd.md#check-step) asserts it regardless. A core service that is not on the `web` network has no load balancer in front of it, declares no `health_check_path`, and needs no HTTP surface of any kind — a queue consumer built under this doctrine listens on nothing.
```

## Step 3 — `cicl_reasoning.md:22`: swap the role-following example

File: `$jb/doctrine/infrastructure/reasoning/cicl_reasoning.md` — **note the directory is
`reasoning/`, not `specifics/`.**

Line 22 is the last row of the scoping table:

```
| | every role-specific field (`health_check_path`, `schedules`, …) |
```

The defect: it offers `health_check_path` as the canonical example of a field that
"follows `role`" (the derivation at line 24 says so explicitly), but rule 33 keys that
field on **network membership, not role**. A direct verbal contradiction.

`schedules` is the correct example and is already on the same line. It exists as a
`fields:` entry only in `$jb/docex/tables/roles/clock.yml` (line 81), and rule 4
(`tt_rule_4_undeclared_field`) rejects it on every other role — purely role-keyed. By
contrast `health_check_path` is a `fields:` entry only in `web.yml` (line 73), and
`web.yml:23` itself says *"Routing is network-driven, not role-static."*

Change line 22 to lead with `schedules` and drop `health_check_path`. A second
genuinely role-keyed field is available if one is wanted: `versioning` in
`object_store.yml:38`. Target text:

```
| | every role-specific field (`schedules`, `versioning`, …) |
```

Then **verify line 24 still reads true** — *"**Role-specific fields follow `role`**,
which is invocation-determined…"* — it does, and needs no edit. Do not touch it.

## Step 4 — `ec2_traefik.md:59` and `:152`: lifecycle state, not a health verdict

File: `$jb/doctrine/infrastructure/specifics/projinfra/ec2_traefik.md`

Both sites describe the ECS provider's `lastStatus == RUNNING` filter as health
behavior. Rule 33 is explicit: *"the ECS provider filters targets on `lastStatus ==
RUNNING`, which is a lifecycle state and not a health verdict."* A container failing
`health.sh` stays `RUNNING` and keeps taking traffic until the ECS scheduler replaces
it.

**Preserve the true half of each claim:** traefik really does balance across all of a
service's running task IPs, which DNS round-robin cannot. Only the *health* framing is
false.

### 4a. Line 59, current:

```
Beyond that, the provider gives what a DNS approach structurally cannot: traefik load-balances across *all* of a service's running task IPs and drops a task from the pool as soon as it leaves `RUNNING` on the next refresh — real balancing and health-gating rather than DNS round-robin against a possibly-stale record.
```

Target text:

```
Beyond that, the provider gives what a DNS approach structurally cannot: traefik load-balances across *all* of a service's running task IPs and drops a task from the pool once it leaves `RUNNING` on the next refresh — real balancing against live membership rather than DNS round-robin against a possibly-stale record. That membership is a **lifecycle** signal, not a health one: a task failing its `health.sh` stays `RUNNING` and keeps taking traffic until the ECS scheduler replaces it, so nothing here health-gates ([rule 33](../../cicl.md#validation-rules)).
```

**Check the relative link depth before writing it.** From
`doctrine/infrastructure/specifics/projinfra/` the path to `cicl.md` is
`../../cicl.md`. Confirm against an existing `cicl.md` link in this same file and match
it; if the file has none, verify with `linkcheck.py` at the end.

### 4b. Line 152, current:

```
This is the deliberate cost of the ECS-provider discovery model: it trades a narrow read grant for real load-balancing and health-aware routing that a DNS-only approach cannot provide.
```

Target text:

```
This is the deliberate cost of the ECS-provider discovery model: it trades a narrow read grant for real load-balancing against live task membership, which a DNS-only approach cannot provide. It does not buy health-aware routing — see the lifecycle-versus-health note above.
```

### 4c. Lines 198-203 — **NO EDIT. The list is correct.**

The env-tier emission list does *not* omit an `aws_lb_target_group`, because **the
compiler emits none on this path.** `$jb/docex/src/docex/emit/hcl.py:1085-1090`
(`_destination_applicable`) returns `False` for `target_group` whenever
`ctx.reverse_proxy != "alb"`. Leave lines 198-203 exactly as they are. Step 5 is the
real fix.

## Step 5 — kill the stale docstring that caused all of the above

File: `$jb/docex/src/docex/emit/hcl.py`, `render_target_group`, lines 825-838.

Current docstring:

```python
def render_target_group(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_lb_target_group`` + ``aws_lb_listener_rule`` for a
    web-network service. The dispatcher only calls this when
    ``web in svc.networks`` (per ``_destination_applicable``).

    Mod 044: ``aws_lb_listener_rule`` is ALB-specific. Mod 070: EC2-traefik
    routes via the traefik ECS provider, which reads each task's traefik.*
    dockerLabels (see render_task_definition) — listener rules don't apply
    there. We still emit the target group: ECS services with a
    ``load_balancer { ... }`` reference it, and even when traefik is the
    front door the target-group resource is harmless (no ALB attaches to
    it). Future cleanup mod can prune.
    """
```

Two defects. The dispatcher gate is stated too weakly (`web in svc.networks` is
necessary but not sufficient — `reverse_proxy == "alb"` is also required), and **"We
still emit the target group … Future cleanup mod can prune" describes a cleanup mod 070
already performed.** This function is unreachable on `ec2_traefik`. This is the docstring
that misled rule 33 into a false clause; `_destination_applicable`'s own docstring in the
same file is correct and contradicts it.

Target docstring:

```python
def render_target_group(svc: CompiledService, ctx: _RenderCtx) -> str:
    """Emit ``aws_lb_target_group`` + ``aws_lb_listener_rule`` for a
    web-network service.

    The dispatcher calls this only when the service is on the ``web``
    network AND the project's ``reverse_proxy`` is ``alb`` — see
    ``_destination_applicable``, which suppresses ``target_group``
    outright on the ``ec2_traefik_*`` variants (mod 044/070: traefik
    reaches ECS tasks through its ECS provider, reading each task's
    ``traefik.*`` dockerLabels — see ``render_task_definition`` — so
    neither a target group nor an ALB listener rule applies there).

    WHY this is spelled out: an earlier version of this docstring said the
    target group was emitted anyway and was "harmless", with a cleanup
    deferred to a future mod. Mod 070 had already done that cleanup. The
    stale text was then cited as evidence in cicl.md's rule 33, which
    carried a false claim about ec2_traefik emitting an inert target group
    until mod 134. Nothing reaches this function unless an ALB will
    attach to what it emits.
    """
```

Docstring-only change; **do not touch the function body.** No test should move.

## Step 6 — `transfer_tables.md`: complete the variable table, and mark the composed row

File: `$jb/doctrine/infrastructure/specifics/transfer_tables.md`

The measured, complete substitution context is built as one dict literal at
`$jb/docex/src/docex/cicl/compile.py:740-760`; `substitute.py:74` is a bare `ctx[name]`
and adds nothing. That dict is the authority for this step.

### 6a. Add the two genuinely missing rows (table at lines 50-65)

Insert after the `${role_name}` row:

```
| `${service}` | The core service's own name segment (e.g. `web` in `api.web`); `None` for a backing service. Used by the bundled role tables to pass a core service's identity to its health probe. |
| `${codebase_name}` | The name of the codebase the core service belongs to (e.g. `api`); `None` for a backing service. |
```

`${service}` is real (`compile.py:755`) and load-bearing in shipped tables —
`web.yml:36,67`, `worker.yml:39,61`, `clock.yml:53,75` all use
`["CMD", "./health.sh", "${service}"]`. Its absence from this table is the residue
`fa5d3fb` left when it corrected the example *to* `${service}` without adding the row.
`${codebase_name}` is at `compile.py:759`.

**Do NOT add a `${project_version}` row.** It is not a compile-time variable at all — it
is a Python parameter (`compile.py:588,672`) the emitter interpolates into f-strings
(e.g. `:1011`, `:979`). A row for it would create a false claim in the one table whose
entire job is enumerating what resolves. This was escalated and the omission is
deliberate. Likewise there is no `${codebase}` key; the key is `codebase_name`.

### 6b. Correct the `${networks}` row (same table)

Current:

```
| `${networks}` | The list of networks the service belongs to. |
```

It is not a list. `compile.py:745` is `",".join(svc.networks)`. Target text:

```
| `${networks}` | The networks the service belongs to, comma-joined into a single string (e.g. `web,internal`) — not a list. |
```

### 6c. Annotate the `OTEL_RESOURCE_ATTRIBUTES` row (line 793) as compiler-composed

That row's value string uses `${project_version}` and `${codebase}`, neither of which is
a compile-time variable. Under this file's own **validation rule 5** (line 959) — *"Every
compile-time variable reference (`${...}`) in any rendered template resolves to a known
variable in its context"* — a reader is entitled to conclude those two resolve. They do
not: the whole string is composed by the compiler at
`$jb/docex/src/docex/cicl/compile.py:1009-1020`, not interpolated from a table.

**Annotate; do not rewrite the value string.** Rewriting it as though the table
interpolated it would replace one wrong claim with another. The row's third column
already begins "Composed by the compiler from `project.yml` and `infra.yml`"; extend that
clause so the notation is explicitly flagged as illustrative rather than a template.
Add to the start of that third column, before the existing text:

```
**Not a transfer-table template** — the `${…}` here is notation for values the compiler substitutes directly, and `${project_version}` / `${codebase}` are *not* compile-time variables (see [§ Available compile-time variables](#available-compile-time-variables)); validation rule 5 does not apply to this string.
```

Verify the anchor `#available-compile-time-variables` matches the real heading
`### Available compile-time variables` at line 50, and that `linkcheck.py` stays green.

## Step 7 — `docex_process.md`: two stale counts, and an ordinal replaced by a method

File: `$jb/docex/plans/core/docex_process.md`

### 7a. Lines 170-172 — both numbers are stale

Current:

```
1. **`python -m pytest`, never bare `pytest`.** The bare binary cannot collect this
   suite. It reports **17** deselected instead of 18 and runs nothing — a count near
   enough to the truth to be believed.
```

Measured today: **21** integration-marked test items, across 14 files. So *both* numbers
are wrong, and this sits in the one section whose entire subject is
plausible-but-wrong counts. Rather than write two fresh numbers that will go stale the
same way, state the count once and name how to re-derive it. Target text:

```
1. **`python -m pytest`, never bare `pytest`.** The bare binary cannot collect this
   suite. It reports a deselect count one short of the real one and runs nothing — at
   the time of writing 21 integration-marked items exist, and the bare binary's near-miss
   is exactly what makes it believable. Re-derive rather than trust this number:
   `python -m pytest docex/tests -q` prints the deselected count, and
   `python -m pytest docex/tests -q -m integration` prints how many actually run. The
   two must agree.
```

### 7b. Lines 147 and 152-154 — the ordinal does not reconcile with the file's own table

Current line 147:

```
Nine of eighteen entries, and **the vocabulary grep found exactly one of them.** The
```

Current lines 152-154:

```
find damage from releases other than the one it is sweeping for. Second, **the
completeness pass is not optional and is not a formality**: it found eight of the
nine. The four still open are booked at
```

The table above at lines 138-145 names **ten** distinct files (`service_discovery`,
`codebase`, `reverse_proxy`, `cert_manager`, `host_machine`, `network_web`, `dns`,
`registrar`, `secrets`, `environment_config`), so "nine" and "eight of the nine" are
both inherited numbers rather than re-derived ones — the exact failure this section
warns about.

**Replace the ordinals with the method, not with new numbers.** Target for line 147:

```
Over half of the eighteen entries, and **the vocabulary grep found exactly one of them.** The
```

Target for lines 152-154:

```
find damage from releases other than the one it is sweeping for. Second, **the
completeness pass is not optional and is not a formality**: every defect above except
that one came from it — count the rows of the table, not this sentence. The four still
open are booked at
```

**Do not touch "The four still open."** It reconciles: the three `booked, not fixed`
rows name exactly four files (`dns`, `registrar`, `secrets`, `environment_config`).

Leave line 134's "defects in half of this directory" alone — at 10/18 it is true.

## Step 8 — `RELEASING.md:73`: the invocation that succeeds while running nothing

File: `$jb/RELEASING.md`. This is the file's only pytest invocation.

Current line 73 (a table row):

```
| `docex` behavior (code/tables) | The six-artifact alignment check + `pytest` (incl. `-m integration`). For **MINOR/MAJOR**, the two-foundation **test-project smoke walks** per [`docex/test_projects/PRE_CUT_CHECKLIST.md`](./docex/test_projects/PRE_CUT_CHECKLIST.md). PATCH skips the smoke walk. |
```

`$jb/docex/pyproject.toml:49` sets `addopts = "-m 'not integration'"`, so bare
`pytest -m integration` composes to `-m 'not integration' -m integration`, matches
nothing, and **exits 0**. Target text:

```
| `docex` behavior (code/tables) | The six-artifact alignment check + `python -m pytest tests`, then `python -m pytest tests -m integration` **as a separate invocation** (never bare `pytest`, and never both `-m` flags in one run — `pyproject.toml`'s `addopts` already carries `-m 'not integration'`, so a combined run matches nothing and still exits 0). For **MINOR/MAJOR**, the two-foundation **test-project smoke walks** per [`docex/test_projects/PRE_CUT_CHECKLIST.md`](./docex/test_projects/PRE_CUT_CHECKLIST.md). PATCH skips the smoke walk. |
```

## Step 9 — `PRE_CUT_CHECKLIST.md`: seven repairs, one cascade, two new boxes

File: `$jb/docex/test_projects/PRE_CUT_CHECKLIST.md`. This file gates two real-AWS
walks; every box must be assertable against reality.

### 9a. A.3.1 line 65 — drop the false "project-agnostic" parenthetical

Current:

```
`./bin/docex preinfra development` (run from either test-project root, since it checks dev-side machine state which is project-agnostic) probes the bridge + HAProxy and exits 0 only when both are present.
```

It is project-specific on two counts. `_check_dev_dns`
(`$jb/docex/src/docex/pipeline/preinfra.py:246-258`) resolves *this* project's hostnames
via `ctx.project.name`; and the manifest-delete probe fires only for
`foundation: fixed` with a `container_registry` (`preinfra.py:181`). One run therefore
leaves the other project's dev DNS and the whole registry probe unchecked. The file
already contradicts itself: line 107 quotes the project-specific failure message and A.5
line 123 pins the run to the fixed root. Target text:

```
`./bin/docex preinfra development` probes the bridge + HAProxy and exits 0 only when both are present. **Run it from *both* test-project roots — it is not project-agnostic.** It also resolves the invoking project's own `dev` hostnames, and the registry manifest-delete probe fires only for a `fixed` project that declares a `container_registry`, so a single run from one root leaves the other project's dev DNS and the entire registry probe unasserted.
```

### 9b. A.2 (lines 24-30) — make the box version-agnostic

Both seeds *and* `$jb/VERSION` are already at `1.7.0`, so as written this box asks the
walker to repin a repo that is already correct and the following box then has nothing to
commit — risking tag surgery on a correct repo at the front of the walk. It has now been
a full release behind twice.

**Do not write a next version number in** — that would assert the next cut's bump
level, which is a release-scope decision. Make the box read the version instead of
restating it.

Current lines 24-26:

```
- [ ] The candidate `docex` image is built locally: `docker images docex:1.7.0` shows the tag.
- [ ] Re-pin each test project to the candidate version. This moves each project's `docex_version` from `1.6.0` to `1.7.0` — the seeds sit at `1.6.0` today because mod 117 deliberately left repinning to the cut:
```

Target text:

```
- [ ] The candidate `docex` image is built locally: `docker images docex:$(cat ../../VERSION)` shows the tag.
- [ ] Re-pin each test project to the candidate version, moving each project's `docex_version` to the candidate. **Check first whether a repin is actually needed** — compare each seed's `project.yml` `docex_version` against `$jb/VERSION`; when a cut has not yet bumped `VERSION`, the seeds may already sit at the candidate and this box plus the commit box below are both no-ops. Do not force a repin that changes nothing, and do not move a tag on a repo that is already correct. Stating the versions as literals is what made this box a full release stale twice; read them:
  ```
  cat ../../VERSION; grep docex_version fixed/project.yml elastic/project.yml
  ```
```

Then keep the two existing `docex_install.sh` lines that follow, unchanged.

Also amend the commit box at line 30 so it is conditional. Its current opening is
`- [ ] **Commit the repin inward before assessing A.2.1.**` — change to
`- [ ] **If the repin changed anything, commit it inward before assessing A.2.1.**` and
leave the rest of that box's text intact.

### 9c. A.4.1 lines 89-90 and A.4.2 lines 106-107 — remove the `test` DNS records

`test` is no longer routed or TLS'd — `preinfra.py:249-252` says so in a comment
(*"We check `dev` only — `test` is no longer routed/TLS'd (mod 054)"*) — and **neither
seed's compiled `test` compose contains a single `Host(` or `traefik` string** (verified:
0 hits in both `infra/output/test/docker-compose.yml`).

Delete these two lines (89-90):

```
- [ ] `test.docex-smoke-fixed.luxrnd.tech      A → $DEV_IP`
- [ ] `*.test.docex-smoke-fixed.luxrnd.tech    A → $DEV_IP`
```

**Cascade — four sites now say "nine" where seven records remain.** Count them after
deleting: `dev`, `*.dev`, `stage`, `*.stage`, `prod`, `*.prod`, bare-project = **7**.
Update:

1. Line 83: `**These nine records are created once...**` → `**These seven records...**`
2. Line 83, later in the same paragraph: `Those nine are *expected* to remain` — this
   phrase is at line 825, not 83; see item 4.
3. Line 85: `If \`dig +short <subdomain>\` returns nothing for any of the nine` → `for
   any of the seven`
4. Line 825 (§ E): `**the nine standing fixed-walk \`A\` records from
   [A.4.1](#a41-fixed-walk-dns)**` → `**the seven standing fixed-walk \`A\` records...**`,
   and in the same box `Those nine are *expected* to remain` → `Those seven are
   *expected* to remain`.

Then in A.4.2, line 106, remove `test` and `*.test` from the resolve list and fix the
stray backtick pair. Current fragment:

```
fails until `dev`, `*.dev`, `test`, `*.test`.`docex-smoke-elastic.luxrnd.tech` resolve to the dev machine.
```

Target fragment:

```
fails until `dev` and `*.dev`.`docex-smoke-elastic.luxrnd.tech` resolve to the dev machine.
```

Better still, since the stray `.` between the backticked list and the domain is itself
the artifact of the original construction, render it unambiguously:

```
fails until `dev.docex-smoke-elastic.luxrnd.tech` and `*.dev.docex-smoke-elastic.luxrnd.tech` resolve to the dev machine.
```

Use the second form. Then line 107: `**⚠ Re-create the same four records in the CHILD
zone` → `**⚠ Re-create the same two records in the CHILD zone`.

**Re-count both after editing** rather than trusting these numbers — that is the whole
lesson of step 7.

### 9d. B.11.1 line 421 — `/health/events` → `/diagnostics/events`

The sanctioned-socket clause names the wrong route. Real source, identical in both
seeds: `core/api/src/root.py:179` is `@app.get("/diagnostics/events")`, with
`socket.create_connection(` at `:184`. The one surviving `/health/events` in the tree is
in gitignored `dist/` build output — **do not cite it**.

In line 421, change:

```
(the seed's `api/src/root.py` does exactly this for `/health/events`)
```

to:

```
(the seed's `api/src/root.py` does exactly this for `/diagnostics/events`)
```

B.11.1 is the lone holdout; lines 490, 626 and 702 already use the right path, and line
626 records the reason the diagnostics routes deliberately do not live under `/health/`.

### 9e. D.9 line 665 and D.11 line 752 — the version literal only

The elastic seed is at `0.0.23` and D.12 line 797 bumps it once, so the walk creates
**`0.0.24`**. `0.0.21` is two releases behind.

In **both** boxes, the sentence currently reads:

```
  Write both timestamps into the walk log. **Expected verdict: `fire` on this
  first `stage` release** — deployment and name are created seconds apart — and
  **`skip` on the code-only 0.0.21 release**, where the gap is days.
```

(D.11 says `prod` where D.9 says `stage`.) Change **only** `0.0.21` → `0.0.24` in each.

**Everything else in both boxes is verified correct — do not touch:** the `fire` clause;
the consumer derivation (D.9 lines 645-650 / D.11 lines 732-737, which correctly derives
consumers `api-web` and `api-clock` and correctly states there is no `uses` cycle); both
`N = 2` clauses (D.9 lines 659-661 / D.11 lines 746-748, derived from `infra.yml` and
not from any version); the verdict tables; the "Neither line appearing" paragraphs; the
"Why this box exists" blockquotes; and the `aws` command blocks with their
`docex-smoke-elastic-stage` / `-prod` cluster names.

### 9f. D.8 line 635 — the citation names the wrong box

`compile` is **D.4**, not D.7. The D-section headings are: line 598
`### D.3 Projinfra production (two phases)`, line 607 `### D.4 Compile`, line 629
`### D.7 Test`. The sentence's own content is about compile-before-projinfra, i.e. D.4
versus D.3.

In line 635, change `Also note the D.3/D.7 ordering` to `Also note the D.3/D.4
ordering`. Change nothing else in that blockquote.

### 9g. New boxes after line 468 (C.6) and line 637 (D.8) — assert the orphan arm

B.9 (lines 251-259) explicitly promises this and nothing delivers: *"at audit time
confirm the *shape* here and record the gate's line when you get there."* As a result the
**orphan arm** — per `$jb/docex/src/docex/pipeline/check.py:413-416`, the only thing that
catches a leftover three-segment contract sitting *beside* its correct replacement,
because an existence check is blind when the wanted file is also present — is asserted
nowhere in either walk.

Both seeds hold exactly three contracts (`api.web.rest.openapi.yml`,
`api.worker.events.asyncapi.yml`, `api.worker.rpc.asyncapi.yml`) matching three declared
surfaces, and exactly one `web`-network openapi provider (`api.web`), so the green output
is known exactly. Gate names and detail strings are from `check.py:474-482` and
`:575-584`; the report format is `check.py:89-106`.

Insert this box immediately **after line 468** (`- [ ] ./bin/docex check — exits 0.` in
C.6), indented as a sub-bullet of that box:

```
  - [ ] **Record `check`'s two contract gates by name, not just the exit code.** Exit 0
        alone does not prove the *orphan* arm ran. Copy both lines out of `check`'s gate
        table into the walk log; for these seeds they read:
        ```
          [PASS] contracts_exist         — 3 contract(s) present
          [PASS] contract_health_path    — 'GET <path>' present for 1 web-network openapi provider(s)
        ```
        (`'GET <path>'` is literal — the gate does not interpolate the path. Column
        padding varies with the longest gate name in the run.) `contracts_exist` reports
        **both** directions, and the orphan direction is the one that matters here: it is
        the only check that catches a leftover three-segment `api.web.openapi.yml` left
        sitting beside its four-segment replacement, which an existence check cannot see
        because the file it wants is also present. A count other than 3 means a contract
        was added, removed, or orphaned — re-derive from `infra.yml`'s `surfaces:` blocks
        before recording anything. This is the box [B.9](#b9-contracts) defers to.
```

Insert the same box immediately **after line 637** (`- [ ] ./bin/docex check — exits 0.`
in D.8), identical text.

Then update **B.9's forward pointer** (lines 258-259) so it no longer dangles — it
currently ends `record the gate's line when you get there`. Append a resolving
cross-reference to C.6 and D.8, e.g. `— recorded at [C.6](#c6-check--containerize) and
[D.8](#d8-check--containerize).` Verify both anchors resolve; match the anchor spelling
already used at lines 258-259.

---

# TIER 3

## Step 10 — the booked brief

Create `$jb/docex/plans/advances/007_small_edges/doctrine_excerpts_overhaul.md`.

This books an overhaul; it fixes nothing. **Every figure below is measured — do not
round, inflate, or restate any of them from memory.** The document's own subject is
plausible-but-wrong counts, so a wrong count in it is self-defeating.

Content to cover:

1. **Scope: 15 of 18 entries carry defects; 3 are substantially clean** — `codebase.md`,
   `core_service.md`, and `container_registry.md`. Say explicitly that
   `container_registry.md` is clean *because mod 133 rewrote it* (`8bef555`) — the
   artifact responds to attention, which is the argument for the overhaul.

2. **The three that actively misinstruct:**
   - `vpc.md` — describes a per-project VPC the doctrine replaced with the shared master
     network. Three inversions in a 12-line file: tier (`:3` "Project-tier" → prerequisite,
     per `shape.md:67`), cardinality ("one VPC per project" → one shared by all projects,
     per `elastic_master_network.md:42`), and NAT (`:8` "one NAT Gateway per AZ" → one
     centralized gateway, `shape.md:68`; `ingress_and_egress.md:36` prices per-project NAT
     at ~$400/yr as the thing explicitly rejected). It is also **the only excerpt whose
     subject resource does not exist in `shape.md` at all** — there is no `[vpc]`; the
     resource is `[master_network]`.
   - `aws_account.md:3` — asserts the exact inverse of the tenancy rule: *"one project per
     AWS account — multi-tenant accounts are out of scope"* against `shape.md:63`'s
     *"Multiple projects may exist under one account."* `:5` then builds a paragraph of
     rationale on top of the inverted rule, which is what makes it misinstruction rather
     than a typo.
   - `reverse_proxy.md:7` (the **Elastic** bullet) — **four** errors in one bullet: "one
     ALB per environment" (it is project-tier, one per project, `elastic_alb.md`); "in the
     env's public subnets" (they are the master VPC's, prerequisite and shared — there are
     no per-env subnets); "Doctrine-provisioned (not declared in `infra.yml`)" (it *is*
     declared — `cicl.md:32`'s `reverse_proxy:`; `alb` is merely the default); and
     "`docex compile` emits the ALB when any service declares `networks: [web, ...]`" (it
     is unconditional project-tier projinfra). A fifth — "the project's ACM cert" singular
     against two SAN'd certs — should be named **as arguable**, not counted. One clause,
     the `prod` replica load-balancing, is correct.

3. **`index.yml` is a clean 18/18 bijection** — 18 keys, 18 distinct existing targets, no
   duplicates, no orphans. The defect is not the mapping but its **coverage and its
   keys**:
   - **Eight `shape.md` resources have no entry at all**: `web_demux`, `master_network`,
     `repo`, `observability_backend`, `configurable_vars`, `telemetry_sidecar`,
     `nat_gateway`, `ecs_cluster`.
   - **Two entries are keyed opposite to `shape.md`**: `shape.md` says `web_network` and
     `internal_network`; `index.yml` says `network_web` and `network_internal`. So
     **`docex why web_network` fails** — `why/catalog.py:66-71` prints
     `unknown resource: 'web_network'`, dumps the 18 keys, exits 1. A reader who took the
     term from `shape.md`, the only place it is spelled, is bounced. `index.yml:1-4`
     states the very rule it breaks: keys should *"match the doctrine's `[resource]`
     notation in shape.md where possible."*
   - Conversely three keys name nothing in `shape.md`: `codebase` (legitimate — a
     `cicl.md`/`lexicon.md` concept), `secrets` (shape.md's resource is
     `configurable_vars`), and `vpc` (no doctrinal referent at all).

4. **The two patterns a vocabulary grep cannot find** — this is the part worth teaching:
   - **An inverted claim propagated across three files.** `vpc.md:3`, `network.md:8`, and
     `network_internal.md:6` all say "project VPC" where the doctrine has a master VPC
     shared by all projects. A grep for the doctrine's terms (`master_vpc`,
     `master_network`) returns nothing *precisely because* these files never use them; the
     wrong phrase is a plausible construction that appears on no term list. The only tell
     is that `network_internal.md` contradicts itself four lines apart — `:6` says "project
     VPC" and `:10` says "the master VPC's NAT gateway". `aws_account.md:3` is the same
     inversion in the tenancy register.
   - **Advance-005 rename residue that is structural, not lexical.** State this precisely:
     **no stale nouns survive** — a grep for `process`/`processes`/`domain_default_process`
     finds one hit and it is a correct unrelated use, and commit `b9b3cc3` did sweep the
     nouns. What survived is that the rename gave the compiled identity a **fourth
     segment** (`${project}-${env}-${codebase}-${service}`), and files still showed three.
     That is *why* no vocabulary grep can see it: the offending token contains no renamed
     word, and only comparison against compiled output reveals the missing segment.

5. **`registrar.md:8`'s compound citation**, folded in as instructed. Verbatim:
   `Doctrine reference: \`infrastructure/shape.md\` § Fixed-Foundation / Elastic-Foundation.`
   The `§` sits *outside* the closing backtick, so `linkcheck.py:124`'s `CITE_RE` leaves
   it **unbounded** — the heading runs into the sentence and is counted, never verified.
   And it names two headings (`### Fixed-Foundation`, `### Elastic-Foundation`) where no
   single heading of that name exists, so any bounder resolving it as one unit yields a
   false BAD CITATION. **It is the only unresolvable citation in the directory** — the
   other 15 `Doctrine reference:` lines all resolve — so splitting it is the precondition
   for mechanically bounding this directory at all. Note two companions for the same
   sweep: `container_registry.md:10` is the only file putting `§` *inside* the backticks
   (the bounded, checkable form all 16 should use), and `secrets.md` has no
   `Doctrine reference:` footer at all.

6. **`secrets.md` describes a model the doctrine explicitly repudiated** — worth its own
   paragraph because it is the severest non-inversion defect. `example.env` appears
   **nowhere** in `doctrine/` (zero grep hits), and `config_and_secrets.md:70` reads
   *"Rather than copy a manifest to `<env>.env` and fill it by hand"* — the real mechanism
   is `docex secrets scaffold <env>`. The store is now split three ways
   (`infra/secrets/`, `infra/config/`, `infra/tte/`); the excerpt shows one.

7. **A rendering defect in shipped output, not a prose nit.** A bare `<domain>` inside a
   markdown table is parsed as an HTML tag and **renders invisibly** under
   `rich.markdown.Markdown` (`why/catalog.py:80`), so `docex why` prints a table with
   holes in it exactly where an operator most needs a value. Sites: `dns.md:7-10`,
   `cert_manager.md:6`, `registrar.md:5`, `secrets.md:19`, and `vpc.md`. Frame it as a
   defect in what `docex why` *prints*.

8. **Why this is booked rather than folded into advance 006.** **15 of 16 defect sites
   (94%) predate advance 006, and 14 of them trace to one commit** — `307d47a`,
   2026-05-26, the directory's original authoring; one more (`registrar.md:8`) to the
   2026-06-22 cohere pass. Exactly one site is 006-attributable and it is the least
   consequential: a `project_dns_label` vocabulary leak in `reverse_proxy.md:5` whose
   rendered value is correct. Record the honest nuance: `git blame` *flatters* advance 006
   badly here, because mod 131 touched `network_web.md:5` and `reverse_proxy.md:5` without
   fixing the underscore token that was already there, so blame attributes 2026-05-26
   content to 2026-08-10. And record the countervailing fact rather than suppressing it:
   **advance 006 improved every excerpt it touched** — mods 130-133 rewrote
   `container_registry.md` to clean, added the correct health-probe paragraph to
   `core_service.md`, and fixed a genuinely inverted host-wide-traefik claim across four
   files. **The overhaul is warranted by original-authoring debt, not by regression.**

9. **Explicitly deferred to the overhaul, with the reason:** `vpc.md:9`'s underscored
   per-env subnets (`${project}_${env}_public_a`, …). These are **not repairable by
   renaming** — those subnets do not exist. The real four are prerequisite master-network
   subnets (`master_network_public-az1` / `public-az2` / `private-az1` / `private-az2`).
   Renaming a phantom would make it look canonical, which is worse than leaving it
   visibly wrong.

Also list the remaining per-file defects in a compact table so the overhaul has a work
list: `backing_service.md:3` (claims the transfer tables pick the engine; the *project*
declares `engine:` — `cicl.md:97,104,111`), `build_image.md:5` (image ref omits the
registry host), `cert_manager.md:6` (one wildcard cert claimed; doctrine issues two with
explicit SAN sets, `shape.md:166`, and the HTTP-01/DNS-01 split is omitted),
`dns.md` (entire model is pre-`apex_domain`: names a `domain:` field that does not exist,
omits the `<project_name>` segment, gives prod as `www.<domain>` where `cicl.md:600`
forbids `www` as a name, and `:12`'s apex→`www` redirect contradicts `cicl.md:281`),
`environment_config.md:6` (puts ALB and ECS cluster in the env `main.tf`; both are
project-tier, `shape.md:74`, and the whole `infra/output/project/…` tier is omitted),
`host_machine.md:5` (inverts single-machine hosting: `infrastructure.md:304` is "one
machine … hosting all environments"), `network.md:3` (underscore naming — **fixed in step
11**), `network_internal.md:6` (the self-contradicting "project VPC"),
`network_web.md`/`network_internal.md:1` (H1s don't match their index keys), and
`backing_service.md:3` ("MinIO" capitalized; doctrine writes `minio`).

## Step 11 — the three fix-now naming tokens

Two-advance-old rename residue. Ground truth is compiled output —
`$jb/docex/test_projects/fixed/infra/output/dev/docker-compose.yml` has
`container_name: docex-smoke-fixed-dev-api-web` (`:141`) and network
`name: docex-smoke-fixed-dev-web` (`:25`) — so identities are
`${project}-${env}-${codebase}-${service}`, hyphens, four segments, and networks are
`${project}-${env}-${network}`.

### 11a. `$jb/docex/doctrine_excerpts/service_discovery.md` line 5

Two faults in one token — underscores, and three segments where the identity has four.
The surrounding prose is also post-005 wrong: `api` is a *codebase*, not a service.
Current:

```
- **Fixed:** docker network DNS — works automatically as soon as containers share a docker network. A service named `api` is reachable at `myproject_dev_api` (its container name) by any other container on the same network. No additional configuration.
```

Target:

```
- **Fixed:** docker network DNS — works automatically as soon as containers share a docker network. The core service `web` of codebase `api` is reachable at `myproject-dev-api-web` (its container name) by any other container on the same network. No additional configuration.
```

Leave line 6 (`${global_service_name}`) and lines 10-17 alone — all correct.

### 11b. `$jb/docex/doctrine_excerpts/network_web.md` line 5

Three faults: underscores, and missing `$` sigils on both placeholders. Change the
clause

```
`{project}_{env}_web`
```

to

```
`${project}-${env}-web`
```

leaving the rest of the sentence intact.

### 11c. `$jb/docex/doctrine_excerpts/network.md` line 3

Same residue, same directory. Fixing two of three occurrences would leave a reader
unable to tell which spelling is current. Change

```
`${project}_${env}_${name}`
```

to

```
`${project_name}-${env_name}-${network_definition_name}`
```

matching `networks.md § Compiled Names`, which is the rule of record for this name.

**Do not touch `vpc.md:9`** — booked in step 10, item 9, for the reason given there.

---

# Out of scope for this mod

- **All of Tier 2** — the code and core-doc claims (`compiler.md:498-500`,
  `worker.yml:66-70`, `model.py::core_uses`, `orchestrate/build.py:66-71`,
  `aws/client.py:410-416`, `stagetest.py:5`, `rollback.py:244-255`, `errors.py`,
  `masterplan.md:165` and `:201`, `compiler.md:587`, and the eight
  silently-shortened lists). These are **mod 134b**, a separate cycle.
- **Any punctuation, grammar, or spelling pass over the corpus.** Fix such things only
  if you are already editing that exact line for a reason above. The one instance
  authorized here is the stray backtick in step 9c.
- **`doctrine/infrastructure/cicl.md`** — do not edit. Rule 33 is already correct.
- **`ingress_and_egress.md`'s arithmetic** — booked, not fixed.

# Report back

- Each step: done / skipped, with anything that did not match this document.
- All four verifier results with counts.
- Anything you found that this document got wrong. **Check claims against the code, not
  against citations** — a stale docstring cited as evidence is exactly how the defect in
  step 5 reached the rule of record, and it is the failure mode this mod exists to
  correct.
