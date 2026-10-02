#!/usr/bin/env python3
"""Aggregate a finished doc-coherer run into a single `history.md` row.

A run produces one `grade.py` scorecard per group (JSON). This collapses every
`group_*.json` in a results directory into one aggregate row and either prints it
(default) or appends it to `history.md`. Because one run is a non-deterministic
sample (see test.md § Philosophy), the point of the log is the *distribution* of
rows over time, not any single row.

Usage:
  record_run.py <results_dir> [--date YYYY-MM-DD] [--ref REF] [--note TEXT] [--append]

  <results_dir>  directory holding this run's group_*.json scorecards
  --ref          agent-under-test identity (default: this repo's short SHA + dirty)
  --append       append the row to history.md (default: just print it to stdout)

Columns (see history.md header for the legend):
  Date | Ref | Groups | tok_max | In | PASS | FAIL | JUDGE | Det | Bdry | Uncat | srcΔ | Notes
"""
import argparse, glob, json, os, subprocess, sys
from datetime import date as _date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(HERE, "history.md")


def _git_ref():
    try:
        sha = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", HERE, "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return f"{sha}{'+dirty' if dirty else ''}" if sha else "unknown"
    except OSError:
        return "unknown"


def _tok_max():
    try:
        return json.load(open(os.path.join(HERE, "fixtures/groups.json")))["tokens_max"]
    except (OSError, KeyError):
        return ""


def _group_key(g):
    return (0, int(g)) if g.isdigit() else (1, g)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--ref", default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args()

    cards = [json.load(open(f)) for f in glob.glob(os.path.join(a.results_dir, "group_*.json"))]
    if not cards:
        sys.exit(f"no group_*.json scorecards found in {a.results_dir!r}")

    groups = sorted((c["group"] for c in cards), key=_group_key)
    agg = {"in": 0, "PASS": 0, "FAIL": 0, "JUDGE": 0, "det": 0, "bdry": 0, "uncat": 0, "src": 0}
    for c in cards:
        for r in c["results"]:
            agg["in"] += 1
            agg["det"] += 1 if r["detected"] else 0
            if r["outcome"] == "PASS":
                agg["PASS"] += 1
            elif r["outcome"] == "FAIL":
                agg["FAIL"] += 1
            else:
                agg["JUDGE"] += 1
        agg["bdry"] += 1 if c["collateral"]["boundary_touched"] else 0
        agg["uncat"] += len(c["uncataloged_doc_changes"])
        agg["src"] += len(c["collateral"]["source_files_changed"])

    ref = a.ref or _git_ref()
    note = a.note or "—"
    row = (f"| {a.date} | {ref} | {','.join(groups)} | {_tok_max()} | "
           f"{agg['in']} | {agg['PASS']} | {agg['FAIL']} | {agg['JUDGE']} | {agg['det']} | "
           f"{agg['bdry']} | {agg['uncat']} | {agg['src']} | {note} |")

    print(row)
    if a.append:
        if not os.path.exists(HISTORY):
            sys.exit(f"{HISTORY} does not exist — create it (with its header) first")
        with open(HISTORY, "a") as fh:
            fh.write(row + "\n")
        print(f"\nappended to {HISTORY}", file=sys.stderr)


if __name__ == "__main__":
    main()
