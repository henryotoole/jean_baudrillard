# `docex secrets` — value fingerprints

## Summary

Add a non-revealing **fingerprint** to `docex secrets status` so an operator (or
an agent that cannot read secret values) can verify a secret's **propagation and
consistency across environments** — and detect drift — without ever exposing the
value. Motivated by the `field_radio` inception: after copying secrets
`dev → stage → prod`, there was no way to confirm all four envs actually held the
same `DISCORD_BOT_TOKEN`, which led to reasoning from stale assumptions instead of
evidence.

## Problem

`docex secrets status` reports only `SET` / `UNSET` per key (correctly redacted).
That answers "does a value exist?" but not:

- Do `dev`, `stage`, and `prod` hold the **same** value for this key? (Did a
  `docex secrets copy` actually land? Has one env drifted?)
- Is a key's value identical to what it was before some operation?

There is deliberately **no** way to read the value, so today these questions can
only be answered by a human eyeballing the `.env` files — which defeats the point
of the redacted tooling and is exactly what an agent cannot do.

## Proposed feature

A fingerprint = a short, salted, one-way hash of the value, safe to display:

```
fingerprint(key, value) = hex( sha256( SALT || value ) )[:8]
```

- **Salt.** Use a fixed, project-local, **non-secret** salt (e.g. derived from
  the project name) so fingerprints are stable and comparable *within a project*
  but not trivially matchable against a global rainbow table of common tokens.
  The salt is not a secret and its exposure does not weaken anything — it only
  needs to prevent a bare `sha256` from being dictionary-checked.
- **Length.** 8 hex chars (32 bits) is enough to spot equality/drift across a
  handful of envs with negligible accidental-collision risk; it is far too short
  to brute-force a high-entropy secret back out.

### Surface

- `docex secrets status <env> --fingerprint` — the existing per-key table gains a
  `FINGERPRINT` column (blank for `UNSET`).
- `docex secrets fingerprints [--format json]` — a cross-env matrix: one row per
  key, one column per env, each cell the fingerprint (or `—` for unset). This is
  the primary "did it propagate / has it drifted?" view:

  ```
  KEY                dev       test      stage     prod
  DISCORD_BOT_TOKEN  a60cb14d  a60cb14d  a60cb14d  a60cb14d
  TELEMETRY_API_KEY  1f9c02be  1f9c02be  0000none  1f9c02be   <- stage drifted/unset
  ```

## What it does NOT do

- It does **not** reveal or approximate the value, and does not let a value be
  reconstructed.
- It does **not** tell you whether a value is "real" vs a "placeholder/dummy" —
  two envs sharing a fingerprint only proves they are the *same* value. Real-vs-
  dummy remains a human judgment. (The `field_radio` confusion was partly this:
  fingerprints would have proven the copy propagated, but not that the token was
  a working Discord token.)

## Fit with existing tooling

Pure addition to the read-only `status` family; no change to `set` / `copy` /
`scaffold`. The `copy` op could optionally print the source and destination
fingerprints after a value-blind copy to confirm the transfer landed. Composes
with the doctrine rule that agents may run `secrets status` freely — fingerprints
carry no secret material.
