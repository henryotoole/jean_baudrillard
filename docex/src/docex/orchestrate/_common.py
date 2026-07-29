"""Shared helpers for the Phase 2 orchestrate-layer commands.

The functions here cover concerns that are reused across ``up``,
``down``, ``build``, ``test``, and ``migrate``:

  * Re-compile defensively so users never have to remember
    ``docex compile`` before ``docex up``.
  * Validate that the named env is one this command supports.
  * Locate the compiled compose file for an env.
  * Enumerate the core services / schema-owning services.
  * Resolve a codebase to its emitted **exec service** — the container the
    per-codebase operations (``migrate``, ``test``, ``build``) run inside.
"""

from __future__ import annotations

from pathlib import Path

from docex.cicl.compile import codebase_global_name, run_compile
from docex.context import ProjectContext
from docex.errors import EnvNotSupported, InfraFileError
from docex.naming import NamingPolicy, dns_label


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


def scheduler_only_services(ctx: ProjectContext) -> list[str]:
    """Codebase keys with NO long-running process type, sorted.

    Every process type of such a codebase is a ``scheduler``, so the
    codebase contributes no ordinary compose service block at all — only
    Ofelia triggers in ``dev``, and in ``test`` nothing but its exec
    service (mod 073 drops the trigger there). That makes it the one
    codebase shape whose image **no compose service builds**: ``up --build``
    has no non-gated block of that codebase to build, and the
    ``profiles: [exec]`` exec service is only ever reached through
    ``compose run``, which builds solely when the image is absent.

    Hence the two consumers: ``up``'s ``_ensure_codebase_image`` (docex
    builds the tag itself) and ``up``'s host-``dist/`` pre-populate skip
    (there is no bind-mounted long-running container to populate for).

    A *mixed* web+scheduler codebase is deliberately excluded from both —
    it has a container to build into and its tag is built by
    ``compose up --build``.
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


def _codebase_naming_policy(
    ctx: ProjectContext, codebase: str, *, foundation: str
) -> NamingPolicy | None:
    """The naming policy for a codebase-keyed identity.

    A codebase-keyed name has no process type and therefore no single role to
    resolve an engine from. Every process type of the codebase must agree on
    the policy for the name to be well-defined, so we resolve all of them and
    require agreement rather than picking one — picking one is precisely the
    instability Mod 099 removed from migration sizing. All bundled core roles
    use ``ecs``.

    Mirrors the compiler's own per-process engine resolution (first engine in
    sorted order that supports ``foundation``), because the names derived from
    this must match ``CompiledService.codebase_global_name`` byte-for-byte.
    Both codebase-keyed identities outside the compiler come through here:
    ``exec_service_key`` (``-exec``) and
    ``migrate.py::_migration_task_family`` (``-migrate``).

    Returns ``None`` when the policy cannot be derived at all (unknown
    codebase, no process types, or no engine supporting ``foundation``); each
    caller decides whether that is a hard error or a best-effort fallback.
    Raises when the process types *disagree*, which is never a fallback case:
    the name would be ambiguous and silently wrong.
    """
    core = (ctx.infra.core_services or {}).get(codebase) if ctx.infra else None
    if core is None or not core.processes:
        return None
    tables = ctx.transfer_tables
    # policy name -> the first process type that resolved to it (for the
    # disagreement message; naming both sides is what makes it diagnosable).
    resolved: dict[str, str] = {}
    for proc_name in sorted(core.processes):
        engines = tables.role(core.processes[proc_name].role)
        entry = next(
            (
                engines[cand] for cand in sorted(engines)
                if engines[cand].supports(foundation)
            ),
            None,
        )
        if entry is None:
            continue
        resolved.setdefault(entry.naming, proc_name)
    if not resolved:
        return None
    if len(resolved) > 1:
        detail = ", ".join(
            f"{proc!r} → {pol!r}" for pol, proc in sorted(resolved.items())
        )
        raise InfraFileError(
            f"core service {codebase!r}: its process types resolve to "
            f"different naming policies ({detail}), so the codebase-keyed "
            f"name is ambiguous. A codebase-scoped identity (the exec "
            f"service, the migration task definition) needs one policy for "
            f"the whole codebase."
        )
    return tables.naming_policies.get(next(iter(resolved)))


def exec_service_key(ctx: ProjectContext, env: str, codebase: str) -> str:
    """The compose key of a codebase's **exec service** (``…-<cb>-exec``).

    The exec service is the container that *is* the codebase — the per-codebase
    operations container ``migrate``, ``test`` and ``build`` run one-off inside
    (Mod 099). This replaced a codebase → app-container resolver that scanned
    the emitted compose file for a key ending in the codebase's lowest-sorted
    non-scheduler process type, and could resolve to the wrong container
    outright: a codebase literally named ``web`` matched a *sibling*
    codebase's ``…-api-web``, silently, with no error.

    Construct-then-verify, deliberately: the key is *derived* from the same
    ``codebase_global_name`` the compiler emits, then checked against the
    compiled compose file. There is no suffix match to mis-resolve and no
    silent fallback to a bare name — a mismatch is a loud error naming the
    ``-exec`` keys that *are* present, which turns a stale-compile or
    naming-policy mismatch from a mystery into a diagnosis.
    """
    import yaml

    # dev/test are always fixed, and so is a fixed project's stage/prod;
    # compose output only ever exists for a fixed-compiled env.
    policy = _codebase_naming_policy(ctx, codebase, foundation="fixed")
    if policy is None:
        raise InfraFileError(
            f"cannot derive the exec service key for codebase {codebase!r} "
            f"in {env!r}: it is not a core service in infra.yml, declares no "
            f"process types, or none of its roles has an engine supporting "
            f"the fixed foundation."
        )
    key = f"{codebase_global_name(ctx.project.name, env, codebase, policy)}-exec"

    compose_path = compose_file_for(ctx, env)
    if compose_path.is_file():
        doc = yaml.safe_load(compose_path.read_text()) or {}
        services = (doc.get("services") or {})
        if key not in services:
            present = sorted(k for k in services if k.endswith("-exec"))
            raise InfraFileError(
                f"no exec service {key!r} in {compose_path}; the compiled "
                f"output is stale or was written under a different naming "
                f"policy. Exec services present: {present or '(none)'}. "
                f"Run 'docex compile'."
            )
    return key
