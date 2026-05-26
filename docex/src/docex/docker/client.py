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
    ) -> int:
        """Run ``docker compose up`` for the given file.

        ``build=True`` adds ``--build``; ``detach=True`` adds ``-d``.
        ``env_file`` is passed to compose's top-level ``--env-file``
        so ``${VAR}`` substitutions in the compose file resolve from
        the project's ``infra/secrets/<env>.env`` (per doctrine).
        """
        ...

    def compose_down(
        self,
        compose_file: Path,
        *,
        preserve_volumes: bool = True,
        env_file: Path | None = None,
    ) -> int:
        """Run ``docker compose down`` for the given file.

        ``preserve_volumes=True`` is the default (dev env doctrine).
        ``preserve_volumes=False`` adds ``-v``, deleting named
        volumes too (test env teardown).
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
    ) -> int:
        """Run a one-shot ``docker compose run --rm`` for a service.

        Used when a command needs a fresh container rather than the
        existing one (mostly future Phase 3 work; included here so
        the protocol is stable).
        """
        ...

    def compose_exec(
        self,
        compose_file: Path,
        service: str,
        command: list[str],
        *,
        env_file: Path | None = None,
    ) -> int:
        """Run a command inside a *running* service container.

        This is the primary mechanism used by ``docex build``,
        ``docex migrate``, and the build-test step of ``docex test``.
        """
        ...

    def compose_ps(self, compose_file: Path, *, env_file: Path | None = None) -> list[str]:
        """Return the names of services currently running under this
        compose file. Empty list means nothing is up."""
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

    def inspect_image_digest(self, tag: str) -> str:
        """Return the sha256 image digest for ``tag``, or empty string
        if the image isn't present locally.

        Used by ``containerize`` to print ``<tag> (sha256:...)`` lines
        after a successful push, so the operator can verify which
        exact image landed in the registry.
        """
        ...
