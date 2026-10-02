#!/usr/bin/env python3
"""Shared signature matcher for the doc-coherer grader and recall audit.

A `fix` inventory entry's `signature` names one target `file` and asserts string
conditions on that file's content. Both `grade.py` (per-group scoring) and
`recall_audit.py` (whole-tree miss audit) check signatures the same way, so the
matcher lives here, in one place, to keep them from drifting.

Matching is **whitespace-tolerant**: the file text and every needle have their
whitespace runs (spaces, tabs, newlines) collapsed to a single space before the
substring test. A correct fix must not be failed merely because a line-wrap or a
re-indent happened to fall between two words of the expected phrase — that is a
property of the rendered Markdown, not of the fix. (This is the one place the old
exact-`in` matcher produced a false negative in practice: a flatten-route fix
whose "…is served here" wrapped across a newline.)

Signature fields (all optional except `file`, which the callers read):
  must_contain      list[str] — EVERY string must be present   (logical AND)
  must_contain_any  list[str] — AT LEAST ONE must be present    (logical OR), for a
                                fix whose correct wording has several equally-valid
                                phrasings. Empty / absent -> this check is skipped,
                                so entries that don't use it are unaffected.
  must_not_contain  list[str] — EVERY string must be absent (the stale text is gone)
"""
import re

_WS = re.compile(r"\s+")


def normalize(s):
    """Collapse every whitespace run (incl. newlines) to a single space."""
    return _WS.sub(" ", s)


def satisfies(sig, text):
    """Return (ok: bool, reason: str) for `sig` against a file's `text`.

    Whitespace-tolerant substring matching; see the module docstring for the
    field semantics. `reason` names the first failing condition (for diagnostics)
    or "ok" on success.
    """
    norm = normalize(text)

    for needle in sig.get("must_contain", []):
        if normalize(needle) not in norm:
            return False, f"missing must_contain {needle!r}"

    any_of = sig.get("must_contain_any", [])
    if any_of and not any(normalize(n) in norm for n in any_of):
        return False, f"none of must_contain_any {any_of!r} present"

    for needle in sig.get("must_not_contain", []):
        if normalize(needle) in norm:
            return False, f"still contains must_not_contain {needle!r}"

    return True, "ok"
