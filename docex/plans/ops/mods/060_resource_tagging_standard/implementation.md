# Mod 060 — Implementation steps

Implements the tagging standard. **Read `overview.md` first** for the full
shape_name/descriptor map and the three decisions. The canonical standard is
`doctrine/infrastructure/cicl.md § Naming and Tagging` (operator-authored — do
not change it). Repo root: `~/.claude/jean_baudrillard/docex`.

This mod changes BOTH doctrine and docex code. The doctrine edits are mechanical
applications of the operator-approved standard with the exact values given below
— apply them as specified; do not invent new tagging policy.

## 1. Central helper — `src/docex/emit/tags.py` (new)

Single source of truth for every elastic tag block.

```python
"""Standard elastic resource tags. Mod 060. The one place the three
doctrine tag blocks (cicl.md § Naming and Tagging) are formed, so every
emit site and the bootstrap API path agree."""
from __future__ import annotations

def standard_tags(
    tier: str,                  # "prerequisite" | "project" | "environment"
    *,
    shape_name: str,
    descriptor: str,
    project: str | None = None,
    env: str | None = None,
    service: str | None = None,  # "etc" for env-scoped resources
    role: str | None = None,     # "etc" for env-scoped resources
) -> dict[str, str]:
    managed_by = "doctrine-operator" if tier == "prerequisite" else "doctrine"
    tags = {
        "managed_by": managed_by,
        "infra_tier": tier,
        "shape_name": shape_name,
        "descriptor": descriptor,
    }
    if tier == "prerequisite":
        tags["Name"] = f"{shape_name}_{descriptor}"
        return tags
    # project + environment both carry project + Name
    assert project is not None
    tags["project"] = project
    if tier == "project":
        tags["Name"] = f"{project}_{shape_name}_{descriptor}"
        return tags
    # environment
    assert env is not None and service is not None and role is not None
    tags["env"] = env
    tags["service"] = service
    tags["role"] = role
    # Name uses service when it's a real service; falls back to descriptor for
    # env-scoped resources (service == "etc") so Names stay unique (decision 2).
    name_seg = descriptor if service == "etc" else service
    tags["Name"] = f"{project}_{env}_{name_seg}"
    return tags


def render_hcl_tags(tags: dict[str, str], indent: str = "  ") -> str:
    """Render a tags dict as an HCL `tags = { … }` block body line."""
    inner = ", ".join(f'{k} = "{v}"' for k, v in tags.items())
    return f"{indent}tags = {{ {inner} }}"
```

Expose `standard_tags` to Jinja: register it as a global on the environment that
renders `project.tf.j2` / `main.tf.j2` (find where the Jinja `Environment` is
built — likely in `emit/hcl.py` or an emit helper module — and add
`env.globals["standard_tags"] = standard_tags`). In templates, emit with a small
macro or inline loop, e.g.:

```jinja
  tags = {
{%- for k, v in standard_tags("project", shape_name="dns", descriptor="zone", project=project).items() %}
    {{ k }} = "{{ v }}"
{%- endfor %}
  }
```

(Or add a `{% macro tagblock(...) %}` to the templates. Either way, one call per
resource with the map values from overview.md.)

## 2. Envinfra emit — `src/docex/emit/hcl.py`

The 5 Python emit sites currently hand-write
`tags = { project, env, service, role, managed_by="doctrine" }`
(render_task_definition: main + log group + _migrate; render_efs_file_system;
render_scheduled_task). Replace each with `render_hcl_tags(standard_tags("environment", ...))`
using the per-resource shape_name/descriptor from overview.md:

- main task def → `shape_name = "core_service" if svc.is_core else "backing_service"`, `descriptor="task-def"`, service=svc.name, role=svc.role.
- `_migrate` task def → core_service, `migrate-task-def`.
- CloudWatch log group → core_service, `logs`.
- EFS → backing_service, `EFS`.
- scheduled-task invocation role → core_service, `scheduler-role`.

For RDS / ElastiCache / S3 / ECS-service / target-group bodies whose tags come
from `svc.body["tags"]` (populated in `cicl/compile.py`): update the compile-time
population so `svc.body["tags"]` is built via `standard_tags("environment", …)`
with the right shape_name (`backing_service` for rds/elasticache/s3,
`core_service` for the ECS service) and descriptor (RDS/cache/S3/ecs-svc). Find
where `compile.py` sets the per-resource `tags` (the `transfer_tables.md
§ Per-resource (elastic)` block is applied there) and route it through the helper.
`project_tag`/`env_tag` reads elsewhere in hcl.py that pull from
`svc.body["tags"]["project"]` still work (the key remains).

