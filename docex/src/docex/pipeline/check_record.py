"""The ``.docex/checks/`` provenance record — what a passing ``check`` blessed.

Written by ``check`` on a fully-green run; read by ``merge`` to decide whether it
may skip its defensive recheck (see [cicd.md § Merge] and [overview.md]). This is
a **performance cache, never a correctness gate**: every read degrades safely to
``None`` (missing dir/file, unreadable, or corrupt JSON), so a missing record
forces ``merge`` to run the full recheck.

Distinct from the SC3 job record under ``.docex/runs/``: ``runs/`` answers "did
this invocation pass"; ``checks/`` answers "what tree a passing check blessed, for
``merge`` to trust forward." One latest-wins file — ``merge`` only ever trusts the
most recent green.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


CHECKS_RELDIR = ".docex/checks"
RECORD_FILENAME = "latest.json"


@dataclass
class CheckRecord:
    """What a successful ``check`` validated. Exactly SC4's five fields.

    ``merged_tree_sha`` is the git tree SHA of the validated (rebased) worktree —
    the authoritative "what was tested", recorded for audit and a possible future
    stronger comparison. It is NOT part of the v1 commit-based skip predicate.
    """

    feature_tip: str
    origin_main: str
    merged_tree_sha: str
    checked_at: str
    docex_version: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "CheckRecord":
        raw = json.loads(text)
        return cls(
            feature_tip=raw["feature_tip"],
            origin_main=raw["origin_main"],
            merged_tree_sha=raw["merged_tree_sha"],
            checked_at=raw["checked_at"],
            docex_version=raw["docex_version"],
        )


def now_iso() -> str:
    """UTC timestamp, ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def checks_dir(project_root: Path) -> Path:
    return project_root / ".docex" / "checks"


def record_path(project_root: Path) -> Path:
    return checks_dir(project_root) / RECORD_FILENAME


def write_check_record(project_root: Path, rec: CheckRecord) -> None:
    """Atomically write the latest-wins record (temp file + ``os.replace``)."""
    d = checks_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{RECORD_FILENAME}.{secrets.token_hex(4)}.tmp"
    tmp.write_text(rec.to_json())
    os.replace(tmp, record_path(project_root))


def read_check_record(project_root: Path) -> CheckRecord | None:
    """Return the recorded provenance, or ``None`` if absent/unreadable/corrupt.

    Degrade-safe by design: any failure ⇒ ``None`` ⇒ ``merge`` runs the full
    recheck (the safe default).
    """
    try:
        text = record_path(project_root).read_text()
    except OSError:
        return None
    try:
        return CheckRecord.from_json(text)
    except (ValueError, KeyError):
        return None
