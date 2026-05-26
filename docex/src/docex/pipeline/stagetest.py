"""``docex stagetest`` — run staging tests against the deployed stage env.

Per [docex.md § stagetest] and [cicd.md § Staging Tests]:

  1. Compute STAGING_URL from ``infra.yml``'s ``domain`` field —
     ``https://stage.<domain>``.
  2. Build the project's stage-tester image from ``infra/stage/``.
  3. Run the tester image with ``--network host`` (simplest choice for
     "container needs to reach the deployed staging URL") and the
     project bind-mounted at ``/project``. Invoke
     ``/project/infra/stage/stage_test.sh`` with ``$STAGING_URL`` set.
  4. Propagate the container's exit code.
"""

from __future__ import annotations

import sys

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import StageTesterBuildFailed


def _stage_tester_tag(project_name: str) -> str:
    """Tag for the locally-built stage tester image.

    We use a stable tag (rather than a content-hash) and rely on
    docker's layer cache to avoid redundant work — the doctrine
    doesn't require a content-addressed scheme here.
    """
    return f"{project_name}-stage-tester:latest"


def run_stagetest(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    staging_url_override: str | None = None,
) -> int:
    """Run the stage smoke tests. Returns exit code."""
    infra = ctx.infra
    if infra is None:
        print(
            "error: stagetest requires infra/infra.yml (none found).",
            file=sys.stderr,
        )
        return 1

    project_root = ctx.project_root
    project_name = ctx.project.name

    # 1. STAGING_URL ---------------------------------------------------
    if staging_url_override:
        staging_url = staging_url_override
    else:
        domain = infra.domain
        if not domain:
            print(
                "error: infra.yml is missing 'domain' — required to "
                "construct STAGING_URL.",
                file=sys.stderr,
            )
            return 1
        staging_url = f"https://stage.{domain}"

    # 2. Build the stage tester image ----------------------------------
    stage_dir = project_root / "infra" / "stage"
    dockerfile = stage_dir / "Dockerfile"
    if not dockerfile.is_file():
        print(
            "error: project is missing infra/stage/Dockerfile; "
            "stagetest needs a stage-tester image to build.",
            file=sys.stderr,
        )
        return 1

    tag = _stage_tester_tag(project_name)
    # The stage-tester Dockerfile is single-stage by convention;
    # ``target=""`` tells the DockerClient to skip ``--target``.
    rc = docker.build_image(stage_dir, target="", tag=tag)
    if rc != 0:
        raise StageTesterBuildFailed(
            f"'docker build' for stage-tester image exited {rc}."
        )

    # 3. Run the tester ----------------------------------------------
    rc = docker.run_one_shot(
        image=tag,
        command=["/project/infra/stage/stage_test.sh"],
        mounts=[(project_root, "/project")],
        remove=True,
        env={"STAGING_URL": staging_url},
        network="host",
    )
    if rc == 0:
        print(f"stagetest: passed (staging_url={staging_url}).")
    else:
        print(
            f"stagetest: failed (staging_url={staging_url}); exit={rc}.",
            file=sys.stderr,
        )
    return rc
