# sample_project_elastic — elastic-foundation test fixture

This fixture mirrors `sample_project/` but flips the foundation to
`elastic` in `infra/infra.yml`. It exercises Phase 4 emit/orchestrate
code paths (HCL emission, SSM push, ECS RunTask migration, `tofu apply`)
against the same single-service shape as the fixed fixture.

## Layout

- `project.yml` — owned by this fixture (different from the fixed
  fixture so the project name / version are independent).
- `infra/infra.yml` — declares `foundation: elastic` and the same
  `api` + `database` services as the fixed fixture.
- `infra/contracts/api.web.openapi.yml` — **symlinked** to
  `../sample_project/infra/contracts/api.web.openapi.yml`. The Phase 3
  `check` gate verifies a `/health` endpoint exists; the same contract
  applies on both foundations.
- `infra/secrets/{dev,test,stage,prod}.env` — placeholder env files.
  On elastic, `docex release` reads these and pushes every `KEY=VALUE`
  pair to SSM Parameter Store under `/<project>/<env>/<KEY>` as a
  SecureString. Real projects MUST gitignore these.
- `core/` — **symlinked** to `../sample_project/core`. The fixed and
  elastic fixtures share one service definition so changes to `api`'s
  source / Dockerfile / migrations apply to both. If you break the
  symlink, both fixtures' integration tests start drifting; restore
  the link.

No `infra/deploy_creds/` directory exists here on purpose: elastic
projects authenticate via `~/.aws/credentials` (mounted by the
`bin/docex` shim), not SSH keys.

## Re-creating the symlinks

If a future port or filesystem snapshot loses the symlinks, recreate
them from this directory with:

```
ln -s ../sample_project/core core
ln -s ../../../sample_project/infra/contracts/api.web.openapi.yml infra/contracts/api.web.openapi.yml
```
