"""``docex check`` — ephemeral worktree + full gate-check suite.

Per [docex.md § check] and [cicd.md § Check Step]: the workflow is

  1. Refuse to run with a dirty tree or on ``main``.
  2. ``git fetch origin`` so we have an authoritative ``origin/main``.
  3. Create an ephemeral worktree at
     ``<root>/.docex/worktrees/check-<short_sha>`` pointing at the
     feature branch.
  4. Inside the worktree, rebase onto ``origin/main``.
  5. Run every gate check — aggregating failures so the developer sees
     all problems in one pass.
  6. Compile + ``compose build`` against the worktree to catch
     Dockerfile errors.
  7. ``docex test`` (delegated to :func:`docex.orchestrate.test.run_test`)
     against the worktree, exercising the full doctrinal test loop.
  8. Always tear down the worktree (success or failure) and delete
     the temp branch.

The gate-check aggregation pattern matches Phase 1's compile-time
validation: collect every result, render a table at the end, exit
non-zero if any failed.
"""

from __future__ import annotations

import shutil
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from docex.cicl.model import CICLDocument, ServiceRef, CoreService  # noqa: F401
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import WorkingTreeDirty
from docex.git.client import GitClient
from docex.naming import dns_label
from docex.orchestrate._common import codebases, services_with_schema
from docex.pipeline._worktree import (
    cleanup_worktree,
    make_temp_branch,
    parse_version,
    worktree_path_for,
)


# ---------------------------------------------------------------------------
# Gate-check report data structures.
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """One gate check's outcome."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class CheckReport:
    """Aggregated outcome of every gate check in a single ``check`` run."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name=name, passed=passed, detail=detail))

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


