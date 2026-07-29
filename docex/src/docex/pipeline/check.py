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

from docex.cicl.model import CICLDocument  # noqa: F401 - typed in helpers
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import WorkingTreeDirty
from docex.git.client import GitClient
from docex.naming import dns_label
from docex.orchestrate._common import core_services, services_with_schema
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
# Contract-format inference.
# ---------------------------------------------------------------------------


def _infer_contract_format(infra: CICLDocument, service: str) -> str:
    """Guess the contract format for a service.

    Phase 3 keeps this shallow: HTTP-style consumers ⇒ ``openapi``;
    queue-style consumers ⇒ ``asyncapi``. Default to ``openapi`` if no
    clear signal — most projects today are HTTP-shaped.
    """
    # Look at consumers' relationship to this service. A queue-shaped
    # dependency surfaces via a backing service whose engine name has
    # ``queue``/``rabbit``/``kafka`` in it.
    for _consumer_name, consumer in infra.core_services.items():
        # Mod 096: `depends_on` is per-process type; a codebase "depends on"
        # a target if any of its process types does.
        consumer_deps = {
            dep for p in consumer.processes.values() for dep in (p.depends_on or [])
        }
        if service in consumer_deps:
            # If the dependency itself is a queue-shaped backing service,
            # treat as asyncapi.
            backing = infra.backing_services.get(service)
            if backing is not None:
                engine = backing.engine
                engine_str = (
                    engine if isinstance(engine, str) else ",".join(engine)
                ).lower()
                if any(kw in engine_str for kw in ("queue", "rabbit", "kafka")):
                    return "asyncapi"
    return "openapi"


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
    """Return the content of ``<ref>:<path>``. Uses subprocess directly via
    the SubprocessGitClient's capture helper to keep this single-call.

    We intentionally route through SubprocessGitClient — the only
    git-subprocess chokepoint — to keep the abstraction discipline.
    """
    from docex.git.subprocess_client import SubprocessGitClient

    cli = SubprocessGitClient()
    content = cli._capture(["show", f"{ref}:{path}"], cwd=repo)  # noqa: SLF001
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

    A core *process type* is a "provider" iff at least one other core
    service has its codebase in ``depends_on``, or it sits on the ``web``
    network. Providers must ship a contract file at
    ``infra/contracts/<svc>.<proc>.<fmt>.yml``.

    Returns (existing_contracts, providers) — the contract paths that
    DO exist, for the next gate to scan, and the list of provider
    process refs, dotted (for downstream-chain logic).
    """
    infra = ctx.infra
    existing: list[Path] = []
    providers: list[str] = []
    if infra is None:
        report.add("contracts_exist", True, "no infra.yml — skipped")
        return existing, providers

    # A core service is a "provider" iff either (a) some other core
    # service has it in ``depends_on``, or (b) it sits on the ``web``
    # network — web-network services have external HTTP consumers
    # whose dependency arrow isn't expressible in infra.yml.
    # Per contracts.md § Mandatory Endpoints, web-network services
    # must ship contracts so the health-endpoint gate has something to
    # validate.
    # Mod 096: `depends_on` and `networks` are process-scoped, so the
    # provider test moves down one level with them — and the contract path
    # gains the process segment, which is what contracts.md § Contract
    # Location fixes it at: `${service}.${process}.${format}.yml`. The
    # *criteria* are unchanged (web membership, or being some other
    # codebase's depends_on target); Mod 101 owns reworking those against
    # `consumes:`.
    dependants: dict[str, set[str]] = {}
    for name, svc in infra.core_services.items():
        for proc in svc.processes.values():
            for dep in (proc.depends_on or []):
                dependants.setdefault(dep, set()).add(name)

    contracts_dir = worktree / "infra" / "contracts"
    missing: list[str] = []
    for svc_name, proc_name, _svc, proc in infra.all_processes():
        on_web = "web" in (proc.networks or [])
        is_dep_target = bool(dependants.get(svc_name))
        if not (on_web or is_dep_target):
            continue  # not a provider
        label = f"{svc_name}.{proc_name}"
        providers.append(label)
        fmt = _infer_contract_format(infra, svc_name)
        candidate = contracts_dir / f"{svc_name}.{proc_name}.{fmt}.yml"
        if candidate.is_file():
            existing.append(candidate)
        else:
            missing.append(f"{label} (expected {candidate.relative_to(worktree)})")

    if missing:
        report.add(
            "contracts_exist",
            False,
            "missing contract(s): " + "; ".join(missing),
        )
    else:
        report.add(
            "contracts_exist",
            True,
            f"{len(existing)} contract(s) present"
            if existing
            else "no provider services — nothing to check",
        )
    return existing, providers


def _gate_health_endpoints(
    worktree: Path,
    ctx: ProjectContext,
    contracts: list[Path],
    report: CheckReport,
) -> None:
    """For each contract on the ``web`` network: assert /health exists;
    for each non-web downstream dependency, /health/<dep> exists too.
    """
    infra = ctx.infra
    if infra is None:
        report.add("health_endpoints", True, "no infra.yml — skipped")
        return

    problems: list[str] = []
    for path in contracts:
        # Derive the codebase key from "api.openapi.yml" → "api".
        # Mod 101: make this right-anchored — under Mod 096's rename the
        # per-process contract filename is "api.web.openapi.yml", and this
        # left-anchored split still yields "api" (a valid core_services key)
        # only because the codebase is the first segment.
        svc = path.name.split(".", 1)[0]
        svc_decl = infra.core_services.get(svc)
        if svc_decl is None:
            continue  # contract for unknown service — skip

        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: malformed YAML ({exc})")
            continue
        paths_map = (doc.get("paths") or {}) if isinstance(doc, dict) else {}

        on_web = any(
            "web" in (p.networks or []) for p in svc_decl.processes.values()
        )
        if on_web:
            health = paths_map.get("/health")
            if not (isinstance(health, dict) and "get" in {k.lower() for k in health}):
                problems.append(
                    f"{path.name}: missing 'GET /health' (required for web-network services)"
                )

        # For each downstream CORE service dependency NOT on the web
        # network, require /health/<dep> to be declared by THIS provider's
        # contract. Per `contracts.md § Health Checks`, only CORE-service
        # downstream deps need a probe endpoint — backing services
        # (postgres, redis, etc.) are excluded. Mod 047 narrowed this
        # from "all non-web" to "core-only" to match the doctrine prose;
        # projects that voluntarily add /health/<backing> endpoints
        # (mirroring the doctrine pattern for backings they care about)
        # remain free to do so.
        svc_deps = sorted({
            dep for p in svc_decl.processes.values() for dep in (p.depends_on or [])
        })
        for dep in svc_deps:
            dep_decl = infra.core_services.get(dep)
            if dep_decl is None:
                # Either not a known service, or a backing — backing
                # services are not required to have a /health/<dep>
                # endpoint on the provider's contract.
                continue
            if any("web" in (p.networks or []) for p in dep_decl.processes.values()):
                continue
            key = f"/health/{dep}"
            hop = paths_map.get(key)
            if not (isinstance(hop, dict) and "get" in {k.lower() for k in hop}):
                problems.append(
                    f"{path.name}: missing 'GET {key}' "
                    f"(required because {svc!r} depends on non-web core {dep!r})"
                )

    if problems:
        report.add(
            "health_endpoints",
            False,
            "; ".join(problems),
        )
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
    for name in sorted(infra.core_services):
        svc = infra.core_services[name]
        # ``extra="allow"`` on ProcessType surfaces role fields like
        # ``health_check_path`` in ``model_extra``; absent ⇒ None. Only
        # ``role: web`` declares the field, but such a process type may sit on
        # a non-``web`` network and still get the curl healthcheck — so do NOT
        # filter on web membership (mod 059).
        #
        # Mod 096: read the PROCESS TYPE. A `getattr(svc, ...)` against the
        # CoreService goes permanently None once the field is process-scoped,
        # so the gate would pass while checking nothing and Mod 051's curl
        # protection would be silently defeated. One image per codebase, so
        # one qualifying entry per codebase — any process type declaring the
        # field obliges the shared image to carry curl.
        declares_hc = any(
            (p.model_extra or {}).get("health_check_path") is not None
            for p in svc.processes.values()
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
    services = core_services(ctx)
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
