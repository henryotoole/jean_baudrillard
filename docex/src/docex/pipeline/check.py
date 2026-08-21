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

from docex.cicl.model import (  # noqa: F401
    IMPLEMENTED_CONTRACT_FORMATS,
    CICLDocument,
    CoreService,
    ServiceRef,
)
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import WorkingTreeDirty
from docex.git.client import GitClient
from docex.naming import dns_label
from docex.orchestrate._common import codebases, codebases_with_schema
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

# contract format -> filename extension. Transcribed from contracts.md § Standards,
# which fixes exactly ONE extension per format. All four rows are carried, including
# the two formats `IMPLEMENTED_CONTRACT_FORMATS` excludes: this is the doctrine's
# table, and when `graphql` lands the only edit is one line in model.py.
#
# WHY here and not model.py, where mod 125 put API_STYLE_FORMATS: that table has two
# consumers (validate.py's rule 29 and this module). This one has exactly one, and a
# one-consumer table does not earn a home outside its consumer.
_FORMAT_EXTENSIONS = {
    "openapi": "yml",
    "asyncapi": "yml",
    "graphql": "graphql",
    "proto": "proto",
}

# contract format -> minimum (major, minor) spec version. Transcribed from
# contracts.md § Standards. Only the two versioned formats appear: graphql/proto
# are SDL/IDL with no version key, and are excluded by IMPLEMENTED_CONTRACT_FORMATS
# regardless. Same one-consumer rationale as _FORMAT_EXTENSIONS keeps this here.
_FORMAT_MIN_SPEC_VERSION = {
    "openapi": (3, 2),
    "asyncapi": (3, 0),
}

# Extensions that make a stray file in `infra/contracts/` look like a contract
# somebody meant to author. Used only by the orphan arm of `_gate_contracts`, to
# separate "a contract with the wrong name" from "a README".
_CONTRACT_EXTENSIONS = frozenset({"yml", "yaml", "graphql", "proto"})


def _parse_contract_filename(name: str) -> tuple[str, str, str, str] | None:
    """``"api.web.rest.openapi.yml"`` → ``("api", "web", "rest", "openapi")``.

    Three things fix the shape:

    - Segments are indexed **from the right**, off the extension.
      "Right-anchored" has never meant *take the last four of however many* — the
      count is exact, so ``a.b.c.d.e.openapi.yml`` is ``None``.
    - ``_SERVICE_NAME_RE`` (model.py) admits no dots in a codebase, core-service,
      or surface name, so a canonical contract filename has exactly four stem
      segments and nothing else is a name ``docex`` authored.
    - The extension is checked **against the resolved format** rather than against
      a list of accepted suffixes. That is what narrows ``.yaml`` out (contracts.md
      § Standards fixes one extension per format) and what lets the non-YAML
      formats use this same template instead of being special-cased later.
    """
    stem, sep, ext = name.rpartition(".")
    if not sep:
        return None
    parts = stem.split(".")
    if len(parts) != 4 or not all(p.strip() for p in parts):
        return None
    fmt = parts[-1]
    if fmt not in _FORMAT_EXTENSIONS:
        return None
    if ext != _FORMAT_EXTENSIONS[fmt]:
        return None
    return parts[-4], parts[-3], parts[-2], parts[-1]


@dataclass
class ContractExpectation:
    """One declared surface's expected contract file."""

    codebase: str
    service: str
    surface: str
    fmt: str
    path: Path
    svc: CoreService

    @property
    def dotted(self) -> str:
        return ServiceRef(self.codebase, self.service).dotted


def _expected_contracts(
    infra: CICLDocument, contracts_dir: Path
) -> list[ContractExpectation]:
    """One expectation per declared surface, named from the surface's format.

    Computed once and shared by the two gates that need the same filenames — a
    second copy of the naming expression is a second place for it to drift. Each
    expectation carries the resolved ``CoreService``, so nothing downstream ever
    parses a filename back into a service.
    """
    out: list[ContractExpectation] = []
    for cb_name, svc_name, _cb, svc in infra.all_core_services():
        for surface_name, surface in sorted(svc.surfaces.items()):
            fmts = surface.formats()
            # WHY skip rather than report: rule 29 (`rule_29_mixed_contract_formats`,
            # `rule_29_unknown_api_style`) and `rule_contract_format_not_implemented`
            # already own these at compile time, and a second complaint here would
            # name a filename the author could never have produced. Skipping does
            # not let the project through: `run_check` runs `run_compile` in the same
            # command, so `docex check` still fails — at the compile step, with the
            # message that names the actual problem. That REACHABILITY is what makes
            # the skip honest rather than lax, and
            # `test_check_reaches_compile_when_a_surface_is_skipped` pins it: delete
            # the `run_compile` call from `run_check` and the skip becomes a hole.
            # Same policy `_resolve_service` stated for rule 25: one authoring
            # mistake produces one report.
            if len(fmts) != 1:
                continue
            fmt = next(iter(fmts))
            if fmt not in IMPLEMENTED_CONTRACT_FORMATS:
                continue
            filename = (
                f"{cb_name}.{svc_name}.{surface_name}.{fmt}."
                f"{_FORMAT_EXTENSIONS[fmt]}"
            )
            out.append(
                ContractExpectation(
                    codebase=cb_name,
                    service=svc_name,
                    surface=surface_name,
                    fmt=fmt,
                    path=contracts_dir / filename,
                    svc=svc,
                )
            )
    return out


