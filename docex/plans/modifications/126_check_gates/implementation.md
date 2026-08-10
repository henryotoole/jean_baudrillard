# Mod 126 — implementation steps

Execute against `/home/ubuntu/.claude/jean_baudrillard/docex` on branch
`006_surfaces_and_health`. Read [`overview.md`](./overview.md) first — especially its
**Rulings** section, which is binding and settles every question this doc does not
re-open.

**Unit baseline to beat: 1036 passed.** Integration baseline 20, expected to land at
18 (one file deleted).

**Territory.** `src/docex/pipeline/check.py`, `src/docex/errors.py`,
`tests/unit/test_contract_health_gates.py`, `tests/unit/test_pipeline_check.py`,
`tests/integration/test_check_real.py`,
`tests/integration/test_check_hcgate_real.py` (deleted), and
`tests/fixtures/sample_project{,_elastic}/**`. **Touch nothing else.** In particular
do not edit `src/docex/cicl/**`, `tables/`, `emit/`, `pipeline/stagelease`-anything,
`test_projects/`, or any file under `doctrine/` or `plans/core/`.

Run tests with `python -m pytest tests/unit -q` from the project root (the repo's
usual invocation; check `pytest.ini`/`pyproject.toml` if it differs).

---

## 1. `src/docex/pipeline/check.py`

### 1.1 Delete the format-by-role machinery

Remove, in the "Contract format" block near the top:

- the `# contracts.md § Standards: the format follows from the PROVIDER'S ROLE…`
  comment,
- `_CONTRACT_FORMAT_BY_ROLE`,
- `_FALLBACK_CONTRACT_FORMAT`,
- `_contract_format_for_role` (whole function, docstring included).

Also delete `_resolve_service` (whole function). Its rule-25 skip *policy* is
preserved as the expectation builder's skip rule in § 1.3 — carry that reasoning
across in a comment there, do not just drop it.

### 1.2 Add the format→extension table and rewrite `_parse_contract_filename`

Import `API_STYLE_FORMATS` / `IMPLEMENTED_CONTRACT_FORMATS` from
`docex.cicl.model` alongside the existing imports from that module. **Do not
re-transcribe `API_STYLE_FORMATS`.**

Add, in the block vacated by § 1.1:

```py
# contract format -> filename extension. Transcribed from contracts.md § Standards,
# which fixes exactly ONE extension per format. All four rows are carried, including
# the two formats `IMPLEMENTED_CONTRACT_FORMATS` excludes: this is the doctrine's
# table, and when `graphql` lands the only edit is one line in model.py.
#
# WHY here and not model.py, where mod 125 put API_STYLE_FORMATS: that table has two
# consumers (validate.py's rule 29 and this module). This one has exactly one, and a
# one-consumer table does not earn a home outside its consumer.
_FORMAT_EXTENSIONS = {
    "openapi": "yml",
    "asyncapi": "yml",
    "graphql": "graphql",
    "proto": "proto",
}
```

Rewrite `_parse_contract_filename` to return
`tuple[str, str, str, str] | None` — `(codebase, service, surface, format)`:

1. Split the trailing extension off the name once, from the right. No extension ⇒
   `None`.
2. Split the stem on `.`. **Exactly four** non-blank segments, else `None`.
3. Resolve `fmt = parts[-1]`. If `fmt` is not a key of `_FORMAT_EXTENSIONS` ⇒ `None`.
4. If the extension is not `_FORMAT_EXTENSIONS[fmt]` ⇒ `None`.
5. Return `(parts[-4], parts[-3], parts[-2], parts[-1])`.

Its docstring must be rewritten from scratch. Keep exactly two points from the old
one and drop the rest (the mod-096 left-anchored archaeology and the health-gate
reference both name things that no longer exist):

- Segments are indexed **from the right**, off the extension. "Right-anchored" has
  never meant *take the last four of however many* — the count is exact, so
  `a.b.c.d.e.openapi.yml` is `None`.
