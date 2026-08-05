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
class ServiceRef:
    """A reference to one core service of one codebase.

    Dots for reference, hyphens for emission (cicl.md § Dots for reference,
    hyphens for emission). Authoring and reference forms — ``consumes:``
    targets, ``domain_default_service``, magic refs, ``describe`` node ids —
    are dotted; emitted data-plane names are hyphenated. This type is the one
    place that rule is expressed.
    """

    codebase: str
    service: str

    @classmethod
    def parse(cls, raw: str) -> "ServiceRef":
        """Parse ``"api.web"``. A bare name is an error, not shorthand."""
        parts = raw.split(".")
        if len(parts) != 2 or not all(p.strip() for p in parts):
            raise ValueError(
                f"{raw!r} is not a valid core service reference. The form is "
                f"'<codebase>.<service>' (e.g. 'api.web'). A bare codebase "
                f"name is illegal, not shorthand: a codebase has no single "
                f"boundary. See cicl.md § Magic Refs."
            )
        return cls(codebase=parts[0], service=parts[1])

    @property
    def dotted(self) -> str:
        return f"{self.codebase}.{self.service}"

    @property
    def compiled(self) -> str:
        """The two-segment compiled identity — ``CompiledService.name``."""
        return f"{self.codebase}-{self.service}"


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


