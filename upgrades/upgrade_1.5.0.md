---
version: "1.5.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 1.5.0

This release ("envmageddon") splits the single per-environment `<env>.env` file
into **three source categories** by provenance, and adds tooling to manage them:

- **TTE** — engine credentials `docex` *mints* (transfer-table `kind: minted`
  env vars, e.g. `POSTGRES_PASSWORD`). Stored in `infra/tte/<env>.env`, never
  hand-edited, never committed.
- **secrets** — operator-supplied secrets (a core service's `secrets:` block +
  the doctrine-injected `TELEMETRY_API_KEY`). Still `infra/secrets/<env>.env`.
- **config** — declared, non-secret, per-env values (a core service's new
  `config:` block). Values in `infra/config/<env>.env`, declarations in
  `infra.yml`.

An **aggregation** step re-merges the three into the same container-facing env
the services already consumed, so **application code and the container env are
unchanged** — only the source layout and the release-time materialization move.
New `docex secrets` / `docex config` subcommands manage the files without
exposing secret values. See
[`config_and_secrets.md`](../doctrine/infrastructure/specifics/config_and_secrets.md)
for the full model and the [1.5.0 CHANGELOG entry](../CHANGELOG.md).

**Why this is `incremental`, not a rebuild.** The compiled infrastructure
*shape* is unchanged — no resource is renamed, no `tofu` state is invalidated,
no container env var changes name or value. The upgrade is a repin + a
source-file reorganization + a recompile + a redeploy. The one thing you must
get right is **preserving the existing engine credential** so a mint doesn't
lock you out of a running database — see [§ Preserve the live engine
credential](#preserve-the-live-engine-credential), the load-bearing step.

---

## Machine sync

Run the **`doctrine-update`** skill (or by hand: `git pull` in
`~/.claude/jean_baudrillard`, then `bash setup.sh`). That lands machine-side:

- the **`docex:1.5.0` image** (built locally on cut);
- the **updated canonical shim** (`docex/bin/docex`) — it now allocates a tty
  (`-t -i`) when you run interactively, so `docex secrets set`'s no-echo prompt
  works. Backward-compatible: unchanged for non-interactive/piped runs.

Nothing breaks if a project lags on an older pin — old images keep working.

---

## Project upgrade

Do this per consuming project (the `project-upgrade` skill drives it).

### 1. Repin + sync the shim

Bump `project.yml`'s `docex_version` to `1.5.0` and re-run the project installer
(`docex_install.sh`) so the project gets the new shim. Commit on a feature
branch as usual.

### 2. Add the category directories

Create `infra/tte/` and `infra/config/`, each with a `.gitignore` (ignore the
value files, keep the dir) and a short `README.md`, mirroring `infra/secrets/`.
Add to the project root `.gitignore`:

```gitignore
infra/tte/*
!infra/tte/.gitignore
!infra/tte/README.md
infra/config/*
!infra/config/.gitignore
!infra/config/README.md
```

(`.docex/agg/<env>.env` — the derived aggregate — is already covered by the
existing `.docex/` ignore.)

### 3. Preserve the live engine credential

**This is the step that prevents a lockout.** Under 1.5.0 the minted engine
credential (`POSTGRES_PASSWORD`) is read from its **authoritative store**
put-if-absent — `docex` mints a fresh one only when the store has none. A
*running* database already holds the *old* credential, so the store must present
that old value before the first 1.5.0 release, or the release mints a new
password the database never accepted → lockout. The store differs by
circumstance:

- **elastic `stage`/`prod` — automatic, no action.** The authoritative store is
  SSM at `/<project>/<env>/POSTGRES_PASSWORD`, and your prior releases already
  pushed the live value there. `ensure_tte` finds it and leaves it untouched.
  Just **do not** re-add `POSTGRES_PASSWORD` to the secrets file (step 4).
- **fixed `stage`/`prod` — SEED THE HOST STORE FIRST.** The authoritative store
  is the host `/opt/<project>/<env>/tte.env`, which does not exist on an
  upgrading host. Before the first 1.5.0 release, SSH to the host and seed it
  from the value already in the live env file:

  ```sh
  # on the deploy host, per env:
  grep '^POSTGRES_PASSWORD=' /opt/<project>/<env>/.env \
    > /opt/<project>/<env>/tte.env
  chmod 600 /opt/<project>/<env>/tte.env
  ```

  (Repeat for every minted key if the project declares more than one.) Skip this
  and the first release mints a new password against a database still holding the
  old one.
- **`dev`/`test` — data is disposable.** The local store is
  `infra/tte/<env>.env`. Either seed it the same way from your current values, or
  simply recreate the postgres volume (`docex envinfra down <env>`, remove the
  `*_data` volume, `docex envinfra up <env>`) and let the fresh mint initialize a
  fresh database.

### 4. Reconcile the secrets file

Run `docex secrets scaffold <env>` per env. It derives the required-secret key
set on demand from `secret_manifest` (core `secrets:` + backing `kind: secret` +
`TELEMETRY_API_KEY`; **no** `POSTGRES_*`) — no committed manifest file is emitted
(`compile` writes nothing under `infra/secrets/`).

```sh
./bin/docex secrets scaffold <env>   # per env
```

`scaffold` reconciles `infra/secrets/<env>.env` against that key set — it
**removes the now-unmanaged engine keys** (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`, `POSTGRES_HOST`, …) and **preserves** your real secret values
(`TELEMETRY_API_KEY`, API keys). Fill any key `docex secrets status <env>`
reports `UNSET`.

### 5. Move per-env non-secret values to `config` (if any)

If you previously smuggled a per-env non-secret value (e.g. a third-party URL
that differs by environment) into the secrets file or hard-coded it, declare it
now in the consuming core service's new `config:` block in `infra.yml`, then set
the per-env values:

```sh
./bin/docex config set <env> PARTNER_URL https://...
```

Config values are non-secret and LLM-readable; `config status`/`config get`
print them. Skip this step if the project has no such values.

### 6. Recompile, redeploy

Recompile, commit the branch, and run the normal pipeline
(`check → merge → containerize → release stage → stagetest → release prod`).
Because aggregation reproduces the same container env, a converged env sees no
change beyond the (preserved) credential and any config you added.

---

## Verification

- `docex secrets status <env>` — every required secret `SET`, no stray
  `POSTGRES_*` key.
- `docex config status <env>` — declared config keys present with values.
- After release: the app connects to its database (the credential was
  preserved), and `/health` is green.
- `git status` — `infra/tte/`, `infra/config/`, and `infra/secrets/` value files
  are ignored; only their `.gitignore`/`README.md` are tracked (mod 092 removed
  the committed `example.env`).

---

## Fixed-foundation only: stage/prod Compose stack rename (mod 090)

On **fixed** foundations, 1.5.0 scopes the release playbook's Compose **project
name** from the unscoped `<env>` (derived from the `/opt/<project>/<env>` deploy
dir) to `<dns_label>-<env>` — matching how docex already names dev/test stacks.
This closes a latent collision between two fixed projects sharing one host.

**If you already have a fixed `stage`/`prod` deployment**, the first 1.5.0
release renames the project. Because the compiled compose file uses explicit
`container_name`s, the newly-named `up` would collide with the still-running
old-named stack rather than adopt it. One-time step **before** the first 1.5.0
release, per deployed env, on the target host:

```bash
docker compose -p <env> -f /opt/<project>/<env>/docker-compose.yml down
```

This stops the old-named stack while **keeping named volumes** (your database
survives — and the TTE credential is preserved per the aggregation change above,
so the re-created stack reconnects). The next `docex release <env>` brings the
stack back up under `<dns_label>-<env>`. Greenfield/first-ever deployments need
nothing. Elastic foundations are unaffected (ECS, not Compose).

---

## Rollback

Standard `docex rollback <env> <prev_version>` applies — the rolled-back code
reads the same preserved credential, and `rollback` re-pushes the older
secrets/config while leaving the live TTE value untouched (put-if-absent). If you
must revert the *repin*, the old `docex` version reads the old `<env>.env`
layout; keep a copy of the pre-split secrets file until the upgrade is verified.
