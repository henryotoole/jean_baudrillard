"""Tests for the cohere executor `verify_examples.py`.

WHY these live in `docex/tests/unit/` even though the harness is not docex
code: this suite is the only harness the release gates actually run. Advance
005 found the canonical `cicl.md` example broken twice, and neither finder was
a shipped check — an unshipped check is what these tests exist to prevent.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_HARNESS_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills" / "cohere" / "executor" / "verify_examples.py"
)

# A complete, valid v3 document. Every fixture below is a mutation of this.
_GOOD = """cicl_version: "3"
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
        health_check_path: /health
        uses: [appdb]
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
"""


@pytest.fixture(scope="module")
def harness():
    """Load the executor by path — it lives outside the `docex` package."""
    spec = importlib.util.spec_from_file_location("verify_examples_under_test", _HARNESS_PATH)
    mod = importlib.util.module_from_spec(spec)
    # WHY: exec_module would otherwise drop a __pycache__ dir into the skills
    # tree, which has no .gitignore covering it.
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def _corpus(tmp_path, fences):
    """Write one markdown file per fence into a synthetic doctrine tree."""
    doctrine = tmp_path / "doctrine"
    doctrine.mkdir(parents=True, exist_ok=True)
    for i, body in enumerate(fences):
        (doctrine / f"doc{i}.md").write_text(f"# Doc {i}\n\n```yml\n{body}```\n")
    return doctrine


def _run(harness, monkeypatch, root):
    monkeypatch.setattr("sys.argv", ["verify_examples.py", str(root)])
    return harness.main()


def test_clean_fence_passes(harness, monkeypatch, tmp_path, capsys):
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [_GOOD]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "[PASS] COMPLETE" in out
    assert "validated OK    : 1" in out


def test_tab_indented_fence_is_reported(harness, monkeypatch, tmp_path, capsys):
    """YAML forbids tabs for indentation — such a fence is not copy-pasteable."""
    tabbed = _GOOD.replace("  api:", "\tapi:")
    _run(harness, monkeypatch, _corpus(tmp_path, [tabbed]))
    out = capsys.readouterr().out
    assert "fences tabbed   : 1" in out
    assert "[de-tabbed]" in out


def test_undeclared_uses_target_is_reported(harness, monkeypatch, tmp_path, capsys):
    """The A4 class: `uses:` naming a service the document never declares."""
    bad = _GOOD.replace("uses: [appdb]", "uses: [nosuchdb]")
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [bad]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL]" in out
    assert "rule_25_unresolved_uses" in out


def test_missing_required_top_level_field_is_reported(
    harness, monkeypatch, tmp_path, capsys
):
    """The A5 class: a complete document missing a field `CICLDocument`
    requires fails at pydantic parse, before validation ever runs."""
    bad = _GOOD.replace('observability_backend_url: "https://obs.example.com"\n', "")
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [bad]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "observability_backend_url" in out
    assert "ValidationError" in out


def test_non_cicl_yaml_is_parse_checked_but_not_validated(
    harness, monkeypatch, tmp_path, capsys
):
    non_cicl = "services:\n  otelcol:\n    image: otel/opentelemetry-collector\n"
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [non_cicl]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "infra.yml-shaped fences : 0" in out
    assert "fences parsed   : 1 / 1" in out
    assert "validated OK    : 0" in out


def test_unparseable_non_cicl_yaml_is_reported(harness, monkeypatch, tmp_path, capsys):
    rc = _run(harness, monkeypatch, _corpus(tmp_path, ["key: [unclosed\n"]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "failed to parse : 1" in out


def test_multi_document_stream_parses(harness, monkeypatch, tmp_path, capsys):
    """A fence may legitimately show frontmatter, which is a two-document
    stream that `yaml.safe_load` alone rejects."""
    rc = _run(harness, monkeypatch, _corpus(tmp_path, ["---\nstratum: resident\n---\n"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "failed to parse : 0" in out


def test_exit_code_is_nonzero_exactly_when_findings_exist(
    harness, monkeypatch, tmp_path, capsys
):
    assert _run(harness, monkeypatch, _corpus(tmp_path, [_GOOD, _GOOD])) == 0
    capsys.readouterr()
    bad = _GOOD.replace("uses: [appdb]", "uses: [nosuchdb]")
    assert _run(harness, monkeypatch, _corpus(tmp_path / "b", [_GOOD, bad])) == 1


# --- EXCERPT classification -------------------------------------------------
#
# An EXCERPT quotes part of a larger YAML document and borrows an `&anchor`
# defined in a different fence. Those fences are correct documentation: showing
# the real emitted shape is their purpose, so forcing them to parse standalone
# would mean damaging the docs to satisfy the tool. The classification must be
# narrow enough that it cannot absorb an unrelated failure.

_ANCHOR_HOST = """x-logging: &default-logging
  driver: json-file
"""

_EXCERPT = """container_name: ${global_service_name}
logging: *default-logging
restart: unless-stopped
"""


def test_excerpt_borrowing_corpus_anchor_is_classified(
    harness, monkeypatch, tmp_path, capsys
):
    """The real case: `*default-logging` defined in another file's fence."""
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [_ANCHOR_HOST, _EXCERPT]))
    out = capsys.readouterr().out
    assert rc == 0, "an excerpt is declared-not-a-document and must not gate"
    assert "fences EXCERPT  : 1" in out
    assert "borrows *default-logging" in out
    assert "failed to parse : 0" in out


def test_excerpt_is_never_counted_as_parsed(harness, monkeypatch, tmp_path, capsys):
    """It must not print as a pass — the count is what catches a regression."""
    _run(harness, monkeypatch, _corpus(tmp_path, [_ANCHOR_HOST, _EXCERPT]))
    out = capsys.readouterr().out
    # Two fences scanned; only the anchor host is a real standalone document.
    assert "fences scanned  : 2" in out
    assert "fences parsed   : 1 / 2" in out


def test_undefined_alias_with_no_corpus_anchor_still_fails(
    harness, monkeypatch, tmp_path, capsys
):
    """No `&anchor` anywhere in the corpus — this is a broken fence, not an
    excerpt, and must still gate red."""
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [_EXCERPT]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "fences EXCERPT  : 0" in out
    assert "failed to parse : 1" in out


def test_excerpt_condition_does_not_absorb_unrelated_error(
    harness, monkeypatch, tmp_path, capsys
):
    """The narrowness guard: a fence that borrows a real corpus anchor AND has
    a genuine syntax error is NOT an excerpt. A classification that can absorb
    an unrelated failure is a gate with a hole in it."""
    broken = _EXCERPT + "unclosed: [a, b\n"
    rc = _run(harness, monkeypatch, _corpus(tmp_path, [_ANCHOR_HOST, broken]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "fences EXCERPT  : 0" in out
    assert "failed to parse : 1" in out
