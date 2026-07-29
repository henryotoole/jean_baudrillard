# Mod 107 — Advance closeout: smoke projects, upgrade guide, changelog, version

Closes the **service process types** advance (mods 094–106) and leaves the repo
**ready-to-cut** at 1.6.0. This mod writes no new `docex` capability; it makes
the seed, the operator-facing documents, and the version artifacts agree with
the thirteen mods that precede it.

Per the operator's autonomy ruling this mod stops at ready-to-cut: **no `v1.6.0`
tag, no `docex:1.6.0` image build, no real-infra smoke walk, no
`pytest -m integration`.** Those four are the operator's.

---

## Baseline, verified before designing

| Check | Result |
| ----- | ------ |
| Branch | `main` — correct for this repo (`docex_process.md § Git`) |
| Working tree vs. `baseline_dirty.txt` | **byte-identical**, 118 entries |
| `pytest tests/` | **1046 passed, 17 deselected** |
| Current version | `1.5.0` in all four tracked artifacts |

The eight already-dirty files under `docex/test_projects/` are **purely
`campaign` → `advance` prose renames** in comments and changelog narrative
(one line each, no structural content). They do not conflict with this mod.
One of them — `infra/contracts/web.openapi.yml` — is a file this mod
**renames**; the rename must carry the dirty content forward rather than
reverting it.

---

## Deliverable 1 — Migrate both smoke projects to `cicl_version: "2"`

### The problem this deliverable actually has to solve

The instruction "add a genuine `worker` process type" collides with a fact about
the current seed that has to be dealt with head-on: **`test_projects/{fixed,elastic}`
already contain a core service named `worker`** — and it is `role: web` with no
port, because `role: worker` did not exist before Mod 095. There are three
codebases, each with exactly one process:

| Codebase | current `role` | shape |
| -------- | -------------- | ----- |
| `web` | `web` | port 8080, `[web, internal]`, `health_check_path: /health`, owns the schema |
| `worker` | **`web`** (a workaround) | no port, `[internal]`, polls the `pings` table |
| `reaper` | `scheduler` | nightly prune |

A mechanical nesting of that shape yields `web-web`, `worker-worker`, and
`reaper-reaper` — three instances of the doubling the C.O. flagged, and it
exercises **none** of the advance's motivating capability, because no codebase
would have more than one process type.

That gap is not hypothetical. **No committed fixture has a multi-process
codebase either**: `sample_project` and `sample_project_elastic` are `api.web`
alone, and both scheduler fixtures are `nightly_cleanup.nightly_cleanup`. The
one-codebase-N-processes expansion — the backbone of the entire advance — is
today proven only by unit tests that build the model inline. If the smoke
projects do not carry it, nothing committed does, and the pre-cut walk cannot
gate it.

### The design: `web` + `worker` merge into one codebase `api`

The current two-codebase split **is an artifact of the limitation this advance
removes.** `web` and `worker` share one database, one table, and (verbatim) six
`DATABASE_*` magic refs; they were split into two codebases only because
pre-1.6.0 CICL had no way to say "one artifact, two invocations". Merging them
is the migration, not an embellishment — and it lands the seed on exactly the
shape `cicl.md § Process Types` uses as its own worked example (`api.web` +
`api.worker`, each consuming the other).

```yml
cicl_version: "2"
domain_default_process: api.web

core_services:
  api:
    env:                                  # codebase-scoped: both processes need a DB
      DATABASE_HOST: ${backing_services.appdb.host}
      … (6 refs, unchanged)
    processes:
      web:
        role: web
        command: ["python", "/service/dist/entrypoints/web.py"]
        port: 8080
        networks: [web, internal]
        health_check_path: /health
        depends_on: [appdb, probe, events]
        consumes: [api.worker]
        env:                              # process-scoped: only the web edge probes these
          SIDECAR_HOST: ${backing_services.probe.host}
          … (4 refs)
      worker:
        role: worker                      # was `role: web` — the real fix
        command: ["python", "/service/dist/entrypoints/worker.py"]
        port: 8081
        health_check_path: /health
        networks: [internal]
        depends_on: [appdb]
        consumes: [api.web]
        replicas: 2
  reaper:                                 # codebase name unchanged
    env: { DATABASE_* }
    processes:
      prune:                              # named after the job, per Q2
        role: scheduler
        schedule: "0 3 * * *"
        command: ["python", "/service/dist/entrypoints/prune.py"]
        networks: [internal]
        depends_on: [appdb]
```