- `_SERVICE_NAME_RE` (model.py) admits no dots in a codebase, core-service, or
  surface name, so a canonical contract filename has exactly four stem segments and
  nothing else is a name `docex` authored.

Add a third point: the extension is checked **against the resolved format** rather
than against a list of accepted suffixes, which is what narrows `.yaml` out and what
lets the non-YAML formats use the same template.

### 1.3 `ContractExpectation` + `_expected_contracts`

New, immediately after `_parse_contract_filename`:

```py
@dataclass
class ContractExpectation:
    """One declared surface's expected contract file."""

    codebase: str
    service: str
    surface: str
    fmt: str
    path: Path
    svc: CoreService

    @property
    def dotted(self) -> str:
        return ServiceRef(self.codebase, self.service).dotted


def _expected_contracts(
    infra: CICLDocument, contracts_dir: Path
) -> list[ContractExpectation]:
    ...
```

Plain `@dataclass` (not `frozen=True`): it holds a pydantic model and is never
hashed, so a generated `__hash__` would be a trap rather than a feature.

Body: walk `infra.all_core_services()`; for each core service, walk
`sorted(svc.surfaces.items())`; for each surface:

- `fmts = surface.formats()`; if `len(fmts) != 1`, **skip**.
- `fmt = next(iter(fmts))`; if `fmt not in IMPLEMENTED_CONTRACT_FORMATS`, **skip**.
- otherwise append an expectation whose `path` is
  `contracts_dir / f"{cb}.{svc_name}.{surface_name}.{fmt}.{_FORMAT_EXTENSIONS[fmt]}"`.

Both skips need the comment that justifies them, and it must state the *ordering*
fact, because that is the whole reason they are honest (overview Ruling 6):

> WHY skip rather than report: rule 29 (`rule_29_mixed_contract_formats`,
> `rule_29_unknown_api_style`) and `rule_contract_format_not_implemented` already own
> these at compile time, and a second complaint here would name a filename the author
> could never have produced. Skipping does not let the project through: `run_check`
> runs every gate BEFORE `run_compile`, so `docex check` still fails — at the compile
> step, with the message that names the actual problem. That ordering is load-bearing
> and `test_check_reaches_compile_when_a_surface_is_skipped` pins it.

Same policy as `_resolve_service`'s deleted docstring stated for rule 25: one
authoring mistake produces one report.

### 1.4 `_gate_contracts` — rewritten

Signature becomes:

```py
def _gate_contracts(
    worktree: Path, ctx: ProjectContext, report: CheckReport
) -> tuple[list[ContractExpectation], list[str]]:
```

Returns `(existing_expectations, providers)`. The `no infra.yml — skipped` early
return is unchanged.

Body:

1. `providers = [e.dotted for … if svc.surfaces]` — walk `all_core_services()`
   directly and test `svc.surfaces`, **not** derived from the expectation list. A
   provider all of whose surfaces were skipped is still a provider; deriving it from
   expectations would make it silently vanish.
2. `expected = _expected_contracts(infra, contracts_dir)`; partition into `existing`
   (`e.path.is_file()`) and `missing`.
3. Orphans. If `contracts_dir.is_dir()`, for each entry in `sorted(contracts_dir.iterdir())`:
   skip non-files and names starting with `.`; skip names in
   `{e.path.name for e in expected}`; otherwise flag it as unexpected **iff**
   `_parse_contract_filename(name) is not None` **or** the name's final extension is
   in `_CONTRACT_EXTENSIONS = frozenset({"yml", "yaml", "graphql", "proto"})`.
4. Report. `missing` and unexpected both fail the gate; when both are non-empty the
   detail carries both clauses.

Message shapes:

- missing: `"missing contract(s): " + "; ".join(f"{e.dotted} surface {e.surface!r} (expected {e.path.relative_to(worktree)})")`
- unexpected (per Ruling 4.1 — **name the four-segment form and say rename or
  delete**):
  `f"{name}: matches no declared surface. The form is "
   f"<codebase>.<service>.<surface>.<format>.<ext> (e.g. api.web.rest.openapi.yml) — "
   f"rename it to the surface it describes, or delete it."`
