# Secrets

This file describes how runtime secrets — database passwords, API keys, and other env-tier values that shouldn't be committed — flow from the operator's machine into running services across both foundations. The `.env`-as-source-of-truth model is uniform; the materialization mechanism is foundation-aware.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context. The shorter doctrine-prose summary is in [credentials.md § Secrets](../credentials.md#secrets).

## Source of Truth

The project keeps per-environment `.env` files under `infra/secrets/`:

```
infra/secrets/
  .gitignore        # auto-created by project inception; ignores *.env
  README.md         # auto-created by project inception; explains usage
  example.env       # auto-emitted by `./bin/docex compile`; committed
  dev.env           # operator-maintained, gitignored
  test.env          # operator-maintained, gitignored
  stage.env         # operator-maintained, gitignored
  prod.env          # operator-maintained, gitignored
```

`example.env` is emitted by the compiler from two sources — the `env:` blocks of the project's backing-service engines (in the transfer tables) and the `secrets:` block of each core service. Every secret any service requires shows up there with an empty placeholder, grouped by the service that introduced it. The developer copies it to `<env>.env` and fills in real values per environment.

This file shape is the single canonical surface for project secrets across both foundations. There is no other secret-handling mechanism; in particular, no env-vars-in-the-shell, no inline `infra.yml` secrets, no per-service config files.

## Materialization at Release

The `.env` is the canonical source; the deployment target is overwritten *from* it on every release.

- **Fixed (Ansible):** the playbook reads `infra/secrets/<env>.env` from the control node and renders it onto the host as `/opt/<project>/<env>/.env`. Docker Compose reads this file when starting containers.
- **Elastic (OpenTofu):** before `tofu apply` runs, `./bin/docex release` reads `infra/secrets/<env>.env` and pushes each `KEY=value` pair to SSM Parameter Store at `/<project>/<env>/KEY` as a `SecureString` (encrypted with the default `aws/ssm` KMS key). The emitted HCL then provisions ECS task definitions whose `secrets[]` blocks reference those SSM paths; ECS resolves the values when starting tasks.

In both cases, the `.env` wins on every release. Manual edits to the host `.env` (fixed) or SSM parameters (elastic) are overwritten on the next deploy. This is by design: it preserves the deterministic doctrine, but means the operator must use the `.env` for everything, including hot-fixes.

## How Secrets Reach Application Code

A core service's container environment is *identical in shape* across both foundations:

| Foundation | Mechanism | Effective container env |
| ---------- | --------- | ----------------------- |
| Fixed | Compose `environment:` line `DATABASE_USER: ${POSTGRES_USER}` reading from `/opt/<project>/<env>/.env` | `DATABASE_USER=<value of POSTGRES_USER in .env>` |
| Elastic | ECS `secrets[]` entry `{ name = "DATABASE_USER", valueFrom = "/<project>/<env>/POSTGRES_USER" }` | `DATABASE_USER=<value of POSTGRES_USER in SSM>` |

The container sees the same key (`DATABASE_USER`) and the same value on both foundations. Only the delivery mechanism underneath differs.

The compiler binds these end-to-end: when a core service declares `env: DATABASE_USER: ${backing_services.database.user}` in `infra.yml`, the `database.user` magic ref resolves (per the relational_db engine's `provides:` block) to the runtime ref `$[POSTGRES_USER]`, which the compiler emits as a compose `environment:` line on fixed or an ECS `secrets[]` entry on elastic, both pointing at the same `.env`/SSM key `POSTGRES_USER`. See [transfer_tables.md § env](./transfer_tables.md#anatomy-of-a-role-definition) for the full mechanism.

## Parts-Only Rule

Engines never expose a pre-composed string for a secret-containing value (e.g., no `database.url` part that includes the password inline). The application must compose its own connection string from the discrete parts (`host`, `port`, `db`, `user`, `password`) at startup.

This rule is what keeps the secret-flow surface clean across both foundations. ECS `secrets[]` can only deliver each secret as a whole standalone env var; it cannot embed one inside a larger value without materializing that value as plaintext in the task definition and Tofu state. Parts-only is the single model that keeps `provides:` identical across foundations.

As a consequence, secrets like `$[POSTGRES_USER]` and `$[POSTGRES_PASSWORD]` never appear as inline values in compiled artifacts — they flow through compose's runtime substitution (fixed) or the ECS `secrets[]` block (elastic), staying out of any persisted task definition or compose snapshot.

The compiler enforces this at compile time: a magic ref that would embed a secret inside a larger value fails compile with a clear error. See [transfer_tables.md § provides](./transfer_tables.md#anatomy-of-a-role-definition) for the full rule.

## Doctrine-Injected Secrets

A small set of secrets are added by the doctrine itself rather than by project services. These appear in `example.env` for the envs that need them, and the operator fills them in like any other secret:

| Secret | Required envs | Source | Consumer |
| ------ | ------------- | ------ | -------- |
| `TELEMETRY_API_KEY` | stage, prod | Obtained from the project's observability backend (HyperDX or equivalent) | The OTel sidecar paired with each core service. See [telemetry_infra.md](./telemetry_infra.md). |

Future doctrine extensions may add more. The general rule: any secret introduced by `docex`'s own machinery (not by a project-declared service) is documented as a doctrine-injected entry in `example.env`, with its purpose called out in the section comment.

## Caveats

- **No externally-rotated secrets.** Phase 1 assumes all secrets are project-controlled. AWS-managed RDS rotation, third-party-issued tokens, or anything else that updates outside the `.env` would be clobbered on each release. Projects that need this will require a future doctrine extension (likely a way to mark certain secret names as externally-managed).
- **Trust model.** Real production secret values sit on every operator's laptop. The doctrine assumes the operator's machine is trusted; compliance-driven environments that mandate "secrets only live in the vault" should not adopt this pattern as-is.
- **Synchronization across operators.** When multiple operators share a project, they must keep their `<env>.env` files in sync out-of-band (a password manager, an encrypted shared file, etc.). The doctrine does not provide synchronization machinery.
- **Rotation.** The doctrine does not provide secret rotation — changing a value in `<env>.env` and running `release` will swap it on the target, but coordinated rotation across multiple secrets, with a window where both old and new are accepted, is not modeled.
