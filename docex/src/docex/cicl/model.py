"""Pydantic v2 schema for ``infra.yml`` (CICL).

Cross-document validation (depends_on graph, magic-ref resolution,
container_registry-on-fixed, etc.) lives in ``compile.py`` — this
module covers only what can be checked from a single ``infra.yml`` in
isolation. See ``cicl.md`` for the full validation rules list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Memory string: decimal MB or GB only. See cicl.md § Resources.
_MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(MB|GB)$")
_DISK_RE = _MEMORY_RE  # same format

# Service-name pattern. Underscores or hyphens, letters, digits. Keep
# permissive; engine ``naming`` rules normalize on emit.
_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

# The one generation of the CICL format this docex compiles. Rule 21's
# validator and rollback's pre-flight precondition both compare against
# it — WHY: two literals for one fact would drift at the worst possible
# moment, the next CICL generation. See cicl.md § CICL Version.
CURRENT_CICL_VERSION = "2"


@dataclass(frozen=True)
class ProcessRef:
    """A reference to one process type of one core service.

    Dots for reference, hyphens for emission (cicl.md § Dots for reference,
    hyphens for emission). Authoring and reference forms — ``consumes:``
    targets, ``domain_default_process``, magic refs, ``describe`` node ids —
    are dotted; emitted data-plane names are hyphenated. This type is the one
    place that rule is expressed.
    """

    service: str
    process: str

    @classmethod
    def parse(cls, raw: str) -> "ProcessRef":
        """Parse ``"api.web"``. A bare name is an error, not shorthand."""
        parts = raw.split(".")
        if len(parts) != 2 or not all(p.strip() for p in parts):
            raise ValueError(
                f"{raw!r} is not a valid process reference. The form is "
                f"'<service>.<process>' (e.g. 'api.web'). A bare core service "
                f"name is illegal, not shorthand: a codebase has no single "
                f"boundary. See cicl.md § Magic Refs."
            )
        return cls(service=parts[0], process=parts[1])

    @property
    def dotted(self) -> str:
        return f"{self.service}.{self.process}"

    @property
    def compiled(self) -> str:
        """The two-segment compiled identity — ``CompiledService.name``."""
        return f"{self.service}-{self.process}"


class ProjectManifest(BaseModel):
    """Schema of ``project.yml`` — small and stable."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    docex_version: str


class GPUSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1)


class Resources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu: float = Field(gt=0)
    memory: str
    disk: str | None = None
    gpu: GPUSpec | None = None

    @model_validator(mode="after")
    def _validate_units(self) -> "Resources":
        if not _MEMORY_RE.match(self.memory):
            raise ValueError(
                f"memory must match '<number><MB|GB>' (decimal units only); "
                f"got {self.memory!r}"
            )
        if self.disk is not None and not _DISK_RE.match(self.disk):
            raise ValueError(
                f"disk must match '<number><MB|GB>' (decimal units only); "
                f"got {self.disk!r}"
            )
        return self


class ProcessType(BaseModel):
    """One named way of invoking a core service's build artifact.

    Its own role, command, resources, networks and port. One codebase, one
    image, N process types. See cicl.md § Process Types.
    """

    # Role-specific fields (health_check_path, schedule, ...) land in
    # model_extra, exactly as they do on _ServiceBase today. Role-specific
    # fields follow `role`, which is invocation-determined, so they are
    # process-scoped by derivation (cicl.md § Field scoping).
    model_config = ConfigDict(extra="allow")

    role: str
    # Rule 23. Required on EVERY process type including `web`: with several
    # process types sharing one image, at most one could inherit the
    # Dockerfile CMD and "which one" is an ambiguity worth deleting.
    command: str | list[str]
    networks: list[str] = Field(min_length=1)
    resources: Resources
    port: int | None = None
    # Rule 24: backing services only. A core process type here is an error.
    depends_on: list[str] = Field(default_factory=list)
    # Rule 25: core process types only, dotted and fully qualified
    # ("api.worker"). The interface half of the split `depends_on` used to
    # conflate — `depends_on` is a readiness gate over backing services,
    # `consumes` is an interface edge between core process types. CI-only:
    # contracts, the health fan-out, and rule 7 read it; nothing is emitted
    # from it. See cicl.md § Consumes Relationships.
    consumes: list[str] = Field(default_factory=list)
    # Carried onto CompiledService as the DECLARED value; `effective_replicas`
    # (compile.py) applies the prod-only clamp. Read by the fixed compose
    # unroll and the elastic ECS `desired_count` (Mod 100).
    replicas: int = Field(default=1, ge=1)
    # The only field valid at both levels. A process type's effective env is
    # the service-level block merged under its own (cicl.md § Field scoping).
    env: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_command_nonempty(self) -> "ProcessType":
        if isinstance(self.command, str):
            if not self.command.strip():
                raise ValueError("command must not be empty")
        elif not self.command:
            raise ValueError("command must not be an empty list")
        return self

    def consumes_refs(self) -> set[str]:
        """This process type's ``consumes:`` targets, normalized to dotted form.

        Entries that do not parse are dropped rather than passed through: rule 25
        reports each one once, and a malformed entry must not ALSO surface
        downstream — as a mystifying rule-7 miss, or as a missing contract for a
        target the author plainly named. Both the validator (rule 7) and
        ``check.py``'s contract / health gates read through here, so the
        dots-for-reference parse lives in exactly one place.
        """
        out: set[str] = set()
        for raw in (self.consumes or []):
            try:
                out.add(ProcessRef.parse(raw).dotted)
            except ValueError:
                continue
        return out


