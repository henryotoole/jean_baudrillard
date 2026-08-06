#!/usr/bin/env python3
"""Compile every CICL example in the corpus, rather than reading it.

Covers the fourth mechanical check in the cohere skill:
  4. Examples that do not compile (fences that are not valid `infra.yml`)

Checks 1 and 3 (links / anchors / duplicate filenames) are `linkcheck.py`'s
job; check 2 (spelling and grammar) stays an LLM pass.

WHY this is a shipped tool and not a scratch script: advance 005 found the
canonical `cicl.md` example broken TWICE — once by a compile harness and once
by an independent tab census — and *neither* was a shipped check. A check that
passes once is not a check.

Usage:
    python3 verify_examples.py [ROOT ...]

ROOTs default to the `doctrine/` and `skills/` dirs resolved relative to this
script's location ($jb), matching `linkcheck.py` so both executors take the
same arguments. Exits non-zero if any fence fails to parse or to validate.

Extracts every ```yml / ```yaml fence under the roots, keeps the
infra.yml-shaped ones, and validates each through the REAL code path
(CICLDocument.model_validate + validate_document), exactly as the unit tests do.

Everything the harness does *for* a fence is DECLARED and PRINTED, because a
fence that only passes because the harness helped is a reported fact, not a
hidden one:

  1. TAB NORMALIZATION. Many doctrine fences are indented with tabs, which is
     not loadable YAML. Leading tabs are converted to two spaces, and every
     fence that needed it is flagged [de-tabbed].
  2. THE SKELETON. Fragments (no `cicl_version:`) are deep-merged into one
     declared v3 skeleton. Fragment values win at every leaf; the skeleton only
     fills gaps and supplies AMBIENT services a fragment refers to but does not
     declare. The exact top-level keys supplied are printed per fence.
  3. SNIPPET DEFAULTS. A fragment introducing a service the skeleton has no
     counterpart for gets the declared default block; every field supplied is
     printed per fence.

Fences are CLASSIFIED, and the classification decides what "pass" means:

  COMPLETE      — carries `cicl_version:`; must validate as-is, no help.
  FRAGMENT      — spliced into the skeleton; must then validate cleanly.
  ILLUSTRATIVE  — contains `...` placeholders; it is deliberately not a
                  document. Reported and skipped, never counted as a pass.
  EXCERPT       — quotes part of a larger YAML document and borrows an
                  `&anchor` defined in a *different* fence (e.g.
                  `logging: *default-logging`). Also deliberately not a
                  standalone document. Reported on its own line and NEVER
                  folded into "parsed" — if a genuinely broken fence ever
                  trips the condition, that count is what catches it.
  PROJECT-LOCAL — declares a role/engine the BUNDLED tables do not ship
                  (that is the point of the snippet). Bundled-table validation
                  cannot know them, so unknown-role/engine issues are EXPECTED
                  and listed separately. What still must be clean is
                  TARGET RESOLUTION (rule 25 / undeclared `uses:` targets) —
                  which is precisely what mod 118 Part B changed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

# This file lives at $jb/skills/cohere/executor/ — same trick linkcheck.py uses.
JB = Path(__file__).resolve().parents[3]
DEFAULT_ROOTS = [JB / "doctrine", JB / "skills"]
# upgrades/ deliberately carries v2 BEFORE-state; excluded by instruction.
EXCLUDE = [JB / "upgrades"]

# WHY: resolve the `docex` import rather than assuming a PYTHONPATH and a cwd
# inside docex/. A bare ImportError here reads as "the tool is broken" when the
# real cause is a moved checkout.
_DOCEX_SRC = JB / "docex" / "src"
if str(_DOCEX_SRC) not in sys.path:
    sys.path.insert(0, str(_DOCEX_SRC))
try:
    from docex.cicl.model import CICLDocument
    from docex.cicl.transfer import load_transfer_tables
    from docex.cicl.validate import validate_document
except ImportError as exc:  # pragma: no cover - environment failure path
    sys.exit(
        f"ERROR: cannot import `docex` from {_DOCEX_SRC} ({exc}).\n"
        "This tool validates fences through docex's real CICL code path and "
        "cannot run without it. Expected layout: $jb/docex/src/docex/, with "
        "this script at $jb/skills/cohere/executor/."
    )

SKELETON_SRC = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        uses: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB
      worker:
        role: worker
        command: ["python", "/service/dist/worker.py"]
        networks: [internal]
        port: 8081
        resources:
          cpu: 1.0
          memory: 2GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
  cache:
    role: cache
    engine: redis
    version: "7"
    networks: [internal]
  bucket:
    role: object_store
    engine: minio
    version: "latest"
    networks: [internal]
"""

