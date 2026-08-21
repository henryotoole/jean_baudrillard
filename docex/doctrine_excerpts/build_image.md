# build_image

A docker container image built from a `codebase`'s source via `docker buildx`, tagged with the project's version, and pushed to the `container_registry`. One image per codebase — every core service the codebase declares runs that same image; all images for a project share the project-wide version.

Build images are **project-tier infrastructure**: one set per project, replicated across environments by tag reference rather than by rebuild. The same `myproject/api:0.4.2` runs in every env, with only `environment_config` and `secrets` differing.

The image's Dockerfile must declare four canonical stages (`build`, `dev`, `prod`, `test`) — this is a strict doctrine rule, not a convention. See `infrastructure/infrastructure.md § Codebase Containers`.

Doctrine reference: `infrastructure/cicd.md § Build Step`.
