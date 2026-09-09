# Mod 159 — Implementation Steps

Fresh-context executor: perform these in order. All paths are relative to the repo
root `/home/ubuntu/.claude/jean_baudrillard` (the `jean_baudrillard` doctrine repo).
Work on branch `010_archdoc_overhaul` (do not create branches, do not commit — the
corporal handles commits).

**Scope fence (do not cross):** edit only the files named below, all under
`doctrine/` plus the one new skill under `skills/`. Do **not** edit `skills/` bodies
other than the new `writing-adrs` skill, do **not** edit `agents/`, do **not** edit
`docex/` source or `docex/plans/`, and do **not** hand-edit `RESIDENT.md` (it is
generated). Do **not** bump any version artifact.

---

## Step 1 — Install `docs.md` (copy draft, then repair links)

1a. Copy the finalized draft over the resident doc:
```
cp docex/plans/advances/010_archdoc_overhaul/docs.md doctrine/practices/docs.md
```
The draft already carries `stratum: resident` frontmatter — keep it.

1b. Apply these exact edits to `doctrine/practices/docs.md` (each `old` string is
unique in the file). These repair placeholder/broken links so `linkcheck` passes and
install the required resident pointer to `adrs.md`.

Edit 1 (transfer-table link):
- old: `[transfer table](TODO TIE INTO CICL.MD)`
- new: `[transfer table](../infrastructure/cicl.md#cicl-transfer-tables)`

Edit 2 (controller-mechanism link):
- old: `[controller mechanism suffix](TODO TIE INTO HEX_OVERVIEW.MD)`
- new: `[controller mechanism suffix](../hexagonal_architecture/hex_overview.md#controller-mechanism)`

Edit 3 (broken self-anchor → resident ADR pointer):
- old: `| Architecture Decisions | N/A | N/A | These go in the `adr` directory; see [below](#architecture-decision-records) |`
- new: `| Architecture Decisions | N/A | N/A | These go in the `adr` directory; see [adrs.md](./adrs.md) |`

Edit 4 (dangling example link in unknowns table → inline code):
- old: `| 0 | x_service_api_doc | Docs for X Service REST API. | [x_api_ref.openapi.json](../references/x_api_ref.openapi.json) |`
- new: `| 0 | x_service_api_doc | Docs for X Service REST API. | `references/x_api_ref.openapi.json` |`

Edit 5 (docex link text polish; anchor already valid):
- old: `See [TODO](#docex) for more info.`
- new: `See [Docex](#docex) for more info.`

Edit 6 (remove `TODO REF` placeholders inside the structure tree; two edits):
- old: `│   ├── mods    # See [modifications.md](TODO REF)`
- new: `│   ├── mods    # see modifications.md`

- old: `│   └── adv     # See [advance.md](TODO REF)`
- new: `│   └── adv     # see advance.md`

Do **not** touch the `<TODO>` prose markers ("Move the above to diagrams…", the
`## Docex` bullet stubs) — they are intentional and belong to later mods.

---

## Step 2 — Install `comments.md` (verbatim copy)

```
cp docex/plans/advances/010_archdoc_overhaul/comments.md doctrine/practices/comments.md
```
No repairs — every link in this draft already resolves, and it keeps its
`stratum: resident` frontmatter. Its H1 is "Code-Level Documentation"; the FILENAME
stays `comments.md` (do not rename the file).

---

## Step 3 — Install `adrs.md` as conditional stratum

3a. Copy the draft:
```
cp docex/plans/advances/010_archdoc_overhaul/adrs.md doctrine/practices/adrs.md
```

