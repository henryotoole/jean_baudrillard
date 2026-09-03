# Mod 164 — Implementation Steps

Documentation-prose only. Six edits across four doctrine files. All paths are
absolute from the jean root `/home/ubuntu/.claude/jean_baudrillard`. Do **not**
touch `docex/` source, `docex/plans/`, `skills/`, or `agents/`. Do **not** edit
any part of `docs.md`/`adrs.md` outside their `## Docex` sections. After the
edits, add a CHANGELOG entry (step 7) and run the gate (step 8).

Apply edits with exact string replacement.

---

## Edit 1 — `doctrine/infrastructure/docex.md`: command-reference table row

In the "Provided Tools" table, insert a `docs` row **between** the `config` row
and the `build` row.

Find:
```
| `config <op> <env> [...]` | Manage an environment's non-secret config file. |
| `build <codebase>` | Run `build.sh` for one or all codebases. |
```
Replace with:
```
| `config <op> <env> [...]` | Manage an environment's non-secret config file. |
| `docs <op>` | Scaffold, check, or regenerate the standard design-doc set under `plans/design`. `docs check` is also a blocking sub-gate of [`check`](#check). |
| `build <codebase>` | Run `build.sh` for one or all codebases. |
```

---

## Edit 2 — `doctrine/infrastructure/docex.md`: new `### docs` detail subsection

Insert a new subsection immediately **before** the `### \`build\`` heading.

Find:
```
### `build`
`./bin/docex build` to refresh `dist/` for all codebases in the `dev` environment.
```
Replace with:
```
### `docs`
`./bin/docex docs scaffold`
`./bin/docex docs check`
`./bin/docex docs adr`

Manages the standard design-doc set under `$pr/plans/design` (see [docs.md](../practices/docs.md)). `scaffold` and `check` share one canonical definition of the standard set, so they can never disagree on what "the standard set" is.

- **`scaffold`** idempotently lays down every missing standard design-doc entry — the L1 arc42 files, the standard diagrams, `adrs/` with its two generated index stubs, `references/`, and a per-`infra.yml`-codebase `module_diagram.mmd`, `module/`, and `specifics/`. It never clobbers an existing file (creates only what is missing) and never auto-creates optional entries; empty standard directories get a `.gitkeep`. It reports what it created.
- **`check`** validates an existing design corpus and exits non-zero on any problem. Three checks: **missing standard file** (a required standard entry is absent), **reachability** (a file under `plans/design` that no standard root can reach through the link graph — an orphaned, potentially load-bearing doc), and **ADR-index freshness** (`adr_index.md` / `adr_active.md` out of sync with `plans/design/adrs/`). It passes as a no-op when the project has no `plans/design` yet. The same three checks run as a **blocking sub-gate of [`check`](#check)** — see [cicd.md § Check Step](./cicd.md#check-step) and [docs.md § Docex](../practices/docs.md#docex).
- **`adr`** regenerates the two ADR index files (`adr_index.md`, `adr_active.md`) from the ADR sources in `plans/design/adrs/`. Deterministic and idempotent — a no-op run rewrites nothing. `docs check` gates their freshness. See [adrs.md § Docex](../practices/adrs.md#docex).

### `build`
`./bin/docex build` to refresh `dist/` for all codebases in the `dev` environment.
```

---

## Edit 3 — `doctrine/infrastructure/docex.md`: thread doc-validation into `### check`

Find (inside the `### check` subsection):
```
runs git/version checks, surface-to-contract alignment checks, build, and the full test suite against the merged state.
```
Replace with:
```
runs git/version checks, surface-to-contract alignment checks, design-doc validation (the [`docs check`](#docs) sub-gate), build, and the full test suite against the merged state.
```

---

## Edit 4 — `doctrine/infrastructure/cicd.md`: Check Step § Process

In the "#### Process" list under "### Check Step", insert a new blocking
"documentation checks" step and renumber the trailing steps.

Find:
```
4. Probe the `observability_backend_url` for reachability (see [telemetry_infra.md § Validation Rules](./specifics/telemetry_infra.md#validation-rules)).
5. Ensure build doesn't fail.
6. Run [build test](#build-test-step).
```
Replace with:
```
4. Perform documentation checks against `plans/design` (design-doc validation; the same checks as [`docex docs check`](./docex.md#docs)). All three are **blocking**, and all three are skipped when the project has no `plans/design` yet:
	1. Every non-optional standard design-doc file and directory is present.
	2. Every file under `plans/design` is reachable through the link graph from a standard root — no orphaned-but-load-bearing docs.
	3. The generated ADR index files (`adr_index.md`, `adr_active.md`) are in sync with `plans/design/adrs/`.
5. Probe the `observability_backend_url` for reachability (see [telemetry_infra.md § Validation Rules](./specifics/telemetry_infra.md#validation-rules)).
6. Ensure build doesn't fail.
7. Run [build test](#build-test-step).
```

---

## Edit 5 — `doctrine/practices/docs.md`: fill the `## Docex` section

