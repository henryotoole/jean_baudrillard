# environment_config

The compiler's per-environment output: the deterministic config artifacts that drive an environment's deployment.

- **Fixed envs (dev, test, and stage/prod on a fixed foundation):** `compose.yml`, plus `playbook.yml`, `inventory.yml`, and `ansible.cfg` for stage/prod.
- **Elastic envs (stage/prod on an elastic foundation):** `main.tf`, a single OpenTofu HCL file containing provider, state backend, the env's security groups, the reverse-proxy wiring (an ALB target group + listener rule, or the EC2-traefik equivalent), ECS services, RDS/S3/etc., and Route53 records. The ECS cluster itself is project-tier, not part of an env's `main.tf`.

All env config is written to `infra/output/<env>/` and is **git-tracked**: a diff shows exactly what an `infra.yml` change produces, so a reviewer sees the full infrastructure impact of a PR. The compiler is deterministic — identical `infra.yml` plus tables produce byte-identical output.

The output is consumed by `docex envinfra up` (the fixed dev loop) and `docex release` (stage/prod). It is the single source of truth for what infrastructure exists; nothing here is hand-edited.

Doctrine reference: `infrastructure/cicl.md § Compiler Output`.
