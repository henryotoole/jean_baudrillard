#!/usr/bin/env python3
"""Deterministic mechanical checks for the doctrine corpus.

Covers two of the three mechanical checks in the cohere skill:
  1. Broken links / references (missing files, missing heading anchors)
  3. Identical filenames (every doctrine filename must be unique)

Spelling/grammar (check 2) stays an LLM pass — it is not deterministic.

Usage:
    python3 linkcheck.py [DOCTRINE_ROOT]

DOCTRINE_ROOT defaults to the `doctrine/` dir resolved relative to this
script's location ($jb/doctrine). Exits non-zero if any problem is found.
"""
import os
import re
import sys

# Default to $jb/doctrine: this file lives at $jb/skills/cohere/executor/.
_SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", "..", "doctrine"))

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
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        print(f"ERROR: doctrine root not found: {root}", file=sys.stderr)
        return 2

    md_files = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".md"):
                md_files.append(os.path.join(dp, fn))

    anchors = {}
    for f in md_files:
        with open(f) as fh:
            anchors[os.path.realpath(f)] = anchors_for(heading_text(fh.readlines()))

    problems = []

    # Check 1: broken links / anchors.
    for f in md_files:
        with open(f) as fh:
            lines = fh.readlines()
        rel = os.path.relpath(f, root)
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
    by_name = {}
    for f in md_files:
        by_name.setdefault(os.path.basename(f), []).append(os.path.relpath(f, root))
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            problems.append(f"DUP FILENAME {name}  ->  {', '.join(sorted(paths))}")

    if problems:
        print("\n".join(problems))
    else:
        print("No broken links, bad anchors, or duplicate filenames found.")
    print(f"\nScanned {len(md_files)} markdown files under {root}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
