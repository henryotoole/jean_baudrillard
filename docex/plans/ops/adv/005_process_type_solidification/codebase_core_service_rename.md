# Rename: a codebase is a `codebase`, a process type is a `core service`

A design record for swapping the two central nouns of the doctrine's service
vocabulary. What is today called a **core service** becomes a **codebase**; what
is today called a **process type** becomes a **core service**.

> **Status.** **Design settled; no open questions** — decisions locked (see
> [Decisions](#decisions)), open items resolved (see
> [Resolved items](#resolved-items)).
> Breaking — every `infra.yml` must be rewritten, so this is a `cicl_version`
> **2 → 3** cut and must ride with [`uses_relation_merge.md`](./uses_relation_merge.md)
> rather than force a second rewrite of the same files. Lands as doctrine
> **1.7.0**. Touches resident doctrine, CICL, contracts, migrations, transfer
> tables, `docex` source and tests, both test projects, six skills, the eval
> fixtures, and the upgrade guides.

## The change

Two nouns trade places:

| Today | Becomes | Is |
| ----- | ------- | -- |
| core service | **codebase** | one source tree, one build artifact, one image |
| process type | **core service** | one named, independently-scaled deployment of that artifact |

Nothing about the *structure* changes. There is still one image per codebase,
still N invocations of it, still a role/command/resources/networks/port on each.
Only the names move.

```yml
# BEFORE (cicl_version 2)
core_services:
  api:
    env: { ... }                 # "codebase-scoped"
    processes:
      web:
        role: web
        env:
          WORKER_HOST: ${core_services.api.worker.host}
domain_default_process: api.web

# AFTER (cicl_version 3)
codebases:
  api:
    env: { ... }                 # codebase-scoped
    core_services:
      web:
        role: web
        env:
          WORKER_HOST: ${codebases.api.core_services.worker.host}
domain_default_service: api.web
```

## Motivation

1.6.0 introduced process types because `web` and `worker` needed to share a
build artifact. That was the right structural move, but it left the vocabulary
one notch out of alignment with reality, and the misalignment is load-bearing in
three places:

**The word "service" stopped meaning a service.** Everywhere else in the
doctrine — and everywhere in the industry — a service is a thing that is
deployed, scaled, routed to, and health-checked. After 1.6.0 the doctrine's
"core service" is none of those: it has no port, no command, no replica count,
and nothing ever routes to it. The things that *are* deployed are the process
types. A reader who knows what a service is has to unlearn it to read
`infra.yml`.

**A bare core service name has no answer.** The clearest symptom is already
written down in [`cicl.md § Magic Refs`](../../../../doctrine/infrastructure/cicl.md#magic-refs):

> A **bare** core service name is illegal rather than shorthand — a codebase has
> no single boundary, so `${core_services.api.host}` has no answer.

That sentence is the doctrine noticing that its own noun is wrong. A service you
cannot address is not a service. The same apology recurs in
`domain_default_process`'s comment in both test projects ("a bare core service
name has no answer, because a codebase has no single boundary").

**The doctrine already reaches for "codebase" when it needs to be precise.**
[`cicl.md § Process Types`](../../../../doctrine/infrastructure/cicl.md#core-services)
opens with "A core service is a *codebase* and the single *build artifact*
compiled from it" and then uses "codebase" — not "core service" — for the rest of
the section: "one codebase, one image, N process types", "codebase-scoped",
"a codebase declares two process types on the same role". The `secrets:` and
`config:` fields are documented as "codebase-scoped". `schema_owned_by` is
documented as naming "a **core service** (a codebase)" — a gloss that exists only
because the primary noun fails. The replacement term is already in use; this
change just makes it the name.

### What the swap preserves

The rename is deliberately conservative. It keeps every distinction the current
vocabulary earns:

- **Core vs. backing stays exactly as it is.** "Core" continues to mean *we
  maintain the code*, "backing" *someone else does*. The dichotomy is untouched;
  it just now sits between two things that are both genuinely services.
- **"Codebase" keeps its existing meaning.** The [lexicon](../../../../doctrine/lexicon.md)
  already defines a codebase as "the bundle of source code that makes up a core
  service. One codebase never imports code from another." That definition
  survives nearly verbatim — it only stops being subordinate to "core service"
  and starts being the primary noun.
- **"Service" recovers its plain meaning** — a deployable, addressable,
  scalable piece of infrastructure — which restores the ordinary reading of
  every sentence in the doctrine that uses the bare word.

## Decisions

Settled with the operator before drafting; recorded here because several are not
recoverable from the diff.

| # | Question | Decision |
| - | -------- | -------- |
| 1 | Does the rename reach the authored CICL surface, or stop at prose? | **Full, in one mod.** Prose *and* authored surface, together. |
| 2 | How is a codebase's set of core services spelled? | Nested key **`core_services:`** under `codebases:` — fully qualified, so the core/backing dichotomy is explicit at the point of declaration. |
| 3 | How do core magic refs spell their namespace? | **Full literal path**: `${codebases.<cb>.core_services.<svc>.<part>}`. The ref mirrors the document exactly. |
| 4 | Do the emitted elastic tag keys change? | **Yes.** `service`→`codebase`, `process`→`service`. |
| 5 | Do `$pr/core/` and the in-container `/service` root change? | **Neither.** Both stay. |
| 6 | Version? | **1.7.0**, `cicl_version` 2 → 3, `upgrades/upgrade_2.0.0.md`. |

### On decision 3 — why the long form

Two shorter forms were considered and rejected:

- **Keep `${core_services.api.worker.host}` unchanged.** Tempting, because the
  string survives the rename *and becomes more correct* — after the swap its
  first segment genuinely does name a core service. Zero upgrade cost for refs.
  Rejected because the ref would no longer be a path: its first segment would
  name the nested key while its second segment indexed the *top-level* one, so
  the reader cannot derive the ref from the document or the document from the
  ref.
- **`${codebases.api.worker.host}`.** A path walk with the nested key elided.
  Rejected as the worst of both: it costs the same rewrite as the long form
  while silently skipping a level, and it never says the word "service" despite
  naming one.

The long form costs one mechanical rewrite in each project and buys an exact
correspondence between ref and document. Backing refs keep their three-segment
form (`${backing_services.appdb.host}`); the asymmetry remains honest, because a
backing service has no service dimension to qualify.

### On decision 4 — why the tag churn is cheap

Tag **values** do not change, and neither does any emitted **string**. Today's
templates already interpolate the two names in the same order the new names
appear in:

| Emitted thing | Template today | Template after | Renders |
| ------------- | -------------- | -------------- | ------- |
| Docker container | `${project}-${env}-${service}-${process}` | `${project}-${env}-${codebase}-${service}` | **identical** |
| Elastic `Name` tag | `${project}_${env}_${service}_${process}` | `${project}_${env}_${codebase}_${service}` | **identical** |
| Domain label | `<service>-<process>.<env>.<project>.<apex>` | `<codebase>-<service>.<env>.<project>.<apex>` | **identical** |
| Image ref | `${project}/${service_name}:${version}` | `${project}/${codebase_name}:${version}` | **identical** |
| Contract path | `${service_name}.${process_name}.${fmt}.yml` | `${codebase_name}.${service_name}.${fmt}.yml` | **identical** |

So the only wire-visible change is the two elastic env-tier tag **keys**. Since
values are unchanged, OpenTofu updates tags in place rather than recreating
resources. The one hard requirement: every `docex` tag filter and lookup must
move in the same commit as the emitter, or teardown and reconcile will silently
match nothing. See [Verify first](#verify-first).

## Vocabulary map

The authoritative old→new table. Anything not listed here does not change.

### Prose

| Old | New |
| --- | --- |
| core service *(= codebase + artifact)* | codebase |
| core service root | codebase root |
| core service name | codebase name |
| process type | core service |
| process types | core services |
| process name | core service name |
| process-scoped | service-scoped |
| process-level | service-level |
| process dimension | service dimension |
| provider process type | provider core service |
| codebase-scoped | *(unchanged — now literally true)* |
| backing service | *(unchanged)* |
| core service container | *(unchanged spelling — now correctly names the deployed unit)* |

### Lexicon

| Entry | Action |
| ----- | ------ |
| **Codebase** | Promote to primary noun: the source of a core-service family and the single build artifact compiled from it. One codebase never imports code from another. Declares one or more core services. |
| **Core Service** | Redefine: a named, independently-scaled deployment of a codebase's build artifact — its own role, command, resources, networks, and port. |
| **Process Type** | **Delete the row.** The mapping is preserved in `upgrade_2.0.0.md`; the doctrine holds one canonical name per concept. |
| **Entrypoint** | Reword: the code module a **core service's** `command` invokes. One entrypoint per core service. |
| **Service** | Unchanged — still "both core services and backing services", still true. |
| **Application Service** | **Unchanged this mod.** It collides with the hexagonal meaning (an alogic class implementing a driving port), but resolving that is a second vocabulary change and is deliberately out of scope. See [Resolved items](#resolved-items) #1. |

### Authored CICL surface

| Old | New |
| --- | --- |
| top-level `core_services:` | `codebases:` |
| nested `processes:` | `core_services:` |
| `domain_default_process` | `domain_default_service` |
| `${core_services.<svc>.<proc>.<part>}` | `${codebases.<cb>.core_services.<svc>.<part>}` |
| `${backing_services.<svc>.<part>}` | *(unchanged)* |
| `consumes: [api.worker]` | *(unchanged — dotted `codebase.service` still)* |
| `schema_owned_by` | *(unchanged key; doc becomes "names a codebase", gloss dropped)* |
| `cicl_version: "2"` | `cicl_version: "3"` |

### Emitted surface

| Old | New |
| --- | --- |
| elastic env tag key `service` *(carried codebase name)* | `codebase` |
| elastic env tag key `process` *(carried process-type name)* | `service` |
| `shape_name` values `core_service` / `backing_service` | *(unchanged — they name a deployed resource, so `core_service` is already correct)* |
| OTel resource attr `docex.core_service` | `docex.codebase` — clean cut, no dual-write ([E1](./codebase_core_service_rename_adjudication.md#e1--docexcore_service--docexprocess_type-are-otel-resource-attributes)) |
| OTel resource attr `docex.process_type` | `docex.service` — **splits existing telemetry time series**; `upgrade_2.0.0.md` must require dashboard/alert updates |
| `docex describe --format llm` JSON key `core_service` | `codebase` — see [E2](./codebase_core_service_rename_adjudication.md#e2--docex-describe---format-llm-emits-a-core_service-json-key) |
| every emitted name, label, and path | *(byte-identical — see [decision 4](#on-decision-4--why-the-tag-churn-is-cheap))* |

### `docex` identifiers

| Old | New |
| --- | --- |
| `CoreService` *(model)* | `Codebase` |
| `ProcessType` *(model)* | `CoreService` |
| `ProcessRef` | `ServiceRef` |
| `ProcessRef.service` / `.process` | `.codebase` / `.service` |
| `CICLDocument.core_services` | `.codebases` |
| `CoreService.processes` | `Codebase.core_services` |
| `domain_default_process` *(field)* | `domain_default_service` |
| `proc_name`, `process_name` | `service_name` |
| `primary_process` | `primary_service` |
| `all_processes` | `all_services` |
| `target_process` | `target_service` |
| `_resolve_process` | `_resolve_service` |
| `_standard_process_fields` | `_standard_service_fields` |
| local `service` / `svc` naming a codebase | `codebase` / `cb` |

## Protected tokens

A naive `s/process/service/` would corrupt ~700 unrelated occurrences. These
contain the substring and **must not be touched**:

- `subprocess`, `subprocess_client`, `subprocess_runner`, `subprocess_docker_client`,
  `SubprocessGitClient`, `SubprocessSshClient`, `subprocesses` — ~270 hits
- `processor`, `processors`, `processor_service`, `processor_cli`,
  `processor_smoke`, `processor.md` — ~170 hits (the test projects' `processor`
  hex module and its `reaper` sibling)
- `processed`, `processed_at`, `processed_before`, `processed_idx`, `processing` — ~275 hits
- `docex_process`, `docex_process.md` — ~99 hits; "process" here is the docex
  *workflow*, unrelated to process types
- 12-factor "**processes**" in the OS sense — e.g. infrastructure.md's "core
  services execute as stateless processes". These stay "processes"; only the
  *type* sense renames.

The `core_service` direction has one protected token of its own:
`docex/doctrine_excerpts/core_service.md` — its filename is referenced by
`doctrine_excerpts/index.yml`, so file and index move together or neither does.

## Blast radius

310 files carry an affected term. 103 are historical records and are **frozen**;
207 are working files that change.

| Area | Files | Notes |
| ---- | ----: | ----- |
| `docex/test_projects` (fixed + elastic) | 56 | Both projects' `infra.yml`, contracts, plans, sources, checked-in compiled output |
| `docex/tests/unit` | 38 | Two files are also renamed: `test_process_nesting.py`, `test_process_expansion_emit.py` |
| `doctrine/infrastructure/specifics` | 14 | |
| `doctrine/infrastructure` | 10 | Includes `cicl.md`, the densest single file |
| `docex/tests/fixtures` | 8 | Four fixture `infra.yml`s |
| `docex/src/docex/{emit,cicl}` | 14 | `cicl/` is the model + compiler; `emit/` includes the two `.tf.j2` templates |
| `docex/doctrine_excerpts` | 7 | Includes `core_service.md` + `index.yml` |
| `doctrine/practices` | 6 | |
| `docex/src/docex/{pipeline,orchestrate,describe,aws}` + `__main__.py`, `errors.py` | 14 | |
| `docex/tables` | 4 | `roles/{web,worker,scheduler}.yml` + README |
| `docex/plans/core` | 4 | docex's own core docs — `compiler.md`, `masterplan.md`, `release_flow.md`, `test_projects.md` |
| `doctrine/infrastructure/reasoning` | 3 | |
| `doctrine/hexagonal_architecture` | 2 | `hex_overview.md` (entrypoints, structure table), `internal_dependency_rules.md` (§ Entrypoints) |
| `docex/tests/integration` | 2 | |
| `skills/` | 6 | `infra-compile`, `contracts`, `testing`, `project-cohere` (+ its `chunk_map.py`), `browser-investigate` |
| `skill_iter/eval` | 10 | 8 live `evals.json` + `queries.json` must be reworded or the outcome evals break; 1 recorded run is frozen |
| `doctrine/lexicon.md` | 1 | Highest-leverage single file |
| root | 2 | `CHANGELOG.md`, `engineer/post_op_doctrine_checklist.md` |

### Frozen — historical records

- `docex/plans/modifications/**` (97 files). Per
  [`practices/modifications.md`](../../../../doctrine/practices/modifications.md),
  mod docs are a record of a change as it was designed at the time. Rewriting
  them would falsify history and they are never loaded into context anyway.
  Notably includes `094_doctrine_process_types`, `096_process_nesting`,
  `103_scheduler_process_type` — whose *titles* record the old vocabulary
  correctly.
- `docex/plans/advances/{003,004}/**` (6 files) — same reasoning.
- `upgrades/upgrade_{1.2.0,1.5.0,1.6.0,1.6.1}.md` — each describes an upgrade
  *to a version that used the old vocabulary*. Rewriting them would make their
  instructions wrong. `upgrade_2.0.0.md` is the one that explains the rename.
- `skill_iter/eval/outcome/project-cohere/full.run.2x.sonnet-sub.json` — a
  recorded run result.

Sibling docs *within this advance* (`uses_relation_merge.md`,
`service_connect_reconcile_trigger.md`) are live design input, not history, and
are reworded.

## Interaction with the rest of the advance

[`uses_relation_merge.md`](./uses_relation_merge.md) is also a `cicl_version`
2 → 3 change requiring every `infra.yml` to be rewritten. **These must ship in
the same cut.** Two independent 2→3 bumps would mean two rewrites of the same
files and two upgrade guides for one release.

Sequencing recommendation: **land the rename first**, then `uses`. The rename is
mechanical and touches everything shallowly; `uses` is structural and touches
`infra.yml` deeply. Doing `uses` second means it is authored directly in the new
vocabulary and never has to be translated. Doing it first would mean writing
`uses` prose about "process types" and immediately rewriting it.

## Verify first

The rename is broad enough that a green test suite is *not* sufficient evidence —
the suite would stay green if the emitter and the tag filters moved together but
both moved wrongly. Three checks that a passing suite would not catch:

1. **Compiled output is byte-identical except for tag keys.** Compile both test
   projects before and after; diff. Every difference must be one of the two tag
   keys. Any change to a container name, domain label, image ref, or contract
   path is a defect.
2. **Tag filters match the emitter.** `docex` reads env-tier tags for teardown
   and Service-Connect reconcile. Grep for the literal strings `"service"` and
   `"process"` used as tag keys and confirm each moved. A filter left on the old
   key matches zero resources and fails silently rather than loudly.
3. **No protected token was collateral damage.** Re-run the counts in
   [Protected tokens](#protected-tokens) and confirm each is unchanged.

## Resolved items

All three settled with the operator; no open questions remain.

1. **"Application service" as a Core Service synonym — leave alone.** The
   collision with the hexagonal meaning is real but out of scope here. The
   lexicon row stands as written. Revisit separately if it ever bites.
2. **`scheduler` — reword only; do not restructure.** The `role`-vs-name
   sentence gets translated into the new vocabulary, and `role: scheduler`
   **stays exactly as it is**. A future mod refactors the scheduler to sit
   correctly in this model; that work does not fit here. This mod must therefore
   resist the temptation to "fix" the scheduler's shape while renaming around it
   — a scheduler core service is still named after its job rather than its role,
   and that stays true until the later mod changes it.
3. **`domain_default_service` — keep the short form.** Chosen for ergonomics.
   The asymmetry with decision 2's fully-qualified nested key is accepted: only
   core services are ever routed to, so there is nothing for the longer form to
   disambiguate.
