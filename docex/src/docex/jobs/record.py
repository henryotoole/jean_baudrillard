"""The on-disk run record — the durable **handle** for a job.

A handle is a directory ``<project_root>/.docex/runs/<id>/`` holding up to
four files:

======== ================================================ ===================
File     Written by                                       Read by
======== ================================================ ===================
meta.json foreground, at launch (immutable)               every verb; reaper
status.json the vessel (and the reaper, on orphan)        ``status``, ``ls``
exit      the vessel (terminal) OR the reaper (synthetic) ``result``, ``wait``
log       the vessel (stdout+stderr redirected here)      ``logs``, attach
======== ================================================ ===================

The ``exit`` file is the **authoritative terminal signal**: it is written
atomically (temp file + ``os.replace``) and survives both vessel teardown
and a killed foreground monitor. Every blocking ``wait`` and ``result``
keys on it. This is the exit-file half of the healthcheck liveness pattern
(``healthchecks.md § What the probe must actually check``); the
tick/staleness half is deliberately not used — a finite job differs from a
perpetual loop.

Every read degrades safely to ``None`` / ``[]`` rather than raising, so a
partially-written or absent record reads as "not found" instead of
crashing a verb.
"""

from __future__ import annotations

import enum
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


RUNS_RELDIR = ".docex/runs"

# The reaper's synthetic exit for a hard-killed vessel: 128 + 9 (SIGKILL),
# so ``docex job result`` reports something honest that reads as "killed"
# rather than an invented sentinel (ruling Q5).
ORPHAN_EXIT_CODE = 137


class Outcome(enum.Enum):
    """The reconciled state of a record against reality — the shared
    primitive ``job ls`` and the reaper both compute via ``classify``."""

    TERMINAL = "terminal"  # exit file present
    LIVE = "live"          # no exit file, vessel running
    ORPHAN = "orphan"      # no exit file, vessel dead/absent


@dataclass
class RunMeta:
    """Immutable launch metadata, written once at record creation."""

    id: str
    kind: str
    scope: str
    slot: int
    vessel_kind: str
    vessel_name: str
    created_at: str
    docex_version: str
    params: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RunMeta":
        raw = json.loads(text)
        return cls(
            id=raw["id"],
            kind=raw["kind"],
            scope=raw["scope"],
            slot=raw["slot"],
            vessel_kind=raw["vessel_kind"],
            vessel_name=raw["vessel_name"],
            created_at=raw["created_at"],
            docex_version=raw["docex_version"],
            params=raw.get("params") or {},
        )


@dataclass
class RunStatus:
    """Mutable progress record. ``state`` is one of
    ``launching | running | succeeded | failed | orphaned``."""

    state: str
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RunStatus":
        raw = json.loads(text)
        return cls(
            state=raw["state"],
            started_at=raw.get("started_at"),
            updated_at=raw.get("updated_at"),
            finished_at=raw.get("finished_at"),
            exit_code=raw.get("exit_code"),
        )


def now_iso() -> str:
    """UTC timestamp, ISO-8601. The one clock read for the whole substrate."""
    return datetime.now(timezone.utc).isoformat()


def runs_dir(project_root: Path) -> Path:
    return project_root / ".docex" / "runs"


def new_run_id() -> str:
    """A sortable, collision-free run id: ``YYYYMMDDThhmmssZ-<6hex>``.

    Lexicographically sortable so ``job ls`` orders by recency; the random
    suffix makes same-second launches collision-free.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def run_dir(project_root: Path, run_id: str) -> Path:
    return runs_dir(project_root) / run_id


def create_record(project_root: Path, meta: RunMeta) -> Path:
    """Create the run directory with ``meta.json`` + a launching status."""
    d = run_dir(project_root, meta.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(meta.to_json())
    (d / "status.json").write_text(
        RunStatus(state="launching", updated_at=meta.created_at).to_json()
    )
    return d


def read_meta(project_root: Path, run_id: str) -> RunMeta | None:
    try:
        return RunMeta.from_json((run_dir(project_root, run_id) / "meta.json").read_text())
    except (OSError, ValueError, KeyError):
        return None


def read_status(project_root: Path, run_id: str) -> RunStatus | None:
    try:
        return RunStatus.from_json(
            (run_dir(project_root, run_id) / "status.json").read_text()
        )
    except (OSError, ValueError, KeyError):
        return None


def write_status(project_root: Path, run_id: str, status: RunStatus) -> None:
    """Overwrite ``status.json``, bumping ``updated_at``."""
    status.updated_at = now_iso()
    d = run_dir(project_root, run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "status.json").write_text(status.to_json())


def exit_path(project_root: Path, run_id: str) -> Path:
    return run_dir(project_root, run_id) / "exit"


def log_path(project_root: Path, run_id: str) -> Path:
    return run_dir(project_root, run_id) / "log"


def read_exit(project_root: Path, run_id: str) -> int | None:
    """Parse the ``exit`` file; None if absent or unparseable."""
    try:
        text = exit_path(project_root, run_id).read_text().strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def write_exit_atomic(project_root: Path, run_id: str, code: int) -> None:
    """Write the exit code atomically — the authoritative terminal signal.

    Writes to a sibling temp file and ``os.replace``s it onto ``exit`` so a
    concurrent reader never sees a half-written value.
    """
    d = run_dir(project_root, run_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".exit.{secrets.token_hex(4)}.tmp"
    tmp.write_text(f"{code}\n")
    os.replace(tmp, d / "exit")


def list_run_ids(project_root: Path) -> list[str]:
    """Run ids under ``.docex/runs``, most recent first. Missing dir → ``[]``."""
    try:
        names = [p.name for p in runs_dir(project_root).iterdir() if p.is_dir()]
    except OSError:
        return []
    return sorted(names, reverse=True)


def classify(project_root: Path, run_id: str, docker) -> Outcome:
    """Reconcile a record against reality — the shared enumeration primitive.

    ``exit`` present → TERMINAL; else the vessel's liveness decides:
    running → LIVE, dead/absent → ORPHAN. An unreadable meta classifies
    ORPHAN (there is no vessel we can trust to be alive).
    """
    if read_exit(project_root, run_id) is not None:
        return Outcome.TERMINAL
    meta = read_meta(project_root, run_id)
    if meta is None:
        return Outcome.ORPHAN
    if docker.container_running(meta.vessel_name) is True:
        return Outcome.LIVE
    return Outcome.ORPHAN
