"""``DockerClient`` protocol.

Every docker / docker compose invocation that docex's orchestrate
layer needs is declared here. The runtime implementation is in
``subprocess_client.py``; unit tests use a fake recording client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DockerClient(Protocol):
    """Abstraction over the ``docker`` CLI.

    All methods return the underlying exit code (0 on success,
    non-zero on failure). They stream stdout/stderr to the caller's
    terminal in the production implementation. None of them raise on
    a non-zero exit — the orchestrate layer decides what to do.
    """

    def is_available(self) -> bool:
        """Probe whether docker is reachable (``docker info``).

        Returns True if the daemon is reachable, False otherwise.
        Used by the dispatcher to bail early with a clean error
        before attempting any Phase 2 command.
        """
        ...

    def compose_up(
        self,
        compose_file: Path,
        *,
        build: bool = True,
        detach: bool = True,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> int:
        """Run ``docker compose up`` for the given file.

        ``build=True`` adds ``--build``; ``detach=True`` adds ``-d``.
        ``env_file`` is passed to compose's top-level ``--env-file``
        so ``${VAR}`` substitutions in the compose file resolve from
        the project's ``infra/secrets/<env>.env`` (per doctrine).
        ``project_dir`` overrides the path compose uses as its working
        directory (``--project-directory``); defaults to the project
        root derived from the compose file's location. ``docex check``
        overrides this with the host path of its ephemeral worktree.
        ``project_name`` sets compose's ``--project-name`` explicitly.
        Like ``project_dir``, it MUST match between ``up`` and ``down``
        (and any ``exec``/``ps`` in between) for compose to find its
        own resources; ``None`` lets compose derive the name from the
        project directory's basename (legacy behavior).
        """
        ...

    def compose_down(
        self,
        compose_file: Path,
        *,
        preserve_volumes: bool = True,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> int:
        """Run ``docker compose down`` for the given file.

        ``preserve_volumes=True`` is the default (dev env doctrine).
        ``preserve_volumes=False`` adds ``-v``, deleting named
        volumes too (test env teardown). ``project_dir`` /
        ``project_name`` — see :meth:`compose_up`. ``project_name``
        must match the value used at ``up`` time or ``down`` will not
        find (and therefore not remove) the stack's resources.
        """
        ...

    def compose_run_one_off(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> int:
        """Run a one-shot ``docker compose run --rm`` for a service.

        Used when a command needs a fresh container rather than the
        existing one (mostly future Phase 3 work; included here so
        the protocol is stable). ``project_dir`` / ``project_name`` —
        see :meth:`compose_up`.
        """
        ...

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
        """Run a command inside a *running* service container.

        This is the primary mechanism used by ``docex build``,
        ``docex migrate``, and the build-test step of ``docex test``.
        ``project_dir`` / ``project_name`` — see :meth:`compose_up`.
        Both must match whatever values were used at ``compose_up``
        time so compose finds the same project.
        """
        ...

    def compose_ps(
        self,
        compose_file: Path,
        *,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> list[str]:
        """Return the names of services currently running under this
        compose file. Empty list means nothing is up.
        ``project_dir`` / ``project_name`` — see :meth:`compose_up`."""
        ...

    def compose_ps_status(
        self,
        compose_file: Path,
        *,
        env_file: Path | None = None,
        project_dir: Path | None = None,
        project_name: str | None = None,
    ) -> dict[str, str]:
        """Map each service to a coarse state: one of
        ``'running' | 'restarting' | 'unhealthy' | 'exited' | 'created'``.

        Unlike :meth:`compose_ps` (running names only), this surfaces
        *all* services and their state so a partial bring-up can be
        diagnosed per-service. Empty dict means nothing is up.
        ``project_dir`` / ``project_name`` — see :meth:`compose_up`.
        """
        ...

    def build_image(self, context: Path, *, target: str, tag: str) -> int:
        """Run ``docker build --target <target> -t <tag> <context>``.

        Used by ``docex up dev`` for the one-time pre-populate of host
        ``dist/`` from a service's ``build`` stage. An empty
        ``target=""`` skips the ``--target`` flag entirely, so callers
        with a single-stage Dockerfile (e.g. ``docex stagetest``'s
        ephemeral tester image) can reuse this method.
        Returns exit code.
        """
        ...

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
        """Run ``docker run [--rm] -v <src>:<dst> ... <image> <command...>``.

        ``mounts`` is a list of ``(host_path, container_path)`` pairs.
        ``remove=True`` adds ``--rm``. ``env`` adds ``-e K=V`` pairs.
        ``network`` adds ``--network <name>`` (used by ``stagetest`` to
        give the ephemeral tester host-network access).
        Returns exit code.
        """
        ...

    # ------------------------------------------------------------------
    # Phase 3 additions: buildx + push for `containerize`.
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
        """Run ``docker buildx build`` and tag the result.

        Phase 3 uses buildx (not plain ``docker build``) so the produced
        image has a deterministic platform identifier suitable for
        cross-arch pushes (``linux/amd64`` even from an arm64 dev
        machine). Returns exit code.
        """
        ...

    def push(self, tag: str) -> int:
        """``docker push <tag>``. Returns exit code.

        Authentication is whatever ``~/.docker/config.json`` is
        configured for; the docex shim mounts the host's config file
        into the container, so registry credentials follow the user's
        existing ``docker login`` state.
        """
        ...

    def login(self, registry: str, *, username: str, password: str) -> int:
        """``docker login <registry>`` with the password supplied on stdin.

        Used by ``containerize`` to authenticate to the project's ECR
        when an elastic project relies on the default registry (no
        explicit ``container_registry``). The password is piped via
        stdin — never argv — so it can't leak into the process table.
        Returns exit code.
        """
        ...

    def inspect_image_digest(self, tag: str) -> str:
        """Return the sha256 image digest for ``tag``, or empty string
        if the image isn't present locally.

        Used by ``containerize`` to print ``<tag> (sha256:...)`` lines
        after a successful push, so the operator can verify which
        exact image landed in the registry.
        """
        ...

    def manifest_inspect(self, ref: str) -> bool:
        """Probe whether ``ref`` (a full ``<registry>/<repo>:<tag>``) is
        resolvable in the registry via ``docker manifest inspect``.

        Returns True iff the manifest is reachable (image exists in the
        registry). Returns False on any non-zero exit, including network
        errors — the caller (``rollback``) treats that as "not present"
        and surfaces it via the precondition check.
        """
        ...

    # ------------------------------------------------------------------
    # Mod 036: env-tier still-up detection used by ``projinfra down``.
    # ------------------------------------------------------------------

    def any_env_compose_up(self, project_name: str) -> bool:
        """True iff any env-tier compose stack for ``project_name`` is
        currently up on the local docker daemon.

        Env compose project names are ``${dns_label(project)}-${env}``
        for env in ``(dev, test, stage, prod)`` — the DNS-labeled form
        matching what the orchestrate layer passes as ``--project-name``
        (``orchestrate._common.env_compose_project``). ``project_name``
        here is the raw project name; the implementation DNS-labels it.
        Implemented via ``docker compose ls --format json --all`` and a
        name-match filter. ``projinfra down`` refuses when True.
        """
        ...

    # ------------------------------------------------------------------
    # Mod 042: preinfra existence checks.
    # ------------------------------------------------------------------

    def network_exists(self, name: str) -> bool:
        """True iff the named docker network exists on the local daemon.

        Used by ``docex preinfra`` to verify that prerequisite docker
        networks (notably the ``docex-ingress`` bridge) have been
        created by the operator before any side runs.
        """
        ...
