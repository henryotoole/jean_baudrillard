# Mod 075 — Implementation steps

## 1. `src/docex/emit/compose.py`

- `_wrapped_job_command(command, env_file_target, secret_exports)`: after
  sourcing, emit one `export <consumer_key>="$$<provider_var>"` per pair
  (sorted), then `exec <cmd>`. `$$` so Compose passes a literal `$`.
- `_ofelia_ini(svc, project_dns_label, env, env_file_source)`:
  - Split `svc.env` into non-secret pairs (inlined) and `secret_exports`
    (pairs of `(consumer_key, provider_var)` from `$[VAR]` values).
  - Emit `environment = KEY=value` as one **bare** line per non-secret pair
    (gcfg list form — NOT a JSON array).
  - Emit `volume = <env_file_source>:/run/job.env:ro` bare.
- `emit_compose` scheduler loop: compute `env_file_source` —
  `${DOCEX_SECRETS_ENV_FILE}` for dev/test, `/opt/<compiled.project>/<env>/.env`
  for stage/prod — and pass it in (drop the old relative `env_file_host_path`).

## 2. `compose_up` extra_env plumbing

- `docker/client.py` + `docker/subprocess_client.py`: add
  `extra_env: dict[str,str] | None = None` to `compose_up`; `_run` merges it
  over `os.environ` for that one subprocess.
- `tests/conftest.py` `FakeDockerClient.compose_up`: accept + record
  `extra_env` as a `compose_up_extra_env` call entry.

## 3. `src/docex/orchestrate/up.py`

Pass `extra_env={"DOCEX_SECRETS_ENV_FILE": <abs infra/secrets/<env>.env>}` to
`compose_up`.

## 4. Tests (`tests/unit/test_scheduler.py`, `test_orchestrate_up.py`)

- Bare gcfg form (no `[` outside the section header; `environment = K=V` lines).
- Secret split: no secret key/var in any `environment` line.
- Command re-exports `export DATABASE_USER="$$POSTGRES_USER"` etc.; ends in
  `exec …`.
- Mount source: `${DOCEX_SECRETS_ENV_FILE}` in dev, baked `/opt/…` in stage.
- `up dev` passes `DOCEX_SECRETS_ENV_FILE`.

## 5. Doctrine

`scheduler.md` § Fixed Foundation + § Env and secret delivery — see overview.

## 6. Verify

`pytest tests/unit/test_scheduler.py tests/unit/test_orchestrate_up.py`, then
full unit suite. Live fixed dev fire (manual, documented in overview).
