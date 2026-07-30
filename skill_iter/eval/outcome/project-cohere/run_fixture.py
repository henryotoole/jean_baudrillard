#!/usr/bin/env python3
"""Fixture harness for outcome-evaluating the `project-cohere` skill.

`project-cohere` is unusual to evaluate: its input is a whole doctrine project
in a specific drift state, and its output is a *diff* against that project's
docs — including the empty diff, which is the correct result when the project is
already coherent. This harness supplies the deterministic scaffolding around a
skill run so grading can be done on the diff:

  assemble  copy fixtures/_base + a state overlay into a scratch git repo and
            record a baseline commit. The skill run then executes in that repo.
  capture   after the skill has run, emit the diff against the baseline commit
            plus a machine summary (files changed, insertions/deletions, empty?).

State storage is base + per-state overlay (not full copies) so every state is
provably `base + exactly one intended drift`, which is the whole point of the
suite: isolate one drift form per state. The overlay dir mirrors the project
root; each file in it replaces/adds the same relative path, and an optional
`DELETE` manifest at the overlay root lists paths to remove.

The scratch repo is created OUTSIDE this repository (system temp by default) so
its inner .git never entangles the outer doctrine repo.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE / "fixtures" / "_base"
STATES_DIR = HERE / "fixtures" / "states"

# WHY: fixtures carry no committer identity; pass one inline so `git commit`
# works on a machine with no global git config (e.g. CI).
GIT_ID = ["-c", "user.email=cohere-eval@example.com", "-c", "user.name=cohere-eval"]
BASELINE_MSG = "fixture baseline"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _apply_overlay(overlay: Path, dest: Path) -> list[str]:
    """Copy overlay files onto dest and honor an optional DELETE manifest.

    Returns the list of relative paths deleted, for the assemble report.
    """
    deleted: list[str] = []
    delete_manifest = overlay / "DELETE"
    if delete_manifest.is_file():
        for line in delete_manifest.read_text().splitlines():
            rel = line.strip()
            if not rel or rel.startswith("#"):
                continue
            target = dest / rel
            if target.is_file():
                target.unlink()
                deleted.append(rel)
            elif target.is_dir():
                shutil.rmtree(target)
                deleted.append(rel)

    for src in sorted(overlay.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(overlay)
        # DELETE is a manifest, .gitkeep only marks an otherwise-empty overlay.
        if rel.name in ("DELETE", ".gitkeep"):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    return deleted


def assemble(state: str, out: str | None = None, force: bool = False) -> dict:
    """Build a scratch git repo for a state (base + overlay) and commit a baseline.

    Returns {state, scratch, baseline_commit, overlay_deleted}. Importable so
    run_outcome.py drives the same assembly the CLI does.
    """
    state_overlay = STATES_DIR / state / "overlay"
    if not state_overlay.is_dir():
        raise ValueError(f"unknown state '{state}' (no {state_overlay})")

    scratch = Path(out).resolve() if out else Path(tempfile.mkdtemp(prefix=f"cohere-{state}-"))
    if scratch.exists() and any(scratch.iterdir()):
        if not force:
            raise FileExistsError(f"{scratch} is not empty (pass force=True to overwrite)")
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)

    shutil.copytree(BASE_DIR, scratch, dirs_exist_ok=True)
    deleted = _apply_overlay(state_overlay, scratch)

    _git(scratch, "init", "-q")
    _git(scratch, *GIT_ID, "add", "-A")
    _git(scratch, *GIT_ID, "commit", "-q", "-m", BASELINE_MSG)
    baseline = _git(scratch, "rev-parse", "HEAD").stdout.strip()

    return {
        "state": state,
        "scratch": str(scratch),
        "baseline_commit": baseline,
        "overlay_deleted": deleted,
    }


def capture(repo_dir: str, baseline: str | None = None, with_diff: bool = False) -> dict:
    """Emit the diff a run produced against the fixture baseline commit.

    Returns {dir, baseline_commit, is_empty, files_changed, insertions,
    deletions, [diff]}. Importable so run_outcome.py can grade on it.
    """
    repo = Path(repo_dir).resolve()
    if not (repo / ".git").is_dir():
        raise FileNotFoundError(f"{repo} is not a git repo (assemble it first)")

    base = baseline or _find_baseline(repo)

    # Stage everything so untracked/created files register in the diff, then
    # diff the full working tree against the baseline commit — this captures the
    # skill's changes whether it left them uncommitted or committed them itself.
    _git(repo, *GIT_ID, "add", "-A")
    numstat = _git(repo, "diff", "--cached", "--numstat", base).stdout.strip()
    diff = _git(repo, "diff", "--cached", base).stdout

    files, insertions, deletions = [], 0, 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, rem, path = parts
        files.append(path)
        insertions += int(add) if add.isdigit() else 0
        deletions += int(rem) if rem.isdigit() else 0

    report = {
        "dir": str(repo),
        "baseline_commit": base,
        "is_empty": not files,
        "files_changed": files,
        "insertions": insertions,
        "deletions": deletions,
    }
    if with_diff:
        report["diff"] = diff
    return report


def cmd_assemble(args: argparse.Namespace) -> None:
    try:
        print(json.dumps(assemble(args.state, args.out, args.force), indent=2))
    except (ValueError, FileExistsError) as e:
        sys.exit(f"error: {e}")


def cmd_capture(args: argparse.Namespace) -> None:
    try:
        print(json.dumps(capture(args.dir, args.baseline, args.with_diff), indent=2))
    except FileNotFoundError as e:
        sys.exit(f"error: {e}")


def _find_baseline(repo: Path) -> str:
    """Return the SHA of the fixture baseline commit (oldest commit)."""
    shas = _git(repo, "rev-list", "--max-parents=0", "HEAD").stdout.split()
    if not shas:
        sys.exit("error: no commits in repo")
    return shas[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_asm = sub.add_parser("assemble", help="build a scratch repo for a state")
    p_asm.add_argument("--state", required=True, help="state name under fixtures/states/")
    p_asm.add_argument("--out", help="scratch dir (default: a fresh system temp dir)")
    p_asm.add_argument("--force", action="store_true", help="overwrite a non-empty --out")
    p_asm.set_defaults(func=cmd_assemble)

    p_cap = sub.add_parser("capture", help="emit the diff after a skill run")
    p_cap.add_argument("--dir", required=True, help="scratch dir from assemble")
    p_cap.add_argument("--baseline", help="baseline commit SHA (default: repo's root commit)")
    p_cap.add_argument("--with-diff", action="store_true", help="include the full unified diff in output")
    p_cap.set_defaults(func=cmd_capture)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