- pass: `f"{len(existing)} contract(s) present"`, or
  `"no core service declares a surface — nothing to check"` when `providers` is empty.

Delete the `fallbacks` list, the `fallback_clause` string, and the comment explaining
why the fallback belongs on the failure too.

The docstring is rewritten. It must say three things:

1. **A core service is a provider iff it declares `surfaces:`.** One expected
   contract per surface, in the format that surface's `api_styles` resolve to
   (`Surface.formats()`).
2. The old two-armed `(core-targeted uses) ∪ (web-network core services)` union is
   deleted, **and the second arm was wrong, not merely redundant**: a `web`-network
   core service that declares no surface now correctly requires **no** contract. That
   is a frontend serving a browser, which `infrastructure.md § Contracts` uses as its
   worked example (`frontend.web` declares no surface). The old arm forced a contract
   onto it.
3. Why the orphan arm exists: an existence-only gate is blind to a half-renamed
   contracts directory *precisely because the new file also exists*, and a leftover
   three-segment `api.web.openapi.yml` is the likeliest 1.7.0 upgrade mistake in this
   advance.

### 1.5 `_gate_health_endpoints` — delete

Delete the entire function, docstring included. Nothing in it survives except the
self-`/health` assertion, which is rewritten from scratch as § 1.6 rather than
carried over.

### 1.6 `_gate_contract_health_path` — new

```py
def _gate_contract_health_path(
    ctx: ProjectContext,
    contracts: list[ContractExpectation],
    report: CheckReport,
) -> None:
```

No `worktree` parameter — the expectations carry absolute paths.

Scope: for each core service that is on the `web` network and has at least one
**existing** `openapi` expectation, at least one of those contracts declares a `get`
on the service's declared `health_check_path`.

Implementation:

1. `if ctx.infra is None: report.add("contract_health_path", True, "no infra.yml — skipped"); return`
2. Group `contracts` by `(codebase, service)`, keeping only `fmt == "openapi"`.
3. For each group, in sorted order:
   - `svc` from the expectation; `if "web" not in (svc.networks or []): continue`
   - `hcp = (svc.model_extra or {}).get("health_check_path")`;
     `if not isinstance(hcp, str) or not hcp: continue`
   - For each expectation in the group: `yaml.safe_load(path.read_text()) or {}`; on
     `yaml.YAMLError`, append a `f"{path.name}: malformed YAML ({exc})"` problem and
     move on to the next file.
   - Satisfied iff **any** file in the group has `paths[hcp]` as a dict containing a
     case-insensitive `get` key. Reuse the old gate's `_declares` idea, but write it
     fresh (no default-arg closure trick needed — pass the paths map explicitly).
   - Not satisfied ⇒ one problem naming the core service, the path, and every openapi
     contract that was searched.
4. Report `contract_health_path`: problems ⇒ fail with `"; ".join(problems)`;
   otherwise pass with `f"'GET <path>' present for N web-network openapi provider(s)"`
   or `"no web-network openapi providers — nothing to check"`.

The docstring carries four things, each load-bearing:

1. **The rule of record, quoted, because this gate is the one thing that survived a
   deletion order.** `healthchecks.md § web services also serve GET /health`: *"Where
   a `web`-network core service also declares an `openapi` surface, `GET /health` is
   part of that surface and belongs in its contract, which the check step asserts as
   well."* And `cicd.md § Check Step` 3.4. It is the *narrowed* form of the deleted
   `_gate_health_endpoints`' self-health arm, written by the same doctrine pass that
   deleted the fan-out.
2. **The path comes from the declared `health_check_path`, never a hardcoded
   `/health`.** `healthchecks.md` says both, and reading the field is the reading that
   is never wrong — a project declaring `/healthz` conforms, and hardcoding would fail
   it.
