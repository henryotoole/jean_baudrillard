# Mod 105 — Implementation steps

Repo: `/home/ubuntu/.claude/jean_baudrillard`. All `docex` paths below are
relative to `/home/ubuntu/.claude/jean_baudrillard/docex/` unless stated
otherwise. Design rationale is in [`overview.md`](./overview.md) — read it first;
it explains *why* each choice below is the choice.

**Goal.** `docex rollback <env> <target>` must refuse a target whose
`infra.yml` is CICL v1 **in the cheap pre-flight band, before the ephemeral
worktree is created**, with a message that tells a mid-outage operator that
nothing was touched and what to do instead. Today the same rollback fails later,
at `run_compile` inside the worktree.

## Ground rules

- Branch is `main` and that is **correct** for this repo (`docex_process.md §
  Git`). Do not create a branch.
- The tree is dirty with work that is **not yours**: ten staged
  `docex/plans/campaigns/` → `docex/plans/advances/` renames, modified
  `docex/tests/unit/test_pipeline_projinfra.py` and
  `doctrine/practices/modifications.md`, untracked `docex/uv.lock`,
  `doctrine/chain/`, `doctrine/charts/configurable.md`,
  `doctrine/practices/advance.md`. **Leave every one of them strictly alone**,
  the `doctrine/` items especially. Do not run `git add -A`, `git add .`, `git
  commit -a`, `git stash`, or `git checkout -- .`.
- Run tests with `python3 -m pytest`, **not** `uv run pytest`, from
  `/home/ubuntu/.claude/jean_baudrillard/docex`.
- Do not commit. The mod's commits are the C.O.'s to make.
- **Do not touch any file under `doctrine/`.** The rule of record for this
  behavior already exists (`cicl.md § CICL Version`); `cicd.md`'s precondition
  list belongs to Mod 106.

## Step 1 — `CURRENT_CICL_VERSION` constant

`src/docex/cicl/model.py`.

Add a module-level constant next to the other module-level regex constants
(after `_SERVICE_NAME_RE`, around line 25):

```python
# The one generation of the CICL format this docex compiles. Rule 21's
# validator and rollback's pre-flight precondition both compare against
# it — WHY: two literals for one fact would drift at the worst possible
# moment, the next CICL generation. See cicl.md § CICL Version.
CURRENT_CICL_VERSION = "2"
```

Then rewrite `CICLDocument._validate_cicl_version` (currently `:293-311`) to use
it. Keep the existing comment and both messages' wording intact; only the
comparisons and the interpolated version change:

```python
    @model_validator(mode="after")
    def _validate_cicl_version(self) -> "CICLDocument":
        # Rule 21. Rejected, not shimmed: a compatibility parser accepting
        # both forms would reintroduce the flat pre-`processes:` shape as a
        # permanent second code path, to serve a migration every project
        # performs exactly once. See cicl.md § CICL Version.
        if self.cicl_version == CURRENT_CICL_VERSION:
            return self
        if self.cicl_version == "1":
            raise ValueError(
                "cicl_version '1' is no longer supported. CICL v2 makes the "
                "`processes:` block mandatory on every core service and adds "
                "the `consumes` relation and four-segment core magic refs. "
                "Follow upgrades/upgrade_1.6.0.md to migrate this infra.yml, "
                "then set cicl_version: \"2\"."
            )
        raise ValueError(
            f"unknown cicl_version {self.cicl_version!r}; the current "
            f"generation of the CICL format is {CURRENT_CICL_VERSION!r}."
        )
```

Note the last message's rendering shifts from `"2"` (a literal in the f-string)
to `'2'` (from `!r`). `tests/unit/test_process_nesting.py:158` asserts only
`"unknown cicl_version" in msg`, so nothing breaks — but check for any other
assertion on that tail before you finish (`grep -rn 'generation of the CICL'
tests/`) and leave the tests' expectations correct either way.

## Step 2 — `GitClient.show`

