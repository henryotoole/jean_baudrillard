# Mod 145 — implementation steps

Doc-only. Each edit is surgical; exact anchors below. No code, no tests to add.

1. **`doctrine/infrastructure/cicl.md`** — in the flagship `infra.yml` example's
   `bucket:` block, add after `engine: [minio, s3]`:
   `version: "RELEASE.2024-01-16T16-07-38Z" # pins the minio image tag (fixed); s3 (elastic) has no image, so version is exempt there`

2. **`doctrine/infrastructure/specifics/config_and_secrets.md`**
   - Status table row → append `[--fingerprint]` to the invocation and note the
     non-revealing fingerprint column.
   - Add a `fingerprints` row (value-blind cross-env matrix; "no" for values in
     context).
   - Reword the "no length or hash" sentence to describe the opt-in fingerprint as
     an equality/drift check that is not a confidentiality guarantee for a
     low-entropy value.

3. **`doctrine/infrastructure/specifics/transfer_tables.md`** — in the `web`/
   `container` walking example's `defaults.elastic`, delete the `launch_type:
   FARGATE` and `network_mode: awsvpc` lines; reword the preceding comment so
   "Doctrine adds Fargate task settings" becomes "Fargate settings
   (`requires_compatibilities`/`network_mode`) are compiler-owned invariants
   emitted as literals, not table defaults — see the `defaults` field note above".

4. **`doctrine/practices/inception.md`** — PART V step 6: name `docex merge` as the
   pipeline's first step.

5. **`docex/plans/core/release_flow.md`** — swap the `docker pull` and `render
   compose.yml + .env` lines in the fixed-flow ASCII diagram, and swap rows 2 and 3
   of the four-sequences table's Fixed column, so render precedes pull.

## Verify
- `python3 skills/cohere/executor/verify_examples.py` → GREEN (was RED on the bucket).
- `python3 skills/cohere/executor/linkcheck.py` → green.
- `docex/.venv/bin/python -m pytest tests -q` → `1254 passed, 21 deselected` (unchanged).
