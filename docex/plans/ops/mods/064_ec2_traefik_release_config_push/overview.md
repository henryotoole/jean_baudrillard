# Mod 064 — Release-side traefik dynamic-config render + SSM push

Part of the [ec2_traefik-functional advance](../_advance_ec2_traefik_functional.md).
Bug 3 of 3.

## Problem

For an `ec2_traefik_*` project, the traefik routing config SSM parameter
`/<project>/ec2_traefik/config.yml` is created by projinfra
(`project.tf.j2:448-452`) as a **static empty stub**:

```
http:
  routers: {}
  services: {}
```

The instance's systemd timer syncs that param to `/etc/traefik/dynamic.yml`, and
traefik's file provider serves it. But **nothing in docex ever replaces the stub
with real routes.** `ec2_traefik.md § Config Delivery` documents that
`docex release stage/prod` re-renders the config from the merged stage+prod
state and pushes it via `ssm:PutParameter Overwrite=True` — but that step was
never implemented. Result: traefik has zero routes; every request gets nothing.

Confirmed on real AWS: after `release stage`, the SSM param was still the empty
stub.

## Design

Add a release-side step that, for `ec2_traefik_*` elastic projects, renders the
full traefik dynamic config (routers + services for **every core web-network
service across BOTH stage and prod**) and pushes it to SSM with overwrite. Both
envs go in one config because a **single** traefik instance serves both (see the
two-router `api-prod`/`api-stage` example in `ec2_traefik.md § Routing
Discovery`). Re-rendering the whole thing on every release (regardless of which
env is being released) keeps the config a pure function of compiled state —
idempotent and self-healing.

### Config shape (per `ec2_traefik.md § Routing Discovery`)

For each core service with `"web" in svc.networks`, in each of stage and prod:

```yaml
http:
  routers:
    <svc.name>-<env>:
      rule: "Host(`h1`) || Host(`h2`) || ..."   # from svc.web_hosts
      service: <svc.name>-<env>
      tls:
        certResolver: doctrine
  services:
    <svc.name>-<env>:
      loadBalancer:
        servers:
          - url: "http://<svc.global_name>.<project_dns_label>-<env>:<svc.port>"
```

- `svc.web_hosts` already carries the canonical `<svc>.<env>.<project>.<apex>`
  host plus the bare-env / bare-project alternates for the
  `domain_default_service` — the exact set the ALB path uses for
  `host_header.values` (`emit/hcl.py:622`). Reuse it verbatim so traefik routing
  matches ALB routing.
- Backend URL host = `<svc.global_name>.<project_dns_label>-<env>` — the ECS
  Service Connect FQDN. `global_name` is already
  `<project_dns_label>-<env>-<svc>`; the namespace is `<project_dns_label>-<env>`.
- Only **core** web services route (mirror `emit/hcl.py:1126`
  `_web_core = [s for s in core if "web" in s.networks]`); managed backing
  services on `web` are not proxy targets (`networks.md`).

## Implementation seams

- **New emit module** `src/docex/emit/traefik.py`:
  `render_traefik_dynamic_config(compiled_envs: list[CompiledEnv]) -> str`
  returning the YAML string. Build a dict and `yaml.safe_dump` (pyyaml is
  already a dependency — used to read infra.yml). Deterministic key order.
- **Release step** in `src/docex/pipeline/release.py::_release_elastic`, right
  after `_push_secrets` (line ~253) and before first-release detection. Gate:
  `ctx.infra.reverse_proxy in ("ec2_traefik_eip", "ec2_traefik_pip")`. Steps:
  1. `from docex.cicl.compile import compile_env` and compile `stage` + `prod`
     in-memory (mirror `run_compile` at `compile.py:943`):
     `compile_env(ctx.infra, ctx.transfer_tables, env=e, project_name=ctx.project.name, project_version=ctx.project.version)`.
  2. `yaml = render_traefik_dynamic_config([stage_env, prod_env])`.
  3. `path = f"/{apply_policy(ctx.project.name, ssm_policy)}/ec2_traefik/config.yml"`
     (ssm policy → underscores preserved, matching the projinfra-created param).
  4. `aws.ssm_put_parameter(path, yaml, overwrite=True)`.
  Do this on **dry_run == False** only, and skip on the rollback
  (`skip_migrations`) path is a judgement call — SAFER to still push (rollback
  should restore the older env's routes); but to match `_push_secrets`
  (which DOES run before the skip_migrations branch) push it in the same place,
  i.e. unconditionally after secrets for ec2_traefik projects. Print a
  one-line confirmation like `release: pushed traefik routing config (<n>
  routers) to SSM`.
- Guard: this step must be a **no-op for `alb`** projects (they route via ALB
  listener rules in HCL). Gate strictly on the ec2_traefik variants.

## No doctrine change

`ec2_traefik.md § Config Delivery` and `§ Routing Discovery` already specify this
exactly. mod 064 makes the code match the doctrine. No prose edit.

## Tests

1. **Unit** (`tests/` — new `test_traefik_config.py` or in an existing emit
   test file): call `render_traefik_dynamic_config` over a compiled elastic
   fixture (stage+prod) and assert: a router per core web service per env named
   `<svc>-<env>`; the rule contains each `web_hosts` entry; the service URL is
   `http://<global_name>.<project_dns_label>-<env>:<port>`; `certResolver:
   doctrine`; non-web and backing services absent; output parses as YAML.
2. **Release-level** (`tests/` release test, use the existing fake `AWSClient`
   recorder in `tests/conftest.py`): assert `_release_elastic` for an
   ec2_traefik project calls `ssm_put_parameter` for
   `.../ec2_traefik/config.yml`, and that an `alb` project does NOT.

Real-AWS confirmation is the advance re-walk (task #9): after release, the SSM
param is non-empty and `curl https://web.stage.<zone>/health` returns 200
through traefik.