`src/docex/git/client.py`. Add to the `GitClient` Protocol, in the reads
section (place it after `merge_base` so the reads stay grouped; exact position is
cosmetic):

```python
    def show(self, cwd: Path, ref: str, path: str) -> str | None:
        """Return the content of ``<ref>:<path>``, or None if unresolvable.

        None covers every failure mode indistinguishably (bad ref, path
        absent at that ref, not a blob) — callers that need to explain
        the failure to an operator should phrase it as "could not read",
        not guess which case it was.
        """
        ...
```

`src/docex/git/subprocess_client.py`. Implement it alongside the other
`_capture`-based reads (after `merge_base`, around `:71`):

```python
    def show(self, cwd: Path, ref: str, path: str) -> str | None:
        return self._capture(["show", f"{ref}:{path}"], cwd=cwd)
```

Do **not** `.strip()` the result — callers parse YAML, where leading whitespace
is significant.

## Step 3 — `check.py`'s `_git_show` delegates

`src/docex/pipeline/check.py:295-308`. Replace the body so the private
`_capture` access and its `noqa` disappear. Keep the function, its name, its
signature, and its `RuntimeError`-on-failure contract — callers
(`_gate_version_bumped`) catch `RuntimeError`.

```python
def _git_show(repo: Path, ref: str, path: str) -> str:
    """Return the content of ``<ref>:<path>``, raising on failure.

    Routes through ``SubprocessGitClient.show`` — the single
    read-a-blob mechanism — and converts its ``None`` into the
    exception shape this module's gates already catch.
    """
    from docex.git.subprocess_client import SubprocessGitClient

    content = SubprocessGitClient().show(repo, ref, path)
    if content is None:
        raise RuntimeError(f"git show {ref}:{path} failed")
    return content
```

This is a pure refactor: identical behavior, no call-site changes.

## Step 4 — the rollback precondition

`src/docex/pipeline/rollback.py`.

### 4a. Imports

Add `import yaml` to the stdlib/third-party import block, and
`from docex.cicl.model import CURRENT_CICL_VERSION` to the `docex` imports.

Check for an import cycle before settling on a module-level import: `rollback.py`
already defers `docex.cicl.compile` to call time with a `WHY` comment about a
`pipeline -> compile -> ...` cycle. `docex.cicl.model` is a leaf (pydantic
schema only) and importing it at module scope should be fine — but **verify** by
running `python3 -c "import docex.pipeline.rollback"` after the edit. If it does
cycle, import `CURRENT_CICL_VERSION` inside the helper and say so in a `WHY`
comment.

### 4b. The helper

Add a module-level helper below `run_rollback` (next to `_missing_images`, which
it parallels — both are precondition probes returning data rather than raising):

```python
def _target_cicl_version(
    project_root: Path,
    *,
    git: GitClient,
    tag_name: str,
) -> tuple[str | None, str | None]:
    """Read ``cicl_version`` from ``infra/infra.yml`` at ``tag_name``.

    Returns ``(version, read_error)`` — exactly one is non-None, except
    that an ``infra.yml`` which parses but declares no ``cicl_version``
    yields ``(None, None)``.

    WHY a single-key read rather than ``CICLDocument`` validation: a
    pre-v2 ``infra.yml`` fails full validation for several unrelated
    reasons at once (no ``processes:``, ``domain_default_service``,
    service-level ``resources:`` under ``extra="forbid"``), and which
    one pydantic reports first decides what the operator sees. "You are
    across the v1 boundary" is the only fact that matters here, and it
    is the one a single-key read cannot get wrong. It also has to work
    on a file that is not a valid CICL document at all.
    """
    raw = git.show(project_root, tag_name, "infra/infra.yml")
    if raw is None:
        return None, f"could not read infra/infra.yml at tag {tag_name!r}"
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, (
            f"infra/infra.yml at tag {tag_name!r} is not parseable YAML: {exc}"
        )
    if not isinstance(doc, dict):
        return None, (
            f"infra/infra.yml at tag {tag_name!r} does not parse to a mapping"
        )
    value = doc.get("cicl_version")
    return (None if value is None else str(value)), None
```

