# service_discovery

How one service finds another by name within an environment.

- **Fixed:** docker network DNS — works automatically as soon as containers share a docker network. A service named `api` is reachable at `myproject_dev_api` (its container name) by any other container on the same network. No additional configuration.
- **Elastic:** AWS Cloud Map + ECS Service Connect. Each environment's ECS namespace registers core services by their short name; consumers reach them as `${global_service_name}` resolved via Service Connect.

In both cases the *connection string* a core service builds looks the same — only the resolution mechanism underneath differs.

Doctrine reference: `infrastructure/shape2.md`.
