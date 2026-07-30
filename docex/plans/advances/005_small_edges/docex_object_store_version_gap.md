# `docex` Gap — `object_store`/`minio` Ignores `version:`

NOTE: this error originated in the `transcript_archive` project (/home/ubuntu/projects/transcript_archive).

A defect in the doctrine-shipped `docex` transfer tables, found while incepting
`transcript_archive` on 2026-07-27 against **`docex` 1.5.0**. This project carries a
project-local workaround; the real fix belongs upstream in `docex`.

## Summary

The `object_store` role's `minio` engine **hardcodes its image tag to `latest`** and
declares no `version` field. A `version:` on an `object_store` backing service in
`infra.yml` is therefore accepted by validation and then **silently ignored**.

Every other backing engine pins its tag from `version:`. `minio` is the lone exception.

## Evidence

The shipped table at `/opt/docex/tables/roles/object_store.yml` inside the `docex:1.5.0`
image:

```yml
roles:
  object_store:
    minio:
      foundation: fixed
      defaults:
        fixed:
          image: "minio/minio:latest"      # <-- hardcoded
          ...
      fields:
        versioning:                         # <-- the only declared field
          fixed:
            x-versioning: ${field_value}
```

Compare `relational_db`/`postgres` in the same table set, which does it correctly:

```yml
      fields:
        version:
          fixed:
            image: postgres:${field_value}
```

Observed behaviour: with `version: "RELEASE.2025-09-07T16-13-09Z"` set on the
`bundle_store` service, `./bin/docex compile` still emitted:

```
infra/output/dev/docker-compose.yml:154:    image: minio/minio:latest
```

`./bin/docex role object_store` corroborates it — it lists `versioning` as the only
role-specific field for the `minio` engine, while `relational_db` lists `version`.

Note also that `version` is documented as a **required** field for backing services in
the doctrine's `cicl.md` § Service Fields,
yet compile succeeded with it entirely absent from `bundle_store`. So there are arguably
two defects: the missing pin, and required-field validation not covering this role.

## Why It Matters

An unpinned tag on a **stateful** backing service breaks the doctrine's determinism
promise. Rebuilding an environment months later pulls whatever `minio/minio:latest` points
at then, against an existing data volume — a class of drift the doctrine exists to
eliminate, and one that surfaces as data-layer breakage rather than a clean failure.

It is especially acute for this project. `bundle_store` holds the **raw transcript
bundles**, which are the only source from which the universal form can ever be re-derived.
The masterplan's own worked example — a harness change forcing a universal-form change,
answered by re-parsing every historical bundle — depends entirely on that store staying
readable. It is the worst place in `transcript_archive` to accept a floating image tag.

## Workaround In Place

`infra/transfer_tables/roles/object_store.yml` — a project-local
transfer table (`cicl.md` § CICL Transfer Tables)
override that deep-merges the missing field in:

```yml
roles:
  object_store:
    minio:
      fields:
        version:
          fixed:
            image: "minio/minio:${field_value}"
```

It introduces nothing novel — it reproduces the `postgres` pattern verbatim. Deep merge
unions the `fields:` dict, so the doctrine's `versioning` field is untouched. With it in
place, `version:` in `infra.yml` becomes authoritative and compile emits the pinned tag
across all four environments.

`infra.yml` pins `version: "RELEASE.2025-09-07T16-13-09Z"` (MinIO's then-current release).

### Verifying

```bash
./bin/docex compile
grep -rn "minio/minio" infra/output/*/docker-compose.yml
# expect the pinned RELEASE.* tag in every env, never ":latest"
```

## Suggested Upstream Fix

In `docex`'s own `tables/roles/object_store.yml`, add a `version` field to the `minio`
engine exactly as `relational_db`/`postgres` declares one, and drop the hardcoded tag from
`defaults.fixed.image`. Decide deliberately whether omitting `version:` should then be a
compile error for this role (consistent with cicl.md's "required" claim) or should fall back
to a doctrine-chosen pinned release — either is defensible, but `latest` is not.

The `s3` engine needs no equivalent change: an AWS S3 bucket has no image and no version.

## Removing The Workaround

Once a `docex` release pins minio from `version:`:

1. Delete `infra/transfer_tables/roles/object_store.yml` (and the now-empty
   `infra/transfer_tables/` tree).
2. Keep the `version:` line in `infra.yml` — it becomes meaningful rather than redundant.
3. `./bin/docex compile` and confirm the pinned tag still appears in all four envs.

The override file carries a delete-me comment pointing here.
