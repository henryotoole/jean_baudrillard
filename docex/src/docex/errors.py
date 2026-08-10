"""Shared exception types and formatted error reporting for docex.

Errors raised from the compiler/loader propagate up to ``__main__.py``,
where they are caught and rendered as concise, traceback-free messages
unless ``--debug`` is set.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from rich.console import Console


class DocexError(Exception):
    """Base type for all docex-controlled errors.

    Anything raised that is NOT a subclass of this should produce a real
    Python traceback (so we can find bugs); anything that IS a subclass
    is a user-facing error and gets a clean one-line message unless
    ``--debug`` is set.
    """


class ProjectNotFoundError(DocexError):
    """No ``project.yml`` found walking up from cwd."""


class ProjectManifestError(DocexError):
    """``project.yml`` is malformed."""


class InfraFileError(DocexError):
    """``infra/infra.yml`` is missing or malformed."""


class TransferTableError(DocexError):
    """A transfer table file is malformed or contradictory."""


class SubstitutionError(DocexError):
    """Substitution failed (undefined ${var}, magic ref to a missing
    service, etc.)."""


class HCLInFixedError(SubstitutionError):
    """An ``@<expr>`` syntax appears in a template that is being compiled
    for a fixed-foundation target."""


# ---------------------------------------------------------------------------
# Phase 2 — orchestrate-layer errors
# ---------------------------------------------------------------------------


class DockerNotAvailable(DocexError):
    """``docker info`` failed — the daemon isn't reachable.

    Raised by the dispatcher before any Phase 2 command runs. The shim
    bind-mounts ``/var/run/docker.sock``; if that's missing or the
    daemon isn't running, the user gets a clean error rather than a
    deep stack trace from inside compose.
    """


class EnvNotSupported(DocexError):
    """A command was given an environment name it can't handle.

    ``up``, ``down``, ``build``, and ``migrate`` (dev/test paths)
    require a fixed env. Stage/prod go through Phase 3's ``release``.
    """


class EnvNotRunning(DocexError):
    """The named env's compose stack is not up.

    Raised by ``build``, which needs running dev containers to run
    ``build.sh`` against the bind-mounted source. NOT raised by
    ``migrate dev/test``: since mod 099 that path runs a one-off container
    rather than exec-ing into a running one, so it does not require the
    stack to be up.
    """


class BuildFailed(DocexError):
    """A ``build.sh`` invocation exited zero but left ``dist/`` empty,
    or returned a non-zero exit code."""


class MigrationFailed(DocexError):
    """``migrate.sh`` for a service exited non-zero.

    **Currently unraised — nothing in docex constructs this.** Kept because it
    is exported. A migration failure surfaces by RETURN CODE, not by this
    exception: ``dev``/``test`` and fixed ``stage``/``prod`` both print to
    stderr and propagate a non-zero rc out of ``orchestrate/migrate.py``, and
    the elastic path raises ``ECSTaskFailed`` instead. Do not add a
    ``raise MigrationFailed`` to those paths on the strength of this class
    existing — their callers read rc.
    """


class AggregationError(DocexError):
    """Aggregation (``TTE ∪ secrets ∪ config``) failed.

    Covers an unsupported env for the current mod's aggregation surface
    and the defensive cross-source key-collision check (rule 20
    disjointness is guaranteed at compile, so a collision here is a bug)."""


# ---------------------------------------------------------------------------
# Phase 3 — pipeline-layer errors
# ---------------------------------------------------------------------------


class WorkingTreeDirty(DocexError):
    """``check``/``merge``/``containerize`` invoked with uncommitted changes."""


class RollbackPreconditionFailed(DocexError):
    """A precondition for ``docex rollback`` failed; no env state was touched.

    Covers branch / tag / version-range / image-existence preconditions.
    The doctrine commits to a narrow-window rollback — if any of these
    fail, the operator is expected to fix forward, not rollback further.
    """


class BranchNotRebaseable(DocexError):
    """Rebase onto origin/main failed (merge conflicts most likely)."""


class VersionAlreadyReleased(DocexError):
    """A tag ``v<project.version>`` already exists; refuse to overwrite."""


class ContractMissing(DocexError):
    """A required contract file is absent.

    One per declared surface, at
    ``infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>``.
    """


class ContractInvalid(DocexError):
    """A contract file is missing a doctrinally required endpoint.

    There is exactly one such endpoint: a `web`-network core service's declared
    ``health_check_path``, in its ``openapi`` surface's contract. That is
    ``docex check``'s ``contract_health_path`` gate, which reports through
    ``CheckReport`` rather than raising this.
    """


class BuildxFailed(DocexError):
    """``docker buildx build`` for a codebase exited non-zero."""


class RegistryPushFailed(DocexError):
    """``docker push`` exited non-zero. Usually a credentials problem
    on the host's ``~/.docker/config.json`` mounted by the shim."""


class AnsibleRunFailed(DocexError):
    """``ansible-playbook`` exited non-zero. The playbook output is the
    primary diagnostic; this error is just a clean wrapper for the
    dispatcher."""


class RequiredSecretsUnset(DocexError):
    """A stage/prod release was attempted while one or more required secrets
    are unset (absent or empty) in infra/secrets/<env>.env. Raised as a
    precondition in run_release, before any side effect. See
    config_and_secrets.md § Required-Secret Guard."""

    def __init__(self, env: str, keys: list[str]) -> None:
        self.env = env
        self.keys = keys
        listing = "\n".join(f"  - {k}   (docex secrets set {env} {k})" for k in keys)
        super().__init__(
            f"release aborted — {len(keys)} required secret(s) unset for "
            f"{env!r}:\n{listing}\n"
            f"Set them (or run `docex secrets scaffold {env}` to reconcile the "
            f"key set first), then retry."
        )


