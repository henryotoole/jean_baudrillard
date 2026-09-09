# Mod 159: Documentation-Doctrine Swap + Cross-Corpus Rewire

## Goal

Install the finalized new documentation model (advance 010, Goal 1) and rewire the
`doctrine/` corpus to it. This is the foundational mod of the advance — the source
of truth everything downstream coheres to. Placement is mechanical (drafts are the
spec); the work is the rename sweep plus repairs that keep the `linkcheck` gate green.

## Design source

The design is finalized as drafts in the advance folder and is treated as the spec:
- `docex/plans/advances/010_archdoc_overhaul/docs.md`
- `docex/plans/advances/010_archdoc_overhaul/comments.md`
- `docex/plans/advances/010_archdoc_overhaul/adrs.md`

## Changes

### 1. Install `docs.md` + `comments.md`
Replace `doctrine/practices/docs.md` and `doctrine/practices/comments.md` with the
drafts, keeping `stratum: resident` frontmatter. `comments.md`'s H1 becomes
"Code-Level Documentation" but the **filename stays `comments.md`** (RESIDENT.md
`@`-includes it by path).

### 2. Install `adrs.md` as CONDITIONAL stratum
Place the ADR spec at `doctrine/practices/adrs.md` with `stratum: conditional`
frontmatter (the draft ships with no frontmatter; it is prepended).

**Residency mechanism (verified):** `RESIDENT.md` is a *generated* manifest —
`setup/claude/gen_resident.sh` scans `doctrine/**` for files whose leading
frontmatter declares `stratum: resident`, shallowest-path first, and writes the
`@`-include list. It is idempotent and runs at setup and on SessionStart. Therefore:
- `docs.md` + `comments.md` keep `stratum: resident` → stay in RESIDENT.md.
- `adrs.md` gets `stratum: conditional` → the generator skips it; it never becomes
  resident. **RESIDENT.md is not hand-edited** (it carries a "do not edit by hand"
  banner and is fully derived). Resident budget respected (advance Goal 1 SC5).

`docs.md` carries the required resident *pointer* (a live link) to `adrs.md` — see
Repair (b) below.

### 3. ADR thread skill
New thread skill `skills/writing-adrs/SKILL.md` (`metadata: type: thread`), a
router into `adrs.md` per the doctrine thread-skill form (`doctrine/skills/skills.md`
§ Form). Skills are auto-discovered from `skills/*/SKILL.md` (plugin.json carries no
explicit list), so no registration step. Name/description chosen per skill-iteration
(crisp, pushy activity trigger keyed to "writing/recording an ADR").

### 4. Cross-corpus rewire + `plans/` layout rename
Layout: `plans/core`→`plans/design`; `plans/modifications`→`plans/ops/mods`;
`plans/advances`→`plans/ops/adv`; `plans/references` unchanged; `plans/product` added
(optional). Vocabulary: the `masterplan` / module-"master document" model → the new
arc42 + standard-diagram (Project/Service/Module Diagram) model.

Files rewired (grep-confirmed exhaustive over `doctrine/`):
- `doctrine/lexicon.md` — "Core Planning Docs" term redefined (see decision D1).
- `doctrine/infrastructure/infrastructure.md` — repo-structure ASCII tree `plans/` subtree.
- `doctrine/hexagonal_architecture/hex_overview.md` — `conventions.md` pointer →
  `doctrine_ext.md`; "Module Docs / master document" section → new L3 module-doc model.
- `doctrine/practices/modifications.md` — `plans/modifications` → `plans/ops/mods`.
- `doctrine/practices/advance.md` — `plans/advances` → `plans/ops/adv`.
- `doctrine/practices/inception.md` — masterplan→arc42/design-doc vocab; `plans/core`
  → `plans/design`; broken `docs.md#` anchors repointed (see decision D2).

