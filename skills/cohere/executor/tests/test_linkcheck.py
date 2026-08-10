"""Unit tests for `linkcheck.py` — the checks as functions.

These call `run_checks` with an injected `doctrine_root` and `index_root`. The
executor's **CLI** seam — `main()`, argv, exit codes, and the module's real
default roots — is tested separately in `docex/tests/unit/test_linkcheck.py`,
which runs with `docex`'s suite. The split is by seam, not by convenience; that
file's docstring carries the full argument and a gating caveat.

Run these with `python3 -m pytest tests -p no:cacheprovider` (no virtualenv
needed). The flag matters: pytest's cache directory contains a `README.md`, and
the sibling executor `verify_examples.py` counts every `.md` under its roots.

Every test builds a fake corpus under `tmp_path`. **No test reads the real
`doctrine/` tree**: a test that fails when someone edits doctrine prose is a
gate, not a test, and the gate already exists (the tool itself, run by the
cohere skill).

The centrepiece is `test_positive_control_reports_nothing`. Two false positives
were produced during this advance — a hand-written checker that stripped `_` as
markdown emphasis and nearly "fixed" two correct links, and a first prototype of
the citation arm that reported 98 findings on a clean tree. A checker that
reports violations where none exist is as corrosive as one that misses them, so
the clean fixture asserts **zero** problems *and* asserts the individual counts:
a regex regression that silently stops matching must not be able to pass by
finding nothing.
"""
import os

import linkcheck

PROBLEM_CLASSES = (
    "BROKEN FILE", "BAD ANCHOR", "BAD CITATION", "NO CITE FILE", "DUP FILENAME")
DECLINED_CLASSES = ("NO ANCHOR RULE", "AMBIGUOUS CITE")


