# Mod 031 — CICL Surface Refresh

Second mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Bundles every change to the `infra.yml` surface and downstream parser/validator/routing that the doctrine restructure landed.

## The Doctrine Changes

This mod implements the CICL-side bullets from [`../_advance_doctrine_shape_and_tiers.md`](../_advance_doctrine_shape_and_tiers.md) — the surface a project author touches:

1. **`domain:` → `apex_domain:`** — the top-level field rename per [`cicl.md`](../../../../doctrine/infrastructure/cicl.md). Semantics change: the value is now the *bare apex* (e.g. `example.com`), not the per-project apex-or-subdomain (e.g. `myproject.example.com`).
2. **New canonical domain form** per [`cicl.md § Domain`](../../../../doctrine/infrastructure/cicl.md#domain): `<service>.<env>.<project_name>.<apex_domain>` (e.g. `api.dev.myproject.example.com`). The `<project_name>` segment is new.
3. **Bare-form routing rules**:
   - Bare env (`<env>.<project>.<apex>`) → env's `domain_default_service`. (Already existed; the host string just gets longer.)
   - Bare project (`<project>.<apex>`) → **prod's** `domain_default_service`. **New**. Replaces the old `www.<apex>` convention for prod.
   - Bare apex (`<apex>`) → nothing. Out of scope.
4. **Service-name blacklist**: `dev`, `test`, `stage`, `prod`, `www`. Per [`cicl.md § Validation Rules`](../../../../doctrine/infrastructure/cicl.md#validation-rules) rule 14. `www` is on the list partly because it collided with the old `www.<apex>` = prod convention; removing the convention removed the collision *requirement*, but the doctrine still blacklists it for ergonomic clarity.
5. **`apex_domain` bare validation** — must not contain subdomain components. Rule 13.
6. **`reverse_proxy:` top-level field** — elastic-only. Values: `alb` (default), `ec2_traefik_eip`, `ec2_traefik_pip`. Per [`cicl.md § Reverse Proxy`](../../../../doctrine/infrastructure/cicl.md#reverse-proxy). Validation rule 18.
7. **`reverse_proxy` role removal** — the old `tables/roles/reverse_proxy.yml` no-op marker is gone. A project that declares `role: reverse_proxy` in `infra.yml` is now a compile error. The reverse proxy is project-tier infra (per mods 036, 038, 044); it's never a CICL service.
8. **Validation rule renumbering**. The old "every `web`-network service other than `reverse_proxy` declares a port" simplifies to "every `web`-network service declares a port" — the `role == "reverse_proxy"` exemption goes away because the role no longer exists.
9. **New compile-time magic vars** per [`transfer_tables.md § Available compile-time variables`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#available-compile-time-variables):
   - `${env_subdomain}` redefined: was `<env-prefix>.<domain>` (where `prod → www`); now `<env>.<project>.<apex>`.
   - `${apex_domain}` new — just the value of `apex_domain:`.
   - `${bare_project_subdomain}` new — `<project>.<apex>`. Useful for prod-routing rules that target the bare-project host.

The doctrine also says **the `reverse_proxy` *backing service* / role declaration is gone**. The role had a no-op `reverse_proxy.yml` transfer table that existed purely so `role: reverse_proxy` parsed cleanly; that's not needed in the new world.

## Concrete Surface Map (docex side)

### CICL parser and model — `src/docex/cicl/model.py`

- Rename `CICLDocument.domain: str` → `CICLDocument.apex_domain: str`.
- Add `CICLDocument.reverse_proxy: Literal["alb", "ec2_traefik_eip", "ec2_traefik_pip"] | None = None`.
- The docstring around `domain_default_service` references `<env>.<domain>` — needs updating to the new canonical form.

### CICL validator — `src/docex/cicl/validate.py`

- New `_validate_apex_domain_bare(doc)` — rejects `apex_domain` values that include `.` segments beyond the apex (e.g. `myproject.example.com` is illegal; `example.com` is fine; `example.co.uk` is fine).
- New `_validate_service_name_blacklist(doc)` — rejects any service named `dev`, `test`, `stage`, `prod`, `www`.
- New `_validate_reverse_proxy_field(doc)` — rejects `reverse_proxy:` when `foundation: fixed`. Accepts when elastic; defaults to `alb` if unset.
- `_validate_web_service_ports`: drop the `if svc.role == "reverse_proxy": continue` exemption; no service can legitimately be `role: reverse_proxy` anymore so the branch is dead.
- The validator should also reject `role: reverse_proxy` outright — graceful "this role no longer exists" error pointing at mod 031.

### Compiler — `src/docex/cicl/compile.py`

- Replace `_ENV_SUBDOMAIN_PREFIX` (with its `prod → www` mapping) with a simpler `f"{env}.{project}.{apex_domain}"` formula. `prod` becomes `prod`, not `www`.
- `_env_subdomain(domain, env)` becomes `_env_subdomain(apex_domain, project, env)` — same idea, three inputs instead of two.
- `_web_hosts` extends to also emit the bare-project host (`<project>.<apex>`) when:
  - The env is `prod`, AND
  - The service IS the `domain_default_service`.
- Remove the `if role == "reverse_proxy"` early return — that branch is dead.
- Substitution context (`_substitution_ctx` or equivalent dict): add `apex_domain`, `bare_project_subdomain`. Update `env_subdomain` value to new shape.
- Every `compiled.domain` / `doc.domain` reference becomes `apex_domain`.

### Emit — `src/docex/emit/{compose,hcl,templates}/*`

The compose Traefik labels and ALB listener-rule emission read the per-service host list from `_web_hosts` (or the equivalent on `CompiledService`). Mostly this just propagates — the list grows from 1–2 entries to 1–3 (bare-project added for prod's default service), and the host strings themselves change shape.

- `src/docex/emit/compose.py:99` docstring mentions `<env>.<domain>`. Update to canonical form.
- `src/docex/emit/compose.py:392` `# domain: ...` debug comment. Update wording.
- `src/docex/emit/hcl.py:519` comment mentions `<env>.<domain>`. Update.
- `src/docex/emit/hcl.py:868` and `~796` pass `domain=compiled.domain` to render templates. Rename.

The templates (`main.tf.j2`, etc.) accept whatever name we hand the renderer. Either rename the template variable from `domain` to `apex_domain` for clarity, or keep `domain` in the template and pass `compiled.apex_domain` into the slot. I'd lean toward renaming for consistency.

### Tables — `tables/`

- Delete `tables/roles/reverse_proxy.yml`.
- Update `tables/README.md` if it mentions the `reverse_proxy` role in its listing.

### Pipeline + describe + orchestrate — small ripple

- `src/docex/pipeline/stagetest.py:63` reads `infra.domain`. Rename.
- `src/docex/pipeline/bootstrap.py:142` passes `ctx.infra.domain` to `_print_delegation_instructions`. Rename.
- `src/docex/orchestrate/up.py:126` reads `ctx.infra.domain`. Rename.
- `src/docex/describe/llm.py:58` and `src/docex/describe/dag.py` — describe output uses `domain` key. Keep that key in describe output for now (operator-facing structured doc; field rename is doctrine-internal). Actually — reconsider: the LLM-output schema is doctrine-shaped, so the key probably should rename too. **Open question, but I'd just rename for consistency.**

### Tests

The test surface affected:

- **`tests/integration/test_compile.py`** — every test that constructs a CICL document inline uses `domain: example.com`. All become `apex_domain: example.com`. The `domain_default_service` mention in the surrounding prose stays. Any host-assertion strings (`api.dev.example.com`) that haven't been updated for the new project-name-bearing form must be updated to `api.dev.<project>.example.com` form.
- **`tests/unit/test_validate.py`** — add new test cases for the three new validation rules (apex bare, service-name blacklist, reverse_proxy elastic-only). Update any existing fixtures that use `domain:`.
- **`tests/unit/test_model.py`** (if present) — covers CICLDocument's parsing; rename field references.
- **`tests/unit/test_orchestrate_up.py`** and friends — same `domain:` rename in their inline fixtures.
- The `*_real.py` integration tests rely on inner-repo `infra.yml` files (under `test_projects/`). Per the operator decision, **we do not touch those** — they'll be rebuilt at end of advance. So those tests will mostly fail at `apex_domain` lookup until the end of the advance, but that's the documented cost of the deferral. *(Decision check below.)*

## Ramifications

### The compiled-output diff

For every project, the compiled `infra/output/<env>/docker-compose.yml` and `infra/output/<env>/main.tf` get diff in:

1. Traefik labels: `Host(\`api.dev.example.com\`)` becomes `Host(\`api.dev.myproject.example.com\`)`.
2. ALB listener-rule `host_header.values`: same shape change.
3. Prod's `domain_default_service` gets two extra host alternates: `prod.<project>.<apex>` and `<project>.<apex>` (replacing the old single `www.<apex>` form).
4. Comments in compose/HCL that include the rendered domain.

Same as mod 030: the test-projects committed output drifts. Not regenerated by this mod.

### Deletion of the `reverse_proxy` role

This is a small additional breaking change — a CICL surface a project author *could* have used (`role: reverse_proxy` as a no-op marker) is gone. In practice the role was always a marker and never load-bearing; no behavior was implemented behind it. But declaring it in `infra.yml` parsed cleanly before, and now produces a compile error.

The smoke projects' `infra.yml` files: I should check whether either of them declares `role: reverse_proxy`. If yes, that's part of the "end-of-advance re-inception" cleanup; we don't touch it now.

### Service name `www`

The blacklist includes `www` even though the `www.<apex>` convention is gone. The doctrine includes it because:
- HAProxy SNI routing on fixed uses domain parsing that depends on unambiguous service names.
- `www` is a near-universal subdomain convention; a service literally named `www` would surprise readers.

A project that *did* have `role: web, name: www` is now invalid; same end-of-advance cleanup story.

### Old `_ENV_SUBDOMAIN_PREFIX`'s `prod → www` mapping

Today, prod's `domain_default_service` answers at `www.example.com`. After this mod it answers at `example.com` (bare project) and `prod.example.com` (the bare-env form for prod). The bare-project form takes over `www`'s former role as "the canonical user-facing entry to prod."

Any deployed project today using the `www` form would lose that host after recompile and redeploy. Per operator decision, the only currently-deployed-but-not-being-handled-now projects are the smoke projects which get rebuilt at the end of the advance. Confirmed not a problem.

### Magic-var-changes ripple to transfer tables

The `${env_subdomain}` redefinition is largely behind-the-scenes — engines don't reference it heavily. But `transfer_tables.md` mentions:

> `${env_subdomain}` | The full bare-env hostname per [cicl.md § Domain](../cicl.md#domain): `${env_name}.${project_name}.${apex_domain}` (e.g., `dev.myproject.example.com`, `prod.myproject.example.com`).

I should grep transfer tables (bundled + smoke projects' if any) for `${env_subdomain}` usage to make sure none are silently relying on the old `prod → www` mapping.

## Operator Decisions

1. **Test-project `infra.yml` files** — do NOT touch in this mod. The inner-repo state and any `*_real.py` tests that rely on it stay broken until end-of-advance re-inception.
2. **`tables/roles/reverse_proxy.yml`** — delete, not archive.
3. **`describe` output field name** — rename `domain` → `apex_domain` in both `describe llm` JSON and `describe dag` text. The describe surface is doctrine-shaped and should track.
4. **`reverse_proxy:` default** — silent default to `alb` when an elastic project omits the field. No explicit-declaration requirement.

## What This Mod Is NOT

- Not implementing the EC2-traefik variant emission — that's mod 044. This mod just parses and validates the `reverse_proxy:` field; the value flows into a `CICLDocument.reverse_proxy` attribute and isn't read by any emit site yet.
- Not changing the `web_demux` HAProxy preinfra or the project-traefik emission — mod 036.
- Not implementing the project-tier ALB emission — mod 038.
- Not changing telemetry sidecar identifiers (`<svc>-otelcol` was mod 030's literal-joiner flip; full sidecar rename is mod 032).
- Not changing compiler output layout (`infra/output/project/{development,production}/...`) — mod 035.
- Not changing command surface — mod 034.

This mod is purely the CICL author-facing surface and its compiler-side handling.