## 3. Env-scoped emit — `src/docex/emit/templates/main.tf.j2`

- ECS cluster → `standard_tags("environment", shape_name="etc", descriptor="ecs-cluster", project, env, service="etc", role="etc")`.
- Service Connect namespace → `service_discovery`, `namespace`, service/role="etc".
- network SG (the `aws_security_group` per network `short`) → `network`,
  `descriptor=short` (the network short name), service/role="etc". This REPLACES
  the current `network = short` tag (descriptor now carries it).

## 4. Projinfra emit — `src/docex/emit/templates/project.tf.j2`

Replace every hand-written `tags = { … }` with the helper, `tier="project"`,
`project=project`, per overview.md's projinfra map. Specifics:
- Route53 zone → dns/zone (was `project`+`managed_by` → now full block; drops nothing it had but gains the block).
- ACM stage/prod cert → cert_manager / `stage-cert` / `prod-cert` (**drop the old `env = "stage|prod"`** — projinfra has no env; the stage/prod distinction now lives in descriptor).
- ALB → reverse_proxy/ALB; ALB SG → reverse_proxy/ALB-SG.
- EC2-traefik: instance→EC2, SG→SG (**drop `purpose=ec2_traefik`**), IAM role→iam-role, log group→logs, SSM param→config, EIP→EIP, ACME EBS→acme-ebs **and keep the resource-local `purpose = "ec2_traefik_acme"`** (append it after the standard block — the helper returns the standard set; add `purpose` as an extra key on that resource only).
- ECR repo → container_registry, `descriptor = svc.name` (per-service differentiation; **drop the old `service` tag** — projinfra block has no service; the service name rides in descriptor + Name).
- task-exec IAM role → etc/exec-role.

