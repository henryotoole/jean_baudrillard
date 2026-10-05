#!/usr/bin/env bash
# Reset a scratch tree from the seed and assemble the field-accurate prompt for one
# group (from fixtures/groups.json or fixtures/curated_groups.json), embedding the
# CURRENT working-tree doc-coherer definition. Prints the prompt path on the last line.
#
# Usage: prep_group.sh <group_index> <scratch_dir>
set -euo pipefail
GROUP="${1:?usage: prep_group.sh <group> <scratch>}"
SCRATCH="${2:?usage: prep_group.sh <group> <scratch>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT="${SCRATCH}_prompt.md"

bash "$HERE/scripts/reset.sh" "$SCRATCH" >/dev/null
python3 - "$GROUP" "$SCRATCH" "$PROMPT" "$HERE" <<'PY'
import json, sys, re
group_id, scr, prompt, here = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
groups={}
for p in (f"{here}/fixtures/groups.json", f"{here}/fixtures/curated_groups.json"):
    for g in json.load(open(p))["groups"]:
        groups[str(g["index"])]=g
g=groups[group_id]
defn=open("/home/ubuntu/.claude/jean_baudrillard/agents/private/doc-coherer.md").read()
defn=re.sub(r'^---\n.*?\n---\n','',defn,count=1,flags=re.S).strip()
assert "Enumeration cross-check" in defn, "updated definition not present!"
def lines(k): return "\n".join(f"{scr}/{i['fpath']}" for i in g[k])
preamble=f"""You are running AS the `doc-coherer` agent for a test pass. Operating notes (test-harness scaffolding; these stand in for the ambient project context the field orchestrator relies on):
- Project root (`$pr`) is `{scr}`. Edit files there freely.
- Today's date (`${{date}}`) is `2026-09-17` (use it for the report filename).
- You may NOT spawn subagents and need NOT load any skills (ignore the chain-of-command step).
- Never edit actual source code (.py/.ts/.svelte); you MAY edit design docs (.md/.mmd) and code-level docstrings/comments.

Your complete operating definition is between the DEFINITION markers. Follow it exactly. After it comes your task message, delivered in the exact template the `doc-edit-orchestrator` uses in the field.

==== DEFINITION ====
{defn}
==== END DEFINITION ====
"""
task=f"""Hello. Please use the following overhead and subject files to carry out your editing passes. Remember, always load the overhead files **first** and then read and edit each subject file serially.

**OVERHEAD FILES** - Read these to inform your edits.
{lines('overhead')}

**SUBJECT FILES** - Edit these
{lines('subjects')}
"""
open(prompt,"w").write(preamble+"\n"+task)
import sys as _s; print(f"group {group_id}: {len(g['subjects'])} subjects, {len(g['overhead'])} overhead", file=_s.stderr)
PY
echo "$PROMPT"