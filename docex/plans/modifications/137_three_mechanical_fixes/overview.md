# Mod 137 — Three mechanical, independently-testable fixes

Advance 008 ("Housekeeping"). This mod bundles three small `src`/table fixes that
share no code and form a clean seam. Each fix's brief in
[`../../advances/008_housekeeping/references/`](../../advances/008_housekeeping/references/)
IS the design record; this overview records the design decisions and how they land,
it does not re-litigate them. All three rulings were fixed at plan review.

## Fix 1 — `object_store`/`minio` ignores `version:`

Brief: `docex_object_store_version_gap.md`.

`tables/roles/object_store.yml`'s `minio` engine hardcodes `image: "minio/minio:latest"`
and declares no `version` field, so a `version:` on an `object_store` service is
accepted then silently ignored — the lone backing engine that does not pin its tag
from `version:`. An unpinned tag on a stateful backing service breaks the
determinism promise.

**Design:**
- Add a `version` field to `minio` mirroring `postgres` (fixed arm only, since
  `minio` is `foundation: fixed`): `fields.version.fixed.image: "minio/minio:${field_value}"`.
- Drop the hardcoded `image: "minio/minio:latest"` from `minio`'s `defaults.fixed`
  so `version:` is authoritative.
- **Missing `version` is a compile error, enforced engine-nuanced** (ruling): required
  wherever the matched engine declares a `version` field, so `minio` requires it and
  `s3` is exempt (elastic, emits an `s3_bucket`, has no image/version). This aligns
  the code to `cicl.md § Service Fields`'s existing "`version | yes | backing`" claim;
  no pinned fallback is invented — `latest` was never defensible.
- Enforcement lives in a new `validate.py` check that reads each backing service's
  matched engines' `fields:` for `version` and requires the service to set it. Because
  the requirement is derived from the engine's own `fields:` block, `s3`'s exemption is
  structural, not special-cased.

## Fix 2 — contract spec-version minimums ungated in `docex check`

Brief: `contract_spec_version_ungated.md`.

`contracts.md § Standards` fixes a minimum spec version per format — OpenAPI **3.2+**,
AsyncAPI **3.0+** — and nothing in `docex` reads it, so `openapi: "2.0"` passes
`docex check` green. The floors are load-bearing: OpenAPI 3.2 buys `itemSchema` (the
`stream` style); AsyncAPI 3.0 buys `reply` (the `rpc` style).

**Design:**
- Add a `_FORMAT_MIN_SPEC_VERSION = {"openapi": (3, 2), "asyncapi": (3, 0)}` map in
  `pipeline/check.py`, carrying the same "this is the doctrine's table" comment
  `_FORMAT_EXTENSIONS` carries. `graphql`/`proto` have no version key and are absent
  by design (and excluded by `IMPLEMENTED_CONTRACT_FORMATS` regardless).
- Add `_gate_contract_spec_version(contracts, report)` iterating the existing
  `list[ContractExpectation]` `_gate_contracts` already materializes — no second
  directory walk. For each contract whose `fmt` is in the map, read the format's own
  root version key (`openapi:` / `asyncapi:`), parse `major.minor`, compare.
- Malformed/absent version key: handled the way `_gate_contract_health_path` handles
  unreadable YAML — report once, do not additionally report the consequence.
- Call it from the same block that calls the other two contract gates, reusing the
  materialized list.

## Fix 3 — env-subdomain expression re-derived by hand in two sites

Brief: `env_subdomain_fourth_copy.md`.

The compiler owns the env subdomain `<env>.<project>.<apex_domain>` as
`CompiledEnv.subdomain` (derived once by `compile._env_subdomain`). Two sites
re-derive it by hand:
- `orchestrate/aggregate.py:54` (`_host_for`)
- `orchestrate/up.py:211-212`

Every copy is a *reader* (no emitter in this family), so drift fails loudly rather
than silently — low severity but real duplication.

**Design:**
- Add a small compiler-owned helper `env_subdomain_for(ctx, env)` in `cicl/compile.py`
  that compiles the env in-memory and returns `compiled.subdomain` — the same idiom
  `orchestrator_health.py`, `release.py`, and `describe/` already use to read a
  `CompiledEnv`. This routes both readers through the carried field.
- `_host_for` and the `up.py` block both call it and delete their hand-rolled
  `f"{env}.{dns_label(...)}.{apex}"` expressions; drop the now-unused `dns_label`
  import where it falls out.
- Re-grep for the expression AFTER the fix (count found by grepping, never predicting).
  Baseline in `src/`: **3** occurrences of `f"{env}.…"` env-subdomain form
  (`compile.py:369` the canonical source of truth; `aggregate.py:54` and `up.py:212`
  the hand-rolled copies). Expected after: **1** (the canonical `_env_subdomain` only).
  The project/stage cousins (`stagetest.py`, `bootstrap.py`, `emit/hcl.py`) are a
  distinct expression and out of scope.

## Testing

Unit tests suffice — none of the three crosses a docker/AWS/git boundary. New tests:
1. `object_store` missing `version` is a compile error; `s3` (elastic) is exempt;
   `minio` with a `version` pins `minio/minio:<v>` and no longer emits `:latest`.
2. The spec-version gate: below-floor OpenAPI/AsyncAPI fails; at-floor passes;
   malformed/absent version key reports once.
3. The subdomain consolidation: `_host_for`/`up.py` produce the compiled subdomain.

## Drift check (six aligned artifacts)

- Doctrine rule of record: `cicl.md § Service Fields` (version required) and
  `contracts.md § Standards` (spec floors) already state what is being enforced — the
  code is aligned TO them; doctrine is NOT edited. The s3-exempt nuance was declared
  alignment (not contradiction) by the ruling.
- Transfer table: `tables/roles/object_store.yml` (fix 1).
- `plans/core/*.md`: `compiler.md` validation-rules list / object_store / subdomain
  mentions to be checked and updated as needed.
- `src` + `tests`: as above.
- `doctrine_excerpts/` + `index.yml`: these fixes introduce/retire no *resource*, so
  almost certainly no excerpt change — to be confirmed, not assumed.

## Design questions

None. All three decisions were fixed at plan review; proceeding through the full cycle
without pausing for design approval, per the kickoff.
