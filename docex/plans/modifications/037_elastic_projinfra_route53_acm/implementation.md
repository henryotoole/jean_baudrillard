# Implementation — Mod 037 — Elastic Projinfra: Route53 Zone + ACM Certs + Two-Phase Apply

## Context for fresh-context implementer

You are executing mod 037 of a 16-mod docex advance. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`projinfra/elastic_route53_zone.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md) — zone spec, two-phase apply rationale.
- [`projinfra/elastic_acm_certs.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md) — exact SAN sets for stage and prod certs.
- [`cicl.md § TLS Implications`](../../../../doctrine/infrastructure/cicl.md#tls-implications) — the broader three-cert system (dev cert lives elsewhere; this mod only emits the two ACM-issued certs).

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Env-tier cert reference updated in mod 037.
- `bootstrap.py` delegation-instructions wording updated to reference `<project>.<apex>`.
- No special handling for cert-validation-record collisions (none expected).

## Step-by-step plan

### Step 1 — Fix Route53 zone name

Edit `src/docex/emit/templates/project.tf.j2`. Find the `resource "aws_route53_zone" "project"` block (around line 45). Change:

```hcl
name = "{{ apex_domain }}"
```

to:

```hcl
name = "{{ project }}.{{ apex_domain }}"
```

Update the leading comment block above the resource to describe the project subdomain (not the apex) and the parent-zone NS-delegation requirement.

### Step 2 — Replace the single ACM cert with two

In the same file, find the `aws_acm_certificate.project` block (around line 169) plus its paired `aws_route53_record.cert_validation` and `aws_acm_certificate_validation.project` blocks. Delete all three.

Replace with two cert pairs — stage and prod — each with its own cert resource, validation-records `for_each` block, and validation resource. See [`overview.md § ACM certs — replace single cert with two`](./overview.md#acm-certs--replace-single-cert-with-two) for the exact HCL shape.

Use distinct resource names:
- `aws_acm_certificate.stage` and `aws_acm_certificate.prod`
- `aws_route53_record.cert_validation_stage` and `aws_route53_record.cert_validation_prod`
- `aws_acm_certificate_validation.stage` and `aws_acm_certificate_validation.prod`

Update the leading comment block to describe the two-cert split and which env each cert covers.

### Step 3 — Update outputs

Delete:

```hcl
output "certificate_arn" {
  value = aws_acm_certificate_validation.project.certificate_arn
}
```

Add:

```hcl
output "stage_cert_arn" {
  value = aws_acm_certificate_validation.stage.certificate_arn
}

output "prod_cert_arn" {
  value = aws_acm_certificate_validation.prod.certificate_arn
}
```

Keep `zone_id` and `zone_name_servers` unchanged — they were already correct.

### Step 4 — Update env-tier `main.tf.j2` cert ARN reference

Edit `src/docex/emit/templates/main.tf.j2`. Find line ~146 referencing `data.terraform_remote_state.project.outputs.certificate_arn`. Replace with the per-env output, branching on the compile-time `env` variable:

```hcl
{% if env == "stage" %}
certificate_arn = data.terraform_remote_state.project.outputs.stage_cert_arn
{% elif env == "prod" %}
certificate_arn = data.terraform_remote_state.project.outputs.prod_cert_arn
{% endif %}
```

Verify the `env` variable is in the template's render context (it almost certainly is — `_env_subdomain` uses it). If not, pass it explicitly through the `emit_hcl` Python call site.

### Step 5 — Update `pipeline/bootstrap.py` delegation-instructions

Read `src/docex/pipeline/bootstrap.py:_print_delegation_instructions` (line ~169). The current message likely says something like "NS-delegate `<apex_domain>`...". Update to:

> NS-delegate `<project>.<apex_domain>` to these nameservers by setting NS records in the parent zone (`<apex_domain>`) at your registrar or DNS provider.

The function signature takes `project_dir, project, apex_domain`. Construct the project-subdomain string from `project` + `apex_domain` and use it in the print message.

### Step 6 — Update tests

#### `tests/integration/test_compile.py`

Find every test that asserts on the project's `main.tf` content. Search:

```bash
grep -n 'aws_route53_zone\|aws_acm_certificate\|certificate_arn' tests/integration/test_compile.py
```

For each hit:

- **Zone name**: assert `aws_route53_zone.project.name` equals `"{project}.{apex}"`. Don't keep old assertions on the bare-apex form.
- **Certs**: replace any single-cert assertion with two assertions — one for `aws_acm_certificate.stage` with domain_name `*.stage.{project}.{apex}` and SANs `[stage.{project}.{apex}]`, one for `aws_acm_certificate.prod` with domain_name `*.prod.{project}.{apex}` and SANs `[prod.{project}.{apex}, {project}.{apex}]`.
- **Outputs**: assert both `output "stage_cert_arn"` and `output "prod_cert_arn"` are present; the old `output "certificate_arn"` is absent.
- **Env-tier cert reference**: assert the stage env's compiled main.tf references `outputs.stage_cert_arn`; prod references `outputs.prod_cert_arn`.

#### `tests/unit/test_hcl_emitter.py` and `tests/unit/test_pipeline_bootstrap.py`

Sweep for any pinning of the old cert resource name or output. Update accordingly. The bootstrap two-phase apply logic itself doesn't change; only the delegation-instruction print string changes.

#### Possible new test

A unit test that exercises `_print_delegation_instructions` with sample inputs and asserts the new project-subdomain wording. Simple stdout capture via `capsys`.

### Step 7 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 8 — Sanity sweeps

```bash
# Old single-cert references should be gone everywhere except deliberate references
grep -rn 'certificate_arn[^_]\|aws_acm_certificate\.project\b' src/ tests/

# New cert names should appear in the expected sites only
grep -rn 'stage_cert_arn\|prod_cert_arn\|aws_acm_certificate\.stage\|aws_acm_certificate\.prod' src/ tests/

# Zone name in template now includes project segment
grep -rn 'aws_route53_zone' src/docex/emit/templates/
```

First sweep: no hits (the only legitimate ones might be CHANGELOG history references — those are fine, they were committed by earlier mods).

Second sweep: hits only in the template, tests, and any remote-state outputs reading code.

Third sweep: confirm `name = "{{ project }}.{{ apex_domain }}"` appears.

## Out of scope

- **No removal of per-project VPC / IGW / NAT / subnets** in `project.tf.j2` — mod 041 owns that as part of "master VPC as preinfra" migration.
- **No ECR / IAM moves** — mod 039.
- **No ALB emission** — mod 038.
- **No env-tier remote-state refactor beyond the cert ARN reference** — mod 040.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No new `output` other than `stage_cert_arn` / `prod_cert_arn` and the existing zone/VPC/etc outputs.**

## Done criteria

- [ ] `aws_route53_zone.project.name` = `<project>.<apex>` in `project.tf.j2`.
- [ ] Single cert replaced with two (stage + prod) with the doctrine-spec SANs.
- [ ] Validation record blocks split per cert with distinct HCL resource names.
- [ ] `certificate_arn` output replaced with `stage_cert_arn` + `prod_cert_arn`.
- [ ] Env-tier `main.tf.j2` consumes the per-env cert ARN.
- [ ] `bootstrap.py` delegation-instructions message updated to reference `<project>.<apex>` and the parent zone.
- [ ] Tests cover the new zone name, both cert resources, both outputs, env-tier per-env cert reference, updated delegation print.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.
- [ ] Sanity sweeps clean.

Working tree dirty when finished. Do not commit.
