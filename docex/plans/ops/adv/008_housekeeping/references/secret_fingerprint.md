# `docex secrets` — value fingerprints

## Summary

Add a non-revealing **fingerprint** to the redacted secrets read so an operator
(or an agent that cannot read secret values) can verify a secret's **propagation
and consistency across environments** — and detect drift — without ever exposing
the value. The motivating case: after copying secrets `dev → stage → prod`, there
is no way to confirm all four envs actually hold the *same* value for a key, which
forces reasoning from stale assumptions instead of evidence.

## Problem

`docex secrets status` reports only `SET` / `UNSET` per key (correctly redacted).
That answers "does a value exist?" but not:

- Do `dev`, `stage`, and `prod` hold the **same** value for this key? (Did a
  `docex secrets copy` actually land? Has one env drifted?)
- Is a key's value identical to what it was before some operation?

There is deliberately **no** way to read a secret value, so today these questions
can only be answered by a human eyeballing the `.env` files — which defeats the
point of the redacted tooling and is exactly what an agent cannot do.

## Proposed feature

A fingerprint = a short, salted, one-way hash of the value, safe to display:

```
fingerprint(key, value) = hex( sha256( SALT || value ) )[:8]
```

- **Salt.** A fixed, project-local, **non-secret** salt (e.g. derived from the
  project name) so fingerprints are stable and comparable *within a project* but
  not trivially matchable against a global rainbow table of common tokens. The
  salt is not a secret; it only needs to stop a bare `sha256` from being
  dictionary-checked.
- **Length.** 8 hex chars (32 bits) — enough to spot equality/drift across a
  handful of envs with negligible accidental-collision risk, far too short to
  brute-force a high-entropy secret back out.

### Surface

- `docex secrets status <env> --fingerprint` — the existing per-key table gains a
  `FINGERPRINT` column (blank for `UNSET`).
- `docex secrets fingerprints [--format json]` — a cross-env matrix: one row per
  key, one column per env, each cell the fingerprint (or `—` for unset). The
  primary "did it propagate / has it drifted?" view:

  ```
  KEY                dev       test      stage     prod
  DISCORD_BOT_TOKEN  a60cb14d  a60cb14d  a60cb14d  a60cb14d
  TELEMETRY_API_KEY  1f9c02be  1f9c02be  0000none  1f9c02be   <- stage drifted/unset
  ```

## Where it lands

`secretsmgmt/engine.py` is a unified engine — `scaffold`/`status`/`set`/`copy`
serve both the secret and config categories via a `CategoryPolicy`
(`values_visible`). `status()` already loads each key's value into its row and
merely redacts it for the secret category, so the fingerprint is computed from a
value already in hand — a pure addition, no read path opened.

Scope it to the **secret** category. Config values are already visible
(`status`/`get` print them), so a fingerprint there is redundant; the feature
exists precisely for the value-blind case.

## What it does NOT do

- It does **not** reveal or approximate the value, and does not let a value be
  reconstructed.
- It does **not** distinguish a "real" value from a "placeholder/dummy" — two
  envs sharing a fingerprint proves only that they hold the *same* value.
  Real-vs-dummy stays a human judgment.

## Fit

Pure addition to the read-only `status` family; no change to `set` / `copy` /
`scaffold`. `copy` could optionally print source and destination fingerprints
after a value-blind copy to confirm the transfer landed. Composes with the
doctrine rule that agents may run `secrets status` freely — fingerprints carry no
secret material.
