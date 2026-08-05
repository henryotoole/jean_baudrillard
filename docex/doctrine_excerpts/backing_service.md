# backing_service

A pre-packaged third-party service the project uses but does not maintain — postgres, redis, MinIO, S3, etc. The project declares the *role* the service plays (`relational_db`, `cache`, `object_store`) in `infra.yml`; the doctrine's transfer tables pick a concrete engine for each foundation.

- **Fixed:** runs as a docker container (postgres, redis, etc.).
- **Elastic:** runs as an AWS-managed service (RDS, ElastiCache, S3).

Backing services do **not** declare a `resources:` block in v1 — sizing comes from the engine's transfer-table defaults. Projects needing custom sizing override via project-local transfer tables at `infra/transfer_tables/`.

The `schema_owned_by:` field on database roles (e.g. `relational_db`) names the codebase that owns and migrates the schema; this is doctrine-enforced as a 1:1 invariant to prevent two codebases racing on the same database. It names a codebase rather than a core service because `migrate.sh` runs once per codebase, not once per invocation.

Doctrine reference: `infrastructure/cicl.md` § Service Fields; `infrastructure/specifics/transfer_tables.md`.
