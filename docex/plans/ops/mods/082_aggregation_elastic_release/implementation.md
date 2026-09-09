# Mod 082 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. **Do not edit doctrine files or
`tables/`.**

## Context (current shapes)

- `src/docex/aws/client.py` — `AWSClient` Protocol:
  `ssm_put_parameter(name, value, *, overwrite=True)` (docstring says
  `SecureString`), `ssm_delete_parameters(path_prefix)`.
- `src/docex/aws/boto3_client.py:96` — `ssm_put_parameter` does
  `ssm.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=overwrite)`.
- `src/docex/pipeline/release.py`:
  - `_release_elastic(...)`: after the `dry_run` early-return, calls
    `pushed = _push_secrets(aws, env_file, project=, env=)` (step 1), then
    first-release detection + apply/migrate ordering.
  - `_push_secrets(aws, env_file, *, project, env)` (~line 375) reads the file
    line-by-line, strips surrounding quotes, and `ssm_put_parameter(path, value,
    overwrite=True)` each. **Superseded** by this mod.
- Mod 080: `orchestrate/aggregate.py` — `read_env_file`, `_secrets_path`,
  `_config_path`, `_disjoint_union`, `minted_policies`, `generate`,
  `AggregationError`. Mod 081 added `parse_env_text`, `ensure_tte_fixed`,
  `aggregate_fixed_prod`.
- The elastic SSM path form is `/<project>/<env>/<KEY>` (see current
  `_push_secrets`: `f"/{project}/{env}/{key}"`).
- Tests use a fake AWS client (grep `tests/` for the class used by
  `test_pipeline_release.py` — likely a `FakeAWSClient`/stub with recorded SSM
  calls). Extend it with an in-memory SSM dict + `ssm_get_parameter` + the
  `param_type` kwarg.

## Step 1 — AWS client: `ssm_get_parameter` + `param_type`

`aws/client.py` (Protocol):

```python
    def ssm_get_parameter(self, name: str) -> str | None:
        """Return the decrypted value of the SSM parameter at ``name``, or
        None if it does not exist. Used for TTE put-if-absent (SSM is the
        authoritative store on elastic)."""
        ...
```

Change `ssm_put_parameter` signature to
`ssm_put_parameter(self, name, value, *, overwrite=True, param_type="SecureString")`
and document `param_type` ∈ {`SecureString`, `String`}.

`aws/boto3_client.py`:
- `ssm_put_parameter`: pass `Type=param_type` instead of the hardcoded
  `"SecureString"`.
- `ssm_get_parameter`:
  ```python
  def ssm_get_parameter(self, name: str) -> str | None:
      ssm = self._client("ssm")
      try:
          resp = ssm.get_parameter(Name=name, WithDecryption=True)
      except ssm.exceptions.ParameterNotFound:
          return None
      return resp["Parameter"]["Value"]
  ```
  (Match how other boto3 methods obtain the client — `self._client("ssm")` per
  the existing code.)

## Step 2 — `ensure_tte_elastic` + `aggregate_elastic` (`orchestrate/aggregate.py`)

```python
def _ssm_path(project, env, key) -> str:
    return f"/{project}/{env}/{key}"

def ensure_tte_elastic(ctx, *, env, aws) -> int:
    """Mint-if-absent each minted key into SSM as SecureString (put-if-absent).
    SSM is the authoritative store on elastic — a present value is left
    untouched (write-once). Returns the count newly minted."""
    project = ctx.project.name
    policies = minted_policies(ctx.infra, ctx.transfer_tables)
    minted = 0
    for key, policy in policies.items():
        path = _ssm_path(project, env, key)
        if aws.ssm_get_parameter(path) is None:
            aws.ssm_put_parameter(path, generate(policy),
                                  overwrite=False, param_type="SecureString")
            minted += 1
    return minted

def aggregate_elastic(ctx, *, env, aws) -> int:
    """Push all three categories to the SSM prefix /<project>/<env>/. TTE
    put-if-absent (SecureString), secrets overwrite (SecureString), config
    overwrite (String). Returns total params written (minted + pushed)."""
    project = ctx.project.name
    tte_keys = set(minted_policies(ctx.infra, ctx.transfer_tables))
    secrets = read_env_file(_secrets_path(ctx, env))
    config = read_env_file(_config_path(ctx, env))
    # Defensive disjointness (compile guarantees declared categories; files are
    # operator-maintained). Mirror the fixed path's guard.
    overlaps = (
        (tte_keys & set(secrets)) | (tte_keys & set(config)) | (set(secrets) & set(config))
    )
    if overlaps:
        raise AggregationError(
            f"SSM aggregation key collision for env {env!r}: {sorted(overlaps)} "
            f"appear in more than one category — should have been caught at "
            f"compile; check infra.yml / the secrets & config files."
        )
    minted = ensure_tte_elastic(ctx, env=env, aws=aws)
    n = minted
    for key, value in secrets.items():
        aws.ssm_put_parameter(_ssm_path(project, env, key), value,
                              overwrite=True, param_type="SecureString")
        n += 1
    for key, value in config.items():
        aws.ssm_put_parameter(_ssm_path(project, env, key), value,
                              overwrite=True, param_type="String")
        n += 1
    return n
```

