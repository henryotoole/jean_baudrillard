# Mod 009 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Add `sslmode` as a `provides:` part on `roles.relational_db.postgres`. Compile-time constant — `"disable"` on fixed, `"require"` on elastic. No source-code changes in `src/docex/**`: the magic-ref resolver already handles plain-string templates (same shape as `db: ${name}`). Plus the smoke projects (`test_projects/fixed`, `test_projects/elastic`) get a `DATABASE_SSLMODE` env var on `web` and `worker`, their `migrate.sh` and `root.py` files start using it, and both `migrate.sh` files become byte-identical.

If you find yourself editing anything under `src/docex/cicl/`, `src/docex/emit/`, or `src/docex/orchestrate/` to make any of this work, **stop** — that's a signal the data shape is wrong. Surface it in the hand-off report.

## Step 1 — Extend the transfer table

File: `tables/roles/relational_db.yml`.

Find the `provides:` block (currently has `host`, `port`, `db`, `user`, `password`). Append `sslmode` as the last entry:

```yml
        sslmode:
          fixed: "disable"
          elastic: "require"
```

Indentation matches the existing entries (8 spaces — confirm against the file's current indentation). The values are plain double-quoted strings. No `${var}`, no `$[var]`, no `@<expr>`.

## Step 2 — Add the consumer env var in both smoke projects' `infra.yml`

### Fixed smoke project

File: `test_projects/fixed/infra/infra.yml`.

In `core_services.web.env`, append after the existing `DATABASE_PASSWORD` line:

```yml
      DATABASE_SSLMODE: ${backing_services.db.sslmode}
```

In `core_services.worker.env`, append the same line. Backing service name is `db` for the fixed project.

### Elastic smoke project

File: `test_projects/elastic/infra/infra.yml`.

Same change, but the backing service is named `appdb` (not `db`) in the elastic project. Append to `core_services.web.env` and `core_services.worker.env`:

```yml
      DATABASE_SSLMODE: ${backing_services.appdb.sslmode}
```

## Step 3 — Make `migrate.sh` consume the env var (both projects)

After this step the two `migrate.sh` files must be byte-identical. Use the content below for *both* `test_projects/fixed/core/web/migrate.sh` and `test_projects/elastic/core/web/migrate.sh`:

```sh
#!/bin/sh
# migrate.sh — apply database migrations via dbmate.
# Doctrine: databases.md mandates dbmate for SQL migrations.
set -eu

cd "$(dirname "$0")"

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_PORT:?DATABASE_PORT must be set}"
: "${DATABASE_NAME:?DATABASE_NAME must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"
: "${DATABASE_SSLMODE:?DATABASE_SSLMODE must be set}"

# Compose the DSN from the parts-only env vars (cicl.md § Provided Fields).
# sslmode is a doctrine-provided part — `disable` on fixed, `require` on
# elastic — so this script is foundation-agnostic.
export DATABASE_URL="postgres://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}?sslmode=${DATABASE_SSLMODE}"

exec dbmate --no-dump-schema --migrations-dir /service/migrations up
```

Verify after writing: `diff test_projects/fixed/core/web/migrate.sh test_projects/elastic/core/web/migrate.sh` must produce empty output. If it doesn't, you've fat-fingered one of them.

## Step 4 — Use sslmode in application DSNs (both projects, web + worker)

The smoke projects' `web` and `worker` build a psycopg DSN from env vars in `root.py`. They must include `sslmode` so runtime connections honor the part too (not just migrations).

### Files to edit

Four `src/root.py` files and four `dist/root.py` files:

- `test_projects/fixed/core/web/src/root.py` + `test_projects/fixed/core/web/dist/root.py`
- `test_projects/fixed/core/worker/src/root.py` + `test_projects/fixed/core/worker/dist/root.py`
- `test_projects/elastic/core/web/src/root.py` + `test_projects/elastic/core/web/dist/root.py`
- `test_projects/elastic/core/worker/src/root.py` + `test_projects/elastic/core/worker/dist/root.py`

`dist/` mirrors `src/` because the smoke projects bind-mount it as the build output and ship both. After editing `src/`, copy the matching `dist/` file by hand — do not run `./bin/docex build` for this; the build is not the goal.

### Change

Each `_dsn_from_env()` function currently looks like:

```python
def _dsn_from_env() -> str:
    parts = {
        "host": os.environ["DATABASE_HOST"],
        "port": os.environ["DATABASE_PORT"],
        "dbname": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
    }
    return (
        f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
        f"user={parts['user']} password={parts['password']}"
    )
```

Change to:

```python
def _dsn_from_env() -> str:
    parts = {
        "host": os.environ["DATABASE_HOST"],
        "port": os.environ["DATABASE_PORT"],
        "dbname": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
        "sslmode": os.environ["DATABASE_SSLMODE"],
    }
    return (
        f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
        f"user={parts['user']} password={parts['password']} "
        f"sslmode={parts['sslmode']}"
    )
```

Note the trailing space on the second-to-last f-string line — the DSN is space-separated and `sslmode=` needs its own separator. The `web/src/root.py` file may have a docstring (`"""Build the postgres DSN from..."""`) on the function; preserve it unchanged.

## Step 5 — Add a unit test

File: `tests/unit/test_magic_refs.py`.

The `_make_resolver` helper at the top of the file constructs a postgres `EngineEntry` with a subset of provided parts (currently `host`, `port`, `user`). Extend that subset to include `sslmode`:

```python
        provides={
            "host": {"fixed": "${global_service_name}", "elastic": "@aws_db_instance.${name}.endpoint"},
            "port": {"fixed": "${port}", "elastic": "${port}"},
            "user": {"fixed": "$[POSTGRES_USER]", "elastic": "$[POSTGRES_USER]"},
            "sslmode": {"fixed": "disable", "elastic": "require"},
        },
```

Then add a new test function at the bottom of the file (after `test_magic_ref_empty_resolution_errors`):

```python
def test_resolve_sslmode_part_compile_time_constant():
    """sslmode is a doctrine-provided part with foundation-specific
    compile-time constants — `disable` on fixed, `require` on elastic —
    so projects can reference it without encoding foundation-aware
    logic. See mod 009."""
    resolver_fixed, _ = _make_resolver(foundation="fixed")
    rendered_fixed = resolver_fixed.resolve_in_string(
        "${backing_services.db.sslmode}", consumer="api"
    )
    assert rendered_fixed.value == "disable"
    assert rendered_fixed.raw_hcl is False
    assert rendered_fixed.runtime_refs == set()

    resolver_elastic, _ = _make_resolver(foundation="elastic")
    rendered_elastic = resolver_elastic.resolve_in_string(
        "${backing_services.db.sslmode}", consumer="api"
    )
    assert rendered_elastic.value == "require"
    assert rendered_elastic.raw_hcl is False
    assert rendered_elastic.runtime_refs == set()
```

The `runtime_refs == set()` assertions are the load-bearing ones — they confirm sslmode does NOT propagate as a secret/runtime ref (unlike `user` / `password`). If the resolver returns a non-empty `runtime_refs` for a plain-string part, that's a bug.

If your codebase exposes `runtime_refs` under a different attribute name, adapt the assertions but keep the intent: the resolved value is a literal string and no runtime indirection appears.

## Step 6 — Recompile the smoke projects

The smoke projects' compiled output (`test_projects/{fixed,elastic}/infra/output/<env>/...`) is git-tracked. Recompile both so the new `DATABASE_SSLMODE` env var appears in compose / HCL:

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/fixed
./bin/docex compile

cd /home/ubuntu/.claude/jean_baudrillard/docex/test_projects/elastic
./bin/docex compile
```

Spot-check after each:
- Fixed: `infra/output/dev/docker-compose.yml` — the `web` and `worker` services have `DATABASE_SSLMODE: disable` in their `environment` block.
- Elastic: `infra/output/stage/main.tf` — the `web` task definition's `environment = [...]` includes `{ name = "DATABASE_SSLMODE", value = "require" }`. Same for `worker`.

The `./bin/docex compile` invocation reads the docex_version pin in `project.yml`. **The pinned image may or may not include the new sslmode part yet** — if `./bin/docex compile` runs from the host's installed image (which is the pre-mod version), the output will not show `DATABASE_SSLMODE`. Two options:

- **Option A** (preferred if your dev loop supports it): rebuild the docex image locally (`docker build -t docex:<pinned_version> .` from the docex root) so the in-image transfer tables include the new sslmode entry, then re-run `./bin/docex compile`. This matches what a cut would produce.
- **Option B**: if rebuilding the image is out of scope for the sub-agent, *skip* the compile-and-spot-check and note this in the hand-off report. The design-context LLM and the operator will rebuild + recompile after review.

Whichever route, the *uncompiled* artifacts (table YAML, infra.yml, migrate.sh, root.py, test) are the substantive deliverables of this mod.

## Step 7 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/
python3 -m pytest tests/unit/test_magic_refs.py -v  # confirm the new test runs and passes
```

All must pass. The full `tests/` (including integration) is optional for the sub-agent run — the design-context LLM will run integration as part of campaign-end checks.

## Step 8 — Leave everything uncommitted

Per the mod process, the design-context LLM reviews before commit. Both the outer `jean_baudrillard` repo and the inner test-project repos (`test_projects/fixed/.git`, `test_projects/elastic/.git`) will show dirty trees — that's expected.

## Hand-off report

In ≤200 words:

- Files changed (group by repo: outer / fixed-inner / elastic-inner).
- Test pass counts; whether the new sslmode test passed.
- Whether Step 6 recompile happened (option A) or was deferred (option B).
- Any decisions made beyond what implementation.md prescribed.
- Anything that smelled off — places where the change felt structurally wrong, or where the data shape resisted.

## Out of scope

- Stronger sslmode values (`verify-ca`, `verify-full`) — deferred per overview.md § "Stronger sslmode values are out of scope".
- Source code changes under `src/docex/**` — the magic-ref resolver should handle plain-string templates unmodified. If it doesn't, that's a separate finding.
- Doctrine prose changes — already landed.
- Bumping the smoke projects' inner-repo `project.yml` version or moving the `v<version>` tag — that's part of the campaign-end work, not per-mod.
- Updating `docex/CHANGELOG.md` — done at cut time, not per mod.
