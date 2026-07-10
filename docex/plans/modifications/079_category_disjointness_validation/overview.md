# Mod 079 — Cross-category disjointness + reserved-key validation

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 4 of 11). Adds the compile-time validation that makes the three
value categories safe to aggregate as a plain disjoint union: no key may belong
to two categories, and doctrine-injected keys may not be redeclared.

## Why

`config_and_secrets.md §4.1` + `cicl.md` rules **16**, **20**: because
aggregation (Mods 080-082) merges TTE ∪ secrets ∪ config with **no precedence**,
a key claimed by two categories would have ambiguous provenance, value, and
read/write permission. The doctrine makes this a **compile error** — the
earliest, cheapest layer (`compiler.md`: "a compile error is always preferable").

Two rules land here (the classifier from Mod 078 does the heavy lifting):

- **Rule 16** — a core service's `env:`, `secrets:`, and `config:` do not
  declare the same key (per-service, container-env namespace). Today
  `_validate_env_secrets_overlap` checks env ∩ secrets; extend to three-way.
- **Rule 20** — the three categories are disjoint **project-wide by source
  key**; a key in more than one is a compile error, and doctrine-injected keys
  (`TELEMETRY_API_KEY`) are reserved (no redeclaration in any category).

## Ownership split (avoids double-reporting)

A project that declares a doctrine-injected key (e.g. puts `TELEMETRY_API_KEY`
in `config:`) would trip *both* the cross-category conflict (classify seeds
`secret` with the injected key, so it lands in secret+config) *and* the
reserved-key rule. To emit exactly one clear diagnostic:

- The **reserved-key** validator owns "a project may not declare a
  doctrine-injected key in any category" (`TELEMETRY_API_KEY`), and the existing
  "auto-injected core env" reserved keys (`PROJECT_VERSION`, `OTEL_*`) — now
  checked across `config:` too.
- The **disjointness** validator reports genuine project-vs-project
  cross-category collisions but **skips keys in `DOCTRINE_INJECTED_SECRETS`**
  (delegated to the reserved check).

`DOCTRINE_INJECTED_SECRETS` (defined in `cicl/categories.py`, Mod 078) is the
single source of truth for the injected-secret set.

## Rule 19 is not a compile check

`cicl.md` rule 19 ("every key a core service consumes from `config:` is declared
in its `config:` block") is trivially satisfied at compile — config has no
separate *consumption* syntax; the block *is* the declaration. The real
conformance (the value file `infra/config/<env>.env` contains exactly the
declared keys) reads files and lands with aggregation / `scaffold` (Mods
080/083). No rule-19 compile check here.

## Scope

**In:** broaden rule 16 to three-way (`validate.py`); new rule-20 disjointness
validator (via `classify_source_keys(...).conflicts()`, skipping injected keys);
extend the reserved-key check to `config:` and add the doctrine-injected-secret
reservation; tests.

**Out:** aggregation (Mods 080-082); tooling (083-084); the `emit/secrets.py`
TELEMETRY dedup (a `DOCTRINE_INJECTED_SECRETS` import there is deferred to Mod
086 cleanup — the two literals agree today).

## Doctrine anchors
- `cicl.md` rule 16 (line 412), rule 19 (415), rule 20 (416).
- `config_and_secrets.md §4.1 Collision rules` — disjoint across categories, shared within; doctrine-injected reserved.

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` (this mod) ⇄ `tests/**` (this mod). No
`tables/`, `emit/`, or doctrine change.