CORE_DEFAULTS = {
    "command": ["python", "/service/dist/root.py"],
    "networks": ["internal"],
    "resources": {"cpu": 1.0, "memory": "2GB"},
}
BACKING_DEFAULTS = {"networks": ["internal"]}

# Issues that are EXPECTED when a snippet documents a project-local role or
# engine, because the bundled tables by definition do not contain it.
PROJECT_LOCAL_RULES = {
    "rule_2_unknown_role",
    "rule_4_unknown_engine",
    "rule_4_engine_foundation_mismatch",
    "rule_3_unresolved_magic_ref",
}

FENCE = re.compile(r"^```(yml|yaml)\s*$(.*?)^```\s*$", re.M | re.S)
SHAPE_KEYS = {"cicl_version", "codebases", "backing_services"}
PLACEHOLDER = re.compile(r"\{\s*\.\.\.\s*\}|\[\s*\.\.\.\s*\]|^\s*\.\.\.\s*$", re.M)


def detab(body):
    """Leading tabs -> 2 spaces each; any remaining (interior) tab -> 1 space.
    YAML forbids tabs as whitespace entirely, so both forms are unloadable."""
    changed = interior = False
    out = []
    for line in body.splitlines():
        s = line.lstrip("\t")
        n = len(line) - len(s)
        if n:
            changed = True
        if "\t" in s:
            interior = True
            changed = True
            s = s.replace("\t", " ")
        out.append("  " * n + s)
    return "\n".join(out) + "\n", changed, interior


def fences(path):
    text = path.read_text(encoding="utf-8")
    for m in FENCE.finditer(text):
        yield text.count("\n", 0, m.start()) + 1, m.group(2)


def deep_merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(base.get(k), v) if k in base else v
    return out


def apply_defaults(doc, frag):
    supplied = []
    for cb, body in (frag.get("codebases") or {}).items():
        for svc in (body.get("core_services") or {}):
            tgt = doc["codebases"][cb]["core_services"][svc]
            for f, val in CORE_DEFAULTS.items():
                if f not in tgt:
                    tgt[f] = val
                    supplied.append(f"codebases.{cb}.{svc}.{f}")
    for bs in (frag.get("backing_services") or {}):
        tgt = doc["backing_services"][bs]
        for f, val in BACKING_DEFAULTS.items():
            if f not in tgt:
                tgt[f] = val
                supplied.append(f"backing_services.{bs}.{f}")
    return supplied


def known_engines(tables, role):
    try:
        return {e.engine for e in tables.by_role(role)}
    except Exception:
        return set()


def known_roles(tables):
    try:
        return set(tables.roles())
    except Exception:
        return set()


def parse_fence(src):
    """Parse a fence's YAML, returning its first document.

    WHY safe_load_all: a markdown fence may legitimately show a multi-document
    stream — the frontmatter example in `doctrine.md` is exactly `---` / key /
    `---`, which is a valid two-document stream that `safe_load` rejects
    outright. Shape detection still keys off the first document only, so this
    changes nothing about which fences become candidates.
    """
    docs = list(yaml.safe_load_all(src))
    return docs[0] if docs else None


ANCHOR_DEF = re.compile(r"&([A-Za-z0-9_\-]+)")
_UNDEF_ALIAS = re.compile(r"found undefined alias '([^']+)'")
_MAX_STUBS = 8


def undefined_alias(exc):
    """Return the alias name if `exc` is purely an undefined-alias error."""
    if not isinstance(exc, yaml.composer.ComposerError):
        return None
    m = _UNDEF_ALIAS.search(getattr(exc, "problem", "") or "")
    return m.group(1) if m else None


