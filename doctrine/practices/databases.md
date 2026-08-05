---
stratum: resident
---

# Relational Databases

This guide covers best practices for working with relational databases.

## Schema Setup and Changes ##

All SQL queries which set up the database should be stored outside of `src/` — in the schema-owning codebase's `migrations` folder — as they do not represent application code.

The choice of migration tool is left to the project. What the doctrine fixes is the *interface*, not the tool: every schema-owning codebase exposes a `migrate.sh` shim whose only contract is its exit code (`0` on success), invoked by `docex` at doctrine-defined lifecycle points. Behind that shim the project may use whatever tool fits its stack. See [migrations.md](../infrastructure/specifics/migrations.md) for the full mechanism.

The doctrine's default recommendation is `dbmate` — a simple, well-known migration tool ([github](https://github.com/amacneil/dbmate)) that suits most SQL-backed projects. Reach for something else only when the project's ecosystem has a strongly idiomatic alternative (e.g. `alembic` in a Python/SQLAlchemy stack).

### Initial Setup

A database schema should be set up for the first time by a regular database migration. The first database migration, therefore, will always set up the initial state of the schema.

### Migrations

Migrations should always be idempotent and forward-only — the doctrine never reverses a schema, even on [rollback](../infrastructure/cicd.md#rollback). To keep rolling deploys and rollbacks safe, each migration must also be [backward compatible](../infrastructure/specifics/migrations.md#backward-compatibility-requirement) with the previous application version.