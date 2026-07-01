# Mod 064 — Implementation steps

Implements bug 3 of the [ec2_traefik campaign](../_campaign_ec2_traefik_functional.md):
render the traefik dynamic routing config at release time and push it to SSM.
Read [`overview.md`](./overview.md) for rationale + the config shape. Self-contained.

Runtime notes:
- `docex` runs from source with `PYTHONPATH=src` (not pip-installed). Tests:
  `cd ~/.claude/jean_baudrillard/docex && PYTHONPATH=src python3 -m pytest ...`.
- Change ONLY these files: `src/docex/emit/traefik.py` (new),
  `src/docex/pipeline/release.py`, and a test file under `tests/`. Do not touch
  templates, doctrine, or the version artifacts. Do not commit.

## Step 1 — New emit module `src/docex/emit/traefik.py`

`render_traefik_dynamic_config(compiled_envs: list[CompiledEnv]) -> str`:

- For each `CompiledEnv` in `compiled_envs`, for each service where
  `svc.is_core and "web" in svc.networks`:
  - router key `f"{svc.name}-{compiled.env_name}"` (confirm the env-name field on
    `CompiledEnv`; it is the compiled env's name — check the dataclass in
    `cicl/compile.py` around line 447, use whatever holds `"stage"`/`"prod"`).
  - `rule` = `" || ".join(f"Host(\`{h}\`)" for h in svc.web_hosts)` (backticks are
    literal in the traefik rule).
  - router body: `{rule, service: <same key>, tls: {certResolver: "doctrine"}}`.
  - service body: `{loadBalancer: {servers: [{url:
    f"http://{svc.global_name}.{compiled.project_dns_label}-{compiled.env_name}:{svc.port}"}]}}`.
- Assemble `{"http": {"routers": {...}, "services": {...}}}` and
  `yaml.safe_dump(..., sort_keys=True)` (deterministic). Return the string.
- `import yaml` (pyyaml is already a dependency).
- If there are zero core web services across all envs, return the empty stub
  `"http:\n  routers: {}\n  services: {}\n"` (matches the projinfra default).

Verify the exact `CompiledEnv` field names first by reading
`src/docex/cicl/compile.py` (`class CompiledEnv`, ~line 447: `project_dns_label`
is confirmed; find the env-name field) and `class CompiledService` (~line 400:
`name`, `is_core`, `global_name`, `networks`, `port`, `web_hosts` are confirmed).

## Step 2 — Push in `_release_elastic`

In `src/docex/pipeline/release.py::_release_elastic`, immediately AFTER the
`_push_secrets(...)` call + its print (currently ~line 252-253) and BEFORE the
`skip_migrations` branch, add:

```python
# ec2_traefik routing config: the single project traefik instance serves
# stage AND prod, so re-render both envs' web routes and push to the SSM
# param the instance's sync timer reads. alb projects route via HCL
# listener rules and need none of this. See ec2_traefik.md § Config Delivery.
rp = ctx.infra.reverse_proxy
if rp in ("ec2_traefik_eip", "ec2_traefik_pip"):
    from docex.cicl.compile import compile_env
    from docex.emit.traefik import render_traefik_dynamic_config
    envs = [
        compile_env(
            ctx.infra, ctx.transfer_tables, env=e,
            project_name=project_name, project_version=ctx.project.version,
        )
        for e in ("stage", "prod")
    ]
    cfg_yaml = render_traefik_dynamic_config(envs)
    ssm_policy = ctx.transfer_tables.naming_policies.get("ssm_path")
    cfg_path = f"/{apply_policy(project_name, ssm_policy)}/ec2_traefik/config.yml"
    n_routers = cfg_yaml.count("certResolver")
    try:
        aws.ssm_put_parameter(cfg_path, cfg_yaml, overwrite=True)
    except Exception as e:
        raise SSMPushFailed(
            f"failed pushing traefik config to {cfg_path!r}: {e}"
        ) from e
    print(f"release: pushed traefik routing config ({n_routers} router(s)) to SSM")
```

- `apply_policy` is already imported in release.py (used for the cluster name).
  If not, import from `docex.naming`.
- `SSMPushFailed` is already imported/defined in release.py (used by
  `_push_secrets`). Reuse it.
- Place it so it runs on the normal AND the `skip_migrations` (rollback) path —
  i.e. before the `if skip_migrations:` block — mirroring `_push_secrets`. It is
  correctly skipped on `dry_run` because the `dry_run` block returns earlier.

## Step 3 — Tests

Add `tests/integration/test_traefik_config.py` (or extend an emit test):

1. Compile the elastic fixture stage+prod in-memory (see how
   `tests/integration/test_compile.py` builds contexts, or call
   `compile_env` directly with a loaded `ctx.infra`/`ctx.transfer_tables`).
   Assert `render_traefik_dynamic_config([stage, prod])`:
   - parses as YAML; has `http.routers` and `http.services`.
   - contains routers `web-stage` and `web-prod` (the fixture's core web
     service is `web`); NOT `worker-*` (worker isn't on web) nor backing
     services (`appdb`/`probe`/`events`).
   - `web-prod` rule contains the bare-project host
     `docex-smoke-elastic.luxrnd.tech` (domain_default_service alternate) and
     `web-stage` contains `web.stage.docex-smoke-elastic.luxrnd.tech`.
   - service URL for `web-stage` ==
     `http://docex-smoke-elastic-stage-web.docex-smoke-elastic-stage:8080`.
   - every router has `certResolver: doctrine`.

2. Release-level (use the fake `AWSClient` recorder in `tests/conftest.py`):
   - an ec2_traefik project's `_release_elastic` records a
     `ssm_put_parameter` call whose name ends `/ec2_traefik/config.yml`.
   - an `alb` project's does NOT. (Look at how existing release tests inject the
     fakes / stub tofu runners; mirror them. If wiring a full `_release_elastic`
     test is heavy, at minimum unit-test the gating predicate + path
     construction.)

## Step 4 — Run

```bash
cd ~/.claude/jean_baudrillard/docex
PYTHONPATH=src python3 -m pytest tests/unit tests/integration -q -m 'not integration'
```
All must pass (baseline is 629 in the fast suite; your new tests add to that).

## Definition of done

1. `emit/traefik.py` renders correct YAML for core web services across stage+prod.
2. `_release_elastic` pushes it for ec2_traefik projects, no-op for alb.
3. New tests pass; full fast suite green.
4. No changes outside the three allowed files; nothing committed.
