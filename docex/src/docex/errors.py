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

    Raised by ``build`` (which needs running dev containers) and by
    ``migrate dev/test`` (which exec into a running container).
    """


class BuildFailed(DocexError):
    """A ``build.sh`` invocation exited zero but left ``dist/`` empty,
    or returned a non-zero exit code."""


class MigrationFailed(DocexError):
    """``migrate.sh`` for a service exited non-zero."""


# ---------------------------------------------------------------------------
# Phase 3 — pipeline-layer errors
# ---------------------------------------------------------------------------


class WorkingTreeDirty(DocexError):
    """``check``/``merge``/``containerize`` invoked with uncommitted changes."""


class BranchNotRebaseable(DocexError):
    """Rebase onto origin/main failed (merge conflicts most likely)."""


class VersionAlreadyReleased(DocexError):
    """A tag ``v<project.version>`` already exists; refuse to overwrite."""


class ContractMissing(DocexError):
    """A required ``infra/contracts/<svc>.<fmt>.yml`` is absent."""


class ContractInvalid(DocexError):
    """A contract file is missing a doctrinally required endpoint."""


class BuildxFailed(DocexError):
    """``docker buildx build`` for a core service exited non-zero."""


class RegistryPushFailed(DocexError):
    """``docker push`` exited non-zero. Usually a credentials problem
    on the host's ``~/.docker/config.json`` mounted by the shim."""


class AnsibleRunFailed(DocexError):
    """``ansible-playbook`` exited non-zero. The playbook output is the
    primary diagnostic; this error is just a clean wrapper for the
    dispatcher."""


class StageTesterBuildFailed(DocexError):
    """Building the ephemeral stage-tester image failed."""


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
    """``docex bootstrap`` couldn't create or reconcile the project's
    OpenTofu state backend (S3 bucket + DynamoDB table)."""


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

    rule: str  # e.g. "rule_7_depends_on_matches_magic_ref"
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
