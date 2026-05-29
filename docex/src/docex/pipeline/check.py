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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from docex.cicl.model import CICLDocument  # noqa: F401 - typed in helpers
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import WorkingTreeDirty
from docex.git.client import GitClient
from docex.orchestrate._common import core_services, services_with_schema


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
# Version-comparison helper (semver-ish, sufficient for project.yml).
# ---------------------------------------------------------------------------


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a tuple of ints for comparison.

    Non-numeric segments fall back to 0 — we don't need a full
    PEP 440 / semver parser, only enough to order ``0.1.0`` < ``0.1.1``.
    """
    parts: list[int] = []
    for seg in v.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            # Strip any pre-release suffix (e.g. "1-rc1") — best effort.
            digits = "".join(ch for ch in seg if ch.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)


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
        if service in (consumer.depends_on or []):
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
    cmp_ok = _parse_version(new_version) > _parse_version(main_version)
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

    A core service is a "provider" iff at least one other core service
    has it in ``depends_on``. Providers must ship a contract file at
    ``infra/contracts/<svc>.<fmt>.yml``.

    Returns (existing_contracts, providers) — the contract paths that
    DO exist, for the next gate to scan, and the list of provider
    service names (for downstream-chain logic).
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
    dependants: dict[str, set[str]] = {}
    for name, svc in infra.core_services.items():
        for dep in (svc.depends_on or []):
            dependants.setdefault(dep, set()).add(name)

    contracts_dir = worktree / "infra" / "contracts"
    missing: list[str] = []
    for name in sorted(infra.core_services):
        svc = infra.core_services[name]
        on_web = "web" in (svc.networks or [])
        is_dep_target = bool(dependants.get(name))
        if not (on_web or is_dep_target):
            continue  # not a provider
        providers.append(name)
        fmt = _infer_contract_format(infra, name)
        candidate = contracts_dir / f"{name}.{fmt}.yml"
        if candidate.is_file():
            existing.append(candidate)
        else:
            missing.append(f"{name} (expected {candidate.relative_to(worktree)})")

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
        # Derive simple service name from "api.openapi.yml" → "api".
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

        on_web = "web" in (svc_decl.networks or [])
        if on_web:
            health = paths_map.get("/health")
            if not (isinstance(health, dict) and "get" in {k.lower() for k in health}):
                problems.append(
                    f"{path.name}: missing 'GET /health' (required for web-network services)"
                )

        # For each downstream dependency NOT on the web network, require
        # /health/<dep> to be declared by THIS provider's contract.
        for dep in (svc_decl.depends_on or []):
            dep_decl = (
                infra.core_services.get(dep)
                or infra.backing_services.get(dep)
            )
            if dep_decl is None:
                continue
            if "web" in (dep_decl.networks or []):
                continue
            key = f"/health/{dep}"
            hop = paths_map.get(key)
            if not (isinstance(hop, dict) and "get" in {k.lower() for k in hop}):
                problems.append(
                    f"{path.name}: missing 'GET {key}' "
                    f"(required because {svc!r} depends on non-web {dep!r})"
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


# ---------------------------------------------------------------------------
# Worktree management.
# ---------------------------------------------------------------------------


def _make_temp_branch(feature: str) -> str:
    """Encode the feature branch + a timestamp so concurrent ``check``
    invocations on the same feature don't collide.
    """
    safe = feature.replace("/", "-").replace(":", "-")
    return f"docex-check/{safe}-{int(time.time())}"


def _worktree_path_for(project_root: Path, short_sha: str) -> Path:
    return project_root / ".docex" / "worktrees" / f"check-{short_sha}"


def _cleanup_worktree(
    project_root: Path,
    worktree: Path,
    temp_branch: str,
    git: GitClient,
) -> None:
    """Remove the worktree and delete the temp branch, swallowing
    errors so cleanup never masks the underlying check failure.

    Build steps leave behind untracked files inside the worktree
    (`.terraform/`, `dist/`, etc.) that ``git worktree remove`` refuses
    by default. We go straight to ``--force``; it skips git's
    "modified or untracked" check. If git still can't remove the
    worktree (some other edge case), fall back to ``shutil.rmtree`` —
    cleanup is best-effort.
    """
    if not worktree.exists():
        # Nothing to remove.
        return
    rc = git.worktree_remove(project_root, worktree, force=True)
    if rc != 0 and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
        # Tell git to forget the worktree entry even though we removed
        # the directory under its feet — otherwise `git worktree list`
        # leaves a stale entry pointing at a missing path.
        git.worktree_prune(project_root)
    # Best-effort temp-branch delete; if the worktree already moved
    # off it, this can fail harmlessly.
    git.delete_branch(project_root, temp_branch, remote=False)


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
    worktree = _worktree_path_for(project_root, short_sha)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    temp_branch = _make_temp_branch(feature)

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

        # If any gate failed, surface aggregated report and stop.
        if not report.all_passed:
            print(_aggregate_check_report(report))
            return 1

        # 6. Build everything --------------------------------------------
        from docex.cicl.compile import run_compile
        from docex.orchestrate._common import compose_file_for, env_file_for

        rc = run_compile(worktree_ctx)
        if rc != 0:
            print(
                f"error: 'docex compile' against worktree exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # Secret files are gitignored, so the worktree doesn't have
        # them — use the MAIN project's env file for variable
        # substitution. Build doesn't need real values; this just
        # silences "${VAR} not set" warnings that otherwise drown the
        # real build output.
        env_file = env_file_for(ctx, "test")

        # Override compose's --project-directory to the worktree path
        # so build contexts and bind-mounts resolve against the
        # worktree tree, not the main project tree.
        compose_path = compose_file_for(worktree_ctx, "test")
        # Use compose_up with build=True then immediately down; we want
        # to confirm `docker build` succeeds without leaving containers
        # around. Easier: a dedicated compose build step.
        rc = _compose_build(docker, compose_path, env_file, worktree)
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
        _cleanup_worktree(project_root, worktree, temp_branch, git)


def _compose_build(
    docker: DockerClient,
    compose_file: Path,
    env_file: Path | None,
    project_dir: Path | None = None,
) -> int:
    """Trigger ``docker compose build`` via the DockerClient abstraction.

    The Phase 2 DockerClient doesn't have a dedicated ``compose_build``
    method, but ``compose_up(build=True, detach=True)`` followed by
    ``compose_down`` accomplishes the same: it builds everything and
    then tears down. We use that pattern so all docker invocations
    still go through the abstraction.
    """
    rc = docker.compose_up(
        compose_file,
        build=True,
        detach=True,
        env_file=env_file,
        project_dir=project_dir,
    )
    # Down regardless — we just wanted the build step.
    docker.compose_down(
        compose_file, preserve_volumes=False,
        env_file=env_file, project_dir=project_dir,
    )
    return rc


# Re-export for use by ``merge`` (which re-runs check defensively).
__all__ = ["run_check", "CheckReport", "CheckResult"]