Keep the EC2 instance's existing human `Name` only if it conflicts — the helper
now sets `Name=${project}_reverse_proxy_EC2`; drop the old hand-set
`Name = "<proj>-traefik"` (superseded). Note any place that *looked up* the
instance by that old Name (grep; likely none — it's referenced by resource ref).

## 5. Bootstrap state-backend tags — `src/docex/pipeline/bootstrap.py` + `aws/*`

- Add a `tags: dict[str, str] | None = None` param to `AWSClient.s3_create_bucket`
  and `ddb_create_locking_table` (interface in `aws/client.py`, impl in
  `aws/boto3_client.py`: pass `Tagging`/`Tags` to the boto3 calls — S3
  `put_bucket_tagging` after create, DDB `Tags=[…]` on `create_table`).
- In `bootstrap.py`, build tags via `standard_tags("project", shape_name="etc",
  descriptor="tofu-state"|"tofu-locks", project=project)` and pass them.
- Update the fakes used in bootstrap unit tests to accept/record the new kwarg.

## 6. Load-bearing filter migration (the hazard)

- `src/docex/pipeline/preinfra.py`: replace `_MASTER_VPC_TAGS` with the semantic
  set:
  ```python
  _MASTER_VPC_TAGS = {
      "managed_by": "doctrine-operator",
      "infra_tier": "prerequisite",
      "shape_name": "master_network",
  }
  ```
  (NOT `Name` — it's redundant per doctrine.) `find_vpc_by_tags` already matches
  every key, so no API change. Subnet lookups (`tier=public|private`) are
  UNCHANGED. Update the module docstring's tag references.
- `src/docex/emit/templates/project.tf.j2`: the `data "aws_vpc" "master"` `tags`
  filter block → the same three semantic tags. Subnet data sources
  (`tier=public|private`) unchanged.

## 7. Doctrine edits (apply exactly; values from overview.md)

- **`specifics/transfer_tables.md § Per-resource (elastic)`**: replace the old
  `tags = { project, env, service, role, managed_by }` block with the envinfra
  block (`managed_by, infra_tier=environment, shape_name, descriptor, project,
  env, service, role, Name`) and add a sentence pointing at
  `cicl.md § Naming and Tagging` for the full three-block standard and the
  pre/projinfra blocks. Keep the existing `identifier`-shorthand note.
- **`preinfra/elastic_master_network.md`**: rewrite the resource-table tag column
  and the intro sentence to the new scheme (per overview.md preinfra map:
  master_network/* and nat_gateway/{NAT,EIP}; subnets keep `tier`). Rewrite the
  `aws ec2 create-tags`/`--tag-specifications` in the stand-up script to emit
  `managed_by=doctrine-operator, infra_tier=prerequisite, shape_name=…,
  descriptor=…, Name=…` (+ `tier` on subnets). Update "Why these exact tags" to
  describe the new semantic filter (`managed_by`+`infra_tier`+`shape_name`).
  **Add a "Migration from earlier docex" note**: existing master networks were
  tagged `managed_by=docex-preinfra`/`Name=docex-master-*`; re-tag them with
  `aws ec2 create-tags` to the new keys/values before running this docex version,
  or `preinfra`/`projinfra` won't find the VPC.
- **`preinfra/telemetry_preinfra.md`**: change the observability-backend EC2+EBS
  tags to the preinfra block (`shape_name=observability_backend`,
  `descriptor=EC2|EBS`, `managed_by=doctrine-operator`, `infra_tier=prerequisite`,
  `Name`). Repoint the duplicate-instance guard from the old
  `prerequisite-infrastructure-telemetry` tag to the new
  `shape_name=observability_backend` (+ `managed_by=doctrine-operator`) match.
- **`specifics/projinfra/*.md`**: in each of `elastic_route53_zone.md`,
  `elastic_alb.md`, `elastic_acm_certs.md`, `elastic_ecr.md`, `elastic_iam.md`,
  `elastic_state_backend.md`, `ec2_traefik.md`, update any "Tags follow the
  doctrine-wide pattern from transfer_tables.md § Per-resource (elastic)" (or
  similar) to point at `cicl.md § Naming and Tagging` (projinfra block), and note
  where Route53/old-5-tag resources **drop `env`/`service`/`role`**. Keep the
  `purpose=ec2_traefik_acme` note in `ec2_traefik.md`.

## 8. Tests

- `tests/unit/test_tags.py` (new): `standard_tags` per tier — key set + values;
  preinfra has no project/env/service/role; the `service=etc` Name fallback uses
  descriptor; per-service Name uses service.
- Emit assertions: extend the HCL/compose emit tests so a representative resource
  in each tier carries the right block (e.g. assert the ECS cluster has
  `infra_tier="environment"`, `shape_name="etc"`, `service="etc"`,
  `Name="…_ecs-cluster"`; an RDS/EFS has `shape_name="backing_service"`; the
  Route53 zone has `infra_tier="project"`, `shape_name="dns"`, no `env`; ACM certs
  carry descriptor `stage-cert`/`prod-cert` and NO `env`; the ACME EBS keeps
  `purpose="ec2_traefik_acme"`; ECR descriptor == service name).
- Filter test: `preinfra.py`'s `_MASTER_VPC_TAGS` is the new semantic set; a fake
  AWS client returns the VPC only when queried with those tags.
- bootstrap test: S3/DDB creation passes the projinfra `etc`/tofu-state|locks tag
  set.
- Update any existing test asserting the OLD tag shape (e.g. tests checking
  `managed_by="docex-preinfra"`, the SG `network=` tag, the ACM `env=` tag, the
  5-tag envinfra block) to the new shape.

## 9. Smoke seeds (test_projects)

The smoke projects' **master network is operator-managed** (not in the seed), so
no seed file changes there — but flag in the report that the smoke walk must
re-tag its master network per the new `elastic_master_network.md` before
`preinfra production` will pass. If the seeds carry any compiled `infra/output/**`
with old tag blocks, leave them (they're regenerated by `compile`); do not
hand-edit committed seed output.

## 10. Verify

- `pytest -m "not integration"` green (helper + emit + filter + bootstrap tests).
- `python -m docex compile` against the two smoke projects (or scratch projects on
  each foundation); eyeball `infra/output/**/main.tf` + `project/production/main.tf`
  for the three blocks on representative resources and the new VPC data-source
  filter. Revert any regenerated smoke output so the tree stays clean.
- Report: every file changed, test counts, the compile spot-check, and confirm the
  master-VPC filter (preinfra.py + project.tf.j2) and the bootstrap tags all use
  the new scheme. Call out anything in this plan that was inaccurate.
