"""End-to-end CLI tests for the cohere executor `linkcheck.py`.

WHY these live in `docex/tests/unit/` even though `linkcheck.py` is not docex
code: this suite is the harness the release gates habitually run, and an untested
check is exactly the defect this module exists to prevent.

WHY there is a second suite, and what divides them: `linkcheck.py`'s unit tests
live beside the executor at `skills/cohere/executor/tests/`, run under bare
`python3` with no virtualenv, and are gated from the `cohere` skill body. They
test `run_checks` — the matching ladder, slugify, the declined classes — with an
injected `doctrine_root`. **These tests own the other seam:** `main()` itself, via
argv and exit codes, against the module's real defaults. Neither file's cases
belong in the other, and the split is by seam rather than by convenience.

Gating gap worth knowing: `RELEASING.md`'s table fires `pytest` on a *docex*
change and `cohere` on a *doctrine-prose* change. A change to `linkcheck.py`
alone is neither — it is a `skills/` change — so run both suites by hand when
editing the executor.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_LINKCHECK_PATH = (
    Path(__file__).resolve().parents[3] / "skills" / "cohere" / "executor" / "linkcheck.py"
)


@pytest.fixture(scope="module")
def linkcheck():
    """Load the executor by path — it lives outside the `docex` package."""
    spec = importlib.util.spec_from_file_location("linkcheck_under_test", _LINKCHECK_PATH)
    mod = importlib.util.module_from_spec(spec)
    # WHY: exec_module would otherwise drop a __pycache__ dir into the skills
    # tree. `skills/cohere/executor/.gitignore` now covers it, but the guard
    # stays: residue on disk still inflates the file count `verify_examples.py`
    # reports, because that executor has no skip-dirs guard.
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def _corpus(tmp_path, doctrine_files, skills_files):
    doctrine = tmp_path / "doctrine"
    skills = tmp_path / "skills"
    for rel, text in doctrine_files.items():
        p = doctrine / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for rel, text in skills_files.items():
        p = skills / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    doctrine.mkdir(parents=True, exist_ok=True)
    skills.mkdir(parents=True, exist_ok=True)
    return doctrine, skills


def _run(linkcheck, monkeypatch, roots):
    monkeypatch.setattr("sys.argv", ["linkcheck.py", *[str(r) for r in roots]])
    return linkcheck.main()


def test_clean_two_tree_corpus_exits_zero(linkcheck, monkeypatch, tmp_path, capsys):
    doctrine, skills = _corpus(
        tmp_path,
        {"alpha.md": "# Alpha\n\n## Some Section\n\nSee [beta](./beta.md).\n",
         "beta.md": "# Beta\n"},
        {"one/SKILL.md": "# One\n\n[alpha](../../doctrine/alpha.md#some-section)\n"},
    )
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 0
    assert "No broken links" in capsys.readouterr().out


def test_skill_link_to_missing_doctrine_file_is_reported(
    linkcheck, monkeypatch, tmp_path, capsys
):
    """Not caught before skills/ became a scanned root."""
    doctrine, skills = _corpus(
        tmp_path,
        {"alpha.md": "# Alpha\n"},
        {"one/SKILL.md": "# One\n\n[gone](../../doctrine/nope.md)\n"},
    )
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 1
    out = capsys.readouterr().out
    assert "BROKEN FILE" in out
    assert "nope.md" in out


def test_skill_link_to_missing_anchor_is_reported(
    linkcheck, monkeypatch, tmp_path, capsys
):
    """The regression a doctrine section rename could silently cause.

    Previously failed open twice over: skills/ was unscanned, and the anchor
    table was built only from files under the single scanned root.
    """
    doctrine, skills = _corpus(
        tmp_path,
        {"alpha.md": "# Alpha\n\n## Real Section\n"},
        {"one/SKILL.md": "# One\n\n[a](../../doctrine/alpha.md#renamed-away)\n"},
    )
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 1
    out = capsys.readouterr().out
    assert "BAD ANCHOR" in out
    assert "renamed-away" in out


def test_doctrine_to_doctrine_broken_link_still_reported(
    linkcheck, monkeypatch, tmp_path, capsys
):
    doctrine, skills = _corpus(
        tmp_path, {"alpha.md": "# Alpha\n\n[b](./missing.md)\n"}, {}
    )
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 1
    assert "BROKEN FILE" in capsys.readouterr().out


def test_two_skill_md_files_are_not_duplicate_findings(
    linkcheck, monkeypatch, tmp_path, capsys
):
    """The Agent Skills Standard names every skill body SKILL.md.

    Check 3 is a doctrine-corpus rule; applying it to skills/ would emit one
    false positive per skill and make the check useless.
    """
    doctrine, skills = _corpus(
        tmp_path,
        {"alpha.md": "# Alpha\n"},
        {"one/SKILL.md": "# One\n", "two/SKILL.md": "# Two\n"},
    )
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 0
    assert "DUP FILENAME" not in capsys.readouterr().out


def test_two_same_named_doctrine_files_still_reported(
    linkcheck, monkeypatch, tmp_path, capsys
):
    """Check 3's scope is the doctrine corpus, so the fake tree must BE it.

    WHY the monkeypatch: check 3 used to be scoped by root *basename* (any root
    not named `skills`), which a tmp tree called `doctrine` satisfied by
    coincidence. It is now an allowlist keyed on the real `$jb/doctrine`, so that
    widening the scan can never make the check fire on a deliberately-mirrored
    tree. Pointing DOCTRINE_ROOT at the fixture is what makes this test assert the
    rule rather than the coincidence.
    """
    doctrine, skills = _corpus(
        tmp_path,
        {"charts/configurable.md": "# A\n", "infra/configurable.md": "# B\n"},
        {"one/SKILL.md": "# One\n"},
    )
    monkeypatch.setattr(linkcheck, "DOCTRINE_ROOT", str(doctrine))
    assert _run(linkcheck, monkeypatch, [doctrine, skills]) == 1
    out = capsys.readouterr().out
    assert "DUP FILENAME" in out
    assert "configurable.md" in out


def test_slugify_preserves_double_hyphen_on_slash_heading(linkcheck):
    """`/` is stripped, leaving two spaces -> two hyphens. Collapsing runs was
    the original false-positive bug; it must stay uncollapsed."""
    assert linkcheck.slugify("Driven Port / Adapter Patterns") == "driven-port--adapter-patterns"
