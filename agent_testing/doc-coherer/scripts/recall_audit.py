#!/usr/bin/env python3
"""End-of-sweep recall audit: check every auto-gradable inventory signature against
the current nasmyth tree. A satisfied signature = the defect is fixed. An
UNSATISFIED auto signature = a still-present catalogued defect = a MISS (if the
whole sweep ran, every subject-file defect had its chance). Newly-added entries
describe the now-fixed state, so they should read SATISFIED.

Judge (auto_grade:false) entries are listed separately for hand review.

Usage: recall_audit.py [--nasmyth DIR] [--inventory PATH]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sig_match import satisfies

DEFAULT_NAS = "/home/ubuntu/projects/nasmyth"
DEFAULT_INV = "/home/ubuntu/.claude/jean_baudrillard/agent_testing/doc-coherer/inventory.json"


def read(nas, rel):
    try:
        return open(os.path.join(nas, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return None


def check(nas, e):
    sig = e.get("signature")
    if not sig:
        return "NO_SIG", "auto entry without signature"
    text = read(nas, sig["file"])
    if text is None:
        return "FILE_MISSING", sig["file"]
    # Shared whitespace-tolerant matcher — same semantics as grade.py.
    ok, why = satisfies(sig, text)
    return ("SATISFIED", "ok") if ok else ("UNSATISFIED", why)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nasmyth", default=DEFAULT_NAS)
    ap.add_argument("--inventory", default=DEFAULT_INV)
    a = ap.parse_args()
    inv = json.load(open(a.inventory))["entries"]
    auto = [e for e in inv if e.get("auto_grade")]
    judge = [e for e in inv if not e.get("auto_grade")]
    sat, unsat, other = [], [], []
    for e in auto:
        st, why = check(a.nasmyth, e)
        (sat if st == "SATISFIED" else unsat if st == "UNSATISFIED" else other).append((e["id"], st, why))
    print(f"AUTO entries: {len(auto)}  SATISFIED(fixed): {len(sat)}  UNSATISFIED(miss): {len(unsat)}  other: {len(other)}")
    print("\n=== UNSATISFIED auto entries (MISSES — still-present catalogued defects) ===")
    for i, st, why in unsat:
        print(f"  [{i}] {why}")
    if other:
        print("\n=== other (no-sig / file-missing) ===")
        for i, st, why in other:
            print(f"  [{i}] {st}: {why}")
    print(f"\n=== JUDGE entries ({len(judge)}) — hand-review, not auto-scored ===")
    for e in judge:
        print(f"  [{e['id']}] {e.get('expected_verdict')}")


if __name__ == "__main__":
    main()
