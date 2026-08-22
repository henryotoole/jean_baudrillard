# Mod 145 — advance 008 cohere fix-pass

A close-out corrective mod. Advance 008's `cohere` (doctrine) and `project-cohere`
(docex) audits found three real drift items the mods' own drift-checks missed,
plus two nits. All are **doc-only, corrective** edits — no code, no design
decisions — aligning the doctrine/core-doc *prose and examples* to changes the
eight mods already landed and the operator already approved. Executed directly by
the sergeant (not a corporal): the edits are surgical and I hold every site in
context.

## Findings & fixes

1. **BLOCKER — `doctrine/infrastructure/cicl.md` flagship `infra.yml` example.**
   The `bucket` `object_store` declares no `version:`, so mod 137's new
   `rule_version_required` rejects it and `cohere`'s `verify_examples.py` gate is
   RED. § Service Fields already marked `version` required (line ~161), so this was
   a latent example gap the new rule exposed. **Fix:** add a real minio `version:`
   (`RELEASE.2024-01-16T16-07-38Z`) to the bucket, with a comment that it pins the
   minio image tag (fixed) and that `s3` (elastic) is exempt.

2. **SHOULD-FIX — `doctrine/infrastructure/specifics/config_and_secrets.md`.**
   Line ~317 claims status redaction has "no length or hash, which would leak
   information" — directly contradicting mod 141's `secrets status --fingerprint` /
   `secrets fingerprints` (a salted `sha256[:8]`). This is the doc `configurable.md`
   and `docex.md` both cite as the authoritative model, so the corpus
   self-contradicts on a security property. **Fix:** reword the claim to describe
   the opt-in fingerprint honestly (equality/drift check, low-entropy caveat), and
   add the `--fingerprint` flag + the `fingerprints` op to the command table.

3. **SHOULD-FIX — `doctrine/infrastructure/specifics/transfer_tables.md` walking
   example.** The `web`/`container` walking example puts `launch_type: FARGATE` and
   `network_mode: awsvpc` in `defaults.elastic` — which mod 138's new
   `rule_elastic_defaults_unread_key` now rejects (code-confirmed), and which
   contradicts the doc's own new sentence (only the closed key set is read).
   **Fix:** drop those two keys from the example and reword the adjacent comment to
   note Fargate settings are compiler-owned invariants, not table defaults.

4. **NIT — `doctrine/practices/inception.md`.** New step 6 references "the first
   `docex merge` at PART V", but PART V only says "proceed along the CI/CD
   pipeline" without naming merge. **Fix:** name `docex merge` as the pipeline's
   first step at PART V.

5. **NIT (pre-existing) — `docex/plans/core/release_flow.md`.** The fixed-flow
   ASCII diagram and the four-sequences table list `docker pull` *before* the
   compose render, but the render must precede the pull (`docker_compose_v2_pull`
   needs the rendered compose file). Pre-existing, not an 008 regression; folded in
   opportunistically. **Fix:** swap the pull/render order in both.

## Verification
`verify_examples.py` must go GREEN (finding 1); `linkcheck` stays green; the test
suite is untouched (doc-only) and stays `1254 passed, 21 deselected`.

## Not in scope
The two deferred real-machine gates (mods 143/144) remain PENDING the
operator-supervised pre-cut walk. This mod changes no code and does not touch them.
