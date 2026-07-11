"""Pydantic v2 schema for ``infra.yml`` (CICL).

Cross-document validation (depends_on graph, magic-ref resolution,
container_registry-on-fixed, etc.) lives in ``compile.py`` — this
module covers only what can be checked from a single ``infra.yml`` in
isolation. See ``cicl.md`` for the full validation rules list.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Memory string: decimal MB or GB only. See cicl.md § Resources.
_MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(MB|GB)$")
_DISK_RE = _MEMORY_RE  # same format

# Service-name pattern. Underscores or hyphens, letters, digits. Keep
# permissive; engine ``naming`` rules normalize on emit.
_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


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


# Both core and backing services share these base fields.
class _ServiceBase(BaseModel):
    """Fields shared by both core and backing services."""

    # Allow role-specific extras (e.g. ``versioning: true`` for object_store).
    model_config = ConfigDict(extra="allow")

    role: str
    networks: list[str] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    port: int | None = None


class CoreService(_ServiceBase):
    """A core service in ``infra.yml``."""

    # Pydantic's ``extra=allow`` means env etc. won't be schema-validated as
    # strict types. That's fine for v1 — magic refs in env values are
    # strings that the compiler resolves later. We model env explicitly so
    # the typical case is well-typed.
    resources: Resources
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
    replicas: int = Field(default=1, ge=1)
    command: str | list[str] | None = None


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
    # The web service mapped to the bare ``<env>.<project>.<apex_domain>``
    # subdomain. Other web services live at
    # ``<service>.<env>.<project>.<apex_domain>``. Optional; if unset,
    # nothing occupies the bare subdomain. See cicl.md § Domain.
    domain_default_service: str | None = None
    # The HTTPS URL of the project's observability backend (HyperDX).
    # Sidecars in stage/prod export OTLP signals here. Required on every
    # project — dev/test sidecars don't consume the URL but the field is
    # validated up-front so misconfigurations surface before stage release.
    # See doctrine/infrastructure/cicl.md § Observability Backend.
    observability_backend_url: str
    core_services: dict[str, CoreService] = Field(default_factory=dict)
    backing_services: dict[str, BackingService] = Field(default_factory=dict)

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

    def all_services(self) -> dict[str, _ServiceBase]:
        """Merged dict of all services keyed by name. Iteration order is
        core-first, then backing — useful for emit order, though callers
        that want full determinism should sort explicitly."""
        merged: dict[str, _ServiceBase] = {}
        merged.update(self.core_services)
        merged.update(self.backing_services)
        return merged
