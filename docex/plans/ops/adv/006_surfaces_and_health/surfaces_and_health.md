# Surfaces replace role-derived contracts; health leaves HTTP

A design record for two coupled changes: replacing role-derived contract-format
selection with an explicitly declared `surfaces:` block, and removing HTTP as the
doctrine's mandated health-check substrate — which deletes the fan-out.

> **Status.** **Design settled; all open questions resolved** (see
> [Resolved decisions](#resolved-decisions)). Breaking on both halves — every `infra.yml`
> gains a `surfaces:` block, every contract file is renamed, every non-`web` core
> service drops its HTTP server, and every project's staging tests lose their
> liveness assertions. Touches CICL, contracts, tests, resident lexicon, `docex`,
> and both `test_projects`. Closes
> [`006_small_edges/doctrine_tweaks.md § 1`](../006_small_edges/doctrine_tweaks.md)
> and subsumes `006_small_edges/mcp_control_surface.md`.

## Why one advance and not two

The surfaces change cannot close on its own. Once a core service may declare more
than one surface, "which surface carries `GET /health`" has no good answer while
health is contract-visible — and every answer available is a contortion
(designate a primary, require it in all, require it in any). Removing health from
the contract for non-`web` services dissolves the question rather than answering
it. Shipping the halves separately means shipping a known knot.

---

## Part I — Surfaces

### The change

1. **A core service declares `surfaces:`** — a map of named boundaries. Each
   surface compiles to exactly one contract file.

   ```yml
   codebases:
     api:
       core_services:
         web:
           role: web
           surfaces:
             rest:
               api_styles: [rest, stream, webhook]   # → one OpenAPI contract
         mcp:
           role: web
           surfaces:
             mcp:
               api_styles: [rpc]                     # → one AsyncAPI contract
   ```

2. **`api_styles` determines the contract format**, replacing
   `_CONTRACT_FORMAT_BY_ROLE`. The canonical styles and their formats:

   | `api_style` | Format | Covers |
   | --- | --- | --- |
   | `rest` | `openapi` | resource-oriented HTTP |
   | `stream` | `openapi` | SSE, JSON Lines, `application/json-seq` (OpenAPI 3.2 `itemSchema`) |
   | `webhook` | `openapi` | provider-initiated callbacks (OpenAPI 3.1 top-level `webhooks`) |
   | `rpc` | `asyncapi` | JSON-RPC, MCP, request/reply (AsyncAPI 3.0 `reply`) |
   | `events` | `asyncapi` | queue / broker / pub-sub |
   | `socket` | `asyncapi` | WebSocket, bidirectional |
   | `graphql` | `graphql` | GraphQL SDL |
   | `grpc` | `proto` | gRPC / protobuf IDL |

3. **A surface's styles must resolve to one format**, or compile fails. The rule
   is *derived*, never tabulated: `len({format(s) for s in api_styles}) == 1`.
   `[rest, stream, webhook]` passes; `[rest, rpc]` fails with "split these into
   two surfaces." This mirrors `cicl.md` rule 5's keyed-on-collision reasoning and
   cannot drift from the style table above.

4. **Contract path gains the surface segment:**
   `$pr/infra/contracts/${codebase}.${service}.${surface}.${format}.${ext}`
   → `api.web.rest.openapi.yml`, `api.mcp.mcp.asyncapi.yml`. The extension is a
   property of the format (`openapi`/`asyncapi` → `yml`, `graphql` → `graphql`,
   `proto` → `proto`), which is what lets the non-YAML formats land in the same
   template. `check.py:153` currently accepts `.yml` **and** `.yaml`; the table
   in `contracts.md` fixes one extension per format, so the parser narrows.
   `_SERVICE_NAME_RE` must extend to surface names so the right-anchored
   four-segment parse stays unambiguous.

5. **Surfaces define the provider set.** The two-armed
   `(core-service uses targets) ∪ (web-network core services)` union is deleted.
   A core service is a provider iff it declares `surfaces:`. A `uses` edge
   targeting a core service that declares none is a **compile error**, not a
   silently-missing contract.

6. **Surface naming follows the core-service convention.** A surface is named
   after its primary `api_style` unless a core service declares two on the same
   style — mirroring `cicl.md`'s "a core service is generally named after its
   role, unless a codebase declares two on the same role."

### Motivation

Format was keyed on `role`, which is a proxy for *transport*, not for interaction
style. The error was "HTTP means REST." MCP is the case that exposed it: HTTP
transport, RPC style, `role: web` — two of three point at AsyncAPI, and the
doctrine keyed on the one that doesn't.

`role` also cannot express a service with two boundaries at all, and `check.py`'s
`_FALLBACK_CONTRACT_FORMAT = "openapi"` means any unrecognized role silently
receives the wrong format rather than an error.

### When to split instead

`surfaces:` is for one process exposing more than one describable boundary — not
for smuggling in deployment differences. The test is mechanical:

> Two boundaries belong to one core service iff every core-service-distinguishing
> field — `role`, `command`, `resources`, `networks`, `port`, `replicas` — would
> take the same value for both. If any would differ, they are two core services.

MCP-plus-REST typically **fails** this on `resources` and `command`: a session
holder sizes on concurrent sessions and needs long drain windows; a REST edge
sizes on request rate and drains in seconds. Under this doctrine a second core
service is cheap — one image, one composition root, one thin entrypoint — so
**splitting is the default and bundling is what requires justification.**

---

## Part II — Health

### The change

7. **The probe becomes command-form.** Both orchestrators natively accept a
   command (`compose healthcheck:`, ECS container `healthCheck`); only the ALB
   target group wants HTTP, and it only ever probes `web` services. The doctrine
   picked the non-universal form and wrapped it in the universal one
   (`curl -f localhost:$PORT/health`). Invert that.

8. **`health.sh` becomes the fourth codebase shim**, alongside `build.sh` /
   `test.sh` / `migrate.sh` (the project-level `stage_test.sh` makes five in
   all). Contract is the exit code — the pattern `databases.md` already
   articulates as "fix the interface, not the tool." Unlike the other four it is
   invoked **per core service**, as `./health.sh <service>`: a web edge and a
   worker of one codebase have genuinely different probes, and argv is cheaper
   than four shims. The compiler emits the argv, so the script never guesses
   which core service it is running in.

9. **Loop liveness moves to a tick file.** A loop-owning process touches a known
   path each iteration; `health.sh` stats its mtime. The existing 10s/30s
   thresholds and the "monotonic tick" wording survive verbatim — only the
   observation point moves, from an HTTP handler to a `stat`.

10. **`GET /health` survives only for `web`-network core services**, because a
    load balancer genuinely probes it there. It stops being the universal
    mechanism and becomes one role's requirement. A `web` service's `health.sh`
    may well curl its own route — but that is now the project's choice inside the
    shim, not infrastructure the doctrine mandates.

11. **Liveness and version come from the orchestrator.** `docker inspect`'s
    `Health.Status` + image ref on fixed; `describe_tasks`' `healthStatus` +
    task-definition revision on elastic. This is *more* truthful than the current
    path: version comes from the deployed task definition rather than from a
    self-report that a stale container will happily falsify.

    **Version is reported from three places, and they are not interchangeable.**
    The probe's *exit code* carries liveness and nothing else — a command probe's
    stdout is captured by Docker (`.State.Health.Log[].Output`) but **not** by
    ECS, which surfaces only `healthStatus`, so probe output can never be the
    cross-foundation version channel. `docex` reads version from the orchestrator.
    A `web` service's `GET /health` keeps returning `{version: "x.x.x"}` for the
    project's own stage smoke tests to assert against the injected
    `PROJECT_VERSION`. When the orchestrator and a self-report disagree, the
    orchestrator wins.

12. **The fan-out is deleted.** `/health/<codebase>/<service>`, the one-hop
    recursion rule, and the contract gate that enforces the paths all go.

13. **Staging tests narrow to what requires being outside** — TLS, DNS,
    reverse-proxy routing, and critical-path smoke tests through the real edge.
    `stagetest.py` keeps its dev-machine, host-network, public-URL shape and
    gains a foundation-aware liveness pre-step that reads orchestrator health
    before invoking `stage_test.sh`.

14. **Rule 28 is deleted** (`health_check_path` obliges a `port`), along with
    `health_check_path` itself for non-`web` services and the `curl`-in-image
    gate for them.

### Motivation

Every carve-out below traces to one substitution — HTTP chosen as the universal
health substrate when the command is:

| Carve-out | Where |
| --- | --- |
| Queue workers must run an HTTP server they never otherwise need | [`contracts.md § Self health`](../../../../doctrine/infrastructure/contracts.md#self-health) |
| `health_check_path` obliges a `port` on port-less services | [`cicl.md`](../../../../doctrine/infrastructure/cicl.md#validation-rules) rule 28 |
| `curl` mandated in images that need it for nothing else | `check.py:_gate_healthcheck_tooling`, [`infrastructure.md`](../../../../doctrine/infrastructure/infrastructure.md#codebase-containers) |
| A one-hop rule exists solely to stop fan-out recursing on the legal `web ↔ worker` cycle | [`contracts.md § Fan-out`](../../../../doctrine/infrastructure/contracts.md#fan-out) |
| Service Connect staleness surfaces as a release-blocking health 503 | [`contracts.md:83`](../../../../doctrine/infrastructure/contracts.md#declared-by-fields-not-by-the-contract) |
| The developer must hand-mirror every `uses` edge into a fan-out route, and it rots silently when the graph changes | [`tests.md § Staging Tests`](../../../../doctrine/infrastructure/tests.md#staging-tests) |
| The clock role is exempt from fan-out entirely; its liveness is already proved by container healthcheck alone | [`tests.md § Staging Tests`](../../../../doctrine/infrastructure/tests.md#staging-tests) |

The last row is the tell. The doctrine **already** accepts container-healthcheck-
as-liveness-proof for one role, reached by accident because fan-out structurally
could not cover a consumer-only service. Generalizing that sentence to every
non-`web` core service leaves the fan-out with nothing to do.

The decisive evidence: **`docex` never calls the endpoint it mandates.** Every
`/health` reference in `src/` is a declaration gate (`check.py:499`), an error
string (`magic_refs.py:207`), or a warning about Service Connect
(`release.py:461,479`). The sole runtime consumer is developer-written code in
`infra/stage/tests`.

### What this preserves

The original goal was right: not "every core service has *a* health check" but
"health checks take a fixed form and are evaluated by a fixed mechanism." This
change serves that goal *better*, by moving liveness assertion out of
hand-written project stage tests and into `docex` — a conditional/design concern
becoming an executor one, which is what the three-strata model asks for.

---

## Doctrine file map

**Load-bearing — operator edits (step 3):**

| File | Change |
| --- | --- |
| `lexicon.md` | Add **Surface**. `api_styles` and "probe" take no rows — the lexicon defines concepts, not CICL fields, and both are self-documenting. |
| `infrastructure/contracts.md` | Largest rewrite. § Standards → surfaces + `api_styles` table. § Health Checks → command probe, `web`-only HTTP. Delete § Fan-out and § Declared by fields. |
| `infrastructure/cicl.md` | Add `surfaces:` / `api_styles` to § Service Fields. Delete rule 28. Add: one-format-per-surface, surface-name regex, `uses` target must declare a surface. |
| `infrastructure/tests.md` | § Staging Tests loses the liveness bullet; gains the orchestrator pre-step. § Contract Tests gains surface granularity. |
| `infrastructure/infrastructure.md` | § Contracts (the `frontend`/`api` example), § Codebase Containers (the `curl` mandate). |

**Sweep — my pass (step 4).** Candidates, to be confirmed by search, not assumed:
`specifics/clock.md`, `specifics/exec_service.md`, `specifics/release.md`,
`specifics/transfer_tables.md`, `shape.md`, `docex.md`, `cicd.md`,
`hexagonal_architecture/internal_dependency_rules.md` (entrypoint rule 6 cites
`contracts.md § Health Checks`), and `skills/contracts/`, `skills/testing/`,
`skills/cicd-pipeline/` pointer validity.

## docex impact (input to step 5)

| Area | Change |
| --- | --- |
| `cicl/model.py` | `surfaces` schema; surface-name regex. |
| `cicl/validate.py` | Delete rule 28; add one-format-per-surface, `uses`-target-declares-surface. |
| `pipeline/check.py` | Delete `_contract_format_for_role` + `_FALLBACK_CONTRACT_FORMAT`; `_parse_contract_filename` → four segments; rewrite `_gate_contracts` off surfaces; delete `_gate_health_endpoints`; narrow `_gate_healthcheck_tooling` to `web`. |
| `emit/compose.py` | Healthcheck emission → `health.sh` command. |
| `emit/hcl.py:373` | Container `healthCheck` → command. `:821` target-group HTTP check stays, `web` only. |
| `pipeline/stagetest.py` | Foundation-aware liveness/version pre-step before `stage_test.sh`. |
| `pipeline/release.py:461,479` | Reword Service Connect warnings — the reconcile stays (real `uses` traffic still needs it), but its symptom stops being a health 503. |
| `cicl/magic_refs.py:207` | Error string. |
| `test_projects/{fixed,elastic}` | `infra.yml` surfaces, contract renames, worker HTTP servers removed, `health.sh` added, stage tests trimmed. |
| `doctrine_excerpts/` | The sixth aligned artifact and the only one with no automated consumer — it drifts silently, so it must be swept by hand. |
| `upgrades/upgrade_<next>.md` | New guide; both halves are breaking. |

## Worked example: an MCP core service

MCP is the case that motivated this advance, so the target shape is recorded here
explicitly.

```yml
codebases:
  api:
    core_services:
      web:
        role: web
        networks: [web, internal]
        surfaces:
          rest:
            api_styles: [rest]
      mcp:
        role: web
        networks: [web, internal]
        resources: {...}      # sized on concurrent sessions, not request rate
        command: [...]        # long idle timeouts, session-aware worker model
        surfaces:
          mcp:
            api_styles: [rpc]
```

**It is `role: web`.** A role is a *process type*, and process types are keyed on
how work arrives — `web` from inbound external requests, `worker` from a queue,
`clock` from time. MCP's work arrives as inbound external requests. Holding a
session while serving them is a characteristic of how it *serves*, not of how work
*arrives*, so it earns no new process type; the same test that condemned
`role: scheduler` in [`clock_core_service.md`](../005_process_type_solidification/clock_core_service.md)
applies. Public reachability comes from `networks: [web, internal]` regardless —
`tables/roles/web.yml` states outright that "routing is network-driven, not
role-static."

**It is a separate core service** because it fails the split test on `resources`
and `command`. **It is named `mcp`** because two core services on `role: web` in
one codebase cannot both take the role's name (`cicl.md:133`).

Note the classification this dissolves: `contracts.md` currently has to adjudicate
request-cycle vs. loop-owning health per service, and MCP genuinely sits between
the two. Under move 8, `./health.sh mcp` decides for itself.

## Known follow-on — routing timeouts

**Out of scope here; must not be forgotten.** There are no routing-timeout knobs
in CICL — `idle_timeout`, `deregistration_delay`, and `stickiness` return zero
hits across `docex/src/` and `doctrine/`. An ALB's default idle timeout is 60
seconds, so a long-lived MCP session on a Streamable-HTTP stream is cut at 60s in
`stage`/`prod` on elastic, for reasons unrelated to the project's code.

This must **not** be solved by letting `api_styles` drive target-group settings.
That would make surfaces smuggle deployment differences, which Part I explicitly
forbids. Timeouts are routing config and belong on the core service beside
`resources`, as a separate and smaller change.

## Resolved decisions

All five open questions are settled. Recorded here rather than deleted, because
each rules out an alternative a fresh context would otherwise re-propose.

1. **`health.sh` is per core service, invoked as `./health.sh <service>`.**
   Rejected: one shim per core service (four files where one suffices), and
   deriving the probe from process type (couples the shim to a concept still
   solidifying). The compiler emits the argv. This is a deliberate asymmetry with
   the other four shims and should be stated as such in `cicd.md`, not glossed.

2. **The probe still reports version — but only where it can be read.** Exit code
   is liveness; `docex` takes version from the orchestrator; `web`'s `GET /health`
   keeps its `{version: "x.x.x"}` body for project stage tests. ECS does not
   surface healthcheck output, so probe stdout is not a cross-foundation channel
   and no docex code should try to parse it. See move 11.

3. **All eight `api_styles` are defined; only `openapi` and `asyncapi` are
   implemented.** The style table is the language and lands whole. `proto` and
   `graphql` compile-fail with "format not yet implemented" — a named, honest
   boundary rather than a silent gap. Note both are non-YAML, so the path
   template's `.yml` assumption is what actually blocks them.

4. **Per-surface `port` is deferred.** The nested shape enables it; this advance
   does not build it. A core service keeps one `port`, which is the routed one.
   gRPC-alongside-REST therefore remains a two-core-service arrangement for now.

5. **A non-`web` core service declares a `port` only when it is directly
   addressed.** Rule 28 tied `port` to `health_check_path`, and
   `contracts.md:81` tied it to Service-Connect discoverability *for the
   fan-out* — both justifications die with the fan-out.
   `elastic_release_pattern.md` said as much outright before it was cut:
   "requiring all core services to be reachable via HTTP is an offshoot of
   requiring HTTP-based healthchecks." So a `uses` target reached over a queue
   or broker needs no port; one a consumer addresses directly does. This is a
   *validation* consequence of the surface, not deployment config derived from
   it — the distinction that keeps it clear of Part I's prohibition. The exact
   style-to-addressability mapping belongs in `cicl.md`/`contracts.md`, stated
   as a principle rather than a lookup table.

6. **Staging tests may not assert anything about non-`web` core services.** They
   cannot reach them at all under this change. A project wanting an end-to-end
   assertion through a worker drives the public edge and observes the effect —
   which is what `tests.md` already says smoke tests are for. This is a genuine
   narrowing and must be written into `tests.md § Staging Tests` explicitly.
