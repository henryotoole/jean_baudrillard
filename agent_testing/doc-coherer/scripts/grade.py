#!/usr/bin/env python3
"""Grade one doc-coherer run against the inventory ground truth.

Given a post-run scratch tree (baseline-committed, agent edits uncommitted) and the
group that was run, this computes:
  - which inventory entries were IN SCOPE (all requires_in_scope paths present),
  - for each: detected? (report mentions it) resolved/deferred correctly? (signature),
  - collateral: boundary_conditions.md touched? source files touched?
  - uncataloged design-doc changes -> triage candidates (new defect OR false positive).

auto_grade:false entries are reported as NEEDS_JUDGE, never auto-failed. A design-doc
change matching no in-scope entry is a triage candidate, never an auto-fail. Output is
a JSON scorecard on stdout; a short human summary on stderr.

Usage:
  grade.py --scratch DIR --group INDEX [--inventory inventory.json]
           [--groups fixtures/groups.json,fixtures/curated_groups.json]
"""
import argparse, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sig_match import satisfies

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUNDARY = "plans/design/boundary_conditions.md"
DOC_EXT = (".md", ".mmd")


def load_groups(paths):
    out = {}
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        data = json.load(open(p))
        groups = data if isinstance(data, list) else data.get("groups", [])
        for g in groups:
            out[str(g["index"])] = g
    return out


def fpaths(group, key):
    return {(i if isinstance(i, str) else i["fpath"]) for i in group.get(key, [])}


def scope_of(group):
    return fpaths(group, "subjects") | fpaths(group, "overhead")


def git(scratch, *args):
    return subprocess.run(["git", "-C", scratch, *args],
                          capture_output=True, text=True).stdout


def changed_files(scratch):
    tracked = git(scratch, "diff", "--name-only").split()
    untracked = git(scratch, "ls-files", "--others", "--exclude-standard").split()
    return set(tracked) | set(untracked)


