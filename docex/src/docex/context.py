"""Project context loading.

A ``ProjectContext`` bundles everything subcommands need to do their
work: the project root, the parsed ``project.yml``, the parsed
``infra.yml``, and the loaded (bundled + project-local) transfer
tables. ``load_project_context`` is the single entry point.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console

from docex import __version__
from docex.cicl.model import CICLDocument, ProjectManifest
from docex.cicl.transfer import TransferTables, load_transfer_tables
from docex.errors import (
    InfraFileError,
    ProjectManifestError,
    ProjectNotFoundError,
)


@dataclass
class ProjectContext:
    """Everything subcommands need to read the project."""

    project_root: Path
    project: ProjectManifest
    transfer_tables: TransferTables
    # ``infra`` is allowed to be None for commands that don't need it (``why``).
    infra: CICLDocument | None = None


def _find_project_root(start: Path) -> Path:
    """Walk up from ``start`` looking for ``project.yml``."""
    here = start.resolve()
    while True:
        if (here / "project.yml").is_file():
            return here
        if here.parent == here:
            raise ProjectNotFoundError(
                f"no project.yml found in {start} or any parent directory"
            )
        here = here.parent


def _load_project_manifest(project_root: Path) -> ProjectManifest:
    path = project_root / "project.yml"
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ProjectManifestError(f"{path}: malformed YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProjectManifestError(
            f"{path}: expected a YAML mapping at the document root"
        )
    try:
        return ProjectManifest.model_validate(raw)
    except PydanticValidationError as exc:
        raise ProjectManifestError(f"{path}: {exc}") from exc


def _load_infra(project_root: Path) -> CICLDocument | None:
    """Load ``infra/infra.yml``; return None if missing.

    Callers that *require* the document (compile, describe) must check
    and raise themselves. ``why`` does not need it.
    """
    path = project_root / "infra" / "infra.yml"
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InfraFileError(f"{path}: malformed YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise InfraFileError(
            f"{path}: expected a YAML mapping at the document root"
        )
    try:
        return CICLDocument.model_validate(raw)
    except PydanticValidationError as exc:
        raise InfraFileError(f"{path}: {exc}") from exc


def _warn_on_version_mismatch(manifest: ProjectManifest) -> None:
    """Phase 1: warn-only on version mismatch. Enforcement is Phase 3."""
    if manifest.docex_version != __version__:
        Console(stderr=True).print(
            f"[yellow]warning:[/yellow] project pins docex_version "
            f"{manifest.docex_version!r}, but this is docex {__version__}. "
            "(this is a warning in Phase 1; will be enforced later.)"
        )


def load_project_context(cwd: Path | None = None) -> ProjectContext:
    """Discover and load everything subcommands need.

    Failure modes:
      - No ``project.yml`` → ``ProjectNotFoundError``
      - Malformed ``project.yml`` → ``ProjectManifestError``
      - Malformed ``infra/infra.yml`` → ``InfraFileError``
      - Missing ``infra/infra.yml`` → ``ProjectContext.infra`` is None
        (subcommands that need it must check explicitly).
    """
    cwd = cwd or Path(os.getcwd())
    project_root = _find_project_root(cwd)
    manifest = _load_project_manifest(project_root)
    _warn_on_version_mismatch(manifest)
    infra = _load_infra(project_root)
    tables = load_transfer_tables(project_root)
    return ProjectContext(
        project_root=project_root,
        project=manifest,
        transfer_tables=tables,
        infra=infra,
    )
