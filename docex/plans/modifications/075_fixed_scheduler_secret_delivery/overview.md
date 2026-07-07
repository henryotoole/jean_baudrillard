# Mod 075 — Make the fixed (Ofelia) scheduler actually run

## Problem

The first live fire of a fixed `scheduler` (a `reaper` job in the fixed smoke
project) proved the mod-055 fixed/Ofelia path **never worked end-to-end**. Three
independent bugs in `docex`'s emit (`src/docex/emit/compose.py`), all fixed-only
(elastic uses the ECS task-def `secrets[]`/SSM path, which is sound):

- **Bug C — wrong Ofelia INI syntax (the root blocker).** The emitter wrote
  `environment` and `volume` as JSON arrays (`environment = ["K=V", …]`,
  `volume = ["src:dst:ro"]`). Ofelia parses its INI with `gcfg`, where a
  repeatable list field is one **bare** `key = value` line per entry. Ofelia took
  the literal `["…` as a value → `invalid mode: ro` / `invalid characters for a
  local volume name`. No job ever ran.
- **Bug A — relative env-file mount.** Even with syntax fixed, the mount source
  was the project-relative `infra/secrets/<env>.env`. Ofelia spawns the job via
  the Docker API (not Compose), which requires an **absolute** host path.
- **Bug B — secret name mismatch.** The sourced `.env` carries the *provider*
  secret names (`POSTGRES_USER`); the job reads the *consumer* keys
  (`DATABASE_USER`). Compose remaps these for ordinary services and the migrate
  one-off; the Ofelia job never got the remap → `KeyError`.

The scheduler *application* code is correct — proven by running the job manually
with the right env. These are all docex emit/orchestration bugs.

## Change (all fixed-only; elastic untouched)

In `src/docex/emit/compose.py::_ofelia_ini` / `_wrapped_job_command`:

- **Bug C:** emit `environment` and `volume` as bare, repeated gcfg lines — one
  `environment = KEY=value` per non-secret var; a single bare
  `volume = <src>:/run/job.env:ro`. No JSON arrays.
- **Bug A:** the `volume` source is an **absolute** path. In fixed
  `stage`/`prod` it is the deterministic ansible deploy path
  `/opt/<project>/<env>/.env`, baked at compile (matches `emit/ansible.py`'s
  `deploy_root` and the migrate one-off's `env_file`). In `dev`/`test` the path
  is machine-specific, so baking it would break compile determinism; the emitter
  writes `${DOCEX_SECRETS_ENV_FILE}` and `docex up` sets that var (via a new
  `extra_env` on `compose_up`) to the absolute `infra/secrets/<env>.env`, which
  Compose interpolates into the rendered config.
- **Bug B:** the command wrapper re-exports each secret from its provider var:
  `sh -c '. /run/job.env && export DATABASE_USER="$POSTGRES_USER" && … && exec
  <cmd>'`. The `$`-refs are emitted **doubled** (`$$`) so Compose passes the
  literal `$POSTGRES_USER` through to the config and the *job* shell expands it
  at run time — the secret value never lands in the rendered config.

Supporting changes: `compose_up` (protocol + subprocess + fake) gains an
`extra_env` kwarg; `orchestrate/up.py` passes `DOCEX_SECRETS_ENV_FILE`.

## Doctrine

`scheduler.md` § Fixed Foundation (INI example) + § Env and secret delivery
rewritten to: (1) show the bare gcfg list form and warn that a JSON array is
mis-parsed; (2) require an absolute mount source (baked `/opt/…` on stage/prod,
`${DOCEX_SECRETS_ENV_FILE}` on dev/test); (3) describe the provider→consumer
re-export with the doubled-`$$` rule. Operator-approved (file-sourcing posture
preserved — secrets stay in the `.env`, never inlined into the rendered config).

## Verification

- Unit: bare-format assertions, absolute-mount assertions (dev var + baked
  stage path), secret re-export assertions, and the `up` `extra_env` pass-through.
- **Live (fixed dev):** the reaper job fires on schedule via docex's real
  emitted compose, sources the env file, re-exports the DB secrets, connects to
  postgres, and deletes exactly the expired processed pings. Ofelia logs
  `failed: false … error: none`.
