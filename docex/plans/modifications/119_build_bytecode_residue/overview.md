# Mod 119 — `docex build` bytecode residue

`docex build` cannot clear `dist/` and dies with `PermissionError`. The fix moves
the clear inside the container that owns the files. The mod also closes the disk
leak that defect has been feeding, which turns out to need one more piece.

## Why this mod is numerically out of order

**119 runs between 116 and 117.** A future reader will find it committed there
and suspect a corrupt history; it is not. This mod was not in the advance plan.
Mod 114 logged it as drift ("one integration test fails"), and Mod 116 revised
its severity twice — the failing test is the visible edge of an *unbounded disk
leak* that both remaining smoke walks would run on top of. Sarge promoted it
ahead of Mod 117 on that basis; see `advance_plan.md § 2b`.

Rule of record: `doctrine/infrastructure/cicd.md § Build Step` (Process, dev
iteration). **No doctrine edit is proposed** — see [Q1](#q1).

## The defect, precisely

`src/docex/orchestrate/build.py:124-135` clears `dist/` from the **host**:

```py
for child in dist_dir.iterdir():
    if child.is_dir():
        shutil.rmtree(child)      # ← :131
```

Measured on a leaked tree on this machine:

```
drwxrwxr-x  ubuntu ubuntu   core/api/dist
-rw-r--r--  root   root     core/api/dist/app.py
drwxr-xr-x  root   root     core/api/dist/__pycache__
```

The decisive detail is that the blocker is a root-owned **directory**, not a
root-owned file. Unlinking depends on write permission of the *parent*, so the
host uid can delete `dist/app.py` (parent `dist/` is `ubuntu`-owned) but cannot
delete anything inside `dist/__pycache__/` (parent is `root`-owned, mode 755).
Confirmed by hand: `os.unlink` on the `.pyc` raises `PermissionError [Errno 13]`.
That is `shutil.rmtree`'s failure, exactly.

**Self-regenerating within one run.** `run_up` produces the residue that its own
`run_build` then cannot delete, so clearing by hand buys exactly one green run.

### The invariant that was violated

Three different writers put root-owned content into the host `dist/`:

| Writer | What it writes |
| --- | --- |
| `up.py::_ensure_initial_dev_build` | `docker run … cp -r /service/dist/. /host_dist/` → `dist/app.py`, root |
| `build.sh` under `compose run` | the artifact itself, root |
| the running dev core service | `dist/__pycache__/*.pyc` on import, root |

`dist/` is a **container-owned directory**. The host uid owns the directory node
(docex `mkdir`s it) and nothing inside it. The rule this mod adopts:

> `docex` may create, list, and stat `core/<codebase>/dist/`, but must never
> delete inside it from the host.

`build.py:129-133` is the **only** host-side mutation of that tree in the whole
codebase (`up.py` only `iterdir`s and `mkdir`s; build's step-4 emptiness check
only `iterdir`s). One site to fix.

## The fix

Fold the clear into the same one-off exec-service container that already runs
`build.sh`:

```py
_CLEAR_AND_BUILD = "set -e; cd /service; mkdir -p dist; find dist -mindepth 1 -delete; exec ./build.sh"
...
rc = docker.compose_run_one_off(compose_file, service_key, ["sh", "-c", _CLEAR_AND_BUILD], …)
```

The host-side branch at `:124-135` collapses to "ensure `dist/` exists"
(`mkdir(parents=True, exist_ok=True)`), which is legal — that is the directory
node the host owns.

**One container, not two.** A separate clear-run would be cleaner in the
abstract, but `docex build` *is* the hot iteration loop, and `build.py` already
carries a documented refusal to add latency to this path (the `--build`
comment at `:139-145`). Same reasoning, same answer.

**`find -mindepth 1 -delete`, not `rm -rf dist/*`.** The bind-mount point itself
cannot be removed, and `rm` globbing misses dotfiles without ugly triple-glob
incantations. It is also literally the idiom the doctrine's own sample
`build.sh` uses for the same reason.

**Defensive by construction.** The container is root, so it deletes pre-existing
residue as readily as its own. Every checkout that already has root-owned
residue — including both smoke projects on this machine — self-heals on the next
`docex build` with no operator `sudo`. That property is the reason to prefer
this over `PYTHONDONTWRITEBYTECODE=1`, which only suppresses *new* residue and
changes emitted output for every project.

*Caveat, recorded not hidden:* a dev-stage image with a non-root `USER` still
could not delete root residue. Neither could the host, so this is not a
regression, and doctrine dev stages are root today.

## Closing the leak needs one more piece

The product fix alone does **not** close the disk leak. Evidence, measured now:

- `/tmp/pytest-of-ubuntu` is **6.0 GB** — regrown since sarge cleared it.
- **~5.9 GB of that is OpenTofu AWS provider binaries**: 676 MB per copy of
  `.terraform/providers/…/aws/5.100.0`, with the two `ec2_traefik` HCL tests
  holding 2.0 GB each.
- Exactly **20** paths are root-owned, and they are tiny. They are not the
  volume — they are the **pin**. pytest keeps the last 3 `pytest-N` roots and
  `rm_rf`s older ones; that removal raises `PermissionError` on a root-owned
  `__pycache__`, so gigabytes of provider binaries are never reclaimed. Small
  residue, large hostage. This is also why it first surfaced as two unrelated
  `tofu validate` tests failing on `no space left on device`.
- Two of the four residue producers are **outside `dist/` entirely**:
  `stagetest_project/.pytest_cache` and `infra/stage/tests/__pycache__`, written
  by the stagetest container running pytest as root against a bind-mounted
  `infra/stage/`. No change to `build.py` can reach those.

So the mod adds a **test-harness reclamation fixture** in
`tests/integration/conftest.py`: autouse, function-scoped, depends on `tmp_path`
(which guarantees it finalizes *before* pytest's own `tmp_path` finalizer), and
at teardown runs

```
docker run --rm -v <tmp_path>:/work alpine:latest chown -R <uid>:<gid> /work
```

`chown`, not `rm` — the tree stays inspectable for debugging while becoming
reclaimable. Best-effort (`check=False`, skipped when docker is unreachable): a
reclamation failure must never redden an otherwise-green test.

This is test-only and emits nothing. It is additive to the preferred fix, not a
substitute for it — no tradeoff was taken quietly.

### Steady state after the fix

Reclamation working means pytest's 3-root retention actually bites: ~3 × 6 GB ≈
**18 GB** steady state, against 24 GB free with two disk-hungry smoke walks
next. Bounded, but not comfortable. So the mod also sets, in `docex/pyproject.toml`:

```toml
tmp_path_retention_policy = "failed"
```

Per-test dirs are deleted at teardown for passing tests and kept for failures —
precisely the ones worth keeping. Green runs then cost ~0 GB. It composes with
the chown fixture by ordering: chown first, then pytest's delete succeeds. See
[Q2](#q2).

**Logged forward, not done here:** the 6 GB per run is five independent copies
of one 676 MB provider. A shared `TF_PLUGIN_CACHE_DIR` would cut it ~5×. That is
a separate concern from this defect and belongs to sarge's queue, not this mod.

## Tests

### Integration — the real regression test

New `test_build_survives_root_owned_residue` in
`tests/integration/test_build_real.py`. It creates **genuine** root-owned
residue the same way the bug does — `docker run --rm -v <dist>:/d alpine sh -c
'mkdir -p /d/__pycache__ && touch /d/__pycache__/x.pyc'` — then asserts
`run_build` returns 0 and the residue is gone.

No privilege escape hatch is needed here: docker gives an unprivileged test a
root writer, which is the whole mechanism of the bug. **This test fails against
today's code** with the production `PermissionError`, not a proxy for it.

### Unit — and the honesty problem in it

`test_build_clears_dist_before_running_build_sh` asserts `not (dist /
"stale.txt").exists()`. Under the new design docex no longer deletes that file;
the container does. The lazy repair — make the fake docker client
unconditionally clear `dist/` — would keep the test green while pinning nothing,
which is the Mod 115 trap the brief names.

Instead the fake's clearing is **derived from the command it is handed**: it
parses the `sh -c` string, and clears only if that string actually contains the
clear. Drop the clear from `build.py` and the fake stops clearing, the stale file
survives, and the original assertion fails. The assertion is preserved and still
load-bearing.

Also:
- New unit test asserting the command handed to `compose_run_one_off` targets
  `/service/dist` and still invokes `./build.sh`.
- New unit test pinning the negative: docex does not touch host `dist/` — with a
  fake that clears nothing, a seeded stale file survives `run_build`.
- `test_build_returns_failure_exit_code_from_build_sh` keys its scripted exit
  code on the command tuple `("./build.sh",)` and must be repointed to the new
  form. Mechanical.

## Verification

| Claim | How |
| --- | --- |
| Headline | `pytest -m integration` → **20 passed / 0 failed** (19 existing green + 1 new). Note the count: the brief's target of 19 assumed no new integration test. |
| Unit | `pytest tests/unit` green; 986 → ~988 (+2 new, 2 edited). Any other delta explained. |
| Leak closed, not just test green | Run a build; confirm **zero** root-owned paths remain under `dist/` after the clear; run it a second time — the second run is what exercises the self-regeneration path that made this bug survive manual cleanup. |
| Disk | `du -sh /tmp/pytest-of-ubuntu` before and after a full integration run; both numbers reported. |

## Scope

- **No `test_projects/` tracked file is edited.** Building against them is fine;
  `dist/` is gitignored.
- `PRE_CUT_CHECKLIST.md` **D.6's `sudo find … -exec rm -rf` workaround should be
  deleted once this lands** — it is a product bug that has been living as an
  operator chore. That file belongs to **Mod 117**; logged forward here, not
  touched.
- Not touched: smoke projects, upgrade guide, `doctrine_excerpts/`, `doctrine/`.
- Files this mod touches: `src/docex/orchestrate/build.py`,
  `tests/unit/test_orchestrate_build.py`, `tests/integration/test_build_real.py`,
  `tests/integration/conftest.py`, `docex/pyproject.toml`, and these mod docs.
- Path-scoped commits only, on `005_process_type_solidification`. No manual test
  phase.

## A correction to the verification phrasing

The brief asks to "confirm no root-owned files remain under `dist/`". That
cannot be the assertion, and should not be: **after a build the artifact itself
is root-owned**, because `build.sh` runs as root in the exec container. That is
by design and is the same property the fix relies on.

The invariant is narrower:

> Root-owned residue present *before* the clear does not survive it, and
> `docex build` is **repeatably** green against a `dist/` full of root-owned
> artifacts.

Repeatability is the real claim. A manual `sudo rm -rf` also produced one green
build; what it never produced was a second one.

**Second correction, found during implementation.** The first draft of the
integration test asserted `not (dist / "__pycache__").exists()` after a build.
That is wrong too, and for the same reason one step further out: the fixture's
`build.sh` ends with `cp -r src/. dist/`, and `src/__pycache__` exists on any
machine where something has imported the fixture — it is gitignored, so its
existence is machine state. The directory therefore legitimately reappears
*after* the clear, carrying a fresh copy rather than surviving residue (proven
by md5: the surviving `.pyc` was byte-identical to `src/__pycache__`'s, while
the seeded `residue.pyc` was gone). The assertion is on the seeded residue.
Even "no root-owned directory survives" is unsafe as a literal assertion, since
a `__pycache__` copied in by the root exec container is legitimately root-owned
— exactly as `dist/app.py` is.

## Rulings (sarge, at design approval)

- **Q1 — `find`, no doctrine edit.** The reason is sharper than "low risk": the
  doctrine's one image requirement (`curl`) is backed by a `docex check` gate,
  and an unenforced image requirement is a claim in the rule of record that
  nothing verifies — the shape rejected in Mod 112. The dependency is stated in
  `compiler.md` beside the mechanism instead, with a WHY. **Logged forward:**
  whether `find` deserves doctrine status *plus* a `check` gate alongside
  `curl` — a coherent small change for a future advance, not something to
  half-do here. Explicitly rejected: a POSIX glob dance (`./.[!.]* ./..?*`) to
  dodge the dependency; it costs more in comprehension than the dependency
  costs in risk.
- **Q2 — include `tmp_path_retention_policy = "failed"`.** 3 × 6 GB against
  24 GB free with two walks pending is a countdown, not a margin. Recorded here
  as a deliberate debugging tradeoff so the next person to want a *passing*
  test's tmp tree knows where it went: `pytest --tmp-path-retention-policy=all`.
- **Q3 — `chown`, not `rm -rf`.** It composes with Q2: retention keeps failing
  runs, and `chown` is what makes those retained trees readable by the host
  user. `rm -rf` would delete the evidence in precisely the case retention
  exists to preserve.

## Design questions

### Q1

**The doctrine wording, and whether `find` is now an image requirement.**

`cicd.md § Build Step` (dev iteration) step 1 reads: "Remove all contents of
`$pr/core/${codebase_name}/dist` on the development machine." A one-off container
on the development machine, clearing the same bind-mounted path, satisfies that
sentence as written — "on the development machine" distinguishes the host tree
from the in-image `dist/`, and both readings name the same path. **My reading:
no doctrine edit is required, and I propose none.**

The adjacent question is `find`. The fix newly depends on `sh` and `find` in the
dev stage. `sh` was already required (`build.sh` is `#!/bin/sh` and is invoked as
`./build.sh`). `find` is present in coreutils and in busybox, i.e. every base a
dev stage could plausibly use — and `cicd.md` already assumes enough of a
userland to run a shell script. `infrastructure.md § Codebase Containers` does
set a precedent for stating image requirements (`curl`, for health-checked
codebases), so a sentence there is *available* if you want the dependency
written down rather than assumed.

**Recommendation: no doctrine edit.** Say the word if you want the `find`
requirement stated explicitly and I will bring it back as a doctrine change
rather than slipping it in.

### Q2

**`tmp_path_retention_policy = "failed"` — in or out?**

In favour: it is what turns "bounded at ~18 GB" into "~0 GB on a green run",
right before two disk-hungry walks, for one line and no emitted output.

Against: you lose the ability to poke at a *passing* integration test's tmp
project after the fact without re-running under
`--tmp-path-retention-policy=all`. Failing tests keep everything either way.

**Recommendation: include it.** It is one line and trivially reversible. But it
is a change to how *you* debug the suite rather than to what docex does, so I am
not making that call silently.

### Q3

**Should the reclamation fixture be `chown` or `rm -rf`?**

Designed as `chown` (reclaim ownership, leave the tree). `rm -rf` would reclaim
disk immediately and unconditionally, but destroys failed-run evidence — which,
combined with Q2, would leave a failing integration test with nothing to inspect.

**Recommendation: `chown`, as designed.** Raised only because it interacts with
Q2; if Q2 is rejected, `chown` alone leaves the ~18 GB steady state standing.
