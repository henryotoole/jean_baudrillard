# Mod 121 — Implementation Steps

Consolidated fix pass after the `cohere` audit. Design is approved; every
semantic question is already ruled. See [`overview.md`](./overview.md) for
reasoning — this document is the executable contract.

Repo root (`$jb`) is `/home/ubuntu/.claude/jean_baudrillard`. All paths below are
relative to it unless absolute. Branch: `005_process_type_solidification`.

---

## Non-negotiables

1. **No rule changes.** Every edit repairs prose, repairs an example so it obeys
   a rule already written, or routes an existing file. If you find yourself
   deciding *what the doctrine says*, stop and report instead.
2. **Prove examples by compiling them, not by reading them.** A previous mod
   marked a fence "verified correct" on a read and compiling proved otherwise.
   Every verdict you report must name the instrument that produced it.
3. **DO NOT TOUCH `doctrine/infrastructure/specifics/clock.md:96`** — the
   binding-coverage sentence ("`docex check` can assert that every declared job
   name has a binding…"). It is held with the operator. Other edits to
   `clock.md` are in scope; that sentence is not.
4. **Do not commit.** Leave all changes uncommitted for review.
5. Prefer many small, surgical edits over rewrites. Preserve surrounding
   wording, voice, and formatting everywhere except § 8 (F1), which is an
   approved full-body replacement.

---

## Instruments

You will run three. Establish all three at baseline **before** editing (Step 0)
and re-run them at the end (Step 14).

**I1 — the compile harness.** Currently at
`/tmp/claude-1000/-home-ubuntu--claude-jean-baudrillard/67dcf749-a5b8-4bf1-9cfc-d41708121d48/scratchpad/verify_examples.py`.

```bash
cd $jb/docex && PYTHONPATH=src python3 <scratchpad>/verify_examples.py
```

Baseline: **42 fences, 16 tabbed, 4 validated OK, 3 failed.**

**I2 — linkcheck.** `python3 $jb/skills/cohere/executor/linkcheck.py`
Baseline: 1 problem (`DUP FILENAME configurable.md`).

**I3 — pytest.**
```bash
cd $jb/docex && python3 -m pytest tests/unit -q
cd $jb/docex && python3 -m pytest -m integration -q
```
Baseline: **988 unit passed**; **20 integration passed / 0 failed**.

---

## Step 0 — Baseline

Run I1, I2, I3. Record the exact output of each. If any baseline differs from
the numbers above, **stop and report** — something changed under us and the rest
of this plan may be built on a false floor.

---

## Step 1 — `database` → `appdb` (defect A1)

`database` is a **reserved** backing-service name for the postgres engine
(`docex/src/docex/tables/roles/relational_db.yml:43`; enforced by
`_validate_reserved_engine_names` / `rule_engine_reserved_name`,
`docex/src/docex/cicl/validate.py:1165`). Every doctrine example using it is
compiler-rejecting.

`appdb` is fixed by precedent, not chosen: `test_projects/fixed/infra/infra.yml:140`,
`test_projects/elastic/infra/infra.yml:161`, `docex/tests/unit/test_validate.py:20-46`,
and `doctrine/infrastructure/specifics/clock.md:26` all already use it.

### 1.1 What to change

Only where `database` is a **backing-service identifier**:
- a key under `backing_services:`
- a member of a `uses:` list
- inside a magic ref `${backing_services.database.*}`
- inside a **derived resource name** built from it (see `shape.md` below)
- prose that names that specific example service

### 1.2 What NOT to change — read this before editing

- **Every `DATABASE_*` env-var key stays.** `DATABASE_HOST`, `DATABASE_PORT`,
  `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_SSLMODE`.
  These are the consuming application's env surface. Both smoke projects keep
  `DATABASE_*` while pointing at `appdb`. Only the **right-hand side** of these
  lines changes:
  `DATABASE_HOST: ${backing_services.database.host}` →
  `DATABASE_HOST: ${backing_services.appdb.host}`
- **Every generic-English use of "database" stays.** "run a database migration",
  "the database is not yet accepting connections", the whole of
  `doctrine/practices/databases.md`, `relational_db` role names, etc.
- **`db` stays.** `${backing_services.database.db}` becomes
  `${backing_services.appdb.db}` — the *field* is `db` and does not change.

**A blind `s/database/appdb/` would corrupt ~60 prose lines and every
`DATABASE_*` key. Edit site by site.**

### 1.3 Sites (~38 across 4 files)

| File | Sites |
| ---- | ----- |
| `doctrine/infrastructure/cicl.md` | `:43-48` (6 refs), `:60`, `:71`, `:81` (`uses:` lists), `:88` (the `backing_services:` key), `:166`, `:176`, `:381`, `:384` |
| `doctrine/infrastructure/shape.md` | `:110-114` (5 refs), `:121` (`uses:`), `:128` (key), **plus derived names**: `:146` `myproject-dev-database_data`, `:149`, `:174` `myproject-prod-database`, `:182` (×3) |
| `doctrine/infrastructure/specifics/transfer_tables.md` | `:22`, `:24`, `:42`, `:45`, `:56`, `:69`, `:293`, `:302`, `:938` — includes HCL literals such as `@aws_db_instance.database.endpoint` |
| `doctrine/infrastructure/specifics/config_and_secrets.md` | `:244`, `:254` |

Derived names in `shape.md` must ripple consistently: `myproject-dev-database_data`
→ `myproject-dev-appdb_data`, `myproject-prod-database` → `myproject-prod-appdb`.
Re-read the surrounding prose after each and make sure it still parses as English.

Line numbers are from the pre-edit tree and will drift as you work. **Re-grep
rather than trusting them**, and confirm you have found every site with:

```bash
grep -rn "backing_services\.database\|^\s*database:\|uses:.*database" doctrine/ skills/
```

No skill files declare a service or hold a magic ref; `skills/` should yield
nothing.

---

## Step 2 — Eliminate tabs from `yml` fences (defect A2)

YAML forbids tabs for indentation. **16 of 42** fences under `doctrine/` +
`skills/` are affected — they are not examples, they are text shaped like
examples.

Convert **each leading tab to 2 spaces**, matching both smoke projects'
`infra.yml`. Preserve relative nesting depth exactly.

Affected fences (fence-opening line numbers, pre-edit):

- `doctrine/infrastructure/cicl.md`: `:22`, `:115`, `:347`, `:376`
- `doctrine/infrastructure/shape.md`: `:100`
- `doctrine/infrastructure/specifics/clock.md`: `:15`
- `doctrine/infrastructure/specifics/transfer_tables.md`: `:90`, `:148`, `:169`,
  `:208`, `:310`, `:808`, `:820`, `:866`, `:876`, `:883`

**Interior tabs** additionally appear in `cicl.md:22` where a tab aligns a
trailing comment:
```
    port: 9000<TAB># on the web network, so a routing port is required
    versioning: true<TAB># A role-specific field.
```
Replace those with a **single space** before the `#`.

Only touch content **inside** ```` ```yml ```` / ```` ```yaml ```` fences. Do
not reformat tabs elsewhere in these files (markdown lists in `cicd.md` and
others legitimately use tabs).

Verify with I1: the tabbed count must go **16 → 0** while the fence total stays
**42**.

---

## Step 3 — Rule 7 in the canonical example (defect A3)

`doctrine/infrastructure/cicl.md:22-107` violates its own rule 7.

**Mechanism:** `BUCKET_NAME: ${backing_services.bucket.bucket_name}` sits in the
**codebase-level** `env:` block (`:42`). Per the same file's own clarification —
*"A codebase-level `env:` ref obliges every core service to declare the edge"* —
all three core services must declare `bucket`. Only `web` (`:60`) does; `worker`
(`:71`) and `clock` (`:81`) do not. The harness reports this as **rule_7 ×2**.

**Approved fix — option (b): move the ref.** Remove the `BUCKET_NAME` line from
the codebase-level `env:` block and add a core-service-level `env:` block to
`web` containing it.

Resulting shape (after Step 2's tab conversion, so 2-space indents):

```yml
  api:
    # Codebase-scoped fields sit at the codebase level.
    secrets:
      DISCORD_API_KEY: "Key to the discord bot used by the API."
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      ...
    core_services:
      web:
        role: web
        ...
        env:
          # Core-service-scoped: only `web` touches the bucket, so the ref
          # belongs here rather than on the codebase.
          BUCKET_NAME: ${backing_services.bucket.bucket_name}
        uses: [appdb, cache, bucket, api.worker]
```

Do **not** add `bucket` to `worker.uses` or `clock.uses`. The whole point of
choosing (b) is that a `clock` must not be shown declaring an edge to a bucket it
never touches.

Place the new `env:` block in a position consistent with the file's existing
field ordering, and keep the explanatory comment — it is what makes the example
teach the codebase/core-service `env:` merge.

---

## Step 4 — Remaining example defects (A4, A5)

**A4 — `cicl.md:376-382`.** The § Uses Relationships fragment declares
`uses: [database, cache, bucket, api.worker]`. Step 1 renames it to `appdb`.
Also update the prose at `:384`: *"a **backing service**, bare (`database`)"* →
``(`appdb`)``.

**A5 — `shape.md:100` is missing a required top-level field. NEW — found by
compiling, not in the original findings.**

That fence is a *complete* document (it declares `cicl_version: "3"`) but omits
**`observability_backend_url`**, which `CICLDocument` marks required. It fails at
**pydantic parse, before validation runs**.

Add, alongside the other top-level keys:
```yml
observability_backend_url: "https://hyperdx.example.com"
```
(the value `cicl.md`'s canonical example already uses).

**Critical:** the parse failure has been masking validation on this fence
entirely — it has never once been validated. After adding the field, **re-run
I1** and fix whatever validation errors then surface for the first time. Expect
possible findings around missing `health_check_path` or `uses`/ref alignment.
Repair by restoration (make the example obey rules already written); if a repair
would require *deciding* something, stop and report.

---

## Step 5 — Mechanical findings

Source: `docex/plans/advances/005_process_type_solidification/cohere_findings.md`.
Line numbers pre-edit; re-grep as needed.

| ID | File | Fix |
| -- | ---- | --- |
| F3 | `doctrine/charts/configurable.md:23` | Config box points at `$pr/infra/secrets/<env>.env`; must be `$pr/infra/config/<env>.env`. **This is an ASCII box-diagram — preserve column alignment and box-drawing characters exactly.** `config` is 6 chars vs `secrets` 7, so pad by one space to keep the right-hand border aligned. Highest-consequence item here: it routes config into the file agents are forbidden to read. |
| F4 | `doctrine/infrastructure/infrastructure.md:276` | "for `dev` and `stage`" → "for `dev` and `test`". |
| F5 | `doctrine/infrastructure/cicd.md:254` | "a target predating the v1 → v2 boundary cannot be rebuilt" → reword to name **no specific generation**, matching `pipeline/rollback.py:316` which renders the boundary generically. E.g. "a target declaring a `cicl_version` this compiler no longer accepts cannot be rebuilt". |
| F6 | `doctrine/infrastructure/specifics/projinfra/elastic_alb.md` | `:44` `myproject-stage-web-tg` → `myproject-stage-api-web-tg`. `:49` pattern → `${project}-${env}-${codebase}-${service}-tg`, example `tactical-lifecycle-test-stage-api-web-tg`. `:76`,`:81` HCL labels `"api"` → `"api_web"` (`aws_lb_listener_rule` / `aws_lb_target_group`). `:59`,`:86` host `api.prod.myproject.example.com` → `api-web.prod.myproject.example.com`. **Re-derive the `hash_truncate` length argument at `:49`** — it gets *stronger* with the longer name; make sure the arithmetic in the prose still holds. |
| F7 | `doctrine/infrastructure/specifics/projinfra/ec2_traefik.md:65-67` | Router key `api-prod` → `api-web-prod` (all three lines: `.rule`, `.tls.certresolver`, and `traefik.http.services.…loadbalancer.server.port`); host → `api-web.prod.myproject.example.com`. Contradicts `:61` four lines above. |
| F8 | `doctrine/hexagonal_architecture/hex_overview.md:129` | "the fifth (service/flow tests) exercises the whole service at once" → "…the whole **codebase** at once", matching its own heading at `:159` and `:161`. |
| F9 | `doctrine/infrastructure/docex.md:123` | "core `secrets:` blocks" → "codebase `secrets:` blocks". |
| F11 | `doctrine/infrastructure/infrastructure.md:253` | "a webapp two codebases" → "a webapp **with** two codebases". |
| F12 | `doctrine/infrastructure/cicl.md:386` | Self-doubling sentence. Replace "Where an engine genuinely needs another container beneath it, which containers an engine requires is an *engine* concern and belongs in…" with "Where an engine genuinely needs another container beneath it, **that requirement** is an *engine* concern and belongs in…". |
| F13 | `doctrine/infrastructure/cicd.md:209` **and** `doctrine/infrastructure/specifics/migrations.md:98` | "Subsequent releases find the **cluster** present" → "Subsequent releases find the env's **ECS service** present". Both paragraphs open by correcting exactly this misconception. (Report says `:96` for migrations.md; the actual line is `:98`.) |
| F15 | `doctrine/chain/chain_of_command.md:32` | Delete the duplicate `Advance` row from the file's private `## Lexicon` table. The definition of record is `practices/advance.md:7` ("a planned collection of mods **and other processes**"); the local copy has drifted to "mods" only. If the table would be left with only the `Commanding Officer` row, that is fine — keep the table. |
| F19 | `doctrine/charts/configurable.md`, `doctrine/charts/ecs_service_connect.md` | Add frontmatter as the **first** lines of each file: `---` / `stratum: conditional` / `---`. Value restored from sibling `doctrine/charts/ing.md`, not chosen. Note `charts/configurable.md` currently begins with whitespace-significant diagram lines — put the frontmatter above them and leave the diagram untouched. |
| F20 | `doctrine/infrastructure/docex.md` "Provided Tools" table | Add rows for `secrets` and `config`. Both already have full `###` sections (`:115`, `:130`) and are cited from resident `configurable.md:57`. Match the existing rows' column format and place them in an order consistent with the table's existing arrangement. |

### F14 — the escalation ladder (`doctrine/chain/chain_of_command.md:46-47`)

The table's "Escalates To" column reads `private` → `private` and `corporal` →
`corporal`, which is circular and contradicts `:88` in the same file ("it
escalates that decision to its C.O. … decisions ripple all the way up to the
human operator").

Fix, restoring the ladder the file's own prose and rank ordering define:

| Name | … | Escalates To |
| ---- | - | ------------ |
| private | … | `corporal` |
| corporal | … | `sarge` |
| sarge | … | Operator |

Change **only** the two cells. Leave the `sarge` row alone.

### Spelling and grammar

Apply all 17 rows of the table in `cohere_findings.md § Spelling and grammar`.
Two notes:

- `elastic_release_pattern.md:26`'s `healtchecks.md` link text is **absorbed by
  Step 8's rewrite** — do not fix it separately.
- `cicl.md:207` "2. Docker containers `${project}-…`" → add a colon, matching
  line 206.

---

## Step 6 — F16: the `clock` name collision (two sentences)

Ruling: **do not reopen the role name.** Add one disambiguating sentence in each
place. No restructuring.

**6.1 — `doctrine/infrastructure/specifics/clock.md`**, immediately after the
opening description of the role (and nowhere near `:96`):

> Not to be confused with the [`Clock` driven port pattern](../../hexagonal_architecture/hex_overview.md#driven-port--adapter-patterns), which abstracts a module's access to the current time. The two are unrelated: this page is about a core service that *fires* scheduled work, not about reading the wall clock.

**6.2 — `doctrine/hexagonal_architecture/hex_overview.md`**, as a note
immediately **below** the driven-pattern table (the `Clock` row is a table cell
and cannot carry the sentence):

> **Note:** the `Clock` pattern above is unrelated to the infrastructure [`role: clock`](../infrastructure/specifics/clock.md), a core service that fires scheduled jobs. A `clock` core service will often depend on a `Clock` port; the shared word is a collision, not a relationship.

The anchor `#driven-port--adapter-patterns` carries a **double hyphen** — the
stripped `/` in "Driven Port / Adapter Patterns" leaves two spaces, and
`linkcheck.py` deliberately does not collapse runs. Both links were verified
resolvable at design time. Do not "correct" the double hyphen.

---

## Step 7 — F2 + F18: route the orphaned conditional files

Four conditional-stratum files are reachable by no skill. All four pointers go in
**`## Specific Information`** ("read on demand"), never `## General Information`
— these are reasoning/chart files carrying motivation, and promoting them to
mandatory reading would inflate fixed context on three skills to buy nothing.

Use the doctrine's reference form: `[filename.md](../../doctrine/path/to/file.md)`.

**7.1 — `skills/infra-compile/SKILL.md` § Specific Information**, appended:

> [`cicl_reasoning.md`](../../doctrine/infrastructure/reasoning/cicl_reasoning.md) — why CICL fields are scoped where they are: the codebase-vs-core-service heuristic (*a field belongs to the **codebase** iff its value is determined by the source code, to the **core service** iff determined by the invocation*), and why `env:` is the one field valid at both levels. Read when `cicl.md`'s field table does not settle a case — adding a field, or placing a role-specific one.

**7.2 — `skills/cicd-pipeline/SKILL.md` § Specific Information**, inserted
directly **after** the existing `release.md` line:

> [`elastic_release_pattern.md`](../../doctrine/infrastructure/reasoning/elastic_release_pattern.md) — why the elastic release carries a post-apply reconcile step at all: ECS's three name-resolution mechanisms and why Service Connect is the only one available, why dependency ordering cannot fix the resulting race, and why the fix observes durable state rather than enforcing an order. Read alongside `release.md` when the reconcile step surprises you.

**7.3 — `skills/contracts/SKILL.md`** has **no** `## Specific Information`
section. Create one between `## General Information` and `## Thread` (legal —
`doctrine/skills/skills.md` makes the section optional), following the house
form: a short line noting these are read on demand, then the link.

> ## Specific Information
>
> The reasoning under the requirement. **Read on demand.**
>
> [`healthchecks.md`](../../doctrine/infrastructure/reasoning/healthchecks.md) — one paragraph on *why* every core service must declare a healthcheck: a system that autoscales and is evaluated by machine has no other way to be judged. `contracts.md` states the requirement; this states its motive.

**7.4 — `skills/configurable-vars/SKILL.md`** gets the renamed chart (see Step
9.2 — do this **after** the rename so the link is not born dangling). Same
placement rule; create `## Specific Information` if absent.

> [`configurable_flow.md`](../../doctrine/charts/configurable_flow.md) — the one-page flow diagram of where configurable values come from and where they land: the three sources, the `docex` command that scaffolds each, and the per-circumstance storage location for every environment.

---

## Step 8 — F1: rewrite `reasoning/elastic_release_pattern.md`

**Rewrite, do not delete.** The file documents a retired mechanism — it says all
ECS services relaunch *twice* and that shape-change detection is part of release.
`release.md` contradicts this three ways and the executor never implemented it
(`grep -rni 'double.rollout|shape.chang' docex/src` returns nothing).

What is **stale**: the `:18` and `:22` claims about double-launch, double-rollout,
and shape-change detection.
What is **sound and kept**: the three name-resolution mechanisms, why ALB and
Service Discovery are unavailable, and the launch-time name freeze.

Replace the **entire body** of
`doctrine/infrastructure/reasoning/elastic_release_pattern.md` with exactly this
approved text:

```md
---
stratum: conditional
---

# Elastic Release Pattern

Releasing on `elastic` is substantially more complex than on `fixed`. This is an unfortunate side-effect of name resolution in ECS. ECS has three mechanisms for name resolution:
1. Load Balancer (conventional)
2. Service Discovery
3. Service Connect

The load balancer option is by far the most desirable. It mirrors how name resolution works on the `fixed` side. However, this choice would require a second load balancer for all `elastic` projects to support non-`web` networked (internal) core services. An ALB can either be public-facing or not; it cannot be both at once.

Service Discovery is a legacy version of Service Connect and has some notorious pitfalls. It also can not be used.

This leaves Service Connect. This produces the unfortunate asymmetry between `fixed` and `elastic` because Service Connect is a decentralized, client-side load balancing and resolving system. It is not a worse system, just different.

The trick is that the decentralized system must still centralize service name resolution. Service Connect achieves this with a Cloud Map registry of the discovery names registered in the namespace. Unfortunately, a client task's copy of that registry is written *exactly once, statically*, when the task launches. A name registered after a task started does not exist for that task for the remainder of its life — it is **unresolvable** rather than merely unreachable, so no amount of application-level backoff ever converges on it.

See [ecs_service_connect.md](../../charts/ecs_service_connect.md) for a full diagram of the name resolution mechanism.

## Why Ordering Cannot Fix This

The obvious response is to create things in dependency order, so no consumer ever starts before a name it needs. That is not available, for two independent reasons.

The first is timing: `tofu apply` creates every env-tier ECS service concurrently, so a consumer and the target it `uses` race, and whichever starts first may never see the other.

The second is fatal to the idea itself. The [`uses`](../cicl.md#uses-relationships) graph may legally [contain cycles](../cicl.md#the-graph-may-contain-cycles) — `api.web` enqueues a job and `api.worker` posts the result back to `api.web`, which is the most common web/worker topology in existence. In a cycle some member must be created first, so there is no creation order to find. Ordering cannot solve a problem whose input admits no valid order.

## The Shape of the Fix: Observe, Don't Enforce

Because the ordering cannot be enforced, the doctrine repairs the outcome instead. After the final apply, `release` asks one question of current AWS state — *is any running consumer task older than the registration of a name it needs?* — and redeploys exactly those consumers for which the answer is yes.

What makes this sound rather than a patch is that both operands are **durable**. An endpoint registration is owned by the ECS service rather than by task liveness, so it survives every task replacement; task start times are AWS-server-issued facts. Nothing is carried across the apply and nothing is remembered between releases, so the step describes the world rather than the run that produced it. Any broken env it can read, it can also repair — including one left behind by an interrupted release, a hand-run `tofu apply`, or a rollback. A trigger keyed on *this release's own actions* would have none of that property: on the re-run of an aborted release every name already exists, and the broken env is set-identical to the healthy one.

The full mechanism — the three properties it exhibits and the implementation details it turns on — is in [release.md § Service Connect Consumer Reconcile](../specifics/release.md#service-connect-consumer-reconcile). The reachability-versus-resolvability distinction that motivates it is in [cicl.md § Resilience covers reachability, not resolvability](../cicl.md#resilience-covers-reachability-not-resolvability).

## Why We Need Name Resolution

Currently, requiring all core services to be reachable via HTTP is an offshoot of requiring HTTP-based healthchecks (see [healthchecks.md](./healthchecks.md)). However, making this universal practice has the additional advantage of allowing any internal-networked core service to be HTTP-reachable. This is a handy advantage for future projects.
```

Notes:
- This absorbs the `healtchecks.md` → `healthchecks.md` link-text typo.
- All five anchors were verified resolvable at design time using
  `linkcheck.py`'s own `slugify`. I2 re-verifies them.
- The file is **not** deleted, so `charts/ecs_service_connect.md` keeps its sole
  inbound link and needs no re-homing.

---

## Step 9 — F17 criterion; F18 rename

**9.1 — Record the lexicon criterion (F17).** Ruling: `uses` and `role` get **no**
lexicon entries — the lexicon defines *concepts*, not CICL field names, and
`depends_on`/`consumes` never had entries either. Record the criterion so the
next audit does not re-raise this as an omission.

In `doctrine/lexicon.md`, extend the intro line ("This guide defines special
words and phrases that have unique context for all markdown files in this
folder.") with one sentence:

> It defines *concepts*, not CICL field names: `uses`, `role`, `env:`, and `networks:` are specified in [cicl.md § Service Fields](./infrastructure/cicl.md#service-fields) rather than here.

Verify the `#service-fields` anchor resolves (I2 will catch it if not); if the
heading differs, link the correct one rather than inventing a section.

**9.2 — Rename the duplicate chart (F18).**
`git mv doctrine/charts/configurable.md doctrine/charts/configurable_flow.md`

This is `linkcheck.py`'s only current finding and fails the cohere skill's own
check 3 (unique filenames). **There are zero inbound links** to this file
anywhere in the corpus — verified at design time; the findings report's claim of
one from `skills/configurable-vars/SKILL.md` is wrong (that skill links only the
resident `infrastructure/configurable.md`). So the rename moves no link. Step 7.4
then gives the chart its first inbound router.

Do this rename **after** F3 and F19 have been applied to the file, or apply them
after the rename — either order, but do not lose those edits.

---

## Step 10 — Extend `linkcheck.py` to cover `skills/`

`doctrine.md:57` calls keeping thread-skill pointers valid "the one ongoing cost
of this structure, and it should be checked mechanically." The shipped executor
walks `doctrine/` only. The audit checked skill links by hand with a scratch
variant — a result that is not reproducible.

**The gap is subtler than "skills aren't scanned."** At `linkcheck.py:131` the
anchor check is guarded by `if rp in anchors`, and `anchors` is built only from
files under the scanned root. So today, a link into any file *outside* the root
has its anchor **silently unchecked** — it fails open. Adding `skills/` as a
second source root closes both halves.

### 10.1 Changes to `skills/cohere/executor/linkcheck.py`

1. **Multiple roots.** Default to `$jb/doctrine` **and** `$jb/skills`, both
   resolved relative to `__file__` as `DEFAULT_ROOT` already is. Accept any
   number of positional roots as an override. A single explicit root must still
   work — the cohere skill documents that invocation.
2. **One anchor table across all roots**, so cross-tree anchors resolve.
3. **Check 3 (duplicate filenames) stays scoped to `doctrine/` only.** This is
   load-bearing: `skills/` contains ~22 files named `SKILL.md` by the Agent
   Skills Standard, and including them would emit ~22 false positives and make
   the check useless. The doctrine's uniqueness rule is a *doctrine-corpus* rule.
   **The rule is not changing** — it is being applied to the tree it was written
   about. Add a `WHY:` comment recording this.
4. **Display paths** relative to the common repo root, since `relpath` against
   one of several roots is ambiguous.
5. Update the module docstring and `Usage:` line.

Keep `slugify`'s no-collapse behaviour and its docstring **exactly** as is — it
encodes a real GitHub-anchor rule and a previously-fixed false-positive bug.

### 10.2 New test `docex/tests/unit/test_linkcheck.py`

Load the script by path (`importlib.util.spec_from_file_location`) since it lives
outside the `docex` package. Build synthetic `doctrine/` + `skills/` trees under
`tmp_path`. Assert:

1. A clean two-tree corpus → exit 0.
2. A skill→doctrine link to a **missing file** → reported. *(Not caught today.)*
3. A skill→doctrine link to a **missing anchor** → reported. *(Not caught today
   — this is the regression the advance's three section renames could have
   caused.)*
4. A doctrine→doctrine broken link → still reported (no regression).
5. Two `SKILL.md` files under `skills/` → **not** reported as duplicates.
6. Two same-named doctrine files → still reported.
7. `slugify` preserves the double hyphen on a `/`-bearing heading.

---

## Step 11 — Promote the compile harness to a shipped tool

**The argument, to be stated in the mod docs and the skill:**

> This advance found the canonical example broken **twice** — by Mod 118's
> compile harness and by this mod's independent tab census — and *neither* was a
> shipped check.

### 11.1 Move and harden

Copy the scratchpad harness to `skills/cohere/executor/verify_examples.py`, then:

1. **Roots** default to `$jb/doctrine` + `$jb/skills`, resolved from `__file__`,
   matching `linkcheck.py` so both executors take the same arguments.
2. **Resolve the `docex` import** rather than assuming it. The scratchpad copy
   relied on `PYTHONPATH=src` and a cwd inside `docex/`. Locate `$jb/docex/src`
   relative to `__file__` (same trick as `linkcheck.py:21-22`) and insert it on
   `sys.path`. If `docex` still cannot be imported, fail with a clear message,
   not a bare `ImportError`.
3. **Exit non-zero** on any parse or validation failure so it can gate.
4. **Report counts**: fences scanned, parsed, validated, tabbed.
5. **Keep the existing classification logic as-is** — full documents (parsed +
   validated), spliceable fragments (spliced into a skeleton then validated), and
   non-CICL YAML (parse-only). That triage is the harness's real intelligence and
   is explicitly **not** being redesigned in this mod.
6. Give it a module docstring in `linkcheck.py`'s style.

After this, run it as the shipped tool (no `PYTHONPATH`, any cwd):
```bash
python3 $jb/skills/cohere/executor/verify_examples.py
```

### 11.2 New test `docex/tests/unit/test_verify_examples.py`

Same by-path import approach. Against synthetic corpora, assert: a clean fence
passes; a **tab-indented** fence is reported; a fence with an undeclared `uses`
target is reported; a fence missing a required top-level field is reported (the
A5 class); a non-CICL yaml fence is parse-checked but not validated; and the exit
code is non-zero exactly when findings exist.

### 11.3 Document both executors in `skills/cohere/SKILL.md`

Its § Mechanical Problems (`:28-39`) names only `linkcheck.py`. Add
`verify_examples.py` alongside it, with the one-line argument above.

Its numbered checklist has three items; the harness covers a **fourth** class —
*examples that do not compile* — which no existing item names. **Add a fourth
item** rather than wedging the tool under an existing one:

> 4. Examples that do not compile (fences that are not valid `infra.yml`)

---

## Step 12 — F10: `chunk_map.py` and its prose

The executor walks `core/*/src` — codebase roots — but calls them "services".
After this advance a service is a *deployment*, and a codebase's core services
share one source tree, so the wording is now false rather than merely
old-fashioned.

**Safety condition already discharged**: nothing parses this JSON key.
`skill_iter/eval/outcome/project-cohere/evals.json` has zero mentions of
`services`; the only matches in the tree are docker-compose's unrelated
`services:` key in `docex/emit/compose.py` and immutable run transcripts
recording the *command*, not the key. Do not re-litigate; do sanity-check that
nothing new has appeared.

**12.1 — `skills/project-cohere/executor/chunk_map.py`:** JSON key `"services"`
→ `"codebases"` (`:197`); chunk-kind label `"services"` → `"codebases"` (`:222`);
`_discover_services` → `_discover_codebases` (`:120`); plus call sites and local
variable names at `:206-222`, `:241`, `:245-251`. Keep behaviour identical.

**12.2 — `skills/project-cohere/SKILL.md:109,115,117`:** "one or more whole
**services** packed together" → "**codebases**"; "a subset of a single
**service's** hex modules" → "**codebase's**"; the bullet "`services` — which
service(s) the chunk's code belongs to" → "`codebases` — which codebase(s) the
chunk's code belongs to". Sweep the surrounding paragraphs for the same usage —
fix the *word where it means codebase*, and leave it where it genuinely means a
deployed service.

Both halves land together. Landing only one would create a fresh doc/code
mismatch — the exact defect class `project-cohere` exists to find.

---

## Step 13 — Log the deferred item (Q5)

`skills/docex-edit/SKILL.md` declares `metadata: type: thread` but has none of
the thread body structure `doctrine/skills/skills.md:24-30` mandates (H1 + intro,
mandatory `## General Information`, optional `## Specific Information` /
`## Thread`).

**Ruled: defer past the cut.** Do **not** change the skill. Record it so it is
not silently dropped: create
`docex/plans/modifications/_advance_006_skill_body_conformance.md`, following the
format of the existing `_advance_*.md` briefs (e.g.
`_advance_retire_depends_on.md`), stating:

- **Status: deferred to advance 006; not a 1.7.0 cut blocker.**
- The defect: `type: thread` with no thread body; pre-existing, not advance-005
  residue.
- Why deferred: it is an honesty defect rather than a correctness one, and
  restructuring a skill body belongs in the `skill-iteration` process **with its
  trigger and outcome evals**. Doing it in a fix mod would change a trigger
  surface with none of the machinery that exists to verify trigger surfaces.
- Suggest the audit be generalized: check *every* skill declaring `type: thread`
  for body conformance, since `docex-edit` is unlikely to be the only one.

---

## Step 14 — Verification

Re-run all three instruments and record exact output.

| Gate | Required result | Instrument |
| ---- | --------------- | ---------- |
| Every `yml` fence parses | 42 / 42 | I1 |
| Every `infra.yml`-shaped fence validates under `cicl_version: "3"` | 0 failed (from 3) | I1 |
| Tabs eliminated | 0 of 42 tabbed (from 16) | I1 |
| Links / anchors / dup filenames | **0 problems** across `doctrine/` **and** `skills/`, run as the shipped tool with no arguments | I2 |
| Unit tests | 988 + new tests, 0 failed | I3 |
| Integration tests | 20 passed / 0 failed, unchanged | I3 |

I1 must be run **as the shipped tool** (Step 11) for the final verdict, not from
the scratchpad.

**Re-run I1 immediately after Step 4's A5 fix**, before proceeding — that fence's
pydantic failure has been masking its validation entirely, and its first-ever
validation may surface further defects that change the remaining work.

---

## Reporting

Report a table with **a verdict and its instrument per row**. A verdict whose
instrument is "I read it" is not acceptable for any example.

Also report:
1. Any site where a fix required *deciding* what the doctrine says rather than
   restoring it — these should have been escalated, not landed.
2. Any validation error surfaced by A5's first-ever validation, and how it was
   repaired.
3. The final `git status --short` and a short summary of files touched by group.
4. Anything in the findings you could **not** land, and why.

Do not commit.
