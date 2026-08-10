# Mod 132 — Implementation

Design: [`overview.md`](./overview.md). Read § 1–4 and § 11–12 of it before
starting; the *reasons* behind the matching rules below are there and are not
repeated here.

**Repo root (`$jb`): `/home/ubuntu/.claude/jean_baudrillard`.** All paths below are
relative to it. Use absolute paths in commands.

**There is no Python on `PATH` in this repo.** Interpreters:

- `$jb/docex/.venv/bin/python` — for the `docex` suite.
- `python3` — the system interpreter, which has pytest 9.0.3. The new tests must
  run under **this** one (the tool imports nothing but the standard library).

**Territory.** You may edit only:

1. `skills/cohere/executor/linkcheck.py`
2. `skills/cohere/executor/tests/` (new) and `skills/cohere/executor/.gitignore` (new)
3. `skills/cohere/SKILL.md`
4. `docex/test_projects/PRE_CUT_CHECKLIST.md` — **one word**, step 3
5. `docex/plans/advances/007_small_edges/changelog_released_section_link_paths.md` — append only

**Do NOT touch**, even if you find something wrong (report it instead):
anything under `doctrine/`; anything under `docex/src/`, `docex/tests/`,
`docex/tables/`; anything under `docex/test_projects/fixed/` or
`docex/test_projects/elastic/` (those are separate inner git repos and sarge owns a
pending fix in them); `RELEASING.md`; the repo-root `CHANGELOG.md` (the mod-cycle
changelog entry is written later, by the corporal, not by this step).

---

## Step 0 — Preconditions

```
cd /home/ubuntu/.claude/jean_baudrillard
git branch --show-current          # expect 006_surfaces_and_health
git status --porcelain             # expect only the 132_* mod folder
```

Record the two baselines you must not move:

```
cd /home/ubuntu/.claude/jean_baudrillard
docex/.venv/bin/python skills/cohere/executor/linkcheck.py doctrine skills | tail -2
#   expect: green, "Scanned 76 markdown files under doctrine, skills"
```

The `docex` suite baseline is **1174 passed, 18 deselected** (~8 minutes). Do not
run it now — run it once, at step 8, and start it in the background while you do
step 7.

---

## Step 1 — Rewrite `skills/cohere/executor/linkcheck.py`

Replace the file wholesale with the content below. It is the design as measured;
do not improvise the matching rules — every constant in `classify_citation` and
`resolve_cited_path` was chosen against a measured corpus outcome, and loosening
one changes the false-positive surface.