Emits `api-web`, `api-worker`, `reaper-prune` — no doubling anywhere, and no
registry-repo churn for the scheduler codebase.

**Three decisions inside that block are load-bearing:**

1. **`env:` is split across both levels, deliberately.** The six `DATABASE_*`
   refs go to the service level (both processes need a database); the four
   `SIDECAR_*`/`CLICKHOUSE_*` refs stay on `api.web` (only the web edge exposes
   `/health/probe` and `/health/events`). This is the honest split, and it
   exercises the two-level merge — the one exception to field scoping, and
   flagged item #11 — in a real project. It also keeps `depends_on` truthful:
   per rule 7 a *service-level* ref obliges **every** process type, so hoisting
   the sidecar refs would force `api.worker` to declare `depends_on: [probe,
   events]` on backings it never touches. **This is the "hidden step" the plan
   warned about**, and splitting `env:` is what contains it to `[appdb]`.

2. **`consumes` is declared in one direction only: `api.web consumes
   api.worker`.** This is a correction to the first draft of this design, which
   proposed the mutual `web ↔ worker` cycle from `cicl.md`'s example in order to
   exercise cycle acceptance. It would have been a **false declaration**: this
   worker polls a table and never calls the web edge. Cycle acceptance is
   already covered by Mod 098's unit tests, and the seed is the file downstream
   projects copy — honesty beats coverage here. The one true edge earns its
   keep: `api.web` holds four-segment magic refs to the worker's host and port
   (which *oblige* the edge, per rule 7), and the edge in turn makes
   `api.worker` a provider — yielding an **AsyncAPI** contract, the format path
   that was *provably unreachable* until Mod 101, and the `/health/api/worker`
   fan-out. `api.worker` owes no fan-out of its own: that obligation falls on
   `web`-network process types only.

3. **`replicas: 2` on the worker of *both* projects.** Elastic puts a real
   `desired_count = 2` through `tofu validate`; fixed is the only thing that
   will ever exercise the replica unroll, since every integration test runs
   against `dev` where the clamp applies. The worker is the right host for it —
   `replicas` is rejected on a `scheduler`, and putting it on `api.web` would
   drag traefik/ALB aggregation into the same step.

### Consequence: the seed needs real application code

This is the part that exceeds "edit `infra.yml`", and it is forced by doctrine
Mod 094 already wrote, not invented here:

- **`src/entrypoints/`** — `internal_dependency_rules.md § Entrypoints` requires
  each process type's `command` to invoke one module under `src/entrypoints/`,
  and the composition root to construct without activating. The seed has
  neither; `root.py` currently does both, and both `web` and `worker` run
  `CMD ["python", "/service/dist/root.py"]`. With two process types on one image
  that is no longer expressible. → `entrypoints/{web,worker}.py` in `api`,
  `entrypoints/prune.py` in `reaper`; `root.py` becomes construct-only.
- **A liveness tick in the worker.** `contracts.md § Health Checks` requires a
  loop-owning process type to serve `GET /health` on its port from an
  **in-process monotonic tick**, 503 when stale, tick ≤ 10 s even when idle,
  staleness threshold 30 s — doctrine-fixed, no knob. The current worker is a
  bare polling loop with no HTTP surface at all. → a small health server plus a
  tick bumped by the poll loop.
- **`/health/api/worker` on the web edge** — one hop, short hard timeout, never
  calling the target's own fan-out.
- **`curl` in the merged image** — the gate keys off `health_check_path` with no
  network filter, and `worker`'s current Dockerfile has no `curl`. The merged
  `api` image inherits `web`'s, which already installs it. (Worth noting this
  gate was a **silent pass** until Mod 096 fixed it, so it fires against this
  seed for the first time.)

Estimated genuinely-new code: ~80 lines, written once and shared by both
projects under the B.14 code-identity rule.

### Scope of file changes

Per project (`fixed/`, `elastic/`), `core/` kept byte-identical between them:

- `infra/infra.yml` — as above
- `core/web/` → `core/api/`, absorbing `core/worker/src/hex/processor/`; new
  `src/entrypoints/`; `core/worker/` deleted
- `core/reaper/` — folder and codebase name unchanged; gains
  `src/entrypoints/prune.py`
- `core/reaper/Dockerfile` — the header documents mod 074's self-contained job
  image, **retired by Mod 103**; the `prod`-stage rationale is now false (dev
  jobs run the `dev` stage)