`str(value)` normalizes an unquoted `cicl_version: 2` (which YAML yields as
`int`) so it compares equal to `"2"` — the compiler's own model would reject that
document for the type, but rollback's job here is to classify the target, not to
re-validate it, and treating an unquoted `2` as "across the boundary" would be a
lie.

`Path` and `GitClient` both need to be importable in `rollback.py` — `GitClient`
is already imported; add `from pathlib import Path` if absent.

### 4c. The precondition itself

Insert into `run_rollback` **after** the `validate_one_minor_back` block
(currently ending `:118`) and **before** the `_missing_images` block (currently
starting with its `WHY` comment at `:120`). Both boundaries matter: the tag must
be known to exist before we read a blob out of it, and this must precede the
registry probe.

```python
    # WHY: rollback recompiles the target's infra.yml with the *current*
    # docex (cicd.md § Rollback step 3), so a target written in an older
    # CICL generation cannot be rolled back to at all. Check it here —
    # ahead of the registry probe and well ahead of the worktree — so an
    # operator mid-outage learns it before anything is touched, rather
    # than from a compile error inside a worktree. Ordered ahead of the
    # image probe by decisiveness, not just cost: a missing image can be
    # rebuilt from the tag, a boundary crossing cannot be resolved by
    # anything except fixing forward, so the image list would be noise.
    # See cicl.md § CICL Version.
    target_cicl, read_err = _target_cicl_version(
        project_root, git=git, tag_name=tag_name,
    )
    if read_err is not None:
        raise RollbackPreconditionFailed(
            f"rollback aborted — {read_err}.\n"
            "Nothing has been touched. Rollback recompiles the target "
            "version's infra.yml with the current docex, so it cannot "
            "proceed without reading it.\n"
            + _FIX_FORWARD
        )
    if target_cicl != CURRENT_CICL_VERSION:
        raise RollbackPreconditionFailed(
            _boundary_message(tag_name, target_cicl)
        )
```

### 4d. The messages

Two module-level helpers, kept out of the precondition body so the band stays
readable. Wording is load-bearing — the design record's phrase *"cannot roll back
across the CICL v1→v2 boundary — fix forward"* must appear, and the
nothing-was-touched statement must come **first** in the body.

```python
_FIX_FORWARD = (
    "Fix forward instead:\n"
    "  1. On main, fix the defect and bump project.yml past the broken "
    "version.\n"
    "  2. ./bin/docex check  ->  merge  ->  containerize  ->  release <env>"
)


def _boundary_message(tag_name: str, target_cicl: str | None) -> str:
    """Compose the abort text for a target docex cannot compile.

    Splits on *why* the target is uncompilable, because the two cases
    call for different operator expectations: the v1 boundary is a
    known one-release-cycle condition, an unrecognized generation is
    not.
    """
    if target_cicl is None or target_cicl == "1":
        declared = (
            'declares cicl_version "1"'
            if target_cicl == "1"
            else "declares no cicl_version, so it predates the field"
        )
        return (
            "rollback aborted - cannot roll back across the CICL v1->v2 "
            "boundary.\n"
            "Nothing has been touched.\n"
            f"\nTarget {tag_name}'s infra/infra.yml {declared}. This docex "
            f'compiles only cicl_version "{CURRENT_CICL_VERSION}", and '
            "rollback recompiles the target's infra.yml with the *current* "
            "docex (cicd.md section Rollback, step 3) - so no rollback to "
            "this target can succeed.\n\n"
            + _FIX_FORWARD
            + '\n\nOnce a second cicl_version "2" release exists, rollback '
            "works normally."
        )
    return (
        f"rollback aborted - target {tag_name}'s infra/infra.yml declares "
        f"cicl_version {target_cicl!r}, which this docex does not compile "
        f'(it compiles "{CURRENT_CICL_VERSION}").\n'
        "Nothing has been touched.\n\n" + _FIX_FORWARD
    )
```

