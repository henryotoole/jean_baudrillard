# Mod 071 — Implementation steps (bugs 7 + 8)

Align docex code to the already-committed doctrine (ECS clusters are
project-tier). Paths relative to the docex root
(`~/.claude/jean_baudrillard/docex`). Do NOT edit doctrine files. Match
existing code style; read each file fully before editing.

Read first: `overview.md`; `src/docex/emit/hcl.py` (`emit_hcl_project`
~line 1045, `render_ecs_service` ~line 509, the scheduler RunTask
renderer ~line 897); `src/docex/emit/templates/{project.tf.j2,
main.tf.j2, ec2_traefik_user_data.sh.j2}`; `src/docex/pipeline/release.py`
(~line 286); `src/docex/aws/{client.py, boto3_client.py}`.

## Bug 7 — traefik LE route53 needs AWS_REGION (trivial)

In `ec2_traefik_user_data.sh.j2`, the `traefik.service` unit heredoc,
add to the `[Service]` section (alongside `ExecStart`):

```
Environment=AWS_REGION={{ traefik_region }}
Environment=AWS_DEFAULT_REGION={{ traefik_region }}
```

`traefik_region` is already passed to this template (mod 070). This lets
lego's route53 DNS-01 provider resolve the Route53 endpoint. (The user_data
is HCL-escaped wholesale later; these lines contain no `${`, so they pass
through untouched.)

## Bug 8 — ECS clusters → project tier

### 1. Emit context — `emit/hcl.py::emit_hcl_project`

Replace the mod-070 `traefik_ecs_clusters` list with a dict that names
each env's cluster (used by the cluster resources, outputs, the IAM
condition, and the user_data provider list):

```python
ecs_clusters = {
    "stage": apply_policy(f"{project}_stage", ecs_p),
    "prod":  apply_policy(f"{project}_prod", ecs_p),
}
```

Pass `ecs_clusters=ecs_clusters` to BOTH the user_data render and the
`project.tf.j2` render (drop `traefik_ecs_clusters` from both). Compute
unconditionally (all elastic projects get clusters, both reverse_proxy
paths) — it's already computed unconditionally today.

### 2. `project.tf.j2` — cluster resources + outputs + IAM loop

- **Add** two cluster resources (near the other project-tier resources,
  outside any `{% if reverse_proxy %}` gate — all elastic projects get
  them):

```hcl
resource "aws_ecs_cluster" "stage" {
  name = "{{ ecs_clusters.stage }}"
{{ tagblock(standard_tags("project", shape_name="ecs_cluster", descriptor="stage", project=project)) }}
}

resource "aws_ecs_cluster" "prod" {
  name = "{{ ecs_clusters.prod }}"
{{ tagblock(standard_tags("project", shape_name="ecs_cluster", descriptor="prod", project=project)) }}
}
```

- **Add** outputs (wherever the other `output` blocks live):

```hcl
output "ecs_cluster_stage_arn" { value = aws_ecs_cluster.stage.arn }
output "ecs_cluster_prod_arn"  { value = aws_ecs_cluster.prod.arn }
```

- **Update** the mod-070 traefik IAM `ArnEquals ecs:cluster` loop: iterate
  `ecs_clusters.values()` instead of `traefik_ecs_clusters` (same rendered
  ARNs). This block stays inside the ec2_traefik branch.

### 3. `ec2_traefik_user_data.sh.j2` — provider cluster list

The `providers.ecs` `clusters:` loop currently iterates
`traefik_ecs_clusters`. Change to `ecs_clusters.values()`:

```
    clusters:
{% for c in ecs_clusters.values() %}      - {{ c }}
{% endfor %}    exposedByDefault: false
```
(Preserve the exact indentation that produced the correct YAML in mod 070.)

### 4. `main.tf.j2` — drop the env cluster, fix the stale comment

- **Remove** the `aws_ecs_cluster.cluster` resource block (the
  `# ECS cluster` section, ~lines 106-112).
