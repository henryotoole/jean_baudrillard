# Implementation — Mod 031 — CICL Surface Refresh

## Context for fresh-context implementer

You are executing mod 031 of a 16-mod docex campaign. Read [`overview.md`](./overview.md) first — it explains the doctrine bullets being implemented and locks four operator decisions. This document is the operational plan.

Invoke the `docex-edit` skill first to load the docex core docs + relevant doctrine specifics.

Authoritative doctrine reading:
- [`doctrine/infrastructure/cicl.md`](../../../../doctrine/infrastructure/cicl.md) — top-level config, domain rules, validation rules, `reverse_proxy:` field.
- [`doctrine/infrastructure/cicl.md § Domain`](../../../../doctrine/infrastructure/cicl.md#domain) — canonical form, bare-form routing, TLS implications.
- [`doctrine/infrastructure/cicl.md § Reverse Proxy`](../../../../doctrine/infrastructure/cicl.md#reverse-proxy) — `reverse_proxy:` field values.
- [`doctrine/infrastructure/specifics/transfer_tables.md § Available compile-time variables`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#available-compile-time-variables) — magic var contract.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- **Do not modify `test_projects/{fixed,elastic}/infra.yml`** or their compiled output. Inner-repo state stays temporarily inconsistent; the `*_real.py` tests will fail and are out of scope for verification.
- **Delete `tables/roles/reverse_proxy.yml`**, do not archive.
- **Rename `domain` → `apex_domain` in describe outputs** (`describe llm` JSON and `describe dag` text).
- **Default `reverse_proxy:` to `alb`** silently when an elastic project omits the field. No required-field error.

## Step-by-step plan

### Step 1 — Rename and extend the CICL model

Edit `src/docex/cicl/model.py`:

1. On `CICLDocument`, rename field `domain: str` → `apex_domain: str`.
2. Update the docstring comment block around the renamed field to describe the new semantics (the value is the *bare apex*, e.g. `example.com` or `example.co.uk`; not `myproject.example.com`).
3. Update the `domain_default_service` docstring comment that currently references `<env>.<domain>` — change to `<env>.<project>.<apex_domain>` to match the new canonical form.
4. Add a new field:
   ```python
   reverse_proxy: Literal["alb", "ec2_traefik_eip", "ec2_traefik_pip"] | None = None
   ```
   Place it logically near `foundation:` since the field is foundation-gated. Add a docstring noting elastic-only.

### Step 2 — Update CICL validator

Edit `src/docex/cicl/validate.py`:

**New validators (add as `_validate_*` functions and wire into the main validation loop):**

- `_validate_apex_domain_bare(doc)` — rejects values containing more than the apex. Concretely: split on `.`, the result should be 2 or 3 parts (`example.com`, `example.co.uk`). 4+ parts is illegal. A leading subdomain (`myproject.example.com`) is the most common misuse and should produce a clear error like:
  > `apex_domain` must be a bare apex (e.g. `example.com`), got `myproject.example.com`. Per `cicl.md`, the project subdomain is derived automatically from `name`.
- `_validate_service_name_blacklist(doc)` — rejects any service named `dev`, `test`, `stage`, `prod`, `www` (case-sensitive — these are the exact reserved tokens). Cite the cicl.md rule in the error.
- `_validate_reverse_proxy_field(doc)` — when `doc.foundation == "fixed"`, reject any non-None `reverse_proxy:`. When elastic, accept the three values (the Literal type already enforces this at parse time, but keep the validator for the foundation gate). No coercion to default here — that's a compile-time concern, not validation.

**Updated validators:**

- `_validate_web_service_ports`: drop the `if svc.role == "reverse_proxy": continue` early return at line 457. With the role gone, no service can have it.
- `_validate_domain_default_service` (line 428–448): no logic change, just verify the error messages don't mention `<env>.<domain>` form — adjust phrasing if they do.
- Add new validator that rejects `role: reverse_proxy` outright with a message pointing at mod 031: this role no longer exists; reverse proxies are project-tier infra (see [`projinfra/`](../../../../doctrine/infrastructure/specifics/projinfra/)).

Wire the three new validators into the validation loop at the top of the file.

### Step 3 — Update the compiler

Edit `src/docex/cicl/compile.py`:

1. **Replace `_ENV_SUBDOMAIN_PREFIX`**: delete the dict at lines 40–46. The `prod → www` mapping is obsolete.
2. **Rewrite `_env_subdomain`**: change signature to `_env_subdomain(apex_domain: str, project: str, env: str) -> str` and return `f"{env}.{project}.{apex_domain}"`. The old form `<env-prefix>.<domain>` is gone — env is always its literal name now.
3. **Update `_web_hosts`** (lines 294–311):
   - Drop the `role == "reverse_proxy"` early return; the role doesn't exist.
   - Function now also needs `project` and `apex_domain` (or an already-computed `bare_project_subdomain`) — pass them in.
   - Extend the default-service branch: when `env == "prod"` and `name == default_service`, also include the bare-project host (`f"{project}.{apex_domain}"`).
   - **Order convention for the host list**: `[per_service, bare_env, bare_project?]` — most specific to least specific. Test assertions may need updating to match; verify before committing.
4. **Substitution context**: every place the compiler builds the `${var}` dict (`_substitution_ctx` or per-service render context — search for `env_subdomain` to find them):
   - Update `env_subdomain` value to the new shape.
   - Add `apex_domain` (the bare apex string).
   - Add `bare_project_subdomain` (= `f"{project}.{apex_domain}"`).
5. **Rename refs**: every `doc.domain` becomes `doc.apex_domain`; every `compiled.domain` becomes `compiled.apex_domain`. Find them with:
   ```bash
   grep -rn '\.domain\b' src/docex/ | grep -v __pycache__
   ```
   Most are in `compile.py`, `pipeline/{bootstrap,stagetest}.py`, `orchestrate/up.py`, `emit/{compose,hcl,describe/*}.py`. Sweep.

### Step 4 — Update emit sites and templates

#### `src/docex/emit/compose.py`

- Docstring at line 99 mentions `<env>.<domain>` — update to canonical form.
- Comment at line 392 (`# domain: ... -> ...`) — update wording to use `apex_domain`.
- The Traefik-label emission reads per-service host lists from the compiler. If it constructs hosts inline (rather than reading from `CompiledService`), update the construction to match the new shape.

#### `src/docex/emit/hcl.py`

- Comment at line ~519 references `<env>.<domain>`; update.
- `domain=compiled.domain` template kwargs (lines ~796, ~868): rename both the field source and the template-side variable name. Use `apex_domain` end-to-end.
- ALB listener-rule emission: the `host_header.values` list should contain whatever `CompiledService.hosts` (or equivalent) produces. Confirm the propagation works after the compiler-side change in Step 3.

#### `src/docex/emit/templates/main.tf.j2`

- Rename the template variable `{{ domain }}` → `{{ apex_domain }}`. Sweep the file.

### Step 5 — Delete the `reverse_proxy` role table

```bash
rm tables/roles/reverse_proxy.yml
```

Check `tables/README.md` — line 18 lists the role. Remove the line and refresh any narrative.

The loader (`src/docex/cicl/transfer.py::load_transfer_tables`) probably has no role-name hardcoding, but verify by searching for `"reverse_proxy"` in `transfer.py`. If a role list is hardcoded anywhere (the doctrine roles ship as a closed set in some places), drop the entry.

### Step 6 — Update describe outputs

Per operator decision, `describe llm` and `describe dag` use the doctrine field name.

#### `src/docex/describe/llm.py`

- Line ~58: `"domain": compiled.domain` → `"apex_domain": compiled.apex_domain`.
- Line ~23: `"kind": "reverse_proxy"` — this was probably the role marker. Audit context: if it's emitting a `reverse_proxy` *infrastructure node* in the describe output (representing the project's reverse proxy), the kind should now be either `project_reverse_proxy` or it should reflect the foundation-aware choice. Per the doctrine, on fixed it's the per-project Traefik; on elastic it's either ALB or EC2-traefik. **For mod 031**, just remove the synthetic `reverse_proxy` describe node if it was being emitted as a CICL service — it's not a service anymore. The project-tier reverse-proxy describe node is mod 036/038 work, not this mod.

#### `src/docex/describe/dag.py`

- Line ~18: `("reverse_proxy", "machine-wide traefik")` — remove. Same reasoning as above.
- Line ~66: `f"  - reverse_proxy            ALB ({...}-alb)"` — remove. The reverse proxy is project-tier and will be described properly in mods 036/038.

These removals leave a small gap in describe output. That's fine — the project tier isn't described yet at all; mod 036 will start filling it in.

### Step 7 — Update pipeline + orchestrate ripple

Sweep `\.domain\b` references and rename:

- `src/docex/pipeline/stagetest.py:63` — `domain = infra.domain` → `apex_domain = infra.apex_domain`. Update the variable use site too.
- `src/docex/pipeline/bootstrap.py:142` — `_print_delegation_instructions(project_dir, project, ctx.infra.domain)` → `ctx.infra.apex_domain`. The function probably uses the value to print delegation info; the printed strings should now reflect the new form (`<project>.<apex>` rather than just `<apex>`).
- `src/docex/orchestrate/up.py:126` — `domain = ctx.infra.domain if ctx.infra is not None else "<unknown>"` → rename. The variable use is probably in a printed URL; check it's referring to the right shape.

### Step 8 — Update tests

#### Fixtures

Every test fixture that constructs a CICL document inline has `domain: example.com` or similar. Find and update:

```bash
grep -rn 'domain:.*\.com\|domain:.*\.org' tests/ | grep -v __pycache__
```

For each hit:
- Rename `domain:` → `apex_domain:`.
- If a hit was previously `domain: myproject.example.com` (i.e. included a project subdomain), strip the project segment — `apex_domain:` must be bare.

#### New tests

Add three new test cases in `tests/unit/test_validate.py`:

1. `test_apex_domain_must_be_bare`: a fixture with `apex_domain: myproject.example.com` should produce a validation error mentioning `apex_domain` and the bare requirement.
2. `test_service_name_blacklist`: fixtures with services named each of `dev`/`test`/`stage`/`prod`/`www` should fail validation.
3. `test_reverse_proxy_field_elastic_only`: a fixed-foundation project with `reverse_proxy: alb` should fail; an elastic project with the same field should succeed.
4. `test_reverse_proxy_role_no_longer_exists`: a service with `role: reverse_proxy` should fail validation pointing at mod 031's removal.

Optional (suggested): `test_reverse_proxy_default_is_alb_on_elastic` — confirms that an elastic project with the field omitted compiles and produces output equivalent to one with `reverse_proxy: alb` explicit.

#### Existing test updates

- `tests/integration/test_compile.py` — every test that asserts a host string. The shape changes from `api.dev.example.com` to `api.dev.<project>.example.com`. For tests using `docex_smoke_elastic` as project, that becomes `api.dev.docex_smoke_elastic.example.com`. **Be careful**: the doctrine's hyphen unification (mod 030) does NOT apply to the project segment of a DNS host — DNS labels can contain neither `_` nor capitals. *(Decision needed — see § Edge case below.)*
- Prod's `domain_default_service` test cases get an extra bare-project host expected. Update the assertions accordingly.

### Step 9 — Run the test suite

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both must be green before declaring done. The `*_real.py` tests are deselected (out of scope) and may still fail when the operator runs them eventually — that's expected per the campaign-wide deferral.

### Step 10 — Final sanity sweep

```bash
# No `domain:` field in CICL fixtures or `.domain` attribute reads
grep -rn '\.domain\b\|^\s*domain:' src/ tests/ tables/

# No reverse_proxy role references
grep -rn 'reverse_proxy' src/ tables/ tests/ | grep -v 'reverse_proxy:\s*\(alb\|ec2_traefik\)'
```

The first sweep should return no hits in src/ or tables/, and only the new test cases (testing rejection of the old `domain:` form) in tests/.

The second sweep should return hits only for:
- The new `CICLDocument.reverse_proxy` field declaration and validators.
- Test fixtures using `reverse_proxy: alb` etc. to test the field.
- Documentation strings citing the doctrine.

## Edge case worth flagging

Project name `docex_smoke_elastic` becomes part of a DNS hostname under the new canonical form: `api.dev.docex_smoke_elastic.example.com`. **DNS labels cannot contain underscores.**

The doctrine's `http_host` policy is hyphen-only — it would translate `docex_smoke_elastic` to `docex-smoke-elastic` for the DNS-label position. But the project segment of `<service>.<env>.<project>.<apex>` is not currently passed through `http_host`.

**Question to surface to the design context** if you hit this: do we apply `_dns_label(project)` (hyphen-translate the project segment) when constructing host strings? The doctrine implies yes — DNS hosts must be valid DNS labels — but neither this mod's overview nor the doctrine prose explicitly calls out the translation point.

**Suggested approach**: in `compile.py`'s host construction, pass the project name through `_dns_label` (which already exists and lowercases + translates underscores). The committed test-project naming has underscores (`docex_smoke_elastic`), so this is load-bearing for getting valid Traefik / ALB host rules.

If this turns out to be more involved (e.g. the magic var `${bare_project_subdomain}` needs the translated form too, not the raw project name), STOP and report back — that's a doctrine clarification, not an implementation choice.

## Out of scope — explicit non-goals

- **No emission of project-tier reverse proxy** — mods 036 (fixed Traefik), 038 (ALB), 044 (EC2-traefik).
- **No `web_demux` HAProxy preinfra changes** — mod 036/042.
- **No compiler output layout changes** — mod 035.
- **No command surface changes** — mod 034.
- **No test-project recompile** — deferred to campaign end (operator decision).
- **No telemetry sidecar rename** — mod 032.

## Done criteria

- [ ] `CICLDocument.domain` renamed to `apex_domain`; `reverse_proxy:` field added with Literal-typed values.
- [ ] Three new validators landed; existing `_validate_web_service_ports` no longer references `reverse_proxy`; `role: reverse_proxy` rejected with a clear error.
- [ ] `_ENV_SUBDOMAIN_PREFIX` removed; `_env_subdomain` rewritten; `_web_hosts` updated with bare-project for prod default service.
- [ ] Substitution context exposes `apex_domain`, `bare_project_subdomain`, redefined `env_subdomain`.
- [ ] All `compiled.domain` / `doc.domain` / `infra.domain` reads renamed.
- [ ] `tables/roles/reverse_proxy.yml` deleted; `tables/README.md` updated.
- [ ] Template `{{ domain }}` → `{{ apex_domain }}`; describe output keys renamed; reverse_proxy synthetic describe nodes removed.
- [ ] New validation tests added; existing test fixtures updated.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No edits to `test_projects/{fixed,elastic}/`.
- [ ] DNS-label edge case (Step 10 § Edge case) handled or escalated.

When finished, leave the working tree dirty for the design-context agent's review. Do not commit.
