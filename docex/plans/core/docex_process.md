# Docex Process

How to develop updates for docex.

`docex` is a little unlike other software packages. It automates parts of the *development and release* processes themselves. This means that both development and testing of `docex` diverges from standard doctrine practices. Furthermore, the doctrine and `docex` intertwine substantially. Often a change to one provokes a change in the other.

The rough, toplevel process for change is this:
1. **Alter the doctrine** - If neccessary, change the actual doctrine wording itself. `docex` is *driven* by the doctrine (from a certain perspective the doctrine forms the product documentation for `docex`) so doctrine should always change first.
	1. Always ask the human operator before altering doctrine files! The language of the doctrine is carefully chosen and often every word is load bearing.
2. **Update `docex` to match** - Change the actual code and function of `docex` using regular mod cycles. Taken all together, the sum of mod cycles needed to complete all needed changes forms a "campaign". Cutting and releasing is expensive and disruptive, so we always want to bundle as many changes as possible into one campaign, even if they split across many mod cycles.
	1. Each cycle will include a design document, implementation steps, sub-agent execution, and the running of standard automated tests at the end as per usual.
	2. Always add good tests for new additions. Unit tests by default; add an integration test when behavior crosses a real boundary (docker / AWS / git).
	3. When checking for drift after a mod implementation, check all [artifacts](#additional-artifacts) for alignment.
3. **Run expensive tests** - When mod cycles are complete, run the "expensive" tests. These include:
	1. End-to-end integration tests. These are automated and hit with `pytest -m integration`
	2. The ["test project" tests](#test-project-tests), which call for the developer (you) to manually step through critical `docex` steps for two distinct sample projects with different foundations.
4. **Cut a new version** - See [below](#cutting-a-version). This process is also disctinct to `docex` and should be followed carefully.

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

### Additional Artifacts

Unfortunately, the unique nature of `docex` means that it has five successive layers of artifacts which **must** be kept aligned across updates. Drift between them is an extreme hazard.

| Artifact | Role |
| -------- | ---- |
| `doctrine/.../*.md` | The rule of record. The *why* and the canonical statement. |
| `docex/plans/core/*.md` | Architecture and design docs for `docex`. This is the *how*. |
| `tables/roles/*.yml` | Transfer tables — how a role/engine compiles per foundation. |
| `src/docex/**` | Compiler / orchestration code that executes the rule. |
| `tests/**` | Proof the executor matches the rule. |

Keep them aligned. Fixing the code while leaving the rule stale (or vice versa) is the failure mode this process guards against.

## Versioning & cutting an image

`docex` follows SemVer per [version_control.md](../../../doctrine/infrastructure/version_control.md). The image tag always equals the version — no floating tags (see [masterplan.md § Distribution](./masterplan.md#distribution)). The image is the unit of determinism, so a version is only meaningful once its image is built.

**Built images are not git-tracked** — they are build artifacts living in the local Docker store. The determinism promise ("a project pinned to a version gets identical output forever") therefore rests on being able to *rebuild* a version's image from source, which requires that version's source to be recoverable. **The git tag is what makes it recoverable** — without it, finding "the commit that was 0.4.0" is archaeology. So every cut is tagged, mirroring the discipline `docex merge` already enforces for consumer projects.

### Cutting a version

Whatever the mode, a *cut* is the same ordered procedure, run from a clean
tree:

1. Assign the version `<v>` (SemVer).
2. Move `[Unreleased]` → `[<v>]` (dated) in [`CHANGELOG.md`](../../CHANGELOG.md).
3. Bump the version in `pyproject.toml` **and** `src/docex/__init__.py`.
4. Commit.
5. **Tag the cut commit `docex-v<v>`.** The tag is namespaced (`docex-v…`, not a bare `v…`) because this repo also holds the doctrine — a bare version tag would collide if the doctrine is ever versioned.
6. Rebuild the image: `docker build -t docex:<v> .` from `docex/`.
7. Reinstall into consumers: `bash docex_install.sh <project>`.

### Git

Trunk-based: commit directly to `main`, consistent with the doctrine's
[branch conventions](../../../doctrine/infrastructure/version_control.md#branch-conventions)
and how the rest of this repo is maintained.

## Test Project Tests

Two doctrine-faithful smoke-test projects live at [`docex/test_projects/`](../../test_projects/): one per foundation. Before cutting a minor or major version, the operator walks both through their full release paths (`bootstrap → compile → containerize → release stage → stagetest → release prod → teardown`) against real infrastructure. The procedure — including the pre-walk doctrine-conformance audit — is in [`docex/test_projects/PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md). Patch cuts skip this; minor and major cuts require it green.

For more details on the structure of these projects, please see the [test project README](../../test_projects/README.md).