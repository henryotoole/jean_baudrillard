# Mod 037 — Elastic Projinfra: Route53 Zone + ACM Certs + Two-Phase Apply

Eighth mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Starts the elastic projinfra rebuild by aligning the Route53 zone and ACM certs with the new doctrine. Three real bugs in the current emission are fixed along the way.

## The Doctrine Changes

From [`projinfra/elastic_route53_zone.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md):

> One hosted zone per project, covering `<project>.<apex_domain>` (e.g., `myproject.example.com`).

From [`projinfra/elastic_acm_certs.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md):

> Two ACM certificates per ALB-using elastic project, both in the project's elastic region (currently `us-east-1`):
>
> 1. **Stage cert** — covers `*.stage.<project>.<apex_domain>`, `stage.<project>.<apex_domain>`.
> 2. **Prod cert** — covers `*.prod.<project>.<apex_domain>`, `prod.<project>.<apex_domain>`, `<project>.<apex_domain>`.

Plus the **two-phase apply** logic in `projinfra up production` (already implemented in `pipeline/bootstrap.py`): if `aws_route53_zone.project` isn't in state, apply only the zone first, print NS records and exit cleanly; otherwise apply everything.

## Three real bugs the current code carries

Surveying `src/docex/emit/templates/project.tf.j2` revealed three departures from the (now-updated) doctrine:

1. **`aws_route53_zone.project.name = "{{ apex_domain }}"`** — should be `"{{ project }}.{{ apex_domain }}"`. The current zone covers the bare apex (e.g. `example.com`), which is wrong — that zone belongs to whoever owns the apex (typically the operator at a registrar), not docex. The project zone covers a project subdomain (`myproject.example.com`), delegated from the parent via NS records.

