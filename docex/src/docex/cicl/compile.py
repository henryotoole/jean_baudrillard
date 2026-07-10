"""The CICL compiler.

Turns ``infra.yml`` + transfer tables into ``infra/output/<env>/...``
artifacts. The flow:

  1. Load + validate (cross-document rules from validate.py).
  2. For each of dev/test/stage/prod:
     - Determine the env's foundation (dev/test → fixed, stage/prod →
       project foundation).
     - Build a compiled in-memory representation.
     - Hand off to the appropriate emitter.
  3. Always emit infra/secrets/example.env.

Determinism: dicts are iterated in sorted-key order anywhere iteration
would otherwise be undefined, so identical inputs produce byte-identical
outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docex import ELASTIC_REGION
from docex.cicl.fargate import fargate_pair, fargate_pair_from_units
from docex.cicl.magic_refs import MagicRefResolver
from docex.cicl.model import (
    BackingService,
    CICLDocument,
    CoreService,
    Resources,
)
from docex.cicl.substitute import HCLLiteral, substitute_tree
from docex.cicl.transfer import EngineEntry, TransferTables
from docex.cicl.validate import validate_document
from docex.errors import ValidationError, ValidationIssue
from docex.naming import NamingPolicy, apply_policy
from docex.naming import dns_label as _dns_label


_ENVS = ("dev", "test", "stage", "prod")

# Runtime-ref token ($[VAR]). Used to enforce the parts-only rule: a
# secret-bearing env value must resolve to exactly one bare ref, never a
# composed string (see transfer_tables.md § provides).
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")


def _env_foundation(project_foundation: str, env: str) -> str:
    # dev and test are always fixed; stage and prod follow the project.
    if env in ("dev", "test"):
        return "fixed"
    return project_foundation


def _resources_to_fixed(res: Resources) -> dict[str, Any]:
    """Translate a Resources block into docker-compose ``deploy.resources``.

    Also returns a `tmpfs:` block if disk is set, as a separate top-level
    key the caller composes onto the compose service.
    """
    out: dict[str, Any] = {
        "deploy": {
            "resources": {
                "limits": {
                    "cpus": str(res.cpu),
                    "memory": res.memory,
                }
            }
        }
    }
    if res.disk is not None:
        # docker's tmpfs `size=` option uses lowercase IEC-ish suffixes:
        # `g` / `m` / `k` (not `GB` / `MB`). Translate the CICL form
        # (e.g. `20GB`) to the docker form (`20g`).
        out["tmpfs"] = [f"/tmp:size={_disk_to_tmpfs_size(res.disk)}"]
    if res.gpu is not None:
        out["deploy"]["resources"].setdefault("reservations", {})
        out["deploy"]["resources"]["reservations"]["devices"] = [
            {
                "driver": "nvidia",
                "count": res.gpu.count,
                "capabilities": ["gpu"],
            }
        ]
    return out


def _memory_to_mib(memory: str) -> int:
    """Convert a 'NGB' or 'NMB' string to MiB (decimal -> binary)."""
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(MB|GB)$", memory)
    if not m:
        raise ValueError(f"unparseable memory string: {memory!r}")
    n, unit = float(m.group(1)), m.group(2)
    # Decimal -> bytes -> MiB.
    bytes_ = n * (1_000_000 if unit == "MB" else 1_000_000_000)
    return int(round(bytes_ / (1024 * 1024)))


def _disk_to_tmpfs_size(disk: str) -> str:
    """Translate a CICL disk string (e.g. ``20GB``) to docker tmpfs size.

    Docker's ``--tmpfs ...,size=`` option uses lowercase IEC-style
    suffixes (``g``, ``m``, ``k``) and rejects the ``B``-suffix forms.
    The Phase 1 emitter previously wrote the raw CICL string, which
    runc rejected. We translate ``GB`` → ``g``, ``MB`` → ``m``,
    ``KB`` → ``k``; integer values pass through unchanged.
    """
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(KB|MB|GB)$", disk)
    if not m:
        # Unknown form — return as-is and let docker complain.
        return disk
    n, unit = m.group(1), m.group(2)
    # Drop trailing ".0" if any (we want "20g", not "20.0g").
    if "." in n and float(n).is_integer():
        n = str(int(float(n)))
    return f"{n}{unit[0].lower()}"


def _disk_to_gib(disk: str) -> int:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(MB|GB)$", disk)
    if not m:
        raise ValueError(f"unparseable disk string: {disk!r}")
    n, unit = float(m.group(1)), m.group(2)
    bytes_ = n * (1_000_000 if unit == "MB" else 1_000_000_000)
    # GiB, rounded up.
    return max(1, int((bytes_ + (1024**3 - 1)) // (1024**3)))


_FARGATE_DISK_MIN_GIB = 21  # AWS Fargate floor; below this is invalid.
_FARGATE_DISK_MAX_GIB = 200  # AWS Fargate ceiling.


def _resources_to_elastic(
    res: Resources, *, service_name: str, is_core: bool = False,
    notes_seen: "set[str] | None" = None,
) -> dict[str, Any]:
    """Translate a Resources block into Fargate task-definition HCL fields.

    Phase 4 enforces Fargate's hard constraints at compile time:
      - ``(cpu, memory)`` must be a valid pair from AWS's allow-list
        (delegated to :func:`fargate_pair`).
      - ``disk:`` must be in the inclusive range 21..200 GiB. Anything
        below 21 fails loudly here. ``disk:`` may be omitted, in which
        case ``ephemeral_storage`` is also omitted and Fargate uses its
        default 21 GiB allotment.

    Mod 018: when ``is_core`` is True, the task-level totals include the
    paired OTel Collector sidecar's 0.1 vCPU / 128 MiB overhead before
    Fargate-tier rounding. The core container still receives the
    requested resources at runtime — only the task-level totals carry
    the overhead. A one-line notice is printed to stdout when the
    overhead bumps the request into a higher Fargate tier than the
    bare-core request alone would have.

    Mod 053 (F17): ``notes_seen`` dedupes the rounding notice across a
    single ``run_compile`` run. The same service compiles once per env
    (stage + prod for elastic) and ``run_compile`` may itself run several
    times per command, so the same notice would otherwise print 2-4×.
    When a set is supplied, each unique notice prints at most once; when
    ``None`` (direct callers / unit tests), the notice always prints.
    """
    def _emit_note(message: str) -> None:
        if notes_seen is not None:
            if message in notes_seen:
                return
            notes_seen.add(message)
        print(message)
    # Sidecar overhead: every core service runs a paired otelcol sidecar at
    # 0.1 vCPU / 128 MiB. The task-level totals must accommodate both
    # containers; the core container still receives the requested resources
    # at runtime. See doctrine/infrastructure/specifics/telemetry_infra.md
    # § Task-Level Resource Allocation.
    sidecar_cpu = 0.1 if is_core else 0.0
    sidecar_mem_mib = 128 if is_core else 0

    # Compute base + overhead in raw units, then round to Fargate tier.
    req_cpu_units = max(1, int(round((res.cpu + sidecar_cpu) * 1024)))
    req_mem_mib = _memory_to_mib(res.memory) + sidecar_mem_mib

    cpu_units, memory_mib = fargate_pair_from_units(
        req_cpu_units, req_mem_mib, service_name=service_name,
    )

    # Surface a one-line notice whenever Fargate-tier rounding occurs.
    # Doctrine (cicl.md § Resources, transfer_tables.md § Resources
    # Translation) makes rounding visibility uniform: both non-tier-
    # aligned project resources and the sidecar overhead can trigger
    # rounding, and each gets a message that names the cause. When both
    # contribute, a single combined message is emitted.
    if is_core:
        bare_cpu_units = max(1, int(round(res.cpu * 1024)))
        bare_mem_mib = _memory_to_mib(res.memory)
        bare_cpu_tier, bare_mem_tier = fargate_pair_from_units(
            bare_cpu_units, bare_mem_mib, service_name=service_name,
        )
        # No observable rounding: the sidecar-inclusive request landed
        # exactly on a Fargate tier on both dimensions. Stay silent.
        has_rounding = (
            cpu_units != req_cpu_units or memory_mib != req_mem_mib
        )
        # Bare-core itself rounds when the operator's request doesn't
        # land exactly on a Fargate tier.
        project_caused_rounding = (
            bare_cpu_units != bare_cpu_tier or bare_mem_mib != bare_mem_tier
        )
        # The sidecar overhead pushed the task past the tier bare-core
        # alone would have landed at.
        sidecar_caused_bump = (
            cpu_units > bare_cpu_tier or memory_mib > bare_mem_tier
        )
        if has_rounding and project_caused_rounding and sidecar_caused_bump:
            _emit_note(
                f"note: core service {service_name!r}: resources rounded "
                f"to Fargate tier (request {req_cpu_units} -> {cpu_units} "
                f"vCPU units, {req_mem_mib} -> {memory_mib} MiB). "
                f"Non-tier-aligned project resources AND sidecar overhead "
                f"each contributed to the bump; bare-core would have "
                f"tiered to ({bare_cpu_tier}, {bare_mem_tier})."
            )
        elif has_rounding and sidecar_caused_bump:
            _emit_note(
                f"note: core service {service_name!r}: sidecar overhead "
                f"pushed task to next Fargate tier "
                f"({bare_cpu_tier} -> {cpu_units} vCPU units, "
                f"{bare_mem_tier} -> {memory_mib} MiB). The core container "
                f"still receives the requested {res.cpu} vCPU / {res.memory}; "
                f"the task-level totals carry the overhead."
            )
        elif has_rounding and project_caused_rounding:
            _emit_note(
                f"note: core service {service_name!r}: resources rounded "
                f"to Fargate tier ({req_cpu_units} -> {cpu_units} vCPU "
                f"units, {req_mem_mib} -> {memory_mib} MiB). Fargate "
                f"accepts only discrete (vCPU, memory) pairs; requested "
                f"values don't match a tier exactly."
            )

    out: dict[str, Any] = {
        "cpu": str(cpu_units),
        "memory": str(memory_mib),
    }
    if res.disk is not None:
        disk_gib = _disk_to_gib(res.disk)
        if disk_gib < _FARGATE_DISK_MIN_GIB:
            raise ValidationError([ValidationIssue(
                rule="rule_fargate_disk_below_floor",
                message=(
                    f"Fargate ephemeral_storage minimum is {_FARGATE_DISK_MIN_GIB} GiB; "
                    f"requested disk={res.disk!r} resolves to {disk_gib} GiB. "
                    f"Either bump the disk: field to >= {_FARGATE_DISK_MIN_GIB} GiB "
                    f"or omit it to inherit Fargate's default."
                ),
                where=f"core_services.{service_name}.resources.disk",
            )])
        if disk_gib > _FARGATE_DISK_MAX_GIB:
            raise ValidationError([ValidationIssue(
                rule="rule_fargate_disk_above_ceiling",
                message=(
                    f"Fargate ephemeral_storage maximum is {_FARGATE_DISK_MAX_GIB} GiB; "
                    f"requested disk={res.disk!r} resolves to {disk_gib} GiB."
                ),
                where=f"core_services.{service_name}.resources.disk",
            )])
        out["ephemeral_storage"] = {"size_in_gib": disk_gib}
    # GPU rejected at validation time; not handled here.
    return out


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def _global_service_name(
    project: str, env: str, service: str, policy: NamingPolicy
) -> str:
    raw = f"{project}_{env}_{service}"
    return apply_policy(raw, policy)


def _network_name(project: str, env: str, network: str) -> str:
    return f"{project}_{env}_{network}"


def _image_ref(
    registry: str | None,
    project: str,
    service: str,
    version: str,
    *,
    env: str,
    foundation: str,
) -> str:
    """Build a deterministic image ref per cicl.md § Container Registry.

    The ref depends on the environment:

    - **dev/test** build the image locally from the service's Dockerfile
      (the compose file carries a ``build:`` block), so they never pull
      from a registry. We emit a registry-less local tag
      ``<project>/<service>:<version>`` regardless of whether
      ``container_registry`` is set — the registry host is meaningless
      for a local build/tag.
    - **stage/prod** reference an image pushed to / pulled from a
      registry. With an explicit ``container_registry`` we use it. On
      elastic with no ``container_registry`` (the ECR default), the ECR
      repo URL is read from the project-tier remote state — the project
      HCL provisions one ECR repo per core service and outputs the URL.
      This branch is only reachable on elastic — fixed always has a
      registry (validation rule 9).
    """
    if env in ("dev", "test"):
        return f"{project}/{service}:{version}"
    if registry:
        return f"{registry.rstrip('/')}/{project}/{service}:{version}"
    hcl_id = service.replace("-", "_")
    return HCLLiteral(
        f'"${{data.terraform_remote_state.project.outputs.'
        f'ecr_repository_{hcl_id}_url}}:{version}"'
    )


def _env_subdomain(apex_domain: str, project: str, env: str) -> str:
    """Build the canonical bare-env subdomain per cicl.md § Domain.

    Returns ``<env>.<project>.<apex_domain>``. The project segment is
    pushed through :func:`_dns_label` so an underscored project name
    (e.g. ``docex_smoke_elastic``) resolves to a DNS-valid label
    (``docex-smoke-elastic``). DNS labels do not accept underscores.
    """
    return f"{env}.{_dns_label(project)}.{apex_domain}"


def _bare_project_subdomain(apex_domain: str, project: str) -> str:
    """The bare-project host: ``<project>.<apex_domain>`` per cicl.md §
    Domain. Used to route prod's ``domain_default_service`` for user URL
    ergonomics, replacing the old ``www.<apex>`` convention. Project
    segment is DNS-labeled (see :func:`_env_subdomain`)."""
    return f"{_dns_label(project)}.{apex_domain}"


def _web_hosts(
    name: str, networks: list[str], subdomain: str,
    default_service: str | None,
    *, env: str, bare_project: str,
) -> list[str]:
    """The public host(s) a web-network service is reachable at.

    Every web-network service gets ``<service>.<env_subdomain>``. The
    ``domain_default_service`` additionally answers at the bare
    ``<env_subdomain>``; in ``prod`` it ALSO answers at the bare-project
    host (``<project>.<apex_domain>``) per cicl.md § Domain (bare
    project routes to prod's default service). Non-web services get no
    hosts.

    Host order is most-specific to least-specific:
    ``[per_service, bare_env, bare_project?]``.
    """
    if "web" not in networks:
        return []
    per_service = f"{_dns_label(name)}.{subdomain}"
    if default_service is not None and name == default_service:
        hosts = [per_service, subdomain]
        if env == "prod":
            hosts.append(bare_project)
        return hosts
    return [per_service]


def web_hostnames_for_env(
    doc: CICLDocument, project_name: str, env: str
) -> list[str]:
    """Every public web hostname for ``env``, order-stable + deduped.

    Reuses the exact host derivation the compiler uses for routing
    (:func:`_web_hosts` over :func:`_env_subdomain` /
    :func:`_bare_project_subdomain`), so the preinfra DNS check and the
    emitted traefik routers never drift. Mod 054.
    """
    subdomain = _env_subdomain(doc.apex_domain, project_name, env)
    bare_project = _bare_project_subdomain(doc.apex_domain, project_name)
    hosts: list[str] = []
    for name, svc in sorted(doc.all_services().items()):
        hosts.extend(_web_hosts(
            name, svc.networks, subdomain, doc.domain_default_service,
            env=env, bare_project=bare_project,
        ))
    return list(dict.fromkeys(hosts))


# ---------------------------------------------------------------------------
# Compiled representation
# ---------------------------------------------------------------------------


@dataclass
class CompiledService:
    """A single service after all transfer-table merging + substitution."""

    name: str
    role: str
    engine: str
    foundation: str
    is_core: bool
    global_name: str
    body: dict[str, Any]  # merged transfer-table block (resolved)
    networks: list[str]  # docker network / SG short names
    depends_on: list[str]
    port: int | None
    env: dict[str, Any]  # core service `env` block, resolved
    # Public host(s) this service is routed at (empty if not web-network).
    # The reverse proxy (Traefik / ALB) routes these to the container port.
    web_hosts: list[str] = field(default_factory=list)
    schema_owned_by: str | None = None
    # Phase 4: True iff this is a core service that owns a backing
    # database (i.e. some backing service declares
    # ``schema_owned_by: <this_service>``). Used by the elastic HCL
    # emitter to know whether to emit a *_migrate task definition.
    schema_owned_by_db: bool = False
    # Field translations that route to a non-default emit target.
    # Keyed by destination name (e.g. "target_group"); the value is the
    # resolved translation body. Empty dict when no fields routed
    # off-default. Mod 010.
    target_extras: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-foundation list of emit destinations from the engine's `emits:`
    # block, propagated at compile time so the emitter doesn't need a
    # full TransferTables reference. Empty list for foundations the
    # engine doesn't support. Mod 013.
    emits: dict[str, list[str]] = field(default_factory=dict)
    # Engine-declared persistent storage spec (e.g.
    # ``{"mount_path": "/var/lib/clickhouse"}``). None when the engine
    # doesn't declare it. Mod 015.
    persistent_storage: dict[str, Any] | None = None
    # Mod 055: the scheduler role's 5-field cron expression, carried
    # verbatim from infra.yml. None for every non-scheduler service. The
    # value needs procedural cron translation (see docex.cicl.cron), so —
    # unlike ordinary role-specific fields — it is carried directly rather
    # than routed through a transfer-table translation body. The fixed
    # (ofelia) and elastic (scheduled_task) emitters translate it.
    schedule: str | None = None


@dataclass
class CompiledEnv:
    """All compiled state for a single environment."""

    env: str
    foundation: str
    # Mod 031: the bare apex domain (e.g. ``example.com``). Distinct from
    # ``subdomain`` (the bare-env host ``<env>.<project>.<apex>``) and
    # ``bare_project_subdomain`` (``<project>.<apex>``).
    apex_domain: str
    subdomain: str
    bare_project_subdomain: str
    project: str
    # Mod 046: DNS-label form of `project` (underscores → hyphens, lowercased).
    # Every data-plane-resolvable name (docker networks, ECS Service Connect,
    # OTel sidecar container names, traefik project containers, etc.) must
    # derive its project segment from this field rather than the raw `project`,
    # per transfer_tables.md § Naming Policies.
    project_dns_label: str
    project_version: str
    container_registry: str | None
    services: dict[str, CompiledService]
    networks: set[str]  # short names, e.g. {"web", "internal"}
    # Mod 018: propagated from the source CICLDocument so the elastic HCL
    # emitter can wire each core service's paired OTel Collector sidecar
    # to forward signals to the project's observability backend.
    observability_backend_url: str = ""
    # Mod 044: propagated from the source CICLDocument so the elastic
    # env-tier emitter can gate ALB-specific resources (listener rules,
    # Route53 alias records) on `reverse_proxy == "alb"` and consume the
    # polymorphic `reverse_proxy_security_group_id` project output.
    # Defaults to "alb" — the doctrine default when the project leaves
    # the CICL field unset on an elastic project.
    reverse_proxy: str = "alb"


def compile_env(
    doc: CICLDocument,
    tables: TransferTables,
    *,
    env: str,
    project_name: str,
    project_version: str,
    notes_seen: "set[str] | None" = None,
) -> CompiledEnv:
    """Compile a single environment in-memory.

    ``notes_seen`` (mod 053 / F17) is an optional dedup set for the
    Fargate-tier rounding notice; ``run_compile`` passes one shared set
    across all env passes so each unique notice prints once per run.
    """
    foundation = _env_foundation(doc.foundation, env)
    subdomain = _env_subdomain(doc.apex_domain, project_name, env)
    bare_project = _bare_project_subdomain(doc.apex_domain, project_name)
    # Mod 046: DNS-labeled form of the project name. Used by emit sites that
    # interpolate the project segment directly into a data-plane resolvable
    # name (docker networks, OTel sidecar container names, Service Connect
    # namespace, etc.). The raw `project_name` may contain underscores; the
    # data plane requires hyphens.
    project_dns_label = _dns_label(project_name)

    # Resolve engines per service first; magic refs need them.
    engines_by_service: dict[str, EngineEntry] = {}
    for name, svc in sorted(doc.all_services().items()):
        if isinstance(svc, BackingService):
            entry = tables.engine_for(svc.role, svc.engine, foundation)
        else:
            # Core services have a single engine per role; pick the first
            # supporting the foundation.
            engines = tables.role(svc.role)
            entry = None
            for cand in sorted(engines):
                cand_entry = engines[cand]
                if cand_entry.supports(foundation):
                    entry = cand_entry
                    break
            if entry is None:
                # No supporting engine — surface clearly.
                raise ValidationError([ValidationIssue(
                    rule="rule_4_engine_foundation_mismatch",
                    message=(
                        f"core service {name!r} role {svc.role!r}: no engine "
                        f"supports foundation {foundation!r}"
                    ),
                    where=name,
                )])
        engines_by_service[name] = entry

    # Build substitution contexts per service.
    contexts: dict[str, dict[str, Any]] = {}
    for name, svc in sorted(doc.all_services().items()):
        engine = engines_by_service[name]
        policy = tables.naming_policies.get(engine.naming)
        gname = _global_service_name(project_name, env, name, policy)
        contexts[name] = {
            "name": name,
            "global_service_name": gname,
            "port": svc.port if svc.port is not None
                    else (engine.default_port if engine.default_port is not None else ""),
            "networks": ",".join(svc.networks),
            "project_name": project_name,
            "env_name": env,
            "role_name": svc.role,
            "env_subdomain": subdomain,
            "apex_domain": doc.apex_domain,
            "bare_project_subdomain": bare_project,
        }

    # The magic-ref resolver shares state across all services in this env.
    resolver = MagicRefResolver(
        doc=doc, tables=tables, foundation=foundation,
        contexts=contexts, engines=engines_by_service,
    )

    compiled_services: dict[str, CompiledService] = {}
    networks_seen: set[str] = set()

    # Which core services own a backing-service schema. Reverse-index
    # the backing services' ``schema_owned_by`` declarations.
    core_owning_schema: set[str] = {
        bsvc.schema_owned_by
        for bsvc in doc.backing_services.values()
        if getattr(bsvc, "schema_owned_by", None)
    }

    for name in sorted(doc.all_services()):
        svc = doc.all_services()[name]
        engine = engines_by_service[name]
        ctx = contexts[name]

        # 1. Start with engine defaults — these always land on the
        #    engine's default target.
        default_target = engine.default_target(foundation)
        body: dict[str, Any] = engine.defaults_for(foundation)
        body = _apply_substitution(body, ctx, foundation, resolver, name)
        target_extras: dict[str, dict[str, Any]] = {}

        def _route_translation(
            translation_body: dict[str, Any], target: str, fctx: dict[str, Any]
        ) -> None:
            """Substitute then merge into default body or target_extras."""
            nonlocal body
            resolved = _apply_substitution(
                translation_body, fctx, foundation, resolver, name,
                use_local_ctx=True,
            )
            if target == default_target:
                body = _deep_merge(body, resolved)
            else:
                existing = target_extras.get(target, {})
                target_extras[target] = _deep_merge(existing, resolved)

        # 2. Apply each role-specific field declared on the service.
        extras_yaml = (svc.model_extra or {})
        for fname, fvalue in sorted(extras_yaml.items()):
            if fname in ("version", "schema_owned_by"):
                # `version` is a field; `schema_owned_by` is structural.
                pass
            if fname == "schedule":
                # Mod 055: the scheduler `schedule` field is carried onto
                # the compiled service (below) and translated procedurally
                # by the emitters; its transfer-table translation body is
                # an empty marker, so routing it here is a no-op. Skip it.
                continue
            translated = engine.field_translation(fname, foundation)
            if translated is None:
                # Unknown role-specific field on this engine/foundation —
                # the validator already reported it; skip gracefully.
                continue
            target, translation_body = translated
            _route_translation(
                translation_body, target, {**ctx, "field_value": fvalue}
            )

        # Special-case: backing services also expose `version` as a field
        # (per the canonical postgres/redis tables), but the value lives on
        # the model, not in model_extra.
        if isinstance(svc, BackingService) and svc.version is not None:
            translated = engine.field_translation("version", foundation)
            if translated is not None:
                target, translation_body = translated
                _route_translation(
                    translation_body, target,
                    {**ctx, "field_value": svc.version},
                )

        # 3. Apply per-foundation invariants and image refs.
        if foundation == "fixed":
            body = _apply_fixed_invariants(body, svc, ctx)
            if isinstance(svc, CoreService):
                body["image"] = _image_ref(
                    doc.container_registry, project_name, name, project_version,
                    env=env, foundation=foundation,
                )
                body = _deep_merge(body, _resources_to_fixed(svc.resources))
                if svc.command is not None:
                    body["command"] = svc.command
                # web-network services are reached through the reverse proxy
                # over the docker network, never a host port — so they publish
                # nothing. This removes host-port collisions entirely (incl. 80
                # /443, which the machine-wide Traefik owns). Non-web core
                # services may still publish for direct host access.
                if svc.port is not None and "web" not in svc.networks:
                    body.setdefault("ports", []).append(f"{svc.port}:{svc.port}")
        else:  # elastic
            body = _apply_elastic_invariants(
                body, svc, ctx,
                is_core=isinstance(svc, CoreService),
                elastic_dests=list((engine.emits or {}).get("elastic", [])),
            )
            if isinstance(svc, CoreService):
                body["image"] = _image_ref(
                    doc.container_registry, project_name, name, project_version,
                    env=env, foundation=foundation,
                )
                # Mod 055: only long-running services (those that emit an
                # `ecs_service`) carry a paired OTel sidecar, so only they
                # need the sidecar's resource overhead folded into the
                # task-level totals. A one-shot scheduler RunTask has no
                # sidecar — accounting for one would over-allocate Fargate
                # and emit a misleading rounding note.
                has_sidecar = "ecs_service" in (engine.emits or {}).get(
                    "elastic", []
                )
                body = _deep_merge(body, _resources_to_elastic(
                    svc.resources, service_name=name, is_core=has_sidecar,
                    notes_seen=notes_seen,
                ))
                if svc.command is not None:
                    body["command"] = svc.command

        # 4. Resolve `env:` block on core services (magic refs live here).
        env_block: dict[str, Any] = {}
        if isinstance(svc, CoreService):
            for key in sorted(svc.env):
                val = svc.env[key]
                if isinstance(val, str):
                    rendered = resolver.resolve_in_string(val, consumer=name)
                    if (
                        not rendered.raw_hcl
                        and "$[" in rendered.value
                        and _RUNTIME_REF_RE.fullmatch(rendered.value) is None
                    ):
                        # Parts-only rule: a secret part must resolve to a
                        # bare $[REF], never embedded in a composed string —
                        # elastic SSM injection can only deliver a secret as
                        # a standalone value, so a composed secret can't
                        # resolve symmetrically across foundations.
                        raise ValidationError([ValidationIssue(
                            rule="rule_composed_secret_forbidden",
                            message=(
                                f"core service {name!r} env {key!r} embeds a "
                                f"secret inside a composed value "
                                f"({rendered.value!r}). Reference the discrete "
                                f"parts (host/port/db/user/password) and compose "
                                f"the handle in the app at startup."
                            ),
                            where=f"core_services.{name}.env.{key}",
                        )])
                    env_block[key] = (
                        HCLLiteral(rendered.value) if rendered.raw_hcl else rendered.value
                    )
                else:
                    env_block[key] = val
            # Core-service `secrets:` are operator-supplied secret env vars with
            # no in-project source (API keys, tokens). Wire each as a self-
            # referential runtime ref so the existing secret path delivers it —
            # compose ${KEY} (fixed) / ECS secrets[] (elastic) — and surfaces it
            # in example.env. Validation forbids a key in both env and secrets.
            for key in sorted(svc.secrets):
                env_block[key] = f"$[{key}]"
            # Core-service `config:` are declared, non-secret, per-env values.
            # Wired exactly like secrets — a self-referential runtime ref that
            # the existing secret path delivers (compose ${KEY} / ECS secrets[]).
            # The value is non-secret (String on elastic); the compiled shape is
            # identical to a secret. See config_and_secrets.md.
            for key in sorted(getattr(svc, "config", {}) or {}):
                env_block[key] = f"$[{key}]"
            # Doctrine-injected: PROJECT_VERSION on every core service.
            # See transfer_tables.md § Per-core-service env (both foundations).
            # Plain string from project.yml — not a magic ref, not a secret.
            # The validator forbids the project from declaring this key itself.
            env_block["PROJECT_VERSION"] = project_version
            # Doctrine-injected OTel env vars on every core service. See
            # transfer_tables.md § Per-core-service env (both foundations). Same on
            # fixed and elastic — the paired sidecar shares the core service's
            # network namespace on both, so localhost:4318 is universal.
            env_block["OTEL_SERVICE_NAME"] = name
            env_block["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
            env_block["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            env_block["OTEL_RESOURCE_ATTRIBUTES"] = (
                f"service.namespace={project_name},"
                f"service.version={project_version},"
                f"deployment.environment.name={env}"
            )

        networks_seen.update(svc.networks)
        is_core = isinstance(svc, CoreService)
        compiled_services[name] = CompiledService(
            name=name,
            role=svc.role,
            engine=engine.engine,
            foundation=foundation,
            is_core=is_core,
            global_name=ctx["global_service_name"],
            body=body,
            networks=list(svc.networks),
            depends_on=list(svc.depends_on or []),
            # Fall back to engine.default_port when the project doesn't
            # declare port: in infra.yml. The substitution context (line
            # 379) already does this fallback for the ${port} variable
            # used in provides templates; CompiledService.port needs to
            # match so downstream emitters (task-def portMappings, ECS
            # Service Connect `service` block) see the engine's port too.
            # Surfaced by Mod 014's project-local sidecar engine — the
            # bundled engine set never exposed this because core services
            # always declare port: and RDS/ElastiCache/S3 don't emit
            # portMappings.
            port=(
                svc.port if svc.port is not None else engine.default_port
            ),
            env=env_block,
            web_hosts=_web_hosts(
                name, svc.networks, subdomain, doc.domain_default_service,
                env=env, bare_project=bare_project,
            ),
            schema_owned_by=getattr(svc, "schema_owned_by", None),
            schema_owned_by_db=(is_core and name in core_owning_schema),
            target_extras=target_extras,
            emits={fnd: list(dests) for fnd, dests in (engine.emits or {}).items()},
            persistent_storage=(
                dict(engine.persistent_storage)
                if engine.persistent_storage
                else None
            ),
            schedule=(
                str(sched)
                if (sched := (svc.model_extra or {}).get("schedule")) is not None
                else None
            ),
        )

    return CompiledEnv(
        env=env,
        foundation=foundation,
        apex_domain=doc.apex_domain,
        subdomain=subdomain,
        bare_project_subdomain=bare_project,
        project=project_name,
        project_dns_label=project_dns_label,
        project_version=project_version,
        container_registry=doc.container_registry,
        services=compiled_services,
        networks=networks_seen,
        observability_backend_url=doc.observability_backend_url,
        reverse_proxy=doc.reverse_proxy or "alb",
    )


def _apply_substitution(
    body: Any, ctx: dict[str, Any], foundation: str,
    resolver: MagicRefResolver, consumer: str,
    *, use_local_ctx: bool = False,
) -> Any:
    """Substitute compile-time vars and magic refs in a tree.

    By default, string substitution flows through the magic-ref
    resolver, which uses the *consumer's* stored context. When
    ``use_local_ctx=True`` (used for field translations that introduce
    ``${field_value}``), substitution uses the ``ctx`` argument
    directly via ``substitute_tree`` — field templates do not contain
    magic refs.
    """
    if use_local_ctx:
        from docex.cicl.substitute import substitute_tree
        return substitute_tree(body, ctx, foundation=foundation)

    if isinstance(body, dict):
        return {k: _apply_substitution(v, ctx, foundation, resolver, consumer)
                for k, v in body.items()}
    if isinstance(body, list):
        return [_apply_substitution(v, ctx, foundation, resolver, consumer) for v in body]
    if isinstance(body, str):
        # Use the magic-ref resolver — it handles both magic refs and
        # plain ${var}/$[var]/@ syntax in one call.
        rendered = resolver.resolve_in_string(body, consumer=consumer)
        return HCLLiteral(rendered.value) if rendered.raw_hcl else rendered.value
    return body


def _apply_fixed_invariants(
    body: dict[str, Any], svc: Any, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Apply per-container fixed invariants (transfer_tables.md § Foundation Invariants)."""
    out = dict(body)
    out["container_name"] = ctx["global_service_name"]
    out["logging"] = {"<<": "*default-logging"}  # YAML merge-key reference
    out["restart"] = "unless-stopped"
    # Map short network names to project-scoped names via top-level
    # ``networks:`` section. The compose emitter rewires these.
    out["networks"] = list(svc.networks)
    if svc.depends_on:
        out["depends_on"] = list(svc.depends_on)
    return out


# Mod 060: which elastic emit destination drives the per-service body
# tags' shape_name/descriptor. A backing service emits exactly one of
# these (postgres→RDS, redis→cache, object_store→S3); a core service's
# body tags carry the ECS-service descriptor. The body tags are consumed
# by the destination renderers that pass `body` through `_hcl_block_body`
# (RDS / ElastiCache / S3); other resources tag via the standard_tags
# helper directly in the emitter.
_BODY_TAG_DESCRIPTOR: dict[str, str] = {
    "rds_instance": "RDS",
    "elasticache_cluster": "cache",
    "s3_bucket": "S3",
    "ecs_service": "ecs-svc",
}


def _apply_elastic_invariants(
    body: dict[str, Any], svc: Any, ctx: dict[str, Any], *, is_core: bool,
    elastic_dests: list[str],
) -> dict[str, Any]:
    """Apply per-resource elastic invariants (tags + identifier).

    The ``tags`` dict is built via :func:`docex.emit.tags.standard_tags`
    so it carries the full envinfra block (cicl.md § Naming and Tagging):
    shape_name (``core_service``/``backing_service`` by ``is_core``) and a
    per-resource descriptor picked from the engine's elastic destinations.
    """
    from docex.emit.tags import standard_tags

    out = dict(body)
    out["identifier"] = ctx["global_service_name"]
    shape_name = "core_service" if is_core else "backing_service"
    descriptor = next(
        (_BODY_TAG_DESCRIPTOR[d] for d in elastic_dests
         if d in _BODY_TAG_DESCRIPTOR),
        "task-def",
    )
    out["tags"] = standard_tags(
        "environment",
        shape_name=shape_name,
        descriptor=descriptor,
        project=ctx["project_name"],
        env=ctx["env_name"],
        service=ctx["name"],
        role=ctx["role_name"],
    )
    return out


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    return override


# ---------------------------------------------------------------------------
# Top-level entry point used by ``__main__``
# ---------------------------------------------------------------------------


def run_compile(ctx: Any) -> int:
    """Compile every env and emit outputs. Returns process exit code."""
    from docex.emit.compose import emit_compose, emit_project_compose
    from docex.emit.hcl import emit_hcl, emit_hcl_project
    from docex.emit.ansible import emit_ansible
    from docex.emit.secrets import emit_example_env
    from docex.errors import InfraFileError

    if ctx.infra is None:
        raise InfraFileError(
            f"{ctx.project_root}/infra/infra.yml: file missing — compile "
            "requires an infra.yml"
        )

    # Cross-document validation (collected).
    issues = validate_document(ctx.infra, ctx.transfer_tables)
    if issues:
        raise ValidationError(issues)

    output_root = ctx.project_root / "infra" / "output"
    output_root.mkdir(parents=True, exist_ok=True)

    files_written = 0
    compiled_envs: list[CompiledEnv] = []
    # F17: dedup the Fargate-tier rounding notice across all env passes of
    # this single compile run (the same service compiles for stage AND prod
    # on elastic) so each unique notice prints once, not per-env.
    notes_seen: set[str] = set()

    for env in _ENVS:
        env_dir = output_root / env
        env_dir.mkdir(parents=True, exist_ok=True)

        compiled = compile_env(
            ctx.infra,
            ctx.transfer_tables,
            env=env,
            project_name=ctx.project.name,
            project_version=ctx.project.version,
            notes_seen=notes_seen,
        )
        compiled_envs.append(compiled)

        if compiled.foundation == "fixed":
            compose_path = env_dir / "docker-compose.yml"
            emit_compose(compiled, compose_path)
            files_written += 1
            # Mod 021: the sidecar config is now embedded inline in the
            # compose file's `configs.otelcol_config.content`, so there's
            # no separate otelcol-config.yaml to write.
            if env in ("stage", "prod"):
                emit_ansible(compiled, env_dir)
                files_written += 3  # playbook.yml, inventory.yml, ansible.cfg
        else:
            hcl_path = env_dir / "main.tf"
            emit_hcl(
                compiled,
                hcl_path,
                naming_policies=ctx.transfer_tables.naming_policies,
            )
            files_written += 1

    # Mod 035: project-tier output is split by side. Both sides emit on
    # every project. The development side is always fixed-style (compose);
    # the production side switches by foundation (compose for fixed, HCL
    # for elastic). Mod 035 emits networks only; the per-project traefik
    # and ansible artifacts land in mod 036.
    # Mod 046: project-tier compose names (the four `-web` networks, the
    # `<project>-traefik` container, the ACME volume) are all data-plane
    # docker identifiers and must derive their project segment from the
    # DNS-labeled form rather than the raw project name.
    project_dns_label = _dns_label(ctx.project.name)

    dev_project_dir = output_root / "project" / "development"
    dev_project_dir.mkdir(parents=True, exist_ok=True)
    emit_project_compose(
        project_dns_label=project_dns_label,
        out_path=dev_project_dir / "docker-compose.yml",
    )
    files_written += 1

    prod_project_dir = output_root / "project" / "production"
    prod_project_dir.mkdir(parents=True, exist_ok=True)
    if ctx.infra.foundation == "fixed":
        emit_project_compose(
            project_dns_label=project_dns_label,
            out_path=prod_project_dir / "docker-compose.yml",
        )
        files_written += 1
    else:  # elastic
        # Project-tier HCL — backs every elastic env-tier main.tf via
        # `data "terraform_remote_state" "project"`; docex bootstrap (now
        # projinfra up production per mod 034) applies it before any
        # env-tier apply.
        emit_hcl_project(
            project=ctx.project.name,
            project_version=ctx.project.version,
            apex_domain=ctx.infra.apex_domain,
            core_service_names=list(ctx.infra.core_services.keys()),
            naming_policies=ctx.transfer_tables.naming_policies,
            out_path=prod_project_dir / "main.tf",
            reverse_proxy=ctx.infra.reverse_proxy,
        )
        files_written += 1

    # Always emit example.env.
    secrets_dir = ctx.project_root / "infra" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    emit_example_env(ctx.infra, ctx.transfer_tables, secrets_dir / "example.env")
    files_written += 1

    print(
        f"Compiled {len(_ENVS)} environments. {files_written} files written "
        f"under infra/output/ and infra/secrets/."
    )
    return 0
