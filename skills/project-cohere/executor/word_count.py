#!/usr/bin/env python3
"""Word-count tracker for the project-cohere skill.

Measures whether a cohere run grows or shrinks the core planning docs.

  --before : snapshot per-file word counts of every markdown doc under
             $pr/plans/core and write them to a baseline file.
  --after  : recount now, diff against the baseline, and print two summaries:
             (A) all docs, and (B) only the files whose count changed.

The baseline lives in the system temp dir, keyed by project-root path, so it
survives between the two invocations without polluting either the target project
or the skill's own directory.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

# WHY: baseline is scratch state, not an artifact of the project OR the skill, so
# it lives in the system temp dir (OS-reaped) — never inside the doctrine repo.
# A prior version wrote under the skill dir; those files accumulated unboundedly
# and risked being committed with the (untracked) skill.
TMP_DIR = Path(tempfile.gettempdir()) / "project-cohere-wordcount"
CORE_DOCS_SUBPATH = Path("plans") / "core"


def find_project_root(start: Path) -> Path:
    """Walk upward from `start` to the first dir containing project.yml.

    project.yml is the doctrine's canonical project-root marker, so this lets
    the script be invoked from anywhere inside the project tree.
    """
    for candidate in [start, *start.parents]:
        if (candidate / "project.yml").is_file():
            return candidate
    sys.exit(
        f"error: no project.yml found in {start} or any parent. "
        "Run from inside a project, or pass --root."
    )


def baseline_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return TMP_DIR / f"wordcount_{digest}.json"


def count_docs(root: Path) -> dict[str, int]:
    """Map each markdown doc (relative to root) to its whitespace word count."""
    core = root / CORE_DOCS_SUBPATH
    if not core.is_dir():
        sys.exit(f"error: {core} does not exist.")
    counts: dict[str, int] = {}
    for md in sorted(core.rglob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        counts[str(md.relative_to(root))] = len(text.split())
    return counts


def pct_change(before: int, after: int) -> str:
    if before == 0:
        return "n/a" if after == 0 else "+inf%"
    return f"{(after - before) / before * 100:+.1f}%"


def run_before(root: Path) -> None:
    counts = count_docs(root)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dest = baseline_path(root)
    dest.write_text(json.dumps({"root": str(root), "counts": counts}, indent=2))
    total = sum(counts.values())
    print(f"Baseline written: {len(counts)} docs, {total} words.")
    print(f"  ({dest})")


def run_after(root: Path) -> None:
    src = baseline_path(root)
    if not src.is_file():
        sys.exit(
            f"error: no baseline for {root}. Run with --before first."
        )
    before = json.loads(src.read_text())["counts"]
    after = count_docs(root)

    before_total = sum(before.values())
    after_total = sum(after.values())

    print("=== A) All core planning docs ===")
    print(f"  before: {before_total} words")
    print(f"  after:  {after_total} words")
    print(f"  change: {pct_change(before_total, after_total)}")

    # A file "changed" if its word count differs from the baseline. This folds
    # in new files (0 -> n) and deletions (n -> 0); same-count edits are missed
    # by design (acceptable per spec).
    changed = sorted(
        k for k in set(before) | set(after)
        if before.get(k, 0) != after.get(k, 0)
    )

    print("\n=== B) Changed files ===")
    if not changed:
        print("  (no files changed word count)")
        return
    cb_total = sum(before.get(k, 0) for k in changed)
    ca_total = sum(after.get(k, 0) for k in changed)
    for k in changed:
        b, a = before.get(k, 0), after.get(k, 0)
        print(f"  {k}: {b} -> {a} ({pct_change(b, a)})")
    print(f"  ---")
    print(f"  before: {cb_total} words")
    print(f"  after:  {ca_total} words")
    print(f"  change: {pct_change(cb_total, ca_total)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cohere doc word-count tracker.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--before", action="store_true", help="write baseline snapshot")
    group.add_argument("--after", action="store_true", help="diff against baseline")
    parser.add_argument("--root", type=Path, help="project root (default: search upward for project.yml)")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else find_project_root(Path.cwd())

    if args.before:
        run_before(root)
    else:
        run_after(root)


if __name__ == "__main__":
    main()