This is the **last** section of the file. Replace the entire stub.

Find:
```
## Docex

TODO *document* how docex interacts with documentation:
+ reachability check stage
+ standard doc missing check stage
+ `infra.yml` matches `service` diagram
+ standard diagrams match each other
```
Replace with:
```
## Docex

`docex` provides the [`docex docs`](../infrastructure/docex.md#docs) command family to lay down and police this standard structure:

- **`docex docs scaffold`** idempotently creates every missing standard design-doc entry under `plans/design` — the L1 arc42 files, the standard diagrams, `adrs/` and its two generated index stubs, `references/`, and a `module_diagram.mmd`, `module/`, and `specifics/` per `infra.yml` codebase. It never overwrites an existing file and never creates the optional entries; empty standard directories get a `.gitkeep`. Inception runs it to seed a new project's design docs.
- **`docex docs check`** validates an existing corpus and blocks (non-zero exit) on any problem: a [missing standard file](#missing-standard-file), an [unreachable doc](#reachability-check), or a stale ADR index. It also runs as a blocking sub-gate of [`docex check`](../infrastructure/cicd.md#check-step); both skip when a project has no `plans/design` yet.
- **`docex docs adr`** regenerates the two ADR index files from the ADR sources — see [adrs.md § Docex](./adrs.md#docex).

### Reachability Check

The [loading flow](#llm-agent-usage) no longer reads *all* design docs, only the top-level ones; routing is strictly top-down. That makes the **orphaned-but-load-bearing doc** the critical failure to avoid: a file buried in `specifics` that no higher-level section or diagram links to is invisible but may still be load-bearing.

`docex docs check` guards against this mechanically. It enumerates every file under `plans/design`, builds the link graph rooted at the standard roots — the L1 arc42 files, `lexicon.md`, the [standard diagrams](#standard-diagrams) (`project_diagram.mmd`, `service_diagram.mmd`, and each codebase's `module_diagram.mmd`), and the two ADR indexes (`adr_index.md`, `adr_active.md`) — and flags any file a root cannot reach. Both markdown links and mermaid `click` targets count as edges. No per-doc frontmatter is required; reachability is computed from the link graph itself.

### Missing Standard File

`docex docs check` also verifies that every non-optional entry in the standard [documentation structure](#standard-documentation-structure) actually exists — each L1 arc42 file, the standard diagrams and ADR indexes, the `adrs/` and `references/` directories, and each codebase's `module_diagram.mmd`, `module/`, and `specifics/`. `docex docs scaffold` lays these down; this check keeps them from being deleted or forgotten. It is blocking under [`docex check`](../infrastructure/cicd.md#check-step).
```

---

## Edit 6 — `doctrine/practices/adrs.md`: fill the `## Docex` section

This is the **last** section of the file. Replace the entire stub.

Find:
```
## Docex

<TODO> Fill this in with the docex command to generate index files. </TODO>
```
Replace with:
```
## Docex

`docex docs adr` regenerates both index files from the ADR sources in `plans/design/adrs/`. It parses each ADR's frontmatter and rewrites `adr_index.md` (all ADRs) and `adr_active.md` (accepted and not superseded). The generation is deterministic (stable id sort) and idempotent — re-running when nothing has changed rewrites nothing — and each generated file's first line is a "do not edit by hand" marker. Because old ADRs are immutable and new ones are only ever added, the indexes are brought current simply by re-running the command after adding an ADR.

Index freshness is enforced, not merely offered: [`docex docs check`](../infrastructure/docex.md#docs) — and the `docex check` gate it feeds — blocks if either index is out of sync with the ADR sources, naming `docex docs adr` as the fix. See [docex.md § docs](../infrastructure/docex.md#docs).
```

---

## Step 7 — CHANGELOG entry

In `/home/ubuntu/.claude/jean_baudrillard/CHANGELOG.md`, under `## [Unreleased]`,
add a bullet to the existing `### Changed` list (documentation prose now matches
shipped tooling). Insert it as the final bullet of the `### Changed` group
(immediately before the `### Added` heading):
```
- **Doctrine prose filled in for the `docex docs` tooling (advance 010, mod 164).**
  Documented the `docex docs {scaffold, check, adr}` command family in `docex.md`
  (command reference + `### docs` detail; `docs check` noted as a blocking sub-gate
  of `docex check`) and `cicd.md` (design-doc validation added to the Check Step).
  Filled the `## Docex` stubs in `docs.md` (command overview + Reachability Check /
  Missing Standard File subsections) and `adrs.md` (`docex docs adr` + index-
  freshness gate). No `docex` behavior change.
```

---

## Step 8 — Gate

Run the linkcheck gate and confirm it exits 0 (GREEN):
```
cd /home/ubuntu/.claude/jean_baudrillard && python3 skills/cohere/executor/linkcheck.py
```
All new cross-links and citations must resolve. Report the result. Do **not**
commit — the driving agent handles commits.
