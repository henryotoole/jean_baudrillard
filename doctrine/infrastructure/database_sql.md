# Databases (SQL)

This guide covers best practices for working with SQL databases.

## Schema Setup and Changes ##

All SQL queries which set up the database should be stored outside of the codebase, as they do not represent code.

In the structure described in [Hexagonal Architecture](../hexagonal_architecture/hex_overview.md), files which setup or modify the database schema should be stored in a folder titled `db` which is one level below the project root:

```
service_root
├── db
├── src
...
```

For SQL servers, **always** use `dbmate` to manage migrations.

### dbmate

`dbmate` is a simple tool that manages migrations. It can be found at this [github](https://github.com/amacneil/dbmate). It's a relatively well known library.

### Initial Setup

The beauty of `dbmate` is its simplicity. The intial database schema is simply setup in the first migration file. Then further changes to the schema are given their own migration file.

It's best to have one single migration file per feature branch (see [version control](./version_control.md)).