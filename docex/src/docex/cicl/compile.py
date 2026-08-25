"""The CICL compiler.

Turns ``infra.yml`` + transfer tables into ``infra/output/<env>/...``
artifacts. The flow:

  1. Load + validate (cross-document rules from validate.py).
  2. For each of dev/test/stage/prod:
     - Determine the env's foundation (dev/test → fixed, stage/prod →
       project foundation).
     - Build a compiled in-memory representation.
     - Hand off to the appropriate emitter.

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
    Codebase,
    ServiceRef,
    Resources,
    names_core_service,
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
    notes_seen: "set[str] | None" = None, where: str | None = None,
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

    Mod 096: ``where`` is the caller-built CICL path the error messages
    point at (``codebases.<cb>.core_services.<svc>.resources`` for a core
    service, ``backing_services.<svc>.resources`` for a backing
    service). ``service_name`` stays the human-readable display name used in
    the rounding notice — the compiled two-segment identity for core.

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
        req_cpu_units, req_mem_mib, where=where,
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
            bare_cpu_units, bare_mem_mib, where=where,
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
                where=f"{where}.disk" if where else None,
            )])
        if disk_gib > _FARGATE_DISK_MAX_GIB:
            raise ValidationError([ValidationIssue(
                rule="rule_fargate_disk_above_ceiling",
                message=(
                    f"Fargate ephemeral_storage maximum is {_FARGATE_DISK_MAX_GIB} GiB; "
                    f"requested disk={res.disk!r} resolves to {disk_gib} GiB."
                ),
                where=f"{where}.disk" if where else None,
            )])
        out["ephemeral_storage"] = {"size_in_gib": disk_gib}
    # GPU rejected at validation time; not handled here.
    return out


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def _global_service_name(
    project: str, env: str, name: str, policy: NamingPolicy,
    *, service: str | None = None, slot: int = 1,
) -> str:
    """The globally-unique name of one emitted service.

    Core services carry a fourth segment (``{project}_{env}_{codebase}_
    {service}``); backing services stay three. Called with ``service=None``
    for the *codebase*-keyed form too — see
    ``CompiledService.codebase_global_name``.

    ``name`` is the codebase name for core services and the backing-service
    name for backings, which is why it is not spelled ``codebase``.

    Mod 152: the optional slot segment. ``slot=1`` (default) inserts NOTHING,
    so every existing name is byte-identical; ``slot`` k>1 weaves ``_s{k}``
    between the env and the rest
    (``{project}_{env}_s{k}_{name}_{service}``).
    """
    # Mod 152: the slot segment. Slot 1 (default) inserts NOTHING, so every
    # existing name is byte-identical; slot k>1 weaves `_s{k}` between the env
    # and the rest (`{project}_{env}_s{k}_{name}_{service}`), namespacing this
    # physical name so N stacks of one fixed env coexist on one host. Because
    # container_name/service-keys/volumes/magic-refs all derive from this one
    # function, slotting it here is what closes what `--project-name` cannot.
    slot_seg = "" if slot == 1 else f"_s{slot}"
    raw = (
        f"{project}_{env}{slot_seg}_{name}_{service}" if service is not None
        else f"{project}_{env}{slot_seg}_{name}"
    )
    return apply_policy(raw, policy)


def codebase_global_name(
    project: str, env: str, codebase: str, policy: NamingPolicy,
    *, slot: int = 1,
) -> str:
    """The codebase-keyed global name, ``{project}-{env}-{codebase}``.

    Public because two identities outside the compiler derive from it and must
    match it byte-for-byte: the per-codebase exec service's compose key
    (``…-exec``, resolved by ``orchestrate/_common.py::exec_service_key``) and
    the elastic migration task-definition family (``…-migrate``, reconstructed
    by ``orchestrate/migrate.py::_migration_task_family``). Mod 099.

    Mod 152: the two out-of-compiler re-derivers named above keep the
    ``slot=1`` default this mod and **must be made slot-aware in Mod 154** when
    a slot-k stack runs migrations, or they will not match the slotted name
    this emits.
    """
    return _global_service_name(project, env, codebase, policy, slot=slot)


def _network_name(project: str, env: str, network: str, *, slot: int = 1) -> str:
    slot_seg = "" if slot == 1 else f"-s{slot}"
    return f"{project}_{env}{slot_seg}_{network}"


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

    - **dev/test** build the image locally from the codebase's Dockerfile
      (the compose file carries a ``build:`` block), so they never pull
      from a registry. We emit a registry-less local tag
      ``<project>/<service>:<version>`` regardless of whether
      ``container_registry`` is set — the registry host is meaningless
      for a local build/tag.
    - **stage/prod** reference an image pushed to / pulled from a
      registry. With an explicit ``container_registry`` we use it. On
      elastic with no ``container_registry`` (the ECR default), the ECR
      repo URL is read from the project-tier remote state — the project
      HCL provisions one ECR repo per codebase and outputs the URL.
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
    default_service_compiled: str | None,
    *, env: str, bare_project: str, policy: NamingPolicy,
) -> list[str]:
    """The public host(s) a web-network service is reachable at.

    ``name`` is the *compiled* identity — two-segment (``api-web``) for a
    core service, the bare name for a backing service — and
    ``default_service_compiled`` is the compiled identity of
    ``domain_default_service``.

    Every web-network service gets ``<label>.<env_subdomain>``. The default
    core service additionally answers at the bare ``<env_subdomain>``; in
    ``prod`` it ALSO answers at the bare-project host
    (``<project>.<apex_domain>``) per cicl.md § Domain (bare project routes
    to prod's default core service).
    Non-web services get no hosts.

    The service label goes through the ``http_host`` naming policy rather
    than a bare :func:`dns_label` call, so the policy's 63-octet DNS ceiling
    actually bites here — this is the only site where the label can grow.
    For any input of 63 characters or fewer the two are byte-identical
    (``separator: hyphen`` + ``case: lower`` == ``dns_label``); the only new
    behavior is a clean compile error above that.

    Host order is most-specific to least-specific:
    ``[per_service, bare_env, bare_project?]``.
    """
    if "web" not in networks:
        return []
    per_service = f"{apply_policy(name, policy)}.{subdomain}"
    if default_service_compiled is not None and name == default_service_compiled:
        hosts = [per_service, subdomain]
        if env == "prod":
            hosts.append(bare_project)
        return hosts
    return [per_service]


def web_hostnames_for_env(
    doc: CICLDocument, project_name: str, env: str, naming_policies: Any
) -> list[str]:
    """Every public web hostname for ``env``, order-stable + deduped.

    Reuses the exact host derivation the compiler uses for routing
    (:func:`_web_hosts` over :func:`_env_subdomain` /
    :func:`_bare_project_subdomain`), so the preinfra DNS check and the
    emitted traefik routers never drift. Mod 054.
    """
    subdomain = _env_subdomain(doc.apex_domain, project_name, env)
    bare_project = _bare_project_subdomain(doc.apex_domain, project_name)
    policy = naming_policies.get("http_host")
    default_compiled = (
        ServiceRef.parse(doc.domain_default_service).compiled
        if doc.domain_default_service is not None else None
    )
    hosts: list[str] = []
    entries: list[tuple[str, list[str]]] = [
        (ServiceRef(cb_name, svc_name).compiled, list(svc.networks))
        for cb_name, svc_name, _cb, svc in doc.all_core_services()
    ]
    entries.extend(
        (name, list(svc.networks))
        for name, svc in sorted(doc.backing_services.items())
    )
    for name, networks in entries:
        hosts.extend(_web_hosts(
            name, networks, subdomain, default_compiled,
            env=env, bare_project=bare_project, policy=policy,
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
    # The authored `uses:` entries, VERBATIM — bare for a backing target,
    # dotted for a core one. See cicl.md § Uses Relationships.
    #
    # WHY one field with two derived accessors, and not two fields: the
    # backing/core split below is DERIVED FROM TARGET KIND, not authored.
    # There is one relation in `infra.yml` (the two-field
    # `depends_on`/`consumes` split was retired in 2.0.0), and storing the
    # split would invite a construction site that populates the two lists
    # inconsistently. Nothing can land in the wrong list because nothing is
    # placed into a list at all.
    uses: list[str]
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
    # Mod 115: the clock role's `schedules` map (job name -> 5-field cron),
    # carried VERBATIM from infra.yml. None for every non-clock service.
    # Its transfer-table body is an empty marker, so it is carried directly
    # rather than routed through a transfer-table translation body; the
    # emitters deliver it procedurally as the
    # `DOCEX_SCHEDULES_YAML` literal (see emit/schedules.py). No cron
    # translation is applied anywhere: clock.md § Cron format passes the
    # expression through to the schedule table unchanged.
    schedules: dict[str, str] | None = None
    # --- Service expansion (Mod 096) -------------------------------------
    # The codebase this compiled service belongs to. None for backing
    # services. `name` is the two-segment compiled identity (`api-web`);
    # `codebase` is what stays keyed on the codebase — the image ref, the
    # ECR repo, `schema_owned_by`, and the `core/<codebase>/` source folder.
    codebase: str | None = None
    service: str | None = None
    # `{project}-{env}-{codebase}` under the same naming policy as
    # `global_name`. The migrate task definition's family derives from this,
    # NOT from `global_name`, so one codebase yields one migrate family.
    # orchestrate/migrate.py reconstructs the identical string.
    codebase_global_name: str | None = None
    # The codebase-scoped env surface: the CODEBASE-level `env:` block
    # resolved, plus secrets / config / doctrine-injected keys, EXCLUDING any
    # core service's `env:` overlay. Consumed by the migrate task definition
    # (and by Mod 099's exec service). See overview.md § Migration carrier.
    codebase_env: dict[str, Any] = field(default_factory=dict)
    # Declared parallelism. The DECLARED value — `effective_replicas` applies
    # the prod-only clamp on top of it. Consumed by the fixed compose unroll
    # and by the elastic ECS `desired_count` (Mod 100).
    replicas: int = 1
    # --- The one and only derivation of the backing / core split ----------
    # Both classify through `names_core_service`, i.e. on `"." in entry`.
    # That is total and unambiguous: `_SERVICE_NAME_RE` forbids a dot in any
    # service name, so bare/dotted partitions the entries with no overlap and
    # no gap, and rule 25 makes that partition *mean* target kind.

    @property
    def uses_backing(self) -> list[str]:
        """`uses` targets that are backing services. A backing service's
        compiled identity IS its bare name, so no translation is needed."""
        return [u for u in self.uses if not names_core_service(u)]

    @property
    def uses_core(self) -> list[str]:
        """`uses` targets that are core services, as COMPILED identities
        (`api-worker`) — the same keys into `CompiledEnv.services`.

        Unparseable entries are dropped, exactly as the authoring-model
        accessor drops them: rule 25 reports each malformed entry once, and it
        must not ALSO resurface downstream.
        """
        out: list[str] = []
        for entry in self.uses:
            if not names_core_service(entry):
                continue
            try:
                out.append(ServiceRef.parse(entry).compiled)
            except ValueError:
                continue
        return out


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
    # Mod 152: which slot this env was compiled for. 1 (default) means no slot
    # segment — byte-identical to a slotless compile. >1 weaves `-s{slot}` into
    # every physical name. Read by emit/compose.py::_network_section to slot the
    # non-web network names (the only physical name not derived from a
    # global_name).
    slot: int = 1


def group_by_codebase(
    compiled: "CompiledEnv",
) -> dict[str, list[CompiledService]]:
    """Core compiled services grouped by codebase, both levels sorted.

    The per-codebase emissions — the exec service (compose), the migration task
    definition (HCL), the playbook's migrate task (ansible) — all iterate this
    rather than picking a representative core service. Mod 099 deleted the
    "pick one core service" bridge; this is what replaced it.

    Backing services are excluded (they have no codebase). Every core
    service's codebase appears, whatever its role: a codebase has a source
    tree to build, test and migrate, so it gets an exec service.
    """
    groups: dict[str, list[CompiledService]] = {}
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        if not svc.is_core or svc.codebase is None:
            continue
        groups.setdefault(svc.codebase, []).append(svc)
    return {cb: groups[cb] for cb in sorted(groups)}


def effective_replicas(svc: CompiledService, env: str) -> int:
    """The number of instances of ``svc`` to emit in ``env``.

    The declared ``replicas`` count applies in ``prod`` only, per ``shape.md``'s
    Runtime Shape paragraphs: "`prod` environments may also have multiple core
    service containers running in parallel." Every other env runs exactly one
    of everything.

    WHY a function and not a pre-clamped field on ``CompiledService``: the
    clamp needs the env, and storing the clamped value would erase the
    distinction between *declared* and *effective*, which the rule-5 collision
    check reads (it seeds replica suffixes off the declaration, before any env
    exists). Both emitters call this so the prod-only rule is stated once.
    """
    if not svc.is_core or env != "prod":
        return 1
    return max(1, svc.replicas)


def _clock_schedules(raw: Any) -> dict[str, str] | None:
    """Mod 115: the `schedules:` value, accepted only in its declared
    shape — a non-empty mapping of ``str -> str``.

    Validation (`rule_clock_schedules_required` / `rule_clock_cron_invalid`)
    has already rejected anything else and raised before compilation reaches
    here, so this is a belt-and-braces gate, not a second opinion: it exists
    so a malformed value can never be rendered into a container's env by an
    emitter.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    if not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        return None
    return dict(raw)


def compile_env(
    doc: CICLDocument,
    tables: TransferTables,
    *,
    env: str,
    project_name: str,
    project_version: str,
    slot: int = 1,
    notes_seen: "set[str] | None" = None,
) -> CompiledEnv:
    """Compile a single environment in-memory.

    ``notes_seen`` (mod 053 / F17) is an optional dedup set for the
    Fargate-tier rounding notice; ``run_compile`` passes one shared set
    across all env passes so each unique notice prints once per run.

    ``slot`` (mod 152) scopes every physical name; ``slot=1`` (default) is
    byte-identical to a slotless compile.
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

    # The unit of work is one EMITTED service: a backing service, or one
    # core service of one codebase. `key` is the compiled identity — the
    # key `engines_by_service`, `contexts` and `compiled_services` are all
    # keyed on, because `role` (and therefore the engine) is per-service now.
    # (key, model, codebase_name | None, service_name | None)
    work: list[tuple[str, Any, str | None, str | None]] = []
    for name in sorted(doc.backing_services):
        work.append((name, doc.backing_services[name], None, None))
    for cb_name, svc_name, _cb, svc in doc.all_core_services():
        work.append((ServiceRef(cb_name, svc_name).compiled, svc, cb_name, svc_name))

    # Resolve engines per emitted service first; magic refs need them.
    engines_by_service: dict[str, EngineEntry] = {}
    for key, svc, cb_name, svc_name in work:
        if isinstance(svc, BackingService):
            entry = tables.engine_for(svc.role, svc.engine, foundation)
        else:
            # Core services have a single engine per role; pick the
            # first supporting the foundation.
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
                        f"core service "
                        f"{ServiceRef(cb_name, svc_name).dotted!r} role "
                        f"{svc.role!r}: no engine supports foundation "
                        f"{foundation!r}"
                    ),
                    where=f"codebases.{cb_name}.core_services.{svc_name}",
                )])
        engines_by_service[key] = entry

    # Build substitution contexts per emitted service.
    contexts: dict[str, dict[str, Any]] = {}
    for key, svc, cb_name, svc_name in work:
        engine = engines_by_service[key]
        policy = tables.naming_policies.get(engine.naming)
        gname = _global_service_name(
            project_name, env, cb_name if svc_name is not None else key,
            policy, service=svc_name, slot=slot,
        )
        contexts[key] = {
            "name": key,
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
            # Mod 096: None for a backing service — `standard_tags` omits the
            # `service` tag entirely in that case, keeping backing tag blocks
            # byte-identical to what they were before service expansion.
            "service": svc_name,
            # The codebase, for the elastic `codebase` tag: the tag block
            # splits the two dimensions (`codebase = api`, `service = web`)
            # rather than carrying the fused compiled identity.
            "codebase_name": cb_name if svc_name is not None else key,
        }

    # The magic-ref resolver shares state across all services in this env.
    resolver = MagicRefResolver(
        doc=doc, tables=tables, foundation=foundation,
        contexts=contexts, engines=engines_by_service,
    )

    compiled_services: dict[str, CompiledService] = {}
    networks_seen: set[str] = set()

    # Which codebases own a backing-service schema. Reverse-index
    # the backing services' ``schema_owned_by`` declarations.
    core_owning_schema: set[str] = {
        bsvc.schema_owned_by
        for bsvc in doc.backing_services.values()
        if getattr(bsvc, "schema_owned_by", None)
    }

    # The compiled identity of `domain_default_service`, compared against
    # each emitted service's `name`.
    default_service_compiled = (
        ServiceRef.parse(doc.domain_default_service).compiled
        if doc.domain_default_service is not None else None
    )
    http_host_policy = tables.naming_policies.get("http_host")

    for name, svc, cb_name, svc_name in work:
        # `svc` is a BackingService, or the CoreService when `cb_name` /
        # `svc_name` are set. `codebase` is the owning Codebase, which
        # holds the codebase-scoped fields (env / secrets / config).
        is_core = cb_name is not None
        codebase: Codebase | None = (
            doc.codebases[cb_name] if is_core else None
        )
        engine = engines_by_service[name]
        ctx = contexts[name]

        # 1. Start with engine defaults — these always land on the
        #    engine's default target.
        default_target = engine.default_target(foundation)

        # Mod 138: fail loud on an inert `defaults.elastic` key. The ECS
        # task-definition renderer reads a NAMED, closed set of keys off the
        # merged body (emit/hcl.py::TASK_DEF_DEFAULT_READ_KEYS) — it does NOT
        # merge the block generically the way the fixed compose path does. A
        # key outside that set would fall on the floor with no warning (mod
        # 127's healthCheck near-miss: it would have shipped a fleet with no
        # container probe). Scope: only the ECS task-definition path, so
        # backing engines' rich defaults.elastic (RDS instance_class, storage,
        # encryption, ...) route to their own renderers and are untouched. The
        # import is function-local to avoid the compile.py <-> emit.hcl import
        # cycle (same idiom as the emit imports further down this module).
        if foundation == "elastic" and default_target == "task_definition":
            from docex.emit.hcl import TASK_DEF_DEFAULT_READ_KEYS
            stray = set(engine.defaults_for("elastic")) - TASK_DEF_DEFAULT_READ_KEYS
            if stray:
                raise ValidationError([ValidationIssue(
                    rule="rule_elastic_defaults_unread_key",
                    message=(
                        f"engine {engine.engine!r} of role {engine.role!r}: "
                        f"defaults.elastic contains key(s) {sorted(stray)} that "
                        f"the ECS task-definition renderer does not read. It "
                        f"reads only {sorted(TASK_DEF_DEFAULT_READ_KEYS)}. "
                        f"Remove the key(s), or route them through a `fields:` "
                        f"translation with a `target:`."
                    ),
                    where=f"tables/roles/{engine.role}.yml defaults.elastic",
                )])

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
            if fname == "schedules":
                # Mod 115: the clock `schedules` map is carried onto the
                # compiled service (below) and delivered procedurally by the
                # emitters; its translation bodies are empty markers on both
                # foundations, so routing it here is a no-op. Skip it.
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

        # The CICL path errors about this emitted service point at.
        where_path = (
            f"codebases.{cb_name}.core_services.{svc_name}" if is_core
            else f"backing_services.{name}"
        )

        # 3. Apply per-foundation invariants and image refs.
        if foundation == "fixed":
            body = _apply_fixed_invariants(body, svc, ctx)
            if is_core:
                # WHY `cb_name`, not `name`: the image is built from the
                # CODEBASE, once, and every core service of that codebase
                # runs it. Passing the two-segment compiled identity here
                # would make the deploy pull `<proj>/api-web:<ver>` while
                # containerize.py pushed `<proj>/api:<ver>`. Mod 096.
                body["image"] = _image_ref(
                    doc.container_registry, project_name, cb_name,
                    project_version, env=env, foundation=foundation,
                )
                body = _deep_merge(body, _resources_to_fixed(svc.resources))
                body["command"] = svc.command
                # Core services never publish a host port. A `web` core
                # service is reached through the reverse proxy over the docker
                # network; a non-web core service's port (e.g. a worker's
                # health port) is probed from inside the netns by the container
                # healthcheck and reached by a sibling over the internal
                # network. Neither path needs a host publish, elastic never
                # published one, and publishing would collide across the
                # workers of two codebases sharing a port in `dev`. Backing
                # services keep their publish (handled by their own
                # transfer-table bodies). Mod 096.
        else:  # elastic
            body = _apply_elastic_invariants(
                body, svc, ctx,
                is_core=is_core,
                elastic_dests=list((engine.emits or {}).get("elastic", [])),
            )
            if is_core:
                # See the fixed branch — keyed on the codebase, never the
                # compiled identity.
                body["image"] = _image_ref(
                    doc.container_registry, project_name, cb_name,
                    project_version, env=env, foundation=foundation,
                )
                # Mod 055: only long-running services (those that emit an
                # `ecs_service`) carry a paired OTel sidecar, so only they
                # need the sidecar's resource overhead folded into the
                # task-level totals. Accounting for one where there is none
                # would over-allocate Fargate and emit a misleading
                # rounding note.
                has_sidecar = "ecs_service" in (engine.emits or {}).get(
                    "elastic", []
                )
                body = _deep_merge(body, _resources_to_elastic(
                    svc.resources, service_name=name, is_core=has_sidecar,
                    notes_seen=notes_seen, where=f"{where_path}.resources",
                ))
                body["command"] = svc.command

        # 4. Resolve `env:` block on core services (magic refs live here).
        #
        # Two surfaces are built from the same tail so they cannot drift:
        #   env_block    — the core service's EFFECTIVE env (the codebase-
        #                  level `env:` with the core service's own block
        #                  merged over it). What the container runs with.
        #   codebase_env — the CODEBASE-scoped surface: the codebase-level
        #                  `env:` only. What per-codebase operations (the
        #                  elastic migrate task definition; Mod 099's exec
        #                  service) run with, because `migrate.sh` may depend
        #                  only on codebase-scoped env.
        def _build_env_surface(
            source: dict[str, Any],
            *,
            otel_service_name: str,
            otel_service: str | None,
        ) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for ekey in sorted(source):
                val = source[ekey]
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
                                f"core service {name!r} env {ekey!r} embeds a "
                                f"secret inside a composed value "
                                f"({rendered.value!r}). Reference the discrete "
                                f"parts (host/port/db/user/password) and compose "
                                f"the handle in the app at startup."
                            ),
                            where=f"{where_path}.env.{ekey}",
                        )])
                    out[ekey] = (
                        HCLLiteral(rendered.value) if rendered.raw_hcl else rendered.value
                    )
                else:
                    out[ekey] = val
            # Codebase `secrets:` are operator-supplied secret env vars with
            # no in-project source (API keys, tokens). Wire each as a self-
            # referential runtime ref so the existing secret path delivers it —
            # compose ${KEY} (fixed) / ECS secrets[] (elastic). Validation
            # forbids a key in both env and secrets.
            for ekey in sorted(codebase.secrets):
                out[ekey] = f"$[{ekey}]"
            # Codebase `config:` are declared, non-secret, per-env values.
            # Wired exactly like secrets — a self-referential runtime ref that
            # the existing secret path delivers (compose ${KEY} / ECS secrets[]).
            # The value is non-secret (String on elastic); the compiled shape is
            # identical to a secret. See config_and_secrets.md.
            for ekey in sorted(codebase.config or {}):
                out[ekey] = f"$[{ekey}]"
            # Doctrine-injected: PROJECT_VERSION on every core service.
            # See transfer_tables.md § Per-core-service env (both foundations).
            # Plain string from project.yml — not a magic ref, not a secret.
            # The validator forbids the project from declaring this key itself.
            out["PROJECT_VERSION"] = project_version
            # Doctrine-injected OTel env vars on every core service. See
            # transfer_tables.md § Per-core-service env (both foundations). Same on
            # fixed and elastic — the paired sidecar shares the core service's
            # network namespace on both, so localhost:4318 is universal.
            # Mod 096: the service name is the two-segment compiled identity,
            # so telemetry distinguishes `api-web` from `api-worker`. Mod 102
            # made it a parameter — see the two call sites below for why the
            # per-codebase surface de-qualifies it.
            out["OTEL_SERVICE_NAME"] = otel_service_name
            out["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
            out["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            # Mod 102: `docex.codebase` and `docex.service` carry the
            # two authoring names, even though `service.name` already fuses
            # them.
            #
            # WHY both, given the fused name: both axes must be independently
            # QUERYABLE ("every core service of the `api` codebase", "every
            # `worker` across all codebases"), and a hyphenated `service.name`
            # does not decompose — `_SERVICE_NAME_RE` (cicl/model.py:24) admits
            # `-` inside BOTH segments, so `api-web-v2` has no recoverable
            # split point. Two attributes make the decomposition explicit
            # rather than guessable.
            #
            # The `docex.` vendor prefix follows the `docex.project`
            # docker-label precedent (emit/compose.py:67-79); OTel has no
            # semantic-convention attribute for either axis. Values are the raw
            # AUTHORING names, not DNS labels: these are query keys a developer
            # greps `infra.yml` for, and `_SERVICE_NAME_RE` admits neither `,`
            # nor `=`, so the attribute encoding is safe by construction.
            attrs = [
                f"service.namespace={project_name}",
                f"service.version={project_version}",
                f"deployment.environment.name={env}",
                f"docex.codebase={cb_name}",
            ]
            if otel_service is not None:
                # `docex.service` is present IFF the emitter is a declared
                # core service. Its absence is the signal that this is a
                # per-codebase artifact (the exec container, the migrate task
                # definition) — NOT an omission to be filled in.
                attrs.append(f"docex.service={otel_service}")
            out["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(attrs)
            return out

        env_block: dict[str, Any] = {}
        codebase_env: dict[str, Any] = {}
        if is_core:
            effective_env = {**(codebase.env or {}), **(svc.env or {})}
            env_block = _build_env_surface(
                effective_env,
                otel_service_name=name,
                otel_service=svc_name,
            )
            # Mod 102: built through the helper UNCONDITIONALLY. There used to
            # be a `dict(env_block)` shortcut here, taken whenever the core
            # service declared no `env:` overlay, because the two surfaces were
            # then identical. DO NOT restore it: this mod falsified that
            # premise.
            # The surfaces now differ in `OTEL_SERVICE_NAME` and
            # `OTEL_RESOURCE_ATTRIBUTES` even with no overlay, because the
            # codebase-scoped surface de-qualifies its telemetry identity.
            #
            # WHY de-qualify: this surface feeds PER-CODEBASE artifacts (the
            # fixed exec service, emit/compose.py:696; the elastic migrate task
            # definition, emit/hcl.py:562), which read it off `svcs[0]` —
            # sorted by compiled name. Carrying a service segment there means a
            # migration reports the name of, say, a cron job, and renaming a
            # core service silently changes the identity a migration reports.
            # De-qualifying removes the choice rather than making it better.
            #
            # Resolving the codebase-level block a second time is not a new code
            # path — it already happened whenever a core service declared an
            # overlay.
            # `MagicRefResolver.deps` is append-only with no consumer and the
            # cycle guard is discarded in a `finally`.
            codebase_env = _build_env_surface(
                dict(codebase.env or {}),
                otel_service_name=cb_name,
                otel_service=None,
            )

        networks_seen.update(svc.networks)
        compiled_services[name] = CompiledService(
            name=name,
            role=svc.role,
            engine=engine.engine,
            foundation=foundation,
            is_core=is_core,
            global_name=ctx["global_service_name"],
            body=body,
            networks=list(svc.networks),
            uses=(list(svc.uses or []) if is_core else []),
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
                name, svc.networks, subdomain, default_service_compiled,
                env=env, bare_project=bare_project, policy=http_host_policy,
            ),
            schema_owned_by=getattr(svc, "schema_owned_by", None),
            # Mod 099: an honest CODEBASE property — "this compiled service's
            # codebase owns a backing DB schema" — and therefore true of EVERY
            # core service of that codebase. Through Mod 096 it was set on
            # exactly one "carrier" core service, picked by a now-deleted
            # "pick one core service" bridge, so that the once-per-codebase
            # migrate emissions it gates fired
            # once. That invariant is now provided STRUCTURALLY by
            # `group_by_codebase`: every consumer groups first and reads the
            # flag off the group. Nothing downstream may reintroduce a
            # "pick one core service" read of this flag — if you need the one
            # container that stands in for a codebase, the answer is the exec
            # service, not a core service.
            schema_owned_by_db=(is_core and cb_name in core_owning_schema),
            target_extras=target_extras,
            emits={fnd: list(dests) for fnd, dests in (engine.emits or {}).items()},
            persistent_storage=(
                dict(engine.persistent_storage)
                if engine.persistent_storage
                else None
            ),
            # Mod 115. Passed through only when it is a `str -> str` mapping:
            # validation has already rejected anything else, and a malformed
            # value must never reach an emitter (which would render it into a
            # container's env).
            schedules=_clock_schedules((svc.model_extra or {}).get("schedules")),
            codebase=cb_name,
            service=svc_name,
            codebase_global_name=(
                _global_service_name(
                    project_name, env, cb_name,
                    tables.naming_policies.get(engine.naming),
                    slot=slot,
                ) if is_core else None
            ),
            codebase_env=codebase_env,
            replicas=(svc.replicas if is_core else 1),
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
        slot=slot,
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
    shape_name (``codebase``/``backing_service`` by ``is_core``) and a
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
        codebase=ctx.get("codebase_name", ctx["name"]),
        role=ctx["role_name"],
        # Mod 096: None for a backing service, which has no service
        # dimension — standard_tags then omits the key entirely, so backing
        # tag blocks are byte-identical to their pre-expansion form.
        service=ctx.get("service"),
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


def env_subdomain_for(ctx: Any, env: str) -> str:
    """The env's bare subdomain ``<env>.<project>.<apex_domain>``, taken from the
    compiler-owned ``CompiledEnv.subdomain`` rather than re-derived by hand.

    Consolidates the two former hand-rolled copies (``aggregate._host_for`` and
    ``up.py``) onto the single derivation the compiler owns (``_env_subdomain``).
    """
    compiled = compile_env(
        ctx.infra,
        ctx.transfer_tables,
        env=env,
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )
    return compiled.subdomain


def _emit_env_dir(
    compiled: CompiledEnv, env_dir: Path, *, naming_policies: Any
) -> int:
    """Emit one compiled env's artifacts into ``env_dir``. Returns files written.

    Shared by :func:`run_compile` (slot 1, per env, into ``infra/output/<env>/``)
    and :func:`compile_slot` (any slot, into ``.docex/slots/<env>/<k>/``). It
    emits ONLY the env-tier artifacts; the project tier (networks/traefik) is
    emitted once by ``run_compile`` and is slot-shared (Mod 153).
    """
    from docex.emit.compose import emit_compose
    from docex.emit.hcl import emit_hcl
    from docex.emit.ansible import emit_ansible
    from docex.emit.schedules import has_clock, render_schedules_file

    env_dir.mkdir(parents=True, exist_ok=True)
    files = 0
    # Mod 115: the clock schedules artifact is written on both foundations and
    # in ALL FOUR envs, even though NOTHING mounts or reads it. It is the
    # *visibility* half of clock.md § How the schedule reaches the container;
    # `DOCEX_SCHEDULES_YAML` (emit/schedules.py) is the *delivery* half. Do not
    # add a `test`-env guard, and do not skip on the grounds that the env var
    # already carries the payload.
    if has_clock(compiled):
        (env_dir / "schedules.yml").write_text(render_schedules_file(compiled))
        files += 1
    if compiled.foundation == "fixed":
        emit_compose(compiled, env_dir / "docker-compose.yml")
        files += 1
        if compiled.env in ("stage", "prod"):
            emit_ansible(compiled, env_dir)
            files += 3  # playbook.yml, inventory.yml, ansible.cfg
    else:
        emit_hcl(compiled, env_dir / "main.tf", naming_policies=naming_policies)
        files += 1
    return files


def compile_slot(ctx: Any, env: str, slot: int) -> Path:
    """Compile ONE env at ``slot`` and emit it. Returns the output dir.

    slot == 1 -> ``infra/output/<env>/`` (identical to run_compile's per-env
                 path).
    slot  > 1 -> ``.docex/slots/<env>/<slot>/`` — ephemeral, machine-local
                 scratch (beside ``.docex/runs/`` and ``.docex/checks/``),
                 gitignored, never in the tracked ``infra/output/`` tree.

    The env-agnostic primitive Mod 154's orchestration and the slot tests call.
    No CLI verb reaches it this mod.
    """
    from docex.errors import InfraFileError
    if ctx.infra is None:
        raise InfraFileError(
            f"{ctx.project_root}/infra/infra.yml: file missing — compile "
            "requires an infra.yml"
        )
    issues = validate_document(ctx.infra, ctx.transfer_tables)
    if issues:
        raise ValidationError(issues)

    if slot == 1:
        env_dir = ctx.project_root / "infra" / "output" / env
    else:
        env_dir = ctx.project_root / ".docex" / "slots" / env / str(slot)

    compiled = compile_env(
        ctx.infra, ctx.transfer_tables, env=env,
        project_name=ctx.project.name, project_version=ctx.project.version,
        slot=slot,
    )
    _emit_env_dir(
        compiled, env_dir,
        naming_policies=ctx.transfer_tables.naming_policies,
    )
    return env_dir


def run_compile(ctx: Any) -> int:
    """Compile every env and emit outputs. Returns process exit code."""
    from docex.emit.compose import emit_project_compose
    from docex.emit.hcl import emit_hcl_project
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

        compiled = compile_env(
            ctx.infra,
            ctx.transfer_tables,
            env=env,
            project_name=ctx.project.name,
            project_version=ctx.project.version,
            notes_seen=notes_seen,
        )
        compiled_envs.append(compiled)

        # Mod 152: the per-env emit body is now shared with `compile_slot` via
        # `_emit_env_dir` (which also mkdir's env_dir). `run_compile` stays slot
        # 1 into `infra/output/<env>/`, behaviorally unchanged.
        files_written += _emit_env_dir(
            compiled, env_dir,
            naming_policies=ctx.transfer_tables.naming_policies,
        )

    # Mod 035: project-tier output is split by side. Both sides emit on
    # every project. The development side is always fixed-style (compose);
    # the production side switches by foundation (compose for fixed, HCL
    # for elastic). Mod 035 emits networks only; the per-project traefik
    # and ansible artifacts land in mod 036.
    # Mod 046: project-tier compose names (the three `-web` networks, the
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
            codebase_names=list(ctx.infra.codebases.keys()),
            naming_policies=ctx.transfer_tables.naming_policies,
            out_path=prod_project_dir / "main.tf",
            reverse_proxy=ctx.infra.reverse_proxy,
        )
        files_written += 1

    print(
        f"Compiled {len(_ENVS)} environments. {files_written} files written "
        f"under infra/output/."
    )
    return 0
