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

One honest limit on that claim, found by mod 133 and left standing rather than
overstated: unbounded citations are **counted, not enumerated**. You learn how
many headings went unchecked; you do not learn which. That is a weaker report
than the other two declined classes give, and it matters more than it looks,
because `doctrine_excerpts/`'s house style is unbounded in 14 of its 16
`Doctrine reference:` lines — so the citation check is close to blind in the one
directory whose dead citation motivated building it. Enumerating them is logged
at `docex/plans/advances/008_housekeeping/references/unbounded_citation_enumeration.md`.

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