- `infra/contracts/web.openapi.yml` → `api.web.openapi.yml` (+ the
  `/health/api/worker` path); **new** `api.worker.asyncapi.yml`
- `infra/stage/tests/test_smoke.py`, `plans/core/**`, `CHANGELOG.md`
- `project.yml` — `docex_version` → `1.6.0` (see *Version artifacts*)

Repo-level, because the walk instructions must not go stale under a walk that
is now load-bearing:

- `docex/test_projects/PRE_CUT_CHECKLIST.md` — B.9 contract path, B.10 health
  paths, **B.11 gains `src/entrypoints/`**, B.14, C.6/D.8 image names, C.9/D.11
  hostnames + `domain_default_process`, D.9's ECS service list, and the dangling
  `release_mechanism.md` link at `:104`
- `docex/plans/core/test_projects.md` — still describes "two cores (`web`,
  `worker`)" and a backing service named `db`
- `fixed/teardown.sh:75` and `fixed/verify_clean.sh:45` — both hard-code
  `for service in web worker`, which becomes `api reaper`. **Pre-existing bug
  found here:** `reaper` is absent from both lists today, so its registry repo
  survives teardown and `verify_clean` cannot see it — a real leak, in a walk
  this mod is about to make load-bearing for scheduler coverage. Fixed in
  passing.

---

## Deliverable 2 — `upgrades/upgrade_1.6.0.md`

`version: "1.6.0"`, `severity: minor`, `kind: incremental`,
`scope: [machine, project]`. Spine is the design record's
*not-process-qualified* inventory plus the nine numbered migration steps, in
`upgrade_1.5.0.md`'s voice.

Beyond the plan's list, four items are **corrections to what the mods
predicted**, established by reading the code rather than the notes:

1. **The `cicl_version: "1"` rejection message is unreachable for the document
   it was written for.** Mod 096 built a bespoke message naming this guide, but
   it lives in a `mode="after"` model validator on `CICLDocument`
   (`cicl/model.py:298-317`), which runs only after nested field validation
   succeeds. A real v1 `infra.yml` fails inside `CoreService` first, so the
   operator sees per-service field-scoping errors plus `extra_forbidden` on
   `domain_default_service` — never the version message. Verified by running
   `compile` against the un-migrated fixed project. Not fatal: the field-scoping
   messages are good and *do* name this guide. But the guide must show the error
   the operator will actually see. See design question **Q5**.

2. **`alb` and `iam` did not change in this advance; the fourth name segment
   is what makes them bite.** The only edit to `tables/naming_policies.yml` is
   `http_host`. `alb`'s 32-char `hash_truncate` dates to mod 069 and `iam`'s
   64-char cap to mod 005/030. Also: `iam` does not literally declare
   `overflow: error` — it inherits the default. The guide should say "a policy
   that always existed now has a longer name to apply itself to", because
   "the policy changed" would send an operator looking for a diff that isn't
   there. Consequence for `alb` is concrete: **target groups whose names
   previously fit are destroyed and recreated on first apply.**

3. **Rollback's refusal message**, quoted verbatim from `_boundary_message`
   (`pipeline/rollback.py:286-318`) rather than paraphrased, including the
   two-step fix-forward block and the closing "Once a second `cicl_version` "2"
   release exists, rollback works normally."

4. **`${a-b}` has no escape, at any layer.** Confirmed: the grammar is exactly
   `${var}`, `$[var]`, `@expr`; `transfer_tables.md § Substitution Grammar`
   documents no escape; the `$$` doubling in the tree is applied by *emitters*
   after substitution and never reaches the resolver. The guide says "rename the
   variable" and explicitly warns off `$${…}`.

Plus, from the plan: rollback unavailable for one release cycle; public DNS
records for every new web hostname **before** `envinfra up dev` on fixed, or
Let's Encrypt's failed-authorization limit trips (`docex preinfra development`
surfaces the gap); new emitted names across containers/ECS services/task
defs/log groups/sidecars/traefik routers/hostnames; the scheduler-only naming
guidance (name the codebase after the codebase and the process after the job —
`reaper.prune`, per resolved Q2); and the
`migrate.sh`/`test.sh`/`build.sh` **service-level-`env:`-only** break, which is
the one most likely to bite silently.

---

## Deliverable 3 — `CHANGELOG.md`