Two properties to preserve while editing anything: **zero third-party imports**,
and **`slugify` must not collapse hyphen runs and must not strip `_`** (both were
real false-positive bugs; step 5's tests pin them).

```python
#!/usr/bin/env python3
"""Deterministic mechanical checks for the doctrine corpus and its skills.

Covers two of the four mechanical checks in the cohere skill, plus one arm this
file grew for the citation form neither of them can see:

  1.  Broken links / references (missing files, missing heading anchors)
  1b. Dead citations: `<file>.md § <Heading>` whose heading no longer exists
  3.  Identical filenames (every doctrine filename must be unique)

Spelling/grammar (check 2) stays an LLM pass — it is not deterministic.
Examples that do not compile (check 4) are `verify_examples.py`'s job.

Usage:
    python3 linkcheck.py [ROOT ...]

ROOTs default to DEFAULT_ROOTS below. Exits non-zero if any problem is found.

THE SCOPES ARE INDEPENDENT, ON PURPOSE
--------------------------------------
Checks 1 and 1b walk every passed root. Check 3 walks only those scanned files
that live under `doctrine/`.

WHY check 3 is an allowlist of one tree rather than a list of exempt trees: the
exemption list had to grow twice for the same reason. `skills/` carries one
SKILL.md per skill by the Agent Skills Standard; `test_projects/{fixed,elastic}/`
mirror each other because audit box B.14 requires their `core/` trees be
byte-identical; `doctrine_excerpts/` mirrors doctrine filenames by design. A rule
whose exception list grows every time the scan widens was never "all roots minus
exceptions" — it was always "the doctrine corpus", written backwards. As an
allowlist, widening the scan can NEVER make check 3 fire, so this tool cannot be
pushed into the always-exit-non-zero state that trains readers to ignore it.

The rule earns its keep twice: doctrine filenames must be unique BECAUSE doctrine
files are cited by bare filename across the corpus, which is exactly what lets
check 1b resolve `cicl.md § Surfaces`. Where uniqueness genuinely does not hold
(the mirrored trees), 1b reports an ambiguity instead of guessing.

CITATIONS: WHOSE WORDS ARE CHECKED BY WHOM
------------------------------------------
A citation has two halves that drift independently — a machine-readable target
and human-readable words. Check 1 has always verified the target. Nothing
verified the words.

  in link text      [cicl.md § Surfaces](../cicl.md#surfaces)
                    anchor: check 1.  words: check 1b.  The anchor can resolve
                    while the words name a heading that is gone; that shape was
                    found live in PRE_CUT_CHECKLIST.md.
  in a code span    `cicl.md § Surfaces`
                    no link at all. Bounded by the closing backtick, so the
                    heading text has a known extent and is checked.
  bare in prose     `tests.md` § Integration Tests and § Contract Tests
                    UNBOUNDED — the heading runs into the sentence. The file is
                    verified; the heading is counted, never guessed. Three
                    measured shapes each defeat a different guess about where the
                    text ends (a bare section number, a truncated title, `§35)`
                    inside a parenthetical), and a wrong finding provokes a wrong
                    repair. Bounding a citation is what brings its words into
                    scope.

A NAIVE VERSION OF 1b REPORTS 98 FALSE POSITIVES. The dominant form in this
corpus is the link-text one, and matching `<file>.md §` in a raw line eats the
link text and then the rest of the sentence. `prose_citations` therefore
collapses every markdown link to its target before scanning — which also keeps
the hybrid form `[`hex/jobs.md`](./hex/jobs.md) § Concurrency` visible.

A VERIFIER MAY DECLINE TO ANSWER; IT MAY NOT DECLINE QUIETLY
------------------------------------------------------------
Everything this file cannot check is counted and printed in the "Declined"
block: anchors whose target is not markdown, citations whose filename matches
more than one file, and unbounded citations. Nothing is skipped in silence.

That rule is written here because the opposite shipped in this file: the anchor
check used to read `if rp in anchors and ...`, where `anchors` held only the
SCANNED files — so any link pointing outside the roots had its anchor skipped
with no output at all, under the headline "No broken links, bad anchors, or
duplicate filenames found." Anchors are now resolved on demand, and the count
that resolved outside the scanned roots is printed.
"""
import os
import re
import sys

# This file lives at $jb/skills/cohere/executor/.
_SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
JB_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
DOCTRINE_ROOT = os.path.join(JB_ROOT, "doctrine")
SKILLS_ROOT = os.path.join(JB_ROOT, "skills")

# WHY these five: every live doctrine-adjacent markdown artifact. Frozen records
# (mod/advance docs, released changelog sections, upgrade guides) and
# deliberately-broken fixtures (skill_iter's drift fixtures) stay out — their
# stale links are the record or the fixture, not a finding.
#   doctrine_excerpts/  is REQUIRED: the dead citation that motivated check 1b
#                       lived there, and it is the one aligned artifact with no
#                       other automated consumer.
#   test_projects/      brings PRE_CUT_CHECKLIST.md — which gates both smoke
#                       walks — inside the shipped default reach.
DEFAULT_ROOTS = [
    DOCTRINE_ROOT,
    SKILLS_ROOT,
    os.path.join(JB_ROOT, "docex", "doctrine_excerpts"),
    os.path.join(JB_ROOT, "docex", "plans", "core"),
    os.path.join(JB_ROOT, "docex", "test_projects"),
]

# WHY: generated residue is not a document. Two untracked `.pytest_cache/README.md`
# files inside the seed trees were being scanned as corpus files.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}

FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
CITE_RE = re.compile(r"(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.md)[`)\]]*\s*§\s*")
CHANGELOG_SECTION_RE = re.compile(r"^##\s+")
CHANGELOG_RELEASED_RE = re.compile(r"^##\s+\[(?!Unreleased\b)[^\]]+\]")
# WHY: a single all-lowercase token after § names a FIELD or RESOURCE documented
# inside the linked section (`§ env`, `§ ecs_cluster`), not a heading. Requiring
# all-lowercase is what keeps `§ Fan-out` and `§ Standards` — single tokens too —
# checked. Applied only AFTER every heading-matching rule has failed.
IDENTIFIER_RE = re.compile(r"^[a-z0-9_.\-/]+$")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#!")


def slugify(heading):
    """Replicate GitHub's heading-anchor algorithm.

    WHY each step matters: GitHub lowercases, strips punctuation (keeping word
    chars, whitespace, and hyphens), then maps EACH whitespace char to its own
    hyphen. It does NOT collapse runs — so "Elastic × Production" becomes
    "elastic--production" (the stripped `×` leaves two spaces → two hyphens).
    Collapsing here was the original false-positive bug. `_` is a word char and
    must survive: stripping it as markdown emphasis is how a checker written by
    hand for this advance nearly "fixed" two correct links.
    """
    h = heading.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h)   # drop punctuation; keep \w, whitespace, hyphen
    h = re.sub(r"\s", "-", h)        # each whitespace char -> one hyphen (no collapsing)
    return h


