# Mod 121 — Consolidated Fix Pass (post-`cohere`)

The last mod of advance 005 before both smoke walks. It takes the 27 findings in
[`cohere_findings.md`](../../advances/005_process_type_solidification/cohere_findings.md)
plus the four pre-existing defects in
[`advance_plan.md § 2c`](../../advances/005_process_type_solidification/advance_plan.md),
lands every mechanical one, lands three semantic ones under sarge's rulings, and
extends `linkcheck.py` to cover `skills/`.

**This mod changes no rule.** Every edit either repairs prose, repairs an example
so it obeys a rule already written, or routes an existing file. Mod 112's output
remains the rule of record. The two places where a genuine choice appeared are
raised as design questions rather than taken.

---

## 1. Instruments

Sarge's bar: *"Prove every example by compiling it, not by reading it. Your
verdicts must name their instrument."* Mod 118's corporal marked a fence
"verified correct" on a read, and compiling proved otherwise — in a fence
carrying the same defect it was fixing four lines above.

Three instruments, each named against every verdict in this mod's report:

| # | Instrument | What it proves | Invocation |
| - | ---------- | -------------- | ---------- |
| I1 | **`verify_examples.py`** — Mod 118's compile harness | Every `yml` fence under `doctrine/` + `skills/` parses; every `infra.yml`-shaped one validates through the real `validate_document` path under `cicl_version: "3"` | `cd $jb/docex && PYTHONPATH=src python3 <scratchpad>/verify_examples.py` |
| I2 | **`linkcheck.py`** — the shipped cohere executor, as extended by this mod | No broken links, no bad anchors, no duplicate doctrine filenames, across `doctrine/` **and** `skills/` | `python3 skills/cohere/executor/linkcheck.py` |
| I3 | **`pytest`** | Unit 988 (+ new `linkcheck` tests) and integration 20/0 unchanged | `cd $jb/docex && python3 -m pytest tests/unit -q` / `-m integration` |

I1 and I3 are already reproduced at their baselines in this design turn:
`pytest tests/unit` → **988 passed**; the harness → **42 fences, 16 tabbed, 4
validated OK, 3 failed**, reproducing Mod 118's committed record byte-for-byte.
The three failures are the §2c defects this mod fixes.

**A tab-census cross-check** run independently of the harness (a separate 12-line
script over both trees) returned **16 of 42** — matching the harness and the
brief. Two instruments agreeing is why I state the count as fact rather than as
the brief's claim.

### The harness is still a throwaway — and that is now the weak link

Mod 118 wrote `verify_examples.py` to the scratchpad and **deliberately did not
commit it** (its `implementation.md` § F1 says so twice). It survives only
because this session shares Mod 118's scratchpad; I re-ran it unmodified.

That is the same property sarge just ruled unacceptable for the hand-checked
skill links — *"a hand check that passes once is not a check."* The compile
harness caught four real defects, will run once more in this mod, and then
evaporate. The next example edit re-opens the same defect class with nothing
watching. **See design question Q1.**

---

## 2. Part A — the four §2c defects (plus a fifth the harness found)

### A1. `database` → `appdb`

`database` is reserved by the postgres engine
(`docex/tables/roles/relational_db.yml:43`, enforced by
`_validate_reserved_engine_names`, rule `rule_engine_reserved_name`,
`validate.py:1165`). The canonical example is therefore **compiler-rejecting**:
a reader who copies it gets a validation error on their first compile.

`appdb` is constrained by precedent, not chosen. **Three** independent sites
already use it:

- `test_projects/fixed/infra/infra.yml:140` — with a comment explaining the reservation
- `test_projects/elastic/infra/infra.yml:161` — same, same reason
- `docex/tests/unit/test_validate.py:20-46` (`_BASE_FIXED`) — the suite's own green skeleton

A fourth site makes the rename a *repair of an existing inconsistency* rather
than a change: **`specifics/clock.md:26` already says `uses: [appdb, api.worker]`**.
Today `clock.md` and `cicl.md` disagree about the name of the same example
service. After this mod they agree.

**The blast radius is wider than the brief assumed.** Sarge named `cicl.md` and
`shape.md`; the ripple also reaches two files sarge did not name:

| File | Sites | Notes |
| ---- | ----- | ----- |
| `cicl.md` | 14 | `:43-48` refs, `:60/71/81` `uses:`, `:88` the key, `:166`, `:176`, `:381`, `:384` |
| `shape.md` | 13 | `:110-114` refs, `:121`, `:128`, plus **derived** names at `:146` (`myproject-dev-database_data`), `:149`, `:174` (`myproject-prod-database`), `:182` (×3) |
| `specifics/transfer_tables.md` | 9 | `:22`, `:24`, `:42`, `:45`, `:56`, `:69`, `:293`, `:302`, `:938` — includes HCL literals `@aws_db_instance.database.endpoint` |
| `specifics/config_and_secrets.md` | 2 | `:244`, `:254` |
| `skills/**` | 0 | no skill declares a service or holds a magic ref |

**~38 sites across 4 files.** A naive `s/database/appdb/` would corrupt ~60
prose lines and every `DATABASE_*` env-var key, so the implementation enumerates
sites explicitly.

**Explicitly excluded** (verified line-by-line): all `DATABASE_*` env-var *keys*
— they are the consuming app's env surface, and both smoke projects keep
`DATABASE_*` while pointing at `appdb` — and every generic-English use of the
word ("run a database migration", `practices/databases.md` entire, etc.).

### A2. The tabs — 16 of 42 `yml` fences

YAML forbids tabs for indentation, so these are not examples; they are text
shaped like examples. None is copy-pasteable.

`doctrine/infrastructure/cicl.md` (`:22`, `:115`, `:347`, `:376`),
`shape.md:100`, `specifics/clock.md:15`, and
`specifics/transfer_tables.md` (`:90`, `:148`, `:169`, `:208`, `:310`, `:808`,
`:820`, `:866`, `:876`, `:883`).

Conversion: each leading tab → **2 spaces**, matching both smoke projects'
`infra.yml`. `cicl.md:22` additionally carries **interior** tabs used as comment
alignment (`port: 9000<TAB># on the web network…`, `versioning: true<TAB># A
role-specific field.`); those become a single space before the `#`. Verdict is
I1, not a read.

### A3. Rule 7 in `cicl.md:22-107` — and a genuine choice inside it

The canonical example fails **its own rule 7**. The mechanism is more specific
than "a ref with a missing `uses`":

`BUCKET_NAME: ${backing_services.bucket.bucket_name}` sits in the **codebase-level**
`env:` block (`:42`). Per the same file's own clarification — *"A codebase-level
`env:` ref obliges every core service to declare the edge"* — all three core
services must declare `bucket`. Only `web` does. `worker` (`:71`) and `clock`
(`:81`) do not. That is the harness's **rule_7 ×2**.

Two repairs are available, and they teach different things:

- **(a) Minimal.** Add `bucket` to `worker.uses` and `clock.uses`.
- **(b) Move the ref.** Relocate `BUCKET_NAME` from the codebase-level `env:`
  down into `web`'s own core-service `env:` block.

**I recommend (b)**, and the reason is not economy. Under (a) the canonical
example would show a `clock` declaring `uses: [bucket]` for a bucket it never
touches — teaching readers to declare edges they do not have, which is precisely
the habit `uses` exists to discipline. (b) also makes the example demonstrate
the one field that legitimately straddles both scopes, which
`cicl_reasoning.md:26` calls out as the single exception to the field-scoping
heuristic and which the canonical example currently never shows. It is a
defect-to-teaching-moment conversion at zero cost.

It is still a choice about what the canonical example teaches. **See Q2.**

### A4. `cicl.md:376-382` — `uses:` with an undeclared target

The § Uses Relationships fragment declares `uses: [database, cache, bucket,
api.worker]`. Fixed by A1's rename (`appdb`), after which the fragment resolves
against the harness skeleton. Prose at `:384` — *"a backing service, bare
(`database`)"* — renames with it. Harness rule: `rule_25_unresolved_uses`.

### A5. **NEW — `shape.md:100` is missing a required top-level field**

Not in the brief. Found by I1, not by reading.

`shape.md:100`'s fence is a *complete* document (it declares `cicl_version: "3"`),
but it omits **`observability_backend_url`**, which `CICLDocument` marks
required. It fails at pydantic parse — before validation even runs — so it is
compiler-rejecting for a reason entirely independent of the `database` name.

