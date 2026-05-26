# core_service

A container running the project's own bespoke code. Always a container — on fixed it runs as a docker-compose service, on elastic it runs as an ECS Fargate task. The container's image is one of the project's `build_image`s pulled from the `container_registry`.

Two strict doctrine rules:

1. **Core services never share code.** Separation of concerns is enforced architecturally. All that ties core services together is a shared purpose, shared backing services, and a single project-wide build version.
2. **Core services execute as stateless processes** (12-factor). Persistent state lives in backing services. A core service must be safe to terminate, restart, or replicate at any moment.

Core services declare `resources:` (CPU, memory, optional disk/GPU) in `infra.yml`; the compiler translates this to compose `deploy.resources` or Fargate task settings per `transfer_tables.md § Resources Translation`.

Doctrine reference: `infrastructure/infrastructure.md` § Codebase Structure; `infrastructure/cicl.md`.
