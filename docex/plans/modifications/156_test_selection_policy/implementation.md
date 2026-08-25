# Mod 156 — Implementation Steps

Pure-prose / process-doctrine mod. **No code, no tests, no pytest.** Six precise
prose edits across the doctrine, two agent defs, and the `testing` skill, all
stating one policy in one vocabulary (`unit` / `integration`; "iterate scoped /
close full"). Paths are relative to the jean root (`~/.claude/jean_baudrillard`).

After all edits, verify **link integrity** (§7). Then update `CHANGELOG.md` (§8).

---

## 1. `doctrine/practices/modifications.md`

In `## Process`, **replace** step **6.4**:

```
	4. Ensure relevant tests are all green.
```

with:

```
	4. **Close the test step on a full run.** You may iterate during the cycle with scoped runs (`docex test unit [subset]` / `docex test integration [subset]`) to keep the loop fast, but the cycle **closes** on the full `unit` tier (cheap, no stack) plus the **relevant `integration`** tests, all green. Choose the scope by your own judgment as the author of the diff — nothing computes an "affected" set from the changes.
```

(Preserve the leading tab indentation exactly, matching sibling sub-items.)

## 2. `doctrine/practices/advance.md`

**2a.** Insert a new subsection immediately **after** the
`### Heuristics for Tactical Planning` section (i.e. after its last list item,
before the `## Process` heading):

```
## Test Scope Across an Advance

Test scope is a sanctioned, policy-governed choice — not license to skip tests. Individual mods within the advance may iterate with scoped runs (`docex test unit [subset]` / `docex test integration [subset]`) and close each cycle on the full `unit` tier plus the **relevant `integration`** tests (see [modifications.md](./modifications.md)). The **advance itself closes on a full run of both tiers** — full `unit` and full `integration` across the project — before you write `report.md`. CI/CD gates (`check` / `merge`) always run full and never scope. Scope is agent judgment via the `docex test` subset mechanism; no computed "affected" selector exists.

```

**2b.** In `## Process`, step **4 (Report)** currently reads:

```
4. **Report**
	1. Write a report summarizing the advance to `report.md`.
	2. End turn and report to the operator that the advance has completed:
```

Insert a new sub-item as **4.1** (pushing the existing 4.1/4.2/4.3 down to
4.2/4.3/4.4), so the block becomes:

```
4. **Report**
	1. Before reporting, ensure the advance has **closed on a full run of both tiers** (see [Test Scope Across an Advance](#test-scope-across-an-advance)).
	2. Write a report summarizing the advance to `report.md`.
	3. End turn and report to the operator that the advance has completed:
```

...and renumber the remaining sub-items of step 4 accordingly (the current
`1. Write a report…` → 2, `2. End turn…` → 3, `3. If the operator does request…`
→ 4), keeping their nested content intact.

**2c.** In the example `advance_plan.md` block, the close-out step **6** reads:

```
6. **Test + release.** Bring up a fresh `test` env, run unit/integration, and (if
   in scope for this advance) run the CI/CD pipeline to stage/prod. Otherwise
   defer to the process step 4 offer to merge.
```

Replace with:

```
6. **Test + release.** Bring up a fresh `test` env and run the **full `unit` and
   `integration` tiers across the project**, and (if in scope for this advance)
   run the CI/CD pipeline to stage/prod. Otherwise defer to the process step 4
   offer to merge.
```

## 3. `agents/corporal/mod-developer.md`

**Append** to the end of the file:

```
# Test Discipline

Iterate with scoped runs (`docex test unit [subset]` / `docex test integration [subset]`) to keep the loop fast, but **close the mod's test step on a full run** — the full `unit` tier plus the **relevant `integration`** tests, all green. Scope is your judgment as the diff's author; there is no computed "affected" selector. This is the mod-cycle test rule from [modifications.md](../../doctrine/practices/modifications.md).
```

## 4. `agents/sergeant/doctrine-advance.md`

**Append** to the end of the file:

```
# Test Discipline

An advance **closes on a full run of both tiers** — full `unit` and full `integration` across the project — before you write `report.md`; never report an advance complete on a scoped run. Your scoped mods each close on full `unit` + relevant `integration` (the corporal enforces that); CI/CD gates (`check` / `merge`) always run full. This is the advance test rule from [advance.md](../../doctrine/practices/advance.md#test-scope-across-an-advance).
```

## 5. `skills/testing/SKILL.md`

**5a.** In the `description:` frontmatter, the sentence ending
`…including the \`DOCEX_TEST_SELECTOR\` subset contract.` becomes:

```
…including the `DOCEX_TEST_SELECTOR` subset contract, and the full-vs-scoped test-selection policy (a mod cycle iterates scoped and closes full; an advance closes full; CI/CD is always full).
```

(Keep the rest of the description — the trailing "Not for how to write…" sentence
— unchanged.)

**5b.** **Append** a new final bullet to the `## Thread` list:

```
- **Test-selection policy (scope is a sanctioned choice).** A mod cycle may
  iterate with scoped runs but **closes on the full `unit` tier plus the relevant
  `integration` tests**; an **advance closes on a full run of both tiers** across
  the project; **CI/CD (`check` / `merge`) is always full**. Scope is agent
  judgment via the subset mechanism above — and `docex test --slots N` sharding
  is what makes closing on full `integration` affordable. **No computed
  "affected" selector exists**, by design: cross-module driving-port imports,
  `shared/` blast radius, and domain changes with no test mirror make a computed
  set give false confidence. The process side lives in
  [`modifications.md`](../../doctrine/practices/modifications.md) (mod cycle) and
  [`advance.md`](../../doctrine/practices/advance.md) (advance).
```

## 6. `doctrine/infrastructure/cicd.md`

In the **`### Build Test Step`** section, the second paragraph ends
`…so that build testing can be triggered for a whole project the same way for every project.`
**Append** one sentence to that paragraph:

```
 The pipeline always runs the **full** suite: `check` and `merge` never scope to a subset — the scoped/subset runs (`DOCEX_TEST_SELECTOR`) are a development-loop convenience only, never a CI/CD gate (see [modifications.md](../practices/modifications.md)).
```

---

## 7. Verify link integrity

No pytest. Instead confirm every touched/new link resolves:

- `advance.md` → `./modifications.md` — sibling file exists.
- `advance.md` self-anchor `#test-scope-across-an-advance` (from Process 4.1) —
  matches the new `## Test Scope Across an Advance` heading.
- `doctrine-advance.md` → `../../doctrine/practices/advance.md#test-scope-across-an-advance`
  — file + new anchor exist.
- `mod-developer.md` → `../../doctrine/practices/modifications.md` — exists.
- `cicd.md` → `../practices/modifications.md` — exists.
- testing skill → `../../doctrine/practices/modifications.md` and `…/advance.md`
  — both exist; skill→doctrine direction is correct.
- Confirm **no doctrine file links out to a skill**.

Suggested mechanical check: `grep` each new relative link target and confirm the
file (and, for anchored links, a matching `#`-slugged heading) exists.

## 8. Update `CHANGELOG.md`

Add an entry under the current `Unreleased`/working section noting: the
test-selection policy is now encoded in the process strata — mod cycles iterate
with scoped runs and close on full `unit` + relevant `integration`; an advance
closes on a full run of both tiers; CI/CD (`check`/`merge`) always runs full;
scope is agent judgment with no computed "affected" selector. Files:
`modifications.md`, `advance.md`, `cicd.md`, the `mod-developer` /
`doctrine-advance` agent defs, and the `testing` skill.

## Out of scope / do NOT do

- No docex source changes; no `test_*.sh` changes; **no pytest**.
- No docex core-planning-doc (`masterplan.md`, etc.) changes.
- No computed selector, `--changed` flag, or dependency-graph logic — prose only.