3. **"Any one" openapi surface satisfies it — and this is the reading that keeps every
   contract true** (overview Ruling 2, and this argument must be *in the code*, not
   only in the design doc). The doctrine says "an `openapi` surface", singular, and
   does not contemplate two. Requiring the path in *every* openapi surface would force
   `rest_admin` to document a route that is not part of the admin boundary — a
   **false** contract. A contract documenting something outside its own boundary is a
   worse defect than one omitting something documented next door.
4. **`web`-network membership, not role** — consistent with rule 33, and for the same
   reason: the field is what the reverse proxy reads, and a `role: web` core service
   off the `web` network has no reverse proxy. A non-`web` `openapi` provider
   (internal REST, reached by magic ref, `port` required by rule 32's positive arm,
   `health_check_path` forbidden by rule 33) must **not** declare the path in its
   contract.

Also note the two skip conditions and why they are not laxity: an absent
`health_check_path` on a `web`-network service is rule 33's to report at compile time,
and a missing contract file is `contracts_exist`' to report — so this gate declines
both rather than double-reporting.

### 1.7 `_gate_healthcheck_tooling` — delete

Delete the whole function, its 25-line docstring, and the `DockerClient` parameter it
alone needed. `run_check` keeps its `docker` argument (`_compose_build` uses it) — do
**not** change `run_check`'s signature.

Leave no tombstone comment in `check.py`. The reasoning for the deletion is recorded
in `overview.md § 5.2` and belongs there; a paragraph in the source explaining a gate
that is not there would be the wrong artifact.

### 1.8 `_gate_codebase_scripts` — `health.sh` becomes the fourth shim

- `for script in ("build.sh", "test.sh")` → `("build.sh", "test.sh", "health.sh")`.
- `migrate.sh` stays conditional on schema ownership — unchanged.
- Pass detail: `f"build.sh/test.sh/health.sh present for {len(all_codebases)} codebase(s)"`.
- Docstring: `"``build.sh``, ``test.sh`` and ``health.sh`` for every codebase;
  ``migrate.sh`` for any codebase that's a schema owner."`
- Add the asymmetry comment, per `cicd.md § Check Step` 3.1:

> `health.sh` is invoked **per core service**, as `./health.sh <service>` — the
> compiler supplies the argv. That changes nothing here (one file per codebase either
> way), which is exactly why it is worth saying: `build.sh`/`test.sh`/`migrate.sh` are
> properties of the source tree and so codebase-scoped, while health is a property of
> a running process. A reader who knows the argv exists would otherwise expect a
> per-core-service check in this gate and find none.

### 1.9 `run_check` wiring

Replace

```py
contracts, _providers = _gate_contracts(worktree, worktree_ctx, report)
_gate_health_endpoints(worktree, worktree_ctx, contracts, report)
_gate_codebase_scripts(worktree, worktree_ctx, report)
_gate_healthcheck_tooling(worktree, worktree_ctx, docker, report)
_gate_observability_backend_url_reachable(worktree_ctx, report)
```

with

```py
contracts, _providers = _gate_contracts(worktree, worktree_ctx, report)
_gate_contract_health_path(worktree_ctx, contracts, report)
_gate_codebase_scripts(worktree, worktree_ctx, report)
_gate_observability_backend_url_reachable(worktree_ctx, report)
```

Gate count on a non-empty-origin run goes **10 → 9**. Do not otherwise reorder
`run_check`; the gates-before-compile ordering is now asserted by a test.

---

## 2. `src/docex/errors.py`

Docstrings only — no behavior, and **do not delete either class**. Both are unraised
anywhere in `src/` (the gates report through `CheckReport`), so these are
documentation fixes on exported types.

- `ContractMissing`: `<codebase>.<service>.<fmt>.yml` →
  `<codebase>.<service>.<surface>.<format>.<ext>`.
- `ContractInvalid`: keep "A contract file is missing a doctrinally required
  endpoint", and add that the one such endpoint is a `web`-network core service's
  declared `health_check_path` in its `openapi` surface contract — `docex check`'s
  `contract_health_path` gate, which reports through `CheckReport` rather than raising
  this.

