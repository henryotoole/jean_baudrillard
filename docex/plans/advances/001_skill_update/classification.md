# Doctrine Strata Classification — Snapshot

The settled output of the classification pass (planner § Major Skill Refactor, step 2).
Records *decisions*, not rationale — the strata model itself is defined canonically in
[`doctrine/doctrine.md` § Strata](../../../../doctrine/doctrine.md) and the lexicon. This
file is a planning snapshot for the advance, superseded once the skills are built.

## Status of the schematic

Settled this session:

- **Strata model** — Resident / Conditional / Executor, written into `overview.md` + lexicon.
- **Resident set** — locked (below).
- **Conditional skill map** — built: nine activity skills written to the `telemetry-design`
  template, all doctrine links validated.
- **Skill naming** — doctrine activities are unprefixed (plugin namespacing prevents
  collisions); `docex-` marks work on docex itself. Recorded in `skills.draft.md`.
- **Deployment** — local plugin; conditional skills run in place from
  `jean_baudrillard/skills/` (validated). Links authored `../../doctrine/…`.
- **Maintenance** — two meta-skills: `cohere` (static corpus soundness, deferred) and
  `skill-evaluation` (behavioral routing + performance, near-term).
- **Discovery** — via always-in-context skill metadata, not a maintained catalog.

## Resident stratum (always loaded; delivered via the `@`-include chain, never a skill)

| File | Note |
| --- | --- |
| `overview.md` | Strata model + doctrine purpose (meta-doctrine). |
| `lexicon.md` | Vocabulary; needed to parse any doctrine file. |
| `hexagonal_architecture/hex_overview.md` | Core architecture. |
| `hexagonal_architecture/internal_dependency_rules.md` | Import / composition-root rules. |
| `practices/comments.md` | Applies to every line. |
| `practices/logging.md` | Cross-cutting coding practice. |
| `practices/languages.md` | Gates language choice for all code. |
| `practices/databases.md` | Kept Resident deliberately — DB correctness is too central to gate. |
| `practices/docs.md` | Plan structure + masterplan spec; central to every mod cycle. |
| `practices/modifications.md` | The mod process; keeps code additions grounded. |
| `infrastructure/version_control.md` | Branching / semver / changelog orientation. |
| `infrastructure/infrastructure.md` | Infra orientation + vocabulary (the infra analog of the lexicon). Kept **whole**, but mechanism detail to be **stripped out** — see below. |

**Borderline rulings (all → Resident):** `databases`, `docs`, `modifications`,
`version_control`. Decided by convention ("keep the code-writer oriented and grounded"),
overriding the strict "needed to write any single line" test. All are short.

**`infrastructure.md` ruling:** stays Resident as an orientation doc, *not* split.
But it currently carries two pockets of mechanism that aren't orientation and should be
relocated to the conditional layer (tracked in planner § Refactors and Edits):
1. **Core Service Containers** — the Dockerfile-stage contract table + the
   Healthcheck `curl`-tooling requirement → belongs in `cicd-pipeline` targets.
2. **Deferred** — a reference footnote, not orientation.
The first thing `cohere`'s misplaced-detail audit would flag.

## Conditional stratum (skills, by activity)

`g` = general (read on skill load) · `s` = specific (read on demand). A file may be a
target of more than one skill — router+thread means skills *point at* shared files.

| Proposed skill | Target files | Existing skill |
| --- | --- | --- |
| **inception** | `practices/inception.md` (s) | — |
| **infra-compile** | `cicl.md` (g+s), `specifics/transfer_tables.md` (s), `specifics/networks.md` (s), `shape.md` (g, shared) | `docex-transfer-table` → fold into this skill |
| **network-design** | `specifics/networks.md` (s, shared), `reasoning/ingress_and_egress.md` (why), `charts/ing.md` (diagram) | — |
| **cicd-pipeline** (one skill — check/merge/containerize/release/stagetest/rollback/migrate) | `cicd.md` (g), `specifics/release.md` (s), `specifics/migrations.md` (s), `specifics/secrets.md` (s), `credentials.md` (g) | — |
| **telemetry-design** | `telemetry.md` (g), `specifics/telemetry_infra.md` (s) | — |
| **contracts** | `contracts.md` (g) — architecture-adjacent; candidate to fold into a service-design skill | — |
| **testing** | `tests.md` (g) — architecture-adjacent | — |
| **preinfra-setup** | `preinfra/preinfra.md` (g) + `container_registry.md`, `fixed_master_network.md`, `elastic_master_network.md` (g-head / s-body) + `telemetry_preinfra.md` (s) | `docex-preinfra` → retired; replaced by this skill |
| **projinfra-setup** | `specifics/projinfra/projinfra.md` (g) + 8 per-resource files (s) | — (new) |

