"""``docex test`` — the build-test step.

Per cicd.md § Build Test Step:

  1. Bring up the test env (compose handles `docker build`, which
     runs build.sh in the build stage so test images carry correct
     artifacts).
  2. Migrate against the test env.
  3. Run each codebase's test.sh, collecting exit codes.
  4. Always tear down with ``preserve_volumes=False`` (test env is
     throwaway; fresh runs get fresh databases).

The teardown happens in a ``finally`` block so a Python exception in
steps 2-3 still tears the env down. Exit 0 only if every step exited 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.orchestrate._common import (
    compose_file_for,
    codebases,
    ensure_compiled,
    env_compose_project,
    exec_service_key,
    slot_compose_file,
    codebases_with_schema,
)
from docex.orchestrate.aggregate import aggregate


_TEST_ENV = "test"


def run_test(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    project_dir: "Path | None" = None,
    env_file_override: "Path | None" = None,
    project_name: "str | None" = None,
    selector: "str | None" = None,
    slots: int = 1,
    slot: int = 1,
) -> int:
    """Run the full build-test cycle. Returns process exit code.

    ``project_dir`` and ``env_file_override`` exist for ``docex check``,
    which calls ``run_test`` against an ephemeral worktree whose
    configurable-value files (gitignored) don't exist on disk. The check
    pipeline passes the host path of the worktree as ``project_dir`` so
    compose resolves build contexts and bind-mounts to the worktree, and
    the worktree's aggregate (``.docex/agg/test.env``, built after
    mirroring the source files in) as ``env_file_override`` so compose's
    ``${VAR}`` substitutions resolve cleanly.

    ``project_name`` overrides the compose ``--project-name``; ``docex
    check`` passes a worktree-unique name so its throwaway ``test`` stack
    can't collide with (or get torn down alongside) a real ``test`` env
    stack on the same host. Defaults to the standard env-tier name.

    ``selector``, when set, is injected into each codebase's ``test.sh``
    one-off container as ``DOCEX_TEST_SELECTOR`` so the project shim can
    narrow the run to a subset of its suite.

    ``slots`` (Mod 154): ``1`` (default) is the existing single-stack path
    below, byte- and behavior-identical to today (no new compile call, no
    ``DOCEX_TEST_SLOT`` injection). ``>= 2`` dispatches ``_run_test_sharded``:
    the whole suite is sharded across N isolated slot stacks.
    Keyword-only so Mod 155 can later add a *distinct* ``slot=`` param (a single
    reserved slot for check/merge) without conflating it with this shard count.

    ``slot`` (Mod 155): pins the *single-stack* path to one slot index. ``1``
    (default) is byte/behavior-identical to today. ``slot != 1`` is used ONLY by
    ``check``/``merge``, which compile + run the ``test`` env at a reserved slot
    above the ``--slots`` band (``CHECK_SLOT``/``MERGE_SLOT``) so their compiled
    physical names — especially the DB volume ``name:`` — are disjoint from any
    ``docex test`` run and from each other, closing the ``--project-name``
    DB-volume collision (compose's ``--project-name`` does not namespace explicit
    ``container_name:``/volume ``name:``). ``slot`` and ``slots`` are mutually
    exclusive: check/merge pass ``slot=``, never ``slots=`` (they never shard).
    """
    if slots >= 2:
        return _run_test_sharded(
            ctx, docker, selector=selector, slots=slots,
        )
    if slot == 1:
        ensure_compiled(ctx)
        compose_file = compose_file_for(ctx, _TEST_ENV)
    else:
        # Reserved-slot single-stack path (check/merge). Compile defensively at
        # `slot` — same "always re-compile" philosophy as ensure_compiled — into
        # the gitignored .docex/slots/<env>/<slot>/ tree, leaving slot-1
        # infra/output/ untouched (byte-identical default preserved).
        from docex.cicl.compile import compile_slot
        compile_slot(ctx, _TEST_ENV, slot)
        compose_file = slot_compose_file(ctx, _TEST_ENV, slot)
    # Bring-up site. With no override this builds the test aggregate here;
    # ``docex check`` passes its own already-built worktree aggregate as the
    # override (it mirrors the gitignored source files into the worktree and
    # aggregates there — see pipeline/check.py).
    env_file = (
        env_file_override
        if env_file_override is not None
        else aggregate(ctx, env=_TEST_ENV)
    )
    if project_name is None:
        project_name = env_compose_project(ctx, _TEST_ENV, slot=slot)

    first_failure: int = 0
    try:
        # Mod 155: reserved-slot (check/merge) runs reap any leftover
        # same-slot stack before bringing up a clean one. Idempotent; ignores
        # absence. Gated slot!=1 so the default `docex test` path is unchanged.
        if slot != 1:
            docker.compose_down(
                compose_file, preserve_volumes=False,
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
        # 1. compose up --build -d
        rc = docker.compose_up(
            compose_file, build=True, detach=True,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )
        if rc != 0:
            print(
                f"error: 'docker compose up' for test env exited {rc}.",
                file=sys.stderr,
            )
            return rc

        # 2. migrate every schema-owning service.
        #
        # WHY build=True (Mod 103): in `test` the image *is* the artifact under
        # test, so a one-off must never run a stale one — and `compose run`
        # builds only when the image is ABSENT, reusing a stale image silently
        # otherwise. In `dev` the source arrives by bind mount and the `dev`
        # stage exists precisely so `build.sh` can be re-invoked without
        # rebuilding the image; that asymmetry is why this is not
        # unconditional. `run_test` is the `test` env by construction
        # (`_TEST_ENV`), so it passes True flat.
        for cb in codebases_with_schema(ctx):
            key = exec_service_key(ctx, _TEST_ENV, cb, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./migrate.sh"], build=True,
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
            if rc != 0:
                print(
                    f"error: migrate.sh for {cb!r} in test env exited {rc}.",
                    file=sys.stderr,
                )
                first_failure = rc
                # Per the doctrine, build test fails on first failure.
                return rc

        # 3. test.sh for each codebase, in the codebase's exec service.
        # Every codebase runs `test.sh` exactly one way: `compose run --rm`
        # against its own exec service, which the compiler emits for every
        # codebase whatever its core services' roles are. `selector`, when
        # set, reaches the project shim as DOCEX_TEST_SELECTOR so it can
        # narrow the run to a subset (see tests.md § Injected environment).
        #
        # WHY build=True: see step 2 above — same `test`-env freshness rule.
        selector_env = (
            {"DOCEX_TEST_SELECTOR": selector} if selector else None
        )
        for svc in codebases(ctx):
            key = exec_service_key(ctx, _TEST_ENV, svc, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./test.sh"], build=True,
                env=selector_env,
                env_file=env_file, project_dir=project_dir,
                project_name=project_name,
            )
            if rc != 0:
                print(f"error: test.sh for {svc!r} exited {rc}.",
                      file=sys.stderr)
                first_failure = rc
                return rc
    finally:
        # 4. Always tear down — even if a Python exception interrupted
        # us. preserve_volumes=False: test env's data is throwaway.
        td_rc = docker.compose_down(
            compose_file, preserve_volumes=False,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )
        if td_rc != 0 and first_failure == 0:
            # Don't mask a real test failure with a teardown failure,
            # but do surface teardown failures when tests passed.
            print(
                f"warning: teardown exited {td_rc}.",
                file=sys.stderr,
            )

    return first_failure


def _run_test_sharded(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    selector: "str | None",
    slots: int,
) -> int:
    """The ``--slots N>=2`` path: the whole suite is sharded across N isolated
    slot stacks brought up concurrently.

    Each physical name carries ``_s{k}`` (Mod 152) and the web bridge is
    per-slot (Mod 153), so the N stacks coexist on one host with no collision.
    Runs INSIDE the vessel (the durable job); the N slot stacks are sibling
    compose stacks it brings up over DooD.
    """
    ensure_compiled(ctx)
    env_file = aggregate(ctx, env=_TEST_ENV)  # per-env, shared by all slots

    # Compile every slot serially (cheap, deterministic — keeps the
    # concurrent section pure docker), then run the N slots concurrently.
    from docex.cicl.compile import compile_slot

    for k in range(1, slots + 1):
        compile_slot(ctx, _TEST_ENV, k)

    import concurrent.futures as _f

    results: dict[int, int] = {}
    with _f.ThreadPoolExecutor(max_workers=slots) as pool:
        futs = {
            pool.submit(
                _run_one_slot, ctx, docker,
                slot=k, slots=slots, env_file=env_file, selector=selector,
            ): k
            for k in range(1, slots + 1)
        }
        for fut in _f.as_completed(futs):
            k = futs[fut]
            results[k] = fut.result()

    # First non-zero, lowest slot first (deterministic report).
    for k in sorted(results):
        if results[k] != 0:
            return results[k]
    return 0


def _run_one_slot(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    slot: int,
    slots: int,
    env_file: "Path | None",
    selector: "str | None",
) -> int:
    """Bring up slot ``slot``, migrate, run the suite shim sharded, then
    tear down IFF it passed.

    A failed slot is LEFT UP for debugging — reaped by the next invocation's
    preflight (fleet reaper) or this slot's own pre-up ``compose down`` on the
    next run. Returns the slot's exit code. Runs on a worker thread;
    ``DockerClient`` is stateless per call, so no state is shared across slots.
    """
    compose_file = slot_compose_file(ctx, _TEST_ENV, slot)
    project_name = env_compose_project(ctx, _TEST_ENV, slot=slot)

    # Pre-up clean slate: reap any leftover same-numbered slot stack (a failed
    # slot left up by a prior run, or an orphan). Idempotent; ignores absence.
    docker.compose_down(
        compose_file, preserve_volumes=False,
        env_file=env_file, project_name=project_name,
    )

    slot_env = {"DOCEX_TEST_SLOT": str(slot), "DOCEX_TEST_SLOTS": str(slots)}
    if selector:
        slot_env["DOCEX_TEST_SELECTOR"] = selector

    rc = 0
    try:
        rc = docker.compose_up(
            compose_file, build=True, detach=True,
            env_file=env_file, project_name=project_name,
        )
        if rc != 0:
            print(f"error: 'compose up' for test slot {slot} exited {rc}.",
                  file=sys.stderr)
            return rc

        for cb in codebases_with_schema(ctx):
            key = exec_service_key(ctx, _TEST_ENV, cb, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./migrate.sh"], build=True,
                env_file=env_file, project_name=project_name,
            )
            if rc != 0:
                print(f"error: migrate.sh for {cb!r} in slot {slot} exited {rc}.",
                      file=sys.stderr)
                return rc

        for svc in codebases(ctx):
            key = exec_service_key(ctx, _TEST_ENV, svc, slot=slot)
            rc = docker.compose_run_one_off(
                compose_file, key, ["./test.sh"], build=True,
                env=slot_env, env_file=env_file, project_name=project_name,
            )
            if rc != 0:
                print(f"error: ./test.sh for {svc!r} slot {slot} "
                      f"exited {rc}.", file=sys.stderr)
                return rc
        return 0
    finally:
        # Keep-failed-slot-up-for-debug: only tear down a slot that PASSED.
        if rc == 0:
            td = docker.compose_down(
                compose_file, preserve_volumes=False,
                env_file=env_file, project_name=project_name,
            )
            if td != 0:
                print(f"warning: slot {slot} teardown exited {td}.",
                      file=sys.stderr)