---

## 3. Fixtures

Apply to **both** `tests/fixtures/sample_project` and
`tests/fixtures/sample_project_elastic`, identically.

### 3.1 `infra/infra.yml`

`api.web` gains, beside `health_check_path`:

```yml
        surfaces:
          rest:
            api_styles: [rest]
```

Without this it declares no surface, is not a provider, and its contract file becomes
an **orphan** — the fixture would fail the very gate it exists to exercise.

### 3.2 `infra/contracts/api.web.openapi.yml` → `api.web.rest.openapi.yml`

`git mv` it. Then:

- Rewrite the header comment. The current one documents the three-segment scheme and
  a `/health/appdb` backing-service fan-out that `docex` stopped asserting in mod 047.
  Replace with a short note: one contract per declared surface, named
  `<codebase>.<service>.<surface>.<format>.<ext>`; `docex check`'s
  `contract_health_path` gate asserts a `GET` on `api.web`'s declared
  `health_check_path` and does no schema conformance.
- **Delete the `/health/appdb` path.** Nothing requires it and leaving it models a
  shape the doctrine now forbids.
- Keep `/health` with its `GET`.

### 3.3 `core/api/health.sh` — new, executable

```sh
#!/bin/sh
# Container health probe. Invoked per core service as `./health.sh <service>`;
# the compiler supplies the argv (cicd.md § Check Step, healthchecks.md § The probe).
set -eu

service="${1:-}"
case "$service" in
  web)
    # Language-native check — this image is python:3.12-slim and carries no curl.
    exec python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
    ;;
  *)
    echo "health.sh: unknown core service '${service}'" >&2
    exit 1
    ;;
esac
```

`chmod +x` it (and verify the mode is committed: `git update-index --chmod=+x` is not
needed if `chmod` precedes `git add`, but confirm with `git ls-files -s`).

### 3.4 `core/api/Dockerfile`

Add `health.sh` to the `dev` and `prod` stages beside the other shims — `COPY
health.sh /service/health.sh` and include it in the existing `chmod +x`. `prod`
currently chmods only `migrate.sh`, so it needs `RUN chmod +x /service/migrate.sh
/service/health.sh`. `infrastructure.md § Codebase Containers` requires the image to
be able to run `./health.sh <service>`; nothing invokes it before mod 127, but a
fixture that could not is a fixture that lies.

---

## 4. `tests/unit/test_contract_health_gates.py` — effectively rewritten

### 4.1 Module docstring and helpers

Rewrite the docstring. Its current three numbered claims (format-follows-role, the
two-armed provider set, the fan-out keying on core `uses` targets) are all now false.
The new one states: the provider set is `surfaces:` and nothing else; one contract per
surface at `<codebase>.<service>.<surface>.<format>.<ext>`; and the one surviving
content assertion — a `web`-network core service's `openapi` contract declares a `GET`
on its declared `health_check_path`. Keep the final paragraph about inline-`infra.yml`
projects under `tmp_path`.

Keep the filename. It still tests a contract gate and a health gate.

Helpers:

- `_proc` gains a `surfaces: dict[str, list[str]] | None = None` parameter emitting a
  `surfaces:` block (`{name: api_styles}`).
- `_ASYNCAPI` survives; its comment (which explains the deleted § Declared by fields)
  does not — replace with "an AsyncAPI contract has no `paths:`, which is why the
  health-path gate only ever looks at `openapi` contracts".
- `_health_result` → `_health_path_result`, running `_gate_contracts` then
  `_gate_contract_health_path` and returning the `contract_health_path` result, with
  the same "exactly as `run_check` wires them" comment.
- `_contracts_result` unchanged except that `contracts` is now a list of
  `ContractExpectation`; assertions on names read `e.path.name`.