Meta-skills (not activity skills): **`cohere`**, **`skill-evaluation`**, and the
existing **`docex-edit`** (unchanged — work on docex itself).

**CI/CD granularity:** decided coarse — one `cicd-pipeline` skill, no finer split.
`secrets-management` as a distinct activity (populating `<env>.env`) is a possible later
split but is folded in for now.

## Executor stratum + cross-cutting reference

- `docex` source + `bin/docex` shim — Executor; consumed by skills, never wrapped in one.
- `infrastructure/docex.md` — the executor's **command reference**; a shared target of the
  pipeline / projinfra / preinfra skills. No Resident summary needed — discovery is via
  skill metadata, not a maintained catalog.

## Cross-reference hubs (the spine threads route along / `cohere` link-checks)

- `cicl.md` and `specifics/transfer_tables.md` — most-referenced sinks; nearly every infra
  specific links back to them.
- `specifics/release.md` — densest outbound node (12+ links, preinfra → projinfra → envinfra).
- `specifics/projinfra/projinfra.md` and `preinfra/preinfra.md` — orientation entry points
  that already route to their per-resource files (router+thread, pre-existing in prose).

## Maintenance backbone — two meta-skills

Pruning/health rules live in skills, **not** as growth constraints in Resident prose
(bonsai — prune to shape; don't try to rule the growth). Split along *static text
soundness* vs. *behavioral does-it-work*:

### `cohere` — static corpus soundness (deferred)

Deterministic, no agent-in-the-loop. Bounded check set:
1. Resident-set discovery + misplaced-detail audit (orientation vs. mechanism).
2. Dangling-link / broken-pointer check across doctrine *and* skills.
3. Skill-pointer-resolution check.
4. Cross-file coherency / contradiction check.

Keystone: the **Resident set is discovered from the loading mechanism**, never a hand-kept
list — the `CLAUDE.md → JEAN.md → doctrine/SKILL.md` `@`-include chain *is* the registry.
Checks 2–3 keep `overview.md`'s "pointers checked mechanically" promise.

### `skill-evaluation` — behavioral routing + performance (near-term)

Built on the **vendored Anthropic skill-eval standard** (`skill-creator`). Two layers:
- **Trigger eval** — do descriptions fire when they should? Adopt the standard's mechanism
  (20 queries, should/shouldn't, near-misses, optimization loop), but run it at the
  **suite level** (all descriptions present at once) since our skills' triggers compete —
  guards against one description silently stealing another's. Central/shared query set.
- **Outcome eval** — does a skill's thread produce a correct result? Adopt the standard's
  format (prompt + assertions + grader subagent); per-skill cases. For router+thread skills
  the with/without baseline measures *navigation value*, and a failure can indict the
  underlying doctrine file (a feature — doubles as a doctrine-content check). Run gated,
  slimmed; defer the heavy aggregation/viewer until volume justifies.

Artifacts live in the top-level **`skill_eval/`** (sibling to `docex`, not under
`doctrine/`): vendored Anthropic scripts, the central trigger query set, per-skill outcome
cases. Seed the trigger set from this map — each activity → should-trigger; each
cross-activity pair → near-miss should-not-trigger.

**Cadence (both skills):** static + trigger on every doctrine/skill change; outcome before
a doctrine-affecting `docex` cut (beside the existing pre-cut checklist).

## Advance progress / remaining

1. **Resident loading mechanism** — trimmed `SKILL.md` drafted (`SKILL.draft.md`); deployment
   validated (local plugin, in place). Trim still staged — activate once the conditional set
   is final.
2. **Skill-system docs** — `skills.draft.md` complete: naming, the two-mechanism loading
   model, the body template, and maintenance. Eval-approach doc settled (lives in
   `skill_eval/`; no separate doctrine `eval.md`). ✔
3. **Activity skills** — all nine written to template (`telemetry-design` pilot + 8), links
   validated; the doctrine-activity prefix was dropped (plugin namespacing handles
   collisions). `docex-preinfra` retired (replaced by `preinfra-setup`). Remaining:
   fold/retire `docex-transfer-table` (→ `infra-compile`); optional re-author of `docex-edit`
   to the template.
4. **Skill evaluation system** — vendored `skill-creator` pinned in `skill_eval/`. Build:
   the suite-level trigger driver, then the slimmed outcome harness.
5. **Meta-skills** — `skill-evaluation` (write after its `skill_eval/` infra exists),
   `cohere` (deferred).
6. **`infrastructure.md` strip** — relocate the two mechanism pockets (planner § Refactors).
