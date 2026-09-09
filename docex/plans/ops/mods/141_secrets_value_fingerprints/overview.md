# Mod 141 — `docex secrets` value fingerprints

## Goal

Add a **non-revealing fingerprint** to the value-blind secrets tooling so an
operator — or an agent that structurally cannot read a secret value — can verify
a secret's **propagation and consistency across environments**, and detect
**drift**, without ever exposing the value. The design record is the advance
brief [`secret_fingerprint.md`](../../advances/008_housekeeping/references/secret_fingerprint.md);
this overview restates only the decisions that pin the implementation.

## What a fingerprint is

```
fingerprint(value) = hex( sha256( SALT || value ) )[:8]     # 8 hex chars, 32 bits
```

- Computed only for a **SET** value (a non-empty string). UNSET keys have no
  fingerprint.
- Scoped to the **secret category only**. Config values are already printed by
  `config status` / `config get`, so a fingerprint there is redundant; the
  feature exists precisely for the value-blind case. `CONFIG_POLICY` never
  produces fingerprints.
- Lands in `secretsmgmt/engine.py`. `status()` already loads each key's value
  into its row and merely redacts it for the secret category, so the fingerprint
  is computed from a value **already in hand** — a pure addition that opens **no
  new value-read path**.

## Resolved design decisions

The brief left two things under-specified; both are resolved here.

### 1. Salt derivation (fixed, project-local, non-secret)

```
SALT = ("docex-secret-fingerprint:" + ctx.project.name).encode("utf-8")
```

- **Project-local** so the same value fingerprints identically within one
  project (enabling the cross-env equality/drift comparison) but differently
  across projects — the same placeholder secret in two projects will not share a
  fingerprint, defeating a global rainbow table of common tokens.
- **Non-secret.** The salt is derived from the public project name and a fixed
  literal prefix; it is not stored anywhere secret and carries no confidential
  material. It only needs to stop a *bare* `sha256` from being matched against a
  precomputed global table.
- **Stable.** Derived purely from `project.yml`'s `name`, so it does not change
  between runs.

### 2. Unset sentinel (resolving the brief's internal inconsistency)

The brief's matrix example is inconsistent (`—` in prose, `0000none` in the
sample). Resolution — **one** sentinel, used consistently:

- **`status <env> --fingerprint`** (per-key table): the `FINGERPRINT` column is
  **blank** for an UNSET key, matching the brief and the column's existing
  `SET`/`UNSET` state.
- **`fingerprints`** cross-env matrix (text): an unset cell renders as the em
  dash **`—`**.
- **`fingerprints --format json`**: an unset cell is JSON **`null`** (the
  idiomatic machine-readable absence), never the string `—`.

## Surfaces

1. **`docex secrets status <env> --fingerprint`** — the existing per-key table
   gains a trailing `FINGERPRINT` column (blank for UNSET). Without the flag,
   `status` output is byte-for-byte unchanged. JSON `status` gains a
   `"fingerprint"` field per row **only** when `--fingerprint` is passed (value
   or `null`); this keeps the value-blind guarantee: the fingerprint is opt-in.

2. **`docex secrets fingerprints [--format json]`** — a new read-only op: a
   cross-env matrix over all four envs (`dev`/`test`/`stage`/`prod`), one row per
   secret key, one column per env, each cell a fingerprint or the unset sentinel.
   This is the primary "did it propagate / has it drifted?" view.

3. **`docex secrets copy` (nice-to-have, implemented):** after a value-blind
   copy the command additionally prints the source and destination fingerprints,
   letting the operator confirm the transfer landed without ever seeing the
   value. Secret category only.

`fingerprints` is a **secret-only** op — it is not added to `docex config`
(config is already value-visible, so a matrix of hashes there is pointless).

## Honesty caveat (documented in doctrine + `--help`/docstrings)

The brief's "does not let a value be reconstructed" is true for a **high-entropy**
secret but **not** for a **low-entropy** one: 8 hex characters plus a
project-name-derived (and therefore guessable) salt is dictionary-attackable for
a weak or placeholder value. The doctrine text and the CLI help/docstrings will
state honestly that fingerprints are for **equality/drift comparison**, reveal no
value directly, but are **not a confidentiality guarantee for a low-entropy
value** — a weak secret is inherently guessable from any hash of it. This matters
because value-blind agents read this text and must not over-trust it.

## Doctrine changes (surgical — new capability + caveat only)

Because this changes the `docex secrets` command surface,
[`docex_process.md`](../../core/docex_process.md) requires the doctrine to move
with it. Two minimal edits:

- `doctrine/infrastructure/configurable.md § Secrets` — the `docex secrets ...`
  ops table gains a `fingerprints` row (and a note that `status` takes
  `--fingerprint`), plus one honesty-caveat sentence.
- `doctrine/infrastructure/docex.md` (`### secrets`) — add the `fingerprints`
  invocation line and one bullet describing it and the caveat.

Both add the new op/flag + caveat only; neither section is rewritten.

## Drift check (six artifacts)

- **Doctrine:** the two edits above.
- **`docex/plans/core/masterplan.md`** — the Subcommand Surface row for `secrets`
  is updated to list `fingerprints` and note `--fingerprint`.
- **Transfer tables:** none (no role/engine touched).
- **src:** `secretsmgmt/engine.py` (add `fingerprint()`, extend `status`, add
  `fingerprints`, extend `copy_key`), `__main__.py` (wire `--fingerprint` and the
  `fingerprints` subcommand).
- **tests:** `tests/unit/test_secretsmgmt.py` additions (see implementation).
- **`doctrine_excerpts/secrets.md` + `index.yml`:** no resource introduced or
  retired. `secrets.md` mentions `scaffold`/`set` illustratively, not an
  exhaustive op list, so it stays accurate untouched — confirmed, no edit.
- **Skill pointers:** `configurable-vars` routes to `configurable.md § Secrets`
  and `docex.md#secrets`; both anchors survive (only rows/bullets are added
  under the existing headings). No skill edit — verify only.

## Tests

Unit only; nothing crosses docker/AWS/git. Cover:
- fingerprint **stability** (same value → same fingerprint);
- **salt varies by project** (same value, different `project.name` → different
  fingerprint);
- the **matrix** output shape (per-key rows, per-env columns, unset sentinel);
- **secret-category-only** (config produces no fingerprint surface);
- critically, a test asserting **no secret value ever appears** in
  `status --fingerprint` or `fingerprints` output (the value-blind guarantee);
- JSON shape for `fingerprints --format json` (and the `null` unset cell).

## Open design questions

None. The two under-specified points (salt derivation, unset sentinel) are
resolved above within the brief's stated intent; the honesty caveat is a
correction to the brief's "What it does NOT do" that the brief's own framing
invites. Nothing here forces a masterplan-level structural change.
