# `object_store`/`minio` ignores `version:`

In the shipped table `tables/roles/object_store.yml`, the `minio` engine
hardcodes its image tag — `defaults.fixed.image: "minio/minio:latest"` — and its
`fields:` block declares only `versioning`, never `version`. A `version:` set on
an `object_store` service in `infra.yml` is accepted by validation and then
silently ignored: the compiled compose emits `minio/minio:latest` regardless.
`minio` is the lone backing engine that does not pin its tag from `version:`.

An unpinned tag on a stateful backing service breaks the determinism promise.
Rebuilding an environment later pulls whatever `minio/minio:latest` points at
then, against an existing data volume — drift that surfaces as data-layer
breakage rather than a clean failure.

Every other engine pins correctly. `relational_db`/`postgres` is the model, now
dual-arm: `fields.version.fixed → image: postgres:${field_value}` and
`fields.version.elastic → engine_version: ${field_value}`.

## Changes to make

1. In `tables/roles/object_store.yml`, add a `version` field to the `minio`
   engine, mirroring `postgres` (fixed arm only — `minio` is `foundation: fixed`):

   ```yml
   fields:
     version:
       fixed:
         image: "minio/minio:${field_value}"
     versioning:            # unchanged
       fixed:
         x-versioning: ${field_value}
   ```

2. Drop the hardcoded `image: "minio/minio:latest"` from `minio`'s
   `defaults.fixed` so `version:` is authoritative.

## Constraints

- **`s3` needs no change.** It is `foundation: elastic`, emits `s3_bucket`, and
  carries no image or version — an S3 bucket has neither. `version:` on an
  `object_store` service is meaningful on the fixed (`minio`) arm only.
- **Missing `version` is a compile error (decided at plan review).** `cicl.md §
  Service Fields` marks `version` **required** for backing services, but nothing
  enforces it — `version` is only in `validate.py`'s `_STANDARD_BACKING_FIELDS`
  allowlist, so omitting it compiles green. Enforce it engine-nuanced: required
  where the engine has a `version` field, so `s3` is exempt. This aligns the code
  to cicl.md's existing "required" claim rather than inventing a pinned fallback;
  `latest` was never defensible.
