"""Subprocess-backed implementation of ``DockerClient``.

This is the *only* module in docex permitted to ``import subprocess``.
Every other module reaches docker through the ``DockerClient``
protocol. That single chokepoint is what makes the unit tests cheap.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - explicit chokepoint, see module docstring
import sys
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
          2. Derived from the compose file's location by walking up to
             the directory that contains ``project.yml`` (mirrors
             ``context._find_project_root``).
          3. Fallback when no ``project.yml`` is found on the way up:
             ``compose_file.parent.parent.parent.parent``, the historical
             "up 4" assumption for the env-tier layout
             ``<root>/infra/output/<env>/docker-compose.yml``.

        WHY walk up rather than count parents: the fixed "up 4" was
        correct for env-tier files (``infra/output/<env>/…``) but
        off-by-one for project-tier files, which nest one level deeper
        (``infra/output/project/<side>/…`` → "up 4" lands on
        ``<root>/infra``, giving every projinfra stack the bogus,
        non-project-scoped compose name ``infra``). Walking up to
        ``project.yml`` resolves to the true project root for both tiers.

        Under DooD the ``bin/docex`` shim mirrors the host project root
        as the same path inside docex's container, so the resolved path
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
        here = compose_file.resolve().parent
        while True:
            if (here / "project.yml").is_file():
                return str(here)
            if here.parent == here:
                break
            here = here.parent
        # Fallback: the historical env-tier "up 4" derivation. Reached
        # only when no project.yml exists above the compose file (e.g.
        # in a bare tmp_path test fixture).
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
        project_name: str | None = None,
    ) -> list[str]:
        # ``-f`` is the compose file. ``--project-directory`` tells
        # compose where to resolve relative paths (build contexts and
        # bind-mount sources) — it must be a host path the docker
        # daemon can find, since the daemon lives on the host. See
        # ``_resolve_project_dir`` for precedence. ``--project-name``,
        # when supplied, fixes the compose project name explicitly
        # rather than letting compose derive it from the project
        # directory's basename — the derived value is wrong, not
        # project-scoped, and unstable across docex versions for the
        # project tier (see ``_resolve_project_dir``). ``--env-file``
        # and ``--project-name`` must come before the subcommand per
        # the v2 CLI.
        project_dir_str = self._resolve_project_dir(compose_file, project_dir)
        cmd = [
            self._docker, "compose",
            "-f", str(compose_file),
            "--project-directory", project_dir_str,
        ]
        if project_name is not None:
            cmd.extend(["--project-name", project_name])
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
        project_name: str | None = None,
    ) -> int:
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + ["up"]
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
        project_name: str | None = None,
    ) -> int:
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + ["down"]
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
        build: bool = False,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> int:
        # ``-T`` disables pseudo-tty allocation so this works when
        # called non-interactively (e.g. from CI). ``run`` allocates a TTY
        # by default, unlike ``exec``; the two must match here because
        # every docex call site is non-interactive.
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + ["run", "--rm", "-T"]
        # WHY --build is not the default: `compose run` builds ONLY when the
        # image is absent — a present-but-stale image is reused silently
        # (verified against compose v5.1.3). Callers in the `test` env must
        # opt in; callers in `dev` must not (the source arrives by bind mount
        # there, and a real rebuild would sit on the hot `docex build` loop).
        if build:
            cmd.append("--build")
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
        project_name: str | None = None,
    ) -> int:
        # ``-T`` disables pseudo-tty allocation so this works when
        # called non-interactively (e.g. from CI).
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + ["exec", "-T", service] + command
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
        project_name: str | None = None,
    ) -> list[str]:
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + ["ps", "--services", "--status=running"]
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

    def compose_ps_status(
        self,
        compose_file: Path,
        *,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> dict[str, str]:
        import json
        cmd = self._compose_base(
            compose_file, env_file, project_dir, project_name
        ) + [
            "ps", "--all", "--format", "json",
        ]
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return {}
        if res.returncode != 0:
            return {}
        return self._parse_ps_status(res.stdout)

    @staticmethod
    def _parse_ps_status(stdout: str) -> dict[str, str]:
        """Translate ``compose ps --format json`` into service → state.

        Compose v2 emits this in two shapes across versions: one JSON
        object per line (JSON-lines) or a single JSON array. Handle both.
        Each record carries ``Service``, ``State`` and ``Health``; an
        ``unhealthy`` Health overrides State so a never-healthy container
        is reported as ``unhealthy`` rather than ``running``.
        """
        import json
        text = stdout.strip()
        if not text:
            return {}
        records: list[dict] = []
        try:
            parsed = json.loads(text)
            records = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        out: dict[str, str] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            service = rec.get("Service")
            if not service:
                continue
            if rec.get("Health") == "unhealthy":
                out[service] = "unhealthy"
            else:
                out[service] = str(rec.get("State", "")).lower()
        return out

    # ------------------------------------------------------------------
    # Mod 036: env-tier still-up detection used by ``projinfra down``.
    # ------------------------------------------------------------------

    def any_env_compose_up(self, project_name: str) -> bool:
        # WHY: --all surfaces both fully-running and partially-up stacks
        # (some containers exited, others up). Either case means projinfra
        # down would orphan something; we want to refuse on both.
        #
        # ``project_name`` is the raw project name; we DNS-label it here so
        # the targets match the explicit env-tier compose project name the
        # orchestrate layer now passes (``<dns_label>-<env>`` — see
        # ``orchestrate._common.env_compose_project``). Before mod 053 this
        # built ``{project_name}-{env}`` from the underscored name, which
        # never matched real stacks named by the path-derived basename — a
        # latent mismatch in the refuse-if-envs-up gate.
        import json
        from docex.naming import dns_label
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
        label = dns_label(project_name)
        targets = {
            f"{label}-{env}" for env in ("dev", "test", "stage", "prod")
        }
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("Name") in targets:
                return True
        return False

    # ------------------------------------------------------------------
    # Mod 042: preinfra existence checks.
    # ------------------------------------------------------------------

    def network_exists(self, name: str) -> bool:
        # WHY: capture_output (not inherited) so probing a missing network
        # doesn't spam the operator's terminal with docker's "No such
        # network" output — this is a probe.
        cmd = [self._docker, "network", "inspect", name]
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return False
        return res.returncode == 0

    # ------------------------------------------------------------------
    # Mod 148: the job substrate's container vessel.
    # ------------------------------------------------------------------

    def run_detached(
        self,
        *,
        name: str,
        image: str,
        command: list[str],
        binds: list[str],
        user: str,
        env: list[str],
        workdir: str,
        group_add: list[str],
    ) -> "tuple[int, bool]":
        cmd = [self._docker, "run", "-d", "--name", name]
        if user:
            cmd.extend(["--user", user])
        if workdir:
            cmd.extend(["-w", workdir])
        for g in group_add:
            cmd.extend(["--group-add", g])
        for e in env:
            cmd.extend(["-e", e])
        for b in binds:
            cmd.extend(["-v", b])
        cmd.append(image)
        cmd.extend(command)
        # WHY capture_output: we must read stderr to distinguish a name
        # collision (the atomic-lock signal) from any other failure. On
        # success we still surface the container id so the launch is visible.
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return (127, False)
        if res.returncode == 0:
            out = (res.stdout or "").strip()
            if out:
                print(out)
            return (0, False)
        stderr = (res.stderr or "").lower()
        name_conflict = "is already in use" in stderr or "conflict" in stderr
        err = (res.stderr or "").strip()
        if err:
            print(err, file=sys.stderr)
        return (res.returncode, name_conflict)

    def inspect_self(self) -> dict:
        import json
        import socket

        from docex.errors import VesselIntrospectionError

        hostname = socket.gethostname()
        cmd = [self._docker, "inspect", hostname, "--format", "{{json .}}"]
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError as exc:
            raise VesselIntrospectionError(
                "docker not found while self-inspecting"
            ) from exc
        if res.returncode != 0:
            raise VesselIntrospectionError(
                f"'docker inspect {hostname}' exited {res.returncode}: "
                f"{(res.stderr or '').strip()}"
            )
        text = (res.stdout or "").strip()
        if not text:
            raise VesselIntrospectionError(
                f"'docker inspect {hostname}' returned empty output"
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VesselIntrospectionError(
                f"unparseable 'docker inspect' output: {exc}"
            ) from exc
        config = data.get("Config") or {}
        host_config = data.get("HostConfig") or {}
        image = config.get("Image")
        if not image:
            raise VesselIntrospectionError(
                "'docker inspect' output has no .Config.Image"
            )
        return {
            "image": image,
            "binds": host_config.get("Binds") or [],
            "user": config.get("User") or "",
            "env": config.get("Env") or [],
            "workdir": config.get("WorkingDir") or "",
            "group_add": host_config.get("GroupAdd") or [],
        }

    def container_running(self, name: str) -> "bool | None":
        cmd = [self._docker, "inspect", "-f", "{{.State.Running}}", name]
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return None
        if res.returncode != 0:
            # No such container (or daemon error) → absent.
            return None
        out = (res.stdout or "").strip().lower()
        if out == "true":
            return True
        if out == "false":
            return False
        return None

    def container_rm(self, name: str) -> int:
        # WHY capture_output: removing an already-absent container is a
        # normal path; don't spam the operator's terminal with docker's error.
        cmd = [self._docker, "rm", name]
        try:
            res = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return 127
        return res.returncode

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
