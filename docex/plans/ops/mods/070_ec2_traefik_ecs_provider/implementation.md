# Mod 070 — Implementation steps

Align docex code to the already-committed Path-B doctrine. Paths are
relative to the docex root (`~/.claude/jean_baudrillard/docex`). Do NOT
edit doctrine files. Match existing code style.

Read `overview.md` first. Read these files before changing them:
`src/docex/emit/hcl.py` (`emit_hcl_project` ~line 1045; `render_task_definition`
~line 300), `src/docex/emit/templates/ec2_traefik_user_data.sh.j2`,
`src/docex/emit/templates/project.tf.j2`, `src/docex/pipeline/release.py`
(~line 251), `src/docex/emit/traefik.py`.

## 1. Task-definition labels — `emit/hcl.py::render_task_definition`

After `container_def` is built (and before the OTel sidecar block is
fine), add the traefik labels when the service is an ec2_traefik web
target. Insert:

```python
# Mod 070: on the ec2_traefik path, the project traefik discovers routes
# from these container labels via its ECS provider (the elastic analog of
# the fixed docker provider). No labels on the alb path — it routes via
# listener rules. Web-network core services with a port only.
if (
    ctx.reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip")
    and "web" in svc.networks
    and svc.port is not None
    and svc.web_hosts
):
    key = f"{svc.name}-{ctx.env}"
    rule = " || ".join(f"Host(`{h}`)" for h in svc.web_hosts)
    container_def["dockerLabels"] = {
        "traefik.enable": "true",
        f"traefik.http.routers.{key}.rule": rule,
        f"traefik.http.routers.{key}.entrypoints": "websecure",
        f"traefik.http.routers.{key}.tls.certresolver": "doctrine",
        f"traefik.http.routers.{key}.service": key,
        f"traefik.http.services.{key}.loadbalancer.server.port": str(svc.port),
    }
```

Notes:
- `svc.web_hosts` is the same list the ALB listener rule uses (`hl.py`
  ~line 633). Confirm it is populated for web-network services regardless
  of `reverse_proxy` (it is a property of the service, not the proxy). If
  you find it gated on the alb path, un-gate it so ec2_traefik gets the
  same hosts.
- Values must all be strings (`str(svc.port)`), since they land in
  `jsonencode`.
- The labels contain backticks and `||` but no `${`, so the existing HCL
  jsonencode path is safe. Do not add these to the `_migrate` container
  or the sidecar — main app container only.

## 2. user_data static config — `ec2_traefik_user_data.sh.j2`

**Replace** the `providers:` block (currently `providers.file`):

```yaml
providers:
  ecs:
    region: {{ traefik_region }}
    autoDiscoverClusters: false
    clusters:
{% for c in traefik_ecs_clusters %}      - {{ c }}
{% endfor %}      exposedByDefault: false
    refreshSeconds: 15
```
(Fix indentation so `exposedByDefault`/`refreshSeconds` sit under `ecs:`,
not under the loop — verify the rendered YAML by eye. `exposedByDefault`
and `refreshSeconds` are siblings of `clusters`/`region` under `ecs:`.)

**Delete** entirely:
- The `# --- Initial dynamic config ... dynamic.yml` heredoc block.
- The `# --- systemd timer that syncs dynamic.yml from SSM` section:
  the `docex-traefik-config-sync` script, `docex-traefik-config.service`,
  and `docex-traefik-config.timer` heredocs.
- In the traefik.service unit, remove `docex-traefik-config.service` from
  the `After=` line (leave `network-online.target`).
- In the "start everything" section: the
  `systemctl enable --now docex-traefik-config.timer` line, the
  synchronous `/usr/local/bin/docex-traefik-config-sync || true` line, and
  its comment.

Keep everything else (EBS attach, IMDSv2 token dance, CloudWatch agent,
PIP DNS-update unit, traefik install, traefik.service, log agent).

## 3. Inject the provider context — `emit/hcl.py::emit_hcl_project`

At the user_data render site (~line 1056), add two context vars. Fetch
the `ecs` naming policy the same way the other policies are fetched in
this function (e.g. `ecs_p = policies.get("ecs")` — match the local var
name convention already used for `s3_p`, `alb_p`, etc.):

```python
traefik_user_data = ud_tpl.render(
    project=project,
    project_subdomain=project_subdomain,
    apex_domain=apex_domain,
    reverse_proxy=rp,
    traefik_acme_email=acme_email,
    traefik_region=ELASTIC_REGION,
    traefik_ecs_clusters=[
        apply_policy(f"{project}_stage", ecs_p),
        apply_policy(f"{project}_prod", ecs_p),
    ],
)
```

The `${` → `$${` escaping that follows (line ~1073) still applies
wholesale and is harmless here (the provider block has no `${`).