- `_web_and_worker` rewritten: `api.web` (web, port 8080, `health_check_path`,
  `surfaces: {rest: [rest]}`, `uses: [api.worker]`) and `api.worker` (internal only,
  **no** port, **no** `health_check_path`, `surfaces: {events: [events]}`). Drop its
  `worker_port` / `worker_hcp` parameters — rules 32 and 33 make both of those shapes
  unrepresentable, and no surviving test needs them.

### 4.2 Deletions

Delete outright: `test_unknown_role_fallback_is_reported`,
`test_missing_fanout_probe_fails`, `test_web_target_is_not_proxied`,
`test_internal_openapi_provider_requires_self_health`,
`test_core_uses_target_without_port_fails`,
`test_core_uses_target_without_health_check_path_fails`,
`test_fully_declared_core_uses_target_passes`, and the mod-113 comment block about
`test_fanout_required_without_depends_on`.

`test_internal_openapi_provider_requires_self_health` gets a one-line deletion note
in the module (not a tombstone function): its premise — "probeable one hop away" — *is*
the fan-out, and `healthchecks.md` now says a non-`web` core service "needs no HTTP
surface of any kind". Test 4.3.15 below is its positive inverse.

### 4.3 Tests, final roster

Rewritten from existing:

1. `test_provider_set_is_surfaces_only` — `_web_and_worker`, only
   `api.web.rest.openapi.yml` on disk. Gate fails naming
   `api.worker.events.asyncapi.yml`; `providers` contains both. Supplying the asyncapi
   file passes, and the expectation paths are exactly those two names. Assert the
   asyncapi name specifically — the format came from `api_styles: [events]`, not from
   `role: worker`.
2. `test_two_web_services_each_get_a_contract` — `api.web` + `api.admin`, both with
   `surfaces: {rest: [rest]}`; drop-one-at-a-time as today.

New:

3. `test_two_surfaces_two_contracts` — one core service declaring `rest` (openapi) and
   `events` (asyncapi). Both files required; with only one present the other is named
   in the detail.
4. `test_two_surfaces_same_format_distinct_filenames` — `rest_public` and `rest_admin`,
   both `[rest]`. Two distinct expected names; both required; and
   `_parse_contract_filename` round-trips both to their own surface segment. This is
   the case a three-segment scheme cannot express at all.
5. `test_web_network_service_without_surfaces_needs_no_contract` — a `web`-network
   core service (port, `health_check_path`) with **no** `surfaces:` and an empty
   contracts dir. Gate passes; `providers` is empty; the detail says nothing is
   declared. The deleted second arm's exact inverse.
6. `test_orphan_contract_for_undeclared_surface_fails` — a canonical
   `api.web.graphql_admin.openapi.yml` beside the declared `api.web.rest.openapi.yml`.
   Fails; detail names the file and "rename it to the surface it describes, or delete
   it".
7. `test_stale_three_segment_contract_fails` — both `api.web.rest.openapi.yml` (valid)
   and a leftover `api.web.openapi.yml`. Fails; detail names the leftover **and the
   four-segment form**. This is the 1.7.0 upgrade case.
8. `test_wrong_extension_is_an_orphan` — `api.web.rest.openapi.yaml` on disk and no
   `.yml`. Both clauses fire: the `.yml` is missing *and* the `.yaml` is unexpected.
9. `test_non_contract_files_are_ignored` — `README.md` and `.gitkeep` beside a valid
   contract. Gate passes.
10. `test_mixed_format_surface_is_skipped` — `api_styles: [rest, rpc]`. `_gate_contracts`
    passes and demands no file for that surface (rule 29 owns it). Pair with the
    `run_check`-level test in § 5.5.
11. `test_unimplemented_format_surface_is_skipped` — `api_styles: [graphql]`. Gate
    passes; no `.graphql` file demanded.