def _declares_get(paths_map: dict, key: str) -> bool:
    """True iff ``paths_map[key]`` is a mapping carrying a ``get`` operation.

    Case-insensitive on the method key: OpenAPI fixes it lowercase, but a
    hand-authored contract that writes ``GET`` is describing the same route and
    must not fail a gate over casing.
    """
    node = paths_map.get(key)
    return isinstance(node, dict) and "get" in {str(k).lower() for k in node}


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
) -> tuple[list[ContractExpectation], list[str]]:
    """Verify the contracts directory matches the declared surfaces exactly.

    **A core service is a provider iff it declares `surfaces:`** (cicl.md
    § Surfaces). One expected contract file per surface, at
    ``infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>``, in the
    format that surface's `api_styles` resolve to via ``Surface.formats()``.

    The old two-armed ``(core-targeted uses) ∪ (web-network core services)``
    union is deleted, **and the second arm was wrong, not merely redundant**: a
    `web`-network core service that declares no surface now correctly requires
    **no** contract. That is a frontend serving a browser, which
    ``infrastructure.md § Contracts`` uses as its worked example (`frontend.web`
    declares no surface) — the old arm forced a contract onto it.

    WHY the orphan arm exists: an existence-only gate is blind to a half-renamed
    contracts directory *precisely because the new file also exists*, and a
    leftover three-segment ``api.web.openapi.yml`` is the likeliest 2.0.0 upgrade
    mistake in this advance.

    Returns (existing_expectations, providers) — the expectations whose file DOES
    exist, for the next gate to read, and the provider core service refs, dotted.
    """
    infra = ctx.infra
    existing: list[ContractExpectation] = []
    providers: list[str] = []
    if infra is None:
        report.add("contracts_exist", True, "no infra.yml — skipped")
        return existing, providers

    # Read the DECLARED set, not the expectation list: a provider all of whose
    # surfaces were skipped (§ `_expected_contracts`) is still a provider, and
    # deriving this from expectations would make it silently vanish.
    for cb_name, svc_name, _cb, svc in infra.all_core_services():
        if svc.surfaces:
            providers.append(ServiceRef(cb_name, svc_name).dotted)

    contracts_dir = worktree / "infra" / "contracts"
    expected = _expected_contracts(infra, contracts_dir)
    missing: list[str] = []
    for exp in expected:
        if exp.path.is_file():
            existing.append(exp)
        else:
            missing.append(
                f"{exp.dotted} surface {exp.surface!r} "
                f"(expected {exp.path.relative_to(worktree)})"
            )

    unexpected: list[str] = []
    if contracts_dir.is_dir():
        wanted = {e.path.name for e in expected}
        for entry in sorted(contracts_dir.iterdir()):
            name = entry.name
            if not entry.is_file() or name.startswith(".") or name in wanted:
                continue
            looks_like_a_contract = (
                _parse_contract_filename(name) is not None
                or name.rpartition(".")[2] in _CONTRACT_EXTENSIONS
            )
            if looks_like_a_contract:
                unexpected.append(
                    f"{name}: matches no declared surface. The form is "
                    f"<codebase>.<service>.<surface>.<format>.<ext> "
                    f"(e.g. api.web.rest.openapi.yml) — rename it to the surface "
                    f"it describes, or delete it."
                )

    if missing or unexpected:
        clauses: list[str] = []
        if missing:
            clauses.append("missing contract(s): " + "; ".join(missing))
        if unexpected:
            clauses.append("unexpected contract file(s): " + "; ".join(unexpected))
        report.add("contracts_exist", False, "; ".join(clauses))
    else:
        report.add(
            "contracts_exist",
            True,
            (
                f"{len(existing)} contract(s) present"
                if providers
                else "no core service declares a surface — nothing to check"
            ),
        )
    return existing, providers


