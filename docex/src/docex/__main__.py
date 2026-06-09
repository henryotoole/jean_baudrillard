"""CLI entrypoint for docex.

The dispatcher exposes the doctrine-defined command surface. Commands
are grouped in ``--help`` by purpose (Introspection / Infrastructure /
Development / Pipeline / Reference) matching the doctrine's
``docex.md`` provided-tools table.

See ``plans/core/masterplan.md`` § Subcommand Surface for the complete list.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from docex import __version__
from docex.errors import DocexError, ErrorReporter


# ---------------------------------------------------------------------------
# Subcommand registry
# ---------------------------------------------------------------------------

_HELP_TEXT: dict[str, str] = {
    "compile": "Translate infra.yml into per-env infra config (compose / HCL).",
    "describe": "Show an environment's infrastructure (DAG or LLM-JSON).",
    "why": "Explain why doctrine handles a resource the way it does.",
    "roles": "List the available service roles (with descriptions).",
    "role": "Describe a role: engines, provided parts, env vars, fields.",
    "preinfra": "Check prerequisite infrastructure for a side (development | production).",
    "projinfra": "Bring up or tear down project-tier infrastructure for a side.",
    "envinfra": "Bring up or tear down a local dev or test environment.",
    "build": "Refresh dist/ for one or all core services.",
    "test": "Run build-time tests in a fresh test env.",
    "migrate": "Apply database migrations against an env.",
    "check": "Run CI gate checks in an ephemeral worktree.",
    "merge": "Rebase + fast-forward + tag + push.",
    "containerize": "Build and push core service prod images.",
    "release": "Deploy the containerized build to stage or prod.",
    "stagetest": "Run staging tests against the deployed stage env.",
    "rollback": "Roll a deployed env back to a prior version (narrow-window emergency).",
}


# Purpose-based grouping for ``--help`` output. Order matches the doctrine
# ``docex.md`` § Provided Tools table; the dispatcher itself doesn't depend
# on this grouping.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Introspection", ("compile", "describe", "why", "roles", "role")),
    ("Infrastructure", ("preinfra", "projinfra", "envinfra")),
    ("Development", ("build", "test", "migrate")),
    ("Pipeline", ("check", "merge", "containerize", "release",
                  "stagetest", "rollback")),
)


# ---------------------------------------------------------------------------
# Usage / help
# ---------------------------------------------------------------------------


def _format_usage() -> str:
    lines = [
        f"docex {__version__} — executor of the doctrine",
        "",
        "usage: docex [--debug] <command> [args...]",
        "",
        "commands:",
    ]

    def _group(title: str, cmds: tuple[str, ...]) -> None:
        lines.append(f"  {title}:")
        for cmd in cmds:
            help_ = _HELP_TEXT.get(cmd, "")
            lines.append(f"    {cmd:<13} {help_}")

    for title, cmds in _GROUPS:
        _group(title, cmds)
    lines.append("")
    lines.append("global options:")
    lines.append("  --debug    Show full Python tracebacks on errors.")
    lines.append("  --version  Print version and exit.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Introspection handlers
# ---------------------------------------------------------------------------


def _cmd_compile(args: list[str]) -> int:
    """``docex compile`` — compile infra.yml to per-env outputs."""
    parser = argparse.ArgumentParser(prog="docex compile", add_help=True)
    # No positional args; compile always emits all envs.
    parser.parse_args(args)

    # Import lazily so the dispatcher itself stays light.
    from docex.cicl.compile import run_compile
    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))
    return run_compile(ctx)


def _cmd_describe(args: list[str]) -> int:
    """``docex describe [<env>] [--format dag|llm]``."""
    parser = argparse.ArgumentParser(prog="docex describe", add_help=True)
    parser.add_argument("env", nargs="?", default="prod",
                        choices=["dev", "test", "stage", "prod"],
                        help="environment to describe (default: prod)")
    parser.add_argument("--format", default="dag",
                        choices=["dag", "llm"],
                        help="output format (default: dag)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.describe import run_describe

    ctx = load_project_context(Path(os.getcwd()))
    return run_describe(ctx, env=ns.env, fmt=ns.format)


def _cmd_why(args: list[str]) -> int:
    """``docex why <resource>``."""
    parser = argparse.ArgumentParser(prog="docex why", add_help=True)
    parser.add_argument("resource", nargs="?",
                        help="resource to explain (run with no arg to list)")
    ns = parser.parse_args(args)

    from docex.why.catalog import run_why

    return run_why(ns.resource)


# ---------------------------------------------------------------------------
# Infrastructure handlers (preinfra / projinfra / envinfra)
# ---------------------------------------------------------------------------


def _require_docker() -> "object":
    """Build a SubprocessDockerClient and ensure docker is reachable.

    Returns the client. Raises ``DockerNotAvailable`` if not — the
    dispatcher catches it and renders a clean error via ErrorReporter.
    """
    from docex.docker import SubprocessDockerClient
    from docex.errors import DockerNotAvailable

    client = SubprocessDockerClient()
    if not client.is_available():
        raise DockerNotAvailable(
            "docker daemon is not reachable. Is dockerd running, and "
            "is /var/run/docker.sock bind-mounted into the docex "
            "container? (See bin/docex shim.)"
        )
    return client


def _cmd_envinfra(args: list[str]) -> int:
    """``docex envinfra <direction> <env>`` — bring up or tear down a
    local dev / test environment. Dev/test only; stage/prod go via
    `release`."""
    parser = argparse.ArgumentParser(prog="docex envinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("env", choices=["dev", "test"],
                        help="environment (dev or test)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()

    if ns.direction == "up":
        from docex.orchestrate.up import run_up
        return run_up(ctx, docker, env=ns.env)
    else:
        from docex.orchestrate.down import run_down
        return run_down(ctx, docker, env=ns.env)


def _cmd_preinfra(args: list[str]) -> int:
    """``docex preinfra <side>`` — check prerequisite infrastructure
    for the given side. STUB in mod 034 — real checks land in mod 042."""
    parser = argparse.ArgumentParser(prog="docex preinfra", add_help=True)
    parser.add_argument("side", choices=["development", "production"],
                        help="side to check (development or production)")
    ns = parser.parse_args(args)

    print(f"preinfra check (stub): {ns.side} side — "
          f"real checks land in mod 042. Returning success.")
    return 0


def _cmd_projinfra(args: list[str]) -> int:
    """``docex projinfra <direction> <side>`` — bring up or tear down
    project-tier infrastructure for a side. Mostly STUB in mod 034.
    The only real behavior is `projinfra up production` on elastic
    projects, which runs the existing state-backend setup (formerly
    the `bootstrap` command). Mods 036 (fixed) and 037-039 (elastic)
    flesh out the rest."""
    parser = argparse.ArgumentParser(prog="docex projinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("side", choices=["development", "production"],
                        help="side (development or production)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))

    # Elastic + up + production: run the existing state-backend setup.
    if (ctx.infra.foundation == "elastic"
            and ns.direction == "up"
            and ns.side == "production"):
        from docex.pipeline.bootstrap import run_bootstrap
        aws = _make_aws_client()
        return run_bootstrap(ctx, aws)

    print(f"projinfra {ns.direction} {ns.side} (stub): "
          f"real behavior lands in mod 036 (fixed) or mods 037-039 "
          f"(elastic). Returning success.")
    return 0


# ---------------------------------------------------------------------------
# Development handlers (build / test / migrate)
# ---------------------------------------------------------------------------


def _cmd_build(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex build", add_help=True)
    parser.add_argument("service", nargs="?", default=None,
                        help="core service to build (omit to build all)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.orchestrate.build import run_build

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    return run_build(ctx, docker, service=ns.service)


def _cmd_test(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex test", add_help=True)
    parser.parse_args(args)  # no positional args

    from docex.context import load_project_context
    from docex.orchestrate.test import run_test

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    return run_test(ctx, docker)


def _cmd_migrate(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex migrate", add_help=True)
    parser.add_argument("env", choices=["dev", "test", "stage", "prod"],
                        help="environment to migrate")
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.orchestrate.migrate import run_migrate

    ctx = load_project_context(Path(os.getcwd()))
    # dev/test always need docker. Stage/prod on fixed drives ansible;
    # stage/prod on elastic drives ECS RunTask via AWSClient. Wire every
    # dependency; ``run_migrate`` picks the ones it needs.
    if ns.env in ("dev", "test"):
        docker = _require_docker()
    else:
        # The stage/prod paths don't touch docker directly. Pass a
        # no-op docker so the function's uniform signature is honored.
        from docex.docker import SubprocessDockerClient
        docker = SubprocessDockerClient()
    from docex.ansible import run_playbook
    # AWSClient is needed only for the elastic stage/prod path; pass
    # one in unconditionally — Boto3AWSClient is cheap to construct and
    # never touches AWS until a method is called.
    aws = _make_aws_client()
    return run_migrate(
        ctx, docker, env=ns.env, ansible_runner=run_playbook, aws=aws,
    )


# ---------------------------------------------------------------------------
# Pipeline handlers (check / merge / containerize / release / stagetest / rollback)
# ---------------------------------------------------------------------------


def _require_git() -> "object":
    """Return a SubprocessGitClient. No availability probe — git is
    expected to be present in the image since Phase 3."""
    from docex.git import SubprocessGitClient

    return SubprocessGitClient()


def _make_aws_client() -> "object":
    """Construct a ``Boto3AWSClient``.

    Construction is cheap and offline — boto3 doesn't probe credentials
    until a method is called. So we always build one; the dispatcher
    threads it through even for handlers that may not use it (fixed
    foundation, dev/test envs), where it stays unused.
    """
    from docex.aws import Boto3AWSClient

    return Boto3AWSClient()


def _cmd_check(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex check", add_help=True)
    parser.parse_args(args)  # no positional args

    from docex.context import load_project_context
    from docex.pipeline.check import run_check

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    return run_check(ctx, docker, git)


def _cmd_merge(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex merge", add_help=True)
    parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.merge import run_merge

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    return run_merge(ctx, docker, git)


def _cmd_containerize(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex containerize", add_help=True)
    parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.containerize import run_containerize

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    # aws is used only on the elastic ECR-default path; cheap to construct
    # and never touches AWS until a method is called.
    aws = _make_aws_client()
    return run_containerize(ctx, docker, git, aws=aws)


def _cmd_release(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex release", add_help=True)
    parser.add_argument("env", choices=["dev", "test", "stage", "prod"],
                        help="environment to release to (stage or prod)")
    ns = parser.parse_args(args)

    from docex.ansible import run_playbook
    from docex.context import load_project_context
    from docex.opentofu import tofu_apply, tofu_init
    from docex.pipeline.release import run_release

    ctx = load_project_context(Path(os.getcwd()))
    # Thread every transport ``run_release`` may need. The fixed branch
    # ignores ``aws`` / ``tofu_*``; the elastic branch ignores
    # ``ansible_runner``. The function dispatches on foundation.
    aws = _make_aws_client()
    return run_release(
        ctx,
        env=ns.env,
        ansible_runner=run_playbook,
        aws=aws,
        tofu_init=tofu_init,
        tofu_apply=tofu_apply,
    )


def _cmd_stagetest(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex stagetest", add_help=True)
    parser.add_argument(
        "--staging-url",
        default=None,
        help="override STAGING_URL (defaults to https://stage.<domain>)",
    )
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.stagetest import run_stagetest

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    return run_stagetest(ctx, docker, staging_url_override=ns.staging_url)


def _cmd_rollback(args: list[str]) -> int:
    """``docex rollback <env> <target_version> [--dry-run]`` — emergency
    reversion to a prior version. Code-only, at most one minor back."""
    parser = argparse.ArgumentParser(prog="docex rollback", add_help=True)
    parser.add_argument("env", choices=["stage", "prod"],
                        help="environment to roll back (stage or prod)")
    parser.add_argument("target_version",
                        help="version to roll back to (without the 'v' prefix)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without applying")
    ns = parser.parse_args(args)

    from docex.ansible import run_playbook
    from docex.context import load_project_context
    from docex.opentofu import tofu_apply, tofu_init, tofu_plan
    from docex.pipeline.rollback import run_rollback

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    aws = _make_aws_client()
    return run_rollback(
        ctx,
        env=ns.env,
        target_version=ns.target_version,
        docker=docker,
        git=git,
        aws=aws,
        ansible_runner=run_playbook,
        tofu_init=tofu_init,
        tofu_apply=tofu_apply,
        tofu_plan=tofu_plan,
        dry_run=ns.dry_run,
    )


# ---------------------------------------------------------------------------
# Reference handlers (roles / role)
# ---------------------------------------------------------------------------


def _load_tables_best_effort() -> "object":
    """Load transfer tables, including project-local extensions when a
    ``project.yml`` is found by walking up from cwd. Falls back to the
    bundled tables when not inside a project — the role/parts catalog is
    reference info that should be queryable anywhere."""
    from docex.cicl.transfer import load_transfer_tables
    from docex.context import _find_project_root
    from docex.errors import ProjectNotFoundError

    try:
        root = _find_project_root(Path(os.getcwd()))
    except ProjectNotFoundError:
        root = None
    return load_transfer_tables(root)


def _cmd_roles(args: list[str]) -> int:
    """``docex roles [--format text|llm]`` — list available roles."""
    parser = argparse.ArgumentParser(prog="docex roles", add_help=True)
    parser.add_argument("--format", default="text", choices=["text", "llm"],
                        help="output format (default: text)")
    ns = parser.parse_args(args)

    from docex.roles import list_roles

    return list_roles(_load_tables_best_effort(), fmt=ns.format)


def _cmd_role(args: list[str]) -> int:
    """``docex role <name> [--format text|llm]`` — describe one role."""
    parser = argparse.ArgumentParser(prog="docex role", add_help=True)
    parser.add_argument("role", help="role to describe (e.g. relational_db)")
    parser.add_argument("--format", default="text", choices=["text", "llm"],
                        help="output format (default: text)")
    ns = parser.parse_args(args)

    from docex.roles import describe_role

    return describe_role(_load_tables_best_effort(), ns.role, fmt=ns.format)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _build_handler_table() -> dict[str, Callable[[list[str]], int]]:
    # Ordered to mirror the ``_GROUPS`` purpose-based help grouping.
    return {
        # Introspection
        "compile": _cmd_compile,
        "describe": _cmd_describe,
        "why": _cmd_why,
        "roles": _cmd_roles,
        "role": _cmd_role,
        # Infrastructure
        "preinfra": _cmd_preinfra,
        "projinfra": _cmd_projinfra,
        "envinfra": _cmd_envinfra,
        # Development
        "build": _cmd_build,
        "test": _cmd_test,
        "migrate": _cmd_migrate,
        # Pipeline
        "check": _cmd_check,
        "merge": _cmd_merge,
        "containerize": _cmd_containerize,
        "release": _cmd_release,
        "stagetest": _cmd_stagetest,
        "rollback": _cmd_rollback,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Pre-parse global options that can appear before the subcommand. We do
    # this by hand rather than with argparse so we don't have to thread it
    # through each subcommand's parser.
    debug = False
    while argv and argv[0].startswith("--"):
        if argv[0] == "--debug":
            debug = True
            argv.pop(0)
            continue
        if argv[0] in ("--version", "-V"):
            print(f"docex {__version__}")
            return 0
        if argv[0] in ("--help", "-h"):
            print(_format_usage())
            return 0
        # Unknown global option — fall through to dispatcher (will show usage).
        break

    if not argv:
        print(_format_usage(), file=sys.stderr)
        return 64  # EX_USAGE

    cmd, *rest = argv
    table = _build_handler_table()
    handler = table.get(cmd)
    if handler is None:
        print(f"error: unknown command {cmd!r}\n", file=sys.stderr)
        print(_format_usage(), file=sys.stderr)
        return 64

    reporter = ErrorReporter(debug=debug)
    try:
        return handler(rest)
    except SystemExit as e:
        # argparse calls sys.exit() on its own errors; propagate cleanly.
        return int(e.code) if e.code is not None else 0
    except DocexError as exc:
        return reporter.report(exc)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001  - top-level catchall
        return reporter.report(exc)


if __name__ == "__main__":
    raise SystemExit(main())
