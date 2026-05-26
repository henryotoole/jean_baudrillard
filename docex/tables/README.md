# Canonical Transfer Tables

This directory holds the canonical role/engine transfer tables that ship inside the `docex` image at `/opt/docex/tables/`. They define how each abstract CICL role compiles to provider-specific resources for both the `fixed` and `elastic` foundations.

See the doctrine's [transfer_tables.md](../../doctrine/infrastructure/specifics/transfer_tables.md) for the full format spec.

## Layout

One YAML file per role:

```
tables/
  roles/
    web.yml             # core service container role (both foundations)
    relational_db.yml   # postgres on fixed and elastic (RDS)
    cache.yml           # redis on fixed and elastic (ElastiCache)
    object_store.yml    # minio (fixed) + s3 (elastic)
    reverse_proxy.yml   # marker role; machine-wide traefik on fixed, ALB on elastic
```

Each file is rooted at `roles:` so files can be deep-merged into one logical table at load time.

## Merge semantics

Projects may extend or override these by placing additional YAML files under `<project_root>/infra/transfer_tables/`. The loader merges them in this order:

1. Bundled tables (this directory).
2. Project-local tables.

The merge is **deep** — dicts merge key-by-key recursively, while scalars and lists are replaced wholesale by the override. Example: a project that wants to change just the postgres `instance_class` on elastic places this in `infra/transfer_tables/relational_db.yml`:

```yml
roles:
  relational_db:
    postgres:
      defaults:
        elastic:
          instance_class: "db.t3.large"
```

…and only that one leaf is overridden; the rest of the postgres entry is inherited from the bundled table.

To **add** a new engine to an existing role, declare it under the same role key with a new engine name. To **add** a new role, declare it at top level under `roles:`.

`None` values do **not** unset keys — to "remove" a default you must override it with an explicit empty value.