Use ASCII `->` rather than the `→` of the design record — this text goes to a
terminal under emergency conditions and must not depend on the encoding. Match
whatever the surrounding module already does for arrows/em-dashes; if
`rollback.py`'s existing messages use plain ASCII (they do — see the
`_missing_images` text), stay ASCII.

### 4e. Module docstring

`rollback.py`'s docstring lists the shape as steps 1-5. Extend step 1's
parenthetical to name the new check, so the file's own summary stays true:

```
  1. Aggressively check preconditions before touching any env state
     (branch + clean tree + tag existence + one-minor-back + the
     target's CICL generation + every core service's image present in
     the registry).
```

## Step 5 — `FakeGitClient.show`

`tests/conftest.py`.

Widen the existing (currently unreferenced) `file_at_ref` field at `:324` to
carry an explicit "unreadable" sentinel, and document it:

```python
    # Mod 105: scripted content for ``show``. Maps ``(ref, path)`` to the
    # file's content, or to None to model "git show failed" (bad ref,
    # path absent at that ref). A key that is absent entirely falls back
    # to ``default_file_content``.
    file_at_ref: dict[tuple, str | None] = field(default_factory=dict)
    # WHY a permissive default: the fake already models "an established
    # repo" (see ``refs``), and the only production caller reads
    # ``cicl_version`` out of a tag during rollback pre-flight. Defaulting
    # to a compilable stub keeps every rollback test asserting its own
    # subject instead of acquiring boilerplate git-content setup.
    # Boundary tests override per key.
    default_file_content: str | None = 'cicl_version: "2"\n'
```

Add the method in the reads section (after `merge_base`, mirroring the protocol's
ordering):

```python
    def show(self, cwd, ref, path):
        self.calls.append(("show", str(cwd), ref, path))
        key = (ref, path)
        if key in self.file_at_ref:
            return self.file_at_ref[key]
        return self.default_file_content
```

`key in ...` rather than `.get(key, default)` is deliberate: it lets a test map a
key explicitly to `None` to mean "unreadable" without that being confused with
"unscripted".

## Step 6 — Tests

All in `tests/unit/test_pipeline_rollback.py`. Put them in the precondition
section, immediately **before** `test_rollback_lists_all_missing_images`, so the
file's reading order matches the band's execution order. Use the existing
`_invoke` helper and the `sample_ctx` / `fake_git` fixtures — the pattern of
`test_rollback_rejects_two_minors_back` is the closest model.

A shared local helper keeps the eight tests short:

```python
_TAG = "v0.0.5"
_INFRA = "infra/infra.yml"


def _preflight_git(fake_git, *, content):
    """fake_git configured to pass every precondition ahead of the CICL
    check, with ``content`` scripted as the target tag's infra.yml."""
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = [_TAG]
    fake_git.file_at_ref[(_TAG, _INFRA)] = content
    return fake_git
```

Note `sample_ctx`'s `project.yml` version must be newer than `0.0.5` for
`validate_one_minor_back` to pass — it already is, since the existing tests
target `0.0.5` successfully. Do not change the fixture.

1. **`test_rollback_rejects_cicl_v1_target`** — content
   `'cicl_version: "1"\nfoundation: fixed\n'`. Assert `RollbackPreconditionFailed`
   and that the message contains `"CICL v1->v2 boundary"`, `"Nothing has been "
   "touched"`, and `"Fix forward"`.

2. **`test_rollback_cicl_v1_aborts_before_worktree_created`** — the point of the
   mod. Same setup; assert `RollbackPreconditionFailed`, then:
   - `"worktree_add" not in [c[0] for c in fake_git.calls]`
   - the worktree path does not exist on disk. Build it the same way the
     production code does:
     `worktree_path_for(sample_ctx.project_root, "rollback-0.0.5")` (import from
     `docex.pipeline._worktree`), then `assert not path.exists()`.
   A non-zero return or a raised exception is **not** sufficient evidence — assert
   both of the above.