def _gate_contract_health_path(
    ctx: ProjectContext,
    contracts: list[ContractExpectation],
    report: CheckReport,
) -> None:
    """A `web`-network core service's ``openapi`` contract declares its health path.

    **The rule of record, quoted, because this gate is the one thing that survived
    a deletion order.** ``healthchecks.md § web services also serve GET /health``:
    *"Where a `web`-network core service **also** declares an `openapi` surface,
    `GET /health` is part of that surface and belongs in its contract, which the
    check step asserts as well."* And ``cicd.md § Check Step`` 3.4. This is the
    *narrowed* form of the deleted ``_gate_health_endpoints``' self-health arm,
    written by the same doctrine pass that deleted the fan-out.

    **The path comes from the declared ``health_check_path``, never a hardcoded
    ``/health``.** ``healthchecks.md`` says both, and reading the field is the
    reading that is never wrong — a project declaring ``/healthz`` conforms, and
    hardcoding would fail it.

    **"Any one" openapi surface satisfies it — and this is the reading that keeps
    every contract true.** The doctrine says "an `openapi` surface", singular, and
    does not contemplate two. Requiring the path in *every* openapi surface would
    force a `rest_admin` surface to document a route that is not part of the admin
    boundary — a **false** contract. A contract documenting something outside its
    own boundary is a worse defect than one omitting something documented next
    door.

    **`web`-network membership, not role** — consistent with rule 33, and for the
    same reason: the field is what the reverse proxy reads, and a `role: web` core
    service off the `web` network has no reverse proxy. A non-`web` `openapi`
    provider (internal REST, reached by magic ref, `port` required by rule 32's
    positive arm, `health_check_path` forbidden by rule 33) must **not** declare
    the path in its contract.

    Two skip conditions, neither of them laxity: an absent ``health_check_path``
    on a `web`-network core service is rule 33's to report at compile time, and a
    missing contract file is ``contracts_exist``' to report — so this gate declines
    both rather than double-reporting.
    """
    if ctx.infra is None:
        report.add("contract_health_path", True, "no infra.yml — skipped")
        return

    groups: dict[tuple[str, str], list[ContractExpectation]] = {}
    for exp in contracts:
        if exp.fmt != "openapi":
            continue
        groups.setdefault((exp.codebase, exp.service), []).append(exp)

    problems: list[str] = []
    checked = 0
    for key in sorted(groups):
        group = groups[key]
        svc = group[0].svc
        if "web" not in (svc.networks or []):
            continue
        hcp = (svc.model_extra or {}).get("health_check_path")
        if not isinstance(hcp, str) or not hcp:
            continue
        checked += 1
        satisfied = False
        readable = 0
        searched: list[str] = []
        for exp in group:
            searched.append(exp.path.name)
            try:
                doc = yaml.safe_load(exp.path.read_text()) or {}
            except yaml.YAMLError as exc:
                problems.append(f"{exp.path.name}: malformed YAML ({exc})")
                continue
            readable += 1
            paths_map = (doc.get("paths") or {}) if isinstance(doc, dict) else {}
            if _declares_get(paths_map, hcp):
                satisfied = True
        # A group whose every contract is unreadable already produced one problem
        # per file. Adding "no contract declares GET <path>" on top would report a
        # CONSEQUENCE of the parse failure as if it were a second, independent
        # defect. Where at least one file parsed, the message is earned.
        if not satisfied and readable:
            problems.append(
                f"{ServiceRef(*key).dotted}: no openapi contract declares "
                f"'GET {hcp}' (its declared health_check_path); searched "
                f"{', '.join(searched)}"
            )

    if problems:
        report.add("contract_health_path", False, "; ".join(problems))
    else:
        report.add(
            "contract_health_path",
            True,
            (
                f"'GET <path>' present for {checked} web-network openapi "
                f"provider(s)"
                if checked
                else "no web-network openapi providers — nothing to check"
            ),
        )


