---
stratum: resident
---

# Relational Databases

This guide covers best practices for working with relational databases.

## Schema Setup and Changes ##

All SQL queries which set up the database should be stored outside of the codebase, as they do not represent code.

For SQL servers, **always** use `dbmate` to manage migrations. `dbmate` is a simple tool that manages migrations. It can be found at this [github](https://github.com/amacneil/dbmate). It's a relatively well-known library.

### Initial Setup

A database schema should be set up for the first time by a regular database migration. The first database migration, therefore, will always set up the initial state of the schema.

### Migrations

Migrations should always be idempotent and reversible.