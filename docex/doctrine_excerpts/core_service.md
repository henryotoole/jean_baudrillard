# core_service

A container running the project's own bespoke code. Always a container — on fixed it runs as a docker-compose service, on elastic it runs as an ECS Fargate task. The container's image is one of the project's `build_image`s pulled from the `container_registry`.

One or more core services are declared by a single `codebase` — one source tree, one build artifact, one image, N ways of invoking it. The codebase is the unit of *code*; the core service is the unit of *deployment*.

Two strict doctrine rules:

1. **Codebases never share code.** Separation of concerns is enforced architecturally. All that ties codebases together is a shared purpose, shared backing services, and a single project-wide build version. Core services of the *same* codebase share everything — they are the same artifact started differently.
2. **Core services execute as stateless processes** (12-factor). Persistent state lives in backing services. A core service must be safe to terminate, restart, or replicate at any moment.

Core services declare `resources:` (CPU, memory, optional disk/GPU) in `infra.yml`; the compiler translates this to compose `deploy.resources` or Fargate task settings per `transfer_tables.md § Resources Translation`.

Every core service's container carries a health probe the compiler emits on both
foundations — `./health.sh <service>`, a compose `healthcheck:` on fixed and an ECS
container `healthCheck` on elastic. The core service declares nothing for it; the
argv is supplied so one codebase's shim can probe a web edge and a queue consumer
differently. For a core service off the `web` network this probe is its **only**
liveness enforcement: nothing routes to it, so no load balancer and no staging test
can reach it.

Doctrine reference: `infrastructure/infrastructure.md § Repository Structure`; `infrastructure/cicl.md § Core Services`.