One `[1.6.0]` entry covering mods 094–106, keepachangelog buckets, built from
all thirteen `overview.md` files (not the diff). Notable items whose
significance exists only in the overviews:

- **Nine silent-failure fixes** that a reader of the diff would take for
  refactors — among them `emit/ansible.py` comparing an authoring
  `schema_owned_by` against a compiled name (the fixed stage/prod playbook would
  have emitted **no migrate tasks while reporting success**), the `curl` gate
  having been a **no-op since process fields moved**, `_infer_contract_format`'s
  asyncapi branch being **provably unreachable since written** (which is *why*
  the health-gate `depends_on` flaw survived), hyphenated four-segment magic refs
  being **emitted verbatim into compose/HCL as literal text**, and `docex build
  dev` being **broken for scheduler-only codebases** by a regression Mod 099
  shipped and Mod 103 caught.
- **`replicas` was declared, range-checked, documented, and read by nothing**
  until Mod 100 — `desired_count` was hardcoded to 1.
- Mod 106's doctrine corrections are changelog-relevant because several were
  *falsehoods*, not staleness — including that the sidecar count is a **sum, not
  the design record's `N × R` product**.

---

## Deliverables 4 & 5 — version artifacts and the two carried decisions

**Version → 1.6.0** in the four artifacts `RELEASING.md` tracks: `VERSION`,
`docex/pyproject.toml`, `docex/src/docex/__init__.py`, and
`.claude-plugin/plugin.json` (**load-bearing** — the plugin cache is keyed on
it, so a stale value silently strands the new skill set). All four are at
`1.5.0` and in sync now.

Three more version sites, none in that table:

- `docex/test_projects/{fixed,elastic}/project.yml` — `docex_version: "1.5.0"`.
  **These must move to `1.6.0` in this mod**, not at walk time as A.2 implies:
  a project migrated to `cicl_version: "2"` cannot compile under a `1.5.0`
  image, so leaving the pin would ship a seed that cannot run at its own pin.
  The image won't exist until the operator builds it — expected, and A.2 builds
  it first.
- `docex/uv.lock:62` — carries docex's own version; needs the bump (or a
  re-lock) or it silently goes stale.
- `docex_install.sh` derives the pin by grepping `pyproject.toml`, which makes
  that file **functionally load-bearing**, not the "packaging metadata"
  `RELEASING.md:24` calls it. Worth a note in the guide.

`skill_iter/.../fixtures/_base/project.yml` also pins `1.5.0` but sits in the
operator's untracked in-progress work — **left strictly alone**.

**`compose_exec` docstring.** Verified stale: `docker/client.py:112-127` still
names `docex build`, `docex migrate`, and `docex test`'s build-test step, all
three of which moved to `compose_run_one_off` (`migrate.py:116`,
`build.py:146`, `test.py:103,127`). Confirmed **zero production call sites** —
only the protocol declaration, the subprocess implementation, the test fake, and
four assertions that its call list is empty. Docstring corrected; **method
kept**, per the pre-made ruling. This is the mod's **only** `src/` change.

**Eight dangling links in `docex/plans/core/`** — the inherited count is right
but the breakdown is wrong, and a naive fix would create three *new* breakages:

| # | Site | Correct target |
| - | ---- | -------------- |
| 1 | `masterplan.md:17` | `specifics/release.md` |
| 2 | `masterplan.md:17` (`elastic_bootstrap.md`) | `specifics/projinfra/elastic_state_backend.md` |
| 3 | `masterplan.md:104` (`#implementation-order`) | **no successor — delete the clause** |
| 4 | `masterplan.md:315` (`…#caveats`) | **`config_and_secrets.md#caveats`**, not `release.md` |
| 5 | `release_flow.md:3` | `specifics/release.md` |
| 6 | `release_flow.md:80` (`#backward-compatibility-requirement`) | **`migrations.md#…`** (anchor survives verbatim) |
| 7 | `release_flow.md:230` | same as 6 |
| 8 | `test_projects.md:78` | empty `](#)` placeholder — **missed by the prior mod** |

Corrections to the inherited note: there are **five** `release_mechanism.md`
links, not six (`masterplan.md` ×2, not ×3); the `#implementation-order` anchor
is at `masterplan.md:104`, not `:17`; and `release_mechanism.md` was split
**three ways**, so #4 and #6/#7 must follow their content to
`config_and_secrets.md` and `migrations.md` respectively — retargeting all five
at `release.md` would leave three anchors dangling. A **ninth** live instance
sits at `PRE_CUT_CHECKLIST.md:104`, inside this mod's scope anyway.