# Both core and backing services share these base fields.
class _ServiceBase(BaseModel):
    """Fields shared by both core and backing services."""

    # Allow role-specific extras (e.g. ``versioning: true`` for object_store).
    model_config = ConfigDict(extra="allow")

    role: str
    networks: list[str] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    port: int | None = None


# Fields that moved from the core service to the process type in CICL v2.
# Used only to produce a targeted migration error — see below.
_MOVED_TO_PROCESS = (
    "role", "command", "networks", "resources", "port",
    "depends_on", "replicas",
)


class CoreService(BaseModel):
    """A core service in ``infra.yml``: one codebase, one build artifact.

    The service level accepts only ``{processes, secrets, config, env}``
    (rule 22). Everything invocation-determined lives on a ProcessType.
    """

    model_config = ConfigDict(extra="forbid")

    # Rule 22: required and non-empty.
    processes: dict[str, ProcessType] = Field(min_length=1)
    env: dict[str, Any] = Field(default_factory=dict)
    # Operator-supplied secret env vars with no in-project source (API keys,
    # tokens). KEY -> human description. Surfaced via `docex secrets scaffold`
    # and wired into the container as a secret. See cicl.md.
    secrets: dict[str, str] = Field(default_factory=dict)
    # Declared, non-secret, per-env config values (e.g. a URL that differs by
    # environment). KEY -> human description. Each key is auto-injected into the
    # container as an env var of the same name, sourced from infra/config/<env>.env
    # (a plain SSM String, not SecureString, on elastic). See config_and_secrets.md.
    config: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_v1_shape(cls, data: Any) -> Any:
        # WHY: bare extra="forbid" says only "Extra inputs are not permitted",
        # which does not hint at the nesting. A stray service-level `role:` /
        # `resources:` / `command:` is THE migration mistake from CICL v1, so
        # it gets a message that names the fix.
        if not isinstance(data, dict):
            return data
        stray = sorted(k for k in _MOVED_TO_PROCESS if k in data)
        if stray:
            raise ValueError(
                f"{stray} moved from the core service to the process type in "
                f"CICL v2. Nest them under a named entry in a `processes:` "
                f"block. Only {{processes, secrets, config, env}} are valid "
                f"at the service level (cicl.md § Field scoping, rule 22). "
                f"See upgrades/upgrade_1.6.0.md."
            )
        return data


# Mod 099 deleted the "pick one process type to stand in for the codebase"
# bridge that Mod 096 planted here. Both of its consumers are gone: migration
# sizing is now the per-dimension max across the codebase's process types, and
# "which container represents this codebase" is answered by the emitted
# per-codebase exec service (`orchestrate/_common.py::exec_service_key`).
# Do not reintroduce it.


class BackingService(_ServiceBase):
    """A backing service in ``infra.yml``."""

    # ``engine`` is either a single string ("postgres") or a list of strings
    # (e.g. ["minio", "s3"] for object_store). The compiler resolves this
    # list against the target foundation by consulting each candidate's
    # ``foundation:`` declaration in the transfer table.
    engine: str | list[str]
    version: str | None = None
    schema_owned_by: str | None = None


