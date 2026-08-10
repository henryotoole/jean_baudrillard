"""``docex stagetest`` — run staging tests against the deployed stage env.

Per [docex.md § stagetest] and [cicd.md § Staging Tests]:

  1. Compute STAGING_URL from ``infra.yml``'s ``domain`` field —
     ``https://stage.<domain>``.
  2. Read every core service's health and version **from the orchestrator** and
     fail if anything is unhealthy, on the wrong version, or unreadable — mod
     128's pre-step, ``pipeline/orchestrator_health.py``. This is
     ``cicd.md § Staging Tests`` step 1 and it runs *before the tester image is
     built*: there is no point building a tester for an env that is not up, and
     no honest way to interpret its verdict.
  3. Build the project's stage-tester image from ``infra/stage/``.
  4. Run the tester image with ``--network host`` (simplest choice for
     "container needs to reach the deployed staging URL") and the
     project bind-mounted at ``/project``. Invoke
     ``/project/infra/stage/stage_test.sh`` with ``$STAGING_URL`` set.
  5. Propagate the container's exit code.

``network_override`` lets a caller put the tester on a specific docker
network instead of the host network — needed when the target is only
reachable over a project network (e.g. a local stand-in: web services no
longer publish host ports, so the tester reaches them by container name
on the env's ``web`` network).
"""

from __future__ import annotations

import sys

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import StageTesterBuildFailed
from docex.naming import dns_label
from docex.pipeline.orchestrator_health import assert_deployed_healthy
from docex.ssh.client import SSHClient

#: ``stagetest`` takes no env argument and is ``stage`` by construction. A module
#: constant rather than a CLI flag: ``docex stagetest <env>`` is not this step's
#: business.
_STAGETEST_ENV = "stage"


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
    aws: AWSClient | None = None,
    ssh: SSHClient | None = None,
    staging_url_override: str | None = None,
    network_override: str | None = None,
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
        apex_domain = infra.apex_domain
        if not apex_domain:
            print(
                "error: infra.yml is missing 'apex_domain' — required to "
                "construct STAGING_URL.",
                file=sys.stderr,
            )
            return 1
        # Canonical bare-env host per cicl.md § Domain:
        # <env>.<project>.<apex_domain>. The project segment must be
        # DNS-labeled — shared rule in naming.dns_label.
        project_seg = dns_label(project_name)
        staging_url = f"https://stage.{project_seg}.{apex_domain}"

    # 2. Orchestrator liveness/version pre-step ------------------------
    #
    # WHY this is second in the body while `cicd.md` numbers the orchestrator
    # read as step 1 — do not flip the order after reading only the doctrine's
    # numbering. The STAGING_URL derivation above is a pure string computation:
    # it touches nothing deployed, builds nothing, and starts nothing. So the
    # orchestrator read is still the first thing in this command that touches
    # the deployed world, which is what the doctrine's ordering is about — and
    # running it second preserves the better error for a project missing
    # `apex_domain` (that is a config bug, not an unhealthy env).
    #
    # Its two error classes are DocexErrors and are NOT caught: the dispatcher's
    # ErrorReporter renders them, exactly as StageTesterBuildFailed is handled.
    assert_deployed_healthy(ctx, env=_STAGETEST_ENV, aws=aws, ssh=ssh)

    # 3. Build the stage tester image ----------------------------------
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

    # 4. Run the tester ----------------------------------------------
    rc = docker.run_one_shot(
        image=tag,
        command=["/project/infra/stage/stage_test.sh"],
        mounts=[(project_root, "/project")],
        remove=True,
        env={
            "STAGING_URL": staging_url,
            "PROJECT_VERSION": ctx.project.version,
        },
        network=network_override or "host",
    )
    if rc == 0:
        print(f"stagetest: passed (staging_url={staging_url}).")
    else:
        print(
            f"stagetest: failed (staging_url={staging_url}); exit={rc}.",
            file=sys.stderr,
        )
    return rc
