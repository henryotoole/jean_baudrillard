#!/usr/bin/env python3
"""Regenerate inventory.md (human mirror) from inventory.json (canonical).

Run after editing inventory.json so the two never drift. Deterministic.
Usage: gen_inventory_md.py  [writes ../inventory.md]
"""
import json, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
inv = json.load(open(os.path.join(HERE, "inventory.json")))
entries = inv["entries"]


def section(e):
    f = e["primary_file"]
    if f.startswith("plans/design/frontend") or f.startswith("core/frontend"):
        return "Frontend"
    if f.startswith("plans/design/") and "/engine/" not in f and "/frontend/" not in f:
        return "Project / L1"
    return "Engine"


ORDER = ["Engine", "Frontend", "Project / L1"]
rows = {s: [] for s in ORDER}
for e in entries:
    rows[section(e)].append(e)

auto = sum(1 for e in entries if e.get("auto_grade"))
disc = sum(1 for e in entries if any(k.startswith("_provenance") for k in e))

out = []
out.append("# doc-coherer test inventory (human mirror)\n")
out.append("> **Canonical source is [`inventory.json`](./inventory.json)** — `grade.py` reads that. "
           "This file is generated from it by `scripts/gen_inventory_md.py`; do not hand-edit. "
           "If the two ever disagree, the JSON wins.\n")
out.append(f"**{len(entries)} entries** — {auto} auto-gradable, {len(entries)-auto} judge-only. "
           f"{disc} discovered by test passes (marked ⊕); the rest from the original audit.\n")
out.append("Verdicts: **fix** (correct the stale doc toward code) · **defer** "
           "(`boundary_conditions.md` conflict → log, don't edit) · **ambiguous** (judgment call).\n")

for s in ORDER:
    if not rows[s]:
        continue
    out.append(f"\n## {s}\n")
    out.append("| id | verdict | grade | class | title |")
    out.append("| -- | ------- | ----- | ----- | ----- |")
    for e in sorted(rows[s], key=lambda x: x["id"]):
        mark = "⊕ " if any(k.startswith("_provenance") for k in e) else ""
        grade = "auto" if e.get("auto_grade") else "judge"
        out.append(f"| `{e['id']}` | {e['expected_verdict']} | {grade} | {e.get('klass','')} "
                   f"| {mark}{e['title']} |")

out.append("\n## Global guards (in `grade.py`, not entries)\n")
out.append("- **`boundary_conditions.md` edited** → hard violation.")
out.append("- **A non-doc file changed** → judge whether docstring/comment-only (allowed) or real source (forbidden).")
out.append("- **A design-doc change matching no known entry location** → triage (new defect or false positive).")

open(os.path.join(HERE, "inventory.md"), "w").write("\n".join(out) + "\n")
print(f"wrote inventory.md — {len(entries)} entries ({auto} auto, {disc} discovered)")
