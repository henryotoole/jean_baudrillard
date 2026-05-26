# container_registry

Where the project's core service images are pushed (by `docex containerize`) and pulled from at release time.

- **Fixed:** prerequisite infrastructure. The doctrine does not provision a registry — it assumes a Docker Registry V2 (self-hosted) or a public registry (Docker Hub, ghcr.io) is already available. The project pins which one via `container_registry:` in `infra.yml` (required on fixed).
- **Elastic:** project-tier infrastructure (AWS ECR). Auto-provisioned per project. `container_registry:` in `infra.yml` is optional; it defaults to the project's ECR URL and is only set explicitly to push to an external registry instead.

Image refs are derived deterministically as `${container_registry}/${project_name}/${service_name}:${version}`. Projects never write image strings by hand.

Doctrine reference: `infrastructure/cicl.md` § Container Registry.
