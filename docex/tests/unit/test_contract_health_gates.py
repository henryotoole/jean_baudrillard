"""Mod 126 — `check.py`'s contract and health-path gates against the doctrine's
actual model (cicl.md § Surfaces, contracts.md, healthchecks.md).

Three things land here:

1. **The provider set is `surfaces:` and nothing else.** Not the `uses` graph,
   not `web`-network membership. A core service that declares no surface is not
   a provider and owes no contract — which is exactly a frontend serving a
   browser (`infrastructure.md § Contracts`).
2. **One contract per surface**, at
   `<codebase>.<service>.<surface>.<format>.<ext>`, in the format that surface's
   `api_styles` resolve to. A file in `infra/contracts/` that no declared surface
   expects is an orphan and fails the gate.
3. **One content assertion survives**: a `web`-network core service's `openapi`
   contract declares a `GET` on its *declared* `health_check_path`.

Inline-`infra.yml` projects under `tmp_path`: the shapes under test are one-off,
and a fixture directory per shape would not pay for itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from docex.context import load_project_context
from docex.pipeline.check import (
    CheckReport,
    _gate_contract_health_path,
    _gate_contracts,
    _parse_contract_filename,
)


# `test_internal_openapi_provider_requires_self_health` (mod 101) is DELETED.
# Its premise — an internal-only openapi provider "must be probeable one hop
# away" — *is* the fan-out, and `healthchecks.md § What this doctrine does not
# do` now says a non-`web` core service "needs no HTTP surface of any kind".
# `test_non_web_openapi_provider_needs_no_health_path` below is its positive
# inverse.


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


_HEAD = (
    'cicl_version: "3"\n'
    "foundation: fixed\n"
    'apex_domain: "example.com"\n'
    'container_registry: "registry.example.com"\n'
    'observability_backend_url: "https://hyperdx.luxrnd.tech"\n'
    "domain_default_service: api.web\n"
    "codebases:\n"
)


def _proc(
    name: str,
    role: str = "web",
    *,
    networks: list[str],
    port: int | None = None,
    hcp: bool = False,
    uses: list[str] | None = None,
    surfaces: dict[str, list[str]] | None = None,
    extra: list[str] | None = None,
) -> str:
    lines = [
        f"      {name}:",
        f"        role: {role}",
        '        command: ["python", "/service/dist/root.py"]',
        f"        networks: [{', '.join(networks)}]",
    ]
    if port is not None:
        lines.append(f"        port: {port}")
    if hcp:
        lines.append("        health_check_path: /health")
    if uses is not None:
        lines.append(f"        uses: {json.dumps(uses)}")
    if surfaces is not None:
        lines.append("        surfaces:")
        for surface_name, styles in surfaces.items():
            lines.append(f"          {surface_name}:")
            lines.append(f"            api_styles: {json.dumps(styles)}")
    lines.extend(extra or [])
    lines += [
        "        resources:",
        "          cpu: 0.5",
        "          memory: 512MB",
        "          disk: 1GB",
    ]
    return "\n".join(lines) + "\n"


def _codebase(name: str, *svcs: str) -> str:
    return f"  {name}:\n    core_services:\n" + "".join(svcs)


def _project(
    tmp_path: Path,
    codebases: str,
    contracts: dict[str, str] | None = None,
):
    """Build a loadable project on disk. Returns ``(ctx, root)``."""
    root = tmp_path / "hcproj"
    (root / "infra" / "contracts").mkdir(parents=True)
    (root / "project.yml").write_text(
        'name: hc\nversion: "0.1.0"\ndocex_version: "1.0.3"\n'
    )
    (root / "infra" / "infra.yml").write_text(_HEAD + codebases)
    for filename, body in (contracts or {}).items():
        (root / "infra" / "contracts" / filename).write_text(body)
    return load_project_context(root), root


def _openapi(*paths: str) -> str:
    """A minimal well-formed OpenAPI document declaring ``GET`` on each path."""
    body = 'openapi: "3.0.3"\ninfo: {title: t, version: "0.1.0"}\npaths:\n'
    for p in paths:
        body += f'  {p}: {{get: {{responses: {{"200": {{description: ok}}}}}}}}\n'
    return body


# An AsyncAPI contract has no `paths:`, which is why the health-path gate only
# ever looks at `openapi` contracts.
_ASYNCAPI = (
    'asyncapi: "2.6.0"\n'
    'info: {title: t, version: "0.1.0"}\n'
    "channels:\n"
    "  jobs:\n"
    "    subscribe:\n"
    "      message:\n"
    "        payload: {type: object}\n"
)


def _contracts_result(ctx, root) -> tuple:
    report = CheckReport()
    contracts, providers = _gate_contracts(root, ctx, report)
    res = next(r for r in report.results if r.name == "contracts_exist")
    return res, contracts, providers


def _health_path_result(ctx, root):
    """Run both gates in sequence — the health-path gate reads the contract
    gate's output, exactly as ``run_check`` wires them."""
    report = CheckReport()
    contracts, _providers = _gate_contracts(root, ctx, report)
    _gate_contract_health_path(ctx, contracts, report)
    return next(r for r in report.results if r.name == "contract_health_path")


