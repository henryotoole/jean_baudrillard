# Docex Process

How to develop updates for docex.

`docex` is a little unlike other software packages. It automates parts of the *development and release* processes themselves. This means that both development and testing of `docex` diverges from standard doctrine practices. Furthermore, the doctrine and `docex` intertwine substantially. Often a change to one provokes a change in the other.

The rough, toplevel process for change is this:
1. **Alter the doctrine** - If neccessary, change the actual doctrine wording itself. `docex` is *driven* by the doctrine (from a certain perspective the doctrine forms the product documentation for `docex`) so doctrine should always change first.
	1. Always ask the human operator before altering doctrine files! The language of the doctrine is carefully chosen and often every word is load bearing.
2. **Update `docex` to match** - Change the actual code and function of `docex` using regular mod cycles. Taken all together, the sum of mod cycles needed to complete all needed changes forms an "advance". Cutting and releasing is expensive and disruptive, so we always want to bundle as many changes as possible into one advance, even if they split across many mod cycles.
	1. Each cycle will include a design document, implementation steps, sub-agent execution, and the running of standard automated tests at the end as per usual.
	2. Always add good tests for new additions. Unit tests by default; add an integration test when behavior crosses a real boundary (docker / AWS / git).
	3. There is no "manual test" phase for `docex` mod cycles. Do not pause for operator manual tests.
	4. When checking for drift after a mod implementation, check all [artifacts](#additional-artifacts) for alignment.
3. **Run expensive tests** - When mod cycles are complete, run the "expensive" tests. These include:
	1. End-to-end integration tests. These are automated and hit with `pytest -m integration`
	2. The ["test project" tests](#test-project-tests), which call for you to manually step through critical `docex` steps for two distinct sample projects with different foundations.
4. **Cut a new version** - a `docex` change ships in a doctrine-wide release; see [`RELEASING.md`](../../../RELEASING.md) and § [Versioning & Releasing](#versioning--releasing) below.

## Docex Documentation

The docex project structure does not adhere to the doctrine-defined standard by design. This means the `src` directory is rather different from a regular doctrine-adherent project and that the project documentation also has slightly different structure.

Toplevel structure is the same:
```
plans
├── modifications
├── core
└── references
```

The interiors of `modifications` and `references` are also the same. `core`, however, is different. It is simply a flat folder containing markdown files (no deeper structure corresponding to modules) because `docex` is not hexagonally-architectured and has no per-module docs to host. It still serves the same purpose of holding "core planning documents":

- [`masterplan.md`](./masterplan.md) — the toplevel architecture / design proposal. Note the framing at the top of that file explaining why a `docex` masterplan reads differently from a standard one.
- [`docex_process.md`](./docex_process.md) — this file. The development process for `docex` itself.
- [`compiler.md`](./compiler.md) — the CICL compiler: service expansion, magic refs, validation, and the emit layer.
- [`release_flow.md`](./release_flow.md) — the release and rollback paths: preconditions, the ephemeral worktree, and the per-foundation apply.
- [`test_projects.md`](./test_projects.md) — the two nested smoke-test projects: why two foundations, their shape, git structure, and commit cadence.

### Additional Artifacts

Unfortunately, the unique nature of `docex` means that it has six successive layers of artifacts which **must** be kept aligned across updates. Drift between them is an extreme hazard.

| Artifact | Role |
| -------- | ---- |
| `doctrine/.../*.md` | The rule of record. The *why* and the canonical statement. |
| `docex/plans/core/*.md` | Architecture and design docs for `docex`. This is the *how*. |
| `tables/roles/*.yml` | Transfer tables — how a role/engine compiles per foundation. |
| `src/docex/**` | Compiler / orchestration code that executes the rule. |
| `tests/**` | Proof the executor matches the rule. |
| `doctrine_excerpts/*.md` + `index.yml` | The prose `docex why <resource>` serves. A *restatement* of the doctrine, so it drifts silently — nothing compiles or tests it. |

The sixth is the one most easily forgotten, precisely because nothing fails when it goes stale: it is the only artifact in the list with no automated consumer. When a doctrine change introduces, retires, or renames a **resource**, `index.yml` needs the corresponding entry added, removed, or moved in the same mod. Mod 110 drifted here; mod 111 added the missing `codebase` entry and wrote this row.

**What earns an entry.** `doctrine_excerpts/` indexes **infrastructural
resources** — the nouns a deployed stack is physically made of, tracking
`shape.md`'s `[resource]` notation. It does **not** index CICL *fields*, and it
does **not** index *roles*. Fields are specified by `cicl.md § Service Fields`;
roles are served by `docex role <name>`, which reads `tables/roles/*.yml` and is
therefore generated rather than restated — it cannot drift the way this artifact
can. Adding a hand-maintained third restatement of something two artifacts
already serve correctly buys nothing and creates a new silent-drift surface.

Applying that criterion at advance 005 (mod 118): **`uses` gets no entry** — it
is a relation between resources, not a resource, and its two predecessors
`depends_on` and `consumes` had no entries across their entire lifetimes, so
merging two non-entries yields a non-entry. **`clock` gets no entry** — it is a
role; `docex role clock` already serves it correctly, and no other role
(`web`, `worker`, `cache`, `relational_db`, `object_store`) has an entry either.
The retired `scheduler` role had none, so its deletion removed nothing. Both
decisions are recorded here rather than left implicit, because on this artifact
a silent "no" is indistinguishable from an oversight.

Keep them aligned. Fixing the code while leaving the rule stale (or vice versa) is the failure mode this process guards against.

## Versioning & Releasing

`docex` no longer carries its own independent version or cut procedure. As of
doctrine version `1.3.0` the version is **doctrine-wide** — doctrine prose,
skills, and `docex` advance together under one number — and a `docex` change
ships as part of a doctrine release. The full procedure (version semantics, the
four synced artifacts, the tag, the image build) lives in
[`RELEASING.md`](../../../RELEASING.md). Cuts now tag `v<v>`, **not** the old
`docex-v<v>` form: the namespacing that once anticipated "a bare version tag
would collide if the doctrine is ever versioned" is now realized by the unified
scheme, so the one version owns the bare tag. Historical `docex-v*` tags remain
only for archaeology.

Two `docex`-specific properties the release process relies on:

- **The image is the unit of determinism.** The image tag always equals the
  version — no floating tags (see [masterplan.md § Distribution](./masterplan.md#distribution)).
  A version is only meaningful once its image is built, and `RELEASING.md` builds
  `docex:<v>` on every cut — even a no-op `docex` rebuild on a doctrine-only
  release, to keep the *doctrine version ⟺ image* invariant.
- **Built images are not git-tracked** — they live in the local Docker store, so
  the determinism promise ("a project pinned to a version gets identical output
  forever") rests on rebuilding a version's image from source. The `v<v>` git
  tag is what makes that source recoverable — without it, finding "the commit
  that was 1.2.0" is archaeology.

### Git

Trunk-based: commit directly to `main`, consistent with the doctrine's
[branch conventions](../../../doctrine/infrastructure/version_control.md#branch-conventions)
and how the rest of this repo is maintained.

## Test Project Tests

Two doctrine-faithful smoke-test projects live at [`docex/test_projects/`](../../test_projects/): one per foundation. Before cutting a minor or major version, the operator walks both through their full release paths (`compile → containerize → release stage → stagetest → release prod → teardown`) against real infrastructure. The procedure — including the pre-walk doctrine-conformance audit — is in [`docex/test_projects/PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md). Patch cuts skip this; minor and major cuts require it green.

For the architecture and design of those projects (why two foundations, code identity, git structure, commit cadence, cut lifecycle), see [`test_projects.md`](./test_projects.md).