3. **`test_rollback_cicl_v1_aborts_before_registry_probe`** — pins the ordering
   decision so a later reshuffle of the band cannot silently undo it. Same setup;
   assert `RollbackPreconditionFailed`, then
   `"manifest_inspect" not in [c[0] for c in fake_docker.calls]` and that no
   `ecr_image_exists` call appears in `fake_aws.calls` (that fake records
   `(method, args, kwargs)` tuples, so check `c[0]`).

4. **`test_rollback_v2_target_proceeds_to_release`** — content
   `'cicl_version: "2"\n'` scripted explicitly rather than relying on the fake's
   default. Use the `worktree_populator` + `stub_compile` fixtures like
   `test_rollback_fixed_calls_ansible_with_skip_tags` does, set
   `fake_git.file_at_ref[(_TAG, _INFRA)] = 'cicl_version: "2"\n'`, and assert the
   rollback returned 0 and `fake_ansible` recorded its call — i.e. the check did
   not become a false gate.

5. **`test_rollback_aborts_when_target_infra_yml_unreadable`** — `content=None`.
   Assert `RollbackPreconditionFailed`, the message names both `v0.0.5` and
   `infra/infra.yml`, and contains `"Fix forward"`. Explicitly assert it is the
   `RollbackPreconditionFailed` type, not an `AttributeError`/`TypeError` — the
   requirement is a comprehensible message rather than a stack trace.

6. **`test_rollback_aborts_on_unparseable_target_infra_yml`** — content of
   deliberately broken YAML, e.g. `"cicl_version: \"2\"\n  bad: [unclosed\n"`.
   Verify locally that `yaml.safe_load` actually raises on whatever string you
   pick (if it doesn't, pick another) — the test must exercise the
   `yaml.YAMLError` branch. Assert `RollbackPreconditionFailed`, that the message
   names the tag and says "not parseable YAML", and that no `yaml.YAMLError`
   escapes.

   Add a sibling assertion for the non-mapping branch in the same test or a
   seventh sibling: content `"just a bare string\n"` → message contains
   `"does not parse to a mapping"`.

7. **`test_rollback_absent_cicl_version_gets_boundary_message`** — content
   `'foundation: fixed\napex_domain: example.com\n'` (parses, no `cicl_version`).
   Assert the boundary message, and specifically that it says the file
   `"predates the field"` rather than claiming it declares `"1"` — a document
   with no such key should not be misreported.

8. **`test_rollback_rejects_unrecognized_cicl_version`** — content
   `'cicl_version: "3"\n'`. Assert `RollbackPreconditionFailed`, that the message
   contains `"3"` and `"Fix forward"`, and that it does **not** contain
   `"v1->v2 boundary"` — the two cases must stay distinguishable, mirroring the
   rule-21 validator's own split.

Docstring each test with the one-line reason it exists (the existing tests in
this file do).

## Step 7 — Verify

From `/home/ubuntu/.claude/jean_baudrillard/docex`:

1. `python3 -c "import docex.pipeline.rollback"` — no import cycle.
2. `python3 -m pytest tests/unit -q` — expect **≥ 974 passed** (974 baseline +
   your new tests). Report the exact number.
3. `python3 -m pytest tests/ -q` — expect **≥ 1038 passed / 17 deselected**.
   Report both numbers.
4. `python3 -m pytest tests/integration -q --collect-only 2>&1 | tail -3` —
   integration must still collect **17**.
5. If a pre-existing test outside your touch list fails, **stop and report it**.
   Do not delete or weaken a test to reach green.

## Step 8 — Report

Return a summary containing:
- exact test counts for unit / full / integration-collect;
- every file you touched, absolute paths;
- the final text of both abort messages, verbatim, as an operator would see them
  (the C.O. reviews the wording, and it is the mod's actual deliverable);
- whether `CURRENT_CICL_VERSION` imported cleanly at module scope in
  `rollback.py` or had to be deferred, and why;
- anything you found that contradicts this document.

Do **not** commit. Do **not** touch `git add`/`stash`/`checkout`. Do **not** edit
anything under `doctrine/`.
