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


_FIXED_ENVS = ("dev", "test")
_ALL_ENVS = ("dev", "test", "stage", "prod")


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
    """Return the path to ``infra/secrets/<env>.env`` if it exists.

    Compose's default behavior is to read ``.env`` next to the compose
    file, but the doctrine puts secrets under ``infra/secrets/``. We
    pass that file via ``--env-file`` so ``${VAR}`` substitutions in
    the compose YAML resolve. Returns None if the file doesn't exist,
    so compose's behavior degrades to "no substitutions" rather than
    erroring on a missing path.
    """
    candidate = ctx.project_root / "infra" / "secrets" / f"{env}.env"
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
    """Return the simple names of every core service, sorted.

    Sorted output keeps ``docex build`` / ``docex test`` deterministic
    across runs — a developer running ``docex test`` twice sees the
    same per-service order both times.
    """
    if ctx.infra is None:
        return []
    return sorted(ctx.infra.core_services or {})


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
    """Map a simple service name (``api``) to its compose-file key.

    The compose emitter writes services under their project-scoped
    global name (e.g. ``sample-dev-api``), so ``docker compose exec
    <simple_name>`` fails with "service not running" — we have to
    feed compose the global key. We parse it back out of the compiled
    compose file rather than re-running naming logic, so the source
    of truth stays in the compiler.
    """
    import yaml

    compose_path = compose_file_for(ctx, env)
    if not compose_path.is_file():
        return simple_name  # Best-effort fallback.
    doc = yaml.safe_load(compose_path.read_text())
    services = (doc or {}).get("services") or {}
    # Heuristic: the global key has the simple name as suffix
    # (possibly separated by '-' or '_').
    for key in services:
        if key == simple_name:
            return key
        if key.endswith(f"-{simple_name}") or key.endswith(f"_{simple_name}"):
            return key
    return simple_name
