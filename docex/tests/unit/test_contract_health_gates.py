"""Mod 101 — `check.py`'s contract and health-endpoint gates against the
doctrine's actual model (contracts.md § Contracts, § Health Checks).

Three things land here:

1. The contract *format* follows the provider's `role` (§ Standards), replacing
   `_infer_contract_format` — a heuristic whose asyncapi branch was unreachable
   from the day it was written, which is why no test in this codebase's history
   ever produced an AsyncAPI provider.
2. The provider set is (`consumes` targets) ∪ (`web`-network core service),
   minus schedulers — Mod 098 added `consumes` and nothing read it until now.
3. The health fan-out keys off `consumes`, not `depends_on`. Under rule 24 a web
   core service cannot `depends_on` its worker at all, so the old gate required
   *nothing* of a web → worker edge.

Inline-`infra.yml` projects under `tmp_path` in the style of `_hc_ctx`
(`test_pipeline_check.py`): the shapes under test are one-off, and a fixture
directory per shape would not pay for itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from docex.context import load_project_context
from docex.pipeline.check import (
    CheckReport,
    _gate_contracts,
    _gate_health_endpoints,
    _parse_contract_filename,
)


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


_HEAD = (
    'cicl_version: "2"\n'
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
    consumes: list[str] | None = None,
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
    if consumes is not None:
        lines.append(f"        consumes: {json.dumps(consumes)}")
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


# An AsyncAPI contract has no `paths:` at all — that is precisely the point of
# § Declared by fields: a worker's self-health is declared by its FIELDS, not by
# a contract format that has nowhere to put an HTTP path.
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


def _health_result(ctx, root):
    """Run both gates in sequence — the health gate consumes the contract
    gate's output, exactly as ``run_check`` wires them."""
    report = CheckReport()
    contracts, _providers = _gate_contracts(root, ctx, report)
    _gate_health_endpoints(root, ctx, contracts, report)
    return next(r for r in report.results if r.name == "health_endpoints")


def _web_and_worker(
    *,
    worker_port: int | None = 9090,
    worker_hcp: bool = True,
) -> str:
    """`api.web` (web network) consumes `api.worker` (internal only)."""
    return _codebase(
        "api",
        _proc(
            "web",
            "web",
            networks=["web", "internal"],
            port=8080,
            hcp=True,
            consumes=["api.worker"],
        ),
        _proc(
            "worker",
            "worker",
            networks=["internal"],
            port=worker_port,
            hcp=worker_hcp,
        ),
    )


# ---------------------------------------------------------------------------
# Provider set + contract format.
# ---------------------------------------------------------------------------


def test_worker_provider_gets_asyncapi(tmp_path):
    """A `consumes` target is a provider, and its format follows its ROLE.

    This is the case the old code could not express. `api.worker` is neither on
    `web` nor a `depends_on` target (rule 24 forbids the latter outright), so the
    old provider test made it a non-provider and demanded no contract at all —
    and even had it been a provider, `_infer_contract_format` would have handed
    it `openapi`, because its asyncapi branch was unreachable.
    """
    ctx, root = _project(
        tmp_path,
        _web_and_worker(),
        {"api.web.openapi.yml": _openapi("/health", "/health/api/worker")},
    )
    res, _contracts, providers = _contracts_result(ctx, root)
    assert not res.passed, res.detail
    assert "api.worker.asyncapi.yml" in res.detail
    assert "api.worker" in providers

    # Supplying it satisfies the gate — and it is looked for under `.asyncapi`,
    # not `.openapi`.
    (root / "infra" / "contracts" / "api.worker.asyncapi.yml").write_text(_ASYNCAPI)
    ctx = load_project_context(root)
    res, contracts, _providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(p.name for p in contracts) == [
        "api.web.openapi.yml",
        "api.worker.asyncapi.yml",
    ]


