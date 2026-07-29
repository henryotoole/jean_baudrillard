"""Shared helpers for the Phase 2 orchestrate-layer commands.

The functions here cover concerns that are reused across ``up``,
``down``, ``build``, ``test``, and ``migrate``:

  * Re-compile defensively so users never have to remember
    ``docex compile`` before ``docex up``.
  * Validate that the named env is one this command supports.
  * Locate the compiled compose file for an env.
  * Enumerate the core services / schema-owning services.
"""

from __future__ import annotations

from pathlib import Path

from docex.cicl.compile import run_compile
from docex.context import ProjectContext
from docex.errors import EnvNotSupported, InfraFileError
from docex.naming import dns_label


_FIXED_ENVS = ("dev", "test")
_ALL_ENVS = ("dev", "test", "stage", "prod")


def env_compose_project(ctx: ProjectContext, env: str) -> str:
    """The explicit compose ``--project-name`` for an env-tier stack.

    ``<dns_label(project)>-<env>`` — DNS-labeled (hyphenated, lowercased)
    so the name is a valid, stable, data-plane-style identifier and is
    project-scoped (no collision across projects on a shared dev host).
    Passed at every env-tier compose call site so ``up``/``down``/
    ``exec``/``ps`` all address the same compose project deterministically
    rather than relying on compose's path-derived basename. This is also
    the form ``any_env_compose_up`` matches against.
    """
    return f"{dns_label(ctx.project.name)}-{env}"


def ensure_compiled(ctx: ProjectContext) -> None:
    """Re-run the compiler so output/ is up to date.

    The Phase 1 compiler is fast and deterministic, so we always
    re-compile rather than asking the user to remember a manual step.
    """
    if ctx.infra is None:
        raise InfraFileError(
            f"{ctx.project_root}/infra/infra.yml: file missing — "
            "this command requires an infra.yml"
        )
    run_compile(ctx)


def compose_file_for(ctx: ProjectContext, env: str) -> Path:
    """Return the path to the compiled compose file for ``env``."""
    return ctx.project_root / "infra" / "output" / env / "docker-compose.yml"


def env_file_for(ctx: ProjectContext, env: str) -> Path | None:
    """The container-facing env file compose reads: the derived aggregate at
    ``.docex/agg/<env>.env`` (TTE ∪ secrets ∪ config), if it exists. Pure —
    does NOT build it (that's ``aggregate()``); returns None when absent so
    teardown / read-only paths degrade gracefully rather than error.
    """
    # WHY: local import avoids any import-cycle risk — aggregate.py imports
    # from categories/generate/envfile, never from _common.
    from docex.orchestrate.aggregate import aggregate_path

    candidate = aggregate_path(ctx, env)
    return candidate if candidate.is_file() else None


def assert_fixed_env(env: str, *, command: str) -> None:
    """Raise ``EnvNotSupported`` if ``env`` isn't dev or test.

    The error message names the offending command so the user knows
    which surface needs a different env name. Stage/prod always
    require ``docex release`` (Phase 3+).
    """
    if env not in _FIXED_ENVS:
        if env in ("stage", "prod"):
            raise EnvNotSupported(
                f"'docex {command} {env}' is only for dev/test envs; "
                "for stage/prod, use 'docex release' (Phase 3+)."
            )
        raise EnvNotSupported(
            f"unknown env {env!r}; valid envs are: {', '.join(_ALL_ENVS)}"
        )


def core_services(ctx: ProjectContext) -> list[str]:
    """Return the codebase keys of every core service, sorted.

    These are *authoring* keys (``api``), not compiled identities
    (``api-web``) — every consumer here is a per-codebase operation
    (``core/<svc>/``, the image ref, ``build.sh``).

    Sorted output keeps ``docex build`` / ``docex test`` deterministic
    across runs — a developer running ``docex test`` twice sees the
    same per-service order both times.
    """
    if ctx.infra is None:
        return []
    return sorted(ctx.infra.core_services or {})