3b. The draft's first line is blank and it has NO frontmatter. Prepend
`stratum: conditional` frontmatter so it is the very first line. Apply this single
Edit to `doctrine/practices/adrs.md`:
- old (the file's first heading line, with the blank line above it):
```

# Architecture Decision Records
```
- new:
```
---
stratum: conditional
---

# Architecture Decision Records
```
After this edit, confirm line 1 of the file is exactly `---` (frontmatter must be the
first line). Leave the rest of the draft, including its trailing `<TODO>` docex stub,
verbatim.

---

## Step 4 — Author the `writing-adrs` thread skill

Create `skills/writing-adrs/SKILL.md` with EXACTLY this content:

```
---
name: writing-adrs
description: Doctrine for authoring an Architecture Decision Record (ADR) — the file format, the status lifecycle, and the generated index files that capture the *reasoning* behind a design decision. Use this whenever you are writing, recording, proposing, accepting, superseding, or deprecating an ADR, or need to durably capture *why* a design choice was made, even if you never say the word "ADR".
metadata:
  type: thread
---

# writing-adrs

Recording an architecture decision (ADR) is one activity: capture the *reasoning*
behind a design choice as an immutable, append-only record, then regenerate the
indexes. The format spec is short — read it now.

## General Information

Critical orienting information — **read the referenced file now.**

[adrs.md](../../doctrine/practices/adrs.md) — the whole ADR practice: why ADRs exist
(they hold the reasoning that would otherwise clutter the lightweight state design
docs), the per-file frontmatter schema, the status enum, the immutable / append-only
rule, and the two generated index files (`adr_index.md`, `adr_active.md`).

## Specific Information

Detailed context — read on demand.

[docs.md](../../doctrine/practices/docs.md) — where ADRs sit in the documentation
taxonomy: they are the *reasoning-doc* half of the design docs, stored under
`plans/design/adrs/`. Read this if you need to place the ADR correctly or understand
its relationship to the state design docs.

## Thread

Write an ADR whenever a design decision needs its *why* preserved. Read `adrs.md` for
the frontmatter schema and status enum, then:
1. Pick the next sequential integer `id` and name the file `${id}_${snake_case_title}`
   under `$pr/plans/design/adrs/`.
2. Fill `Context` / `Decision` / `Consequences`; set `status` (usually `proposed`,
   then `accepted` once agreed).
3. Old ADRs are **immutable** — never edit a shipped decision. To change one, write a
   *new* ADR and link the pair with `supersedes` / `superseded-by`.
4. Regenerate the index files (`adr_index.md` + `adr_active.md`) rather than
   hand-editing them — they are derived from the ADR files by `docex`.
```

---

## Step 5 — Cross-corpus rewire (exact edits)

### 5a. `doctrine/lexicon.md` (redefine the term)
- old: `| Core Planning Docs | "core docs", "core project docs", "project documentation" | The architectural and module docs found at "$pr/plans/core/*". |`
- new: `| Design Docs | "core planning docs", "core docs", "project documentation" | The project's design-documentation corpus, stored at "$pr/plans/design/*": the arc42 state docs, the standard diagrams (Project / Service / Module), module docs, and ADRs. |`

### 5b. `doctrine/infrastructure/infrastructure.md` (repo-structure tree)
Replace the `plans` subtree. 
- old:
```
└── plans
    ├── modifications
    ├── core
    └── references
```
- new:
```
└── plans
    ├── product     # Optional; product docs
    ├── design      # Design docs: arc42 state docs, diagrams, module docs, ADRs
    ├── ops
    │   ├── mods    # Modification cycles
    │   └── adv     # Advances
    └── references
```
(Line 214's `[here](../practices/docs.md)` link is correct — leave it.)

### 5c. `doctrine/hexagonal_architecture/hex_overview.md` (two edits)
Edit 1 (project-specific-patterns pointer):
- old: `In that case, the pattern should be documented in [conventions.md](../practices/docs.md).`
- new: `In that case, the pattern should be documented as a doctrine extension in the project's `doctrine_ext.md` (see [docs.md § Cross-Cutting Concepts](../practices/docs.md#cross-cutting-concepts)).`

Edit 2 (module-doc model):
- old: `High level conceptual documentation for a module belongs in the module's [master document](../practices/docs.md) file. This file should contain the following:`
- new: `High level conceptual documentation for a module belongs in that module's L3 [module doc](../practices/docs.md#design-documentation) — a design doc living under `plans/design/${codebase}/module/`. This file should contain the following:`

### 5d. `doctrine/practices/modifications.md`
- old: `	1. Create a new [modification folder](./docs.md) in the modification documentation in `$pr/plans/modifications`.`
- new: `	1. Create a new [modification folder](./docs.md#standard-documentation-structure) in the modification documentation in `$pr/plans/ops/mods`.`
(Line 47's `[core planning docs](./docs.md)` resolves and "core planning docs" is now
a lexicon synonym — leave it.)

### 5e. `doctrine/practices/advance.md` (two edits)
- old: `Every individual advance gets a folder at `$pr/plans/advances/${advance_number}_${advance_name}/`. This folder contains:`
- new: `Every individual advance gets a folder at `$pr/plans/ops/adv/${advance_number}_${advance_name}/`. This folder contains:`

- old: `	4. Create the advance folder at `$pr/plans/advances/${advance_number}_${advance_name}` if it does not already exist.`
- new: `	4. Create the advance folder at `$pr/plans/ops/adv/${advance_number}_${advance_name}` if it does not already exist.`
(Leave `plans/references` on line 66 and the "core planning docs" phrases — all valid.)

### 5f. `doctrine/practices/inception.md` (masterplan → design-brief / design-docs)
Edit 1 (L7):
- old: `all we have is a rough idea in the form of a [masterplan](./docs.md#the-masterplan) document`
- new: `all we have is a rough idea in the form of an initial [design brief](./docs.md#design-documentation)`

Edit 2 (L12):
- old: `1. A `masterplan.md` document, detailing the project's:`
- new: `1. An initial design brief, detailing the project's:`

Edit 3 (L27):
- old: `1. Read the `masterplan.md`. If the operator has not indicated where this is, ask them.`
- new: `1. Read the initial design brief. If the operator has not indicated where this is, ask them.`

Edit 4 (L48):
- old: `	6. Write `masterplan.md` verbatim into its place at `$pr/plans/core/masterplan.md`.`
- new: `	6. Place the initial design brief under `$pr/plans/design/` to seed the project-level design docs; PART II unpacks it into the full arc42 structure.`

Edit 5 (L54):
- old: `The project has now been set up. Basic structure exists and the `masterplan.md` is in the defined place. Everything from this point on goes wherever the `doctrine` prescribes.`
- new: `The project has now been set up. Basic structure exists and the initial design brief is in place under `plans/design`. Everything from this point on goes wherever the `doctrine` prescribes.`

Edit 6 (L61):
- old: `The design phase should "fill out" the [core planning docs](./docs.md#core-planning-documents). Each codebase should be given a folder in `$pr/plans/core`, and filled out with architecture and design docs. Codebases with internal hexagonal architecture should have module docs for each planned hexagonal module.`
- new: `The design phase should "fill out" the [design docs](./docs.md#design-documentation) — the arc42 project-level (L1) state docs, the standard diagrams, and per-codebase docs. Each codebase should be given a folder in `$pr/plans/design`, and filled out with codebase-level (L2) and module-level (L3) design docs. Codebases with internal hexagonal architecture should have a module doc for each planned hexagonal module.`

Edit 7 (L63):
- old: `All these core planning docs are driven by `masterplan.md`. They "unpack" those high-level plans into more concrete architecture and design docs.`
- new: `All these design docs are driven by the initial design brief. They "unpack" those high-level plans into the concrete arc42 state docs, diagrams, and module docs.`

Edit 8 (L70):
- old: `4. Write `infra.yml` to reflect the needs of the core planning docs.`
- new: `4. Write `infra.yml` to reflect the needs of the design docs.`

**Do NOT edit `doctrine/infrastructure/credentials.md`** — its only `masterplan` hit
is a link into `docex/plans/core/masterplan.md` (docex's own docs, out of scope; Mod 7
migrates that). Leaving it keeps the link resolving.

---

## Step 6 — Regenerate the resident manifest & verify

6a. Run the resident-manifest generator (idempotent) so RESIDENT.md reflects
frontmatter; confirm `adrs.md` did NOT join:
```
bash setup/claude/gen_resident.sh
```
Then confirm `RESIDENT.md` still contains `docs.md` and `comments.md` and does NOT
contain `adrs.md`.

6b. Run the link checker gate (must be GREEN — exit 0, "No broken links…"):
```
python3 skills/cohere/executor/linkcheck.py
```
If any BROKEN FILE / BAD ANCHOR / BAD CITATION / NO CITE FILE problem is reported for
a file this mod edited, fix it and re-run. Report the final linkcheck output verbatim.

## Step 7 — Report
Report: files created/edited, the `gen_resident.sh` result (did adrs.md stay out?),
and the full final `linkcheck.py` output. Do not commit.