---

## Staging

`implementation.md` will be staged per deliverable so each is independently
reviewable: **(A)** smoke-project migration + walk-doc alignment, **(B)**
upgrade guide, **(C)** changelog, **(D)** version artifacts + the two carried
decisions.

Verification available without docker: `PYTHONPATH=…/docex/src python3 -m docex
compile` run from each project root — `compile` is pure (`load_project_context`
+ `run_compile`, no docker), and this path already reproduces the migration
errors, so it will confirm both projects compile and let the emitted output be
inspected directly. Expected end state: **1046 passed / 17 deselected**
unchanged, since the only `src/` change is a docstring.

---

## Design questions — resolved

All six were answered by the C.O. before implementation. Recorded here because
two of them changed the design.

**Q1 — the merge. APPROVED.** `web` + `worker` collapse into codebase `api`
with process types `web` + `worker`, and this mod restructures the seed's
application source to do it. The decisive reasoning, per the C.O., is not that
the current split is a pre-095 workaround but that **no committed fixture
carries a multi-process codebase either** — so without this, the pre-cut walk
that gates a minor release never validates the release's headline capability
end to end, and 1.6.0 would be cut on unit tests alone for the one thing it is
*for*. The ~80 lines of seed code are approved on the grounds that
`src/entrypoints/` and the liveness tick are what the doctrine now *requires* of
every downstream project, making this seed the **reference implementation** —
so `contracts.md`'s thresholds are followed exactly (monotonic tick, ≤10 s even
when idle, 30 s staleness, 503 when stale), because it will be copied.

**Q2 — CHANGED from my recommendation.** The codebase **stays `reaper`**; the
*process* is named after the job → `reaper.prune`, emitting `reaper-prune`. This
is both cheaper (no folder rename, no new registry/ECR repo, no image-name churn
in the walk) and more faithful to `cicl.md § Naming convention`, whose rule is
`role: scheduler` → *the job's name*, precisely because a codebase commonly has
several jobs. `reaper` is already a codebase noun; the doubling was never the
codebase's fault. My `jobs` proposal solved the doubling by moving the wrong
name.

**Q3 — `PRE_CUT_CHECKLIST.md` is in scope, and not optionally so.** A checklist
citing a contract path, health path, image name, and hostname that no longer
exist would misroute the very walk this mod exists to enable.

**Q4 — document prominently; do not touch the clamp.** The prod-only clamp
stays (it is flagged item #8 and the operator's call). But
`PRE_CUT_CHECKLIST.md` must say **in as many words** that the prod release is
the only thing in existence that exercises the fixed replica unroll, so skipping
C.9 means shipping that code untested. This finding *strengthens* the case for
letting `stage` honour `replicas` — recorded here as input to #8, not as a
reopening of it: `stage` exists to be production-equivalent, and the one shape
it cannot rehearse is the one whose failure mode (a process type that does not
tolerate siblings) the doctrine already admits it cannot catch.

**Q5 — attempt the fix, with a bail-out.** Authorized to try the
`mode="before"` validator, because this is the single most-read error message
the release produces: every downstream project hits it exactly once, while
upgrading, at the worst possible moment, and a wall of field-scoping errors is
strictly less actionable than one sentence naming the guide — even granting the
field errors also name it. **Bail-out condition:** if it costs more than a small
validator change plus one test, stop and document instead. Either way the
upgrade guide shows what the operator *actually* sees. The path taken is
reported at the end of `implementation.md`.

**Q6 — fixtures keep `nightly_cleanup.nightly_cleanup`.** Unit fixtures are
test scaffolding, not teaching material; churning them for cosmetics risks a
green suite for no gain.

**Advance-level:** the missing `queue` role is carried up by the C.O. as the
headline loose end. No action here.

**On the advance as a whole** — one gap I can see from here that no mod owns:
the **`queue` role still does not exist** (flagged item #4). The advance's
motivating example is a queue consumer, `cicl.md`'s worked example now declares
its broker as `role: cache` with a redis engine explicitly because there is no
alternative, and this mod's smoke projects will do the same thing (their
"worker" polls a postgres table — a legitimate shape, but not the one the
advance is *about*). 1.6.0 ships a first-class `worker` role with no
first-class thing for it to consume. That is coherent and shippable, but it is
the most visible loose end the advance leaves, and it will be the first question
a project author asks.
