# Implementation — Mod 036 — Fixed Projinfra: Per-Project Traefik + Behavior

## Context for fresh-context implementer

You are executing mod 036 of a 16-mod docex advance. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`projinfra/fixed_reverse_proxy.md`](../../../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md) — the per-project traefik resource spec (cert resolver, networks, acme volume, command-line flags).
- [`projinfra/projinfra.md`](../../../../doctrine/infrastructure/specifics/projinfra/projinfra.md) — `projinfra <direction> <side>` command behavior, including the env-still-up refusal.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Traefik image pinned by digest via a new `TRAEFIK_IMAGE` constant.
- Single-machine only; no ansible-at-project-tier in mod 036.
- DNS-01 with operator-supplied `${TRAEFIK_ACME_EMAIL:-}` / `${TRAEFIK_DNS_PROVIDER:-}`.
- No preinfra precondition wired in mod 036 — let docker surface missing-network errors.
- Env-still-up detection method is implementer's discretion.

## Step-by-step plan

### Step 1 — Add `TRAEFIK_IMAGE` constant

Edit `src/docex/__init__.py`. Add alongside the existing `OTEL_COLLECTOR_IMAGE`:

```python
# Traefik image pinned by digest. Mod 036.
# Resolve current digest with:
#   docker pull traefik:v3.3 && docker inspect --format '{{index .RepoDigests 0}}' traefik:v3.3
TRAEFIK_IMAGE = "traefik:v3.3@sha256:<resolve-current-digest>"
```

To resolve the digest:

```bash
docker pull traefik:v3.3 && docker inspect --format '{{index .RepoDigests 0}}' traefik:v3.3
```

Pick whatever current v3.x version makes sense; the digest pinning matters more than the major version choice.

### Step 2 — Extend `emit_project_compose` to include the traefik service

Edit `src/docex/emit/compose.py:emit_project_compose` (added in mod 035). Add the traefik service block and the acme volume:

```python
from docex import TRAEFIK_IMAGE  # at module top

def emit_project_compose(*, project: str, out_path: Path) -> None:
    """Emit a project-tier compose file declaring:
    - The four ${project}-${env}-web networks (owned by this compose file).
    - The docex-ingress preinfra network reference.
    - The ${project}-traefik container, joined to all four -web networks
      plus docex-ingress, with the doctrine cert resolver and the
      project-named acme volume for cert persistence. Mod 036.
    """
    networks = {
        f"{project}-dev-web":   {"name": f"{project}-dev-web"},
        f"{project}-test-web":  {"name": f"{project}-test-web"},
        f"{project}-stage-web": {"name": f"{project}-stage-web"},
        f"{project}-prod-web":  {"name": f"{project}-prod-web"},
        "docex-ingress":        {"external": True},
    }
    acme_volume = f"{project}-traefik-acme"
    services = {
        f"{project}-traefik": {
            "image": TRAEFIK_IMAGE,
            "container_name": f"{project}-traefik",
            "restart": "unless-stopped",
            "networks": [
                f"{project}-dev-web",
                f"{project}-test-web",
                f"{project}-stage-web",
                f"{project}-prod-web",
                "docex-ingress",
            ],
            "volumes": [
                "/var/run/docker.sock:/var/run/docker.sock:ro",
                f"{acme_volume}:/letsencrypt",
            ],
            "command": [
                "--providers.docker=true",
                "--providers.docker.exposedbydefault=false",
                "--entrypoints.web.address=:80",
                "--entrypoints.websecure.address=:443",
                "--certificatesresolvers.doctrine.acme.email=${TRAEFIK_ACME_EMAIL:-}",
                "--certificatesresolvers.doctrine.acme.storage=/letsencrypt/acme.json",
                "--certificatesresolvers.doctrine.acme.dnschallenge=true",
                "--certificatesresolvers.doctrine.acme.dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}",
            ],
        }
    }
    data = {
        "networks": networks,
        "services": services,
        "volumes": {acme_volume: {}},
    }
    out_path.write_text(yaml.safe_dump(data, sort_keys=False))
```

The exact ordering of keys (`networks` first or `services` first) doesn't matter functionally — pick whatever matches the existing convention in the file.

### Step 3 — Flip env compose's `web` network reference

Edit `src/docex/emit/compose.py:_network_section`. The current code:

