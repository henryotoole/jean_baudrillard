# Mod 009 — `sslmode` provided part on `relational_db`/`postgres`

## Problem

Discovered during the maptrack smoke release. The `postgres` engine's `provides:` set today is `host` / `port` / `db` / `user` / `password` — i.e., the parts you need to assemble a connection string, *except* one. SSL/TLS posture differs across foundations:

- **Fixed** — the postgres container ships with SSL disabled by default; clients must connect plaintext.
- **Elastic** — AWS RDS rejects non-SSL connections under its default `pg_hba.conf`; clients must declare `sslmode=require` (or stronger).

Because the doctrine doesn't expose this difference as a part, every project's `migrate.sh` (and any other code that constructs a DSN) has to encode foundation-aware logic by hand. Maptrack ended up at `if [[ "$DATABASE_HOST" == *.rds.amazonaws.com ]]; then sslmode=require; else sslmode=disable; fi` — exactly the cross-foundation coupling the parts-only model exists to prevent.

The two smoke projects exhibit the same problem in different forms:

- `test_projects/fixed/core/web/migrate.sh` hardcodes `?sslmode=disable`.
- `test_projects/elastic/core/web/migrate.sh` omits sslmode and relies on libpq's `prefer` default (which dbmate's `pq` driver does not accept verbatim; the elastic walk has been lucky, not correct).

The two `migrate.sh` files diverge on a foundation difference that the doctrine should be hiding. They should be byte-identical.

## Design

### The new part

Add `sslmode` to `roles.relational_db.postgres.provides`:

```yml
sslmode:
  fixed: "disable"
  elastic: "require"
```

The values are plain strings — no `${var}` substitution, no `$[var]` runtime ref, no `@<expr>` HCL pass-through. They're compile-time constants that the compiler resolves like any other part: when a consumer declares `DATABASE_SSLMODE: ${backing_services.appdb.sslmode}`, the compiler substitutes the literal `"disable"` or `"require"` into the consumer's env block per the env being compiled.

### Why a part rather than a hidden default

Two alternatives were considered and rejected:

1. **Bake sslmode into the `host` template.** Would produce a connection-string-like value (e.g. `host=... sslmode=require`) that defeats the parts-only model — the doctrine forbids composed strings in `provides:` parts ([`transfer_tables.md § provides`](../../../../doctrine/infrastructure/specifics/transfer_tables.md)).
2. **Have docex inject `PGSSLMODE` automatically as a runtime env var.** Bypasses CICL entirely. Would work, but breaks the contract that `provides:` is the surface for cross-foundation differences — projects looking at `./bin/docex role relational_db` wouldn't see sslmode, and the env var would appear "from nowhere."

A real part is the right answer: visible to `docex role`, validated by the compiler against magic refs, naturally included in `example.env` if a consumer references it.

### Compile-time, not runtime

`sslmode` resolves at compile time because the value is determined by the env's foundation, not by runtime secrets. The fixed envs (`dev`, `test`, plus `stage`/`prod` of fixed-foundation projects) always get `"disable"`; the elastic envs (`stage`/`prod` of elastic-foundation projects) always get `"require"`. This is symmetric with `db: ${name}` — also a plain compile-time substitution.

The compiler's existing magic-ref resolver (`src/docex/cicl/magic_refs.py`'s `MagicRefResolver`) handles this case unchanged. A part template with no `$[...]` or `@...` resolves to a literal string, which the emit layer drops into the consumer's env block. No new code paths.

### Stronger sslmode values are out of scope

`require` is the appropriate default for elastic — it asks libpq to use SSL but accepts the RDS-managed cert without CA verification. Stronger modes (`verify-ca`, `verify-full`) require shipping CA bundles in the container image and a verified RDS endpoint hostname; deferred until a project actually needs it. The part is a single string, not a structured policy, by design.

### Where the data and the consumers live