def read(scratch, rel):
    try:
        return open(os.path.join(scratch, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def find_report(scratch, changed):
    # The report the agent writes; excluded from "doc edits". Prefer a changed one.
    cands = [f for f in changed if "/doc_edits/" in f and f.endswith(".md")]
    if not cands:
        d = os.path.join(scratch, "plans/ops/doc_edits")
        if os.path.isdir(d):
            cands = [os.path.join("plans/ops/doc_edits", f)
                     for f in os.listdir(d) if f.endswith(".md")]
    return sorted(cands)[-1] if cands else None


def grade_fix(scratch, entry):
    sig = entry.get("signature")
    if not sig:
        return "NEEDS_JUDGE", "no signature"
    # Whitespace-tolerant, any-of-aware matching lives in sig_match.satisfies so
    # grade.py and recall_audit.py can never disagree on what a signature means.
    ok, why = satisfies(sig, read(scratch, sig["file"]))
    return ("PASS", "signature satisfied") if ok else ("FAIL", f"{why} in {sig['file']}")


def grade_defer(scratch, entry, changed, report_text):
    sig = entry.get("signature", {})
    top = entry["primary_file"]
    notes = []
    ok = True
    if top in changed:
        ok = False; notes.append(f"top-level doc {top} was EDITED (must not be)")
    fsc = sig.get("file_still_contains")
    if fsc and fsc["text"] not in read(scratch, fsc["file"]):
        ok = False; notes.append(f"{fsc['text']!r} no longer present in {fsc['file']}")
    rx = sig.get("report_matches")
    if rx and not (report_text and re.search(rx, report_text, re.I)):
        ok = False; notes.append(f"report does not mention /{rx}/")
    return ("PASS" if ok else "FAIL"), "; ".join(notes) or "deferred correctly"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--group", required=True, help="group index, e.g. 0 or clean-guard")
    ap.add_argument("--inventory", default=os.path.join(HERE, "inventory.json"))
    ap.add_argument("--groups", default=",".join([
        os.path.join(HERE, "fixtures/groups.json"),
        os.path.join(HERE, "fixtures/curated_groups.json")]))
    args = ap.parse_args()

    groups = load_groups(args.groups.split(","))
    if args.group not in groups:
        sys.exit(f"unknown group {args.group!r}; have {sorted(groups)}")
    group = groups[args.group]
    scope = scope_of(group)
    subjects = fpaths(group, "subjects")
    inv = json.load(open(args.inventory))["entries"]

    changed = changed_files(args.scratch)
    report_rel = find_report(args.scratch, changed)
    report_text = read(args.scratch, report_rel) if report_rel else ""
    doc_changes = {f for f in changed if f.endswith(DOC_EXT)}
    src_changes = {f for f in changed
                   if not f.endswith(DOC_EXT) and f != report_rel}

    # An entry is expected only where its primary_file is a SUBJECT (what the agent
    # is actually pointed at to edit) AND all requires_in_scope paths are in scope
    # (as subject or overhead; corroboration the agent may also load off-disk).
    in_scope = [e for e in inv
                if e["primary_file"] in subjects and set(e["requires_in_scope"]) <= scope]

    results, matched_docs = [], set()
    for e in in_scope:
        detected = any(kw.lower() in report_text.lower()
                       for kw in e.get("report_keywords", [])) if report_text else False
        verdict = e["expected_verdict"]
        if not e.get("auto_grade"):
            outcome, why = "NEEDS_JUDGE", e.get("judge_note", e.get("note", ""))
        elif verdict == "fix":
            outcome, why = grade_fix(args.scratch, e)
            if outcome == "PASS":
                matched_docs.add(e["signature"]["file"])
        elif verdict == "defer":
            outcome, why = grade_defer(args.scratch, e, changed, report_text)
        else:
            outcome, why = "NEEDS_JUDGE", "ambiguous verdict"
        results.append({"id": e["id"], "verdict": verdict, "detected": detected,
                        "outcome": outcome, "why": why})

    # Known defect locations across the WHOLE inventory (any entry's primary_file or
    # signature target), so a changed doc that is an already-catalogued defect is not
    # re-triaged in every group whose code happens to reveal it. A changed doc that is
    # NOT a known location is a genuine discovery candidate.
    known_docs = {e["primary_file"] for e in inv}
    known_docs |= {e["signature"]["file"] for e in inv
                   if e.get("signature", {}).get("file")}
    triage = sorted(d for d in doc_changes
                    if d != report_rel and d != BOUNDARY and d not in known_docs)

    collateral = {
        "boundary_touched": BOUNDARY in changed,            # HARD violation
        "source_files_changed": sorted(src_changes),        # NEEDS_JUDGE (docstring-only?)
    }

    scorecard = {
        "group": args.group,
        "report_written": report_rel,
        "in_scope_count": len(in_scope),
        "results": results,
        "uncataloged_doc_changes": triage,
        "collateral": collateral,
    }
    print(json.dumps(scorecard, indent=2))

    # human summary -> stderr
    def n(o): return sum(1 for r in results if r["outcome"] == o)
    print(f"\n[group {args.group}] in-scope={len(in_scope)} "
          f"PASS={n('PASS')} FAIL={n('FAIL')} JUDGE={n('NEEDS_JUDGE')}", file=sys.stderr)
    if collateral["boundary_touched"]:
        print("  !! boundary_conditions.md was edited — hard violation", file=sys.stderr)
    if collateral["source_files_changed"]:
        print(f"  ?? {len(src_changes)} source file(s) changed — judge if docstring-only",
              file=sys.stderr)
    if triage:
        print(f"  ?? {len(triage)} uncataloged doc change(s) — triage: {triage}", file=sys.stderr)
    for r in results:
        print(f"  [{r['outcome']:11}] {r['id']} ({r['verdict']}) "
              f"detected={r['detected']} — {r['why']}", file=sys.stderr)


if __name__ == "__main__":
    main()