def _web_and_worker() -> str:
    """`api.web` (web network, rest surface) uses `api.worker` (internal only,
    events surface, no port and no `health_check_path` — rules 32 and 33 make
    both of those shapes unrepresentable on this service)."""
    return _codebase(
        "api",
        _proc(
            "web",
            "web",
            networks=["web", "internal"],
            port=8080,
            hcp=True,
            uses=["api.worker"],
            surfaces={"rest": ["rest"]},
        ),
        _proc(
            "worker",
            "worker",
            networks=["internal"],
            surfaces={"events": ["events"]},
        ),
    )


# ---------------------------------------------------------------------------
# Provider set + contract naming.
# ---------------------------------------------------------------------------


def test_provider_set_is_surfaces_only(tmp_path):
    """A core service is a provider iff it declares `surfaces:`, and the format
    follows the surface's `api_styles` — not its role, not the `uses` graph."""
    ctx, root = _project(
        tmp_path,
        _web_and_worker(),
        {"api.web.rest.openapi.yml": _openapi("/health")},
    )
    res, _contracts, providers = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.worker.events.asyncapi.yml" in res.detail
    assert sorted(providers) == ["api.web", "api.worker"]

    # Supplying it satisfies the gate — and it is looked for under `.asyncapi`,
    # which came from `api_styles: [events]`, not from `role: worker`.
    (root / "infra" / "contracts" / "api.worker.events.asyncapi.yml").write_text(
        _ASYNCAPI
    )
    ctx = load_project_context(root)
    res, contracts, _providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(e.path.name for e in contracts) == [
        "api.web.rest.openapi.yml",
        "api.worker.events.asyncapi.yml",
    ]


def test_two_web_services_each_get_a_contract(tmp_path):
    """The contract path is service-keyed unconditionally: a public `web` and an
    internal `admin` on one codebase are two genuine boundaries."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
        _proc(
            "admin", "web", networks=["web", "internal"], port=8081, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    both = {
        "api.web.rest.openapi.yml": _openapi("/health"),
        "api.admin.rest.openapi.yml": _openapi("/health"),
    }
    ctx, root = _project(tmp_path, src, both)
    res, _contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(providers) == ["api.admin", "api.web"]

    for dropped, kept in (
        ("api.admin.rest.openapi.yml", "api.web.rest.openapi.yml"),
        ("api.web.rest.openapi.yml", "api.admin.rest.openapi.yml"),
    ):
        ctx, root = _project(tmp_path / dropped, src, {kept: both[kept]})
        res, _c, _p = _contracts_result(ctx, root)
        assert not res.passed, res.detail
        assert dropped in res.detail
        assert kept not in res.detail


def test_two_surfaces_two_contracts(tmp_path):
    """One core service, two surfaces of different formats, two contracts."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"], "events": ["events"]},
        ),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.rest.openapi.yml": _openapi("/health")}
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.web.events.asyncapi.yml" in res.detail

    (root / "infra" / "contracts" / "api.web.events.asyncapi.yml").write_text(
        _ASYNCAPI
    )
    ctx = load_project_context(root)
    res, contracts, _p = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(e.path.name for e in contracts) == [
        "api.web.events.asyncapi.yml",
        "api.web.rest.openapi.yml",
    ]