def test_two_web_processes_each_get_a_contract(tmp_path):
    """The contract path is service-keyed unconditionally: a public `web` and an
    internal `admin` on one codebase are two genuine boundaries."""
    src = _codebase(
        "api",
        _proc("web", "web", networks=["web", "internal"], port=8080, hcp=True),
        _proc("admin", "web", networks=["web", "internal"], port=8081, hcp=True),
    )
    both = {
        "api.web.openapi.yml": _openapi("/health"),
        "api.admin.openapi.yml": _openapi("/health"),
    }
    ctx, root = _project(tmp_path, src, both)
    res, _contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert sorted(providers) == ["api.admin", "api.web"]

    for dropped, kept in (
        ("api.admin.openapi.yml", "api.web.openapi.yml"),
        ("api.web.openapi.yml", "api.admin.openapi.yml"),
    ):
        ctx, root = _project(tmp_path / dropped, src, {kept: both[kept]})
        res, _c, _p = _contracts_result(ctx, root)
        assert not res.passed, res.detail
        assert dropped in res.detail
        assert kept not in res.detail


def test_scheduler_is_never_a_provider(tmp_path):
    """§ Health Checks: `scheduler` core services are exempt. Cron invokes one
    and nobody else does, so it exposes no boundary to contract."""
    src = (
        _codebase(
            "api",
            _proc("web", "web", networks=["web", "internal"], port=8080, hcp=True),
        )
        + _codebase(
            "jobs",
            _proc(
                "nightly",
                "scheduler",
                networks=["internal"],
                extra=['        schedule: "0 3 * * *"'],
            ),
        )
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.openapi.yml": _openapi("/health")}
    )
    res, _contracts, providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert providers == ["api.web"]
    assert "jobs.nightly" not in res.detail

    # And it is exempt from the fan-out and the probeability assertion even when
    # something (illegally, per rule 25) consumes it.
    src_consumed = (
        _codebase(
            "api",
            _proc(
                "web",
                "web",
                networks=["web", "internal"],
                port=8080,
                hcp=True,
                consumes=["jobs.nightly"],
            ),
        )
        + _codebase(
            "jobs",
            _proc(
                "nightly",
                "scheduler",
                networks=["internal"],
                extra=['        schedule: "0 3 * * *"'],
            ),
        )
    )
    ctx, root = _project(
        tmp_path / "consumed",
        src_consumed,
        {"api.web.openapi.yml": _openapi("/health")},
    )
    res, _c, _p = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert _health_result(ctx, root).passed


def test_unknown_role_fallback_is_reported(tmp_path):
    """An unrecognized role falls back to openapi rather than raising — but the
    fallback is named in the gate detail, never taken silently."""
    src = _codebase(
        "api",
        _proc("web", "web", networks=["web", "internal"], port=8080, hcp=True),
        _proc("bogus", "bogus", networks=["web", "internal"], port=8081),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.openapi.yml": _openapi("/health"),
            "api.bogus.openapi.yml": _openapi("/health"),
        },
    )
    res, _contracts, _providers = _contracts_result(ctx, root)
    assert res.passed, res.detail
    assert "unrecognized role, assumed openapi" in res.detail
    assert "api.bogus" in res.detail
    assert "'bogus'" in res.detail


# ---------------------------------------------------------------------------
# Filename parsing.
# ---------------------------------------------------------------------------


def test_contract_filename_parsed_right_anchored():
    assert _parse_contract_filename("api.web.openapi.yml") == (
        "api", "web", "openapi",
    )
    assert _parse_contract_filename("api.worker.asyncapi.yaml") == (
        "api", "worker", "asyncapi",
    )
    # Two segments: the pre-Mod-096 shape. Not a name this gate authored.
    assert _parse_contract_filename("api.openapi.yml") is None
    assert _parse_contract_filename("a.b.c.d.yml") is None
    assert _parse_contract_filename("api.web.openapi.txt") is None
    assert _parse_contract_filename("api..openapi.yml") is None


# ---------------------------------------------------------------------------
# Health endpoints — fan-out.
# ---------------------------------------------------------------------------


def test_missing_fanout_probe_fails(tmp_path):
    contracts = {
        "api.web.openapi.yml": _openapi("/health"),
        "api.worker.asyncapi.yml": _ASYNCAPI,
    }
    ctx, root = _project(tmp_path, _web_and_worker(), contracts)
    res = _health_result(ctx, root)
    assert not res.passed
    assert "/health/api/worker" in res.detail

    contracts["api.web.openapi.yml"] = _openapi("/health", "/health/api/worker")
    ctx, root = _project(tmp_path / "fixed", _web_and_worker(), contracts)
    assert _health_result(ctx, root).passed