def excerpt_aliases(src, corpus_anchors):
    """Classify a fence as an EXCERPT, returning the aliases it borrows.

    An EXCERPT is a fence that is deliberately *not* a standalone document: it
    quotes part of a larger YAML document and refers to an anchor defined in a
    different fence (e.g. `logging: *default-logging`, whose `&default-logging`
    lives in another file's fence). Those excerpts are correct documentation —
    showing the real emitted shape is their entire purpose — so making them
    parse standalone would mean damaging the docs to satisfy this tool.

    WHY the condition is this narrow: a classification that can absorb an
    unrelated failure is a gate with a hole in it. Both must hold —
      1. every parse error is an *undefined alias*, and
      2. every such alias has an `&anchor` defined somewhere in the corpus.
    We prove (1) by stubbing each missing anchor and re-parsing: if the fence
    then parses, the aliases were the *only* problem. Anything else — a genuine
    syntax error, an alias nothing in the corpus defines — still fails.

    Returns a sorted list of alias names, or None if this is not an excerpt.
    """
    borrowed, probe = [], src
    for _ in range(_MAX_STUBS):
        try:
            list(yaml.safe_load_all(probe))
        except Exception as exc:
            name = undefined_alias(exc)
            if name is None or name not in corpus_anchors:
                return None
            borrowed.append(name)
            # Anchors are per-document, so the stub must join the same document.
            # A non-mapping top level will fail the re-parse, i.e. fail closed.
            probe = f"_docex_anchor_stub_{len(borrowed)}: &{name} {{}}\n" + probe
            continue
        return sorted(set(borrowed)) if borrowed else None
    return None