```python
if short == "web":
    # WHY: project-scoping `web` would force per-project Traefik
    # instances, which can't coexist on :443. The bare external
    # `web` network is the single host-wide public-routing plane
    # the machine-wide Traefik attaches to.
    out[short] = {"name": "web", "external": True}
    continue
```

Replace with:

```python
if short == "web":
    # Mod 036: the `web` network is now per-project per-env
    # (`${project}-${env}-web`), owned by projinfra. The
    # per-project traefik (also projinfra) joins all four of the
    # project's `-web` networks; coexistence on :443 isn't an
    # issue because the host-wide HAProxy web demux fronts every
    # project. See projinfra/fixed_reverse_proxy.md.
    out[short] = {
        "name": f"{compiled.project}-{compiled.env}-web",
        "external": True,
    }
    continue
```

Drop the obsolete comment about machine-wide Traefik.

### Step 4 — Wire `projinfra <up|down> <side>` for fixed

Edit `src/docex/__main__.py:_cmd_projinfra` (the stub from mod 034). Insert the fixed branch ahead of the existing elastic branch and ahead of the catchall stub:

```python
def _cmd_projinfra(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex projinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"])
    parser.add_argument("side", choices=["development", "production"])
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.projinfra import (
        run_projinfra_fixed_up, run_projinfra_fixed_down,
    )

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()

    if ctx.infra.foundation == "fixed":
        if ns.direction == "up":
            return run_projinfra_fixed_up(ctx, docker, side=ns.side)
        else:
            return run_projinfra_fixed_down(ctx, docker, side=ns.side)

    # Elastic: existing up-production path remains.
    if (ctx.infra.foundation == "elastic"
            and ns.direction == "up"
            and ns.side == "production"):
        from docex.pipeline.bootstrap import run_bootstrap
        aws = _make_aws_client()
        return run_bootstrap(ctx, aws)

    print(f"projinfra {ns.direction} {ns.side} (stub): "
          f"real behavior lands in mods 037-039 (elastic).")
    return 0
```

### Step 5 — Add `src/docex/pipeline/projinfra.py`

New module. Two top-level functions:

```python
"""Project-tier infrastructure runner. Mod 036 ships the fixed branch
(per-project traefik + four -web networks); mods 037-039 add elastic.

`docex/projinfra/projinfra.md` describes the per-(foundation, side)
behavior at the doctrine level."""
from __future__ import annotations

from pathlib import Path
from docex.context import ProjectContext
from docex.docker.client import DockerClient


def run_projinfra_fixed_up(
    ctx: ProjectContext, docker: DockerClient, *, side: str
) -> int:
    """Bring up the project-tier compose stack for the given side
    (development or production) on a fixed-foundation project. On a
    single-machine fixed project the two sides converge — running
    `up production` after `up development` is a docker-compose-up
    no-op because the resource set is identical."""
    compose_file = (
        ctx.project_root / "infra" / "output" / "project" / side
        / "docker-compose.yml"
    )
    if not compose_file.exists():
        print(f"error: {compose_file} not found — run `docex compile` first.")
        return 1
    rc = docker.compose_up(compose_file, detached=True)
    if rc != 0:
        print(f"error: `docker compose up` failed with exit code {rc}.")
    return rc


def run_projinfra_fixed_down(
    ctx: ProjectContext, docker: DockerClient, *, side: str
) -> int:
    """Tear down the project-tier compose stack. Refuses if any env-tier
    compose stack for this project is still up — projinfra is the
    foundation env-tier sits on. The acme named volume survives."""
    if docker.any_env_compose_up(ctx.project.name):
        print(
            f"error: env-tier compose stacks for project "
            f"{ctx.project.name!r} are still up. `docex envinfra down "
            f"<env>` first, then re-run."
        )
        return 1
    compose_file = (
        ctx.project_root / "infra" / "output" / "project" / side
        / "docker-compose.yml"
    )
    if not compose_file.exists():
        print(f"warning: {compose_file} not found — nothing to tear down.")
        return 0
    return docker.compose_down(compose_file)