class CICLDocument(BaseModel):
    """The parsed ``infra.yml``."""

    model_config = ConfigDict(extra="forbid")

    cicl_version: str
    foundation: Literal["fixed", "elastic"]
    # The bare apex domain (e.g. ``example.com`` or ``example.co.uk``).
    # Must NOT include a project subdomain — the project segment is derived
    # automatically from ``name`` in project.yml. The canonical service host
    # form is ``<service>.<env>.<project>.<apex_domain>``. See cicl.md § Domain.
    apex_domain: str
    # Elastic-only choice of reverse proxy. ``alb`` (default) provisions an
    # AWS ALB; ``ec2_traefik_eip`` / ``ec2_traefik_pip`` provision an EC2
    # instance running traefik backed by an Elastic IP or a regular Public
    # IP respectively. Rejected on fixed-foundation projects (validation
    # rule 18). See cicl.md § Reverse Proxy.
    reverse_proxy: Literal["alb", "ec2_traefik_eip", "ec2_traefik_pip"] | None = None
    container_registry: str | None = None
    # Documentary only — the git host and repo are prerequisite infrastructure;
    # docex doesn't act on this. Accepted so a project that follows the
    # cicl.md § "Git Repo URL" prose still compiles. See cicl.md.
    repo_url: str | None = None
    # The web *process type* mapped to the bare
    # ``<env>.<project>.<apex_domain>`` subdomain, named as a dotted
    # reference (e.g. ``api.web``). Other web process types live at
    # ``<service>-<process>.<env>.<project>.<apex_domain>`` — the canonical
    # host form. Optional; if unset, nothing occupies the bare subdomain.
    # See cicl.md § Domain.
    domain_default_process: str | None = None
    # The HTTPS URL of the project's observability backend (HyperDX).
    # Sidecars in stage/prod export OTLP signals here. Required on every
    # project — dev/test sidecars don't consume the URL but the field is
    # validated up-front so misconfigurations surface before stage release.
    # See doctrine/infrastructure/cicl.md § Observability Backend.
    observability_backend_url: str
    core_services: dict[str, CoreService] = Field(default_factory=dict)
    backing_services: dict[str, BackingService] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_cicl_version(self) -> "CICLDocument":
        # Rule 21. Rejected, not shimmed: a compatibility parser accepting
        # both forms would reintroduce the flat pre-`processes:` shape as a
        # permanent second code path, to serve a migration every project
        # performs exactly once. See cicl.md § CICL Version.
        if self.cicl_version == CURRENT_CICL_VERSION:
            return self
        if self.cicl_version == "1":
            raise ValueError(
                "cicl_version '1' is no longer supported. CICL v2 makes the "
                "`processes:` block mandatory on every core service and adds "
                "the `consumes` relation and four-segment core magic refs. "
                "Follow upgrades/upgrade_1.6.0.md to migrate this infra.yml, "
                "then set cicl_version: \"2\"."
            )
        raise ValueError(
            f"unknown cicl_version {self.cicl_version!r}; the current "
            f"generation of the CICL format is {CURRENT_CICL_VERSION!r}."
        )

    @model_validator(mode="after")
    def _validate_service_names(self) -> "CICLDocument":
        # Rule 5: names unique across services.
        names: set[str] = set()
        for name in list(self.core_services) + list(self.backing_services):
            if not _SERVICE_NAME_RE.match(name):
                raise ValueError(
                    f"service name {name!r} must start with a letter and "
                    "contain only letters, digits, '_' or '-'"
                )
            if name in names:
                raise ValueError(f"duplicate service name: {name!r}")
            names.add(name)
        # A process name is emitted as the second segment of a compiled
        # identity, so it is bound by exactly the same character rule as a
        # service name.
        for svc_name, svc in self.core_services.items():
            for proc_name in svc.processes:
                if not _SERVICE_NAME_RE.match(proc_name):
                    raise ValueError(
                        f"process name {proc_name!r} (on core service "
                        f"{svc_name!r}) must start with a letter and "
                        "contain only letters, digits, '_' or '-'"
                    )
        # Names unique across core+backing too.
        overlap = set(self.core_services) & set(self.backing_services)
        if overlap:
            raise ValueError(
                f"service name(s) appear in both core_services and "
                f"backing_services: {sorted(overlap)}"
            )
        return self

    @model_validator(mode="after")
    def _validate_observability_backend_url(self) -> "CICLDocument":
        try:
            parsed = urlparse(self.observability_backend_url)
        except Exception as exc:
            raise ValueError(
                f"observability_backend_url is not a parseable URL: "
                f"{self.observability_backend_url!r} ({exc})"
            )
        if parsed.scheme != "https":
            raise ValueError(
                f"observability_backend_url must use the https:// scheme; "
                f"got {self.observability_backend_url!r}. http:// is rejected "
                f"at compile time per doctrine/infrastructure/telemetry.md "
                f"§ Authentication — the API key flows in plaintext over "
                f"HTTPS, never in the clear."
            )
        if not parsed.netloc:
            raise ValueError(
                f"observability_backend_url has no host: "
                f"{self.observability_backend_url!r}"
            )
        return self

    # Convenience accessors -------------------------------------------------

    def all_services(self) -> dict[str, Any]:
        """Merged dict of all services keyed by name. Iteration order is
        core-first, then backing — useful for emit order, though callers
        that want full determinism should sort explicitly.

        This is the *authoring* view: authoring models keyed by authoring
        name. Core entries are :class:`CoreService` (which no longer shares
        a base with :class:`BackingService`), so a caller that needs
        ``role`` / ``networks`` / ``port`` wants :meth:`all_processes`.
        """
        merged: dict[str, Any] = {}
        merged.update(self.core_services)
        merged.update(self.backing_services)
        return merged

    def all_processes(self) -> list[tuple[str, str, CoreService, ProcessType]]:
        """Every ``(service_name, process_name, service, process)``, sorted.

        The process-level companion to :meth:`all_services`, which stays the
        *authoring* view (authoring models keyed by authoring name) because
        every validator depends on that.
        """
        out = []
        for svc_name in sorted(self.core_services):
            svc = self.core_services[svc_name]
            for proc_name in sorted(svc.processes):
                out.append((svc_name, proc_name, svc, svc.processes[proc_name]))
        return out