class StageTesterBuildFailed(DocexError):
    """Building the ephemeral stage-tester image failed."""


class DeployedServiceUnhealthy(DocexError):
    """The orchestrator answered, and the answer is bad.

    A deployed core service is not healthy, is not running, or is not on the
    version under test. Raised by ``stagetest``'s orchestrator pre-step (mod
    128). Rule of record: ``healthchecks.md § Version`` — the orchestrator's
    aggregated state and the deployment record are the truth, never a probe's
    stdout.

    Paired with ``OrchestratorStateUnreadable``. **These are two types and not
    one on purpose.** The operator's next move differs — "the release is bad,
    look at the service" vs. "the question was never answered, look at docex or
    your credentials" — but the load-bearing reason is narrower: keeping them
    separate makes "the gate broke" *untypeable* as "the env is fine". With one
    type, a test written for the honest failure would pass when the gate merely
    failed to read anything, which is the exact defect mod 128 exists to close.
    """


class OrchestratorStateUnreadable(DocexError):
    """docex could not obtain an answer about the deployed env at all.

    Unreachable host, absent cluster or service, an inconsistent task set, an
    unreadable task-definition revision, garbled ``docker inspect`` output, an
    image that declares no healthcheck, or an image ref with no readable tag.

    This class exists so that *not knowing* can never be reported as health.
    See ``DeployedServiceUnhealthy`` above for why the split is two types, and
    ``healthchecks.md § Version`` plus mod 128's overview
    (§ *Every way this step could fail to be able to answer*) for the full
    enumeration of modes that land here.
    """


class TagMissing(DocexError):
    """``containerize`` was invoked before ``docex merge`` tagged the
    release. The expected ``v<version>`` tag is not present on HEAD."""


# ---------------------------------------------------------------------------
# Phase 4 — AWS + OpenTofu errors
# ---------------------------------------------------------------------------


class AWSCredentialsMissing(DocexError):
    """No AWS credentials are reachable. ``~/.aws/credentials`` is the
    doctrine-prescribed source; CI runners may supply env vars instead.
    Either way, boto3 couldn't find any."""


class BootstrapFailed(DocexError):
    """``docex projinfra up production`` couldn't create or reconcile the
    project's OpenTofu state backend (S3 bucket + DynamoDB table). The verb
    was ``docex bootstrap`` before mod 034; the internal step is still called
    bootstrap (``pipeline/bootstrap.py::run_bootstrap``)."""


class SSMPushFailed(DocexError):
    """A failure occurred while pushing secrets from
    ``infra/secrets/<env>.env`` to SSM Parameter Store during a
    release. The release is aborted before any tofu apply happens."""


class ECSTaskFailed(DocexError):
    """An ECS RunTask (migration) failed: the task didn't reach
    STOPPED within the timeout, the container exited non-zero, or
    Fargate refused to start it at all."""


class TofuValidateFailed(DocexError):
    """``tofu validate`` exited non-zero. The HCL emitter produced
    something that OpenTofu refuses to parse or type-check."""


class TofuApplyFailed(DocexError):
    """``tofu apply`` exited non-zero. The state file is authoritative —
    no automatic rollback is attempted; the operator is expected to
    inspect via ``tofu plan`` and re-run."""


@dataclass
class ValidationIssue:
    """A single validation problem detected during compile."""

    rule: str  # e.g. "rule_7_magic_ref_implies_uses"
    message: str  # human-readable
    where: str | None = None  # optional path/context hint

    def render(self) -> str:
        prefix = f"[{self.rule}]"
        if self.where:
            return f"{prefix} {self.where}: {self.message}"
        return f"{prefix} {self.message}"


class ValidationError(DocexError):
    """One or more validation rules failed.

    Carries the full list of issues so the developer can see everything
    that's wrong in a single compile cycle (per the spec).
    """

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__(self.render())

    def render(self) -> str:
        lines = [f"validation failed ({len(self.issues)} issue(s)):"]
        for issue in self.issues:
            lines.append(f"  - {issue.render()}")
        return "\n".join(lines)


@dataclass
class ErrorReporter:
    """Centralized error printing. Honors a ``--debug`` flag."""

    debug: bool = False
    console: Console = field(default_factory=lambda: Console(stderr=True))

    def report(self, exc: BaseException) -> int:
        """Print the exception. Return the appropriate process exit code."""
        if isinstance(exc, ValidationError):
            self.console.print(f"[red]{exc.render()}[/red]")
            return 1
        if isinstance(exc, DocexError):
            self.console.print(f"[red]error:[/red] {exc}")
            if self.debug:
                self.console.print_exception(show_locals=False)
            return 1
        # Truly unexpected — always show the traceback.
        self.console.print(f"[red]internal error:[/red] {exc}")
        self.console.print_exception(show_locals=False)
        return 2


def die(msg: str, code: int = 1, *, console: Console | None = None) -> "type[SystemExit]":  # pragma: no cover - thin wrapper
    """Helper for one-off fatal exits from CLI code."""
    (console or Console(stderr=True)).print(f"[red]error:[/red] {msg}")
    sys.exit(code)
