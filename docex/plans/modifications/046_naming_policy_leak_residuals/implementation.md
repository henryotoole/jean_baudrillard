# Implementation — Mod 046 — Naming Policy Leak Residuals

## Context for fresh-context implementer

You are executing mod 046. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:

- [`transfer_tables.md § Naming Policies`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies) — the "anything name-resolvable on the data plane uses hyphens" rule.
- [`projinfra/elastic_route53_zone.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md) — the zone covers `<project>.<apex_domain>` and the project segment must be DNS-valid.
- [`projinfra/elastic_acm_certs.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md) — cert SAN structure.
- [`projinfra/fixed_reverse_proxy.md`](../../../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md) — `${project}-traefik` and the four `${project}-${env}-web` networks.
- [`preinfra/fixed_master_network.md`](../../../../doctrine/infrastructure/preinfra/fixed_master_network.md) — the HAProxy demux reconstructs `${project_name}-traefik` from the domain (post-`_dns_label`).

## The principle to apply

Every emit site that puts a name onto the data plane (Docker network/container/volume, ECS Service Connect namespace, Route53 zone or record, ACM cert) must derive its project segment from the DNS-labeled form (`project.replace('_', '-').lower()` — equivalent to `apply_policy(project, http_host)` or `_dns_label(project)`), not from the raw `project_name`. Inert AWS record-key identifiers (IAM, SSM, DDB) keep their existing policy behavior.

The clean way to plumb this is to add the DNS-labeled form to the data the emitters already consume:

1. Add a `project_dns_label: str` field to `CompiledEnv` (set to `_dns_label(project_name)` in `compile_env`).
2. Pass `project_dns_label` into the project-tier emit calls in `run_compile`.
3. Update each emit site to use `compiled.project_dns_label` (or the new arg) instead of `compiled.project` whenever the result lands on the data plane.

Joiners are already hyphens at every site we touch (mod 030); we're only changing how the project segment is rendered.

## Step-by-step plan

### Step 1 — Add `project_dns_label` to `CompiledEnv`

`src/docex/cicl/compile.py`:

1. In `compile_env`, just after `subdomain = _env_subdomain(...)` and `bare_project = _bare_project_subdomain(...)`, compute:

   ```python
   project_dns_label = _dns_label(project_name)
   ```

2. Add `project_dns_label: str` field to the `CompiledEnv` dataclass (place it next to `project: str`).

3. Pass `project_dns_label=project_dns_label` into the `CompiledEnv(...)` constructor call.

### Step 2 — Patch compose env-tier emit (`src/docex/emit/compose.py`)

1. **`_network_section`** (around line 84): replace `f"{compiled.project}-{compiled.env}-…"` with `f"{compiled.project_dns_label}-{compiled.env}-…"`.

2. **`_sidecar_block`** (around line 181): change signature to take `project_dns_label: str` (or refactor to use the `compiled` directly — but the call site at line 332 already passes `project`/`env` individually, so an additional `project_dns_label` parameter is the lightest touch). Update `sidecar_name = f"{project_dns_label}-{env}-{svc.name}-otelcol"`.

3. **`emit_compose` second-pass sidecar loop** (around line 331): same change — `sidecar_name = f"{compiled.project_dns_label}-{compiled.env}-{svc.name}-otelcol"`. Update the call into `_sidecar_block` to pass `compiled.project_dns_label` for the new parameter.

### Step 3 — Patch compose project-tier emit (`src/docex/emit/compose.py::emit_project_compose`)

The signature currently takes `project: str`. We need the DNS-labeled form here too. Two reasonable shapes:

A. Accept a second arg: `def emit_project_compose(*, project: str, project_dns_label: str, out_path: Path)`. The caller in `compile.py` computes the DNS label.

B. Accept only the DNS-labeled form: `def emit_project_compose(*, project_dns_label: str, out_path: Path)`. The raw `project` isn't used anywhere in the body once the leak is fixed.

Prefer option B. Trace `project` references inside the function body and confirm none of them want the raw form — every use is for a docker network/container/volume name, which is data-plane resolvable and must hyphenate. Drop the `project` parameter, accept `project_dns_label` only, and use it for:

- `acme_volume = f"{project_dns_label}-traefik-acme"`
- All four `f"{project_dns_label}-{env}-web"` network entries (both as the dict key and as the `name:` value)
- `f"{project_dns_label}-traefik"` (both as the service key and as `container_name`)
- The `networks:` attachment list inside the traefik service

Update the caller in `compile.py::run_compile` (search for `emit_project_compose(` — two call sites, dev + prod project-tier).

### Step 4 — Patch HCL project-tier emit (`src/docex/emit/templates/project.tf.j2`)

Add a `project_subdomain` variable computed in `hcl.py::emit_hcl_project` and pass it into the template via `tpl.render(...)`:

```python
http_host_p = naming_policies.get("http_host")
project_subdomain = f"{apply_policy(project, http_host_p)}.{apex_domain}"
```

Then in `project.tf.j2`, replace every literal `{{ project }}.{{ apex_domain }}` with `{{ project_subdomain }}`. Touch these specific sites (per grep `"{{ project }}.{{ apex_domain }}"\|{{ project }}.{{ apex`):

- L47 (approx): `aws_route53_zone.project.name`
- L116, L118: stage ACM cert `domain_name` + first SAN
- L132, L134, L135: prod ACM cert `domain_name` + two SANs

Also update any comment blocks that quote `<project>.<apex_domain>` to clarify the DNS-labeled form (cosmetic but keeps docs accurate).

### Step 5 — Patch HCL env-tier emit (`src/docex/emit/templates/main.tf.j2`)

The Service Connect namespace (around line 122):

```hcl
name        = "{{ project }}-{{ env }}"
```

Change to:

```hcl
name        = "{{ project | replace('_', '-') | lower }}-{{ env }}"
```

(Matches the Jinja-filter pattern mod 040 used for the env-tier SG name fix, which keeps the template self-contained without requiring another `tpl.render` arg.)

Comment immediately above can stay; reinforce in the description string too:

```hcl
description = "ECS Service Connect namespace for {{ project | replace('_', '-') | lower }} {{ env }}"
```

(The description string is informational only — AWS doesn't read it for resolution — but consistency reads better in the AWS console.)

### Step 6 — Tests

New file: `tests/unit/test_naming_policy_leak.py`. Two flavors of test:

1. **Compose emit** — instantiate a `CompiledEnv` manually (or via a new lightweight fixture under `tests/fixtures/sample_underscored/`) whose `project` is `my_test_proj`, run `emit_compose`, parse the output YAML, and assert:
   - `networks.web.name == "my-test-proj-dev-web"` (hyphenated)
   - `networks.internal.name == "my-test-proj-dev-internal"`
   - The OTel sidecar's `container_name` for each core service is hyphenated (`my-test-proj-dev-api-otelcol` etc.)

2. **Project-tier compose emit** — call `emit_project_compose` with `project_dns_label="my-test-proj"`, parse the output, assert:
   - All four `my-test-proj-{dev,test,stage,prod}-web` networks exist
   - `services["my-test-proj-traefik"]` exists and has `container_name: my-test-proj-traefik`
   - `volumes["my-test-proj-traefik-acme"]` exists

3. **HCL project-tier emit** — call `emit_hcl_project(project="my_test_proj", ...)`, read the rendered HCL, assert:
   - `name = "my-test-proj.example.com"` appears (Route53 zone)
   - `domain_name = "*.stage.my-test-proj.example.com"` appears (ACM stage)
   - `domain_name = "*.prod.my-test-proj.example.com"` appears (ACM prod)
   - No occurrence of `my_test_proj.example.com` (the bug's form)

4. **HCL env-tier emit** — call `emit_hcl` against a `CompiledEnv` with `project="my_test_proj"`, assert the rendered HCL contains `name        = "my-test-proj-stage"` (Service Connect namespace) and not `my_test_proj-stage`.

### Step 7 — Compile the existing test projects and verify

After patching:

```bash
cd test_projects/fixed && ./bin/docex compile
cd test_projects/elastic && ./bin/docex compile
```

Spot-check via grep:

```bash
grep -rE 'docex_smoke_(fixed|elastic)' test_projects/*/infra/output/ | grep -v '\.terraform' | head -30
```

Expected: every occurrence is in a place where underscores are *correct* per doctrine (ECR repo names `docex_smoke_elastic/web`; IAM role `docex_smoke_elastic_task_execution`; SSM paths `/docex_smoke_elastic/<env>/...`; DDB table `docex_smoke_elastic_tofu_locks`; CloudWatch log group ARN `/<project>/<env>/...`; YAML/HCL comments and `tags` blocks). Any underscored project-segment leak on a data-plane name should be gone.

### Step 8 — Run the full test suite

```bash
cd ~/.claude/jean_baudrillard/docex
python -m pytest -q tests/unit/  # unit pass first
python -m pytest -q tests/integration/  # if integration tests run cleanly in this environment
```

Tests must pass. If any existing test fails because a snapshot now contains hyphens where it previously had underscores, that test was asserting the *bug*; update its expectation. Document any such update at the bottom of this file under "Side effects observed".

## Side effects observed

(Fill in during implementation.)

## Out of scope reminder

- Do NOT touch ECR repo name emission (already correct per mod 030 — structural).
- Do NOT touch IAM/SSM/DDB names (underscore-preserving policies are correct).
- Do NOT change joiners (mod 030 already settled the hyphen-on-data-plane rule).
