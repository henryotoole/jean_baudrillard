# Mod 081 — Aggregation on the fixed stage/prod release path

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 6 of 11). Extends aggregation to the **fixed** stage/prod release.

## Why

`config_and_secrets.md § Aggregation` + `§4.2`: on fixed stage/prod the
authoritative TTE store is the **host** `/opt/<project>/<env>/tte.env` (the store
the host's containers read), and the aggregate is the host runtime env file
`/opt/<project>/<env>/.env` — **same path as today**, now merge-fed. The host is
authoritative to prevent the lost-local-copy → re-mint → lockout hazard
(`§ authoritative-store rule`).

Today the ansible playbook copies `.env` straight from the operator's local
`infra/secrets/<env>.env`. That file no longer holds TTE/config, so the release
must instead build the aggregate and render *that*.

## Mechanism (one SSH read + ansible for the rest)

Generation is impure Python (never ansible/Jinja). But the host is authoritative,
so docex must read the host's current TTE before minting:

1. **`ensure_tte` (fixed)** — docex SSH-**captures** the host
   `/opt/<project>/<env>/tte.env` (a quiet `cat`), parses it, mints only the
   *missing* minted keys (preserving every host value), and stages the resulting
   superset to a control-node file `.docex/agg/<env>.tte.env`.
2. **aggregate** — `tte ∪ local secrets ∪ local config` → `.docex/agg/<env>.env`.
3. **ansible renders both to the host** — the playbook copies the staged
   aggregate → host `.env` and the staged store → host `tte.env`, via two
   `--extra-vars` paths (the runner already supports `extra_vars`). Copying the
   store back is safe: it is always a superset of what the host had (host values
   preserved + newly-minted added), so a converged host is a no-op and a
   lost-local-copy never triggers a spurious re-mint.

The host address is `compiled.subdomain` (`<env>.<dns_label(project)>.<apex>`),
the SSH user is `deploy`, the key is `infra/deploy_creds/<env>` — the same
identity ansible and the preinfra probe already use.

## Threading (contained)

`_release_fixed` gains an injected `SSHClient` (mirrors how `aws`/`tofu` are
threaded). The dispatcher (`__main__._cmd_release`) and `run_rollback` both build
and pass one. Rollback reuses `_release_fixed`, so it also gains the `ssh`
transport and — because it recompiles + mirrors gitignored inputs into a
worktree — its mirror step adds `infra/config/<env>.env` alongside the secrets
it already mirrors.

`docex migrate stage/prod` (fixed, `--tags migrate`) does **not** rebuild the
aggregate — it reads the host `.env` a prior release already rendered; the
untagged copy tasks are skipped, so their `extra_vars` paths are never rendered.

## Scope

**In:** `SSHClient.capture` (protocol + subprocess impl); `ensure_tte`/aggregate
fixed stage/prod branch (`orchestrate/aggregate.py`); `_release_fixed` +
dispatcher + `run_rollback` ssh threading + rollback config mirror; playbook
template (render `.env` from the aggregate, add the `tte.env` copy task); strip
engine-managed `POSTGRES_*` from the **fixed** stage/prod fixture secrets; unit
tests with a fake SSH + fake ansible runner.

**Out:** elastic stage/prod (Mod 082). Real end-to-end validation is the fixed
smoke walk (operator, deferred past this autonomous run) — unit tests here mock
SSH + ansible, so the SSH command strings and playbook YAML are only fully
proven by that walk. Flag this in the mod report.

## Doctrine anchors
- `config_and_secrets.md §4.2` (fixed prod carries two host files: `.env` aggregate + persistent `tte.env`), `§ authoritative-store rule`, `§ Materialization at Release` (fixed = ansible renders the aggregate).
- `release_flow.md § Fixed-foundation flow` / `§ Rollback flow` (the mirror step).

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` + `templates/` (this mod) ⇄ `tests/**`. The
release_flow.md core doc narrative is updated in Mod 086.