def test_two_surfaces_same_format_distinct_filenames(tmp_path):
    """Two surfaces of the SAME format on one core service. This is the case a
    three-segment `<cb>.<svc>.<fmt>` scheme cannot express at all, and the whole
    reason the surface segment exists."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest_public": ["rest"], "rest_admin": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.rest_public.openapi.yml": _openapi("/health")}
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.web.rest_admin.openapi.yml" in res.detail

    (root / "infra" / "contracts" / "api.web.rest_admin.openapi.yml").write_text(
        _openapi("/admin")
    )
    ctx = load_project_context(root)
    res, contracts, _p = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(e.path.name for e in contracts) == [
        "api.web.rest_admin.openapi.yml",
        "api.web.rest_public.openapi.yml",
    ]
    # And the parse round-trips each to its OWN surface segment.
    assert _parse_contract_filename("api.web.rest_admin.openapi.yml") == (
        "api", "web", "rest_admin", "openapi",
    )
    assert _parse_contract_filename("api.web.rest_public.openapi.yml") == (
        "api", "web", "rest_public", "openapi",
    )


def test_web_network_service_without_surfaces_needs_no_contract(tmp_path):
    """The deleted second arm's exact inverse: a `web`-network core service that
    declares no surface is a frontend serving a browser, and owes no contract
    (`infrastructure.md § Contracts`)."""
    src = _codebase(
        "frontend",
        _proc("web", "web", networks=["web"], port=3000, hcp=True),
    )
    ctx, root = _project(tmp_path, src, {})
    res, contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert providers == []
    assert contracts == []
    assert "no core service declares a surface" in res.detail


# ---------------------------------------------------------------------------
# Orphans.
# ---------------------------------------------------------------------------


def test_orphan_contract_for_undeclared_surface_fails(tmp_path):
    """A canonically-named contract for a surface nobody declares is drift, and
    worse than no contract because it reads as documentation."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest.openapi.yml": _openapi("/health"),
            "api.web.graphql_admin.openapi.yml": _openapi("/admin"),
        },
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.web.graphql_admin.openapi.yml" in res.detail
    assert "rename it to the surface it describes, or delete it" in res.detail


def test_stale_three_segment_contract_fails(tmp_path):
    """The 2.0.0 upgrade case: the renamed file exists, so an existence-only
    gate is blind to the leftover beside it."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest.openapi.yml": _openapi("/health"),
            "api.web.openapi.yml": _openapi("/health"),
        },
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.web.openapi.yml" in res.detail
    assert "<codebase>.<service>.<surface>.<format>.<ext>" in res.detail


def test_wrong_extension_is_an_orphan(tmp_path):
    """`contracts.md § Standards` fixes ONE extension per format, so a `.yaml`
    neither satisfies the `.yml` expectation nor passes as an unrelated file."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.rest.openapi.yaml": _openapi("/health")}
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    # Both clauses fire.
    assert "missing contract(s)" in res.detail
    assert "api.web.rest.openapi.yml" in res.detail
    assert "api.web.rest.openapi.yaml" in res.detail
    assert "rename it" in res.detail


def test_non_contract_files_are_ignored(tmp_path):
    """Dotfiles and non-contract extensions are not orphans — the orphan arm
    must not invent false positives out of a README."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest.openapi.yml": _openapi("/health"),
            "README.md": "# contracts\n",
            ".gitkeep": "",
        },
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert res.passed, res.detail


# ---------------------------------------------------------------------------
# Skips — the surfaces compile owns, not this gate.
# ---------------------------------------------------------------------------


def test_mixed_format_surface_is_skipped(tmp_path):
    """`rule_29_mixed_contract_formats` owns this at compile time; a second
    complaint here would name a filename the author could never have produced.
    `test_check_reaches_compile_when_a_surface_is_skipped` pins the ordering
    that makes the skip honest rather than lax."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"mixed": ["rest", "rpc"]},
        ),
    )
    ctx, root = _project(tmp_path, src, {})
    res, contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert contracts == []
    # Still a provider — a skipped surface must not make one vanish.
    assert providers == ["api.web"]


