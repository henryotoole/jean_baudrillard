"""Subprocess-backed implementation of ``DockerClient``.

This is the *only* module in docex permitted to ``import subprocess``.
Every other module reaches docker through the ``DockerClient``
protocol. That single chokepoint is what makes the unit tests cheap.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
from pathlib import Path


class SubprocessDockerClient:
    """Production ``DockerClient`` implementation.

    Stdout and stderr are inherited from the parent process so docker's
    progress output reaches the user's terminal unaltered.
    """

    def __init__(self, *, docker_bin: str = "docker") -> None:
        self._docker = docker_bin

    def _compose_env(self, compose_file: Path) -> dict[str, str]:
        """Return an env dict for ``subprocess.run`` calls to compose.

        Critical: compose resolves relative bind-mount paths in the
        compose YAML against ``COMPOSE_PROJECT_DIR`` (or, absent that
        var, against the directory containing the compose file). Our
        compose files live under ``infra/output/<env>/`` but reference
        ``./core/<svc>/...`` relative to the *project root*. So we
        always ensure ``COMPOSE_PROJECT_DIR`` is set to the project
        root.

        Under DooD (docex runs inside its own container), ``/project``
        inside the container is the *host*'s project root; the docker
        daemon lives on the host and resolves bind-mount paths against
        the host filesystem, where ``/project`` does not exist. The
        ``bin/docex`` shim therefore sets ``COMPOSE_PROJECT_DIR`` to
        the host project root before exec'ing docex, and we honor that
        value via ``setdefault`` here. Direct ``SubprocessDockerClient``
        use (tests, scripts) hits the fallback path: we derive the
        project root from the compose file's location.
        """
        env = dict(os.environ)
        # compose_file = <project_root>/infra/output/<env>/docker-compose.yml
        project_root = compose_file.parent.parent.parent.parent
        env.setdefault("COMPOSE_PROJECT_DIR", str(project_root))
        return env

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

    def _compose_base(self, compose_file: Path, env_file: Path | None) -> list[str]:
        # ``-f`` is the compose file. Relative bind-mount resolution
        # (``./core/<svc>/...``) is driven by ``COMPOSE_PROJECT_DIR``,
        # set in ``_compose_env`` so that under DooD the shim's host
        # path is honored. Passing ``--project-directory`` here would
        # take precedence over the env var and, inside docex,
        # silently resolve to ``/project`` (the in-container path),
        # which the host's docker daemon then fails to find on disk.
        # ``--env-file`` must come before the subcommand per the v2 CLI.
        cmd = [
            self._docker, "compose",
            "-f", str(compose_file),
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
    ) -> int:
        cmd = self._compose_base(compose_file, env_file) + ["up"]
        if build:
            cmd.append("--build")
        if detach:
            cmd.append("-d")
        return self._run(cmd, env=self._compose_env(compose_file))

    def compose_down(
        self,
        compose_file: Path,
        *,
        preserve_volumes: bool = True,
        env_file: Path | None = None,
    ) -> int:
        cmd = self._compose_base(compose_file, env_file) + ["down"]
        if not preserve_volumes:
            cmd.append("-v")
        return self._run(cmd, env=self._compose_env(compose_file))

    def compose_run_one_off(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        env_file: Path | None = None,
    ) -> int:
        cmd = self._compose_base(compose_file, env_file) + ["run", "--rm"]
        for key, val in (env or {}).items():
            cmd.extend(["-e", f"{key}={val}"])
        cmd.append(service)
        cmd.extend(command)
        return self._run(cmd, env=self._compose_env(compose_file))

    def compose_exec(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env_file: Path | None = None,
    ) -> int:
        # ``-T`` disables pseudo-tty allocation so this works when
        # called non-interactively (e.g. from CI).
        cmd = self._compose_base(compose_file, env_file) + ["exec", "-T", service] + command
        return self._run(cmd, env=self._compose_env(compose_file))

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

    def compose_ps(self, compose_file: Path, *, env_file: Path | None = None) -> list[str]:
        cmd = self._compose_base(compose_file, env_file) + ["ps", "--services", "--status=running"]
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=self._compose_env(compose_file),
            )
        except FileNotFoundError:
            return []
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, cmd: list[str], *, env: dict[str, str] | None = None) -> int:
        """Run ``cmd`` with inherited stdio; return its exit code."""
        try:
            res = subprocess.run(cmd, check=False, env=env)  # noqa: S603
        except FileNotFoundError:
            # Docker not installed at all. Tell the caller this is fatal.
            return 127
        return res.returncode