This is the same defect class as the other four and belongs in the same sweep.
The repair is restoration, not choice: add
`observability_backend_url: "https://hyperdx.example.com"`, the value
`cicl.md`'s canonical example already uses. Because the pydantic failure masks
everything downstream, the implementor must **re-run I1 after adding it** and
fix whatever validation then surfaces — the fence has never once been validated.

---

## 3. Part B — the mechanical findings

All land autonomously. Enumerated rather than counted, because the brief's "21"
and the report's own tiering do not reconcile cleanly: cohere's inline
**SEMANTIC** marks fall on 8 findings (F1, F2, F14, F16, F17, F18, F21, F22),
leaving **14 mechanical F-numbers**, plus a **17-row spelling/grammar table**,
plus §2c's **4** (now 5). The report's "21 mechanical" evidently groups the
spelling table; the enumeration below is the contract, not the count.

| ID | File:line | Fix |
| -- | --------- | --- |
| F3 | `charts/configurable.md:23` | Config box points at `$pr/infra/secrets/<env>.env` → `$pr/infra/config/<env>.env`. Copy-paste from the Secrets box. **Highest-consequence mechanical item**: it routes config into the file agents are forbidden to read. Redraw the box keeping column alignment. |
| F4 | `infrastructure.md:276` | "for `dev` and `stage`" → "for `dev` and `test`". Resident file; contradicts its own tree 100 lines up. |
| F5 | `cicd.md:254` | "predating the v1 → v2 boundary" → name **no** generation, matching `rollback.py:316` which renders the boundary generically. |
| F6 | `projinfra/elastic_alb.md:44,49,59,76,81,86` | One-segment core-service identity → two. `myproject-stage-web-tg` → `myproject-stage-api-web-tg`; `api.prod.…` → `api-web.prod.…`; HCL resource labels `"api"` → `"api_web"`. Re-derive the `hash_truncate` length argument at `:49` — it gets **stronger** with the longer name. |
| F7 | `projinfra/ec2_traefik.md:65-67` | Router key `api-prod` → `api-web-prod`; host `api.prod.…` → `api-web.prod.…`. Contradicts `:61` four lines above. |
| F8 | `hex_overview.md:129` | "the fifth (service/flow tests) exercises the whole service" → "the whole codebase", matching its own heading at `:159`. Resident file. |
| F9 | `docex.md:123` | "core `secrets:` blocks" → "codebase `secrets:` blocks". |
| F10 | `skills/project-cohere/SKILL.md:109,115,117` | "service(s)" → "codebase(s)". **Has a code half — see Q3.** |
| F11 | `infrastructure.md:253` | "a webapp two codebases" → "a webapp with two codebases". |
| F12 | `cicl.md:386` | Self-doubling sentence → "…, that requirement is an *engine* concern and belongs in…". |
| F13 | `cicd.md:209`, `migrations.md:98` | "Subsequent releases find the **cluster** present" → "find the env's **ECS service** present". Both paragraphs open by correcting exactly this. (Note: the second site is `:98`, not the report's `:96`.) |
| F14 | `chain_of_command.md:46-47` | Escalation ladder: private → `corporal`, corporal → `sarge`. **Landing — restoration, see §5.** |
| F15 | `chain_of_command.md:32` | Drop the duplicate `Advance` row; the definition of record is `lexicon.md` / `practices/advance.md:7` ("mods **and other processes**"). |
| F19 | `charts/configurable.md`, `charts/ecs_service_connect.md` | Add `stratum: conditional` frontmatter, matching sibling `charts/ing.md`. Value is restored from the sibling, not chosen. |
| F20 | `docex.md` Provided Tools table | Add `secrets` and `config` rows; both have `###` sections and are cited from resident `configurable.md:57`. |
| — | 17-row spelling/grammar table | Land as written. Includes `elastic_release_pattern.md:26`'s `healtchecks.md` link text, which F1's rewrite absorbs. |

---

## 4. Part C — the three semantic items sarge ruled on

### F16 — `clock` names two things. Two sentences, no restructuring.

Sarge: do not reopen the role name. Add a disambiguating sentence in each place.

**In `specifics/clock.md`**, immediately after the opening description of the role:

> Not to be confused with the [`Clock` driven port pattern](../../hexagonal_architecture/hex_overview.md#driven-port--adapter-patterns), which abstracts a module's access to the current time. The two are unrelated: this page is about a core service that *fires* scheduled work, not about reading the wall clock.

**In `hex_overview.md`**, as a note immediately below the driven-pattern table
(the `Clock` row itself is a table cell and cannot carry the sentence):

> **Note:** the `Clock` pattern above is unrelated to the infrastructure [`role: clock`](../infrastructure/specifics/clock.md), a core service that fires scheduled jobs. A `clock` core service will often depend on a `Clock` port; the shared word is a collision, not a relationship.

Both links verified resolvable by hand and will be re-verified by I2. The
`#driven-port--adapter-patterns` anchor carries a **double** hyphen — the
stripped `/` leaves two spaces and `linkcheck.py` deliberately does not collapse
runs (`slugify`'s docstring records this as the original false-positive bug).

### F2 — routing the three orphaned conditional files

Sarge's mapping, by the activity each supports. Pointer text drafted below;
**not landing until approved**, per sarge's note that a router line is a trigger
surface.

Placement rationale: all three go in **`## Specific Information`** ("read on
demand"), never `## General Information` ("read these now"). These are
reasoning files — the *why* behind a mechanism. Promoting them to mandatory
reading would inflate the fixed context cost of every invocation of three
skills to explain motivation the reader may not need.

**1. `cicl_reasoning.md` → `infra-compile` § Specific Information**

> [`cicl_reasoning.md`](../../doctrine/infrastructure/reasoning/cicl_reasoning.md) — why CICL fields are scoped where they are: the codebase-vs-core-service heuristic (*a field belongs to the **codebase** iff its value is determined by the source code, to the **core service** iff determined by the invocation*), and why `env:` is the one field valid at both levels. Read when `cicl.md`'s field table does not settle a case — adding a field, or placing a role-specific one.

*Why this text:* it quotes the heuristic itself rather than describing it, so the
router line is useful even if the agent never opens the file — which is the
correct hedge for the single clearest statement of the rule this advance turns
on.

**2. `elastic_release_pattern.md` → `cicd-pipeline` § Specific Information**,
placed directly after the existing `release.md` line.

> [`elastic_release_pattern.md`](../../doctrine/infrastructure/reasoning/elastic_release_pattern.md) — why the elastic release carries a post-apply reconcile step at all: ECS's three name-resolution mechanisms and why Service Connect is the only one available, why dependency ordering cannot fix the resulting race, and why the fix observes durable state rather than enforcing an order. Read alongside `release.md` when the reconcile step surprises you.

**3. `healthchecks.md` → `contracts`** — requires adding a `## Specific
Information` section, which the skill currently lacks (legal; `skills.md` makes
it optional).

> ## Specific Information
>
> The reasoning under the requirement. **Read on demand.**
>
> [`healthchecks.md`](../../doctrine/infrastructure/reasoning/healthchecks.md) — one paragraph on *why* every core service must declare a healthcheck: a system that autoscales and is evaluated by machine has no other way to be judged. `contracts.md` states the requirement; this states its motive.

**Two honest corrections to cohere's F2**, neither of which changes the ruling:

- The report says all three are "referenced by **zero** … other doctrine files."
  That is wrong for `healthchecks.md`: `elastic_release_pattern.md:26` links it
  (with the misspelled link *text* the spelling table catches). The conclusion
  survives intact and is arguably sharper — its only inbound link is from a file
  that is *itself* unrouted, so it is reachable only from something unreachable.
- The pointer text above is nearly as long as its target. `healthchecks.md` is
  **two sentences**. Sarge has already seen and declined the fold-into-
  `contracts.md` alternative, so I am landing the pointer as ruled; I flag only
  that it promises a document more substantial than the one it opens.

### F1 — rewriting `reasoning/elastic_release_pattern.md`

Sarge: rewrite, do not delete; the *why* is valuable and only the mechanism
changed. Escalated for reading before landing.

**What is stale** (all in the `:18`/`:22` block): "all ECS services must be
launched *twice*"; "any release which adds a new named piece of infrastructure
must perform a double-rollout"; "This shape-changing detection is part of the
release process." `grep -rni 'double.rollout|shape.chang' docex/src` returns
nothing — the executor never implemented any of it.

**What is sound and is kept**: the three name-resolution mechanisms and why ALB
and Service Discovery are both unavailable; Service Connect as decentralized
client-side resolution; and the launch-time name freeze itself, which Step 0
observed on real AWS.

**One factual correction folded in**, from the Step 0 recon: the name is created
with the **ECS service**, not with its first task. The draft therefore attributes
registration durability to the service rather than to task liveness, matching
`release.md`'s tie-breaking note.

**Knock-on resolved:** because the file is rewritten rather than deleted,
`charts/ecs_service_connect.md` keeps its sole inbound link and needs no
re-homing.

#### Draft (full replacement body)

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

**Nothing in the draft is new doctrine.** Every claim restates Mod 114's
approved output: the concurrency race and the cycle argument from
`release.md`'s reconcile section, the durability argument from `cicl.md §
Resilience covers reachability, not resolvability`, and the aborted-release
sentence from `release.md:106`. The draft deliberately **routes to** those two
sections for the mechanism rather than restating it, so the reasoning file
cannot drift from them the way the current text did.

---

## 5. Part D — the remaining semantic findings (my judgement)

Sarge's test: *land what restores what the doctrine already says elsewhere;
escalate what would be choosing what it says.*

| ID | Call | Reasoning |
| -- | ---- | --------- |
| **F14** escalation ladder | **LAND** | Pure restoration. The file's own `:88` says "it escalates that decision to its C.O. … decisions ripple all the way up to the human operator", and `:36-40` fixes the order private < corporal < sarge. The table's `private → private` / `corporal → corporal` cells contradict prose in the same file; the intended ladder is *derivable*, not choosable. Two cells. |
| **F18** duplicate `configurable.md` | **LAND**, reported | `linkcheck.py`'s only current finding; fails the cohere skill's own check 3. Renaming `charts/configurable.md` → **`charts/configurable_flow.md`** (it *is* a flow diagram; the sibling chart names are already irregular). **Correction to the report:** it claims one inbound link from `skills/configurable-vars/SKILL.md`. There is **none** — that skill links only the resident `infrastructure/configurable.md`. Grep confirms **zero** inbound links to the chart from anywhere. So the rename moves no link — but it also means the chart is an orphan, which is the larger latent problem and which I am **not** fixing here (routing it is an F2-class decision nobody has ruled on). Flagged for the record. |
| **F17** lexicon entries for `uses` / `role` | **RULED: no entries; record the criterion** | Escalated as Q4; sarge ruled no. The lexicon defines *concepts*, not CICL field names. One criterion line lands in `lexicon.md`'s intro so the next audit does not re-raise it as an omission. |
| **F21** `docex-edit` declares `type: thread` with no thread body | **RULED: defer to advance 006** | Escalated as Q5; sarge ruled defer. Restructuring a skill body belongs in `skill-iteration` **with its trigger and outcome evals**, not the tail of a fix mod. Logged as a stub, not silently dropped. |

---

## 6. Part E — the executor changes

Three, all approved at design review: `linkcheck.py` gains `skills/` coverage
(§ 6.1), `verify_examples.py` is promoted from scratchpad to shipped tool
(§ 6.2), and `chunk_map.py` gets F10's code half (§ 6.3).

### 6.1 `linkcheck.py` covers `skills/`

`doctrine.md:57` calls keeping thread-skill pointers valid "the one ongoing cost
of this structure, and it should be checked mechanically." The shipped executor
walks `doctrine/` only. The audit checked skill links by hand with a scratch
variant and found them all resolving — a result that is not reproducible.

**The gap is sharper than "skills aren't scanned."** At `linkcheck.py:131` the
anchor check is guarded by `if rp in anchors` — `anchors` is built only from
files *under the scanned root*. So even today, a `doctrine/` link into any file
outside `doctrine/` has its **anchor silently unchecked**; it fails open. Adding
`skills/` as a second source root closes both halves at once: skill→doctrine
links get scanned, and doctrine↔skill anchors enter the table.

#### Design

1. **Multiple roots.** Default to `$jb/doctrine` **and** `$jb/skills`. Positional
   args override. Backward compatible: a single explicit root still works, which
   keeps the cohere skill's documented invocation valid.
2. **One anchor table across both trees**, so cross-tree anchors resolve.
3. **Check 3 (duplicate filenames) stays scoped to `doctrine/` only.** This is
   the load-bearing decision. `skills/` contains ~22 files named `SKILL.md` by
   the Agent Skills Standard; including them would emit 22 false positives and
   make the check useless. The doctrine's uniqueness rule is a *doctrine-corpus*
   rule — `doctrine.md` states it about doctrine files. The rule is not being
   changed, only applied to the tree it was written about.
4. **Display paths** become relative to the common repo root, since `relpath`
   against one of two roots would be ambiguous.

#### Tests

New `docex/tests/unit/test_linkcheck.py`, loading the script by path
(`importlib.util.spec_from_file_location`) since it lives outside the `docex`
package. Against synthetic `tmp_path` trees, asserting:

1. A clean two-tree corpus → exit 0.
2. A skill→doctrine link to a **missing file** → caught. *(Not caught today.)*
3. A skill→doctrine link to a **missing anchor** → caught. *(Not caught today —
   this is the regression the advance's three section renames could have caused.)*
4. A doctrine→doctrine broken link → still caught (no regression).
5. Two `SKILL.md` files under `skills/` → **not** reported as duplicates.
6. Two same-named doctrine files → still reported.
7. `slugify`'s no-collapse behaviour on a `/`-bearing heading → preserved
   (guards the documented original false-positive bug).

Placing a `skills/` test inside `docex/tests/unit/` is mildly incongruous — it is
not `docex` code. It is deliberate: that suite is the only harness the release
gates actually run, and an untested check is what this finding is about.

### 6.2 Promote `verify_examples.py` into `skills/cohere/executor/`

The argument, in one line, for the mod docs and the skill:

> This advance found the canonical example broken **twice** — by Mod 118's
> compile harness and by this mod's independent tab census — and *neither* was
> a shipped check.

The harness moves from the scratchpad to `skills/cohere/executor/verify_examples.py`
and becomes a real tool:

1. **Roots default** to `$jb/doctrine` + `$jb/skills`, matching `linkcheck.py`
   so the two executors take the same arguments.
2. **The `docex` import is resolved, not assumed.** The scratchpad copy relied on
   `PYTHONPATH=src` and a cwd inside `docex/`. The shipped version locates
   `$jb/docex/src` relative to its own `__file__` — the same trick
   `linkcheck.py:21-22` already uses for `DEFAULT_ROOT` — and fails with a clear
   message if `docex` cannot be imported rather than a bare `ImportError`.
3. **Exits non-zero** on any parse or validation failure, so it can gate.
4. **Reports counts** — fences scanned, parsed, validated, tabbed — because those
   counts are this mod's verification contract.
5. **Classification stays as-is.** Fences are triaged into full documents (parsed
   + validated), spliceable fragments (spliced into a skeleton, then validated),
   and non-CICL YAML (parse-only). That triage is the harness's real
   intelligence and is not being redesigned in this mod.

**Test:** `docex/tests/unit/test_verify_examples.py`, same by-path import as
`test_linkcheck.py`. Against synthetic corpora: a clean fence passes; a
**tab-indented** fence is reported; a fence with an undeclared `uses` target is
reported; a fence missing a required top-level field is reported (the A5 class);
a non-CICL yaml fence is parse-checked but not validated; and the exit code is
non-zero exactly when findings exist.

**Both executors get documented in `skills/cohere/SKILL.md`.** Its § Mechanical
Problems names only `linkcheck.py` today. Note that its checklist has three
items and the harness covers a **fourth** class — *examples that do not compile*
— which no item currently names, so the list gains an item rather than the tool
being wedged under an existing one.

### 6.3 `chunk_map.py` — F10's code half

JSON key `"services"` → `"codebases"` (`:197`), chunk-kind label (`:222`), and
`_discover_services` → `_discover_codebases` (`:120`, plus call sites and local
names at `:206-222`, `:241`, `:245-251`).

**Safety condition discharged before landing**, per sarge's requirement: nothing
parses the key. `evals.json` has **zero** mentions of `services`; the only
matches in the tree are docker-compose's unrelated `services:` key in
`docex/emit/compose.py` and immutable run transcripts recording the *command*,
not the key. The sole consumer is the skill agent reading `SKILL.md`, which
F10's prose half updates in the same commit.

---

## 7. Verification

Reported as a table with a verdict **and its instrument** per row, per sarge.

| Gate | Target | Instrument |
| ---- | ------ | ---------- |
| Every `yml` fence parses | 42/42 | I1 |
| Every `infra.yml`-shaped fence validates under `cicl_version: "3"` | all shaped fences OK, 0 failed (from 4 OK / 3 failed) | I1 |
| Tabs eliminated | 0 of 42 fences tabbed (from 16) | I1 + the independent census |
| Links / anchors / dup filenames | green across `doctrine/` **and** `skills/`, run as the **shipped** tool | I2 |
| Unit tests | 988 + new `linkcheck` tests, 0 failed | I3 |
| Integration tests | 20 passed / 0 failed, unchanged | I3 |

I1 must be re-run **after** the A5 fix specifically: the pydantic failure masks
validation on that fence entirely, so its first-ever validation happens in this
mod and may surface further defects.

## 8. Scope guards

- **Held, untouched:** `clock.md:96`'s binding-coverage sentence is with the
  operator.
- **No rule changes.** Nothing here alters Mod 112's output.
- **Commits are path-scoped**; inner-repo cadence if anything reaches
  `test_projects/`. Current expectation: **nothing does** — every A1 site is in
  `doctrine/`, and the smoke projects are already on `appdb`.

---

## Rulings (sarge, at design review)

Design approved. All five questions ruled, plus two additions.

**Q1 — Promote the compile harness. APPROVED.** `verify_examples.py` moves into
`skills/cohere/executor/` beside `linkcheck.py`, with its own test. The
one-line argument, to be stated in the mod docs and the cohere skill:

> This advance found the canonical example broken **twice** — by Mod 118's
> compile harness and by this mod's independent tab census — and *neither* was
> a shipped check.

**Q2 — Take (b).** Move `BUCKET_NAME` into `web`'s own `env:`. Sarge: under (a)
the fence would teach readers to add edges to silence a validator, which is the
opposite of what `uses` means; under (b) it teaches one more true thing than it
did before. Changing what the canonical example teaches is the right reason to
prefer a fix, not a reason to hesitate.

**Q3 — Both halves. Condition discharged.** Sarge conditioned the rename on
nothing consuming the JSON key. **Verified: nothing does.**
`skill_iter/eval/outcome/project-cohere/evals.json` contains **zero** mentions of
`services`; the only hits anywhere are (i) `docex/emit/compose.py`, which is
docker-compose's own unrelated `services:` key, and (ii) `full.run.2x*.json`,
which are immutable historical run transcripts recording the *command invoked*,
not the key parsed. The sole consumer is the skill agent reading `SKILL.md`, so
the rename is self-contained and safe.

**Q4 — No lexicon entries; record the criterion.** The lexicon defines
*concepts*, not CICL field names — `depends_on` and `consumes` never had entries
across their lifetimes, and neither do `env:`, `networks:`, or `resources:`. One
criterion line lands in **`lexicon.md`'s own intro** (its durable home, per the
Mod 118 precedent of filing the `doctrine_excerpts` decision in
`docex_process.md` rather than a mod folder), so the next audit does not
re-raise this as an omission. An unrecorded "no" is indistinguishable from an
oversight.

**Q5 — Defer `docex-edit` past the cut.** Logged to advance 006. Not caused by
this advance; a `type: thread` declaration without a thread body is an honesty
defect rather than a correctness one; and decisively, restructuring a skill body
belongs in the `skill-iteration` process **with its trigger and outcome evals**.
Doing it here would change a trigger surface with none of the machinery that
exists to verify trigger surfaces.

### Two additions

**F18 — add the inbound router too.** Declining to fix the orphan unasked was the
right instinct, and the answer is yes: `charts/configurable_flow.md` gets a
router pointer from the `configurable-vars` skill, same treatment and same
`## Specific Information` placement as F2's three. Leaving one known orphan
behind in the pass that fixed three others would be an odd place to stop.

**Placement reasoning preserved.** The `## Specific Information` call is correct
and its rationale stays in this document. The `healthchecks.md` pointer being
nearly as long as its target lands anyway — but **is stated in the mod docs**
rather than quietly absorbed.
