# Mod 040 — Env-Tier SG Name Hyphen Fix

Eleventh mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Closes a residual data-plane naming leak missed by mod 030: the env-tier security-group AWS-side `name` field still uses underscores in `main.tf.j2`.

## Scope shrunk substantially

The advance list's original mod 040 was framed as a broad env-tier HCL refactor: add `data "terraform_remote_state" "project"` block, per-web-service listener rules + target groups referencing the project ALB by ARN, env web SG ingress source = project ALB SG via remote state, allow-all egress on every emitted SG. **All four bullets already landed naturally as side effects of mods 037, 038, and existing mod-006 egress work.**

Auditing what's currently in env-tier `main.tf` against the original mod 040 brief:

| Bullet | Status | Where it landed |
| ------ | ------ | --------------- |
| `data "terraform_remote_state" "project"` block | ✓ already there | pre-existing; line 38 of `main.tf.j2` |
| Per-web-service `aws_lb_listener_rule` + `aws_lb_target_group` referencing project ALB ARN | ✓ done | mod 038 (`hcl.py:510` listener_arn now via remote state) |
| Env-banded listener-rule priorities | ✓ done | mod 038 (stage 1000-, prod 5000-) |
| Env web SG ingress source = project ALB SG via remote state | ✓ done | mod 038 (line 80 `source_security_group_id`) |
| Allow-all egress on every emitted env SG | ✓ done | mod 006 + mod 038 (`main.tf.j2:59-64`) |

That leaves a single concrete leftover: the env-tier SG `name` field at `main.tf.j2:52` is still composed with literal underscores:

```hcl
resource "aws_security_group" "{{ short }}" {
  name = "{{ project }}_{{ env }}_{{ short }}"   # <- still underscored
  ...
}
```

[`networks.md § Compiled Names`](../../../../doctrine/infrastructure/specifics/networks.md#compiled-names) says explicitly:

> Networks are given short, meaningful names in `infra.yml` like `web`, `internal`, etc. The compiler scopes those names by project and env on both foundations:
> ```
> ${project_name}-${env_name}-${network_definition_name}
> ```
> The same form applies whether the underlying resource is a Docker network (fixed) or an AWS security group (elastic). There are no special exceptions — `web` compiles to `${project}-${env}-web` just like any other network.

Mod 030 unified the docker side (the compose `_network_section` now emits hyphens). The elastic HCL side was not touched by mod 030 — it still uses literal underscores in the template. Mod 040 closes the gap.

## The change

### `src/docex/emit/templates/main.tf.j2:52`

Replace:

```hcl
name = "{{ project }}_{{ env }}_{{ short }}"
```

with:

```hcl
name = "{{ project | replace('_', '-') }}-{{ env }}-{{ short }}"
```

The `replace('_', '-')` filter handles project names with underscores (e.g. `docex_smoke_elastic` → `docex-smoke-elastic`). The `env` value is one of `dev`/`test`/`stage`/`prod` (no underscores possible). The `short` value is the CICL network short-name (e.g. `web`, `internal`) — also no underscores by convention.

Alternative formulation: pass a `dns_label_project` template variable from the Python side (computed via `_dns_label(project)` reused from compile.py), keeping all underscore-translation in Python. Either approach works; I'd lean toward the Jinja filter for locality (the substitution is right there at the use site).

### Sanity sweep — find similar leaks

While we're here, sweep for any other env-tier emission sites that compose names with literal `_` joiners:

```bash
grep -n '"{{ project }}_\|{{ project }}_{{ env }}' src/docex/emit/templates/
```

If any hits emerge beyond the SG name, evaluate them — are they hyphen-required (data-plane) or underscore-OK (IAM/SSM/DDB)?

### Tests

`tests/integration/test_compile.py` — find any assertion on the env-tier SG name and flip from underscore to hyphen form.

```bash
grep -n 'project.*_.*_.*"web"\|project.*_.*_.*"internal"' tests/integration/test_compile.py
```

Or more broadly, any assertion that pins the SG name:

```bash
grep -n 'aws_security_group "web\|aws_security_group "internal' tests/
```

The implementer should run the sweep and flip whatever matches.

## What This Mod Is NOT

- **No env-tier listener rule changes** — already done by mod 038.
- **No new project-tier resources** — that's other mods.
- **No master VPC switchover** — mod 041.
- **No env-tier task definition changes** — already consumes project-tier remote state.
- **No `test_projects/{fixed,elastic}/` edits.**

## Operator Decisions Needed

1. **Jinja filter vs. Python variable** — implementer's call. Either `{{ project | replace('_', '-') }}-{{ env }}-{{ short }}` in the template, or precompute `dns_label_project` in `emit_hcl` and pass it. I'd lean filter for locality. Confirm or leave to implementer discretion.

## Why This Is Its Own Mod

The fix is small (one line + tests), and could in principle ride along with mod 041's larger refactor. Keeping it as its own mod has three benefits:
1. Honors the advance list's published numbering.
2. Surfaces a real bug (env-tier SG names didn't match the doctrine's stated unification) cleanly in `git blame` / CHANGELOG.
3. Mod 041 is large enough (VPC → master VPC preinfra switchover); keeping orthogonal concerns separate reduces review surface.

If the operator prefers, this could fold into mod 041. The doctrine has no hard rule against it.