### Repairs to the drafts (required for the linkcheck gate)
The drafts contain placeholder / broken links that would fail `linkcheck` (which
parses `[text](target)` and resolves the target; only fenced blocks and inline-code
spans are exempt). These are repaired on install — this is the "verify/repair that
link resolves" part of scope, not a redesign:
- (a) `docs.md` L141 `[transfer table](TODO TIE INTO CICL.MD)` →
  `../infrastructure/cicl.md#cicl-transfer-tables`; `[controller mechanism suffix]
  (TODO TIE INTO HEX_OVERVIEW.MD)` → `../hexagonal_architecture/hex_overview.md#controller-mechanism`.
- (b) `docs.md` L125 `see [below](#architecture-decision-records)` → `[adrs.md](./adrs.md)`.
  The `#architecture-decision-records` anchor does not exist in the new `docs.md`
  (ADRs moved out to `adrs.md`); repointing both fixes the dangling anchor **and**
  supplies the required resident pointer from `docs.md` to `adrs.md`.
- (c) `docs.md` unknowns-table example `[x_api_ref.openapi.json](../references/...)`
  resolves to a nonexistent doctrine path → neutralized to inline-code
  `` `references/x_api_ref.openapi.json` `` (it is an illustrative example row, not a
  live doctrine link).
- (d) `docs.md` `TODO REF` placeholders inside the fenced structure tree → plain
  `see modifications.md` / `see advance.md` (fence-exempt, but the placeholder is
  removed for cleanliness); `[TODO](#docex)` link text → `[Docex](#docex)`.

The `<TODO>` prose markers in `docs.md` ("Move the above to diagrams and link", the
`## Docex` bullet stubs) are **kept verbatim** — they are part of the finalized draft
and track work owned by later mods (Mod 4 diagrams, Mod 6 docex docs). They are not
markdown links and do not affect the gate.

## Gate
`python3 skills/cohere/executor/linkcheck.py` GREEN (default roots) before COMPLETE.

## Decisions / notes (sarge pre-ruled the majors; these are how they were applied)

- **D1 — "Core Planning Docs" lexicon term.** The phrase "core planning docs" is used
  pervasively across `advance.md`, `modifications.md`, `inception.md`, and skills/agents
  (Mod 5). Rather than a corpus-wide phrase rename (over-reach, large blast radius), the
  lexicon term is **redefined** to point at `plans/design` and describe the new
  design-doc corpus, keeping "core planning docs / core docs / project documentation"
  as synonyms so existing prose stays valid. Skills/agents re-terming, if any, is Mod 5.

- **D2 — inception.md depth.** `inception.md` (conditional) is masterplan-centric. The
  advance assigns the inception *skill* + `docex docs scaffold` integration to Mods 2/5.
  Here I do the mechanical layout/vocab conversion only: retire the `masterplan.md`
  term in favor of an initial "design brief" seed that PART II unpacks into the
  `plans/design` arc42 corpus, fix `plans/core`→`plans/design` and the broken `docs.md`
  anchors. I do **not** invent the not-yet-existing `docex docs scaffold` step or a
  precise seed-file mapping — that is Mod 2/5 design. Flagged as deliberate residue.

- **D3 — credentials.md left unchanged (deliberate residue).** Its only `masterplan`
  hit is `[docex's masterplan](../../docex/plans/core/masterplan.md#the-shim)` — a link
  into *docex's own* `plans/core`, which the scope fence forbids editing and which
  Mod 7 migrates to `design/`. Repointing it now would dangle (target still lives at
  `plans/core`). Left as-is; Mod 7 updates it when it moves docex's own docs.

- **D4 — masterplan-model prose removed from `docs.md`** entirely, since the draft is a
  wholesale replacement (no masterplan concept survives in the new model).

No open blocking questions. Sarge's two pre-decided rulings (adrs.md home =
`doctrine/practices/adrs.md`; ADR skill = short thread skill triggered by "writing an
ADR") are adopted as given.
