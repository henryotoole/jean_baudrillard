# secrets

Environment-specific runtime values — database passwords, API keys, signing keys — that must never be committed. Doctrine uses a `.env`-per-environment source-of-truth model across both foundations, stored at `$pr/infra/secrets/<env>.env` (gitignored).

The **schema** of each `<env>.env` — which keys must exist — is derived deterministically from two sources: the `secrets:` blocks codebases declare in `infra.yml`, and doctrine-mandated keys such as `TELEMETRY_API_KEY`. `docex` manages that schema; only the values are supplied by hand.

- `docex secrets scaffold <env>` reconciles the required key set into `<env>.env`, preserving any values already present. There is **no** committed `example.env` — the schema lives in `docex`, not in a checked-in template.
- The operator fills values by editing `<env>.env` directly, or via `docex secrets set <env> <KEY>` (write-only, so values never enter an agent's context).

Materialization at release:

- **Fixed:** Ansible renders `<env>.env` onto the host; docker-compose reads it at container start.
- **Elastic:** `docex release` pushes each key to SSM Parameter Store at `/<project>/<env>/<KEY>` as a `SecureString`; ECS task definitions reference those paths via `secrets[]`.

The `.env` is authoritative on every release — manual edits to the deployed copy are clobbered — so rotation means editing the `.env`.

Doctrine reference: `infrastructure/configurable.md § Secrets`.
