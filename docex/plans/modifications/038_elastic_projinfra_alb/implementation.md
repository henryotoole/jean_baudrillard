# Implementation — Mod 038 — Elastic Projinfra: ALB Project-Tier Move

## Context for fresh-context implementer

You are executing mod 038. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`projinfra/elastic_alb.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_alb.md) — ALB resource list, listener-rules-stay-env-tier rule, project-tier outputs.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Listener-rule priorities: stage in `1000–4999`, prod in `5000–9999`.
- Prod cert is the listener default; stage cert attached via `aws_lb_listener_certificate.project_stage`.
- `subnets` references the per-project `aws_subnet.public` resources for now; mod 041 swaps later. Add a comment at the reference site.

## Step-by-step plan

### Step 1 — Add the ALB set to `project.tf.j2`

Edit `src/docex/emit/templates/project.tf.j2`. After the ACM cert / cert-validation blocks added in mod 037, insert the ALB resources and outputs per [`overview.md § Add to project.tf.j2`](./overview.md#add-to-projecttfj2). Use these exact resource names:

- `aws_security_group.project_alb`
- `aws_lb.project`
- `aws_lb_listener.project_https` — `certificate_arn = aws_acm_certificate_validation.prod.certificate_arn` (prod = default).
- `aws_lb_listener_certificate.project_stage` — points at `aws_acm_certificate_validation.stage.certificate_arn`, attached to `project_https`.
- `aws_lb_listener.project_http` — 80 → 301 redirect to 443.

At the `subnets` reference, add a doctrine-internal comment:

```hcl
# mod 041 will switch this to a master VPC data source.
subnets = aws_subnet.public[*].id
```

Add the six outputs at the bottom of the template (alongside the existing outputs):
- `alb_arn`, `alb_dns_name`, `alb_zone_id`, `alb_https_listener_arn`, `alb_http_listener_arn`, `alb_security_group_id`.

### Step 2 — Compute naming inputs in `emit_hcl_project`

`src/docex/emit/hcl.py:emit_hcl_project` (lines ~755+) currently computes structural names like `state_bucket`, `task_execution_role_name`. Add two more:

```python
alb_p = naming_policies.get("alb")
alb_name    = apply_policy(f"{project}_alb",    alb_p)
alb_sg_name = apply_policy(f"{project}_alb_sg", alb_p)
```

Pass them to the template render: add `alb_name=alb_name, alb_sg_name=alb_sg_name`.

### Step 3 — Delete env-tier ALB resources from `main.tf.j2`

In `src/docex/emit/templates/main.tf.j2`:

- Delete `aws_security_group "alb"` block (lines ~96–105).
- Delete `aws_lb "alb"` block (lines ~128–139).
- Delete `aws_lb_listener "alb_https"` block (lines ~141–159).
- Delete `aws_lb_listener "alb_http_redirect"` block (lines ~161–175).

The "Reverse proxy: one ALB per env" comment block above the ALB is also stale — delete it. The new state: env main.tf has no ALB-defining resources.

### Step 4 — Refactor remaining env-tier references to use remote state

Same file (`main.tf.j2`):

- **Per-network SG ingress** (lines ~74–80): change `source_security_group_id = aws_security_group.alb.id` → `source_security_group_id = data.terraform_remote_state.project.outputs.alb_security_group_id`.
- **Route53 alias records** (lines ~221–237): change every `name = aws_lb.alb.dns_name` and `zone_id = aws_lb.alb.zone_id` → `data...outputs.alb_dns_name` / `data...outputs.alb_zone_id`.

The `data "terraform_remote_state" "project"` block already exists at the top of `main.tf.j2`; no additional data-source plumbing required.

### Step 5 — Refactor listener-rule emit in `hcl.py`

`src/docex/emit/hcl.py:510` currently emits:

```python
out.append('  listener_arn = aws_lb_listener.alb_https.arn')
```

Change to:

```python
out.append('  listener_arn = data.terraform_remote_state.project.outputs.alb_https_listener_arn')
```

### Step 6 — Listener-rule priority namespacing per env

`hcl.py` somewhere assigns the `priority` value for each listener rule (search for `priority` in the listener-rule emission). Currently it's probably a per-service deterministic number. Update so:

- Stage priorities live in `[1000, 4999]`.
- Prod priorities live in `[5000, 9999]`.

Concrete suggested approach: take the existing per-service index `i` (0..N-1) and offset by env:

```python
ENV_PRIORITY_BASE = {"stage": 1000, "prod": 5000}
priority = ENV_PRIORITY_BASE[env] + i
```

That keeps the existing relative ordering within an env, just shifts each env into its band. Find the existing priority allocation site and apply this transform. (Confirm there are no two-rules-on-the-same-priority issues across envs that need explicit guarding — there shouldn't be.)

If the existing allocation already produces unique values, you may still need to band them per env to avoid collision now that stage and prod share the listener. Decide based on what the code currently does.

### Step 7 — Tests

#### `tests/integration/test_compile.py`

For an elastic project's compiled output:

- **Project main.tf** assertions:
  - `aws_security_group.project_alb` present with ingress 80/443 from `0.0.0.0/0`.
  - `aws_lb.project` present, named `${project}-alb`, type `application`, internet-facing.
  - `aws_lb_listener.project_https` present at port 443 with `certificate_arn` referencing the prod cert validation.
  - `aws_lb_listener_certificate.project_stage` present, attached to the HTTPS listener, referencing the stage cert validation.
  - `aws_lb_listener.project_http` present at port 80 with redirect to 443.
  - Outputs `alb_arn`, `alb_dns_name`, `alb_zone_id`, `alb_https_listener_arn`, `alb_http_listener_arn`, `alb_security_group_id` all present.
- **Env main.tf** assertions:
  - No `aws_lb`, `aws_lb_listener`, `aws_security_group "alb"` resources.
  - Per-network SG ingress sources reference `data.terraform_remote_state.project.outputs.alb_security_group_id`.
  - Route53 alias records reference `data...outputs.alb_dns_name` and `.alb_zone_id`.
  - Listener rules reference `data...outputs.alb_https_listener_arn`.
  - Stage env's listener-rule priorities are in `[1000, 4999]`; prod env's are in `[5000, 9999]`.

#### `tests/unit/test_hcl_emitter.py`

- Listener-rule emit asserts the new remote-state reference.
- Priority assignment asserts the env-band offset.

### Step 8 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 9 — Sanity sweeps

```bash
# Env-tier should have no ALB-defining resources left
grep -n 'aws_lb\b\|aws_lb_listener\b\|aws_security_group "alb"' src/docex/emit/templates/main.tf.j2

