# Mod 016 — Transfer-table authoring documentation

## Problem

After Mods 012–015, the doctrine declares enough machinery to support project-local engines for any containerized backing service, with strict validation, source-attributed errors, and EFS-backed persistence. But the *authoring perspective* — what a project developer actually writes when they need a ClickHouse engine or an OTel collector — is scattered across:

- `transfer_tables.md § Where Transfer Tables Live` (one paragraph on `infra/transfer_tables/`)
- `transfer_tables.md § Anatomy of a Role Definition` (the schema, with bundled engine examples)
- `transfer_tables.md § Failure-mode contract` (Mod 012)
- `transfer_tables.md § Container-backing services on elastic` (Mod 013)
- `transfer_tables.md § Persistent storage on Fargate` (Mod 015)

A project developer asking "how do I add ClickHouse?" has to stitch those together themselves. Mod 016 consolidates the authoring perspective into one place, with worked examples that walk end-to-end.

Plus the small unfinished doctrine item from Campaign goal #2: documenting the deep-merge semantics for naming policies, so projects know they can define new policies and override existing ones via project-local tables.

## Design

One new section in `transfer_tables.md`, placed after "Persistent storage on Fargate" (Mod 015's section) and before "Foundation Invariants":

```
## Authoring Project-Local Transfer Tables

### File layout and discovery
### Deep-merge semantics (engines + naming policies)
### Adding a new engine to an existing role
### Adding a wholly new role
### Worked example — sidecar / nginx (stateless container backing)
### Worked example — analytics_db / clickhouse (stateful container backing)
```

Each subsection is short and concrete — no abstract framing, just "here's how, here's why, here's the YAML."

### Content sketch

**File layout and discovery.** What goes where. `infra/transfer_tables/*.yml` (flat) or `infra/transfer_tables/roles/*.yml` (nested) — both work. The loader (`load_transfer_tables`) reads recursively and deep-merges. Project tables override bundled values at every leaf.

**Deep-merge semantics.** Walk through what "deep merge" means for engines and naming policies specifically: dicts merge key-by-key (project values win on conflict); scalars and lists are replaced wholesale (no list-append semantics). Worked mini-example: project sets `defaults.elastic.instance_class: db.t3.large` on the bundled postgres engine — only that one leaf changes; everything else (foundation, naming, emits, the other defaults) stays as bundled. Same model for naming policies: a project can override an existing policy's `max_len` or define a new policy entirely. The `parse_policies` parser sees the merged table.

**Adding a new engine to an existing role.** When the project needs a different concrete implementation of an existing role — e.g., `engine: clickhouse` for `role: analytics_db` (a hypothetical existing role). The project-local table declares only the new engine under the role; the bundled role's other engines remain available.

**Adding a wholly new role.** When the project needs a kind of service the doctrine doesn't model — `role: telemetry_collector` for OTel-style sidecars. The project declares the role + engine(s). Engine declarations look identical regardless of whether the role is bundled or project-defined.

**Worked example 1 (stateless container backing).** Full project-local table file for an OTel collector sidecar. Walk through every field — foundation, emits, defaults, provides, naming. Show the `infra.yml` snippet that consumes it. Show the magic-ref consumer pattern in the application code.

**Worked example 2 (stateful container backing).** Same but for ClickHouse. Adds `persistent_storage`, `emits.elastic: [..., efs_file_system]`, and the optional `backups` field for project opt-in. Note the bidirectional validation invariant.

### Doctrine prose alignment

This mod adds prose only. No `cicl.md`, `shape2.md`, or `infrastructure.md` changes. No code changes either — Mods 012–015 provided the machinery; this mod documents how projects use it.

### What this mod does NOT do

- Does not add new engines to the bundled set. ClickHouse and OTel collector live in project-local tables; the doctrine intentionally doesn't bundle them (different projects want different versions, configurations).
- Does not refactor or restructure existing `transfer_tables.md` sections. Mods 012–015's additions stay where they are; this mod adds a new section.
- Does not duplicate content from earlier sections. Where the authoring section needs to reference the strict-failure contract or the EFS section, it links rather than re-explains.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md`: new "Authoring Project-Local Transfer Tables" section with 6 subsections. |
| `docex/plans/core/*.md` | No change. |
| `tables/*.yml` | No change. |
| `src/docex/**` | No change. |
| `tests/**` | No change. |

## Validation

Read-through review against the implementation as Mods 012–015 left it. Confirm:
- File-layout statement matches `_read_yaml_files` recursive globbing.
- Deep-merge mini-example matches `_deep_merge`'s behavior (dict union; list/scalar override).
- Worked example YAML files would actually compile cleanly (strict validation, all allowed keys, no typos).
- Magic-ref consumer pattern in the worked examples matches the parts-only doctrine and the actual `provides.host.elastic` template form.

## Decisions captured

1. **One consolidated section, not scattered additions.** A project author should be able to read one section and have everything they need. Cross-links to the earlier doctrine sections cover the spec details; this section is the practical guide.
2. **Two worked examples, one stateless and one stateful.** Together they exercise every authoring surface: foundation, emits, defaults, provides, naming, persistent_storage, fields with target routing.
3. **Worked examples are concrete and complete.** Not pseudo-YAML — actual files a project could copy and adapt. Long-form is acceptable here because the authoring scenario is concrete.
4. **Naming-policy deep-merge gets equal billing**. Campaign goal #2's specific request: projects need to know they can override or extend the policy set. The deep-merge subsection covers it.

## Open questions

None. This is a docs consolidation pass over machinery that already exists.

## Process note

Docs-only mod — no sub-agent execution needed; the design-context LLM writes the prose directly. Single commit covers the doctrine addition. No `implementation.md` companion file (the "implementation" IS the prose; the overview + a single commit are sufficient).
