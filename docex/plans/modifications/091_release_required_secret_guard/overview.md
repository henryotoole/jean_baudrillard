# Mod 091 — Release-time required-secret guard

## Problem

An unset required secret is caught **nowhere** on the path to a stage/prod
deploy. `docex compile` validates only the *declared* category disjointness
(rules 16/20 in `cicl/validate.py`) — it never reads the operator's
`infra/secrets/<env>.env` value files. Aggregation
(`orchestrate/aggregate.py`) is a plain union of whatever sits on disk: a
missing or empty required secret flows through as an empty value and only
surfaces as a container failure at runtime — or a silently-broken prod.

## Change

Add a **precondition to `docex release`** (stage/prod): before any side effect,
verify that every required secret has a non-empty value in
`infra/secrets/<env>.env`. If any is unset, abort the release with a clear
message naming each unset key and its `docex secrets set <env> <KEY>`
remediation.

This is the doctrine's new **Required-Secret Guard**
(`config_and_secrets.md § Required-Secret Guard`, added alongside this mod).

### Definitions (match the doctrine)

- **Required secret** = any key in `secret_manifest(infra, tables)`
  (`cicl/categories.py`): core `secrets:` blocks + backing engines'
  `kind: secret` vars + doctrine-injected secrets (`TELEMETRY_API_KEY`).
- **Unset** = absent from `infra/secrets/<env>.env` **or** present with an
  empty value (`""`). This matches the `SET`/`UNSET` convention already used by
  `secrets status` (`secretsmgmt/engine.py`, `val != ""`).

### Scope (deliberate, per the doctrine section)

- **Secrets only.** TTE is docex-minted (put-if-absent during aggregation), so
  it is never operator-unset; config is non-secret and may legitimately be
  empty. Neither gates a release.
- **stage/prod only.** The guard lives in `run_release`, which already refuses
  `dev`/`test`. Local iteration via `docex up` is never blocked.
- **Rollback is not gated.** Rollback (`pipeline/rollback.py`) calls
  `_release_fixed` / `_release_elastic` *directly*, bypassing `run_release`, so
  placing the guard in `run_release` leaves rollback's emergency, code-only
  semantics untouched. This is intentional — do **not** add the guard to the
  branch functions or to rollback.

## Placement rationale

The guard goes in `pipeline/release.py::run_release`, immediately after the
existing env/`infra`-present checks and **before** the `foundation` branch. At
that point:

- It is foundation-agnostic — the secrets file is the same on both foundations,
  so one check covers fixed and elastic.
- It runs before every side effect: aggregation (`aggregate_fixed_prod` /
  `aggregate_elastic`), the SSM push, and the ansible/tofu apply all happen
  inside the branch functions that follow.
- It naturally excludes rollback (which never enters `run_release`).

## Why not compile-time

An earlier option (a compile-time drift *advisory*) was rejected: `compile` is
offline-pure, runs inside `check`'s ephemeral worktree where the gitignored
value files are absent (guaranteed false positives), returns hard-error
`ValidationIssue`s rather than warnings, and runs once project-wide rather than
per-env. Release is the point where a missing value actually bites, so a hard
guard there solves the problem completely and cleanly. See the conversation that
spawned this mod.

## Affected artifacts

| Layer | File | Change |
| ----- | ---- | ------ |
| Doctrine | `doctrine/.../config_and_secrets.md` | `§ Required-Secret Guard` (done with this mod) |
| Code | `src/docex/errors.py` | new `RequiredSecretsUnset(DocexError)` |
| Code | `src/docex/pipeline/release.py` | `_require_secrets_present` helper + call in `run_release` |
| Tests | `tests/unit/...` | guard unit tests |
| Core docs | `docex/plans/core/release_flow.md` | updated by the design agent post-impl (not in implementation.md) |

No transfer-table change, no contract change, no boundary crossed → unit tests
only (per `docex_process.md`).

## Versioning

Folds into the open **1.5.0** release (envmageddon theme — completes the
config/secrets story). No version bump; a CHANGELOG line under `[1.5.0]` is
added in the doc/changelog step.