def main():
    roots = [Path(a).resolve() for a in sys.argv[1:]] or DEFAULT_ROOTS
    for r in roots:
        if not r.is_dir():
            sys.exit(f"ERROR: root not found: {r}")

    # WHY: `relative_to` against one of several roots is ambiguous, and roots
    # may sit outside $jb entirely (tests), so display paths hang off the
    # common ancestor of whatever was actually passed.
    if len(roots) > 1:
        display_base = Path(os.path.commonpath([str(r) for r in roots]))
    else:
        display_base = roots[0].parent

    def show(path):
        try:
            return str(Path(path).relative_to(display_base))
        except ValueError:
            return str(path)

    tables = load_transfer_tables(project_root=None)
    skeleton = yaml.safe_load(SKELETON_SRC)
    roles = known_roles(tables)

    files = []
    for root in roots:
        for p in sorted(root.rglob("*.md")):
            if not any(str(p).startswith(str(e)) for e in EXCLUDE):
                files.append(p)

    # WHY a pre-pass: an EXCERPT is only legitimate if the anchor it borrows is
    # defined somewhere in the corpus, which we cannot know until every fence
    # has been seen. Cheap — a regex over fence bodies, no YAML parsing.
    corpus_anchors = set()
    for p in files:
        for _, body in fences(p):
            corpus_anchors.update(ANCHOR_DEF.findall(body))

    total = detabbed = 0
    unparseable, cands, interior_tabs, excerpts = [], [], [], []
    for p in files:
        for ln, body in fences(p):
            total += 1
            src, changed, interior = detab(body)
            if changed:
                detabbed += 1
            if interior:
                interior_tabs.append((p, ln))
            illustrative = bool(PLACEHOLDER.search(src))
            try:
                raw = parse_fence(src)
            except Exception as exc:
                if illustrative:
                    cands.append((p, ln, None, changed, True))
                else:
                    borrowed = excerpt_aliases(src, corpus_anchors)
                    if borrowed:
                        excerpts.append((p, ln, borrowed))
                    else:
                        unparseable.append((p, ln, type(exc).__name__))
                continue
            if isinstance(raw, dict) and (SHAPE_KEYS & set(raw)):
                cands.append((p, ln, raw, changed, illustrative))

    print("roots: " + ", ".join(show(r) for r in roots))
    print(f"markdown files scanned  : {len(files)}")
    print(f"yml/yaml fences found   : {total}")
    print(f"fences needing de-tab   : {detabbed}  (leading tabs -> 2 spaces)")
    print(f"fences w/ INTERIOR tabs  : {len(interior_tabs)}  (tab used as an inline-comment separator)")
    for p, ln in interior_tabs:
        print(f"    !! {show(p)}:{ln}")
    print(f"fences unparseable      : {len(unparseable)}")
    for p, ln, e in unparseable:
        print(f"    !! {show(p)}:{ln}  {e}")
    print(f"fences EXCERPT          : {len(excerpts)}  (borrow an anchor defined in another fence)")
    for p, ln, names in excerpts:
        print(f"    -- {show(p)}:{ln}  borrows {', '.join('*' + x for x in names)}")
    print(f"infra.yml-shaped fences : {len(cands)}")
    print()
    print("DECLARED SKELETON (used for every FRAGMENT below):")
    print("-" * 72)
    print(SKELETON_SRC.strip())
    print("-" * 72)
    print(f"DECLARED core defaults    : {CORE_DEFAULTS}")
    print(f"DECLARED backing defaults : {BACKING_DEFAULTS}")
    print("-" * 72)
    print()

    n = {"COMPLETE": 0, "FRAGMENT": 0, "ILLUSTRATIVE": 0, "PROJECT-LOCAL": 0}
    ok = fail = helped = 0
    for p, ln, raw, tabbed, illus in sorted(cands, key=lambda c: (str(c[0]), c[1])):
        rel = show(p)
        tag = " [de-tabbed]" if tabbed else ""
        if illus:
            n["ILLUSTRATIVE"] += 1
            print(f"[SKIP] ILLUSTRATIVE {rel}:{ln}{tag}")
            print("         contains `...` placeholders — deliberately not a document")
            continue

        bss = (raw.get("backing_services") or {}).values()
        declared_roles = {b.get("role") for b in bss} - {None}
        project_local = bool(declared_roles - roles) if roles else False
        if not project_local:
            for b in bss:
                r, e = b.get("role"), b.get("engine")
                engines = [e] if isinstance(e, str) else (e or [])
                if r in roles and engines:
                    known = known_engines(tables, r)
                    if known and any(x not in known for x in engines):
                        project_local = True

        complete = "cicl_version" in raw
        notes = []
        if complete:
            doc_raw, kind = raw, "COMPLETE"
            notes.append("validated AS-IS (complete document), no help given")
        else:
            kind = "FRAGMENT"
            doc_raw = deep_merge(skeleton, raw)
            gave = sorted(set(skeleton) - set(raw))
            filled = apply_defaults(doc_raw, raw)
            notes.append("skeleton supplied top-level: " + (", ".join(gave) or "nothing"))
            if filled:
                notes.append("defaults supplied: " + ", ".join(filled))
                helped += 1
        if project_local:
            kind = "PROJECT-LOCAL"

        try:
            issues = validate_document(CICLDocument.model_validate(doc_raw), tables)
            issues = [(getattr(i, "rule", ""), str(getattr(i, "message", i))) for i in issues]
        except Exception as exc:
            issues = [("", f"{type(exc).__name__}: {exc}")]

        # Authoritative signal: the validator itself says the bundled tables
        # do not ship this role/engine. That IS the project-local case.
        if any(i[0] in ("rule_2_unknown_role", "rule_4_unknown_engine") for i in issues):
            project_local = True
            kind = "PROJECT-LOCAL"

        if project_local:
            expected = [i for i in issues if i[0] in PROJECT_LOCAL_RULES]
            blocking = [i for i in issues if i[0] not in PROJECT_LOCAL_RULES]
        else:
            expected, blocking = [], issues

        n[kind] += 1
        status = "PASS" if not blocking else "FAIL"
        ok, fail = (ok + 1, fail) if not blocking else (ok, fail + 1)
        print(f"[{status}] {kind} {rel}:{ln}{tag}")
        for note in notes:
            print(f"         {note}")
        if project_local:
            print("         project-local role/engine — bundled tables cannot know it;")
            print("         target resolution (rule 25) is what is being asserted here")
            for r, m in expected:
                print(f"         (expected) {r}: {m[:200]}")
        for r, m in blocking:
            print(f"         !! {r}: {m[:400]}" if r else f"         !! {m[:400]}")

    print()
    n["EXCERPT"] = len(excerpts)
    for k, v in n.items():
        print(f"{k:<14}: {v}")
    print(f"fragments needing a default fill : {helped}")
    print()
    print(f"fences scanned  : {total}")
    # WHY excerpts are subtracted rather than counted as parsed: an EXCERPT is
    # not a pass. It is a fence we have decided not to hold to the standalone
    # standard, and folding it into "parsed" would hide it. If a genuinely
    # broken fence ever trips the excerpt condition, this count is what catches
    # it — so it must stay a number someone can watch.
    print(f"fences parsed   : {total - len(unparseable) - len(excerpts)} / {total}")
    print(f"fences EXCERPT  : {len(excerpts)}")
    print(f"fences tabbed   : {detabbed}")
    print(f"validated OK    : {ok}")
    print(f"failed to parse : {len(unparseable)}")
    print(f"failed to valid.: {fail}")
    # Exit non-zero on any parse OR validation failure, so this can gate.
    # Excerpts are declared-not-documents and do not gate.
    return 1 if (fail or unparseable) else 0


if __name__ == "__main__":
    sys.exit(main())
