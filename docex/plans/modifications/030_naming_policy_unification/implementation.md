# Implementation — Mod 030 — Naming Policy Unification

## Context for fresh-context implementer

You are executing mod 030 of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Read [`overview.md`](./overview.md) first — it explains *what* changes and *why*. This document is the operational plan.

The doctrine has already been edited; this mod brings docex into alignment with it. Authoritative doctrine reading:

- [`doctrine/infrastructure/specifics/transfer_tables.md § Naming Policies`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies) — the canonical policy table.
- [`doctrine/infrastructure/specifics/transfer_tables.md § How structural emitters reference a policy`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#how-structural-emitters-reference-a-policy) — the ECR carve-out.
- [`doctrine/infrastructure/cicl.md § Container Registry and Service Images`](../../../../doctrine/infrastructure/cicl.md#container-registry-and-service-images) — the canonical image-reference form.

Your docex-side mental map of where naming lives:

- `tables/naming_policies.yml` — the policy table itself (data, deep-merged at load with project-local tables).
- `src/docex/naming.py` — `apply_policy` is the single translation entry point.
- `src/docex/cicl/transfer.py` — loads + validates the policy table.
- `src/docex/emit/hcl.py` — every elastic emit site that produces an identifier reads its policy from `naming_policies` and calls `apply_policy`.
- `src/docex/emit/compose.py` — fixed-side emit; uses the `docker` policy via the engine's `naming:` ref.
- `src/docex/pipeline/release.py`, `src/docex/orchestrate/migrate.py`, `src/docex/pipeline/bootstrap.py` — runtime lookups of ECS cluster name and SSM/S3 paths.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- **Do not recompile the test projects.** Leave `test_projects/{fixed,elastic}/infra/output/` untouched. The major-version re-inception at end-of-campaign rebuilds them from scratch.
- **No backwards-compatibility shim.** Delete `ecr_repo`; do not deprecate it.
- **No changelog caveats beyond the standard major-bump note.** No in-flight consumers to warn.

## Step-by-step plan

### Step 1 — Update `tables/naming_policies.yml`

1. Flip `docker` policy `separator: underscore` → `separator: hyphen`.
2. Flip `ecs` policy `separator: underscore` → `separator: hyphen`.
3. Delete the entire `ecr_repo:` block (whole policy entry).
4. Rewrite the leading file comment block. The current comment says "the doctrine prefers underscore (matching the project-name form). Hyphen is used only where AWS rejects underscores." That is now backwards. Rewrite to match the doctrine's new default rule from `transfer_tables.md § Naming Policies` — verbatim or near-verbatim is fine:

> Default rule: anything name-resolvable on the data plane uses hyphens (Docker containers/networks/volumes, ECS cluster/service/task-def/Service Connect, ALB/target groups, RDS, S3, hostnames). Underscores are preserved only for inert AWS record-key identifiers that applications never name in DNS or compose: IAM roles, SSM path segments, DynamoDB tables.

Also update individual per-policy comments that reference the old default (e.g. the `ecs` and `docker` comments currently say "prefer underscore for consistency with project-name form" — that's wrong now).

### Step 2 — Update `src/docex/emit/hcl.py`

The ECR repo emit currently lives around lines 780–790. Two changes:

**Remove the `ecr_repo` policy lookup at line 784:**

```python
ecr_p = naming_policies.get("ecr_repo")   # delete this line
```

**Replace the `ecr_repo_names` dict at lines 787–792 with structural emit:**

```python
# Before:
ecr_repo_names = {
    name: (
        apply_policy(project, ecr_p) + "/" + apply_policy(name, ecr_p)
    )
    for name in core_service_names
}

# After:
# Structural emit per transfer_tables.md § How structural emitters
# reference a policy — ECR repo names are `${project}/${service}`
# with each segment verbatim and `/` as joiner; the policy
# machinery's single-separator shape cannot express this.
ecr_repo_names = {
    name: f"{project}/{name}"
    for name in core_service_names
}
```

No template (`project.tf.j2`) changes — the template consumes `ecr_repo_names` as a dict of strings and doesn't care how they're built.

### Step 3 — Verify no other code references `ecr_repo`

Run:

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn '"ecr_repo"\|naming.*ecr_repo' src/ tables/
```

After step 2 this should return no hits. If anything else references the policy name, examine it and either remove the reference or restructure to use the verbatim path.

### Step 4 — Confirm no allowlist changes are needed

The `_ALLOWED_*` constants in `src/docex/cicl/transfer.py` and `src/docex/naming.py` constrain *keys within a policy body* (`separator`, `case`, `max_len`), not policy names. Policy names are runtime values — any name declared in the table is valid, and any name referenced by an engine's `naming:` field must exist in the table. So deleting `ecr_repo` from the table is sufficient; no allowlist constant edits required. **Confirm by inspection** that this remains true (this is the implementer's sanity check, not a planned edit).

### Step 5 — Update unit tests

#### `tests/unit/test_naming.py`

Two cases need surgery:

**Line 26** uses a synthetic `ecs` policy with `separator: underscore` and probably asserts an underscore result. Either:
- Update the assertion to the new hyphen form, *or*
- Reframe the test to use a synthetic non-real policy name so it doesn't entangle with doctrine values. Pick whichever pattern the test file's other cases use.

**Lines 31** uses a synthetic `ecr_repo` policy. The policy no longer exists in doctrine. Either:
- Remove the case entirely (preferred — it's testing a deleted policy), *or*
- Reframe with a synthetic policy name unrelated to `ecr_repo`.

**Lines 58 + 65** construct a `policies` dict literal containing an `ecs` entry with `separator: underscore`. Update to `separator: hyphen` and flip the expected output assertion.

#### `tests/unit/test_transfer.py`

**Line 105** has a hardcoded list of expected policy names:

```python
for policy_name in ("s3", "rds", "ddb", "alb", "ecs", "ecr_repo", "iam", "ssm_path", "docker", "http_host"):
```

Remove `"ecr_repo"` from the tuple. Verify the surrounding test still passes — it's checking that every doctrine-shipped policy is present in the loaded table.

### Step 6 — Update integration tests

#### `tests/integration/test_compile.py`

Several tests assert specific compiled identifiers. Audit by category:

- **`s3`-derived and `ddb`-derived names** (`test_project_tier_state_backend_names_translated`, `test_bootstrap_state_backend_matches_project_tier`, `test_env_tier_state_backend_alb_ecs_cluster_names`): policies unchanged, no asserted-string changes.
- **`docker`-derived names** (compose container_name, network names): flip every asserted string from `${project}_${env}_${svc}` to `${project}-${env}-${svc}`. The test project is `docex_smoke_elastic` (or fixed); a network previously asserted as `docex_smoke_elastic_dev_internal` becomes `docex-smoke-elastic-dev-internal`.
- **`ecs`-derived names** (ECS cluster, service, task-def family, Service Connect discovery name): same flip.
- **`alb`-derived target-group names**: policy unchanged.
- **ECR repo names** (`test_project_tier_ecr_and_iam_names_use_correct_policies` and friends): the assertion has been "passes through `ecr_repo` policy"; rewrite to "structural emit: `f'{project}/{name}'`". For the smoke project, the *string* is unchanged (`docex_smoke_elastic/api`); the *test* should change to assert the construction mechanism (or simply pin the literal string and drop any `apply_policy` reference).

The implementer must walk the entire file and update every assertion in lockstep — there is no shortcut. Most edits are mechanical `s/_/-/g` in expected strings for docker/ecs categories.

#### Other test files

Anything under `tests/unit/` or `tests/integration/` that asserts a specific Docker or ECS identifier needs the same flip. Quick survey:

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn 'docex_smoke_[a-z]*_\(dev\|test\|stage\|prod\)_' tests/
```

Every hit is a candidate. Update mechanically.

The `*_real.py` integration tests (`test_up_down_real.py`, `test_containerize_real.py`, etc.) invoke `docker` CLI as a subprocess — those don't reference the policy at all and need no changes.

### Step 7 — Update docex core planning docs

Per `docex_process.md` Additional Artifacts table, docex/plans/core must stay aligned.

#### `docex/plans/core/compiler.md`

- The "Structural vs engine emit" section currently includes "project ECR repos" in the structural list — confirm it's still there, no edit needed.
- The "Where to look when changing things" table is fine; the relevant rows still point at the right files.
- If the doc currently mentions the `ecr_repo` policy anywhere by name, replace with a note that ECR repo names are hardcoded structural emit (point at the transfer_tables.md carve-out paragraph).

Grep for it:

```bash
grep -n "ecr_repo" docex/plans/core/compiler.md
```

#### `tables/README.md`

Quick read; if it lists policies by name and includes `ecr_repo`, drop the entry and refresh any narrative about underscore-vs-hyphen defaults.

### Step 8 — Run the test suite

```bash
cd ~/.claude/jean_baudrillard/docex
./bin/docex test     # docex's own test suite (not a consumer project test)
```

Or directly:

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"   # the offline integration tests
```

The `*_real.py` integration tests require docker / AWS and are out of scope for this mod — they're not affected by policy changes.

Expect all in-scope tests to pass after the mechanical updates. Any failures are real bugs to fix, not "expected churn to ignore."

### Step 9 — Final sanity sweep

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn "ecr_repo" src/ tests/ tables/ plans/core/
```

Should return no hits.

```bash
grep -rn '"separator": "underscore"' src/ tables/ | grep -E '(docker|ecs)'
```

Should return no hits inside `naming_policies.yml`. Hits inside test files that exercise `apply_policy` with a synthetic underscore policy are fine (they test the function's behavior, not the doctrine's default).

## Out of scope — explicit non-goals

- **No `apex_domain:` rename** — that's mod 031.
- **No `reverse_proxy:` field changes** — mod 031.
- **No telemetry sidecar rename** — mod 032.
- **No test-project recompile** — deferred to campaign end.
- **No `tables/roles/reverse_proxy.yml` deletion** — mod 031 (which also drops that role from CICL entirely).
- **No new commands, no new emit sites, no project-tier ECR move yet** — mod 039 moves ECR to project-tier; this mod only changes *how* ECR names are formed.

## Done criteria

- [ ] `tables/naming_policies.yml` updated: `docker` and `ecs` flipped to hyphen; `ecr_repo` entry removed; leading comment block and per-policy comments reflect the new default rule.
- [ ] `src/docex/emit/hcl.py` ECR emit refactored to verbatim `f"{project}/{name}"`.
- [ ] No references to `"ecr_repo"` remain anywhere under `src/`, `tests/`, `tables/`, or `plans/core/`.
- [ ] `tests/unit/test_naming.py` and `tests/unit/test_transfer.py` updated.
- [ ] `tests/integration/test_compile.py` updated: every asserted docker/ecs identifier flipped to hyphen form.
- [ ] `docex/plans/core/compiler.md` and `tables/README.md` references checked and updated where needed.
- [ ] `pytest tests/unit` and offline `tests/integration` both green.
- [ ] No edits to `test_projects/{fixed,elastic}/infra/output/`.
- [ ] No edits to anything else outside the mod's documented scope.

When finished, leave the working tree dirty for the design-context agent's review pass. Do not commit.