class CoreService(BaseModel):
    """One named way of invoking a codebase's build artifact.

    Its own role, command, resources, networks and port. One codebase, one
    image, N core services. See cicl.md § Core Services.
    """

    # Role-specific fields (health_check_path, schedule, ...) land in
    # model_extra, exactly as they do on _ServiceBase today. Role-specific
    # fields follow `role`, which is invocation-determined, so they are
    # core-service-scoped by derivation (cicl.md § Field scoping).
    model_config = ConfigDict(extra="allow")

    role: str
    # Rule 23. Required on EVERY core service including `web`: with several
    # core services sharing one image, at most one could inherit the
    # Dockerfile CMD and "which one" is an ambiguity worth deleting.
    command: str | list[str]
    networks: list[str] = Field(min_length=1)
    resources: Resources
    port: int | None = None
    # Rule 24: backing services only. A core service here is an error.
    depends_on: list[str] = Field(default_factory=list)
    # Rule 25: core service only, dotted and fully qualified
    # ("api.worker"). The interface half of the split `depends_on` used to
    # conflate — `depends_on` is a readiness gate over backing services,
    # `consumes` is an interface edge between core services. CI-only:
    # contracts, the health fan-out, and rule 7 read it; nothing is emitted
    # from it. See cicl.md § Consumes Relationships.
    consumes: list[str] = Field(default_factory=list)
    # Carried onto CompiledService as the DECLARED value; `effective_replicas`
    # (compile.py) applies the prod-only clamp. Read by the fixed compose
    # unroll and the elastic ECS `desired_count` (Mod 100).
    replicas: int = Field(default=1, ge=1)
    # The only field valid at both levels. A core service's effective env is
    # the codebase-level block merged under its own (cicl.md § Field scoping).
    env: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_command_nonempty(self) -> "CoreService":
        if isinstance(self.command, str):
            if not self.command.strip():
                raise ValueError("command must not be empty")
        elif not self.command:
            raise ValueError("command must not be an empty list")
        return self

    def consumes_refs(self) -> set[str]:
        """This core service's ``consumes:`` targets, normalized to dotted form.

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
                out.add(ServiceRef.parse(raw).dotted)
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


# Fields that moved from the codebase to the core service in CICL v2.
# Used only to produce a targeted migration error — see below.
_MOVED_TO_SERVICE = (
    "role", "command", "networks", "resources", "port",
    "depends_on", "replicas",
)


class Codebase(BaseModel):
    """A codebase in ``infra.yml``: one source tree, one build artifact.

    The codebase level accepts only ``{core_services, secrets, config, env}``
    (rule 22). Everything invocation-determined lives on a CoreService.
    """

    model_config = ConfigDict(extra="forbid")

    # Rule 22: required and non-empty.
    core_services: dict[str, CoreService] = Field(min_length=1)
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
        # which does not hint at the nesting. A stray codebase-level `role:` /
        # `resources:` / `command:` is THE migration mistake from CICL v1, so
        # it gets a message that names the fix.
        if not isinstance(data, dict):
            return data
        stray = sorted(k for k in _MOVED_TO_SERVICE if k in data)
        if stray:
            raise ValueError(
                f"{stray} moved from the codebase to the core service in "
                f"CICL v2. Nest them under a named entry in a `core_services:` "
                f"block. Only {{core_services, secrets, config, env}} are valid "
                f"at the codebase level (cicl.md § Field scoping, rule 22). "
                f"See upgrades/upgrade_1.6.0.md."
            )
        return data


# Mod 099 deleted the "pick one core service to stand in for the codebase"
# bridge that Mod 096 planted here. Both of its consumers are gone: migration
# sizing is now the per-dimension max across the codebase's core services, and
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
    # form is ``<codebase>-<service>.<env>.<project>.<apex_domain>``.
    # See cicl.md § Domain.
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
    # The web *core service* mapped to the bare
    # ``<env>.<project>.<apex_domain>`` subdomain, named as a dotted
    # reference (e.g. ``api.web``). Other web core services live at
    # ``<codebase>-<service>.<env>.<project>.<apex_domain>`` — the canonical
    # host form. Optional; if unset, nothing occupies the bare subdomain.
    # See cicl.md § Domain.
    domain_default_service: str | None = None
    # The HTTPS URL of the project's observability backend (HyperDX).
    # Sidecars in stage/prod export OTLP signals here. Required on every
    # project — dev/test sidecars don't consume the URL but the field is
    # validated up-front so misconfigurations surface before stage release.
    # See doctrine/infrastructure/cicl.md § Observability Backend.
    observability_backend_url: str
    codebases: dict[str, Codebase] = Field(default_factory=dict)
    backing_services: dict[str, BackingService] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _validate_cicl_version(cls, data: Any) -> Any:
        # Rule 21. Rejected, not shimmed: a compatibility parser accepting
        # both forms would reintroduce the flat pre-`core_services:` shape as a
        # permanent second code path, to serve a migration every project
        # performs exactly once. See cicl.md § CICL Version.
        #
        # WHY mode="before": a `mode="after"` validator runs only once every
        # nested field has validated, and a real v1 `infra.yml` fails inside
        # `Codebase` first — so the operator saw a wall of per-codebase
        # field-scoping errors and never this message, on the single error every
        # downstream project hits exactly once, while upgrading. Reading the raw
        # mapping fires before the nested models are built.
        if not isinstance(data, dict):
            return data
        version = data.get("cicl_version")
        # A non-str (unquoted `cicl_version: 2` arrives as an int) or an absent
        # key is left to normal field validation, which reports the type or
        # missing-field error. Only a well-formed string is judged here.
        if not isinstance(version, str) or version == CURRENT_CICL_VERSION:
            return data
        if version == "1":
            raise ValueError(
                "cicl_version '1' is no longer supported. The current generation "
                "nests a `core_services:` block under each entry in `codebases:`, "
                "and adds the `consumes` relation and five-segment core magic refs "
                "(${codebases.<cb>.core_services.<svc>.<part>}). Follow "
                "upgrades/upgrade_1.6.0.md then upgrades/upgrade_1.7.0.md to "
                "migrate this infra.yml, then set cicl_version: \"2\"."
            )
        raise ValueError(
            f"unknown cicl_version {version!r}; the current "
            f"generation of the CICL format is {CURRENT_CICL_VERSION!r}."
        )

    @model_validator(mode="after")
    def _validate_service_names(self) -> "CICLDocument":
        # Rule 5: names unique across services.
        names: set[str] = set()
        for name in list(self.codebases) + list(self.backing_services):
            if not _SERVICE_NAME_RE.match(name):
                raise ValueError(
                    f"service name {name!r} must start with a letter and "
                    "contain only letters, digits, '_' or '-'"
                )
            if name in names:
                raise ValueError(f"duplicate service name: {name!r}")
            names.add(name)
        # A core service name is emitted as the second segment of a compiled
        # identity, so it is bound by exactly the same character rule as a
        # codebase name.
        for cb_name, cb in self.codebases.items():
            for service_name in cb.core_services:
                if not _SERVICE_NAME_RE.match(service_name):
                    raise ValueError(
                        f"core service name {service_name!r} (on codebase "
                        f"{cb_name!r}) must start with a letter and "
                        "contain only letters, digits, '_' or '-'"
                    )
        # Names unique across core+backing too.
        overlap = set(self.codebases) & set(self.backing_services)
        if overlap:
            raise ValueError(
                f"service name(s) appear in both codebases and "
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

    def all_authored(self) -> dict[str, Any]:
        """Merged dict of every top-level authored entry, keyed by name.

        Iteration order is codebases-first, then backing services — useful for
        emit order, though callers wanting full determinism should sort.

        NOT named ``all_core_services``: it merges :class:`Codebase` entries with
        :class:`BackingService` entries, and a codebase is not a service. The
        two things it merges are exactly the two top-level maps an author
        writes, which is what the name states. A caller that wants the
        core-service-level view — ``role`` / ``networks`` / ``port`` / ``command`` —
        wants :meth:`all_core_services`.
        """
        merged: dict[str, Any] = {}
        merged.update(self.codebases)
        merged.update(self.backing_services)
        return merged

    def all_core_services(
        self,
    ) -> list[tuple[str, str, Codebase, CoreService]]:
        """Every ``(codebase_name, service_name, codebase, core_service)``, sorted.

        The core-service-level companion to :meth:`all_authored`, which stays the
        *authoring* view (authoring models keyed by authoring name) because
        every validator depends on that.
        """
        out = []
        for cb_name in sorted(self.codebases):
            cb = self.codebases[cb_name]
            for service_name in sorted(cb.core_services):
                out.append((cb_name, service_name, cb, cb.core_services[service_name]))
        return out
