"""Unit tests for ``docex docs scaffold`` (mod 160)."""

from __future__ import annotations

from docex.docs.check import missing_standard_files, unreachable_docs
from docex.docs.scaffold import scaffold_design
from docex.docs.standard_set import resolve


def test_scaffold_creates_every_mandatory_entry(tmp_path):
    scaffold_design(tmp_path, ["api"])
    plans = tmp_path / "plans"
    for entry in resolve(["api"]):
        target = plans / entry.rel_path
        if entry.optional:
            continue
        if entry.kind == "dir":
            assert target.is_dir(), entry.rel_path
        else:
            assert target.is_file(), entry.rel_path


def test_scaffold_never_creates_optional_files(tmp_path):
    scaffold_design(tmp_path, ["api"])
    plans = tmp_path / "plans"
    assert not (plans / "design/doctrine_ext.md").exists()
    assert not (plans / "design/quality_scenarios.md").exists()


def test_scaffold_gitkeeps_empty_dirs(tmp_path):
    scaffold_design(tmp_path, ["api"])
    plans = tmp_path / "plans"
    for rel in ("design/adrs", "references", "design/api/module",
                "design/api/specifics"):
        gitkeep = plans / rel / ".gitkeep"
        assert gitkeep.is_file(), rel


def test_scaffold_is_idempotent_and_no_clobber(tmp_path):
    scaffold_design(tmp_path, ["api"])
    lexicon = tmp_path / "plans" / "design" / "lexicon.md"
    sentinel = "# SENTINEL — do not clobber\n"
    lexicon.write_text(sentinel)

    created = scaffold_design(tmp_path, ["api"])
    assert created == []
    assert lexicon.read_text() == sentinel


def test_freshly_scaffolded_tree_passes_both_checks(tmp_path):
    scaffold_design(tmp_path, ["api"])
    assert missing_standard_files(tmp_path, ["api"]) == []
    assert unreachable_docs(tmp_path, ["api"]) == []