## Step 3 — `_release_elastic` uses `aggregate_elastic` (`pipeline/release.py`)

- Replace the step-1 block
  `pushed = _push_secrets(aws, env_file, project=project_name, env=env)` /
  its print with:
  ```python
  from docex.orchestrate.aggregate import aggregate_elastic
  pushed = aggregate_elastic(ctx, env=env, aws=aws)
  print(f"release: pushed {pushed} configurable value(s) to SSM under "
        f"/{project_name}/{env}/ (TTE minted-if-absent, secrets/config overwritten)")
  ```
  Keep this AFTER the `dry_run` early-return (so dry-run stays side-effect-free)
  and BEFORE first-release detection / apply — unchanged position.
- The `env_file` existence check at the top of `_release_elastic` currently
  guards `infra/secrets/<env>.env`. Keep a check, but the secrets file may now
  be legitimately empty/absent if a project has no bespoke secrets — however
  `TELEMETRY_API_KEY` is doctrine-injected and required on stage/prod, so the
  file should exist. Keep the existing "expected env secrets at ..." guard
  (secrets file is still where TELEMETRY_API_KEY lives).
- Remove `_push_secrets` (now unused). Grep for other callers first; if none,
  delete it and its `SSMPushFailed` usage there (keep the `SSMPushFailed` error
  class — `aggregate_elastic` may raise it, or wrap put failures. If you want
  the same fail-fast-on-push-error behavior, catch the boto exception in
  `aggregate_elastic` and raise `SSMPushFailed`; otherwise let it propagate.
  Prefer keeping `SSMPushFailed` semantics: wrap the `ssm_put_parameter` calls).

## Step 4 — elastic stage/prod fixture cleanup

Strip engine-managed `POSTGRES_*` (and the placeholder `POSTGRES_DB`) from the
**elastic-foundation** stage/prod fixture secrets so `aggregate_elastic`'s
disjointness guard doesn't fire (a `POSTGRES_PASSWORD` in the secrets file
collides with the minted TTE key):
- `tests/fixtures/sample_project_elastic/infra/secrets/stage.env` + `prod.env`
- `tests/fixtures/sample_project_scheduler_elastic/infra/secrets/stage.env`
  (and `prod.env` if present).

Leave a comment matching the Mod 080/081 fixture wording. Keep any genuine
secret (e.g. `TELEMETRY_API_KEY`) if the fixture needs one for its release test;
add it if the release test asserts it's pushed.

## Step 5 — tests (`tests/unit/`)

Extend the fake AWS client with an in-memory SSM store (`dict[path -> (value,
type)]`), `ssm_get_parameter` reading it, and `ssm_put_parameter` honoring
`overwrite` (raise/ignore on `overwrite=False` when present) + recording
`param_type`.

1. `ensure_tte_elastic`: empty SSM → mints `POSTGRES_PASSWORD` as `SecureString`
   (1 minted); pre-populated SSM → 0 minted, existing value untouched
   (put-if-absent, no clobber).
2. `aggregate_elastic`: pushes secrets as `SecureString` (overwrite), config as
   `String` (overwrite), TTE minted-if-absent; returns the right count; a
   secrets-file key colliding with a TTE key raises `AggregationError`.
3. `_release_elastic`: with the fake AWS + fake tofu runners, assert
   `aggregate_elastic` ran (SSM store populated with the right types) before
   apply; assert `dry_run=True` does NOT touch SSM.
4. Update/replace any existing `_push_secrets` test with the `aggregate_elastic`
   equivalent (grep `_push_secrets`).

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 081 was 740 passed).
- Elastic release pushes TTE (minted-if-absent, SecureString), secrets
  (SecureString, overwrite), config (String, overwrite) to `/<project>/<env>/`.
- A present TTE param is never re-minted or clobbered.
- `dry_run` touches no SSM.
- No `tables/` or doctrine change. Report that end-to-end elastic release is
  validated only by the (deferred) elastic smoke walk; unit tests mock AWS.
