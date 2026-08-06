# secrets

Environment-specific runtime values — database passwords, API keys, signing keys — that must not be committed. Doctrine uses a unified `.env`-as-source-of-truth model across both foundations.

```
infra/secrets/
  example.env       # auto-emitted by `docex compile`; committed
  dev.env           # operator-maintained, gitignored
  test.env          # operator-maintained, gitignored
  stage.env         # operator-maintained, gitignored
  prod.env          # operator-maintained, gitignored
```

The compiler reads each backing service's transfer-table `env:` block and emits `example.env` with one section per service listing every required key. The operator copies it to `<env>.env` and fills in real values per environment.

Materialization at release:

- **Fixed:** Ansible renders `<env>.env` onto the host as `/opt/<project>/<env>/.env`; docker-compose reads it at container start.
- **Elastic:** `docex release` pushes each key to SSM Parameter Store at `/<project>/<env>/<KEY>` as a `SecureString`; ECS task definitions reference those SSM paths via `secrets[]`.

The `.env` wins on every release — manual edits to the deployed copy are clobbered. This keeps the deterministic doctrine intact but means rotation requires editing the `.env`. See `infrastructure/specifics/release.md`.
