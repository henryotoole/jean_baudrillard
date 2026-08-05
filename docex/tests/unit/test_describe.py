"""Unit tests for the ``describe`` renderers (Mod 104).

``render_dag`` / ``render_llm`` are pure functions over a ``CompiledEnv``, so
the unit layer is their home; before Mod 104 the only coverage was
``tests/integration/test_compile.py::test_describe_dag_and_llm``.

Mod 104 made the renderers show BOTH relations — ``depends_on`` (readiness) and
``consumes`` (interface) — over dotted reference-form node ids, from a single
shared derivation. These tests pin each of those properties separately.
"""

from __future__ import annotations

import json

import yaml

from docex.cicl.compile import compile_env
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.describe.dag import collect_edges, node_id, render_dag
from docex.describe.llm import render_llm


def _compiled(src: str, env: str = "prod"):
    return compile_env(
        CICLDocument.model_validate(yaml.safe_load(src)),
        load_transfer_tables(project_root=None),
        env=env,
        project_name="sample",
        project_version="0.1.0",
    )


def _doc(web_consumes: str = "[api.worker]") -> str:
    """The test document. ``web ↔ worker`` is the legal interface cycle.

    `web_consumes` is substituted verbatim so a variant can carry a malformed
    or unresolvable target without a second copy of the document.
    """
    return f"""
cicl_version: "2"
foundation: fixed
apex_domain: example.com
container_registry: registry.example.com
observability_backend_url: "https://obs.example.com"
domain_default_service: api.web
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        port: 8080
        networks: [web, internal]
        depends_on: [appdb]
        consumes: {web_consumes}
        resources: {{cpu: 1.0, memory: 2GB, disk: 20GB}}
      worker:
        role: worker
        command: ["python", "-m", "worker"]
        networks: [internal]
        depends_on: [appdb]
        consumes: [api.web]
        replicas: 4
        resources: {{cpu: 0.5, memory: 1GB, disk: 20GB}}
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    port: 5432
    networks: [internal]
    schema_owned_by: api
"""


def _arrow_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if " -> " in ln or " ..> " in ln]


# ---------------------------------------------------------------------------
# 1-3. `consumes` on CompiledService
# ---------------------------------------------------------------------------


def test_consumes_compiles_to_compiled_identities():
    """Not dotted — these are keys into ``CompiledEnv.services``.

    The whole point of the compiled form is that an edge of either relation
    resolves with one dict lookup, so the lookup is asserted too.
    """
    c = _compiled(_doc())
    assert c.services["api-web"].consumes == ["api-worker"]
    assert c.services["api-worker"].consumes == ["api-web"]
    for key in ("api-worker", "api-web"):
        assert key in c.services


def test_backing_service_compiles_to_empty_consumes():
    """A backing service has no ``consumes:`` (rule 14), so the field is []."""
    c = _compiled(_doc())
    assert c.services["appdb"].consumes == []


def test_malformed_consumes_entries_are_dropped():
    """A rule-25-rejected entry must not surface as a phantom node.

    ``consumes_refs()`` drops what does not parse, and ``compile_env`` does not
    validate, so this is the property that keeps a bare name (``api``) or a
    backing target (``appdb``) from reaching the graph view.
    """
    c = _compiled(_doc(web_consumes='["appdb", "api"]'))
    assert c.services["api-web"].consumes == []


# ---------------------------------------------------------------------------
# 4-7. render_dag
# ---------------------------------------------------------------------------


def test_dag_renders_both_edge_kinds_distinguishably():
    """Both headings, and each relation under its own glyph — never the other's."""
    out = render_dag(_compiled(_doc()))
    assert "depends_on edges (readiness) — solid:" in out
    assert "consumes edges (interface) — dashed:" in out
    assert "  api.web -> appdb" in out
    assert "  api.web ..> api.worker" in out
    # The glyphs do not cross over.
    assert "  api.web ..> appdb" not in out
    assert "  api.web -> api.worker" not in out


def test_dag_node_ids_are_dotted_and_emitted_name_still_shown():
    """The reference form is the node id; the emitted name sits beside it."""
    out = render_dag(_compiled(_doc()))
    assert "core:api.web" in out
    assert "core:api-web" not in out
    assert "sample-prod-api-web" in out


def test_dag_consumes_cycle_renders_each_edge_once():
    """``web ↔ worker`` is legal; the flat pass emits two lines, not a walk.

    ``render_dag`` is called directly, so a recursive implementation fails here
    by blowing the stack rather than by a subtle diff.
    """
    out = render_dag(_compiled(_doc()))
    lines = out.splitlines()
    assert lines.count("  api.web ..> api.worker") == 1
    assert lines.count("  api.worker ..> api.web") == 1


def test_dag_replicas_yield_one_node():
    """A replica is an emission detail, not a topology node (Mod 100).

    ``replicas`` is asserted on the compiled service too, so this proves the
    count is *carried but not multiplied* rather than merely absent.
    """
    c = _compiled(_doc())
    lines = render_dag(c).splitlines()
    assert len([ln for ln in lines if "core:api.worker" in ln]) == 1
    assert len([ln for ln in lines if "core:" in ln]) == 2
    assert c.services["api-worker"].replicas == 4


# ---------------------------------------------------------------------------
# 8-9. render_llm
# ---------------------------------------------------------------------------


def test_llm_edges_carry_both_kinds():
    doc = json.loads(render_llm(_compiled(_doc())))
    edges = doc["edges"]
    assert {e["kind"] for e in edges} == {"depends_on", "consumes"}
    consumes = [e for e in edges if e["kind"] == "consumes"]
    assert {(e["from"], e["to"]) for e in consumes} == {
        ("api.web", "api.worker"),
        ("api.worker", "api.web"),
    }


def test_llm_nodes_carry_both_axes_and_consumes():
    doc = json.loads(render_llm(_compiled(_doc())))
    nodes = {r["short"]: r for r in doc["tiers"]["environment"]}
    web = nodes["api.web"]
    assert web["short"] == "api.web"
    assert web["core_service"] == "api"
    assert web["service"] == "web"
    assert web["consumes"] == ["api.worker"]
    db = nodes["appdb"]
    assert db["core_service"] is None
    assert db["service"] is None


# ---------------------------------------------------------------------------
# 10-11. one derivation; graceful degradation
# ---------------------------------------------------------------------------


def test_one_derivation_two_renderings():
    """The regression guard against ``llm.py``'s duplicated edge loop returning."""
    c = _compiled(_doc())
    edges = collect_edges(c)
    llm_edges = {
        (e["from"], e["to"], e["kind"])
        for e in json.loads(render_llm(c))["edges"]
    }
    assert set(edges) == llm_edges

    out = render_dag(c)
    arrows = _arrow_lines(out)
    assert len(arrows) == len(edges)
    for src, dst, kind in edges:
        arrow = "->" if kind == "depends_on" else "..>"
        assert f"  {src} {arrow} {dst}" in arrows


def test_unresolvable_consumes_target_degrades_to_raw_key():
    """``describe`` is illustrative: it prints an odd token rather than raising.

    ``run_describe`` compiles WITHOUT ``validate_document``, so a well-formed
    but unresolvable target (``ghost.web``) reaches the renderer.
    """
    c = _compiled(_doc(web_consumes='["ghost.web"]'))
    assert c.services["api-web"].consumes == ["ghost-web"]
    out = render_dag(c)
    assert "  api.web ..> ghost-web" in out
    assert node_id(c.services["api-web"]) == "api.web"