def _aggregate_check_report(report: CheckReport) -> str:
    """Render the report as a human-readable table."""
    name_w = max((len(r.name) for r in report.results), default=4)
    lines = ["", "docex check — gate results:", ""]
    for r in report.results:
        marker = "PASS" if r.passed else "FAIL"
        line = f"  [{marker}] {r.name.ljust(name_w)}"
        if r.detail:
            line += f"  — {r.detail}"
        lines.append(line)
    lines.append("")
    if report.all_passed:
        lines.append(f"all {len(report.results)} gate(s) passed.")
    else:
        lines.append(
            f"{report.failure_count}/{len(report.results)} gate(s) failed."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contract format.
# ---------------------------------------------------------------------------

# contracts.md § Standards: the format follows from the PROVIDER'S ROLE, not from
# the shape of the graph — the role is what fixes the communication mechanism, so
# it is the honest source. `scheduler` is absent because a scheduler is never a
# provider (see `_gate_contracts`).
_CONTRACT_FORMAT_BY_ROLE = {
    "web": "openapi",
    "worker": "asyncapi",
}
_FALLBACK_CONTRACT_FORMAT = "openapi"


def _contract_format_for_role(role: str) -> tuple[str, bool]:
    """``(format, role_recognized)`` for a provider core service.

    Mod 101 replaces a heuristic (`_infer_contract_format`) whose asyncapi branch
    was unreachable from the day it was written: its only call site passed a CORE
    service name, the function then looked that name up in `backing_services`, and
    `model.py` forbids the overlap — so it returned "openapi" every time it was
    ever called. That is why the async-contract path was never exercised.

    WHY a fallback rather than a raise: an unrecognized core role is already a
    transfer-table load error, and raising here would deny the operator every other
    gate's result — the aggregation pattern exists precisely to avoid that. The
    caller surfaces the fallback in the gate detail so it is never silent.
    """
    fmt = _CONTRACT_FORMAT_BY_ROLE.get(role)
    if fmt is None:
        return _FALLBACK_CONTRACT_FORMAT, False
    return fmt, True


def _parse_contract_filename(name: str) -> tuple[str, str, str] | None:
    """``"api.web.openapi.yml"`` → ``("api", "web", "openapi")``; else ``None``.

    RIGHT-anchored, per contracts.md's `${service}.${process}.${format}.yml`. The
    left-anchored `name.split(".", 1)[0]` this replaces yielded "api" — a valid
    `codebases` key purely because the codebase happens to be the first segment
    — and discarded the process entirely, so the health gate reasoned at codebase
    granularity and silently `continue`d on anything it could not match.

    Exactly three segments are required: `_SERVICE_NAME_RE` (model.py) admits no
    dots in a service or process name, so a canonical contract filename has three
    and nothing else is a name this gate authored.
    """
    stem = name
    for suffix in (".yml", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        return None
    parts = stem.split(".")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        return None
    return parts[-3], parts[-2], parts[-1]


def _resolve_service(
    infra: CICLDocument, dotted: str
) -> tuple[str, str, CoreService] | None:
    """``"api.worker"`` → ``("api", "worker", <CoreService>)`` if it names a real
    core service, else ``None``.

    Returning ``None`` for an unresolvable reference is deliberate: rule 25 already
    reports it, and this gate must not double-report it as a missing contract or a
    missing probe endpoint.
    """
    try:
        ref = ServiceRef.parse(dotted)
    except ValueError:
        return None
    svc = infra.codebases.get(ref.codebase)
    if svc is None:
        return None
    proc = svc.core_services.get(ref.service)
    if proc is None:
        return None
    return ref.codebase, ref.service, proc


# ---------------------------------------------------------------------------
# Individual gate checks.
# ---------------------------------------------------------------------------


def _gate_clean_worktree(
    worktree: Path, git: GitClient, report: CheckReport
) -> None:
    clean = git.is_clean(worktree)
    report.add(
        "worktree_clean",
        clean,
        "" if clean else "worktree has uncommitted changes after rebase",
    )


def _gate_latest_main(
    project_root: Path,
    worktree: Path,
    git: GitClient,
    report: CheckReport,
) -> None:
    """Confirm we rebased onto the *fetched* origin/main, not a stale local.

    We capture origin/main's sha via ``rev-parse`` on the project repo
    (it was just fetched), then assert that the worktree's history
    contains that sha — i.e. ``merge-base origin/main HEAD`` equals
    origin/main's sha.
    """
    origin_main = git.head_sha(project_root)  # We'll re-check below.
    # Better: compute origin/main directly via merge-base.
    from docex.git.subprocess_client import SubprocessGitClient

    # Use the existing client's `merge_base` for a clean abstraction.
    origin_main_sha = _resolve_origin_main(project_root, git)
    if origin_main_sha == "":
        report.add(
            "latest_main",
            False,
            "could not resolve origin/main; did 'git fetch' fail?",
        )
        return
    mb = git.merge_base(worktree, "HEAD", origin_main_sha)
    on_top = mb == origin_main_sha
    report.add(
        "latest_main",
        on_top,
        (
            ""
            if on_top
            else f"worktree HEAD does not include origin/main ({origin_main_sha[:8]})"
        ),
    )
    # Quiet the unused-variable warning.
    _ = origin_main


def _resolve_origin_main(project_root: Path, git: GitClient) -> str:
    """Return origin/main's sha or empty string if unresolvable."""
    # We need rev-parse on origin/main; expose it via the existing
    # ``head_sha`` shape would require a ref argument. The Protocol
    # doesn't have a generic rev-parse, but ``merge_base(a, b)`` does
    # accept any refish — and merge_base(origin/main, origin/main) is
    # the same as resolving origin/main to a sha. That's portable.
    return git.merge_base(project_root, "origin/main", "origin/main")


def _gate_version_bumped(
    project_root: Path,
    worktree: Path,
    report: CheckReport,
) -> None:
    """Worktree's project.yml version must be strictly greater than main's."""
    new_ctx = load_project_context(worktree)
    new_version = new_ctx.project.version

    # Read main's project.yml from the parent repo (not worktree, since
    # main may have moved). We look at the project_root's main branch.
    # The parent repo is presumed to be on the feature branch right now;
    # use ``git show origin/main:project.yml`` to fetch the file content.
    try:
        main_content = _git_show(project_root, "origin/main", "project.yml")
    except RuntimeError as exc:
        report.add("version_bumped", False, str(exc))
        return
    try:
        main_raw = yaml.safe_load(main_content) or {}
        main_version = main_raw.get("version", "0.0.0")
    except yaml.YAMLError:
        report.add(
            "version_bumped",
            False,
            "main's project.yml is malformed YAML",
        )
        return
    cmp_ok = parse_version(new_version) > parse_version(main_version)
    report.add(
        "version_bumped",
        cmp_ok,
        (
            f"feature version {new_version!r} bumps main's {main_version!r}"
            if cmp_ok
            else f"feature version {new_version!r} does not exceed main's {main_version!r}"
        ),
    )


def _git_show(repo: Path, ref: str, path: str) -> str:
    """Return the content of ``<ref>:<path>``, raising on failure.

    Routes through ``SubprocessGitClient.show`` — the single
    read-a-blob mechanism — and converts its ``None`` into the
    exception shape this module's gates already catch.
    """
    from docex.git.subprocess_client import SubprocessGitClient

    content = SubprocessGitClient().show(repo, ref, path)
    if content is None:
        raise RuntimeError(f"git show {ref}:{path} failed")
    return content


def _gate_version_not_released(
    project_root: Path,
    worktree: Path,
    git: GitClient,
    report: CheckReport,
) -> None:
    new_ctx = load_project_context(worktree)
    version = new_ctx.project.version
    tag_name = f"v{version}"
    # Look at the parent repo's tags — the worktree shares the same
    # object DB so either source works, but project_root is canonical.
    tags = git.list_tags(project_root, pattern="v*")
    free = tag_name not in tags
    report.add(
        "version_not_released",
        free,
        (
            f"tag {tag_name!r} is unused — safe to release"
            if free
            else f"tag {tag_name!r} already exists; bump project.yml version"
        ),
    )


def _gate_no_merge_conflicts(rebase_rc: int, report: CheckReport) -> None:
    ok = rebase_rc == 0
    report.add(
        "no_merge_conflicts",
        ok,
        "" if ok else f"git rebase exited {rebase_rc}",
    )


def _gate_contracts(
    worktree: Path,
    ctx: ProjectContext,
    report: CheckReport,
) -> tuple[list[Path], list[str]]:
    """Verify every required contract file is present.

    Per contracts.md, **the provider set is (`consumes` targets) ∪ (`web`-network
    core service)**, minus `scheduler` core service. Both arms are load-bearing:
    the first is the declared interface graph; the second catches every publicly
    reachable boundary even when nothing inside the project consumes it, which is
    what gives the health-endpoint gate something to validate. Driving the set off
    `consumes` alone would silently switch that gate off for a public edge.

    Providers ship a contract at ``infra/contracts/<svc>.<proc>.<fmt>.yml``. The
    path is process-keyed unconditionally: one codebase may run two HTTP process
    types — a public `api` and an internal `admin` — and both are genuine
    boundaries deserving their own contract.

    Returns (existing_contracts, providers) — the contract paths that DO exist,
    for the next gate to scan, and the provider process refs, dotted.
    """
    infra = ctx.infra
    existing: list[Path] = []
    providers: list[str] = []
    if infra is None:
        report.add("contracts_exist", True, "no infra.yml — skipped")
        return existing, providers

    # Every `consumes` target in the document, dotted. Mod 101 is the first
    # reader of `consumes`; it lives on the AUTHORING model (Mod 098 kept it off
    # `CompiledService` deliberately), which is what this gate reads.
    consumed: set[str] = set()
    for _s, _p, _svc, proc in infra.all_core_services():
        consumed |= proc.consumes_refs()

    contracts_dir = worktree / "infra" / "contracts"
    missing: list[str] = []
    fallbacks: list[str] = []
    for svc_name, service_name, _svc, proc in infra.all_core_services():
        # contracts.md § Health Checks: `scheduler` core services are exempt.
        # Rule 25 now forbids consuming one and rule 27 forbids `web` in its
        # networks, so neither arm can reach a scheduler — the gate states the
        # exemption anyway so it does not depend on the validator to be correct.
        if proc.role == "scheduler":
            continue
        label = ServiceRef(svc_name, service_name).dotted
        on_web = "web" in (proc.networks or [])
        if not (on_web or label in consumed):
            continue  # not a provider
        providers.append(label)
        fmt, role_known = _contract_format_for_role(proc.role)
        if not role_known:
            fallbacks.append(f"{label} (role {proc.role!r})")
        candidate = contracts_dir / f"{svc_name}.{service_name}.{fmt}.yml"
        if candidate.is_file():
            existing.append(candidate)
        else:
            missing.append(f"{label} (expected {candidate.relative_to(worktree)})")

    fallback_clause = (
        "; unrecognized role, assumed openapi: " + ", ".join(fallbacks)
        if fallbacks
        else ""
    )
    if missing:
        # The fallback is likely to be WHY a contract appears missing (the gate
        # looked for the wrong extension), so it belongs on the failure too.
        report.add(
            "contracts_exist",
            False,
            "missing contract(s): " + "; ".join(missing) + fallback_clause,
        )
    else:
        detail = (
            f"{len(existing)} contract(s) present"
            if existing
            else "no provider core service — nothing to check"
        )
        report.add("contracts_exist", True, detail + fallback_clause)
    return existing, providers


def _gate_health_endpoints(
    worktree: Path,
    ctx: ProjectContext,
    contracts: list[Path],
    report: CheckReport,
) -> None:
    """Assert the doctrine's health model (contracts.md § Health Checks).

    Three things, per core service:

    1. **Self health** — every OpenAPI provider declares ``GET /health``. § Self
       health says *every* long-running core service serves it; a `worker` is not
       checked here because its contract is AsyncAPI, which has no natural place
       for an HTTP path — not because it is exempt. Its self-health is asserted
       through its fields instead (3).
    2. **Fan-out** — every `web`-network core service declares
       ``GET /health/<codebase>/<service>`` for each of its `consumes` targets that is not
       itself on `web`. Keyed off `consumes`, not `depends_on`: a web edge does not
       depend on its worker (it needs the *broker* up), and rule 24 now forbids a
       core `depends_on` outright, so a `depends_on`-keyed gate requires nothing at
       all of a web → worker edge. A dead consumer is invisible from outside —
       requests keep returning 200 while work piles up behind it. Targets on `web`
       are skipped: they are publicly reachable and answer their own `/health`, so
       there is nothing to proxy. Backing services have no `<codebase>/<service>` form and
       are not required (mod 047); a project may still declare them voluntarily.
    3. **Probeability** — a `consumes` target declares both `port` and
       `health_check_path`. Per § Declared by fields those two fields *are* the
       health declaration. On elastic the `port` is also exactly what makes the
       target Service-Connect-discoverable, which is what lets a sibling `web`
       process reach its `/health` one hop away. Distinct from rule 28, which
       constrains a core service that *has* `health_check_path`; this requires a
       consumes target to have it at all.

    `scheduler` core services are exempt throughout.
    """
    infra = ctx.infra
    if infra is None:
        report.add("health_endpoints", True, "no infra.yml — skipped")
        return

    problems: list[str] = []

    # --- 1 + 2: what the contracts must declare -------------------------
    for path in contracts:
        parsed = _parse_contract_filename(path.name)
        if parsed is None:
            continue  # not a contract filename this gate authored
        svc, service_name, fmt = parsed
        resolved = _resolve_service(infra, f"{svc}.{service_name}")
        if resolved is None:
            continue  # contract for an unknown core service — skip
        _s, _p, proc = resolved
        if proc.role == "scheduler":
            continue

        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: malformed YAML ({exc})")
            continue
        paths_map = (doc.get("paths") or {}) if isinstance(doc, dict) else {}

        def _declares(key: str, _paths_map: dict = paths_map) -> bool:
            node = _paths_map.get(key)
            return isinstance(node, dict) and "get" in {k.lower() for k in node}

        if fmt == "openapi" and not _declares("/health"):
            problems.append(
                f"{path.name}: missing 'GET /health' (contracts.md § Self health "
                f"— every long-running core service serves it)"
            )

        if "web" not in (proc.networks or []):
            continue
        for dotted in sorted(proc.consumes_refs()):
            target = _resolve_service(infra, dotted)
            if target is None:
                continue
            t_svc, t_proc_name, t_proc = target
            if t_proc.role == "scheduler":
                continue
            if "web" in (t_proc.networks or []):
                continue  # publicly reachable; nothing to proxy
            key = f"/health/{t_svc}/{t_proc_name}"
            if not _declares(key):
                problems.append(
                    f"{path.name}: missing 'GET {key}' (required because "
                    f"{svc}.{service_name} consumes non-web {dotted})"
                )

    # --- 3: what the consumed core service's FIELDS must declare --------
    # Keyed by target so two consumers of one under-declared target produce one
    # problem naming both, not two problems saying the same thing.
    underdeclared: dict[str, tuple[list[str], set[str]]] = {}
    for svc_name, service_name, _svc, proc in infra.all_core_services():
        for dotted in sorted(proc.consumes_refs()):
            target = _resolve_service(infra, dotted)
            if target is None:
                continue
            _t_svc, _t_proc_name, t_proc = target
            if t_proc.role == "scheduler":
                continue
            absent = []
            if t_proc.port is None:
                absent.append("port")
            if (t_proc.model_extra or {}).get("health_check_path") is None:
                absent.append("health_check_path")
            if absent:
                entry = underdeclared.setdefault(dotted, (absent, set()))
                entry[1].add(ServiceRef(svc_name, service_name).dotted)
    for dotted in sorted(underdeclared):
        absent, consumers = underdeclared[dotted]
        problems.append(
            f"consumes target {dotted!r} declares no "
            f"{' and no '.join(absent)} — those fields ARE its health "
            f"declaration (contracts.md § Declared by fields), and on elastic "
            f"the port is what makes it Service-Connect-discoverable. "
            f"Consumed by: {', '.join(sorted(consumers))}."
        )

    if problems:
        report.add("health_endpoints", False, "; ".join(problems))
    else:
        report.add(
            "health_endpoints",
            True,
            f"all required endpoints present in {len(contracts)} contract(s)",
        )


def _gate_healthcheck_tooling(
    worktree: Path,
    ctx: ProjectContext,
    docker: DockerClient,
    report: CheckReport,
) -> None:
    """Verify every ``health_check_path``-declaring web-service image carries
    ``curl``.

    Mod 051 (Gap I): ``web.yml``'s ``health_check_path`` field compiles to a
    Docker healthcheck that probes ``/health`` with ``curl``. On a curl-less
    base image (python-slim, alpine, distroless) the healthcheck errors on
    every run, Docker marks the container ``unhealthy``, and Traefik 3.x's
    docker provider drops the route — the service is silently unreachable with
    no application-log signal. This gate turns that into a loud, early failure:
    it builds each qualifying service's ``prod``-target image and runs
    ``command -v curl`` inside it.

    Scope is every core service that declares ``health_check_path`` —
    **regardless of network membership**, per ``infrastructure.md``'s "any
    core service that declares a ``health_check_path`` must carry ``curl``."
    The curl need follows the field, not the ``web`` network: the compiler
    emits the curl healthcheck whenever ``health_check_path`` is set (mod 059
    confirmed a ``web``-role service on a non-``web`` network still gets it),
    and a curl-less healthcheck marks the container ``unhealthy`` — which drops
    the Traefik route for a ``web`` service AND breaks any
    ``depends_on: service_healthy`` waiting on a non-``web`` one. A service that
    declares no ``health_check_path`` (e.g. a port-less worker) needs no curl.
    See ``contracts.md § Health Checks`` and ``infrastructure.md § Healthcheck
    Tooling Requirement``.
    """
    infra = ctx.infra
    if infra is None:
        report.add("healthcheck_tooling", True, "no infra.yml — skipped")
        return

    qualifying: list[str] = []
    for name in sorted(infra.codebases):
        svc = infra.codebases[name]
        # ``extra="allow"`` on CoreService surfaces role fields like
        # ``health_check_path`` in ``model_extra``; absent ⇒ None. Only
        # ``role: web`` declares the field, but such a core service may sit on
        # a non-``web`` network and still get the curl healthcheck — so do NOT
        # filter on web membership (mod 059).
        #
        # Mod 096: read the CORE SERVICE. A `getattr(svc, ...)` against the
        # Codebase goes permanently None once the field is service-scoped,
        # so the gate would pass while checking nothing and Mod 051's curl
        # protection would be silently defeated. One image per codebase, so
        # one qualifying entry per codebase — any core service declaring the
        # field obliges the shared image to carry curl.
        declares_hc = any(
            (p.model_extra or {}).get("health_check_path") is not None
            for p in svc.core_services.values()
        )
        if declares_hc:
            qualifying.append(name)

    if not qualifying:
        report.add(
            "healthcheck_tooling",
            True,
            "no health_check_path-declaring web services — nothing to check",
        )
        return

    problems: list[str] = []
    for svc in qualifying:
        svc_dir = worktree / "core" / svc
        tag = f"docex-hcgate-{svc}:check"
        build_rc = docker.build_image(svc_dir, target="prod", tag=tag)
        if build_rc != 0:
            # The build gate will also catch this; record + move on so the
            # operator still sees the curl status of any other service.
            problems.append(f"{svc}: image build failed")
            continue
        probe_rc = docker.run_one_shot(
            tag,
            ["sh", "-c", "command -v curl >/dev/null 2>&1"],
            remove=True,
        )
        if probe_rc != 0:
            problems.append(
                f"service {svc!r} declares health_check_path but its image "
                "lacks curl; the Docker healthcheck will fail and Traefik will "
                "drop the route. Add curl to its Dockerfile "
                "(apt-get/apk install curl)."
            )

    if problems:
        report.add("healthcheck_tooling", False, "; ".join(problems))
    else:
        report.add(
            "healthcheck_tooling",
            True,
            f"curl present in {len(qualifying)} web-service image(s)",
        )


def _gate_service_scripts(
    worktree: Path,
    ctx: ProjectContext,
    report: CheckReport,
) -> None:
    """``build.sh`` and ``test.sh`` for every core service; ``migrate.sh``
    for any service that's a schema owner."""
    problems: list[str] = []
    services = codebases(ctx)
    schema_owners = set(services_with_schema(ctx))

    for svc in services:
        svc_root = worktree / "core" / svc
        for script in ("build.sh", "test.sh"):
            path = svc_root / script
            if not path.is_file():
                problems.append(f"core/{svc}/{script} missing")
            elif not _is_executable(path):
                problems.append(f"core/{svc}/{script} not executable")
        if svc in schema_owners:
            mpath = svc_root / "migrate.sh"
            if not mpath.is_file():
                problems.append(f"core/{svc}/migrate.sh missing")
            elif not _is_executable(mpath):
                problems.append(f"core/{svc}/migrate.sh not executable")

    if problems:
        report.add("service_scripts", False, "; ".join(problems))
    else:
        report.add(
            "service_scripts",
            True,
            f"build.sh/test.sh present for {len(services)} service(s)",
        )


def _is_executable(path: Path) -> bool:
    import os

    return os.access(path, os.X_OK)


def _gate_observability_backend_url_reachable(
    ctx: ProjectContext,
    report: CheckReport,
) -> None:
    """HTTP GET against ``observability_backend_url``. Any 2xx/3xx/4xx
    response passes — the check verifies the host resolves and the TLS
    handshake completes. DNS resolution failure, TLS handshake failure,
    connection refusal, or timeout fails the gate.

    See doctrine/infrastructure/specifics/telemetry_infra.md § Validation
    Rules and cicd.md § Check Step.
    """
    infra = ctx.infra
    if infra is None:
        report.add(
            "observability_backend_reachable",
            True,
            "no infra.yml — skipped",
        )
        return

    url = infra.observability_backend_url
    try:
        # 10 s timeout: enough for slow ACME-backed TLS handshakes but
        # short enough that an unreachable host fails the gate quickly.
        with urllib.request.urlopen(url, timeout=10):  # nosec B310
            pass
    except urllib.error.HTTPError as exc:
        # Server responded with non-2xx — host is up. 401/404 are common
        # for OTLP-only endpoints lacking a generic GET handler; either
        # confirms reachability sufficient to catch DNS/cert typos.
        report.add(
            "observability_backend_reachable",
            True,
            f"{url} responded HTTP {exc.code}",
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        report.add(
            "observability_backend_reachable",
            False,
            f"{url} unreachable: {exc}",
        )
    else:
        report.add(
            "observability_backend_reachable",
            True,
            f"{url} reachable",
        )


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def run_check(
    ctx: ProjectContext,
    docker: DockerClient,
    git: GitClient,
) -> int:
    """Run the full check sequence. Returns process exit code."""
    project_root = ctx.project_root

    # 1. Pre-check on the developer's tree ------------------------------
    if not git.is_clean(project_root):
        raise WorkingTreeDirty(
            "check refuses to run with a dirty working tree. "
            "Commit or stash your changes first."
        )

    feature = git.current_branch(project_root)
    if feature == "" or feature == "main":
        print(
            "error: check must be run from a feature branch "
            f"(currently {feature or '<detached HEAD>'!r}).",
            file=sys.stderr,
        )
        return 1

    # 2. Fetch ----------------------------------------------------------
    rc = git.fetch(project_root, remote="origin")
    if rc != 0:
        print(
            f"warning: 'git fetch origin' exited {rc}; "
            "continuing with potentially stale origin/main.",
            file=sys.stderr,
        )

    # 3. Worktree creation ---------------------------------------------
    short_sha = git.head_sha(project_root, short=True)
    worktree = worktree_path_for(project_root, f"check-{short_sha}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    temp_branch = make_temp_branch("check", feature)

    rc = git.worktree_add(
        project_root,
        worktree,
        branch=temp_branch,
        ref=feature,
    )
    if rc != 0:
        print(
            f"error: 'git worktree add' exited {rc}; cannot run check.",
            file=sys.stderr,
        )
        return rc

    # First-release-on-empty-remote detection: a brand-new project's
    # remote has no `main` ref yet (e.g. inception's first PART V
    # release). Trunk-comparing gates have nothing to compare against
    # and rebase has nothing to rebase onto. We run the gates that
    # don't depend on origin/main and skip the rest with a banner.
    empty_origin = not git.ref_exists(project_root, "origin/main")

    report = CheckReport()
    try:
        if empty_origin:
            # No trunk to rebase onto — just check out at HEAD.
            print(
                "check: origin/main does not exist yet — running in "
                "first-release mode (trunk-comparing gates are "
                "skipped). `docex merge` will seed origin/main from "
                "this feature branch.",
                file=sys.stderr,
            )
            # Trunk-comparing gates get a single PASS line each so the
            # report still makes sense.
            report.add("no_merge_conflicts", True, "skipped (empty origin/main)")
            report.add("worktree_clean", True, "skipped (empty origin/main)")
            report.add("latest_main", True, "skipped (empty origin/main)")
            report.add("version_bumped", True, "skipped (empty origin/main)")
            report.add("version_not_released", True, "skipped (empty origin/main)")
        else:
            # 4. Rebase onto fetched origin/main ----------------------------
            rebase_rc = git.rebase(worktree, "origin/main")
            if rebase_rc != 0:
                # Abort so the worktree's tree returns to a sane state for
                # ``worktree_remove`` to succeed.
                git.rebase_abort(worktree)

            # 5. Gate checks -------------------------------------------------
            _gate_no_merge_conflicts(rebase_rc, report)
            _gate_clean_worktree(worktree, git, report)
            _gate_latest_main(project_root, worktree, git, report)
            _gate_version_bumped(project_root, worktree, report)

        # Load the worktree's ProjectContext for the remaining gates.
        worktree_ctx = load_project_context(worktree)

        if not empty_origin:
            _gate_version_not_released(project_root, worktree, git, report)
        contracts, _providers = _gate_contracts(worktree, worktree_ctx, report)
        _gate_health_endpoints(worktree, worktree_ctx, contracts, report)
        _gate_service_scripts(worktree, worktree_ctx, report)
        _gate_healthcheck_tooling(worktree, worktree_ctx, docker, report)
        _gate_observability_backend_url_reachable(worktree_ctx, report)

        # If any gate failed, surface aggregated report and stop.
        if not report.all_passed:
            print(_aggregate_check_report(report))
            return 1

        # 6. Build everything --------------------------------------------
        from docex.cicl.compile import run_compile
        from docex.orchestrate._common import compose_file_for
        from docex.orchestrate.aggregate import aggregate

        rc = run_compile(worktree_ctx)
        if rc != 0:
            print(
                f"error: 'docex compile' against worktree exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # The configurable-value source files (secrets/config/tte) are
        # gitignored per doctrine, so `git worktree add` does NOT carry
        # them — they live only in the operator's main project tree.
        # Mirror the `test` env's source files in (same pattern rollback.py
        # uses for gitignored deploy creds), then build the worktree's
        # aggregate there. The build + test steps below both consume it as
        # the compose --env-file so `${VAR}` substitutions resolve and the
        # worktree stack gets its real (minted-in-worktree) TTE values.
        for src_rel in (
            "infra/secrets/test.env",
            "infra/config/test.env",
            "infra/tte/test.env",
        ):
            src = ctx.project_root / src_rel
            if src.is_file():
                dst = worktree / src_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        env_file = aggregate(worktree_ctx, env="test")

        # Override compose's --project-directory to the worktree path
        # so build contexts and bind-mounts resolve against the
        # worktree tree, not the main project tree.
        compose_path = compose_file_for(worktree_ctx, "test")
        # Worktree-unique compose project name so this throwaway `test`
        # stack can't collide with — or get torn down alongside — a real
        # `test` env stack on the same host. Folds in the worktree slug
        # (``check-<short_sha>``) so concurrent checks don't clash either.
        check_project_name = f"{dns_label(worktree_ctx.project.name)}-{worktree.name}"
        # Use compose_up with build=True then immediately down; we want
        # to confirm `docker build` succeeds without leaving containers
        # around. Easier: a dedicated compose build step.
        rc = _compose_build(
            docker, compose_path, env_file, worktree,
            project_name=check_project_name,
        )
        if rc != 0:
            print(
                f"error: 'docker compose build' against worktree exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # 7. Run the full test loop -------------------------------------
        from docex.orchestrate.test import run_test

        rc = run_test(
            worktree_ctx, docker,
            project_dir=worktree,
            env_file_override=env_file,
            project_name=check_project_name,
        )
        if rc != 0:
            print(
                f"error: 'docex test' against worktree exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # All good.
        print(_aggregate_check_report(report))
        print("check: all gates and tests passed.")
        return 0
    finally:
        # 8. Cleanup, always ----------------------------------------------
        cleanup_worktree(project_root, worktree, temp_branch, git)


def _compose_build(
    docker: DockerClient,
    compose_file: Path,
    env_file: Path | None,
    project_dir: Path | None = None,
    *,
    project_name: str | None = None,
) -> int:
    """Trigger ``docker compose build`` via the DockerClient abstraction.

    The Phase 2 DockerClient doesn't have a dedicated ``compose_build``
    method, but ``compose_up(build=True, detach=True)`` followed by
    ``compose_down`` accomplishes the same: it builds everything and
    then tears down. We use that pattern so all docker invocations
    still go through the abstraction. ``project_name`` keeps this
    throwaway build stack isolated from any real ``test`` env stack on
    the same host (and the matching ``down`` only removes this stack).
    """
    rc = docker.compose_up(
        compose_file,
        build=True,
        detach=True,
        env_file=env_file,
        project_dir=project_dir,
        project_name=project_name,
    )
    # Down regardless — we just wanted the build step.
    docker.compose_down(
        compose_file, preserve_volumes=False,
        env_file=env_file, project_dir=project_dir,
        project_name=project_name,
    )
    return rc


# Re-export for use by ``merge`` (which re-runs check defensively).
__all__ = ["run_check", "CheckReport", "CheckResult"]