## 4. IAM — `project.tf.j2`

In `aws_iam_role_policy.project_traefik`:
- **Remove** the `ssm:GetParameter` / `ssm:GetParameters` statement
  (routing no longer lives in SSM).
- **Add** two read-only statements (see overview § IAM). Use `{{ region }}`
  and `${data.aws_caller_identity.current.account_id}` (both already used
  in this file) and a new `{{ traefik_ecs_clusters }}` context list for
  the cluster ARNs:

```hcl
      {
        # Cluster-scoped discovery for the traefik ECS provider.
        Effect   = "Allow"
        Action   = [
          "ecs:ListTasks",
          "ecs:DescribeTasks",
          "ecs:DescribeServices",
          "ecs:DescribeContainerInstances",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "ecs:cluster" = [
{% for c in traefik_ecs_clusters %}              "arn:aws:ecs:{{ region }}:${data.aws_caller_identity.current.account_id}:cluster/{{ c }}",
{% endfor %}            ]
          }
        }
      },
      {
        # Unscopeable read-only discovery calls (AWS permits no resource-
        # level scoping on these).
        Effect   = "Allow"
        Action   = [
          "ecs:ListClusters",
          "ecs:DescribeClusters",
          "ecs:DescribeTaskDefinition",
          "ec2:DescribeInstances",
        ]
        Resource = "*"
      },
```
(Keep the route53, logs, EBS statements as-is.)

- **Remove** the `aws_ssm_parameter.project_traefik_config` resource
  block entirely (the `# SSM Parameter that holds traefik's dynamic-config`
  block).

Pass `traefik_ecs_clusters` into the `project.tf.j2` render call (the
`tpl.render(...)` at ~line 1077) — the same list computed in step 3.
Guard: it's only meaningful on the ec2_traefik path, but passing it
unconditionally is fine (the template only references it inside the
ec2_traefik branch). Compute it once and use for both renders.

## 5. Release — `pipeline/release.py`

Remove the entire `ec2_traefik` SSM-push block (the `rp = ctx.infra.reverse_proxy`
… `print(f"release: pushed traefik routing config ...")` section, ~lines
255–280). Release no longer pushes traefik config. Remove any now-unused
imports (`render_traefik_dynamic_config`; `SSMPushFailed` only if it is
used nowhere else — check first). Leave `_push_secrets` and everything
else intact.

## 6. Remove dead code — `emit/traefik.py`

Delete `src/docex/emit/traefik.py` (its only caller was release.py).
Delete its test module (search `tests/` for `render_traefik_dynamic_config`
/ `traefik` unit tests and remove the ones that test the removed function).

## 7. Tests

- **Fix the stale mod-062 test** `tests/integration/test_compile.py::test_mod062_traefik_user_data_hcl_escaped_eip`:
  it asserts `"$(curl -sf http://169.254.169.254" in tf`. Mod 065 moved
  metadata fetches to IMDSv2 token curls, so update the assertion to
  match the current form (e.g. assert the token PUT
  `$(curl -sf -X PUT "http://169.254.169.254/latest/api/token"` appears,
  or drop the bash-command-substitution-specific assertion and keep the
  escaping assertions). Keep the mod-062 escaping regression intact.
- **Remove/replace** tests that asserted the SSM push or the `dynamic.yml`
  file / config-sync timer in user_data.
- **Add** emit tests:
  - Web-network core service on `ec2_traefik_eip` compiles a task
    definition whose container `dockerLabels` include `traefik.enable`,
    a router `rule` matching the service's `web_hosts`, `service=<svc>-<env>`,
    and the loadbalancer port. Router key is `<svc>-<env>`.
  - The same service on `reverse_proxy: alb` has **no** `traefik.` labels.
  - user_data on the ec2_traefik path contains `providers:` → `ecs:` with
    both cluster names and `exposedByDefault: false` / `refreshSeconds: 15`,
    and does **not** contain `docex-traefik-config` or `dynamic.yml`.
  - The project HCL IAM policy contains the ECS discovery actions and no
    longer contains `ssm:GetParameter`; `aws_ssm_parameter.project_traefik_config`
    is absent from the project HCL.

Use the existing elastic-compile test helpers (e.g.
`_compile_elastic_with_reverse_proxy` in `tests/integration/test_compile.py`)
where they fit.

## 8. Run the suite

From the docex root, run the full non-integration suite plus the
`test_compile.py` integration compile tests (these are offline-pure — no
AWS/docker boundary, safe to run locally). All must pass, including the
now-fixed mod-062 test. `-m integration` tests that require real docker/AWS
are out of scope for local execution — but the `test_compile.py` compile
assertions do run offline; confirm they pass.

## Contracts

No core-service contract changes.
