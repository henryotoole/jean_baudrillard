# Mod 094 — Doctrine: process types, `consumes`, and the rule restatements

Phase 0 of the [service process types advance](../../advances/004_next/service_processes_implementation_plan.md#mod-094--doctrine-process-types-consumes-and-the-rule-restatements).
The design is settled in
[`service_processes_refactor.md`](../../advances/004_next/service_processes_refactor.md);
this mod writes the **rule of record** into the doctrine so that mods 095-105
have something to be measured against.

**Doctrine prose only.** No `docex` code, no transfer tables, no tests. Per
[`docex_process.md`](../../core/docex_process.md) step 1, the doctrine always
changes first.

## Why

The doctrine currently fuses three axes that are independent in general
practice: codebase, build artifact, and process type. Image identity is keyed
off the `core_services` CICL key, and "core services never share code" then
turns a new *scaling unit* into a new *codebase*. The advance decouples one
joint — build artifact → process type becomes 1:N — via a mandatory `processes:`
block, and splits `depends_on` into a readiness relation (`depends_on`, backing
services only) and an interface relation (`consumes`, core process types only).

Everything downstream of that — emitted names, hostnames, contract paths, health
paths, `OTEL_SERVICE_NAME` — gains a process segment. This mod states the rule;
later mods make `docex` obey it.

## Scope

Seven doctrine files — resident stratum first, then conditional — plus two
skill bodies swept for falsified prose (see [Skills sweep](#skills-sweep)).

### `doctrine/lexicon.md` (resident)

- **Core Service** — clarify as *codebase + build artifact*: one source folder,
  one image, one or more process types. The core/backing axis is about whose
  code it is, which has not moved.
- **Process Type** (new) — the infra-level declaration; a scaling unit with its
  own role, command, resources, networks, and port. 12-factor's own term.
- **Entrypoint** (new) — reserved for the *code module* a process type's
  `command` invokes. Explicitly **not** the infra noun: the word is already
  spent on Dockerfile `ENTRYPOINT` and traefik entrypoints.

Rows go immediately after **Backing Service**, keeping the table's existing
service-first ordering.

### `doctrine/hexagonal_architecture/internal_dependency_rules.md` (resident)

§ Composition Root responsibility (4) — *"Registering every HTTP controller's
router with the application"* — is the one line where a runtime host (Starlette)
got baked into the composition root. It moves out.

- Responsibility (3) is amended: the root instantiates every driving adapter for
  **every** mechanism, regardless of which process type is running. Controller
  construction is free — it captures a port reference and performs no I/O.
- Responsibility (4) is deleted from the list.
- A new **§ Entrypoints** subsection carries the rules that follow from the
  design record § Resolution — Code Side: one composition root and one
  entrypoint per process type; entrypoints call `build()` and never a concrete
  adapter constructor; the runtime host is not an adapter; never
  `root_web.py` / `root_worker.py`; inverted-control registration
  (Celery-style decorators) belongs in the entrypoint, not the adapter; an
  expensive single-consumer driven adapter goes lazy internally rather than
  forking the root; and a long-running entrypoint that owns a loop must expose
  that loop's liveness.

The liveness rule is a **router, not a copy**. The tick is a code-side
obligation but its specification — the monotonic tick, the thresholds, the
endpoint shape — is conditional-stratum material, so the resident rule states
the obligation and links to
[`contracts.md § Health Checks`](../../../../doctrine/infrastructure/contracts.md#health-checks)
rather than restating any of it. Resident points; conditional specifies.

### `doctrine/hexagonal_architecture/hex_overview.md` (resident)

- `entrypoints/` added to the `src/` tree beside `root.py`, with `http.py` /
  `worker.py` as the illustrative members.
- An `entrypoints` row in the folder-purpose table.
- A `Queue` row in the controller-mechanism table (`ContBrokerQueue`), which
  resolves a live cross-stratum contradiction: the driven table already carries
  the `Queue` pattern for the producer side, and a queue consumer is a driving
  adapter on the *same* driving port as the HTTP controller.
- One sentence in § Tests: entrypoints are too thin to test — if an entrypoint
  needs a test of its own, it is doing too much and the surplus belongs in an
  adapter or in alogic. This heads off a real class of bad tests that would
  otherwise accumulate at the new layer.

### `doctrine/infrastructure/infrastructure.md` (resident)

- **"Core services never share code"** re-scoped to core service **sources**.
  Sibling process types are one codebase, so nothing is shared and the rule's
  intent survives intact. A pointer is added: when only the *invocation*
  differs, the answer is a process type, not a second core service. This
  re-scoped rule is now what carries the point that two genuinely separate core
  services remain legal.
- **§ Codebase Structure** — the example tree's `core/web` + `core/worker`
  becomes `core/api` + `core/frontend`. Under the advance, `web` and `worker`
  are process types of one codebase, so a tree showing them as sibling *core
  services* would contradict § Contracts three sections below inside the same
  file. `api` + `frontend` is a genuinely-separate-codebases pair — different
  language, different bounded context — and lines up with the § Contracts
  rewrite. The ripple is followed everywhere in the file that names `worker` or
  `web` as a folder.
- **§ Core Service Containers** — a process type's `command` is required, so the
  Dockerfile `CMD` is irrelevant for core services.
- **§ Contracts** — provider/consumer inference moves from `depends_on` to
  `consumes`, and the worked example is re-cast in process-type terms
  (`frontend.web` consumer-only, `api.web` both, `api.worker` provider-only)
  with contracts `api.web.openapi.yml` / `api.worker.asyncapi.yml`.

### `doctrine/practices/logging.md` (resident)

The dev telemetry-watching command becomes
`docker compose logs -f <svc>-<proc>-otelcol`.

### `doctrine/infrastructure/cicl.md` (conditional) — the big one

Structural additions, all as `###` children of `## The CICL Format` so existing
anchors are untouched:

| New section | Carries |
| ----------- | ------- |
| `### Process Types` | the mandatory non-empty `processes:` block; the worked example; the field-scoping principle and table; the service level accepting only `{processes, secrets, config, env}`; `command` required everywhere; the naming convention; `env:` merging process-over-service |
| `### Magic Refs` | four-segment core refs vs. three-segment backing refs, the asymmetry justification, self-refs rejected |
| `### Consumes Relationships` | the interface relation, dotted fully-qualified targets, the legal cyclic digraph, one-directional rule 7, same-codebase not exempt, service-level `env:` obliging every process type |
| `### CICL Version` | `cicl_version: "2"`; `"1"` is rejected, not shimmed |

Edits to existing sections:

- **The worked `infra.yml` example** — `cicl_version: "2"`,
  `domain_default_process: api.web`, and `api` restructured into `web` /
  `worker` / `nightly_cleanup` process types with `secrets:` hoisted to the
  service level.
- **§ Service Fields** — the "Core or Backing Service" column's values become
  `core (service)` / `core (process type)` / `backing`, so the table itself
  carries the scoping. `processes` and `consumes` rows added; `command` becomes
  required; `replicas`, `role`, `networks`, `resources`, `port`, `depends_on`,
  `env` re-scoped.
- **§ Environmental Variables** — `env:` is the one field valid at both levels
  and merges process-over-service; `secrets:` and `config:` are service-level
  only.
- **§ Domain** — the form becomes
  `<service>-<process>.<env>.<project_name>.<apex_domain>`, with the three
  independent reasons the label must be *single and hyphen-joined* (TLS
  wildcards cover exactly one label; the parse is positional; the bare routes
  are defined relative to a four-part form), the dots-for-reference /
  hyphens-for-emission rule, and — load-bearing, because it dissolves the
  apparent ambiguity of `api-web` — **nothing ever reverse-parses the label back
  into `(service, process)`**. The Bare Env row takes
  `domain_default_process`.
- **§ Container Registry and Service Images** — one image per *codebase*, shared
  by all its process types. The image ref is not process-qualified.
- **§ Networks** — `worker` and `scheduler` process types may not declare `web`;
  a process type wanting public ingress *is* `role: web`. Network attachment is
  per process type.
- **§ Resources** — required on every **process type**; error paths read
  `core_services.<svc>.processes.<proc>.resources`.
- **§ Naming and Tagging** — the fixed container form becomes
  `${project}-${env}-${service}-${process}`; envinfra tags gain `process` and
  the `Name` tag is process-qualified.
- **§ Depends-On Relationships** — heading **kept** (see
  [Link discipline](#link-discipline)); rewritten to backing services only, a
  fixed-only readiness convenience and never a correctness guarantee. Roles 2
  (provider/consumer) and 3 (downstream chain) move to § Consumes Relationships.
  The corollary is written in explicitly: **startup ordering is not a substitute
  for connection resilience.** A `depends_on`-vs-`consumes` comparison table
  sits at the seam.
- **§ Validation Rules** — 5, 7, 10, 12, 14, 15, 16 restated per the design
  record's table; new rules **appended as 21-27**, not interleaved, so no
  existing rule number moves under the `docex` code and tests that cite them:

  | # | Rule |
  | - | ---- |
  | 21 | `cicl_version` is `"2"` |
  | 22 | every core service declares a non-empty `processes:`, and the service level declares nothing outside `{processes, secrets, config, env}` |
  | 23 | every process type declares a `command` |
  | 24 | `depends_on` names only backing services |
  | 25 | `consumes` names only core process types, fully qualified as `<service>.<process>` |
  | 26 | `replicas` is not declared on a `scheduler` process type |
  | 27 | `worker` and `scheduler` process types do not declare `web` in `networks` |

### `doctrine/infrastructure/contracts.md` (conditional)

- Path gains the process dimension unconditionally:
  `$pr/infra/contracts/${service}.${process}.${format}.yml`. Format alone cannot
  disambiguate — one codebase may run two HTTP process types that are both
  genuine boundaries.
- Provider set = (`consumes` targets) ∪ (web-network process types). Both arms
  are needed; driving the set purely off `consumes:` would silently switch off
  the health-endpoint gate.
- Format derives from the **provider's** `role` (`web` → openapi, `worker` →
  asyncapi), not from graph shape. This confirms the direction the file already
  asserts ("an asyncapi.yml contract describes `worker`").
- § Health Checks rewritten to the in-process-tick model: every long-running
  process type serves
  `GET /health` on its declared port; liveness is loop-sourced and intra-process
  via a monotonic tick; doctrine-fixed thresholds of a 10 s tick and a 30 s
  staleness threshold; fan-out over the **union** of `consumes` and
  `depends_on`; `/health/<svc>/<proc>`; **one hop only**, which is what keeps the
  legal `web ↔ worker` cycle from recursing; a `consumes` target must declare
  `port` and `health_check_path`; `scheduler` process types exempt. Plus the
  **health-declared-by-fields** rule and why: AsyncAPI has no natural place for
  an HTTP path, so the fields *are* the declaration and the `check` gate asserts
  them.

**Why 10 s / 30 s are doctrine-fixed rather than per-project knobs.** The pair
is one decision, not two: 30 s is 3× the 10 s tick, so a healthy loop misses two
consecutive ticks before the handler calls it stale. That slack absorbs ordinary
scheduling jitter and one slow iteration without flapping, while still failing a
genuinely wedged loop inside the window an ECS container healthcheck or a
compose `healthcheck` will act on. Making it tunable would buy nothing a project
actually needs — a loop that cannot tick every 10 s even when idle has an
unbounded receive, which is the bug the rule exists to surface — and would cost
a per-project value that must then be reasoned about at every read site, in a
doctrine whose whole premise is one canonical answer for deterministic choices.
A project with a genuinely long unit of work still ticks on schedule; the tick
belongs to the receive loop, not to the work.

## Link discipline

Renaming or removing a heading strands cross-references, which
[`doctrine.md` § Skills](../../../../doctrine/doctrine.md#skills) names as the one
ongoing cost of this structure. Two anchors are load-bearing across mod
boundaries:

- **`cicl.md#depends-on-relationships`** is linked from `cicd.md:58`,
  `contracts.md:9`, `contracts.md:34`, and `infrastructure.md:254`. The heading
  is therefore **kept**; only its body changes. `contracts.md` and
  `infrastructure.md` are mine and get repointed to
  `#consumes-relationships`; `cicd.md` is Mod 106's and its link keeps
  resolving in the meantime.
- **`contracts.md#health-checks`** is linked from `cicd.md` and `tests.md`
  (both Mod 106's). The heading is kept.

Every other inbound anchor into `cicl.md` (`#validation-rules`,
`#provided-fields`, `#service-fields`, `#cicl-transfer-tables`,
`#compiler-output`, `#naming-and-tagging`, `#simplifications`, `#domain`,
`#elastic-tls`, `#fixed-tls`, `#container-registry-and-service-images`,
`#resources`, `#the-cicl-format`, `#tls-implications`) is preserved; all new
sections are additions. `hex_overview.md#tests` and
`infrastructure.md#contracts` likewise survive.

## Decisions taken inside scope

Recorded rather than raised, because the design record settles the principle and
only the local rendering was open.

1. **The worked example's worker depends on `cache`, not `taskqueue`.** The
   design record's snippet uses `depends_on: [taskqueue]`, but no queue role
   ships in `tables/roles/` (only `cache`, `object_store`, `relational_db`,
   `scheduler`, `web`). The doctrine's example must name a role that exists, so
   redis-as-broker via the existing `cache` backing service stands in, with an
   explicit sentence in the example saying so — otherwise a reader infers a
   `queue` role exists. The shape of the example is unchanged. **The absent
   `queue` role is a real doctrine gap** (the advance's own motivating
   capability can only be expressed through the `cache` role) and has been
   carried to the operator; it is not this mod's to solve.
2. **New validation rules are appended, not interleaved.** See question 5.
3. **`cicl.md § Naming and Tagging` is updated here** even though the design
   record files the envinfra tag block under `specifics/transfer_tables.md`
   (Mod 106). The same statement lives in both files and `cicl.md` is this mod's;
   leaving `${project}-${env}-${service}` in place would be a known-false
   sentence for twelve mods.

## Out of scope

`doctrine/infrastructure/{cicd,docex,shape,tests,telemetry}.md`,
`doctrine/infrastructure/specifics/*`, and
`doctrine/infrastructure/preinfra/*` are **Mod 106's**, deliberately written
after the code exists. Their prose will read stale against this mod's output for
the duration of the advance; that is the plan's intent, not drift. No version
artifact is bumped — that is Mod 107.

## Rulings

Five questions were raised at design review. All are settled; no open design
questions remain.

1. **The full health-check model lands in `contracts.md § Health Checks` — this
   mod owns it.** It otherwise reaches no doctrine file: Mod 106's file list
   does not include `contracts.md` and Mod 101 is `check.py` only. The advance
   plan is being amended to record the ownership so Mod 106 does not duplicate
   it and Mod 101 has something to implement against. The resident-stratum
   liveness rule in `internal_dependency_rules.md § Entrypoints` **links** here
   rather than restating.
2. **The "entrypoints are too thin to test" note is included** — one sentence in
   `hex_overview.md § Tests`.
3. **The `infrastructure.md` codebase tree changes** — option (b),
   `core/api` + `core/frontend`. The deciding reason is self-consistency, not
   taste: § Contracts in the same file is being re-cast to `api.web` /
   `api.worker`, so a tree three sections above showing `web` and `worker` as
   sibling core services would make `infrastructure.md` contradict itself.
4. **The `skills/` tree is swept and fixed here.** Findings below; all are plain
   renames.
5. **New validation rules append as 21-27.** Stable numbers beat a tidy list.

### Skills sweep

Grepped the whole `skills/` tree for everything this mod falsifies. Two files,
both plain renames — nothing needing more than that:

- **`skills/browser-investigate/SKILL.md`** (lines 83, 88) —
  `domain_default_service` → `domain_default_process`; the per-service dev URL
  becomes `https://<service>-<process>.dev.<project>.<apex_domain>`; the
  bare-env host answers for the `domain_default_process`.
- **`skills/contracts/SKILL.md`** (lines 10, 16, 20, 21) — the boundary is a
  provider **process type**; the downstream endpoint is `/health/<svc>/<proc>`;
  provider/consumer relationships are declared via `consumes`, not
  `depends_on`, and the check step enforces contract-to-`consumes` alignment.

Deliberately **not** touched:

- `skills/infra-compile/SKILL.md:16` — its router line ("services, fields, magic
  refs, networks, domains, and validation rules") is incomplete after this mod
  but not false. Adding "process types" is a trigger-quality improvement, which
  is Mod 106's "verify the skill pointers" pass, not a factual correction.
- `skills/testing/SKILL.md` — the design record already assigns it a possible
  line on where entrypoints sit, to Mod 106.
- `skills/skill-iteration/references/evaluation.md:60` — cites
  `/health/<dependency>` generically while discussing eval methodology, not as a
  doctrine statement. Still reads correctly.
