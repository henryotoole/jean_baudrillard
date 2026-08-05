#!/usr/bin/env python3
"""Chunk a project's source into subagent-sized units for the cohere sweep.

A cohere sweep must read most of the source, which on a large project exceeds a
single agent's context. This executor splits `core/*/src` deterministically along
the doctrine's known filestructure so each piece fits one subagent. It reads no
file contents — it sizes by character count (a stable proxy for tokens; code is
mostly ASCII, so bytes ≈ chars ≈ tokens × ~3.5) and emits a JSON map on stdout.

It is purely a CODE chunker: it does NOT pair chunks to docs. A service's doc
layout is irregular (especially non-hex frontends) and cannot be resolved into a
provably-complete file set, so doc selection is left to the skill-agent, which has
read all the planning docs and can curate the relevant set per chunk (see SKILL.md).
The `hints` block still offers structural code↔doc signals (undocumented code,
docs with no code) to help that curation.

A chunk takes one of these shapes, chosen by size:
  - the entire source                     (small projects — one subagent for all)
  - one or more whole codebases           (packed together up to the budget)
  - a subset of one codebase's hex modules (a codebase too big to fit whole)

Bounded contexts stay separate: hex modules from *different* codebases are never
mixed into one chunk. Whole *codebases* may share a chunk (the common "one big
codebase + a couple of tiny ones" pattern), and a single oversized codebase is split
into its own module chunks — never merged with another codebase's modules.

What counts as "source": an ALLOWLIST of the extensions of the doctrine's
supported languages (see languages.md). This is deliberate — a denylist can't
exclude compiled artifacts it doesn't anticipate (notably extensionless Go
binaries), whereas an allowlist counts only real source and ignores everything
else (`.pyc`, `.o`, `.dll`, `target/` blobs, …) for free. Extend SOURCE_EXTS if
the project's language set grows.

Usage:
  python3 executor/chunk_map.py --root <project-root> [--budget 200000]
The --root behavior matches word_count.py: omit it to search upward for project.yml.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_BUDGET_CHARS = 1_400_000  # ~400k tokens at ~3.5 chars/token; leaves subagent headroom
CHARS_PER_TOKEN = 3.5

# Source extensions for the doctrine's supported languages (languages.md):
# C++, C#, Go, JavaScript (+ TypeScript, in practice), Python, Rust. Plus .sql
# for in-tree schema. Anything not listed here — compiled artifacts, binaries,
# assets — is not counted, so we never mistake a build product for source.
SOURCE_EXTS = {
    ".py", ".pyi",                                  # Python
    ".go",                                          # Go
    ".rs",                                          # Rust
    ".cs",                                          # C#
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",  # JavaScript / TypeScript
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",  # C / C++
    ".sql",                                         # in-tree schema
}

# Pruned during the walk so we never descend into dependency/build trees — cheaper,
# and it keeps vendored third-party source (which matches SOURCE_EXTS) out of the count.
IGNORE_DIRS = {
    "__pycache__", ".git", "node_modules", "dist", "build", "target",
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "bin", "obj", "vendor", "coverage",
}


def find_project_root(start: Path) -> Path:
    """Walk upward from `start` to the first dir containing project.yml."""
    for candidate in [start, *start.parents]:
        if (candidate / "project.yml").is_file():
            return candidate
    sys.exit(
        f"error: no project.yml found in {start} or any parent. "
        "Run from inside a project, or pass --root."
    )


def _iter_source_files(path: Path):
    """Yield source files at/under `path`, skipping ignored dirs and non-source."""
    # Guard the walk root itself: the relative-parts check below can't see an
    # ignored name when it IS the root (e.g. a code_path pointing at node_modules).
    if path.is_dir() and path.name in IGNORE_DIRS:
        return
    if path.is_file():
        if path.suffix.lower() in SOURCE_EXTS:
            yield path
        return
    for p in path.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SOURCE_EXTS:
            continue
        if any(part in IGNORE_DIRS for part in p.relative_to(path).parts):
            continue
        yield p


def _chars(paths: list[Path]) -> int:
    return sum(f.stat().st_size for path in paths for f in _iter_source_files(path))


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _mds(directory: Path, recursive: bool) -> list[Path]:
    if not directory.is_dir():
        return []
    it = directory.rglob("*.md") if recursive else directory.glob("*.md")
    return sorted(it)


def _est_tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def _discover_services(root: Path) -> list[Path]:
    core = root / "core"
    if not core.is_dir():
        sys.exit(f"error: {core} does not exist — not a doctrine project layout.")
    return sorted(d for d in core.iterdir() if d.is_dir() and (d / "src").is_dir())


def _service_whole_unit(root: Path, svc_dir: Path) -> dict:
    """A whole service as one packable unit (used when it fits under the budget)."""
    src = svc_dir / "src"
    return {
        "name": svc_dir.name,
        "svc": svc_dir.name,
        "code": [src],
        "chars": _chars([src]),
    }


def _service_units(root: Path, svc_dir: Path) -> list[dict]:
    """Split one hex service into a shell unit + one unit per hex module."""
    svc = svc_dir.name
    src = svc_dir / "src"
    hex_dir = src / "hex"
    modules = [d for d in sorted(hex_dir.iterdir()) if d.is_dir()] if hex_dir.is_dir() else []

    # Shell = everything under src/ except the module dirs (root.py, shared/, util/,
    # any non-dir files sitting directly in hex/). It carries service-level docs.
    shell_paths: list[Path] = []
    for child in sorted(src.iterdir()):
        if child.name in IGNORE_DIRS:
            continue
        if child == hex_dir:
            shell_paths += [f for f in sorted(hex_dir.iterdir()) if not f.is_dir()]
        else:
            shell_paths.append(child)
    # Keep only paths that actually carry source — a code_path with no source is noise.
    shell_paths = [p for p in shell_paths if _chars([p]) > 0]

    units: list[dict] = []
    if shell_paths:
        units.append({
            "name": f"{svc}:_shell", "svc": svc, "code": shell_paths, "chars": _chars(shell_paths),
        })
    for m in modules:
        units.append({
            "name": f"{svc}:{m.name}", "svc": svc, "code": [m], "chars": _chars([m]),
        })
    return units


def _binpack(units: list[dict], budget: int) -> list[list[dict]]:
    """First-fit-decreasing: pack units into as few bins <= budget as possible.

    An oversized unit gets its own bin (flagged over_budget downstream) rather than
    being split — splitting a module across subagents would fragment the doc/code
    comparison it exists to enable.
    """
    bins: list[dict] = []  # {"units": [...], "chars": int}
    for u in sorted(units, key=lambda x: x["chars"], reverse=True):
        placed = False
        for b in bins:
            if b["chars"] + u["chars"] <= budget:
                b["units"].append(u)
                b["chars"] += u["chars"]
                placed = True
                break
        if not placed:
            bins.append({"units": [u], "chars": u["chars"]})
    return [b["units"] for b in bins]


def _chunk(id_: str, granularity: str, units: list[dict], root: Path, budget: int) -> dict:
    code = [_rel(root, p) for u in units for p in u["code"]]
    chars = sum(u["chars"] for u in units)
    return {
        "id": id_,
        "granularity": granularity,
        "services": sorted({u["svc"] for u in units}),
        "code_paths": code,
        "code_chars": chars,
        "est_tokens": _est_tokens(chars),
        "over_budget": chars > budget,
    }


def build_chunks(root: Path, budget: int) -> dict:
    services = _discover_services(root)
    svc_chars = {svc: _chars([svc / "src"]) for svc in services}
    total = sum(svc_chars.values())

    chunks: list[dict] = []
    if total <= budget:
        # Whole source fits one subagent.
        units = [_service_whole_unit(root, svc) for svc in services]
        chunks.append(_chunk("ALL", "codebase", units, root, budget))
    else:
        fits = [svc for svc in services if svc_chars[svc] <= budget]
        big = [svc for svc in services if svc_chars[svc] > budget]

        # Pack whole services together (never mixing modules across services).
        for bin_units in _binpack([_service_whole_unit(root, svc) for svc in fits], budget):
            names = "+".join(u["svc"] for u in bin_units)
            chunks.append(_chunk(names, "services", bin_units, root, budget))

        # A service too big to fit whole: split it, alone, into its own chunks.
        for svc_dir in big:
            if (svc_dir / "src" / "hex").is_dir():
                for bin_units in _binpack(_service_units(root, svc_dir), budget):
                    ids = "+".join(u["name"].split(":", 1)[1] for u in bin_units)
                    chunks.append(_chunk(f"{svc_dir.name}:{ids}", "modules", bin_units, root, budget))
            else:
                # Non-hex service over budget: no finer structural bound to split on.
                chunks.append(_chunk(svc_dir.name, "service", [_service_whole_unit(root, svc_dir)], root, budget))

    return {
        "root": str(root),
        "budget_chars": budget,
        "budget_est_tokens": _est_tokens(budget),
        "chars_per_token": CHARS_PER_TOKEN,
        "total_code_chars": total,
        "chunks": chunks,
        "hints": _hints(root, services),
    }


def _hints(root: Path, services: list[Path]) -> dict:
    """Best-effort structural signals: code with no doc, docs with no code."""
    plans_core = root / "plans" / "core"
    undocumented: list[str] = []
    unpaired: list[dict] = []

    for svc_dir in services:
        svc = svc_dir.name
        hex_dir = svc_dir / "src" / "hex"
        if hex_dir.is_dir():
            for m in sorted(d for d in hex_dir.iterdir() if d.is_dir()):
                if not (plans_core / svc / "hex" / f"{m.name}.md").is_file():
                    undocumented.append(_rel(root, m))
            # Module docs with no corresponding module dir (stale / deleted).
            for doc in _mds(plans_core / svc / "hex", recursive=False):
                if not (hex_dir / doc.stem).is_dir():
                    unpaired.append({"doc": _rel(root, doc),
                                     "note": "module doc with no code (possible unimplemented / stale doc)"})
        db_schema = plans_core / svc / "db_schema.md"
        if db_schema.is_file():
            unpaired.append({"doc": _rel(root, db_schema),
                             "note": f"schema doc; code counterpart is core/{svc}/migrations "
                                     "(outside chunked source) — verify separately"})

    return {"undocumented_code_units": undocumented, "unpaired_docs": unpaired}


def main() -> None:
    ap = argparse.ArgumentParser(description="Cohere codebase chunker.")
    ap.add_argument("--root", type=Path, help="project root (default: search upward for project.yml)")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET_CHARS,
                    help=f"max chars per chunk (default {DEFAULT_BUDGET_CHARS}, ~{_est_tokens(DEFAULT_BUDGET_CHARS)} tokens)")
    args = ap.parse_args()

    root = args.root.resolve() if args.root else find_project_root(Path.cwd())
    result = build_chunks(root, args.budget)

    n = len(result["chunks"])
    over = sum(1 for c in result["chunks"] if c["over_budget"])
    print(f"{n} chunk(s), {result['total_code_chars']} code chars "
          f"(~{_est_tokens(result['total_code_chars'])} tokens), budget {args.budget}."
          + (f" {over} OVER budget." if over else ""), file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
