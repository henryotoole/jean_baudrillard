#!/usr/bin/env python3
"""Deterministic mechanical checks for the doctrine corpus and its skills.

Covers two of the four mechanical checks in the cohere skill:
  1. Broken links / references (missing files, missing heading anchors)
  3. Identical filenames (every doctrine filename must be unique)

Spelling/grammar (check 2) stays an LLM pass — it is not deterministic.
Examples that do not compile (check 4) are `verify_examples.py`'s job.

Both `doctrine/` and `skills/` are scanned by default. `doctrine.md` calls
keeping thread-skill pointers valid "the one ongoing cost of this structure,
and it should be checked mechanically" — scanning only `doctrine/` left every
skill->doctrine link unchecked, and left every doctrine link *out* of the
scanned tree with its anchor silently unverified (the anchor table is built
only from scanned files, so an unknown target fails open).

Usage:
    python3 linkcheck.py [ROOT ...]

ROOTs default to the `doctrine/` and `skills/` dirs resolved relative to this
script's location ($jb). Exits non-zero if any problem is found.
"""
import os
import re
import sys

# This file lives at $jb/skills/cohere/executor/.
_SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
JB_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
DOCTRINE_ROOT = os.path.join(JB_ROOT, "doctrine")
SKILLS_ROOT = os.path.join(JB_ROOT, "skills")
DEFAULT_ROOTS = [DOCTRINE_ROOT, SKILLS_ROOT]

FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def slugify(heading):
    """Replicate GitHub's heading-anchor algorithm.

    WHY each step matters: GitHub lowercases, strips punctuation (keeping word
    chars, whitespace, and hyphens), then maps EACH whitespace char to its own
    hyphen. It does NOT collapse runs — so "Elastic × Production" becomes
    "elastic--production" (the stripped `×` leaves two spaces → two hyphens).
    Collapsing here was the original false-positive bug.
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
        # WHY: headings inside fenced code blocks are not real headings.
        s = slugify(m.group(1))
        if s in seen:
            seen[s] += 1
            final.add(f"{s}-{seen[s]}")
        else:
            seen[s] = 0
            final.add(s)
    return final


def strip_code(lines):
    """Yield (lineno, scannable_text) with fenced blocks dropped and inline
    code spans blanked, so example links in code never read as real links."""
    in_fence = False
    for i, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i, INLINE_CODE_RE.sub("", line)


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


def main():
    roots = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_ROOTS
    roots = [os.path.realpath(r) for r in roots]
    for r in roots:
        if not os.path.isdir(r):
            print(f"ERROR: root not found: {r}", file=sys.stderr)
            return 2

    # WHY: `relpath` against one of several roots is ambiguous, so display
    # paths hang off the common ancestor of every root instead.
    display_base = os.path.realpath(os.path.commonpath(roots + [JB_ROOT]))

    md_files = []
    for root in roots:
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if fn.endswith(".md"):
                    md_files.append(os.path.join(dp, fn))
    md_files = sorted(set(os.path.realpath(f) for f in md_files))

    # WHY: one anchor table across every root, so a skill->doctrine (or
    # doctrine->skill) link has its anchor actually checked rather than
    # skipped by the `rp in anchors` guard below.
    anchors = {}
    for f in md_files:
        with open(f) as fh:
            anchors[f] = anchors_for(heading_text(fh.readlines()))

    problems = []

    # Check 1: broken links / anchors.
    for f in md_files:
        with open(f) as fh:
            lines = fh.readlines()
        rel = os.path.relpath(f, display_base)
        for lineno, scannable in strip_code(lines):
            for m in LINK_RE.finditer(scannable):
                target = m.group(2).strip()
                if target.startswith(("http://", "https://", "mailto:", "#!")):
                    continue
                if target.startswith("#"):
                    path, anchor = f, target[1:]
                else:
                    parts = target.split("#", 1)
                    rawpath = parts[0]
                    anchor = parts[1] if len(parts) > 1 else None
                    path = f if rawpath == "" else os.path.normpath(
                        os.path.join(os.path.dirname(f), rawpath))
                if not os.path.exists(path):
                    problems.append(f"BROKEN FILE  {rel}:{lineno}  -> {target}")
                    continue
                if anchor:
                    rp = os.path.realpath(path)
                    if rp in anchors and anchor.lower() not in anchors[rp]:
                        problems.append(
                            f"BAD ANCHOR   {rel}:{lineno}  -> {target}  "
                            f"(anchor '{anchor}' not found)")

    # Check 3: identical filenames.
    #
    # WHY the skills tree is exempt: the uniqueness rule is a *doctrine-corpus*
    # rule — `doctrine.md` states it about doctrine files. `skills/` carries one
    # file named SKILL.md per skill by the Agent Skills Standard, so including
    # them would emit one false positive per skill and make the check useless.
    # The rule is unchanged; it is applied to the tree it was written about.
    # Scoping is by root name so an explicitly-passed root behaves the same way.
    checked_roots = [r for r in roots if os.path.basename(r) != "skills"]
    by_name = {}
    for f in md_files:
        if not any(os.path.commonpath([f, r]) == r for r in checked_roots):
            continue
        by_name.setdefault(os.path.basename(f), []).append(
            os.path.relpath(f, display_base))
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            problems.append(f"DUP FILENAME {name}  ->  {', '.join(sorted(paths))}")

    if problems:
        print("\n".join(problems))
    else:
        print("No broken links, bad anchors, or duplicate filenames found.")
    print(f"\nScanned {len(md_files)} markdown files under "
          f"{', '.join(os.path.relpath(r, display_base) or '.' for r in roots)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
