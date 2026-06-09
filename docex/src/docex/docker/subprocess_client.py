"""Subprocess-backed implementation of ``DockerClient``.

This is the *only* module in docex permitted to ``import subprocess``.
Every other module reaches docker through the ``DockerClient``
protocol. That single chokepoint is what makes the unit tests cheap.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
from pathlib import Path


class SubprocessDockerClient:
    """Production ``DockerClient`` implementation.

    Stdout and stderr are inherited from the parent process so docker's
    progress output reaches the user's terminal unaltered.
    """

    def __init__(self, *, docker_bin: str = "docker") -> None:
        self._docker = docker_bin

    def _resolve_project_dir(
        self, compose_file: Path, project_dir: Path | None
    ) -> str:
        """Pick the host path compose should use as its project directory.

        Precedence:
          1. Explicit ``project_dir`` argument (caller knows best — e.g.
             ``docex check`` overrides this to the path of an ephemeral
             worktree).
          2. Derived from the compose file's location:
             ``compose_file.parent.parent.parent.parent`` matches the
             standard layout
             ``<root>/infra/output/<env>/docker-compose.yml``.

        Under DooD the ``bin/docex`` shim mirrors the host project root
        as the same path inside docex's container, so the derived path
        is simultaneously a valid in-container path (for compose's
        client-side reads) and a valid host path (for the daemon's
        bind-mount resolution). No env-var lookup needed.

        Note: docker compose v2 does NOT honor ``COMPOSE_PROJECT_DIR``
        as an env var (verified empirically against v2 v5.1.3). We
        always pass ``--project-directory`` on the CLI;
        ``_compose_base`` does that from the value returned here.
        """
        if project_dir is not None:
            return str(project_dir)
        # compose_file = <project_root>/infra/output/<env>/docker-compose.yml
        return str(compose_file.parent.parent.parent.parent)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            res = subprocess.run(  # noqa: S603 - intentional
                [self._docker, "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError:
            return False
        return res.returncode == 0

    # ------------------------------------------------------------------
    # docker compose wrappers
    # ------------------------------------------------------------------

    def _compose_base(
        self,
        compose_file: Path,
        env_file: Path | None,
        project_dir: Path | None,
    ) -> list[str]:
        # ``-f`` is the compose file. ``--project-directory`` tells
        # compose where to resolve relative paths (build contexts and
        # bind-mount sources) — it must be a host path the docker
        # daemon can find, since the daemon lives on the host. See
        # ``_resolve_project_dir`` for precedence. ``--env-file`` must
        # come before the subcommand per the v2 CLI.
        project_dir_str = self._resolve_project_dir(compose_file, project_dir)
        cmd = [
            self._docker, "compose",
            "-f", str(compose_file),
            "--project-directory", project_dir_str,
        ]
        if env_file is not None:
            cmd.extend(["--env-file", str(env_file)])
        return cmd

    def compose_up(
        self,
        compose_file: Path,
        *,
        build: bool = True,
        detach: bool = True,
        env_file: Path | None = None,
        project_dir: Path | None = None,
    ) -> int:
        cmd = self._compose_base(compose_file, env_file, project_dir) + ["up"]
        if build:
            cmd.append("--build")
        if detach:
            cmd.append("-d")
        return self._run(cmd)

    def compose_down(
        self,
        compose_file: Path,
        *,
        preserve_volumes: bool = True,
        env_file: Path | None = None,
        project_dir: Path | None = None,
    ) -> int:
        cmd = self._compose_base(compose_file, env_file, project_dir) + ["down"]
        if not preserve_volumes:
            cmd.append("-v")
        return self._run(cmd)

    def compose_run_one_off(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        env_file: Path | None = None,
        project_dir: Path | None = None,
    ) -> int:
        cmd = self._compose_base(compose_file, env_file, project_dir) + ["run", "--rm"]
        for key, val in (env or {}).items():
            cmd.extend(["-e", f"{key}={val}"])
        cmd.append(service)
        cmd.extend(command)
        return self._run(cmd)

    def compose_exec(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env_file: Path | None = None,
        project_dir: Path | None = None,
    ) -> int:
        # ``-T`` disables pseudo-tty allocation so this works when
        # called non-interactively (e.g. from CI).
        cmd = self._compose_base(compose_file, env_file, project_dir) + ["exec", "-T", service] + command
        return self._run(cmd)

    # ------------------------------------------------------------------
    # docker build / run (used for one-shot stage builds outside compose)
    # ------------------------------------------------------------------

    def build_image(self, context: Path, *, target: str, tag: str) -> int:
        cmd = [self._docker, "build"]
        if target:
            # Multi-stage Dockerfile: target a specific stage. An empty
            # ``target`` means "use the final stage" (passing
            # ``--target ""`` to docker would error).
            cmd.extend(["--target", target])
        cmd.extend(["-t", tag, str(context)])
        return self._run(cmd)

    def run_one_shot(
        self,
        image: str,
        command: list[str],
        *,
        mounts: list[tuple[Path, str]] | None = None,
        remove: bool = True,
        env: dict[str, str] | None = None,
        network: str | None = None,
    ) -> int:
        cmd = [self._docker, "run"]
        if remove:
            cmd.append("--rm")
        if network is not None:
            cmd.extend(["--network", network])
        for key, val in (env or {}).items():
            cmd.extend(["-e", f"{key}={val}"])
        for host, container in (mounts or []):
            cmd.extend(["-v", f"{host}:{container}"])
        cmd.append(image)
        cmd.extend(command)
        return self._run(cmd)

    # ------------------------------------------------------------------
    # Phase 3: buildx + push for `containerize`.
    # ------------------------------------------------------------------

    def buildx_build(
        self,
        *,
        context: Path,
        dockerfile: Path,
        target: str,
        platform: str,
        tag: str,
    ) -> int:
        # ``--load`` puts the produced image in the local docker
        # image store so the subsequent ``docker push`` finds it.
        # buildx's default for single-platform builds with a single
        # tag is to NOT load; --load makes the behaviour explicit.
        cmd = [
            self._docker, "buildx", "build",
            "--platform", platform,
            "--target", target,
            "--file", str(dockerfile),
            "--tag", tag,
            "--load",
            str(context),
        ]
        return self._run(cmd)

    def push(self, tag: str) -> int:
        return self._run([self._docker, "push", tag])

    def login(self, registry: str, *, username: str, password: str) -> int:
        # Password via stdin (``--password-stdin``) so it never appears
        # in argv / the process table.
        cmd = [
            self._docker, "login",
            "--username", username,
            "--password-stdin",
            registry,
        ]
        try:
            res = subprocess.run(  # noqa: S603 - chokepoint
                cmd, input=password, text=True, check=False,
            )
        except FileNotFoundError:
            return 127
        return res.returncode

    def inspect_image_digest(self, tag: str) -> str:
        cmd = [
            self._docker, "image", "inspect",
            "--format", "{{.Id}}",
            tag,
        ]
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return ""
        if res.returncode != 0:
            return ""
        return res.stdout.strip()

    def manifest_inspect(self, ref: str) -> bool:
        # WHY: capture_output (not inherited stdio) so a missing image
        # doesn't spam the operator's terminal with docker's error output
        # — this is a probe, not a user-facing command.
        cmd = [self._docker, "manifest", "inspect", ref]
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return False
        return res.returncode == 0

    def compose_ps(
        self,
        compose_file: Path,
        *,
        env_file: Path | None = None,
        project_dir: Path | None = None,
    ) -> list[str]:
        cmd = self._compose_base(compose_file, env_file, project_dir) + ["ps", "--services", "--status=running"]
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return []
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Mod 036: env-tier still-up detection used by ``projinfra down``.
    # ------------------------------------------------------------------

    def any_env_compose_up(self, project_name: str) -> bool:
        # WHY: --all surfaces both fully-running and partially-up stacks
        # (some containers exited, others up). Either case means projinfra
        # down would orphan something; we want to refuse on both.
        import json
        cmd = [
            self._docker, "compose", "ls",
            "--format", "json",
            "--all",
        ]
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return False
        if res.returncode != 0:
            return False
        try:
            entries = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            return False
        if not isinstance(entries, list):
            return False
        targets = {
            f"{project_name}-{env}" for env in ("dev", "test", "stage", "prod")
        }
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("Name") in targets:
                return True
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, cmd: list[str]) -> int:
        """Run ``cmd`` with inherited stdio; return its exit code."""
        try:
            res = subprocess.run(cmd, check=False)  # noqa: S603
        except FileNotFoundError:
            # Docker not installed at all. Tell the caller this is fatal.
            return 127
        return res.returncode
