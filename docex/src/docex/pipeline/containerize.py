"""``docex containerize`` — build + push per-codebase prod images.

Per [cicd.md § Containerize Step] and [docex.md § containerize]:

  1. Validate preconditions (clean tree, on main, ``v<version>`` tag
     exists on HEAD).
  2. Resolve the registry from ``infra.yml``.
  3. For each codebase: ``docker buildx build --target prod`` then
     ``docker push <full_tag>``.
  4. Print one ``containerize: pushed <tag> (sha256:...)`` line per
     successful push.

The shim mounts the host's ``~/.docker/config.json`` into the container,
so ``docker push`` uses the operator's existing credentials. We do NOT
call ``docker login`` here — forcing a relogin every run would defeat
the purpose of credential persistence.
"""

from __future__ import annotations

import sys

from docex import ELASTIC_REGION
from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.errors import (
    BuildxFailed,
    RegistryPushFailed,
    TagMissing,
    WorkingTreeDirty,
)
from docex.git.client import GitClient
from docex.orchestrate._common import codebases


_DEFAULT_PLATFORM = "linux/amd64"


def _image_tag(registry: str, project_name: str, codebase: str, version: str) -> str:
    """Return ``<registry>/<project>/<codebase>:<version>``.

    Phase 1 already produces the same string for the prod compose
    ``image:`` field; this helper centralizes the formula so the
    registry destination matches what the deployed compose file
    expects to pull.
    """
    return f"{registry.rstrip('/')}/{project_name}/{codebase}:{version}"


def run_containerize(
    ctx: ProjectContext,
    docker: DockerClient,
    git: GitClient,
    *,
    platform: str = _DEFAULT_PLATFORM,
    aws: AWSClient | None = None,
) -> int:
    """Build + push prod images for every codebase. Returns exit code.

    ``aws`` is required only on the elastic ECR-default path (an elastic
    project with no explicit ``container_registry``); the dispatcher
    always passes one.
    """
    project_root = ctx.project_root
    project = ctx.project
    infra = ctx.infra
    if infra is None:
        print(
            "error: containerize requires infra/infra.yml (none found).",
            file=sys.stderr,
        )
        return 1

    # 1. Preconditions ---------------------------------------------------
    if not git.is_clean(project_root):
        raise WorkingTreeDirty(
            "containerize refuses to run with a dirty working tree. "
            "Commit or stash your changes first."
        )

    branch = git.current_branch(project_root)
    if branch != "main":
        print(
            f"error: containerize must run from 'main' (currently on {branch!r}).",
            file=sys.stderr,
        )
        return 1

    expected_tag = f"v{project.version}"
    if not git.tag_exists(project_root, expected_tag):
        # Phase 3 demands a real release tag — containerize follows
        # merge, which creates the tag. If no tag, refuse.
        raise TagMissing(
            f"no tag {expected_tag!r} exists on this repository; run "
            f"'docex merge' first to tag the release before containerizing."
        )

    # 2. Registry --------------------------------------------------------
    registry = infra.container_registry
    ecr = False
    if not registry:
        if infra.foundation == "elastic":
            # Elastic ECR default: derive the registry host from the AWS
            # account ID, then authenticate to ECR before pushing.
            if aws is None:
                print(
                    "error: elastic ECR-default containerize requires an "
                    "AWSClient. (Internal dispatch bug.)",
                    file=sys.stderr,
                )
                return 1
            account = aws.caller_identity()
            registry = f"{account}.dkr.ecr.{ELASTIC_REGION}.amazonaws.com"
            ecr = True
        else:
            print(
                "error: infra.yml is missing 'container_registry' — it is "
                "required on a fixed foundation (elastic defaults to the "
                "project ECR).",
                file=sys.stderr,
            )
            return 1

    # 3. Per-codebase buildx + push -------------------------------------
    all_codebases = codebases(ctx)
    if not all_codebases:
        print("containerize: no codebases declared; nothing to do.")
        return 0

    project_name = project.name
    version = project.version

    # Elastic ECR default: authenticate once before pushing.
    if ecr:
        username, password = aws.ecr_authorization_token()
        rc = docker.login(registry, username=username, password=password)
        if rc != 0:
            raise RegistryPushFailed(
                f"'docker login {registry}' exited {rc}; could not "
                f"authenticate to the project ECR."
            )

    for cb in all_codebases:
        context = project_root / "core" / cb
        dockerfile = context / "Dockerfile"
        if not dockerfile.is_file():
            print(
                f"error: {dockerfile} missing — codebase {cb!r} "
                "must ship a Dockerfile.",
                file=sys.stderr,
            )
            return 1

        full_tag = _image_tag(registry, project_name, cb, version)

        # ECR repositories are provisioned by `docex bootstrap` as part
        # of the project-tier tofu apply. We don't ensure them here.

        # Build.
        rc = docker.buildx_build(
            context=context,
            dockerfile=dockerfile,
            target="prod",
            platform=platform,
            tag=full_tag,
        )
        if rc != 0:
            raise BuildxFailed(
                f"'docker buildx build' for codebase {cb!r} exited {rc}."
            )

        # Push.
        rc = docker.push(full_tag)
        if rc != 0:
            raise RegistryPushFailed(
                f"'docker push {full_tag}' exited {rc}. "
                "Check your ~/.docker/config.json has credentials for "
                f"{registry!r}."
            )

        digest = docker.inspect_image_digest(full_tag) or "sha256:<unknown>"
        print(f"containerize: pushed {full_tag} ({digest})")

    return 0