def test_fanout_required_without_depends_on(tmp_path):
    """The whole point of keying off `consumes`: rule 24 forbids a core
    `depends_on`, so a `depends_on`-keyed gate would require nothing here."""
    src = _web_and_worker()
    assert "depends_on" not in src  # the shape genuinely has no depends_on edge

    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.openapi.yml": _openapi("/health"),
            "api.worker.asyncapi.yml": _ASYNCAPI,
        },
    )
    assert "depends_on" not in (root / "infra" / "infra.yml").read_text()
    res = _health_result(ctx, root)
    assert not res.passed
    assert "/health/api/worker" in res.detail


def test_web_target_is_not_proxied(tmp_path):
    """§ Fan-out's carve-out: a target on `web` is publicly reachable and answers
    its own `/health` at its own hostname, so there is nothing to proxy."""
    src = _codebase(
        "api",
        _proc(
            "web",
            "web",
            networks=["web", "internal"],
            port=8080,
            hcp=True,
            consumes=["api.admin"],
        ),
        _proc("admin", "web", networks=["web", "internal"], port=8081, hcp=True),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.openapi.yml": _openapi("/health"),
            "api.admin.openapi.yml": _openapi("/health"),
        },
    )
    res = _health_result(ctx, root)
    assert res.passed, res.detail


# ---------------------------------------------------------------------------
# Health endpoints — self health.
# ---------------------------------------------------------------------------


def test_openapi_provider_requires_self_health(tmp_path):
    src = _codebase(
        "api",
        _proc("web", "web", networks=["web", "internal"], port=8080, hcp=True),
    )
    ctx, root = _project(
        tmp_path, src, {"api.web.openapi.yml": _openapi("/other")}
    )
    res = _health_result(ctx, root)
    assert not res.passed
    assert "GET /health" in res.detail
    assert "api.web.openapi.yml" in res.detail


def test_internal_openapi_provider_requires_self_health(tmp_path):
    """Q5's widening: self-`/health` follows the OpenAPI contract, not `web`
    membership. § Self health has no web-network qualifier — an internal-only
    `web`-role core service reached via `consumes` is exactly what must be probeable
    one hop away."""
    src = _codebase(
        "api",
        _proc(
            "web",
            "web",
            networks=["web", "internal"],
            port=8080,
            hcp=True,
            consumes=["api.internal"],
        ),
        _proc("internal", "web", networks=["internal"], port=8081, hcp=True),
    )
    ctx, root = _project(
        tmp_path,
        src,
        {
            "api.web.openapi.yml": _openapi("/health", "/health/api/internal"),
            "api.internal.openapi.yml": _openapi("/other"),
        },
    )
    res = _health_result(ctx, root)
    assert not res.passed
    assert "api.internal.openapi.yml" in res.detail
    assert "GET /health" in res.detail
    # The consumer itself is fine — only the internal provider is at fault.
    assert "api.web.openapi.yml" not in res.detail


# ---------------------------------------------------------------------------
# Health endpoints — probeability (§ Declared by fields).
# ---------------------------------------------------------------------------


def test_consumes_target_without_port_fails(tmp_path):
    ctx, root = _project(
        tmp_path,
        _web_and_worker(worker_port=None),
        {
            "api.web.openapi.yml": _openapi("/health", "/health/api/worker"),
            "api.worker.asyncapi.yml": _ASYNCAPI,
        },
    )
    res = _health_result(ctx, root)
    assert not res.passed
    assert "api.worker" in res.detail
    assert "port" in res.detail
    assert "api.web" in res.detail  # names the consumer too


def test_consumes_target_without_health_check_path_fails(tmp_path):
    ctx, root = _project(
        tmp_path,
        _web_and_worker(worker_hcp=False),
        {
            "api.web.openapi.yml": _openapi("/health", "/health/api/worker"),
            "api.worker.asyncapi.yml": _ASYNCAPI,
        },
    )
    res = _health_result(ctx, root)
    assert not res.passed
    assert "api.worker" in res.detail
    assert "health_check_path" in res.detail


def test_fully_declared_consumes_target_passes(tmp_path):
    """The positive control for the two above — otherwise they could pass for
    the wrong reason."""
    ctx, root = _project(
        tmp_path,
        _web_and_worker(),
        {
            "api.web.openapi.yml": _openapi("/health", "/health/api/worker"),
            "api.worker.asyncapi.yml": _ASYNCAPI,
        },
    )
    res = _health_result(ctx, root)
    assert res.passed, res.detail