12. `test_contract_filename_parsed_four_segments` — replaces
    `test_contract_filename_parsed_right_anchored` (which asserted a four-segment stem
    is *invalid*). Table:
    `api.web.rest.openapi.yml` → the 4-tuple; `api.worker.events.asyncapi.yml` → the
    4-tuple; and `None` for `api.web.rest.openapi.yaml`, `api.web.openapi.yml`,
    `a.b.c.d.e.openapi.yml`, `api.web.rest.openapi.txt`, `api..rest.openapi.yml`,
    `api.web.rest.bogus.yml`.
13. `test_health_path_missing_from_openapi_contract_fails` — `web` + `rest` surface,
    contract declares `/other` only. Fails; detail names the contract and `/health`.
14. `test_health_path_read_from_declared_field` — `health_check_path: /healthz`. A
    contract declaring `/healthz` passes; one declaring `/health` fails. This is the
    test that would catch a regression to a hardcoded path.
15. `test_health_path_in_any_one_openapi_surface_suffices` — `rest_public` declares it,
    `rest_admin` does not. Passes. Ruling 2's shape.
16. `test_non_web_openapi_provider_needs_no_health_path` — an internal-only core
    service with an `openapi` surface, a `port`, no `health_check_path`, and a contract
    declaring no health route. Passes. The positive inverse of the deleted mod-101
    widening; docstring says so.
17. `test_malformed_contract_yaml_is_reported` — an openapi contract that is not valid
    YAML. Fails with "malformed YAML".

---

## 5. `tests/unit/test_pipeline_check.py`

1. `test_check_contracts_missing_failure` — unlink
   `infra/contracts/api.web.rest.openapi.yml`.
2. `test_check_health_endpoint_missing_failure` → rename to
   `test_check_contract_health_path_failure`; it already rewrites the contract to drop
   `/health`, so only the filename and the asserted gate name
   (`"contract_health_path" in out`) change.
3. **Delete** the five `_gate_healthcheck_tooling` tests
   (`test_hcgate_passes_when_curl_present`, `test_hcgate_fails_when_curl_absent`,
   `test_hcgate_skips_services_without_health_check_path`,
   `test_hcgate_checks_nonweb_health_check_path_service`,
   `test_hcgate_reports_build_failure`), the `_hc_ctx` helper, and the
   `# Gap I (mod 051)` section banner. Leave `test_check_empty_origin_skips_trunk_gates`
   (which follows them) intact.
4. `test_check_happy_path_aggregates_all_passing` — **add an explicit roster
   assertion**, which the test currently lacks. Assert `"all 9 gate(s) passed"` in the
   output, that `contract_health_path` appears, and that neither `health_endpoints` nor
   `healthcheck_tooling` does. Careful with `capsys`: read `readouterr()` **once** into
   a local and assert against that.
5. **New** `test_check_reaches_compile_when_a_surface_is_skipped` — Ruling 6's
   ordering pin, at the `run_check` level rather than the gate level. Use
   `worktree_setup` plus a variant of `stub_test_and_compile` that stubs
   `_compose_build`, `run_test`, and `urlopen` but **leaves `run_compile` real**
   (parameterize the existing fixture or add a second one; do not duplicate the
   urlopen stub by hand twice if it can be factored). Add a second surface to
   `api.web` with `api_styles: [rest, rpc]` before `run_check`, then assert
   `pytest.raises(ValidationError)` and that `rule_29_mixed_contract_formats` appears
   in `str(excinfo.value)`. `run_compile` **raises** `ValidationError` rather than
   returning non-zero, and it validates before emitting anything, so this is cheap.
   The test's docstring must state what it defends: `_expected_contracts` skips a
   mixed-format surface only because compile runs later in the same command, so a
   reorder of `run_check` would turn the skip into a hole.
6. **New** `test_check_requires_health_sh` and
   `test_check_requires_health_sh_executable` — delete / `chmod -x`
   `core/api/health.sh` in the source tree before `run_check`, assert `rc == 1` and
   `"codebase_scripts"` in the output.

---

## 6. Integration