def scheduler_services(ctx: ProjectContext) -> list[str]:
    """Codebase keys with AT LEAST ONE ``scheduler`` process type, sorted.

    Used by ``up`` to build each scheduler's self-contained job image
    (mod 074) — any codebase carrying a scheduler job needs that image
    built, whether or not it also runs long-running processes.
    """
    if ctx.infra is None:
        return []
    return sorted(
        name
        for name, svc in (ctx.infra.core_services or {}).items()
        if any(p.role == "scheduler" for p in svc.processes.values())
    )


def scheduler_only_services(ctx: ProjectContext) -> list[str]:
    """Codebase keys with NO long-running process type, sorted.

    Distinct from :func:`scheduler_services` because the two call sites
    want different predicates: ``_ensure_scheduler_image`` must run for any
    codebase carrying a scheduler job, while the dev-build skip and the
    test-path branch apply only when there is no long-running container at
    all — a mixed web+scheduler codebase still has a container to build
    into and exec against.
    """
    if ctx.infra is None:
        return []
    return sorted(
        name
        for name, svc in (ctx.infra.core_services or {}).items()
        if svc.processes
        and all(p.role == "scheduler" for p in svc.processes.values())
    )


def services_with_schema(ctx: ProjectContext) -> list[str]:
    """Return core services that declare ``schema_owned_by``.

    These are the services whose ``migrate.sh`` must be invoked by
    ``up`` (dev/test), ``migrate`` (dev/test), and ``test``. Sorted
    for determinism, matching ``core_services``.
    """
    if ctx.infra is None:
        return []
    # A core service "owns a schema" by declaring schema_owned_by on
    # the backing service; we look at backing services whose value
    # points at a core service.
    schema_owners: set[str] = set()
    for _name, backing in (ctx.infra.backing_services or {}).items():
        owner = getattr(backing, "schema_owned_by", None)
        if owner:
            schema_owners.add(owner)
    # Filter to those that are actually core services in the doc.
    valid_core = set(core_services(ctx))
    return sorted(schema_owners & valid_core)


def compose_service_key(ctx: ProjectContext, env: str, simple_name: str) -> str:
    """Map a codebase key (``api``) to the compose-file key of the one
    container that stands in for it.

    The compose emitter writes services under their project-scoped
    global name (e.g. ``sample-dev-api-web``), so ``docker compose exec
    <simple_name>`` fails with "service not running" — we have to
    feed compose the global key. We parse it back out of the compiled
    compose file rather than re-running naming logic, so the source
    of truth stays in the compiler.

    !!! TEMPORARY — DELETED BY MOD 099, which replaces this with
    ``exec_service_key`` against an emitted per-codebase exec service. Do
    not build on it. The suffix scan already mis-resolves in principle (a
    codebase named ``web`` matches ``sample-dev-api-web``, giving the wrong
    container with no error); Mod 096 only keeps it working under
    two-segment keys by matching the codebase's primary process, nothing
    more.
    """
    import yaml

    from docex.cicl.model import primary_process

    compose_path = compose_file_for(ctx, env)
    if not compose_path.is_file():
        return simple_name  # Best-effort fallback.
    doc = yaml.safe_load(compose_path.read_text())
    services = (doc or {}).get("services") or {}
    core = (ctx.infra.core_services or {}).get(simple_name) if ctx.infra else None
    suffix = (
        f"{simple_name}-{primary_process(core)}" if core is not None
        else simple_name
    )
    # Sidecar (`-otelcol`) and ofelia (`-scheduler`) keys are emitted
    # alongside the service they belong to and are never an exec target.
    candidates = [
        k for k in services
        if not (k.endswith("-otelcol") or k.endswith("-scheduler"))
    ]
    for key in candidates:
        if key == suffix:
            return key
        if key.endswith(f"-{suffix}") or key.endswith(f"_{suffix}"):
            return key
    return simple_name
