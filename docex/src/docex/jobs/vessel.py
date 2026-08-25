"""The container vessel — a detached sibling docex container.

Under Docker-out-of-Docker the foreground ``docex test`` runs *inside* the
``--rm`` docex container the shim launched; when the operator's shim call is
killed, that container dies. So the durable work cannot live in the
foreground — it runs in a separate ``-d`` sibling container the foreground
spawns over the docker socket. That sibling is the **vessel**.

The vessel is launched by **self-inspecting the foreground container**
(``docker inspect $HOSTNAME``) and cloning its image, binds, user, workdir
and group-add. This guarantees zero drift from the ``bin/docex`` shim's
mount contract and needs no shim change. If self-inspection fails, a warning
is emitted and a defensive spec is reconstructed from ``ctx`` — the launch
never proceeds silently on a wrong spec.

The vessel is **not** ``--rm``: its deterministic name is the lock, and the
name must persist after exit so the preflight can classify a dead vessel
(completed vs. orphaned) and reap it deterministically.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from docex.errors import VesselIntrospectionError


@dataclass
class LaunchResult:
    """Outcome of a vessel launch."""

    rc: int
    name_conflict: bool  # True iff docker refused on an existing --name


class ContainerVessel:
    """A detached, deterministically-named sibling docex container."""

    def __init__(self, docker, vessel_name: str) -> None:
        self._docker = docker
        self.vessel_name = vessel_name

    def is_running(self) -> bool | None:
        """True/False, or None when the container is absent."""
        return self._docker.container_running(self.vessel_name)

    def remove(self) -> int:
        """``docker rm`` the vessel (never ``-f``; callers only remove a
        non-running container)."""
        return self._docker.container_rm(self.vessel_name)

    def launch(self, ctx, run_id: str) -> LaunchResult:
        """Launch the detached vessel running ``docex __run-job <run_id>``.

        The ``docker run --name`` create is the atomic lock arbiter: if the
        name is already taken, ``run_detached`` reports ``name_conflict`` and
        the caller refuses rather than double-launching.
        """
        spec = self._resolve_spec(ctx)
        # The image's ENTRYPOINT is ["docex"] (see Dockerfile). We set the
        # entrypoint EXPLICITLY here rather than relying on that, and pass only
        # the args after it, so the effective container argv is exactly
        # `docex __run-job <run_id>` regardless of the cloned image's ENTRYPOINT
        # — this is what prevents the entrypoint doubling (`docex docex
        # __run-job …` → "unknown command 'docex'", exit 64) that mod 157 fixed.
        command = ["__run-job", run_id]
        rc, name_conflict = self._docker.run_detached(
            name=self.vessel_name,
            image=spec["image"],
            command=command,
            binds=spec["binds"],
            user=spec["user"],
            env=spec["env"],
            workdir=spec["workdir"],
            group_add=spec["group_add"],
            entrypoint="docex",
        )
        return LaunchResult(rc=rc, name_conflict=name_conflict)

    def _resolve_spec(self, ctx) -> dict:
        """The launch spec: a faithful clone of the foreground container.

        On introspection failure, warn and fall back to
        :meth:`_reconstruct_spec` — never mislaunch silently.
        """
        try:
            raw = self._docker.inspect_self()
        except VesselIntrospectionError as exc:
            print(
                f"warning: could not self-inspect the docex container "
                f"({exc}); reconstructing the vessel launch spec from project "
                f"context instead of cloning the foreground container. Verify "
                f"the run if it misbehaves.",
                file=sys.stderr,
            )
            return self._reconstruct_spec(ctx)
        # Env filtering (guard b): carry ONLY HOME — the one var the shim adds
        # that the vessel needs. TERM and any DOCEX_* are dropped: they are
        # either irrelevant to `test` or behavior-changing. The image's own
        # ENV applies automatically at `docker run`, so nothing else is copied.
        env = [e for e in (raw.get("env") or []) if e.startswith("HOME=")]
        return {
            "image": raw["image"],
            "binds": list(raw.get("binds") or []),
            "user": raw.get("user") or "",
            "env": env,
            "workdir": raw.get("workdir") or "",
            "group_add": list(raw.get("group_add") or []),
        }

    def _reconstruct_spec(self, ctx) -> dict:
        """Defensive fallback (ruling Q3a): rebuild the documented shim mount
        contract from ``ctx.project``.

        Reached only when self-inspection failed; a warning already told the
        operator. Mirrors ``bin/docex``: image ``docex:<docex_version>`` (local
        store, no registry prefix), the project root mirrored at its host path,
        ``/etc/passwd`` + ``/etc/group`` read-only, the docker socket, the
        host ``~/.docker``, and ``--user <uid>:<gid>``.
        """
        home = os.environ.get("HOME", "/root")
        project_root = str(ctx.project_root)
        binds = [
            f"{project_root}:{project_root}",
            "/etc/passwd:/etc/passwd:ro",
            "/etc/group:/etc/group:ro",
            "/var/run/docker.sock:/var/run/docker.sock",
            f"{home}/.docker:{home}/.docker",
        ]
        group_add: list[str] = []
        try:
            group_add = [str(os.stat("/var/run/docker.sock").st_gid)]
        except OSError:
            pass
        return {
            "image": f"docex:{ctx.project.docex_version}",
            "binds": binds,
            "user": f"{os.getuid()}:{os.getgid()}",
            "env": [f"HOME={home}"],
            "workdir": project_root,
            "group_add": group_add,
        }