| File | Change |
| ---- | ------ |
| `tables/roles/relational_db.yml` | Add `sslmode` entry to `provides:`. |
| `test_projects/fixed/infra/infra.yml` | Add `DATABASE_SSLMODE: ${backing_services.db.sslmode}` to `web` and `worker` env. |
| `test_projects/elastic/infra/infra.yml` | Add `DATABASE_SSLMODE: ${backing_services.appdb.sslmode}` to `web` and `worker` env. |
| `test_projects/fixed/core/web/migrate.sh` | Read `$DATABASE_SSLMODE`; use it in the DSN's `?sslmode=` query. |
| `test_projects/elastic/core/web/migrate.sh` | Same. After this mod, fixed and elastic `migrate.sh` are byte-identical. |
| `test_projects/{fixed,elastic}/core/{web,worker}/src/root.py` | Read `DATABASE_SSLMODE` and append `sslmode=$value` to the psycopg DSN, so runtime application connections honor the part too (not just migrations). |
| `test_projects/{fixed,elastic}/core/{web,worker}/dist/root.py` | Mirror the src change — `dist/` is the bind-mounted build output and the smoke projects ship both, per the existing pattern. |

The `worker` is not a schema owner (no `migrate.sh`) but does connect to the database from `root.py`; both consumers receive the env var for symmetry. Without it, the worker's psycopg connection would still happen to work on RDS via psycopg's "prefer SSL" default, but that's the same accidental-correctness the mod exists to eliminate.

### Doctrine alignment

The doctrine edit for this mod has already landed in [`transfer_tables.md`](../../../../doctrine/infrastructure/specifics/transfer_tables.md) — the postgres walking example now shows `sslmode` in `provides:` and a paragraph justifying its existence. Mod 009 brings the data and the smoke projects in line with that text.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | Already changed: `transfer_tables.md` postgres walking example + rationale paragraph. No further edits in this mod. |
| `docex/plans/core/*.md` | No change — `sslmode` is a data addition, not a structural shift in `compiler.md`'s pipeline. |
| `tables/*.yml` | `tables/roles/relational_db.yml` gains the `sslmode` provides entry. |
| `src/docex/**` | No source changes. The magic-ref resolver already handles plain-string templates. |
| `tests/**` | New unit test in `tests/cicl/test_compile.py` (or wherever postgres-engine tests live): a consumer referencing `${backing_services.<svc>.sslmode}` resolves to `"disable"` on a fixed env and `"require"` on an elastic env. |

The "no source changes" line is the critical-path assertion of this mod. If the implementer finds themselves editing `compile.py` / `magic_refs.py` / `emit/*.py` to make this work, the data shape is probably wrong — surface immediately rather than working around.

## Validation

1. `python3 -m pytest tests/` — green, including the new unit test.
2. `./bin/docex compile` from each smoke project — both fixed and elastic produce compiled output where `web` and `worker` containers/tasks carry `DATABASE_SSLMODE` env vars with the foundation-appropriate value.
3. `diff test_projects/fixed/core/web/migrate.sh test_projects/elastic/core/web/migrate.sh` — empty (the files are byte-identical post-mod).
4. `./bin/docex role relational_db` — `sslmode` appears in the listed provided parts.

Real-AWS staging walk is not part of this mod — it's part of the campaign-end PRE_CUT_CHECKLIST walk. The smoke release tests for v0.7.0 caught the symptom; the campaign-end walk for the cut that ships this mod will verify the fix.

## Decisions captured

1. **`sslmode` is a part, not a hidden injection.** Keeps the parts-only model load-bearing on both foundations and keeps `docex role relational_db` honest.
2. **Compile-time constants, not runtime refs.** `sslmode` is determined by foundation, not by secrets — resolves to a literal string at compile time. No `$[...]` runtime indirection, no SSM entry, no env-file row.
3. **`require`, not `verify-full`.** Pragmatic default for v1. Stronger SSL modes require CA bundles in the container image; deferred until a project asks.
4. **Both web and worker get the env var.** Both connect to the database; both should honor the same foundation-derived sslmode. Symmetric consumer surface beats clever scoping.
5. **No `provides:` change on the runtime side.** The part is a compile-time string. `provides.sslmode.elastic` is literally `"require"`, not `@aws_db_instance...` — there's nothing AWS-side to wait for.

## Open questions

1. Should `migrate.sh` on the elastic smoke project keep its existing libpq-comment block (rationalizing the `prefer` default) once it's deleted? **No** — the new file should look like the fixed file, no foundation-aware commentary. The whole point is that foundation doesn't matter at this layer.
2. Does docex have an existing test fixture for "compile a tiny postgres-using project on each foundation and assert env vars on the consumer"? Implementation step 1 will discover; if not, the unit test goes inline against the magic-ref resolver instead of a full compile.
