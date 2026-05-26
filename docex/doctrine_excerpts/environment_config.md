# environment_config

The compiler's per-environment output: the deterministic config artifacts that drive an environment's deployment.

- **Fixed envs (dev, test, and stage/prod on fixed foundation):** `docker-compose.yml`, plus `playbook.yml`, `inventory.yml`, and `ansible.cfg` for stage/prod.
- **Elastic envs (stage/prod on elastic foundation):** `main.tf`, a single OpenTofu HCL file containing provider, state backend, network plane, ALB, ECS cluster + services, RDS/S3/etc., and Route53 records.

All env config is written to `infra/output/<env>/`. It is **git-tracked**: diffs on these files show what an `infra.yml` change actually produces, and reviewers see the full infrastructure impact of a PR. The compiler is deterministic — identical `infra.yml` plus tables produce byte-identical output.

The output is consumed by `docex up` (fixed dev loop) and `docex release` (stage/prod). It is the single source of truth for what infrastructure actually exists; nothing else should be hand-edited.

Doctrine reference: `infrastructure/cicl.md` § Compiler Output.