# Local-reference patterns (deleted) should not appear in env-tier
grep -n 'aws_lb\.alb\|aws_security_group\.alb\b' src/docex/emit/templates/main.tf.j2 src/docex/emit/hcl.py

# Project-tier should be the only home of the ALB
grep -n 'aws_lb\b\|aws_lb_listener\b' src/docex/emit/templates/project.tf.j2

# Remote-state references in expected sites
grep -n 'outputs\.alb_' src/docex/emit/templates/main.tf.j2 src/docex/emit/hcl.py
```

First two sweeps: zero hits in main.tf.j2 and zero local-ref hits anywhere. Third and fourth: hits only in the expected sites.

## Out of scope

- **No master VPC switchover** — mod 041.
- **No ECR / IAM moves** — mod 039.
- **No env-tier remote-state refactor beyond the ALB-adjacent references** — mod 040 may extend remote-state coverage to other resources.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No `release` flow changes** — listener rules still come up with env-tier `tofu apply` per the existing release path.

## Done criteria

- [ ] ALB set added to `project.tf.j2`: SG, LB, two listeners, listener_certificate, six outputs.
- [ ] `emit_hcl_project` computes `alb_name` and `alb_sg_name` and passes to the template.
- [ ] ALB resources deleted from `main.tf.j2`.
- [ ] Per-network SG ingress, Route53 alias, and listener-rule listener_arn all consume remote-state outputs.
- [ ] Listener-rule priorities banded per env (stage 1000–4999, prod 5000–9999).
- [ ] Tests cover all of the above.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.
- [ ] Sanity sweeps clean.

Working tree dirty when finished. Do not commit.