def anchors_for(text):
    """Return the set of valid anchors for a file's text, with GitHub's
    numeric suffixing for duplicate headings (foo, foo-1, foo-2, ...)."""
    final = set()
    seen = {}
    for m in HEADING_RE.finditer(text):
        s = slugify(m.group(1))
        if s in seen:
            seen[s] += 1
            final.add(f"{s}-{seen[s]}")
        else:
            seen[s] = 0
            final.add(s)
    return final


def heading_text(lines):
    """Reconstruct heading-only text (outside fences) for anchor extraction."""
    out = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "".join(out)


def markdown_files(root):
    """Every `.md` under `root`, generated residue skipped."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                out.append(os.path.realpath(os.path.join(dirpath, fn)))
    return out


class Corpus:
    """Lazy anchor extraction and basename lookup over a whole repo.

    WHY lazy and WHY repo-wide rather than scan-wide: a link or a citation may
    point at a file outside the scanned roots, and the old code's response to
    that was to skip the check silently.
    """

    def __init__(self, index_root):
        self.index_root = os.path.realpath(index_root)
        self._anchors = {}
        self._by_basename = None

    def anchors(self, path):
        rp = os.path.realpath(path)
        if rp not in self._anchors:
            with open(rp) as fh:
                self._anchors[rp] = anchors_for(heading_text(fh.readlines()))
        return self._anchors[rp]

    def by_basename(self, name):
        if self._by_basename is None:
            index = {}
            for f in markdown_files(self.index_root):
                index.setdefault(os.path.basename(f), []).append(f)
            self._by_basename = index
        return self._by_basename.get(name, [])


def resolve_cited_path(citing, raw, corpus):
    """Resolve a cited path. Returns (realpath, "ok") | (None, "ambiguous"|"missing").

    WHY the basename fallback: citations are written the way a reader speaks —
    `cicl.md § Surfaces`, or with an elided path
    (`doctrine/.../projinfra/elastic_route53_zone.md § Teardown`). It is only
    sound because check 3 keeps doctrine basenames unique; where a basename is
    genuinely ambiguous this returns "ambiguous" rather than picking one.
    """
    if not raw:
        return os.path.realpath(citing), "ok"
    for cand in (os.path.join(os.path.dirname(citing), raw),
                 os.path.join(corpus.index_root, raw)):
        cand = os.path.normpath(cand)
        if os.path.isfile(cand):
            return os.path.realpath(cand), "ok"
    hits = corpus.by_basename(os.path.basename(raw))
    tail = raw.lstrip("./")
    narrowed = [h for h in hits if h.endswith("/" + tail)] if "/" in raw else hits
    for candidates in (narrowed, hits):
        if len(candidates) == 1:
            return candidates[0], "ok"
    return None, ("ambiguous" if hits else "missing")


def classify_citation(head, anchors):
    """Match a citation's visible words against a file's real headings.

    Returns one of: exact, truncated, extended, identifier, empty, miss. Each
    accepting rule names an authorial form found in the corpus rather than a
    tolerance tuned until the noise stopped — see overview.md § 2.1 for the
    measured counts behind each.
    """
    slug = slugify(head)
    if not slug:
        return "empty"
    if slug in anchors:
        return "exact"
    if any(a.startswith(slug + "-") for a in anchors):
        # truncated title: `§ Per-core-service env` -> "... (both foundations)"
        return "truncated"
    if any(slug.startswith(a + "-") for a in anchors):
        return "extended"
    if IDENTIFIER_RE.match(head.strip()):
        return "identifier"
    return "miss"


def scannable_lines(path, stats):
    """Yield (lineno, raw_line), skipping fenced blocks and RELEASED changelog
    sections.

    WHY fences: headings and links inside a fenced block are examples, not links.

    WHY released changelog sections: they are frozen history. A released entry may
    cite a heading that has since been deleted, or a path from before a file
    moved, and revising it would falsify the record — the governing distinction is
    that a link target may be repointed where a claim may not. Without this,
    four permanently-dead citations in the seed projects' history and fourteen
    stale paths in this repo's own changelog would make the tool exit non-zero
    forever, which trains readers to ignore it. `[Unreleased]` is live and stays
    in scope, as does any preamble before the first `##`.
    """
    with open(path) as fh:
        lines = fh.readlines()
    is_changelog = os.path.basename(path) == "CHANGELOG.md"
    in_fence = False
    frozen = False
    for i, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if is_changelog and CHANGELOG_SECTION_RE.match(line):
            frozen = bool(CHANGELOG_RELEASED_RE.match(line))
        if frozen:
            stats["frozen_lines"] += 1
            continue
        yield i, line


def link_text_citations(line):
    """Yield (cited_name, resolve_path, head) for citations inside link TEXT.

    The link's target is check 1's business; these are the visible WORDS, which
    were nobody's. The TARGET is authoritative for which file is meant — the two
    halves are written independently, and that is the whole point.
    """
    spans = [(m.start(), m.end()) for m in INLINE_CODE_RE.finditer(line)]
    for m in LINK_RE.finditer(line):
        # WHY: a whole [text](target) construct inside a code span is a printed
        # EXAMPLE of a link, not a link.
        if any(s <= m.start() and m.end() <= e for s, e in spans):
            continue
        text, target = m.group(1), m.group(2).strip()
        if "§" not in text:
            continue
        inner = text.strip().strip("`")
        cm = CITE_RE.search(inner)
        if not cm:
            continue
        head = inner[cm.end():].strip().strip("`")
        if target.startswith(EXTERNAL_PREFIXES):
            resolve_path = cm.group("path")
        elif target.startswith("#"):
            resolve_path = ""            # same-file link
        else:
            resolve_path = target.split("#", 1)[0]
        yield cm.group("path"), resolve_path, head


def prose_citations(line):
    """Yield (cited_name, head_or_None) for citations outside link text.

    `head` is None when the citation is UNBOUNDED — path and `§` are not inside
    one common inline-code span, so the heading text has no determinable end.

    WHY links are collapsed to their targets rather than dropped: dropping them
    loses the hybrid form `[`hex/jobs.md`](./hex/jobs.md) § Concurrency`, whose
    words nothing else checks. Collapsing also pads to preserve column offsets.
    """
    collapsed = LINK_RE.sub(
        lambda m: " " * (len(m.group(0)) - len(m.group(2))) + m.group(2), line)
    spans = [(m.start(), m.end()) for m in INLINE_CODE_RE.finditer(collapsed)]
    for m in CITE_RE.finditer(collapsed):
        section = collapsed.index("§", m.start())
        end = None
        for s, e in spans:
            if s <= m.start("path") < e and s <= section < e:
                end = e
                break
        if end is None:
            yield m.group("path"), None
        else:
            yield m.group("path"), collapsed[m.end():end - 1].strip()


def run_checks(roots, doctrine_root=None, index_root=None):
    """Run every check. Returns (problems, declined, stats).

    `problems` are failures (non-zero exit). `declined` are things this tool
    cannot answer; they are printed and counted but do not fail the run.
    """
    doctrine_root = os.path.realpath(doctrine_root or DOCTRINE_ROOT)
    corpus = Corpus(index_root or JB_ROOT)
    roots = [os.path.realpath(r) for r in roots]
    md_files = sorted(set(f for r in roots for f in markdown_files(r)))
    md_set = set(md_files)

    # WHY: `relpath` against one of several roots is ambiguous, so display
    # paths hang off the common ancestor of every root instead.
    display_base = os.path.realpath(os.path.commonpath(roots + [JB_ROOT]))

    problems, declined = [], []
    stats = {
        "files": len(md_files), "check3_files": 0, "frozen_lines": 0,
        "anchors": 0, "anchors_offroot": 0, "anchors_unverifiable": 0,
        "exact": 0, "truncated": 0, "extended": 0, "identifier": 0,
        "empty": 0, "unbounded": 0, "ambiguous": 0,
        "display_base": display_base, "roots": roots,
    }

    def cite(rel, lineno, name, resolve_path, head, citing):
        path, status = resolve_cited_path(citing, resolve_path, corpus)
        if status == "ambiguous":
            stats["ambiguous"] += 1
            declined.append(
                f"AMBIGUOUS CITE {rel}:{lineno}  -> {name} § {head if head else '...'}"
                f"  (that filename matches more than one file)")
            return
        if status == "missing":
            problems.append(
                f"NO CITE FILE {rel}:{lineno}  -> {name} § {head if head else '...'}"
                f"  (no file matches '{name}')")
            return
        if head is None:
            stats["unbounded"] += 1
            return
        verdict = classify_citation(head, corpus.anchors(path))
        if verdict == "miss":
            problems.append(
                f"BAD CITATION {rel}:{lineno}  -> {name} § {head}  "
                f"(heading not found in {os.path.relpath(path, display_base)})")
        else:
            stats[verdict] += 1

    for f in md_files:
        rel = os.path.relpath(f, display_base)
        for lineno, line in scannable_lines(f, stats):

            # Check 1: broken links / anchors. Inline code spans are blanked so
            # example links in prose never read as real links.
            for m in LINK_RE.finditer(INLINE_CODE_RE.sub("", line)):
                target = m.group(2).strip()
                if target.startswith(EXTERNAL_PREFIXES):
                    continue
                if target.startswith("#"):
                    path, anchor = f, target[1:]
                else:
                    parts = target.split("#", 1)
                    anchor = parts[1] if len(parts) > 1 else None
                    path = f if parts[0] == "" else os.path.normpath(
                        os.path.join(os.path.dirname(f), parts[0]))
                if not os.path.exists(path):
                    problems.append(f"BROKEN FILE  {rel}:{lineno}  -> {target}")
                    continue
                if not anchor:
                    continue
                if not (os.path.isfile(path) and path.endswith(".md")):
                    stats["anchors_unverifiable"] += 1
                    declined.append(
                        f"NO ANCHOR RULE {rel}:{lineno}  -> {target}"
                        f"  (target is not a markdown file)")
                    continue
                rp = os.path.realpath(path)
                stats["anchors"] += 1
                # WHY counted: these are exactly the anchors the previous version
                # skipped in silence, because its anchor table held scanned files
                # only. They are now resolved on demand and reported.
                if rp not in md_set:
                    stats["anchors_offroot"] += 1
                if anchor.lower() not in corpus.anchors(rp):
                    problems.append(
                        f"BAD ANCHOR   {rel}:{lineno}  -> {target}  "
                        f"(anchor '{anchor}' not found)")

            # Check 1b: citations. Two passes, and they cannot double-report:
            # collapsing links in `prose_citations` removes the text the first
            # pass reads.
            for name, resolve_path, head in link_text_citations(line):
                cite(rel, lineno, name, resolve_path, head, f)
            for name, head in prose_citations(line):
                cite(rel, lineno, name, name, head, f)

    # Check 3: identical filenames, over the doctrine corpus only.
    by_name = {}
    for f in md_files:
        if os.path.commonpath([f, doctrine_root]) != doctrine_root:
            continue
        by_name.setdefault(os.path.basename(f), []).append(
            os.path.relpath(f, display_base))
    stats["check3_files"] = sum(len(v) for v in by_name.values())
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            problems.append(f"DUP FILENAME {name}  ->  {', '.join(sorted(paths))}")

    return problems, declined, stats


def main():
    roots = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_ROOTS
    roots = [os.path.realpath(r) for r in roots]
    for r in roots:
        if not os.path.isdir(r):
            print(f"ERROR: root not found: {r}", file=sys.stderr)
            return 2

    problems, declined, stats = run_checks(roots)
    base = stats["display_base"]

    if problems:
        print("\n".join(problems))
    else:
        print("No broken links, bad anchors, dead citations, or duplicate "
              "filenames found.")

    if declined:
        print("\nDeclined — counted, not failures. A verifier may decline to "
              "answer, but not quietly:")
        print("\n".join("  " + d for d in declined))

    checked = stats["exact"] + stats["truncated"] + stats["extended"]
    print(f"\nScanned {stats['files']} markdown files under "
          f"{', '.join(os.path.relpath(r, base) or '.' for r in stats['roots'])}")
    print(f"  links, anchors, citations : {stats['files']} files")
    print(f"  duplicate filenames       : {stats['check3_files']} files "
          f"(the doctrine corpus only)")
    print(f"  anchors                   : {stats['anchors']} checked, "
          f"{stats['anchors_offroot']} of them outside the scanned roots, "
          f"{stats['anchors_unverifiable']} unverifiable")
    print(f"  citations                 : {checked} checked "
          f"({stats['exact']} exact / {stats['truncated']} truncated / "
          f"{stats['extended']} extended), {stats['identifier']} identifier refs, "
          f"{stats['unbounded']} unbounded (file checked, heading not), "
          f"{stats['ambiguous']} ambiguous")
    print(f"  frozen changelog lines    : {stats['frozen_lines']} skipped")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

### 1.1 Sanity-check it before going further

```
cd /home/ubuntu/.claude/jean_baudrillard
docex/.venv/bin/python skills/cohere/executor/linkcheck.py doctrine skills
```

Expect: green; `Scanned 76 markdown files`; `duplicate filenames : 54 files`;
non-zero counts on the `anchors` and `citations` lines. Then:

```
docex/.venv/bin/python skills/cohere/executor/linkcheck.py
```

Expect **exactly one** problem before step 3 is done — the `BAD CITATION` at
`docex/test_projects/PRE_CUT_CHECKLIST.md:182`, and nothing else. If any other
problem appears, **stop and report it**: it is either a defect in your
transcription of the code above or a real finding the design did not predict, and
either way the corporal decides, not you.

Reference figures at the default scope (from the design measurement — a small
drift in one is fine, a large one means something is wrong):

| Figure | Expected |
| ------ | -------: |
| files scanned | 127 |
| check-3 files | 54 |
| citations checked | 246 |
| — of which exact / truncated / extended | 237 / 7 / 2 |
| identifier refs | 5 |
| unbounded | 27 |
| ambiguous | 0 |
| frozen changelog lines | 545 |
| problems | 1 (step 3 takes it to 0) |

---

## Step 2 — Demonstrate the arm **failing**, before it is believed

A pass never contrasted against a fail is not a check. Reconstruct the real
instance this arm exists for — the dead citation mod 131 repaired in
`docex/doctrine_excerpts/service_discovery.md`.

1. Find the live citation near line 22. It currently reads
   `` `infrastructure/specifics/release.md § Service Connect Consumer Reconcile` ``.
2. Temporarily replace that one citation with the pre-131 dead form:
   `` `cicl.md § Resilience covers reachability, not resolvability` ``
   (`cicl.md` has no heading beginning "Resilience"; verified at design time).
3. Run `docex/.venv/bin/python skills/cohere/executor/linkcheck.py` and **capture
   the output verbatim.** Expect a `BAD CITATION` line naming
   `doctrine/infrastructure/cicl.md`, and `echo $?` → `1`.
4. `git checkout docex/doctrine_excerpts/service_discovery.md`, re-run, and
   capture the contrast.

Paste both transcripts into `## Demonstration` in this mod's `implementation.md`
(append a section at the end of this file) — the red one, the green one, and both
exit codes. **Do not skip this because the fixture in step 5 covers it.** The
fixture proves the code; this proves the code against the real corpus.

---

## Step 3 — Repair the one live finding

`docex/test_projects/PRE_CUT_CHECKLIST.md`, line 182. The citation reads
`` [`infrastructure.md § Codebase Structure`](../../doctrine/infrastructure/infrastructure.md#repository-structure) ``.
The anchor is correct; the words are not — `infrastructure.md` has *Repository
Structure* and *Codebase Containers*, and no *Codebase Structure*.

Change **only** the citation text: `§ Codebase Structure` → `§ Repository
Structure`. Do not touch the anchor, the surrounding checklist prose, or anything
else in the file. Re-run the default invocation: **zero problems.**

---

## Step 4 — `skills/cohere/executor/.gitignore` (new)

```
__pycache__/
.pytest_cache/
```

WHY: the repo has no root `.gitignore`, and running the tool or its tests leaves
bytecode residue that shows up as untracked. Bytecode residue was its own mod
once (119).

---

## Step 5 — Tests: `skills/cohere/executor/tests/`

Two new files. They must pass under **`python3 -m pytest`** with no virtualenv.

**`tests/conftest.py`** — put the executor directory on `sys.path` so
`import linkcheck` works regardless of the invoking directory:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
```

**`tests/test_linkcheck.py`** — hermetic. Every test builds a fake corpus under
`tmp_path` and calls
`linkcheck.run_checks([roots], doctrine_root=tmp/"doctrine", index_root=tmp)`.
**No test may read the real `doctrine/` tree**: a test that fails when someone
edits doctrine prose is a gate, not a test, and the gate already exists.

Write a small helper that writes files from a dict, e.g.
`write(tmp_path, {"doctrine/a.md": "# Title\n...", ...})`, and a helper that
returns `(problems, declined, stats)`.

### 5.1 The positive control — one fixture, asserted to yield **zero** problems

This is the answer to the two false positives this advance produced (mod 131's
checker stripping `_` as emphasis; this mod's first prototype reporting 98
findings on a clean tree). Build **one** fixture corpus containing all of the
following, and assert `problems == []`. Then assert the individual counts, so a
regex regression that silently stops matching cannot pass by finding nothing.

Headings to place in a target file (`doctrine/target.md`):

| Heading | Anchor it must produce | Pins |
| ------- | ---------------------- | ---- |
| `## The health_check_path field` | `the-health_check_path-field` | `_` survives slugify |
| `## verify_clean.sh` | `verify_clean.sh` → `verify_clean.sh`? **compute it, do not guess** — `.` is stripped, so `verify_cleansh` | `_` + `.` handling |
| `## A.7 Fixed deploy credentials and deploy-target user` | `a7-fixed-deploy-credentials-and-deploy-target-user` | dots, digits, hyphens |
| ``## `uses` Relationships`` | `uses-relationships` | backticks in a heading |
| `## Elastic × Production` | `elastic--production` | **hyphen runs must not collapse** |
| `## Repeated` twice | `repeated` and `repeated-1` | GitHub duplicate suffixing |
| `## Per-core-service env (both foundations)` | — | target for the truncated rule |
| `## Standards` | — | target for a single-token capitalized citation |

Citing content that must all pass:

1. Markdown links to each anchor above, including the `_` and `×` ones.
2. **Link-text citations** — the 98-false-positive class, pinned as a control:
   one exact (`[target.md § Standards](./target.md#standards)`), one truncated
   (`[target.md § Per-core-service env](./target.md#per-core-service-env-both-foundations)`),
   and one carrying trailing words so the `extended` rule fires
   (`[target.md § Standards and floors](./target.md#standards)` — slug
   `standards-and-floors` begins with the real anchor `standards` + `-`).
3. An **identifier reference** in link text:
   `[target.md § env](./target.md#standards)` — must count as `identifier`, not
   a problem.
4. Code-span citations: `` `target.md § Standards` ``, and one with an
   underscore heading.
5. All three **unbounded** shapes, none of which may be reported. In each the
   `§` sits *outside* any inline-code span, which is what makes the heading's end
   undecidable — so each must land in `stats["unbounded"]`, with the file still
   resolved:
   - section number then prose — ``See `target.md` § A.7 is the section that says so.``
   - truncated title then a sentence period — ``See `target.md` § Standards.``
   - number, no space, in a parenthetical — `(per target.md §7): as above`
6. A citation inside a **fenced block**, and a whole markdown link inside a code
   span — both ignored.
7. A bare `§ Standards` with no filename — ignored.
8. An **elided** path: `` `doctrine/.../target.md § Standards` `` resolving by
   unique basename.
9. Two mirrored trees **outside** `doctrine/` holding identically-named files —
   no `DUP FILENAME`.
10. A `CHANGELOG.md` whose **released** section carries a dead citation *and* a
    broken relative link — neither reported.

### 5.2 The negative controls — each **exactly one** problem, of the right class

One test per row. Assert the count *and* the label, and assert nothing else fires.

| Case | Expected |
| ---- | -------- |
| Code-span citation to a heading that does not exist (the § 2 instance: `` `cicl.md § Resilience covers reachability, not resolvability` `` against a `cicl.md` with other headings) | one `BAD CITATION` |
| **Link text naming a dead heading while the anchor resolves** — the `PRE_CUT_CHECKLIST.md:182` class, and the arm's entire justification | one `BAD CITATION`, and **no** `BAD ANCHOR` |
| Markdown link with a dead anchor | one `BAD ANCHOR` |
| Markdown link to a file that does not exist | one `BROKEN FILE` |
| Citation naming a file that exists nowhere | one `NO CITE FILE` |
| Link with an anchor into a `.md` file **outside** the scanned roots, anchor dead | one `BAD ANCHOR` — this is the fail-open regression test; the old code reported nothing here |
| Two identically-named files **inside** `doctrine/` | one `DUP FILENAME` |
| A dead citation in a `CHANGELOG.md` **`[Unreleased]`** section | one `BAD CITATION` — proves the exclusion keys on the section, not the filename |

### 5.3 Declined-block tests

| Case | Expected |
| ---- | -------- |
| Link with an anchor whose target is **not** markdown (`../foo.py#L10`) | `problems == []`; one `NO ANCHOR RULE` in `declined`; `stats["anchors_unverifiable"] == 1` |
| Citation by a bare filename that matches two files | `problems == []`; one `AMBIGUOUS CITE`; `stats["ambiguous"] == 1` |
| Unbounded citation | `stats["unbounded"] == 1` and `problems == []` |
| Anchor resolved into a file outside the roots, anchor **live** | `stats["anchors_offroot"] == 1`, `problems == []` |

### 5.4 Scope tests

| Case | Expected |
| ---- | -------- |
| `run_checks` over a root containing a mirrored non-doctrine pair **plus** `doctrine/` with unique names | no `DUP FILENAME`; `stats["check3_files"]` counts only the doctrine files |
| `run_checks` over a root that is entirely outside `doctrine_root` | `stats["check3_files"] == 0` |
| A `.pytest_cache/README.md` and a `__pycache__` dir inside a scanned root | not counted in `stats["files"]` |
| `slugify` unit cases | `_`, `.`, `×`-double-hyphen, and case folding, asserted directly |

Run them:

```
cd /home/ubuntu/.claude/jean_baudrillard/skills/cohere/executor
python3 -m pytest tests -q
```

All green. Report the test count.

---

## Step 6 — `skills/cohere/SKILL.md`

Replace the `linkcheck.py` bullet (currently line 40) with the following, and
leave every other line of the file alone:

```
- `python3 executor/linkcheck.py` — deterministically reports check 1 (broken links / bad heading anchors), check 3 (duplicate filenames), and a third arm: **dead citations**, where the words of a `<file>.md § <Heading>` reference name a heading that no longer exists. Do not hand-derive GitHub anchor slugs; the executor already encodes them correctly. Two things to know before reading its output:
	- **The two scopes are independent.** Checks 1 and the citation arm walk five roots by default (`doctrine/`, `skills/`, and `docex/`'s `doctrine_excerpts/`, `plans/core/`, and `test_projects/`); the duplicate-filename check walks the doctrine corpus only, because `skills/`, the two seed projects, and `doctrine_excerpts/` all carry mirrored filenames *by design*. Released `CHANGELOG.md` sections are frozen history and are excluded from both.
	- **Read the counts, not just the exit code**, and read the `Declined` block. The tool prints what it *could not* check — unverifiable anchors, ambiguous filenames, and citations whose heading text has no closing delimiter — because a verifier may decline to answer but must not decline quietly. A citation count that falls to zero is a regression in the tool, not a clean corpus.
- `python3 -m pytest executor/tests` — the executors' own tests, ~1 s, no virtualenv needed. Run these **first**. A checker that reports violations where none exist is as corrosive as one that misses them: this advance produced two such false positives, one of which nearly "fixed" two correct links, and these tests are the positive control that pins the classes they came from.
```

---

## Step 7 — Append to the 007 brief

Append this section verbatim to
`docex/plans/advances/007_small_edges/changelog_released_section_link_paths.md`.
Change nothing already in that file.

```
## A third end state, found by mod 132 (appended)

Mod 132 implemented option (1) and, while measuring whether the repo-root files
could come into scope at all, found a case neither option above contemplates.

`CHANGELOG.md:633` — inside **`[Unreleased]`**, so not frozen and not covered by
the exclusion — reads:

> `doctrine_excerpts/secrets.md` cited `specifics/release_mechanism.md § Secrets`
> — a file and a heading that have **never existed** …

That is a changelog entry describing mod 118's *repair* of a dead citation. The
citation is quoted **in order to be dead**, as evidence. Any checker pointed at
that file flags it, and no repair is possible: rewording it would destroy the
evidence, and the entry is a claim rather than a link target.

So repairing the fourteen paths (option 2) is **not sufficient** to bring the
repo-root files into scope. A checker reaching released history — or any live
prose that quotes a dead reference — needs an inline suppression marker
(`<!-- linkcheck-ignore -->` on the line, about two lines of code in
`scannable_lines`). Mod 132 declined to add one on the grounds that it would have
exactly one user, and left the root files out of scope for this measured reason
rather than an aesthetic one.

Whoever takes this brief therefore chooses between three end states, not two:
(1) exclude frozen sections — **done**; (2) repair the fourteen paths; (3) add a
suppression marker, which is what option (2) additionally requires if the goal is
`CHANGELOG.md`, `README.md`, and `RELEASING.md` inside the default scan. Accepting
a *file* (not only a directory) as a root is a five-line change in
`linkcheck.py::main`, deliberately not made.
```

---

## Step 8 — Verification

Run all of it and report every number.

```
cd /home/ubuntu/.claude/jean_baudrillard

# 1. the tool, default scope
docex/.venv/bin/python skills/cohere/executor/linkcheck.py; echo "exit=$?"
#    expect exit=0, ~127 files, and the counts table from § 1.1

# 2. the invocation the release gates use, unchanged
docex/.venv/bin/python skills/cohere/executor/linkcheck.py doctrine skills; echo "exit=$?"
#    expect exit=0, 76 files

# 3. the executor's own tests, no venv
cd skills/cohere/executor && python3 -m pytest tests -q; cd /home/ubuntu/.claude/jean_baudrillard

# 4. the example-compile harness must be unaffected
docex/.venv/bin/python skills/cohere/executor/verify_examples.py | tail -3

# 5. docex's suite must not move
cd docex && .venv/bin/python -m pytest tests -q 2>&1 | tail -3
#    expect exactly: 1174 passed, 18 deselected

# 6. no residue, no stray files
cd /home/ubuntu/.claude/jean_baudrillard
find skills docex/plans/modifications/132_linkcheck_scope_and_citations -name __pycache__ -o -name .pytest_cache
git status --porcelain
```

`git status --porcelain` must show **only**:

```
 M docex/plans/advances/007_small_edges/changelog_released_section_link_paths.md
 M docex/test_projects/PRE_CUT_CHECKLIST.md
 M skills/cohere/SKILL.md
 M skills/cohere/executor/linkcheck.py
?? docex/plans/modifications/132_linkcheck_scope_and_citations/   (or ' M' if already committed)
?? skills/cohere/executor/.gitignore
?? skills/cohere/executor/tests/
```

Anything else — especially a modified file under `doctrine/`, `docex/src/`,
`docex/tests/`, or either seed project — is a mistake to be undone and reported.

**Do not commit.** The corporal handles review, documentation, and both commits.

---

## Step 9 — Report

Report back, with numbers rather than adjectives:

1. The step-2 demonstration: both transcripts and both exit codes.
2. The default-scope counts table, against § 1.1's expected figures, and any
   figure that differed and why.
3. The test count from step 5, and whether any test needed the design's rules
   loosened to pass. **If you loosened a matching rule to make a test pass, say
   so explicitly** — that is a design change, and it is the corporal's call, not
   yours.
4. `pytest tests` → must read `1174 passed, 18 deselected`.
5. `linkcheck doctrine skills` → green, 76 files.
6. Anything you found that is wrong and outside your territory, quoted with
   file:line, **not fixed**.