def write(base, files):
    """Create `files` — a {relative path: text} map — under `base`."""
    for rel, text in files.items():
        path = os.path.join(str(base), rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return str(base)


def check(tmp, roots=None, doctrine="doctrine"):
    """Run every check over the fake corpus at `tmp`.

    `index_root` is pinned to `tmp` so basename resolution cannot reach the real
    repo; `doctrine_root` is a path *inside* `tmp`, so check 3's allowlist is
    exercised without the real doctrine tree.
    """
    tmp = str(tmp)
    roots = [os.path.join(tmp, r) for r in (roots or ["."])]
    return linkcheck.run_checks(
        roots, doctrine_root=os.path.join(tmp, doctrine), index_root=tmp)


def classify(lines, known):
    """Map each reported line to its class label, asserting all are recognized."""
    out = []
    for line in lines:
        match = [c for c in known if line.startswith(c)]
        assert match, f"unclassifiable line: {line!r}"
        out.append(match[0])
    return out


def only(problems, declined, expected_class):
    """Assert exactly one problem, of `expected_class`, and nothing declined."""
    assert classify(problems, PROBLEM_CLASSES) == [expected_class], problems
    assert declined == [], declined


# --------------------------------------------------------------------------
# slugify / anchors_for units
# --------------------------------------------------------------------------

def test_slugify_keeps_underscores():
    # WHY: stripping `_` as markdown emphasis was a real false positive.
    assert linkcheck.slugify("The health_check_path field") == \
        "the-health_check_path-field"


def test_slugify_strips_dots_and_folds_case():
    assert linkcheck.slugify("verify_clean.sh") == "verify_cleansh"
    assert linkcheck.slugify("A.7 Fixed deploy credentials and deploy-target user") \
        == "a7-fixed-deploy-credentials-and-deploy-target-user"


def test_slugify_does_not_collapse_hyphen_runs():
    # WHY: the stripped `×` leaves two spaces, so GitHub emits two hyphens.
    # Collapsing them was the original false-positive bug in this file.
    assert linkcheck.slugify("Elastic × Production") == "elastic--production"


def test_slugify_strips_backticks_in_heading_text():
    assert linkcheck.slugify("`uses` Relationships") == "uses-relationships"


def test_anchors_for_suffixes_duplicate_headings():
    assert linkcheck.anchors_for("## Repeated\n## Repeated\n## Repeated\n") == \
        {"repeated", "repeated-1", "repeated-2"}


# --------------------------------------------------------------------------
# The positive control
# --------------------------------------------------------------------------

TARGET = """# Target

## The health_check_path field

Body.

## verify_clean.sh

Body.

## A.7 Fixed deploy credentials and deploy-target user

Body.

## `uses` Relationships

Body.

## Elastic × Production

Body.

## Repeated

Body.

## Repeated

Body.

## Per-core-service env (both foundations)

Body.

## Standards

Body.
"""

CITING = """# Citing

Anchor links, one per interesting slug:

- [health field](./target.md#the-health_check_path-field)
- [script](./target.md#verify_cleansh)
- [creds](./target.md#a7-fixed-deploy-credentials-and-deploy-target-user)
- [uses](./target.md#uses-relationships)
- [elastic](./target.md#elastic--production)
- [first](./target.md#repeated)
- [second](./target.md#repeated-1)

Citations inside link text — the 98-false-positive class, pinned as a control:

- exact: [target.md § Standards](./target.md#standards)
- truncated: [target.md § Per-core-service env](./target.md#per-core-service-env-both-foundations)
- extended: [target.md § Standards and floors](./target.md#standards)
- identifier: [target.md § env](./target.md#standards)

Citations inside code spans:

- `target.md § Standards`
- `target.md § The health_check_path field`
- elided path: `doctrine/.../target.md § Standards`

Unbounded — the file is checked, the heading is counted and never guessed:

- See `target.md` § A.7 is the section that says so.
- See `target.md` § Standards.
- (per target.md §7): as above

Ignored constructs:

- a printed example of a link: `[target.md § Nonexistent](./nope.md#nope)`
- a bare section reference with no file: § Standards

```py
`target.md § Nonexistent Heading`
[broken](./nope.md#nope)
```
"""

CHANGELOG = """# Changelog

## [Unreleased]

Nothing dead here.

## [1.2.0] - 2026-01-01

Repaired `target.md § No Such Heading` and moved [a file](./deleted/gone.md).
"""


def test_positive_control_reports_nothing(tmp_path):
    write(tmp_path, {
        "doctrine/target.md": TARGET,
        "doctrine/citing.md": CITING,
        # Two mirrored trees OUTSIDE doctrine/ sharing a filename: check 3 is an
        # allowlist of the doctrine tree, so this can never fire.
        "mirror_a/plans/core/mirrored.md": "# Mirrored A\n",
        "mirror_b/plans/core/mirrored.md": "# Mirrored B\n",
        # A released changelog section carrying a dead citation AND a broken link.
        "proj/CHANGELOG.md": CHANGELOG,
    })
    problems, declined, stats = check(tmp_path)

    assert problems == [], problems
    assert declined == [], declined

    assert stats["files"] == 5
    assert stats["check3_files"] == 2          # only doctrine/{target,citing}.md
    assert stats["anchors"] == 11
    assert stats["anchors_offroot"] == 0
    assert stats["anchors_unverifiable"] == 0
    # 1 in link text, 2 in code spans, 1 by elided path.
    assert stats["exact"] == 4
    assert stats["truncated"] == 1
    assert stats["extended"] == 1
    assert stats["identifier"] == 1
    assert stats["unbounded"] == 3
    assert stats["ambiguous"] == 0
    assert stats["frozen_lines"] == 3


# --------------------------------------------------------------------------
# Negative controls — each exactly one problem, of the right class
# --------------------------------------------------------------------------

def test_dead_code_span_citation(tmp_path):
    """The mod-131 instance: a code-span citation to a heading that is gone."""
    write(tmp_path, {
        "doctrine/cicl.md": "# CICL\n\n## Surfaces\n\n## Service Fields\n",
        "doctrine/a.md":
            "Per `cicl.md § Resilience covers reachability, not resolvability`.\n",
    })
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "BAD CITATION")
    assert "cicl.md" in problems[0]


def test_link_text_dead_words_with_live_anchor(tmp_path):
    """The PRE_CUT_CHECKLIST.md:182 class — the arm's entire justification.

    The anchor resolves, so check 1 passes it and always would have. The words
    name a section that does not exist.
    """
    write(tmp_path, {
        "doctrine/target.md": "# T\n\n## Repository Structure\n",
        "doctrine/a.md":
            "Per [`target.md § Codebase Structure`]"
            "(./target.md#repository-structure).\n",
    })
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "BAD CITATION")
    assert "BAD ANCHOR" not in "\n".join(problems)


def test_dead_markdown_anchor(tmp_path):
    write(tmp_path, {
        "doctrine/target.md": "# T\n\n## Standards\n",
        "doctrine/a.md": "See [x](./target.md#nope).\n",
    })
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "BAD ANCHOR")


def test_link_to_missing_file(tmp_path):
    write(tmp_path, {"doctrine/a.md": "See [x](./missing.md).\n"})
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "BROKEN FILE")


def test_citation_to_file_that_exists_nowhere(tmp_path):
    write(tmp_path, {"doctrine/a.md": "Per `nowhere.md § Whatever`.\n"})
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "NO CITE FILE")