def test_unimplemented_format_surface_is_skipped(tmp_path):
    """`rule_contract_format_not_implemented` owns this one."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"gql": ["graphql"]},
        ),
    )
    ctx, root = _project(tmp_path, src, {})
    res, contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert contracts == []
    assert "graphql" not in res.detail
    assert providers == ["api.web"]


# ---------------------------------------------------------------------------
# Filename parsing.
# ---------------------------------------------------------------------------


def test_contract_filename_parsed_four_segments():
    assert _parse_contract_filename("api.web.rest.openapi.yml") == (
        "api", "web", "rest", "openapi",
    )
    assert _parse_contract_filename("api.worker.events.asyncapi.yml") == (
        "api", "worker", "events", "asyncapi",
    )
    # The extension is checked against the RESOLVED FORMAT, not a suffix list.
    assert _parse_contract_filename("api.web.rest.openapi.yaml") is None
    # The retired three-segment shape.
    assert _parse_contract_filename("api.web.openapi.yml") is None
    # Exact count, still — never "the last four of however many".
    assert _parse_contract_filename("a.b.c.d.e.openapi.yml") is None
    assert _parse_contract_filename("api.web.rest.openapi.txt") is None
    assert _parse_contract_filename("api..rest.openapi.yml") is None
    assert _parse_contract_filename("api.web.rest.bogus.yml") is None


# ---------------------------------------------------------------------------
# The health path in the contract.
# ---------------------------------------------------------------------------


def test_health_path_missing_from_openapi_contract_fails(tmp_path):
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.rest.openapi.yml": _openapi("/other")}
    )
    res = _health_path_result(ctx, root)
    assert not res.passed
    assert "api.web.rest.openapi.yml" in res.detail
    assert "/health" in res.detail


def test_health_path_read_from_declared_field(tmp_path):
    """The asserted path is the DECLARED `health_check_path`, never a hardcoded
    `/health` — a project declaring `/healthz` conforms."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080,
            surfaces={"rest": ["rest"]},
            extra=["        health_check_path: /healthz"],
        ),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.rest.openapi.yml": _openapi("/healthz")}
    )
    assert _health_path_result(ctx, root).passed

    ctx, root = _project(
        tmp_path / "wrong", src, {"api.web.rest.openapi.yml": _openapi("/health")}
    )
    res = _health_path_result(ctx, root)
    assert not res.passed
    assert "/healthz" in res.detail


def test_health_path_in_any_one_openapi_surface_suffices(tmp_path):
    """Ruling 2: the core service serves the path once. Requiring it in EVERY
    openapi surface would force `rest_admin` to document a route outside its own
    boundary — a false contract."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest_public": ["rest"], "rest_admin": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest_public.openapi.yml": _openapi("/health", "/things"),
            "api.web.rest_admin.openapi.yml": _openapi("/admin/things"),
        },
    )
    res = _health_path_result(ctx, root)
    assert res.passed, res.detail


def test_non_web_openapi_provider_needs_no_health_path(tmp_path):
    """The positive inverse of mod 101's deleted widening. A non-`web` openapi
    provider is a coherent thing — internal REST, reached by magic ref, `port`
    required by rule 32's positive arm, `health_check_path` FORBIDDEN by rule 33
    — and it must not declare a health route in its contract."""
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            uses=["api.internal"], surfaces={"rest": ["rest"]},
        ),
        _proc(
            "internal", "web", networks=["internal"], port=8081,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest.openapi.yml": _openapi("/health"),
            "api.internal.rest.openapi.yml": _openapi("/things"),
        },
    )
    res = _health_path_result(ctx, root)
    assert res.passed, res.detail


def test_malformed_contract_yaml_is_reported(tmp_path):
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {"api.web.rest.openapi.yml": 'openapi: "3.0.3"\npaths: [unclosed\n'},
    )
    res = _health_path_result(ctx, root)
    assert not res.passed
    assert "malformed YAML" in res.detail
    assert "api.web.rest.openapi.yml" in res.detail
    # ONE problem, not two. "no openapi contract declares 'GET /health'" is a
    # consequence of the parse failure, and reporting a consequence beside its
    # cause reads as two independent defects.
    assert "no openapi contract declares" not in res.detail


def test_health_path_skipped_for_non_web_service_declaring_the_field(tmp_path):
    """The `web`-network guard, made falsifiable.

    Rule 33 forbids `health_check_path` off the `web` network — but rules are
    compile-time and `run_check` runs every gate BEFORE `run_compile`, so this
    document genuinely reaches this gate. The guard is what stops it being
    reported here as a contract defect when it is a *declaration* defect that
    rule 33 owns and names properly.

    Without the guard, `api.internal`'s contract would be searched for
    'GET /health' and fail. With it, the gate is silent and the operator gets
    exactly one message, from compile.
    """
    src = _codebase(
        "api",
        _proc(
            "web", "web", networks=["web", "internal"], port=8080, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
        _proc(
            "internal", "web", networks=["internal"], port=8081, hcp=True,
            surfaces={"rest": ["rest"]},
        ),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.rest.openapi.yml": _openapi("/health"),
            "api.internal.rest.openapi.yml": _openapi("/things"),
        },
    )
    res = _health_path_result(ctx, root)
    assert res.passed, res.detail
    assert "api.internal" not in res.detail
