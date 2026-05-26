"""Pydantic v2 schema for ``infra.yml`` (CICL).

Cross-document validation (depends_on graph, magic-ref resolution,
container_registry-on-fixed, etc.) lives in ``compile.py`` — this
module covers only what can be checked from a single ``infra.yml`` in
isolation. See ``cicl.md`` for the full validation rules list.
"""

from __future__ import annotations

import re
from typing import Any, Literal

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
    domain: str
    container_registry: str | None = None
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

    # Convenience accessors -------------------------------------------------

    def all_services(self) -> dict[str, _ServiceBase]:
        """Merged dict of all services keyed by name. Iteration order is
        core-first, then backing — useful for emit order, though callers
        that want full determinism should sort explicitly."""
        merged: dict[str, _ServiceBase] = {}
        merged.update(self.core_services)
        merged.update(self.backing_services)
        return merged