1. `tests/integration/test_check_real.py` — update the contract filename in
   `test_check_real_fails_on_missing_contract_health`; rename it to
   `test_check_real_fails_on_missing_contract_health_path`. Its body (rewrite the
   contract so the health route is absent) is already exactly the surviving assertion.
   No other change; `_init_repo_with_fixture` copies whatever the fixture holds.
2. `tests/integration/test_check_hcgate_real.py` — **delete the file.** It exists
   solely to exercise the curl gate against real `docker build` + `docker run`.
   Integration count 20 → 18.

Note while you are here, and report it: the fixture image is `python:3.12-slim`, which
carries no `curl`, while `api.web` declares `health_check_path`. If
`test_check_real_happy_path` was passing before this mod, `curl` was present after all;
if it was failing, deleting the gate fixes it. Either way, **state which** in your
report — do not silently assume.

---

## 7. Verification — red before green, per behavior

Advance 005's standing rule: a check's pass is worthless until it has been observed
failing. Do all of § 1–6 first, confirm the suite is green, **then** demonstrate red
for each new behavior by neutralizing exactly the clause that implements it, running
the one test, recording the failure output, and restoring. One mutation at a time; the
suite must be green again between each.

| Behavior | Mutation to demonstrate red | Test that must fail |
| -------- | --------------------------- | ------------------- |
| two surfaces ⇒ two contracts | in `_expected_contracts`, `break` after the first surface of a core service | `test_two_surfaces_two_contracts` |
| same-format surfaces stay distinct | drop `{surface}` from the filename f-string | `test_two_surfaces_same_format_distinct_filenames` |
| surface-less `web` service needs no contract | re-add the old second arm (`or "web" in (svc.networks or [])`) as a provider test | `test_web_network_service_without_surfaces_needs_no_contract` |
| orphans are reported | comment out the unexpected-file loop | `test_orphan_contract_for_undeclared_surface_fails`, `test_stale_three_segment_contract_fails` |
| extension narrowing | re-accept `.yaml` in `_parse_contract_filename` | `test_wrong_extension_is_an_orphan`, `test_contract_filename_parsed_four_segments` |
| health path from the field | hardcode `"/health"` instead of reading `health_check_path` | `test_health_path_read_from_declared_field` |
| any-one-surface suffices | require the path in **every** openapi contract of the group | `test_health_path_in_any_one_openapi_surface_suffices` |
| non-`web` provider exempt | drop the `"web" in networks` guard | `test_non_web_openapi_provider_needs_no_health_path` |
| `health.sh` required | revert the shim tuple to `("build.sh", "test.sh")` | `test_check_requires_health_sh` |
| gates run before compile | move the `_gate_*` calls after `run_compile` in `run_check` | `test_check_reaches_compile_when_a_surface_is_skipped` |

Record, for each row, the test name and the one-line failure message you actually saw.
That list goes in your report.

Finally:

- `python -m pytest tests/unit -q` — report the count against the **1036** baseline.
- `python -m pytest tests/unit -q -p no:randomly` if the suite is order-randomized, to
  rule out ordering flakiness in the new fixture edits.
- Do **not** run `pytest -m integration` (docker/AWS cost; the mod owner runs it).
- Confirm `git status` shows changes only within the territory listed at the top.

## 8. Do not

- Do not touch `src/docex/cicl/**` — `API_STYLE_FORMATS`, `Surface`,
  `CoreService.surfaces`, and rules 29–33 are mod 125's and are correct. Import them.
- Do not re-raise rules 29–33 in `check.py`.
- Do not edit `tables/`, `emit/`, `pipeline/stagetest.py`, `pipeline/release.py`, or
  `test_projects/`.
- Do not touch any file under `doctrine/`.
- Do not update `plans/core/masterplan.md` (mod 131's § *The contract and health
  gates*) or `plans/core/compiler.md` (brought current by mod 125).
- Do not "fix" `test_projects/`' now-failing `docex check`. It is expected: they lack
  `health.sh` and their contracts are still three-segment. Mod 129 owns both.
- Do not commit. The mod owner reviews the working tree and commits.
