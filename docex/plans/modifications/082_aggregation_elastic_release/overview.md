# Mod 082 — Aggregation on the elastic stage/prod release path

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 7 of 11). Extends aggregation to the **elastic** stage/prod release,
replacing the single-category `_push_secrets` with a three-category SSM push.

## Why

`config_and_secrets.md §4.2`: on elastic there is no aggregate *file* — "the SSM
prefix `/<project>/<env>/` **is** the aggregate." The authoritative TTE store is
SSM itself (ECS reads it). So aggregation on elastic *is* the push, with
per-category behavior:

| Category | SSM behavior | SSM type |
| -------- | ------------ | -------- |
| **TTE** (minted) | **put-if-absent** — preserve the live write-once value; mint only when SSM has none | `SecureString` |
| **secret** | overwrite (`Overwrite=True`) | `SecureString` |
| **config** | overwrite (`Overwrite=True`) | `String` (non-secret; fine in task defs/logs) |

Put-if-absent on TTE is the elastic form of the authoritative-store rule: a lost
local copy can never clobber the live RDS credential, because docex reads SSM
before minting and only mints when SSM is empty (first release).

Today `_release_elastic` step 1 is `_push_secrets`, which reads
`infra/secrets/<env>.env` and pushes **every** key as `SecureString` (with legacy
quote-stripping). Under the split, that file no longer holds TTE keys, config is
separate, and values are raw-literal (no quote-stripping). This mod replaces it.

## Mechanism

New `aggregate_elastic(ctx, *, env, aws) -> int` (in `orchestrate/aggregate.py`):

1. **Defensive disjointness** — `tte_keys ∪ secrets-file keys ∪ config-file keys`
   must be pairwise disjoint (compile guarantees the *declared* categories are;
   the operator-maintained files are re-checked, mirroring the fixed path's
   `_disjoint_union` guard). A collision raises `AggregationError`.
2. **`ensure_tte_elastic`** — for each minted key, `ssm_get_parameter` at
   `/<project>/<env>/<key>`; if absent, `generate()` + put `SecureString`
   (put-if-absent). Present → leave (no re-mint, no clobber).
3. **secrets** — read `infra/secrets/<env>.env` (standard raw-literal form);
   push each `SecureString`, `Overwrite=True`.
4. **config** — read `infra/config/<env>.env`; push each `String`,
   `Overwrite=True`.

Ordering: this runs as `_release_elastic` step 1 (before first-release detection
and `tofu apply`), so the RDS `data "aws_ssm_parameter"` and ECS `secrets[]`
resolve at apply. `dry_run` skips it entirely (already side-effect-free per the
existing branch). `skip_migrations` (rollback) is unaffected — put-if-absent
means the live TTE is preserved while the older secrets/config are re-pushed.

## AWS client surface

- Add `AWSClient.ssm_get_parameter(name) -> str | None` (protocol + boto3 impl:
  `get_parameter(WithDecryption=True)`, `ParameterNotFound → None`).
- Extend `ssm_put_parameter(name, value, *, overwrite=True, param_type="SecureString")`
  so config can be pushed as `String`. Default keeps every existing caller
  identical.

## Scope

**In:** `ssm_get_parameter` + `param_type` (`aws/client.py`, `aws/boto3_client.py`);
`ensure_tte_elastic` + `aggregate_elastic` (`orchestrate/aggregate.py`); replace
`_push_secrets` in `_release_elastic` (remove the superseded quote-stripping
parser); strip engine-managed `POSTGRES_*` from the **elastic** stage/prod
fixture secrets; unit tests with a fake AWS client backed by an in-memory SSM.

**Out:** fixed release (Mod 081, done); the `secrets`/`config` tooling
(Mods 083/084). Real end-to-end validation is the elastic smoke walk (operator,
deferred). Unit tests mock the AWS client — flag that in the report.

## Doctrine anchors
- `config_and_secrets.md §4.2` (elastic: SSM prefix is the aggregate; TTE put-if-absent, secrets/config overwrite; String vs SecureString), `§ Materialization at Release` (elastic), `§ authoritative-store rule` (elastic store = SSM).
- `release_flow.md § Elastic-foundation flow` step 1 (SSM push) — narrative updated in Mod 086.

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` (this mod) ⇄ `tests/**`. No `tables/` or
doctrine change.