- **Fix the stale namespace comment** (~lines 114-121): it still claims
  the Cloud Map zone is "resolvable VPC-wide so EC2-traefik … can reach
  services by name" — that's the bug-6 misconception. Reword to: the
  namespace provides *mesh-internal* Service Connect resolution only; the
  EC2-traefik path discovers backends via the ECS provider, not this zone
  (see `ec2_traefik.md`). Keep the namespace resource itself unchanged.

### 5. `emit/hcl.py` — env references the project-tier cluster

- `render_ecs_service` (~line 555): replace
  `'  cluster         = aws_ecs_cluster.cluster.id'`
  with
  `f'  cluster         = data.terraform_remote_state.project.outputs.ecs_cluster_{ctx.env}_arn'`.
- Scheduler RunTask renderer (~line 897): replace
  `"    arn      = aws_ecs_cluster.cluster.arn"`
  with
  `f"    arn      = data.terraform_remote_state.project.outputs.ecs_cluster_{ctx.env}_arn"`.

The env `main.tf` already declares `data "terraform_remote_state" "project"`
(it reads vpc_id, task_execution_role_arn, etc.), so these new output refs
resolve. `ctx.env` is `stage`/`prod` (main.tf is stage/prod only).

### 6. `pipeline/release.py` — first-release detector

The cluster now always exists, so `ecs_cluster_exists` can't detect a
first release. Switch to env-service existence (~line 286-293):

```python
ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)
# Mod 071: the cluster is project-tier and always present; a first
# release is one where the env has no ECS services in it yet.
first_release = not aws.ecs_cluster_has_services(cluster_name)
if first_release:
    print(
        f"release: no ECS services in cluster {cluster_name!r} — "
        f"first-time release detected; applying infra before migrate."
    )
```

### 7. `aws/client.py` + `boto3_client.py` — new probe

- `client.py`: add abstract `ecs_cluster_has_services(self, cluster: str) -> bool`
  with a docstring mirroring `ecs_cluster_exists`. Keep `ecs_cluster_exists`
  (leave it; harmless if now unused — grep to confirm no other caller).
- `boto3_client.py`:

```python
def ecs_cluster_has_services(self, cluster: str) -> bool:
    ecs = self._client("ecs")
    try:
        resp = ecs.list_services(cluster=cluster, maxResults=1)
    except ecs.exceptions.ClusterNotFoundException:
        return False
    return bool(resp.get("serviceArns"))
```

(Also update any fake/mock AWS client in tests that implements the
`AWSClient` interface so it satisfies the new abstract method.)

### 8. Teardown ordering (verify, likely no change)

`teardown.sh` (elastic) already destroys env tiers before the project
tier. Clusters are now project-tier, so they're destroyed by the project
`tofu destroy` — after env services are gone. Confirm the walk teardown
still ends clean (an ECS cluster with registered services can't delete,
but env-first ordering removes services first). No code change expected;
flag if the walk shows otherwise.

## Tests

- **Emit (both reverse_proxy paths):**
  - Project HCL contains `aws_ecs_cluster.stage` + `aws_ecs_cluster.prod`
    and the `ecs_cluster_{stage,prod}_arn` outputs.
  - Env (`stage`/`prod`) HCL no longer contains `aws_ecs_cluster.cluster`;
    each `aws_ecs_service` and the scheduler RunTask reference
    `data.terraform_remote_state.project.outputs.ecs_cluster_<env>_arn`.
  - ec2_traefik user_data `traefik.service` unit contains
    `Environment=AWS_REGION=`.
- **release detector:** unit test with a fake AWS client — first release
  when `ecs_cluster_has_services` returns False (apply→migrate order);
  steady-state when True.
- **Fix existing tests** that assert `aws_ecs_cluster.cluster` in env
  output or that stub `ecs_cluster_exists` for detection — rewrite to the
  new resource location / probe. Don't weaken assertions; move them.
- **tofu validate** (offline integration, `test_compile.py`) on both
  `alb` and `ec2_traefik_eip` must stay green.

## Run

From the docex root: full non-integration `pytest` + the offline
`tests/integration/test_compile.py`. All green. Report counts + any
existing tests you rewrote and why.

## Contracts

No core-service contract changes.
