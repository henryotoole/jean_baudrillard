"""Standing consumer for the doctrine_excerpts artifact.

`docex why <resource>` serves prose keyed by `doctrine_excerpts/index.yml`.
That artifact has no compile/runtime consumer, so it drifts silently — this
is the check that catches a key that no longer names a `shape.md` resource
(the `network_web` / `vpc` class of drift). Pure unit test: reads two files,
asserts. No docker, no AWS.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_EXCERPTS = _REPO / "docex" / "doctrine_excerpts"
_INDEX = _EXCERPTS / "index.yml"
_SHAPE = _REPO / "doctrine" / "infrastructure" / "shape.md"

# Keys deliberately indexed although they are not shape.md [resource] tokens.
# codebase: the unit-of-code concept (deployed nouns are core_service /
#   backing_service). secrets: a source of the configurable_vars resource.
EXCEPTIONS = {"codebase", "secrets"}

_BRACKET_RE = re.compile(r"\[([a-z][a-z0-9_]*)\]")


def _shape_resources() -> set[str]:
    """Resource nouns named in shape.md: [bracket] tokens plus table-row
    names (aws_account / ecs_cluster appear only as table rows)."""
    text = _SHAPE.read_text()
    resources = set(_BRACKET_RE.findall(text))
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|", 1)[0].strip()
        if re.fullmatch(r"[a-z][a-z0-9_]*", first):
            resources.add(first)
    return resources


def _index() -> dict[str, str]:
    return yaml.safe_load(_INDEX.read_text())


def test_every_index_key_resolves_to_a_shape_resource() -> None:
    resources = _shape_resources()
    unknown = {k for k in _index() if k not in resources and k not in EXCEPTIONS}
    assert not unknown, (
        "index.yml keys not found as a shape.md [resource] token (nor a "
        f"documented exception {sorted(EXCEPTIONS)}): {sorted(unknown)}"
    )


def test_every_index_value_file_exists() -> None:
    missing = {k: v for k, v in _index().items() if not (_EXCERPTS / v).is_file()}
    assert not missing, f"index.yml points at missing files: {missing}"


def test_no_orphan_excerpt_files() -> None:
    referenced = set(_index().values())
    on_disk = {p.name for p in _EXCERPTS.glob("*.md")}
    orphans = on_disk - referenced
    assert not orphans, (
        f"excerpt .md files not referenced by any index.yml key: {sorted(orphans)}"
    )