def _parse_major_minor(raw: object) -> tuple[int, int] | None:
    """``"3.2.0"`` / ``3.2`` -> ``(3, 2)``; unparseable -> None.

    Accepts a str or a YAML-numeric (an unquoted ``asyncapi: 3.0`` arrives as a
    float). Only major.minor is compared — the patch is irrelevant to the floor.
    """
    if isinstance(raw, (int, float)):
        raw = str(raw)
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _gate_contract_spec_version(
    ctx: ProjectContext,
    contracts: list[ContractExpectation],
    report: CheckReport,
) -> None:
    """Each contract declares a spec version at or above the doctrine floor.

    contracts.md § Standards fixes OpenAPI >= 3.2 and AsyncAPI >= 3.0 — each floor
    is what makes a promised api_style implementable (openapi 3.2 -> itemSchema for
    `stream`; asyncapi 3.0 -> reply for `rpc`). The version key each format declares
    in its own root is the same token as the format name (`openapi:` / `asyncapi:`).

    A malformed or absent version key is reported once, as its own defect — NOT
    also reported as a below-floor consequence it cannot compute, matching
    `_gate_contract_health_path`'s handling of unreadable YAML.
    """
    if ctx.infra is None:
        report.add("contract_spec_version", True, "no infra.yml — skipped")
        return

    problems: list[str] = []
    checked = 0
    for exp in contracts:
        floor = _FORMAT_MIN_SPEC_VERSION.get(exp.fmt)
        if floor is None:
            continue
        try:
            doc = yaml.safe_load(exp.path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{exp.path.name}: malformed YAML ({exc})")
            continue
        raw = doc.get(exp.fmt) if isinstance(doc, dict) else None
        parsed = _parse_major_minor(raw)
        if parsed is None:
            problems.append(
                f"{exp.path.name}: no readable {exp.fmt!r} version key "
                f"(found {raw!r}); expected >= {floor[0]}.{floor[1]}"
            )
            continue
        checked += 1
        if parsed < floor:
            problems.append(
                f"{exp.path.name}: declares {exp.fmt} "
                f"{parsed[0]}.{parsed[1]}, but the doctrine floor is "
                f"{floor[0]}.{floor[1]} (contracts.md § Standards)"
            )

    if problems:
        report.add("contract_spec_version", False, "; ".join(problems))
    else:
        report.add(
            "contract_spec_version",
            True,
            (
                f"{checked} contract(s) meet the spec-version floor"
                if checked
                else "no versioned contracts — nothing to check"
            ),
        )


def _gate_codebase_scripts(
    worktree: Path,
    ctx: ProjectContext,
    report: CheckReport,
) -> None:
    """``build.sh``, ``test.sh`` and ``health.sh`` for every codebase;
    ``migrate.sh`` for any codebase that's a schema owner.

    `health.sh` is invoked **per core service**, as ``./health.sh <service>`` —
    the compiler supplies the argv (cicd.md § Check Step 3.1). That changes
    nothing here (one file per codebase either way), which is exactly why it is
    worth saying: `build.sh`/`test.sh`/`migrate.sh` are properties of the source
    tree and so codebase-scoped, while health is a property of a running process.
    A reader who knows the argv exists would otherwise expect a per-core-service
    check in this gate and find none.
    """
    problems: list[str] = []
    all_codebases = codebases(ctx)
    schema_owners = set(codebases_with_schema(ctx))

    for cb in all_codebases:
        cb_root = worktree / "core" / cb
        for script in ("build.sh", "test.sh", "health.sh"):
            path = cb_root / script
            if not path.is_file():
                problems.append(f"core/{cb}/{script} missing")
            elif not _is_executable(path):
                problems.append(f"core/{cb}/{script} not executable")
        if cb in schema_owners:
            mpath = cb_root / "migrate.sh"
            if not mpath.is_file():
                problems.append(f"core/{cb}/migrate.sh missing")
            elif not _is_executable(mpath):
                problems.append(f"core/{cb}/migrate.sh not executable")

    if problems:
        report.add("codebase_scripts", False, "; ".join(problems))
    else:
        report.add(
            "codebase_scripts",
            True,
            f"build.sh/test.sh/health.sh present for {len(all_codebases)} "
            f"codebase(s)",
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

    # 2. Fetch (only when an origin remote exists) ----------------------
    # A fetch *failure* is fatal here, exactly as it is in `merge` (which runs
    # `check` defensively first). `check` exists to predict whether `merge` will
    # succeed; if `merge` would die at `git fetch origin` — a path-scoped
    # credential helper, or a genuine network/auth failure — `check` must not
    # report green. Downgrading it to a warning let a failed fetch masquerade as
    # an empty origin/main and misfire first-release mode (mod 136). A repo with
    # no `origin` (the test projects) skips the fetch and does NOT error.
    if git.remote_exists(project_root, "origin"):
        rc = git.fetch(project_root, remote="origin")
        if rc != 0:
            print(
                f"error: 'git fetch origin' exited {rc}; cannot verify against "
                "the trunk. `docex merge` would fail at the same fetch — resolve "
                "git credentials/network and retry.",
                file=sys.stderr,
            )
            return rc
    else:
        print(
            "check: no 'origin' remote — comparing against local trunk only.",
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
        _gate_contract_health_path(worktree_ctx, contracts, report)
        _gate_contract_spec_version(worktree_ctx, contracts, report)
        _gate_codebase_scripts(worktree, worktree_ctx, report)
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
