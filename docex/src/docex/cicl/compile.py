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
from docex.cicl.fargate import fargate_pair
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


# Subdomain prefixes per env (from cicl.md § Domain).
_ENV_SUBDOMAIN_PREFIX = {
    "dev": "dev",
    "test": "test",
    "stage": "stage",
    "prod": "www",
}

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


def _resources_to_elastic(res: Resources, *, service_name: str) -> dict[str, Any]:
    """Translate a Resources block into Fargate task-definition HCL fields.

    Phase 4 enforces Fargate's hard constraints at compile time:
      - ``(cpu, memory)`` must be a valid pair from AWS's allow-list
        (delegated to :func:`fargate_pair`).
      - ``disk:`` must be in the inclusive range 21..200 GiB. Anything
        below 21 fails loudly here. ``disk:`` may be omitted, in which
        case ``ephemeral_storage`` is also omitted and Fargate uses its
        default 21 GiB allotment.
    """
    cpu_units, memory_mib = fargate_pair(
        res.cpu, res.memory, service_name=service_name
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


def _env_subdomain(domain: str, env: str) -> str:
    return f"{_ENV_SUBDOMAIN_PREFIX[env]}.{domain}"


def _dns_label(name: str) -> str:
    """A service name as a DNS label (underscores → hyphens, lowercased)."""
    return name.replace("_", "-").lower()


def _web_hosts(
    name: str, role: str, networks: list[str], subdomain: str,
    default_service: str | None,
) -> list[str]:
    """The public host(s) a web-network service is reachable at.

    Every web-network service gets ``<service>.<env_subdomain>``. The
    ``domain_default_service`` additionally answers at the bare
    ``<env_subdomain>``. Non-web services get no hosts. The
    ``reverse_proxy`` role is excluded — it *is* the edge router, not a
    routed target.
    """
    if role == "reverse_proxy" or "web" not in networks:
        return []
    per_service = f"{_dns_label(name)}.{subdomain}"
    if default_service is not None and name == default_service:
        return [subdomain, per_service]
    return [per_service]


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


@dataclass
class CompiledEnv:
    """All compiled state for a single environment."""

    env: str
    foundation: str
    domain: str
    subdomain: str
    project: str
    project_version: str
    container_registry: str | None
    services: dict[str, CompiledService]
    networks: set[str]  # short names, e.g. {"web", "internal"}


def compile_env(
    doc: CICLDocument,
    tables: TransferTables,
    *,
    env: str,
    project_name: str,
    project_version: str,
) -> CompiledEnv:
    """Compile a single environment in-memory."""
    foundation = _env_foundation(doc.foundation, env)
    subdomain = _env_subdomain(doc.domain, env)

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
            body = _apply_elastic_invariants(body, svc, ctx)
            if isinstance(svc, CoreService):
                body["image"] = _image_ref(
                    doc.container_registry, project_name, name, project_version,
                    env=env, foundation=foundation,
                )
                body = _deep_merge(body, _resources_to_elastic(svc.resources, service_name=name))
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
            # Doctrine-injected: PROJECT_VERSION on every core service.
            # See transfer_tables.md § Per-core-service env (both foundations).
            # Plain string from project.yml — not a magic ref, not a secret.
            # The validator forbids the project from declaring this key itself.
            env_block["PROJECT_VERSION"] = project_version

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
            port=svc.port,
            env=env_block,
            web_hosts=_web_hosts(
                name, svc.role, svc.networks, subdomain, doc.domain_default_service
            ),
            schema_owned_by=getattr(svc, "schema_owned_by", None),
            schema_owned_by_db=(is_core and name in core_owning_schema),
            target_extras=target_extras,
            emits={fnd: list(dests) for fnd, dests in (engine.emits or {}).items()},
        )

    return CompiledEnv(
        env=env,
        foundation=foundation,
        domain=doc.domain,
        subdomain=subdomain,
        project=project_name,
        project_version=project_version,
        container_registry=doc.container_registry,
        services=compiled_services,
        networks=networks_seen,
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


def _apply_elastic_invariants(
    body: dict[str, Any], svc: Any, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Apply per-resource elastic invariants (tags + identifier)."""
    out = dict(body)
    out["identifier"] = ctx["global_service_name"]
    out["tags"] = {
        "project": ctx["project_name"],
        "env": ctx["env_name"],
        "service": ctx["name"],
        "role": ctx["role_name"],
        "managed_by": "doctrine",
    }
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
    from docex.emit.compose import emit_compose
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

    for env in _ENVS:
        env_dir = output_root / env
        env_dir.mkdir(parents=True, exist_ok=True)

        compiled = compile_env(
            ctx.infra,
            ctx.transfer_tables,
            env=env,
            project_name=ctx.project.name,
            project_version=ctx.project.version,
        )
        compiled_envs.append(compiled)

        if compiled.foundation == "fixed":
            compose_path = env_dir / "docker-compose.yml"
            emit_compose(compiled, compose_path)
            files_written += 1
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

    # Project-tier HCL — only for elastic-foundation projects. The env-tier
    # HCL reads its outputs via terraform_remote_state, so this must exist
    # before any env-tier apply (docex bootstrap takes care of that).
    if ctx.infra.foundation == "elastic":
        project_dir = output_root / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        emit_hcl_project(
            project=ctx.project.name,
            project_version=ctx.project.version,
            domain=ctx.infra.domain,
            core_service_names=list(ctx.infra.core_services.keys()),
            naming_policies=ctx.transfer_tables.naming_policies,
            out_path=project_dir / "main.tf",
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