```

### Step 6 — Extend `DockerClient` and `SubprocessDockerClient`

Add methods to `src/docex/docker/client.py` (Protocol) and `src/docex/docker/subprocess_client.py`:

- `compose_up(compose_file: Path, *, detached: bool = False) -> int`
- `compose_down(compose_file: Path) -> int`
- `any_env_compose_up(project_name: str) -> bool`

The first two are thin subprocess wrappers around `docker compose -f <file> up -d` / `docker compose -f <file> down`. The third runs `docker compose ls --format json --all` (or `docker network ls --filter name=<project>-<env>-internal --quiet`) and checks for any project-env match.

Suggested implementation for the third using `docker compose ls`:

```python
def any_env_compose_up(self, project_name: str) -> bool:
    """True if any env-tier compose stack for this project is currently
    up. Env compose project names are `${project}-${env}` for env in
    (dev, test, stage, prod)."""
    import json
    result = subprocess.run(
        ["docker", "compose", "ls", "--format", "json", "--all"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return False  # uncertain; default safe
    try:
        projects = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    targets = {
        f"{project_name}-{env}" for env in ("dev", "test", "stage", "prod")
    }
    for entry in projects:
        if entry.get("Name") in targets:
            status = entry.get("Status", "")
            if "running" in status.lower() or "up" in status.lower():
                return True
    return False
```

(`docker network inspect ${project}-${env}-internal` is the alternative — also fine. Implementer's call.)

### Step 7 — Tests

#### `tests/unit/test_compose_emitter.py`

- New assertion: the project compose includes a `${project}-traefik` service with the right container_name, networks list (5 entries), volumes, command flags (cert resolver name `doctrine`, dnschallenge=true, env-var-substitution shape).
- Existing env-compose tests asserting `web` network was bare → flip to `${project}-${env}-web` with `external: true`.

#### `tests/integration/test_compile.py`

- The four mod-035 project-tier tests already there: extend the content-validation case to also assert the traefik service block is present.
- New: assert env-tier compose's `web` network references the project-tier name with `external: true`.

#### `tests/unit/test_pipeline_projinfra.py` (new)

- `test_projinfra_fixed_up_runs_compose_up`: stub DockerClient, dispatch projinfra-up-development on a fixed project, assert `compose_up` called with the right path.
- `test_projinfra_fixed_down_refuses_when_env_up`: stub DockerClient with `any_env_compose_up=True`; assert refusal with exit code 1 and a clear message.
- `test_projinfra_fixed_down_proceeds_when_env_clean`: stub `any_env_compose_up=False`; assert `compose_down` called.
- `test_projinfra_fixed_up_missing_compose_file`: project_root has no `infra/output/project/<side>/docker-compose.yml`; assert error message and exit 1.

#### `tests/unit/test_dispatcher.py`

- Extend the existing projinfra dispatcher tests: the previously-stubbed fixed branches now dispatch to `run_projinfra_fixed_*`. Mock those and assert they're called.

### Step 8 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 9 — Sanity sweep

```bash
# No old "machine-wide traefik" / bare-web-network assumptions remain
grep -rn '"web", "external": True\|"name": "web"' src/

# Traefik image consumed where expected
grep -rn 'TRAEFIK_IMAGE' src/

# Projinfra fixed branch wired
grep -n 'run_projinfra_fixed' src/docex/__main__.py
```

First sweep: zero hits. Second and third: hits only in the expected sites.

## Out of scope

- **No ansible artifacts at project tier** — multi-machine fixed deferred.
- **No elastic projinfra changes** beyond preserving mod 034's behavior.
- **No real `preinfra` checks** — mod 042. `projinfra up` doesn't pre-flight-check; docker errors surface organically.
- **No env-tier release flow changes.**
- **No `test_projects/{fixed,elastic}/` edits.**
- **No EC2-traefik variant** — mod 044.
- **No operator-credential management for LE DNS providers.**

## Done criteria

- [ ] `TRAEFIK_IMAGE` constant added in `src/docex/__init__.py`, pinned by digest.
- [ ] `emit_project_compose` produces traefik service block + four `-web` networks + acme volume.
- [ ] Env compose `_network_section` flipped: `web` short name → `${project}-${env}-web` external.
- [ ] `pipeline/projinfra.py` new module with `run_projinfra_fixed_up` / `_down`.
- [ ] `_cmd_projinfra` fixed branch wired ahead of elastic branch.
- [ ] `DockerClient` extended with `compose_up`, `compose_down`, `any_env_compose_up`.
- [ ] Tests cover: project-traefik service emission, env-compose external-web flip, projinfra fixed-up dispatch, projinfra fixed-down refusal, projinfra fixed-down success.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/` edits.

Working tree dirty when finished. Do not commit.
