# Doctrine changes surfaced during envmageddon implementation

Doctrine-facing findings from implementing advance 003 (mods 076-086). The
**Recommended** section is pending — apply these against the doctrine. The
**Already applied** section records doctrine edits made *during* implementation
(committed, listed for traceability). The **Considered / no action** section
records things looked at and deliberately not changed.

Paths are relative to the repo root (`~/.claude/jean_baudrillard/`).

---

## Applied against doctrine (post-implementation)

Items 1 and 2 below were applied as doctrine-only edits (the implementation
already behaved this way, so no code/table/test changes rode along).

### 1. Config delivery on elastic is imprecise — it is `secrets[]`-`valueFrom`, not `environment[]`

**Status: APPLIED.** Both sites in `config_and_secrets.md` reworded — config on
elastic is now described as an ECS `secrets[]` entry whose `valueFrom` sources a
plain `String` SSM parameter (vs. `SecureString` for secret/TTE), never an
`environment[]` entry.

**File:** `doctrine/infrastructure/specifics/config_and_secrets.md`
**Sites:** § *Materialization at Release* (line ~191) and § *How Values Reach
Application Code* (the Elastic row, line ~207).

**Problem.** Both sites describe config being delivered on elastic via an ECS
`environment[]` entry that *sources* the SSM path:

- L191: "The emitted HCL provisions ECS task definitions whose `secrets[]` /
  **`environment[]`** blocks reference those paths."
- L207: "ECS `secrets[]` (secret/TTE) or **`environment[]`** (config) entry
  sourcing `/<project>/<env>/…`"

ECS `environment[]` entries are **static inline `name`/`value` pairs** — they
cannot `valueFrom` an SSM parameter. Only `secrets[]` can source from SSM, and
`secrets[]` `valueFrom` works against a **plain `String`** SSM parameter just as
well as a `SecureString`. So config is delivered through the **same
`secrets[]`-`valueFrom` mechanism as secrets**, differing only in the SSM
*storage* type (`String` vs `SecureString`), not the ECS delivery verb.

**This is how the implementation actually works** (Mod 078/082): a `config:`
key compiles to the identical `$[KEY]` runtime ref as a secret and rides the
existing `_partition_env` → `secrets[]` path; the `String`/`SecureString` split
is purely the push-time decision in `aggregate_elastic` (Mod 082). No emitter
distinguishes config from secret at the container edge.

**Recommended edit.** Reword both sites so config on elastic is an ECS
`secrets[]` entry whose `valueFrom` points at a plain `String` SSM parameter
(the non-secret storage type), NOT an `environment[]` entry. E.g. L207 →
`ECS secrets[] entry sourcing /<project>/<env>/<KEY> (SecureString for
secret/TTE, plain String for config)`. Note `cicl.md` line 119 already states
this correctly ("delivered to the container the same way a secret is") — only
`config_and_secrets.md` carries the `environment[]` imprecision.

### 2. Parts-only rule — clarify that `kind: fixed` literals are exempt

**File:** `doctrine/infrastructure/specifics/config_and_secrets.md` § *Parts-Only
Rule* (and the mirror in `transfer_tables.md`).

**Context.** The parts-only rule forbids composing a **secret** into a larger
string. Since Mod 077, a `kind: fixed` engine var is inlined to its literal at
compile, so it is a plain literal — not a runtime ref — by the time the
compiler's parts-only guard runs. A fixed literal *can* therefore be freely
composed (e.g. `postgres://appuser@host/db`), which the guard previously would
have flagged.

**Status: APPLIED** — and it was **more than the optional note** originally
scoped. `config_and_secrets.md § Parts-Only Rule` got the one-line exemption
note as planned. But the `transfer_tables.md` mirror (the § *Anatomy* `provides`
hard-rule prose) carried **stale drift**, not just a missing clarification: it
cited `$[POSTGRES_USER]` alongside `$[POSTGRES_PASSWORD]` as "secrets that never
appear as inline values." Since Mod 077 `POSTGRES_USER` is `kind: fixed`
(`value: appuser`, confirmed in `tables/roles/relational_db.yml`) — it is inlined
and *does* appear inline. That sentence was corrected to cite only
`$[POSTGRES_PASSWORD]` and to name `POSTGRES_USER` as the opposite (fixed-literal)
case. `config_and_secrets.md` line ~231 already listed only `POSTGRES_PASSWORD`,
so it needed no drift fix — only the new exemption note.

---

## Already applied during implementation (committed — for the record)

### 3. `docex.md § config` command section — added (Mod 084)

**File:** `doctrine/infrastructure/docex.md` — a `### config` section was
**added** (mirrors `### secrets`) documenting `docex config
scaffold/status/set/get/copy`. `docex.md` previously documented the `secrets`
group but not `config`, while `config_and_secrets.md § Tooling` already mandated
the config ops — so this closed a doc gap rather than inventing a rule. Already
committed (Mod 084). No further action; noted for traceability.

---

## Considered / no action (for transparency)

### 4. Two `cicl.md` rewordings a sub-agent made were reverted

During Mod 084 a sub-agent made two unrequested `cicl.md` edits that I reverted
(the doctrine's wording is load-bearing and these were out of scope):

- **`config` field-table row:** re-pointed its link from
  `specifics/config_and_secrets.md` → `configurable.md#config`, and "config
  values" → "config variables". *Possibly* a reasonable improvement — linking
  the resident overview (`configurable.md`) rather than the conditional
  specifics may fit a field-table reference better — but it changes a link the
  author chose deliberately, so it's the operator's call. Reverted; flagging in
  case you want it.
- **§ Provided Fields prose:** "fundamental properties like `port` or even
  secrets like `password`" → "like `port` or `host`". This *removes* a valid
  example (`password` as a provided secret); not an improvement. Reverted, no
  action recommended.

### 5. `migrate stage/prod` ordering assumption (core-doc, not doctrine)

`docex migrate stage/prod` reads the host `.env` a prior `release` rendered; it
does not itself rebuild the aggregate (Mod 081). This ordering assumption was
documented in `docex/plans/core/release_flow.md` (Mod 086). It is a docex-behavior
note, not a doctrine rule, so no `doctrine/` change is needed — noted only so it
isn't re-discovered as a surprise.
