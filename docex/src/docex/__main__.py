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
    "build": "Refresh dist/ for one or all codebases.",
    "test": "Run build-time tests in a fresh test env.",
    "migrate": "Apply database migrations against an env.",
    "check": "Run CI gate checks in an ephemeral worktree.",
    "merge": "Rebase + fast-forward + tag + push.",
    "containerize": "Build and push per-codebase prod images.",
    "release": "Deploy the containerized build to stage or prod.",
    "stagetest": "Run staging tests against the deployed stage env.",
    "rollback": "Roll a deployed env back to a prior version (narrow-window emergency).",
    "secrets": "Manage per-env secrets (scaffold/status/set/copy) value-blind.",
    "config": "Manage per-env config (scaffold/status/set/get/copy) values visible.",
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
    ("Configuration", ("secrets", "config")),
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
    """``docex envinfra <direction> <env>`` — bring up or tear down an
    environment.

    ``up`` is **dev/test only**: bringing stage/prod up needs a
    versioned build, which is ``docex release``'s job. ``down`` covers
    **all** envs (Mod 052, Gap F): dev/test (and fixed stage/prod) tear
    down their compose stack; elastic stage/prod ``tofu destroy`` the
    env-tier HCL behind a deletion-protection pre-flight gate.

    Mod 042: ``up`` refuses when ``preinfra development`` fails;
    teardown is not gated (preinfra existence isn't required to remove
    a stack).
    """
    parser = argparse.ArgumentParser(prog="docex envinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("env", choices=["dev", "test", "stage", "prod"],
                        help="environment (dev/test for up; any for down)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))

    if ns.direction == "up":
        if ns.env not in ("dev", "test"):
            print(
                f"error: 'docex envinfra up {ns.env}' is not supported — "
                f"stage/prod are brought up by `docex release` (an elastic "
                f"env's ECS/RDS are created by the release `tofu apply`, "
                f"which also requires a versioned build)."
            )
            return 1
        docker = _require_docker()
        # envinfra up is dev/test only — always development side, never
        # needs AWS even on elastic projects.
        from docex.dns.dnspython_resolver import DnspythonResolver
        from docex.pipeline.preinfra import run_preinfra
        rc = run_preinfra(
            ctx, docker, aws=None, side="development",
            dns=DnspythonResolver(),
        )
        if rc != 0:
            print("error: preinfra development failed; aborting envinfra up.")
            return rc
        from docex.orchestrate.up import run_up
        return run_up(ctx, docker, env=ns.env)

    # down — all envs. Elastic stage/prod need AWS + the tofu runners
    # for the deletion-protection gate and `tofu destroy`; dev/test (and
    # fixed stage/prod) only need docker. Thread all transports; the
    # function dispatches on foundation/env.
    docker = _require_docker()
    from docex.opentofu import tofu_destroy, tofu_init
    from docex.orchestrate.down import run_down
    aws = _make_aws_client()
    return run_down(
        ctx, docker, env=ns.env,
        aws=aws, tofu_init=tofu_init, tofu_destroy=tofu_destroy,
    )


def _cmd_preinfra(args: list[str]) -> int:
    """``docex preinfra <side>`` — check prerequisite infrastructure
    for the given side.

    Mod 042: lazy AWS client construction. Boto3 is only built when
    the project is elastic and the side is production; fixed-only
    operators (or anyone checking the development side) don't need
    AWS credentials on disk.
    """
    parser = argparse.ArgumentParser(prog="docex preinfra", add_help=True)
    parser.add_argument("side", choices=["development", "production"],
                        help="side to check (development or production)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.dns.dnspython_resolver import DnspythonResolver
    from docex.pipeline.preinfra import run_preinfra

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    needs_aws = (
        ctx.infra is not None
        and ctx.infra.foundation == "elastic"
        and ns.side == "production"
    )
    aws = _make_aws_client() if needs_aws else None
    needs_ssh = (
        ctx.infra is not None
        and ctx.infra.foundation == "fixed"
        and ns.side == "production"
    )
    ssh = _make_ssh_client() if needs_ssh else None
    # The DNS resolver is cheap to construct and only consulted on the
    # development branch; pass it unconditionally (mod 054).
    dns = DnspythonResolver()
    return run_preinfra(ctx, docker, aws, side=ns.side, ssh=ssh, dns=dns)


def _cmd_projinfra(args: list[str]) -> int:
    """``docex projinfra <direction> <side>`` — bring up or tear down
    project-tier infrastructure for a side.

    Mod 036 wires the fixed branch end-to-end: ``up`` runs the project-
    tier compose stack (four ``-web`` networks + per-project traefik);
    ``down`` tears it down (refusing if any env-tier compose stack for
    this project is still up). Elastic ``up production`` continues to
    run the existing state-backend setup (formerly ``bootstrap``); the
    rest of elastic projinfra is stubbed until mods 037-039."""
    parser = argparse.ArgumentParser(prog="docex projinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("side", choices=["development", "production"],
                        help="side (development or production)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))

    # Fixed-foundation branch: both sides run a docker compose stack
    # against the local daemon. On single-machine fixed projects the
    # two sides converge — same daemon, same network/service set, the
    # second `up` is a docker-compose no-op.
    #
    # Mod 048: an elastic project's DEVELOPMENT side is mechanically
    # identical to a fixed development side (same emit shape per
    # `projinfra/projinfra.md § Why all four web networks live on every
    # side`); route both through the same fixed-style code path. Only
    # the production side of an elastic project diverges (real AWS
    # state-backend + Route53 + ACM + ALB / EC2-traefik).
    fixed_style = (
        ctx.infra is not None and (
            ctx.infra.foundation == "fixed"
            or (ctx.infra.foundation == "elastic" and ns.side == "development")
        )
    )
    if fixed_style:
        from docex.pipeline.projinfra import (
            run_projinfra_fixed_down,
            run_projinfra_fixed_up,
        )
        docker = _require_docker()
        if ns.direction == "up":
            # Mod 042: precondition gate. Fixed-side preinfra needs
            # only docker, never AWS.
            #
            # Mod 050: the (fixed, production) preinfra branch probes the
            # target host for the registry credential over SSH, so supply
            # an SSH client for that case (lazy, mirroring aws).
            from docex.dns.dnspython_resolver import DnspythonResolver
            from docex.pipeline.preinfra import run_preinfra
            needs_ssh = (
                ctx.infra.foundation == "fixed" and ns.side == "production"
            )
            ssh = _make_ssh_client() if needs_ssh else None
            # Mod 054: this branch handles `projinfra up development` too,
            # where run_preinfra's dev-DNS check needs a resolver.
            rc = run_preinfra(
                ctx, docker, aws=None, side=ns.side, ssh=ssh,
                dns=DnspythonResolver(),
            )
            if rc != 0:
                print(
                    f"error: preinfra {ns.side} failed; "
                    f"aborting projinfra up."
                )
                return rc
            return run_projinfra_fixed_up(ctx, docker, side=ns.side)
        return run_projinfra_fixed_down(ctx, docker, side=ns.side)

    # Elastic + up + production: run the existing state-backend setup.
    if (ctx.infra is not None
            and ctx.infra.foundation == "elastic"
            and ns.direction == "up"
            and ns.side == "production"):
        # Mod 042: precondition gate. Elastic prod side needs AWS to
        # probe the master VPC and subnets.
        from docex.pipeline.bootstrap import run_bootstrap
        from docex.pipeline.preinfra import run_preinfra
        docker = _require_docker()
        aws = _make_aws_client()
        rc = run_preinfra(ctx, docker, aws, side="production")
        if rc != 0:
            print(
                "error: preinfra production failed; "
                "aborting projinfra up."
            )
            return rc
        return run_bootstrap(ctx, aws)

    # Remaining case: elastic + down + production (Mod 052, Gap F).
    # Automated project-tier teardown: refuse-if-envs-up, then
    # `tofu destroy` the project tier + ECR/SSM/state-backend cleanup.
    if (ctx.infra is not None
            and ctx.infra.foundation == "elastic"
            and ns.direction == "down"
            and ns.side == "production"):
        from docex.opentofu import tofu_destroy, tofu_init
        from docex.pipeline.projinfra import run_projinfra_elastic_down
        aws = _make_aws_client()
        return run_projinfra_elastic_down(
            ctx, aws, tofu_init=tofu_init, tofu_destroy=tofu_destroy,
        )

    # Fallthrough: elastic + down + development is handled by the
    # fixed-style branch above; nothing else should reach here.
    print(
        f"projinfra {ns.direction} {ns.side} on elastic foundation: "
        f"unsupported combination."
    )
    return 1


# ---------------------------------------------------------------------------
# Development handlers (build / test / migrate)
# ---------------------------------------------------------------------------


def _cmd_build(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex build", add_help=True)
    parser.add_argument("codebase", nargs="?", default=None,
                        help="codebase to build (omit to build all)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.orchestrate.build import run_build

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    return run_build(ctx, docker, codebase=ns.codebase)


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


def _make_ssh_client() -> "object":
    """Construct a ``SubprocessSSHClient``.

    Stateless and offline to construct — no connection is opened until
    ``run`` is called. The dispatcher builds one for the fixed-
    production preinfra branch (registry-cred probe).
    """
    from docex.ssh import SubprocessSSHClient

    return SubprocessSSHClient()


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
    # ``ansible_runner`` / ``ssh``. The function dispatches on foundation.
    aws = _make_aws_client()
    ssh = _make_ssh_client()
    return run_release(
        ctx,
        env=ns.env,
        ansible_runner=run_playbook,
        aws=aws,
        tofu_init=tofu_init,
        tofu_apply=tofu_apply,
        ssh=ssh,
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
    ssh = _make_ssh_client()
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
        ssh=ssh,
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
# Configuration handlers (secrets)
# ---------------------------------------------------------------------------


def _cmd_secrets(args: list[str]) -> int:
    """``docex secrets <scaffold|status|set|copy> ...`` — value-blind secret
    management. ``set`` never accepts a positional value (tty prompt or
    ``--from-file`` only) and nothing here ever prints a secret value."""
    _ENVS = ["dev", "test", "stage", "prod"]
    parser = argparse.ArgumentParser(prog="docex secrets", add_help=True)
    sub = parser.add_subparsers(dest="op", required=True)

    p_scaffold = sub.add_parser(
        "scaffold", help="reconcile <env>.env against the required key set")
    p_scaffold.add_argument("env", choices=_ENVS)

    p_status = sub.add_parser(
        "status", help="show SET/UNSET per key (never the value)")
    p_status.add_argument("env", choices=_ENVS)
    p_status.add_argument("--format", default="text", choices=["text", "json"])

    p_set = sub.add_parser(
        "set", help="set one key's value (tty prompt or --from-file only)")
    p_set.add_argument("env", choices=_ENVS)
    p_set.add_argument("key", help="the secret key to set")
    p_set.add_argument("--from-file", default=None,
                       help="read the value from a file (non-interactive)")

    p_copy = sub.add_parser(
        "copy", help="copy a key's value from one env to another (blind)")
    p_copy.add_argument("src_env", choices=_ENVS)
    p_copy.add_argument("tgt_env", choices=_ENVS)
    p_copy.add_argument("key", help="the secret key to copy")

    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.secretsmgmt import (
        SECRET_POLICY,
        copy_key,
        scaffold,
        set_key,
        status,
    )

    ctx = load_project_context(Path(os.getcwd()))
    if ctx.infra is None:
        print(
            "error: no infra/infra.yml found; `docex secrets` needs the "
            "declared key set to reconcile against.",
            file=sys.stderr,
        )
        return 1

    if ns.op == "scaffold":
        return scaffold(ctx, SECRET_POLICY, ns.env)
    if ns.op == "status":
        return status(ctx, SECRET_POLICY, ns.env, fmt=ns.format)
    if ns.op == "set":
        return set_key(
            ctx, SECRET_POLICY, ns.env, ns.key, from_file=ns.from_file)
    if ns.op == "copy":
        return copy_key(ctx, SECRET_POLICY, ns.src_env, ns.tgt_env, ns.key)
    return 64  # unreachable — argparse requires a valid subcommand


def _cmd_config(args: list[str]) -> int:
    """``docex config <scaffold|status|set|get|copy> ...`` — per-env config
    management with inverted permissions (config_and_secrets.md § Tooling):
    ``status``/``get`` show values, ``set`` accepts a positional value, and
    ``copy`` stays value-blind (lower-stakes)."""
    _ENVS = ["dev", "test", "stage", "prod"]
    parser = argparse.ArgumentParser(prog="docex config", add_help=True)
    sub = parser.add_subparsers(dest="op", required=True)

    p_scaffold = sub.add_parser(
        "scaffold", help="reconcile <env>.env against the required key set")
    p_scaffold.add_argument("env", choices=_ENVS)

    p_status = sub.add_parser(
        "status", help="show SET/UNSET and the value per key")
    p_status.add_argument("env", choices=_ENVS)
    p_status.add_argument("--format", default="text", choices=["text", "json"])

    p_set = sub.add_parser(
        "set", help="set one key's value (positional value, tty, or --from-file)")
    p_set.add_argument("env", choices=_ENVS)
    p_set.add_argument("key", help="the config key to set")
    p_set.add_argument("value", nargs="?", default=None,
                       help="the value (positional; config is non-secret)")
    p_set.add_argument("--from-file", default=None,
                       help="read the value from a file (non-interactive)")

    p_get = sub.add_parser(
        "get", help="print one key's value")
    p_get.add_argument("env", choices=_ENVS)
    p_get.add_argument("key", help="the config key to print")

    p_copy = sub.add_parser(
        "copy", help="copy a key's value from one env to another")
    p_copy.add_argument("src_env", choices=_ENVS)
    p_copy.add_argument("tgt_env", choices=_ENVS)
    p_copy.add_argument("key", help="the config key to copy")

    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.secretsmgmt import (
        CONFIG_POLICY,
        copy_key,
        get_key,
        scaffold,
        set_key,
        status,
    )

    ctx = load_project_context(Path(os.getcwd()))
    if ctx.infra is None:
        print(
            "error: no infra/infra.yml found; `docex config` needs the "
            "declared key set to reconcile against.",
            file=sys.stderr,
        )
        return 1

    if ns.op == "scaffold":
        return scaffold(ctx, CONFIG_POLICY, ns.env)
    if ns.op == "status":
        return status(ctx, CONFIG_POLICY, ns.env, fmt=ns.format)
    if ns.op == "set":
        return set_key(
            ctx, CONFIG_POLICY, ns.env, ns.key,
            value=ns.value, from_file=ns.from_file)
    if ns.op == "get":
        return get_key(ctx, CONFIG_POLICY, ns.env, ns.key)
    if ns.op == "copy":
        return copy_key(ctx, CONFIG_POLICY, ns.src_env, ns.tgt_env, ns.key)
    return 64  # unreachable — argparse requires a valid subcommand


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
        # Configuration
        "secrets": _cmd_secrets,
        "config": _cmd_config,
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
