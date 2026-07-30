# Mod 029 — Rollback command (implementation)

This is the executor-facing document. Read [`overview.md`](./overview.md) first for *why* and the design decisions; this doc is *what* to change.

## Pre-reads (must read before editing)

- [`overview.md`](./overview.md) — design + decisions locked in.
- [`doctrine/.../cicd.md § Rollback`](../../../../doctrine/infrastructure/cicd.md#rollback) — operator contract.
- [`doctrine/.../docex.md § rollback`](../../../../doctrine/infrastructure/docex.md#rollback) — command reference (one paragraph).
- [`src/docex/pipeline/release.py`](../../../src/docex/pipeline/release.py) — the function shape you'll add `skip_migrations` to. Especially `_release_fixed` and `_release_elastic`.
- [`src/docex/pipeline/check.py`](../../../src/docex/pipeline/check.py) — the worktree helpers you'll extract: `_worktree_path_for`, `_make_temp_branch`, `_cleanup_worktree`, `_parse_version`.
- [`src/docex/__main__.py`](../../../src/docex/__main__.py) — the dispatcher pattern.
- [`src/docex/ansible/subprocess_runner.py`](../../../src/docex/ansible/subprocess_runner.py) — `run_playbook`, which already has `tags=`; you'll add `skip_tags=` and `check_mode=`.
- [`tests/conftest.py`](../../../tests/conftest.py) — `FakeDockerClient`, `FakeGitClient`, `FakeAWSClient` recorder classes. Extend each for the new methods.

## Worktree-helper decision (locked)

**Extract `_worktree_path_for`, `_make_temp_branch`, `_cleanup_worktree` from `check.py` into a new shared module `src/docex/pipeline/_worktree.py`.** Mirror the `orchestrate/_common.py` convention: underscored module, public function names (no leading underscore on the functions themselves). Rationale: the three helpers are small, self-contained, and the rollback recipe differs (no rebase) so a parallel helper would just duplicate code. `check.py` keeps using them via import.

Same move for `_parse_version`: lift it into `_worktree.py` (or a tiny `_versions.py` — see step 1d). It's a SemVer-ish parser that rollback's one-minor-back check needs too.

## Step-by-step

### Step 1 — Extract shared helpers

**1a.** Create `src/docex/pipeline/_worktree.py` with three functions extracted verbatim from `check.py`:

```python
"""Worktree helpers shared by pipeline commands (check, rollback)."""
from __future__ import annotations
import shutil, time
from pathlib import Path
from docex.git.client import GitClient


def worktree_path_for(project_root: Path, slug: str) -> Path:
    """Return the conventional path for an ephemeral worktree.

    ``slug`` distinguishes the worktree's purpose, e.g. ``check-<sha>``
    or ``rollback-<version>``. Callers compose it.
    """
    return project_root / ".docex" / "worktrees" / slug


def make_temp_branch(prefix: str, ref_name: str) -> str:
    """Encode the calling command and ref name into a unique branch.

    ``prefix`` is the command name (``check`` / ``rollback``).
    ``ref_name`` is the human-meaningful anchor (feature branch name
    for check, target version for rollback). The timestamp suffix
    prevents collision when the same command runs concurrently against
    the same ref.
    """
    safe = ref_name.replace("/", "-").replace(":", "-")
    return f"docex-{prefix}/{safe}-{int(time.time())}"


def cleanup_worktree(
    project_root: Path,
    worktree: Path,
    temp_branch: str,
    git: GitClient,
) -> None:
    """Best-effort worktree teardown. Never raises.

    Forces removal (worktrees collect untracked build artifacts that
    git's default-mode remove refuses), falls back to shutil.rmtree if
    git still can't remove, prunes the worktree list, deletes the
    temp branch. Errors are swallowed so cleanup never masks the
    underlying command failure.
    """
    if not worktree.exists():
        return
    rc = git.worktree_remove(project_root, worktree, force=True)
    if rc != 0 and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
        git.worktree_prune(project_root)
    git.delete_branch(project_root, temp_branch, remote=False)
```

**1b.** Update `src/docex/pipeline/check.py`:
- Remove the local `_worktree_path_for`, `_make_temp_branch`, `_cleanup_worktree` definitions.
- Add `from docex.pipeline._worktree import worktree_path_for, make_temp_branch, cleanup_worktree` near the other imports.
- Replace the call sites:
  - `_worktree_path_for(project_root, short_sha)` → `worktree_path_for(project_root, f"check-{short_sha}")` (caller now composes the slug).
  - `_make_temp_branch(feature)` → `make_temp_branch("check", feature)`.
  - `_cleanup_worktree(project_root, worktree, temp_branch, git)` → `cleanup_worktree(project_root, worktree, temp_branch, git)`.

**1c.** Also extract `_parse_version` from `check.py` into `_worktree.py` (rename to `parse_version`, no leading underscore):

```python
def parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a tuple of ints for comparison.

    Non-numeric segments fall back to 0 — sufficient for ordering
    project.yml versions, not a full PEP 440 parser.
    """
    parts: list[int] = []
    for seg in v.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            digits = "".join(ch for ch in seg if ch.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)
```

Update `check.py` to import `parse_version` from `_worktree` instead of defining `_parse_version` locally.

**1d.** Add a new helper in `_worktree.py`:

```python
def validate_one_minor_back(current: str, target: str) -> str | None:
    """Return None if rolling back ``current`` to ``target`` is allowed
    by the one-minor-back doctrine rule; else return an error string.

    Per cicd.md § Rollback: target must satisfy
    ``target.major == current.major`` and
    ``target.minor >= current.minor - 1``, and ``target <= current``.
    """
    cur = parse_version(current)
    tgt = parse_version(target)
    # Pad to 3 components so .minor / .patch are addressable.
    cur = (cur + (0, 0, 0))[:3]
    tgt = (tgt + (0, 0, 0))[:3]

    if tgt >= cur:
        return (
            f"target version {target!r} is not older than current "
            f"version {current!r}; rollback requires a strictly prior version."
        )
    if tgt[0] != cur[0]:
        return (
            f"target version {target!r} crosses a major-version boundary "
            f"(current {current!r}); rollback supports at most one minor "
            f"version back."
        )
    if cur[1] - tgt[1] > 1:
        return (
            f"target version {target!r} is more than one minor version "
            f"behind current {current!r}; rollback supports at most one "
            f"minor version back."
        )
    return None
```

Unit-test cases (in step 7):
- Same minor, older patch: pass (e.g. 1.5.2 → 1.5.0).
- One minor back, any patch: pass (1.5.2 → 1.4.7).
- Two minors back: fail.
- Different major: fail.
- Equal version: fail.
- Newer target: fail.

### Step 2 — Image-existence probes

**2a. DockerClient.manifest_inspect (fixed path).**

In `src/docex/docker/client.py`, add to the `DockerClient` Protocol:

```python
def manifest_inspect(self, ref: str) -> bool:
    """Probe whether ``ref`` (a full ``<registry>/<repo>:<tag>``) is
    resolvable in the registry via ``docker manifest inspect``.

    Returns True iff the manifest is reachable (image exists in the
    registry). Returns False on any non-zero exit, including network
    errors — the caller treats that as "not present" and surfaces it
    via the precondition check.
    """
    ...
```

In `src/docex/docker/subprocess_client.py`, append to `SubprocessDockerClient`:

```python
def manifest_inspect(self, ref: str) -> bool:
    cmd = [self._docker, "manifest", "inspect", ref]
    try:
        res = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return False
    return res.returncode == 0
```

**2b. AWSClient.ecr_image_exists (elastic path).**

In `src/docex/aws/client.py`, add to the `AWSClient` Protocol (right after `ecr_authorization_token`):

```python
def ecr_image_exists(self, repository: str, tag: str) -> bool:
    """Return True iff the ECR repository ``repository`` contains an
    image with the given ``tag``.

    Used by ``rollback`` to confirm every core service has an image
    at the target version before any infra is touched. Maps to ECR
    ``describe_images`` with ``imageTag=<tag>``; ``ImageNotFoundException``
    returns False, other exceptions propagate.
    """
    ...
```

In `src/docex/aws/boto3_client.py`, append to `Boto3AWSClient`:

```python
def ecr_image_exists(self, repository: str, tag: str) -> bool:
    ecr = self._client("ecr")
    try:
        ecr.describe_images(
            repositoryName=repository,
            imageIds=[{"imageTag": tag}],
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ImageNotFoundException", "RepositoryNotFoundException"):
            return False
        raise
    return True
```

Note: `RepositoryNotFoundException` is also treated as "image absent" — if the repository itself is missing, the image obviously is too, and we want the caller to see a clean "image missing" diagnostic rather than a raised exception.

### Step 3 — Extend `run_playbook` for skip-tags and check mode

In `src/docex/ansible/subprocess_runner.py`, add two kwargs:

```python
def run_playbook(
    playbook: Path,
    inventory: Path,
    *,
    extra_vars: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    skip_tags: list[str] | None = None,    # NEW
    check_mode: bool = False,              # NEW
    config: Path | None = None,
    private_key: Path | None = None,
) -> int:
```

And in the command construction (after the existing `--tags` branch):

```python
    if skip_tags:
        cmd.extend(["--skip-tags", ",".join(skip_tags)])
    if check_mode:
        cmd.append("--check")
```

### Step 4 — `skip_migrations` (and `dry_run`) on the release functions

In `src/docex/pipeline/release.py`:

**4a.** Extend the `RunPlaybook` type alias is already `Callable[..., int]` so no change there. But `run_release` itself doesn't grow new params — the rollback path will call `_release_fixed` / `_release_elastic` directly with the new flags. Keep `run_release`'s public surface unchanged.

**4b.** Extend `_release_fixed`:

```python
def _release_fixed(
    ctx: ProjectContext,
    *,
    env: str,
    ansible_runner: RunPlaybook,
    skip_migrations: bool = False,
    dry_run: bool = False,
) -> int:
    # ... existing preflight unchanged ...

    rc = ansible_runner(
        playbook, inventory,
        config=config if config.is_file() else None,
        private_key=private_key,
        skip_tags=["migrate"] if skip_migrations else None,
        check_mode=dry_run,
    )
    # ... existing exit-handling unchanged ...
```

`release`'s existing call path passes neither flag → behavior unchanged.

**4c.** Extend `_release_elastic`:

```python
def _release_elastic(
    ctx: ProjectContext,
    *,
    env: str,
    aws: AWSClient,
    tofu_init: TofuInit,
    tofu_apply: TofuApply,
    tofu_plan: TofuPlan | None = None,
    skip_migrations: bool = False,
    dry_run: bool = False,
) -> int:
    # ... existing preflight unchanged ...

    if dry_run:
        # Dry-run is side-effect free: do NOT push SSM, do NOT apply.
        # Just init the workdir so plan has providers, then plan.
        if tofu_plan is None:
            print("error: elastic dry-run requires a tofu_plan runner. (Internal dispatch bug.)",
                  file=sys.stderr)
            return 1
        rc_init = tofu_init(out_dir)
        if rc_init != 0:
            raise TofuApplyFailed(f"'tofu init' for env {env!r} exited {rc_init}")
        rc_plan = tofu_plan(out_dir)
        if rc_plan != 0:
            raise TofuApplyFailed(f"'tofu plan' for env {env!r} exited {rc_plan}")
        print(f"rollback dry-run: see 'tofu plan' output above for env {env!r}.")
        return 0

    # 1. Push secrets to SSM. (Unchanged.)
    pushed = _push_secrets(aws, env_file, project=project_name, env=env)
    print(f"release: pushed {pushed} secret(s) to SSM under /{project_name}/{env}/")

    if skip_migrations:
        # Rollback path: no migration task-def bump, no RunTask. Just apply.
        _do_apply()
        print(f"release: {env} deployed successfully via OpenTofu (migrations skipped).")
        return 0

    # ... existing first_release / steady-state branches unchanged ...
```

Add a new type alias near the others:

```python
TofuPlan = Callable[..., int]
```

**4d.** Add `from typing import ...` imports as needed.

### Step 5 — Implement `run_rollback`

Create `src/docex/pipeline/rollback.py`:

```python
"""``docex rollback <env> <target_version>`` — emergency reversion.

Per cicd.md § Rollback: narrow-window, code-only, at most one minor
version back. Reuses release machinery with migrations skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from docex.aws.client import AWSClient
from docex.context import ProjectContext, load_project_context
from docex.docker.client import DockerClient
from docex.errors import (
    EnvNotSupported,
    RollbackPreconditionFailed,
    WorkingTreeDirty,
)
from docex.git.client import GitClient
from docex.pipeline._worktree import (
    cleanup_worktree,
    make_temp_branch,
    validate_one_minor_back,
    worktree_path_for,
)
from docex.pipeline.release import _release_elastic, _release_fixed


RunPlaybook = Callable[..., int]
TofuInit = Callable[..., int]
TofuApply = Callable[..., int]
TofuPlan = Callable[..., int]


def run_rollback(
    ctx: ProjectContext,
    *,
    env: str,
    target_version: str,
    docker: DockerClient,
    git: GitClient,
    aws: AWSClient,
    ansible_runner: RunPlaybook,
    tofu_init: TofuInit,
    tofu_apply: TofuApply,
    tofu_plan: TofuPlan,
    dry_run: bool = False,
) -> int:
    """Roll ``env`` back to ``target_version``. Returns exit code."""
    # ---- Preconditions (fail-fast on env, then fail-aggregated on
    #      cross-service image probe; see overview.md) ---------------
    if env not in ("stage", "prod"):
        raise EnvNotSupported(
            f"rollback target {env!r} is not supported; only 'stage' and 'prod'."
        )

    project_root = ctx.project_root
    infra = ctx.infra
    if infra is None:
        print("error: rollback requires infra/infra.yml (none found).", file=sys.stderr)
        return 1

    # On main, clean tree.
    if git.current_branch(project_root) != "main":
        raise RollbackPreconditionFailed(
            "rollback must run from 'main'. Check out main and try again."
        )
    if not git.is_clean(project_root):
        raise WorkingTreeDirty(
            "rollback refuses to run with a dirty working tree. Commit or stash first."
        )

    # Tag exists.
    tag_name = f"v{target_version}"
    if not git.tag_exists(project_root, tag_name):
        raise RollbackPreconditionFailed(
            f"no tag {tag_name!r} exists in this repo. Use './bin/docex' to "
            f"list recent versions, or supply a valid target."
        )

    # One-minor-back validation.
    current = ctx.project.version
    err = validate_one_minor_back(current, target_version)
    if err is not None:
        raise RollbackPreconditionFailed(err)

    # Image probe (fail-aggregated): every core service at target_version
    # must be in the registry.
    missing = _missing_images(ctx, docker=docker, aws=aws, target_version=target_version)
    if missing:
        raise RollbackPreconditionFailed(
            "rollback aborted — image(s) missing in registry:\n  - "
            + "\n  - ".join(missing)
            + "\nThis target version was not fully containerized, or the "
            "registry no longer retains it."
        )

    # ---- Worktree + recompile ----------------------------------------
    worktree = worktree_path_for(project_root, f"rollback-{target_version}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    temp_branch = make_temp_branch("rollback", target_version)

    rc = git.worktree_add(project_root, worktree, branch=temp_branch, ref=tag_name)
    if rc != 0:
        print(f"error: 'git worktree add' for {tag_name!r} exited {rc}.", file=sys.stderr)
        return rc

    try:
        worktree_ctx = load_project_context(worktree)

        from docex.cicl.compile import run_compile
        rc = run_compile(worktree_ctx)
        if rc != 0:
            print(f"error: recompile of {tag_name!r} exited {rc}.", file=sys.stderr)
            return rc

        # ---- Apply via release machinery, migrations skipped ----------
        if infra.foundation == "elastic":
            return _release_elastic(
                worktree_ctx, env=env, aws=aws,
                tofu_init=tofu_init, tofu_apply=tofu_apply, tofu_plan=tofu_plan,
                skip_migrations=True, dry_run=dry_run,
            )
        return _release_fixed(
            worktree_ctx, env=env, ansible_runner=ansible_runner,
            skip_migrations=True, dry_run=dry_run,
        )
    finally:
        cleanup_worktree(project_root, worktree, temp_branch, git)


def _missing_images(
    ctx: ProjectContext,
    *,
    docker: DockerClient,
    aws: AWSClient,
    target_version: str,
) -> list[str]:
    """Probe every core service's image at ``target_version``. Returns
    the list of missing ``<registry>/<project>/<svc>:<version>`` refs,
    or an empty list if all are present.
    """
    from docex.orchestrate._common import core_services
    infra = ctx.infra
    assert infra is not None  # caller checks
    project = ctx.project.name

    # Resolve registry the same way containerize does. For elastic
    # ECR-default (no explicit container_registry), the registry host
    # is derived from the AWS account ID.
    registry = infra.container_registry
    if not registry:
        if infra.foundation == "elastic":
            account = aws.caller_identity()
            registry = f"{account}.dkr.ecr.us-east-1.amazonaws.com"
        else:
            return [f"<no container_registry configured>"]

    missing: list[str] = []
    for svc in core_services(ctx):
        ref = f"{registry.rstrip('/')}/{project}/{svc}:{target_version}"
        if infra.foundation == "elastic":
            # ECR uses repository=<project>/<svc> by convention; probe via boto3.
            present = aws.ecr_image_exists(f"{project}/{svc}", target_version)
        else:
            # Fixed: probe via docker manifest inspect.
            present = docker.manifest_inspect(ref)
        if not present:
            missing.append(ref)
    return missing
```

Notes:
- `RollbackPreconditionFailed` is a new error class (step 5b).
- The lazy `from docex.cicl.compile import run_compile` mirrors release.py's lazy-import pattern.

**5b.** Add the new error class to `src/docex/errors.py`. Look at how other errors are defined (e.g. `WorkingTreeDirty`, `TagMissing`, `AnsibleRunFailed`) and add:

```python
class RollbackPreconditionFailed(DocexError):
    """A precondition for ``docex rollback`` failed; no env state was touched."""
```

(Place it near `WorkingTreeDirty` for clustering.)

### Step 6 — Dispatcher wiring

In `src/docex/__main__.py`:

**6a.** Add a Phase 5 group near the top:

```python
_PHASE5_COMMANDS = ("rollback",)
```

Update `_phase_of` to return 5 when `cmd in _PHASE5_COMMANDS`.

Update `_HELP_TEXT`:

```python
    "rollback": "Roll a deployed env back to a prior version (narrow-window emergency).",
```

In `_format_usage`, add the Phase 5 group after Phase 4:

```python
    _group("Phase 5 (implemented)", _PHASE5_COMMANDS)
```

**6b.** Add the handler:

```python
def _cmd_rollback(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex rollback", add_help=True)
    parser.add_argument("env", choices=["stage", "prod"],
                        help="environment to roll back (stage or prod)")
    parser.add_argument("target_version",
                        help="version to roll back to (without the 'v' prefix)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without applying")
    ns = parser.parse_args(args)

    from docex.ansible import run_playbook
    from docex.context import load_project_context
    from docex.opentofu import tofu_apply, tofu_init, tofu_plan
    from docex.pipeline.rollback import run_rollback

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    git = _require_git()
    aws = _make_aws_client()
    return run_rollback(
        ctx,
        env=ns.env,
        target_version=ns.target_version,
        docker=docker,
        git=git,
        aws=aws,
        ansible_runner=run_playbook,
        tofu_init=tofu_init,
        tofu_apply=tofu_apply,
        tofu_plan=tofu_plan,
        dry_run=ns.dry_run,
    )
```

**6c.** Register in `_build_handler_table`:

```python
        # Phase 5
        "rollback": _cmd_rollback,
```

**6d.** Verify `tofu_plan` is importable from `docex.opentofu`. It exists in `subprocess_runner.py` but check `docex/opentofu/__init__.py` re-exports it; if not, add it. (Existing exports: `tofu_init`, `tofu_apply`. Add `tofu_plan`.)

### Step 7 — Tests

**7a.** Extend `tests/conftest.py`:

- `FakeDockerClient`: add a `manifest_inspect` method and a `manifest_inspect_results: dict[str, bool]` recorder. Default behavior: if a ref is in the dict, return its value; else return True (image present). The bool default lets tests opt into "missing" by populating the dict.

- `FakeAWSClient`: add an `ecr_image_exists` method and a `ecr_image_exists_results: dict[tuple[str, str], bool]` recorder. Default True; tests override.

- `fake_tofu_plan` fixture mirroring the existing `fake_tofu_apply` / `fake_tofu_init` fakes — a recording callable.

- `fake_ansible`: extend the recorder so calls now also capture `skip_tags` and `check_mode`. Backward-compatible: keys default to None.

**7b.** Create `tests/unit/test_pipeline_rollback.py` with at minimum these cases:

| Test | Asserts |
| ---- | ------- |
| `test_rollback_rejects_non_main_branch` | `RollbackPreconditionFailed` raised; no calls to any runner. |
| `test_rollback_rejects_dirty_tree` | `WorkingTreeDirty` raised. |
| `test_rollback_rejects_unknown_env` | `EnvNotSupported` raised for `dev`/`test`/garbage. |
| `test_rollback_rejects_missing_tag` | Tag absent → `RollbackPreconditionFailed`; no worktree created. |
| `test_rollback_rejects_two_minors_back` | current=1.5.2, target=1.3.0 → `RollbackPreconditionFailed`. |
| `test_rollback_rejects_major_crossing` | current=2.0.0, target=1.9.9 → `RollbackPreconditionFailed`. |
| `test_rollback_rejects_target_equal_or_newer` | current=1.5.2, target=1.5.2 (and target=1.6.0) → `RollbackPreconditionFailed`. |
| `test_rollback_accepts_same_minor_older_patch` | current=1.5.2, target=1.5.0 → preconditions pass. |
| `test_rollback_accepts_one_minor_back` | current=1.5.2, target=1.4.7 → preconditions pass. |
| `test_rollback_lists_all_missing_images` | Two services, both missing → error string mentions both refs. (Not just first.) |
| `test_rollback_fixed_calls_ansible_with_skip_tags` | Fixed foundation → fake_ansible called with `skip_tags=["migrate"]`. |
| `test_rollback_elastic_skips_runtask_and_pre_apply` | Elastic foundation → `fake_aws.ecs_run_task` never called; `fake_tofu_apply` called once with no targets (no pre-migrate targeted apply). |
| `test_rollback_elastic_still_pushes_ssm` | Elastic → `fake_aws.ssm_put_parameter` called for each .env entry. |
| `test_rollback_dry_run_fixed_uses_check_mode` | Fixed + `--dry-run` → `fake_ansible` called with `check_mode=True`, no SSM/etc. |
| `test_rollback_dry_run_elastic_uses_plan_skips_ssm` | Elastic + `--dry-run` → `fake_tofu_plan` called; `fake_aws.ssm_put_parameter` NOT called; `fake_tofu_apply` NOT called. |
| `test_rollback_worktree_cleaned_up_on_success` | After success, `git.worktree_remove` was called. |
| `test_rollback_worktree_cleaned_up_on_failure` | If recompile fails, `git.worktree_remove` still called (try/finally). |

**7c.** Extend `tests/unit/test_pipeline_release.py` with one new test ensuring the existing release path is untouched:

| Test | Asserts |
| ---- | ------- |
| `test_release_default_does_not_skip_migrations` | Existing fixture, default invocation → `fake_ansible.calls[0].get("skip_tags") in (None, [])`; elastic equivalent: ECS RunTask still happens. |

**7d.** Add a unit test for the version helper at `tests/unit/test_worktree_versions.py` (or extend `test_pipeline_check.py`):

```python
def test_validate_one_minor_back_accepts_same_minor_older_patch():
    assert validate_one_minor_back("1.5.2", "1.5.0") is None

def test_validate_one_minor_back_accepts_one_minor_behind():
    assert validate_one_minor_back("1.5.2", "1.4.7") is None

def test_validate_one_minor_back_rejects_two_minors_behind():
    assert validate_one_minor_back("1.5.2", "1.3.0") is not None

# ... etc per the table above ...
```

**7e.** Add a small unit test for the new probe methods on the *subprocess* clients (in `tests/unit/test_subprocess_docker_client.py` and a new `tests/unit/test_aws_ecr_image_exists.py` — match existing test-file layout):

- Docker: monkeypatch `subprocess.run` to return rc=0 / rc=1; assert True/False.
- AWS: stub the `_client("ecr")` to return an object with `describe_images` raising `ClientError(ImageNotFoundException)` / `RepositoryNotFoundException` / success; assert True/False/raises for other codes.

**7f.** No integration tests required for this mod — the smoke walk (Step 8) is the real integration coverage. Unit tests are sufficient for merge.

### Step 8 — PRE_CUT_CHECKLIST.md update

Read `docex/test_projects/PRE_CUT_CHECKLIST.md`. Find the smoke-walk section for each foundation. After the existing "release prod" + "verify" steps, before "teardown", insert a "Rollback walk" step per overview.md § PRE_CUT_CHECKLIST walk pattern:

```markdown
N. **Rollback walk.** Demonstrates rollback against real infrastructure.
   1. Bump the test project's `project.yml` version (e.g. 0.0.X → 0.0.X+1).
      Inner-repo commit per `test_projects.md § Commit cadence`; force-move
      the `v<version>` tag at the new HEAD.
   2. `./bin/docex containerize` (pushes the v0.0.X+1 image to the registry alongside v0.0.X).
   3. `./bin/docex release prod` (deploys v0.0.X+1; verify `/health` reports v0.0.X+1).
   4. `./bin/docex rollback prod 0.0.X` (rolls back to the prior version).
   5. Verify `/health` reports v0.0.X. Sanity-check that no new ECS rolling
      deploy fails (elastic) or that compose containers came up healthy (fixed).
   6. Proceed to teardown.
```

The exact section number depends on the current numbering — read the file and slot in correctly.

### Step 9 — CHANGELOG

In `docex/CHANGELOG.md`, under `## [Unreleased]`, add:

```markdown
### Added

- `./bin/docex rollback <env> <target_version>` — emergency reversion to a
  prior version, code-only, at most one minor back. Doctrine spec at
  cicd.md § Rollback. `--dry-run` previews the apply on both foundations.
- `DockerClient.manifest_inspect(ref)` for registry image-existence probes.
- `AWSClient.ecr_image_exists(repository, tag)` for ECR image probes.
- `run_playbook` learns `skip_tags=` and `check_mode=`.
```

(Match the existing Keep-a-Changelog format used elsewhere in the file.)

### Step 10 — Commit

After the implementation is done and `pytest` passes (`pytest tests/unit/` at minimum), commit the working tree directly to `main` per [docex_process.md § Git](../../core/docex_process.md):

```
mod 029: rollback command — code-only narrow-window prod reversion
```

Do **not** cut a new docex version in this mod. The version cut is a separate step run after the advance closes.

## Five-artifact alignment after this mod

| Artifact | Status after mod 029 |
| -------- | -------------------- |
| `doctrine/.../*.md` | Already aligned (prior turn). |
| `docex/plans/core/*.md` | `release_flow.md` to be updated in the post-impl doc-update step (per mod cycle step 7 — NOT part of this implementation document). |
| `tables/roles/*.yml` | Untouched. |
| `src/docex/**` | New `pipeline/rollback.py`, `pipeline/_worktree.py`; edits to `pipeline/check.py`, `pipeline/release.py`, `__main__.py`, `errors.py`, `ansible/subprocess_runner.py`, `docker/{client,subprocess_client}.py`, `aws/{client,boto3_client}.py`, `opentofu/__init__.py`. |
| `tests/**` | New `tests/unit/test_pipeline_rollback.py`, `tests/unit/test_worktree_versions.py`, `tests/unit/test_aws_ecr_image_exists.py`; extensions to `tests/conftest.py`, `tests/unit/test_subprocess_docker_client.py`, `tests/unit/test_pipeline_release.py`. |

## What this implementation does NOT do

- Does not add the "Rollback flow" section to `plans/core/release_flow.md`. That is the design-context LLM's post-execution job (per the mod cycle).
- Does not cut a docex version.
- Does not modify the doctrine.
- Does not touch transfer tables.
- Does not change the smoke-project source. (PRE_CUT_CHECKLIST.md is doctrine-side test guidance, not project source.)