2. **Single `aws_acm_certificate.project`** with SANs `["*.{{ apex_domain }}", "*.dev.{{ apex_domain }}", "*.test.{{ apex_domain }}", "*.stage.{{ apex_domain }}", "*.www.{{ apex_domain }}"]`. Issues:
   - `dev` and `test` are always fixed-style; they never reach the ALB. ACM should not issue certs covering those.
   - `*.www.<apex>` uses the obsolete `www = prod` convention. The new doctrine drops `www` entirely (it's even on the service-name blacklist).
   - The single cert covers both stage and prod, breaking the "stage and prod cert-separated for blast-radius" doctrine intent.

3. **Single `output "certificate_arn"`** — there should be `stage_cert_arn` and `prod_cert_arn` outputs.

These have been incorrect for a while — but `infra/output/project/...` was never actually applied end-to-end against AWS by anything besides the smoke project's test walk, so the bugs survived. Mod 037 fixes them as part of the broader alignment.

## Concrete file surface

### `src/docex/emit/templates/project.tf.j2`

#### Route53 zone — fix name

```hcl
resource "aws_route53_zone" "project" {
  name = "{{ project }}.{{ apex_domain }}"   # was: "{{ apex_domain }}"
  tags = { ... }
}
```

#### ACM certs — replace single cert with two

Delete the existing `aws_acm_certificate.project` and the single `aws_route53_record.cert_validation` + `aws_acm_certificate_validation.project` block. Replace with:

```hcl
# Stage cert. Two SANs per elastic_acm_certs.md.
resource "aws_acm_certificate" "stage" {
  domain_name = "*.stage.{{ project }}.{{ apex_domain }}"
  subject_alternative_names = [
    "stage.{{ project }}.{{ apex_domain }}",
  ]
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { project = "{{ project }}", env = "stage", managed_by = "doctrine" }
}

# Prod cert. Three SANs: stage and prod ergonomic + bare-project ergonomic.
resource "aws_acm_certificate" "prod" {
  domain_name = "*.prod.{{ project }}.{{ apex_domain }}"
  subject_alternative_names = [
    "prod.{{ project }}.{{ apex_domain }}",
    "{{ project }}.{{ apex_domain }}",
  ]
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { project = "{{ project }}", env = "prod", managed_by = "doctrine" }
}

# Validation records — one set per cert, sharing the same zone.
resource "aws_route53_record" "cert_validation_stage" {
  for_each = {
    for dvo in aws_acm_certificate.stage.domain_validation_options : dvo.domain_name => {
      name = dvo.resource_record_name, record = dvo.resource_record_value, type = dvo.resource_record_type
    }
  }
  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.project.zone_id
}

resource "aws_route53_record" "cert_validation_prod" {
  for_each = { for dvo in aws_acm_certificate.prod.domain_validation_options : ... }
  ...
}

resource "aws_acm_certificate_validation" "stage" {
  certificate_arn         = aws_acm_certificate.stage.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation_stage : r.fqdn]
}

resource "aws_acm_certificate_validation" "prod" {
  certificate_arn         = aws_acm_certificate.prod.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation_prod : r.fqdn]
}
```

#### Outputs

Replace:

```hcl
output "certificate_arn" {
  value = aws_acm_certificate_validation.project.certificate_arn
}
```

with:

```hcl
output "stage_cert_arn" {
  value = aws_acm_certificate_validation.stage.certificate_arn
}

output "prod_cert_arn" {
  value = aws_acm_certificate_validation.prod.certificate_arn
}
```

Leave `zone_id` and `zone_name_servers` unchanged — they were already correct.

### Env-tier `main.tf.j2` — consume per-env cert ARN

`src/docex/emit/templates/main.tf.j2` line ~146 currently reads `data.terraform_remote_state.project.outputs.certificate_arn`. After mod 037, the env reads its per-env cert ARN. The env (`stage` or `prod`) is known at compile time, so the template can render the right output name:

```hcl
{% if env == "stage" %}
certificate_arn = data.terraform_remote_state.project.outputs.stage_cert_arn
{% elif env == "prod" %}
certificate_arn = data.terraform_remote_state.project.outputs.prod_cert_arn
{% endif %}
```

Both the `stage` and `prod` env-tier compiled `main.tf` files now consume their own cert. Dev/test never compile elastic main.tf (they're always fixed).

### `pipeline/bootstrap.py`

The two-phase apply already works — it checks for `aws_route53_zone.project` in state, runs targeted apply if missing, else untargeted. No changes needed in bootstrap. Verify by reading the existing logic and confirming the resource name reference still matches.

Possible touch: the delegation-instructions print probably constructs `<apex>` and prints "NS-delegate `<apex>` to these nameservers". After mod 037, the zone is `<project>.<apex>`, so the instructions should say "NS-delegate `<project>.<apex>` to these nameservers from `<apex>`'s parent." Read the function and update if it's stale.

### Tests

- `tests/integration/test_compile.py`: any assertions on `aws_route53_zone.project` content need updating. New: assert the zone name is `<project>.<apex>`.
- New: assertions on the two ACM certs' domain_name and SANs.
- New: assertions on the two outputs `stage_cert_arn` and `prod_cert_arn`.
- Existing: any test referencing the single `certificate_arn` output → split into the two.
- `tests/unit/test_hcl_emitter.py` / `test_pipeline_bootstrap.py`: if any pin the cert resource name or single-cert assumption, update.

## Ramifications

### Compiled-output diff

Every elastic project's `infra/output/project/production/main.tf` changes:
- `aws_route53_zone.project.name`: `example.com` → `myproject.example.com`.
- `aws_acm_certificate.project` deleted; `aws_acm_certificate.stage` and `aws_acm_certificate.prod` added with new SANs.
- Per-cert validation record blocks added.
- Outputs: `certificate_arn` removed; `stage_cert_arn` and `prod_cert_arn` added.

Every elastic project's env-tier `main.tf` (`stage` and `prod`) changes the data-source key it reads for the cert ARN.

Per campaign-wide deferral, no test-project recompile.

### Operator-visible behavior change

When an operator runs `docex projinfra up production` against an elastic project for the first time after this mod:
- Phase 1 creates the zone for `<project>.<apex>` (was `<apex>`). The NS records the operator must delegate are now for the project subdomain at the parent zone (e.g. NS records for `myproject.example.com` set in the `example.com` zone).
- Phase 2 creates two certs instead of one.

If an existing elastic project was already running with the old single-cert model, the next `projinfra up production` after upgrading would attempt to delete the old cert and create two new ones — that's tofu's planned action. The operator decision earlier in the campaign is "no backwards compatibility, no in-flight consumer projects." Same answer applies here.

### What this mod does NOT touch (yet)

- **Per-project VPC + IGW + subnets + NAT** in `project.tf.j2` lines ~57–160. These are obsolete (master VPC is preinfra per mod 041) but stay in mod 037 — ripped out in mod 041. Mod 037 keeps them so the broader emission keeps compiling.
- **ECR repos and IAM** in `project.tf.j2` lines ~210+. These are project-tier per the doctrine; mods 039 owns refactoring their move.
- **ALB** is currently absent; added by mod 038.

## Operator Decisions

1. **Env-tier cert reference updated in mod 037.** Required for compile to continue working; `certificate_arn` output goes away in this mod.
2. **Delegation-instructions wording updated in `bootstrap.py`.** The zone is now `<project>.<apex>`, so the operator-facing print should say "NS-delegate `<project>.<apex>` from `<apex>`'s parent zone."
3. **No AWS validation-record collision.** Two cert resources in one zone produce disjoint AWS-generated validation CNAMEs; the HCL `for_each` blocks have distinct names.

## What This Mod Is NOT

- **No master VPC removal / preinfra references** — mod 041.
- **No ALB emission** — mod 038.
- **No ECR/IAM project-tier moves** — mod 039.
- **No EC2-traefik variant** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No `docex preinfra` real checks** — mod 042.
