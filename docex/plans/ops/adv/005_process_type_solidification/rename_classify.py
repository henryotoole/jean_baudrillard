#!/usr/bin/env python3
"""Sense-tagged inventory for the codebase/core-service rename.

Emits one TSV row per hit. Senses:
  KEY_TOP/KEY_NEST/KEY_FIELD  authored CICL surface
  REF        magic ref namespace
  IDENT      code identifier (deterministic in code files)
  CB         prose "core service" carrying the CODEBASE sense -> "codebase"
  SVC        "process type" family -> "core service" family
  KEEP       "core service" already carrying the DEPLOYABLE sense -> unchanged
  AMBIG      needs human adjudication
"""
import re
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/.claude/jean_baudrillard")
WORKING = Path(sys.argv[1])

CODE_EXT = {".py", ".j2", ".tf", ".sh"}
DATA_EXT = {".yml", ".yaml", ".json"}

# Strong, same-line evidence that the mention means the codebase.
CB_SIGNALS = re.compile(
    r"\b(codebase|image|build artifact|artifact|Dockerfile|build\.sh|test\.sh|"
    r"migrate\.sh|schema_owned_by|source code|src/|dist/|registry|containerize|"
    r"one codebase|never share code|per[- ]codebase|build stage)\b", re.I)
# Strong, same-line evidence it already means the deployed unit.
KEEP_SIGNALS = re.compile(
    r"\bcore[_ ]services?\s+(container|process|instance)s?\b|"
    r"\b(container|task|ECS service|Fargate|replica)s?\s+per\s+core[_ ]service\b",
    re.I)

PROTECTED = re.compile(
    r"subprocess|Subprocess|process(or|ing|ed)|docex_process|stateless process")

# Deterministic renames, checked in order.
TERMS = [
    (re.compile(r"\bdomain_default_process\b"), "KEY_FIELD", "domain_default_service"),
    (re.compile(r"\$\{core_services\.[A-Za-z0-9_.]+\}"), "REF",
     "${codebases.<cb>.core_services.<svc>.<part>}"),
    (re.compile(r"^\s*core_services:"), "KEY_TOP", "codebases:"),
    (re.compile(r"^\s*processes:"), "KEY_NEST", "core_services:"),
    (re.compile(r"\bProcessType\b"), "IDENT", "CoreService"),
    (re.compile(r"\bProcessRef\b"), "IDENT", "ServiceRef"),
    (re.compile(r"\bCoreService\b"), "IDENT", "Codebase"),
    (re.compile(r"\b(proc_name|process_name)\b"), "IDENT", "service_name"),
    (re.compile(r"\b(primary_process|all_processes|target_process)\b"), "IDENT", "*_service"),
    (re.compile(r"\b(_resolve_process|_standard_process_fields)\b"), "IDENT", "_*_service"),
    (re.compile(r"\bprocess[_ -]types?\b", re.I), "SVC", "core service(s)"),
    (re.compile(r"\bprocess[- ]scoped\b", re.I), "SVC", "service-scoped"),
    (re.compile(r"\bprocess[- ]level\b", re.I), "SVC", "service-level"),
    (re.compile(r"\bprocess dimension\b", re.I), "SVC", "service dimension"),
    (re.compile(r"\bcore[_ ]services?\b", re.I), None, None),
]

rows = []
for rel in WORKING.read_text().split():
    p = ROOT / rel
    if not p.is_file():
        continue
    ext = p.suffix
    try:
        lines = p.read_text(errors="replace").splitlines()
    except Exception:
        continue
    for i, line in enumerate(lines, 1):
        for rx, sense, proposed in TERMS:
            for m in rx.finditer(line):
                tok = m.group(0)
                if sense is not None:
                    s, conf, prop = sense, "high", proposed
                else:
                    if re.match(r"^\s*core_services:", line):
                        continue
                    if ext in CODE_EXT or ext in DATA_EXT:
                        # In code/data, `core_service*` is an identifier or key
                        # for the codebase concept -> deterministic.
                        s, conf, prop = "IDENT", "high", (
                            "codebases" if tok.rstrip(":").endswith("s") else "codebase")
                    else:
                        keep = bool(KEEP_SIGNALS.search(line))
                        cb = bool(CB_SIGNALS.search(line))
                        if keep and cb:
                            # Both senses on one line. NEVER auto-resolve: a
                            # high-confidence wrong call here is invisible.
                            s, conf, prop = "AMBIG", "mixed", "codebase? or KEEP?"
                        elif keep:
                            s, conf, prop = "KEEP", "high", "(unchanged)"
                        elif cb:
                            s, conf, prop = "CB", "high", "codebase"
                        else:
                            s, conf, prop = "AMBIG", "low", "codebase? or KEEP?"
                # Changelogs record what was true at the time. Existing
                # entries are frozen; the file is APPEND-ONLY (a 1.7.0
                # entry states the old->new mapping).
                if rel.endswith("CHANGELOG.md"):
                    s, conf, prop = "FROZEN_HISTORY", "policy", "(append 1.7.0 entry only)"
                if PROTECTED.search(line):
                    s, conf = "PROTECTED_NEARBY", "review"
                rows.append((rel, i, tok.strip(), s, conf, prop or "", line.strip()[:150]))

print("file\tline\tterm\tsense\tconfidence\tproposed\tcontext")
for r in rows:
    print("\t".join(str(x) for x in r))
