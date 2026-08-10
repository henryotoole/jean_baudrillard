# service_discovery

How one service finds another by name within an environment.

- **Fixed:** docker network DNS — works automatically as soon as containers share a docker network. A service named `api` is reachable at `myproject_dev_api` (its container name) by any other container on the same network. No additional configuration.
- **Elastic:** AWS Cloud Map + ECS Service Connect. Each environment's ECS namespace registers core services by their short name; consumers reach them as `${global_service_name}` resolved via Service Connect.

In both cases the *connection string* a core service builds looks the same — only the resolution mechanism underneath differs.

On elastic, a service's set of **resolvable** endpoint names is fixed when its
ECS **deployment** is created — every task launched into that deployment
inherits the same list rather than re-reading the namespace. A name registered
afterwards is not merely unreachable — it does not exist for any task in that
deployment, for the life of the deployment, and retrying never converges.
Replacing a task does not help; only a new deployment does. This is why a
release redeploys any consumer whose current deployment predates an endpoint it
uses. Fixed has no equivalent constraint: docker DNS resolves at lookup time.

Doctrine reference: `infrastructure/shape.md`;
`infrastructure/reasoning/elastic_release_pattern.md` (why application-level
retrying cannot recover from an unresolvable name);
`infrastructure/specifics/release.md § Service Connect Consumer Reconcile` (what a
release does about it).
