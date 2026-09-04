# Intro and Goals

`docex_smoke_fixed` is one of two **doctrine smoke-test projects** that ship
inside the `docex/` tree. It is *not* a real product. It exists so that, before
cutting a minor or major `docex` version, the operator can drive a real
`fixed`-foundation project end-to-end through
`projinfra → envinfra → check → merge → containerize → release stage → stagetest → release prod → teardown`
and surface the bugs that only appear against real infrastructure. The companion
project at `docex/test_projects/elastic/` exercises the `elastic`-foundation
path; together they cover the two foundations the doctrine commits to.

The system-context picture is [`project_diagram.mmd`](./project_diagram.mmd).

## Requirements

1. **Exercise the fixed-foundation release path end-to-end** — the surface that
   unit tests structurally cannot reach.
2. **Stay doctrine-faithful.** Every artifact is what current doctrine
   prescribes a fixed-foundation project to look like. When walking the inception
   flow surfaces an ambiguity, the fix lands in the doctrine, not in a workaround
   here.
3. **Exercise the project-local transfer-table feature.**
   `infra/transfer_tables/{sidecar,clickhouse}.yml` declare two project-local
   engines — a stateless nginx sidecar and a stateful ClickHouse `analytics_db` —
   so each cut exercises the deep-merge path, container-backings on the dispatch
   surface, and (on the elastic counterpart) the EFS persistent-storage
   machinery.

# Constraints

- **Hexagonally-architectured Python.** The one codebase, `api`, is built per
  `doctrine/hexagonal_architecture/` and written in Python.
- **Single host per environment.** On `fixed`, all four environments (`dev`,
  `test`, `stage`, `prod`) run as docker containers side-by-side on one host —
  for this test project, the operator's dev machine.
- **One codebase.** The project is deliberately a single codebase exposing three
  core services, not several codebases — see
  [ADR 0001](./adrs/0001_one_codebase_three_core_services.md).

# Context and Scope

The project is a black box against the operator and the external systems a fixed
walk touches (registry, Route53, preinfra); the picture is
[`project_diagram.mmd`](./project_diagram.mmd) and the interior is
[`service_diagram.mmd`](./service_diagram.mmd). What this project deliberately
does **not** do bounds its scope:

- It does **not** solve a real problem. The flows are minimal by design.
- It does **not** carry custom transfer tables beyond `sidecar.yml` and
  `clickhouse.yml`. Those two exist specifically to keep the project-local
  transfer-table surface exercised every cut; an ambiguity a walk surfaces in the
  doctrine's project-local mechanism is fixed in doctrine, not in additional
  tables here.
- It does **not** ship custom observability, alerting, or anything in the
  Deferred section of `doctrine/infrastructure/infrastructure.md`. A surfaced
  need for one of those is a Deferred item being un-deferred, not a change here.

# Quality Requirements

The project's one quality bar is **doctrine fidelity**: every artifact should be
exactly what current doctrine prescribes, so that a discrepancy the walk finds is
a doctrine bug rather than a project bug. When the walk surfaces an ambiguity, the
fix lands in the doctrine, never in a workaround inside this project. There are no
discrete quality scenarios, so no `quality_scenarios.md` is kept.
