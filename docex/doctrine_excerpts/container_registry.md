# container_registry

Where the project's codebase images are pushed (by `docex containerize`) and pulled from at release time.

- **Fixed:** prerequisite infrastructure. The doctrine does not provision a registry — it assumes a Docker Registry V2 (self-hosted) or a public registry (Docker Hub, ghcr.io) is already available. The project pins which one via `container_registry:` in `infra.yml` (required on fixed). It is operator-managed preinfra: its setup, its manifest-delete requirement (`REGISTRY_STORAGE_DELETE_ENABLED`, which `teardown.sh` depends on and `docex preinfra development` probes), and its garbage-collection procedure all live in `infrastructure/preinfra/container_registry.md`, not in the `container_registry:` field's own docs.
- **Elastic:** project-tier infrastructure (AWS ECR). Auto-provisioned per project. `container_registry:` in `infra.yml` is optional; it defaults to the project's ECR URL and is only set explicitly to push to an external registry instead.

Image refs are derived deterministically as `${container_registry}/${project_name}/${codebase_name}:${version}` — one image per codebase, run by every core service that codebase declares. Projects never write image strings by hand.

Doctrine reference: `infrastructure/cicl.md § Container Registry and Service Images`; `infrastructure/preinfra/container_registry.md`.