def test_dead_anchor_in_file_outside_the_scanned_roots(tmp_path):
    """The fail-open regression test.

    The old guard read `if rp in anchors and ...` against a table built only from
    SCANNED files, so this case was skipped in silence under a green headline.
    """
    write(tmp_path, {
        "scan/a.md": "See [x](../outside/other.md#nope).\n",
        "outside/other.md": "# Other\n\n## Live\n",
    })
    problems, declined, stats = check(tmp_path, roots=["scan"])
    only(problems, declined, "BAD ANCHOR")
    assert stats["anchors"] == 1
    assert stats["anchors_offroot"] == 1


def test_duplicate_filenames_inside_doctrine(tmp_path):
    write(tmp_path, {
        "doctrine/x/dup.md": "# A\n",
        "doctrine/y/dup.md": "# B\n",
    })
    problems, declined, _ = check(tmp_path)
    only(problems, declined, "DUP FILENAME")


def test_dead_citation_in_unreleased_changelog_section(tmp_path):
    """Proves the changelog exclusion keys on the SECTION, not the filename."""
    write(tmp_path, {
        "proj/target.md": "# T\n\n## Standards\n",
        "proj/CHANGELOG.md":
            "# Changelog\n\n## [Unreleased]\n\n"
            "Broke `target.md § No Such Heading`.\n\n"
            "## [1.0.0] - 2026-01-01\n\n"
            "Also `target.md § No Such Heading`.\n",
    })
    problems, declined, stats = check(tmp_path)
    only(problems, declined, "BAD CITATION")
    assert stats["frozen_lines"] == 3


# --------------------------------------------------------------------------
# Declined block — counted, printed, never fatal
# --------------------------------------------------------------------------

def test_anchor_into_non_markdown_target_is_declined(tmp_path):
    write(tmp_path, {
        "doctrine/a.md": "See [line](./foo.py#L10).\n",
        "doctrine/foo.py": "x = 1\n",
    })
    problems, declined, stats = check(tmp_path)
    assert problems == [], problems
    assert classify(declined, DECLINED_CLASSES) == ["NO ANCHOR RULE"]
    assert stats["anchors_unverifiable"] == 1


def test_ambiguous_basename_citation_is_declined(tmp_path):
    write(tmp_path, {
        "scan/a.md": "Per `dup.md § Something`.\n",
        "x/dup.md": "# D\n",
        "y/dup.md": "# D\n",
    })
    problems, declined, stats = check(tmp_path)
    assert problems == [], problems
    assert classify(declined, DECLINED_CLASSES) == ["AMBIGUOUS CITE"]
    assert stats["ambiguous"] == 1


def test_unbounded_citation_is_counted_not_reported(tmp_path):
    write(tmp_path, {
        "doctrine/target.md": "# T\n\n## Standards\n",
        "doctrine/a.md": "See `target.md` § Standards for the rule.\n",
    })
    problems, declined, stats = check(tmp_path)
    assert problems == [], problems
    assert declined == [], declined
    assert stats["unbounded"] == 1
    assert stats["exact"] == 0


def test_live_anchor_outside_roots_is_verified_and_counted(tmp_path):
    write(tmp_path, {
        "scan/a.md": "See [x](../outside/other.md#live).\n",
        "outside/other.md": "# Other\n\n## Live\n",
    })
    problems, declined, stats = check(tmp_path, roots=["scan"])
    assert problems == [], problems
    assert stats["anchors"] == 1
    assert stats["anchors_offroot"] == 1


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------

def test_check3_ignores_mirrored_trees_outside_doctrine(tmp_path):
    write(tmp_path, {
        "doctrine/a.md": "# A\n",
        "doctrine/b.md": "# B\n",
        "m1/same.md": "# S\n",
        "m2/same.md": "# S\n",
    })
    problems, declined, stats = check(tmp_path)
    assert problems == [], problems
    assert stats["files"] == 4
    assert stats["check3_files"] == 2


def test_check3_counts_zero_for_a_root_outside_doctrine(tmp_path):
    write(tmp_path, {"other/a.md": "# A\n", "other/b.md": "# B\n"})
    problems, _, stats = check(tmp_path, roots=["other"])
    assert problems == [], problems
    assert stats["files"] == 2
    assert stats["check3_files"] == 0


def test_generated_residue_is_not_a_document(tmp_path):
    write(tmp_path, {
        "doctrine/a.md": "# A\n",
        "doctrine/.pytest_cache/README.md": "# residue\n",
        "doctrine/__pycache__/stale.md": "# residue\n",
    })
    _, _, stats = check(tmp_path)
    assert stats["files"] == 1
    assert stats["check3_files"] == 1
