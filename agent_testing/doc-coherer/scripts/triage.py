#!/usr/bin/env python3
"""Whole-tree triage for an accumulating (no-reset) doc-coherer sweep.

Classifies every file changed in the nasmyth tree since a baseline ref against
inventory.json's KNOWN locations (any entry's primary_file or signature.file).

  - known-location change   -> expected (a catalogued defect being fixed)
  - unknown-location change  -> SURPRISE (genuine new defect OR false positive)

It is a FILE-level filter: a surprise inside a *known* file (a second, distinct
defect in a file already catalogued for something else) will show under
known-location, so still read each group's report + diff by hand.

Usage: triage.py --base <ref> [--nasmyth DIR] [--inventory PATH]
  --base is the commit to diff against (e.g. the previous group's commit, or the
  pre-sweep baseline for a whole-run view). Commit after each group so --base can
  be the prior group's commit and each group's contribution shows in isolation.
"""
import argparse, json, os, subprocess

DEFAULT_NAS = "/home/ubuntu/projects/nasmyth"
DEFAULT_INV = "/home/ubuntu/.claude/jean_baudrillard/agent_testing/doc-coherer/inventory.json"
DOC_EXT = (".md", ".mmd")


def git(nas, *a):
    return subprocess.run(["git", "-C", nas, *a], capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="git ref to diff against")
    ap.add_argument("--nasmyth", default=DEFAULT_NAS)
    ap.add_argument("--inventory", default=DEFAULT_INV)
    a = ap.parse_args()
    nas = a.nasmyth

    inv = json.load(open(a.inventory))["entries"]
    known = {e["primary_file"] for e in inv}
    known |= {e["signature"]["file"] for e in inv if e.get("signature", {}).get("file")}
    where = {}
    for e in inv:
        for f in {e["primary_file"], e.get("signature", {}).get("file")}:
            if f:
                where.setdefault(f, []).append(e["id"])

    changed = [f for f in git(nas, "diff", "--name-only", a.base).split() if f]
    report_ns = "plans/ops/doc_edits/"
    known_hits, surprises, src_touched, reports = [], [], [], []
    for f in changed:
        if f.startswith(report_ns):
            reports.append(f); continue
        if not f.endswith(DOC_EXT):
            src_touched.append(f)
        (known_hits.append((f, where.get(f, []))) if f in known else surprises.append(f))

    print("=" * 70)
    print(f"BASE {a.base}  |  {len(changed)} files changed")
    print("=" * 70)
    print(f"\nKNOWN-LOCATION changes ({len(known_hits)}) — expected catalogued fixes:")
    for f, ids in sorted(known_hits):
        print(f"  {f}\n      entries: {', '.join(ids)}")
    print(f"\n*** SURPRISE changes ({len(surprises)}) — NOT a known inventory location:")
    for f in sorted(surprises):
        tag = "  [SOURCE/non-doc]" if not f.endswith(DOC_EXT) else ""
        print(f"  {f}{tag}")
    print(f"\nSource / non-doc files touched ({len(src_touched)}) — judge docstring-only vs real source:")
    for f in sorted(src_touched):
        print(f"  {f}")
    print(f"\nReports written ({len(reports)}): {reports}")


if __name__ == "__main__":
    main()
