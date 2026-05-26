# `docex` — Phase 3 Implementation

This document covers the work needed to ship Phase 3 of `docex`: the `check`, `merge`, `containerize`, `release` (fixed only), `stagetest`, and the fixed-foundation halves of `migrate stage` / `migrate prod`. Phase 3 takes a doctrine-conformant fixed-foundation project from "runnable on a dev/test stack" (Phase 2) to "fully releasable to stage and prod via the CI/CD pipeline." After Phase 3, the entire chain `docex merge && docex containerize && docex release stage && docex stagetest && docex release prod` works end-to-end for fixed projects.

Phase 3's success criterion: against a fixed-foundation project, a developer can run the manual CI/CD chain from [cicd.md § Manual `docex` Chain](../../doctrine/infrastructure/cicd.md#manual-docex-chain) end-to-end and land code in a deployed prod environment.

## Required Reading

You should already have the Phase 1 + 2 doctrine context. Additional load-bearing reads for Phase 3:

1. `~/.claude/jean_baudrillard/doctrine/infrastructure/cicd.md` — re-read end-to-end. Phase 3 implements nearly every step described in this file.
2. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/release_mechanism.md` — authoritative for the fixed-foundation release flow (Ansible playbook structure, SSH credentials, registry credentials, inventory).
3. `~/.claude/jean_baudrillard/doctrine/infrastructure/contracts.md` — contract format spec; needed for `check`'s contract-alignment gate.
4. `~/.claude/jean_baudrillard/doctrine/infrastructure/version_control.md` — branch and version conventions; `check` and `merge` both enforce these.
5. `~/.claude/jean_baudrillard/doctrine/infrastructure/credentials.md` — deploy creds layout, registry creds, AWS creds.
6. `~/.claude/jean_baudrillard/doctrine/infrastructure/docex.md` §§ check, merge, containerize, release, stagetest, migrate — authoritative per-command surfaces.
7. `~/.claude/jean_baudrillard/docex/implementation/phase_2.md` — to know the patterns Phase 2 established (DockerClient pattern, orchestrate layer, fixture extensions).

## Scope Boundaries

**In scope for Phase 3:**
- `check` — ephemeral worktree + full gate-check sequence + build + test against merged state.
- `merge` — defensive recheck + rebase + fast-forward + tag + push + branch cleanup.
- `containerize` — `docker buildx build --target prod` + tag + push for each core service.
- `release <env>` — **fixed foundation only**. Runs the emitted Ansible playbook against the env's host.
- `stagetest` — ephemeral stage-tester container against the deployed staging URL.
- `migrate <env>` for `stage`/`prod` — **fixed foundation only**. Runs just the migrate task of the playbook against the deployed env.
- `GitClient` abstraction parallel to `DockerClient`.
- `AnsibleRunner` — a small wrapper for `ansible-playbook` invocations.
- Ansible + git + openssh-client added to the image.
- One Phase 1 patch: the compose emitter's `disk:` → `tmpfs` translation drops the units' `B` suffix.
- Sample fixture extended with `infra/contracts/api.openapi.yml` so `check`'s contract gate has something to validate.

**Explicitly NOT in scope:**
- `release stage` / `release prod` for elastic — Phase 4.
- `migrate stage` / `migrate prod` for elastic — Phase 4.
- `bootstrap` — Phase 4.
- HCL emission fixes (semicolons, Fargate memory rounding, ECS `secrets[]` block, listener-rule host_header) — all elastic concerns; Phase 4.
- Deep contract validation (schemathesis-style schema conformance) — Phase 3 only checks existence and required-endpoints presence.
- Automated CI/CD triggers (GitHub Actions, GitLab CI wrappers). The doctrine assumes docex is driven manually or by a thin CI runner.
- Rollback. Doctrine-deferred.

## What Phase 2 Already Provides

Phase 2 shipped these pieces Phase 3 leans on:

- `DockerClient` protocol + `SubprocessDockerClient`. Phase 3 extends the protocol with a `buildx` method and a `push` method; the existing implementation grows to cover them.
- `docex.orchestrate._common.{ensure_compiled, compose_file_for, core_services, services_with_schema, compose_service_key}`. Phase 3's release/migrate paths reuse these.
- `docex.orchestrate.test.run_test(ctx, docker)`. `check` calls this directly inside the ephemeral worktree's project context to satisfy its "run full test suite" requirement.
- The sample fixture's `core/api/` tree. Phase 3 only adds `infra/contracts/api.openapi.yml` and possibly an `infra/stage/` tree.
- The Phase 2 fixed Phase 1 emitter to emit `build:` blocks for dev/test. Phase 3 leaves those alone; `containerize` does not use compose for image building.

The Phase 1 `disk:` → `tmpfs` translation is broken (Phase 2 worked around it in the fixture by omitting `disk:`). Step 1 patches it.

## Step-by-Step Implementation

### Step 1: Patch Phase 1 — `disk:` translation

In the compose emitter, fix the translation from CICL `disk:` to docker tmpfs. Current behavior emits `tmpfs: ["/tmp:size=20GB"]`; docker's tmpfs `size=` option does not accept `B`-suffix units. Translate `<n>GB` → `<n>g` and `<n>MB` → `<n>m` (lowercase, no `B`).

Add a unit test under `tests/unit/test_compose_emitter.py` that compiles a fixture with `disk: 20GB` and asserts the emitted tmpfs string is `/tmp:size=20g`. Restore `disk: 20GB` to `tests/fixtures/sample_project/infra/infra.yml` and remove the workaround comment.

This is the only Phase 1 patch Phase 3 needs. The elastic HCL bugs noted in earlier reviews belong to Phase 4.

### Step 2: Add ansible + git + openssh-client to the image

Update `Dockerfile` to install:
- `git` (pin version) — used by `check` and `merge` for worktree, fetch, rebase, tag, push.
- `ansible` (pin version, install via pip with a `requirements.txt` so transitive deps pin too) — used by `release` and stage/prod `migrate`.
- `openssh-client` — used by ansible to SSH to fixed hosts.
- `community.docker` Ansible collection — the playbook templates use `community.docker.docker_*` modules.

Bump `pyproject.toml`'s version and `docex.__version__` to `0.3.0`. Update every stub message that references the version. Rebuild and confirm `git --version`, `ansible-playbook --version`, `ssh -V` all work inside the new image.

### Step 3: `GitClient` abstraction

Create `src/docex/git/` parallel to `src/docex/docker/`:

```
src/docex/git/
├── __init__.py
├── client.py             (GitClient Protocol)
└── subprocess_client.py  (SubprocessGitClient; the ONLY module permitted to import subprocess for git)
```

`GitClient` covers every git operation `check` and `merge` need:

```python
class GitClient(Protocol):
    def is_clean(self, cwd: Path) -> bool: ...
    def current_branch(self, cwd: Path) -> str: ...
    def head_sha(self, cwd: Path, *, short: bool = False) -> str: ...
    def fetch(self, cwd: Path, *, remote: str = "origin") -> int: ...
    def merge_base(self, cwd: Path, a: str, b: str) -> str: ...
    def rebase(self, cwd: Path, onto: str) -> int: ...
    def fast_forward(self, cwd: Path, branch: str, to_ref: str) -> int: ...
    def tag(self, cwd: Path, name: str, *, ref: str = "HEAD") -> int: ...
    def tag_exists(self, cwd: Path, name: str) -> bool: ...
    def push(self, cwd: Path, *, remote: str = "origin", refs: list[str]) -> int: ...
    def delete_branch(self, cwd: Path, name: str, *, remote: bool = False) -> int: ...
    def worktree_add(self, cwd: Path, path: Path, *, branch: str | None = None, ref: str = "HEAD") -> int: ...
    def worktree_remove(self, cwd: Path, path: Path) -> int: ...
    def list_tags(self, cwd: Path, *, pattern: str | None = None) -> list[str]: ...
```

Same rules as `DockerClient`: every method returns the exit code (where applicable); none raise on non-zero. `SubprocessGitClient` is the only module permitted to `import subprocess` for git. The dispatcher wires the real implementation; unit tests use a `FakeGitClient` recorder.

Add new errors to `errors.py`: `WorkingTreeDirty`, `BranchNotRebaseable`, `VersionAlreadyReleased`, `ContractMissing`, `ContractInvalid`, `BuildxFailed`, `RegistryPushFailed`, `AnsibleRunFailed`, `StageTesterBuildFailed`.

### Step 4: `AnsibleRunner` — thin function-level abstraction

Ansible only needs one operation: run a playbook. Skip the Protocol ceremony and keep this as one function (with a fake for tests):

```python
# src/docex/ansible/__init__.py
def run_playbook(
    playbook: Path,
    inventory: Path,
    *,
    extra_vars: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    config: Path | None = None,
    private_key: Path | None = None,
) -> int: ...
```

Implementation lives at `src/docex/ansible/subprocess_runner.py`. The dispatcher passes a callable to commands that need it; tests inject a `fake_run_playbook` that records arguments.

The `private_key` argument is used by `release` and stage/prod `migrate` to point ansible at `infra/deploy_creds/<env>` per [release_mechanism.md § SSH Credentials](../../doctrine/infrastructure/specifics/release_mechanism.md#fixed-foundation-ansible).

### Step 5: Extend the sample fixture

Add to `tests/fixtures/sample_project/`:

```
infra/
├── contracts/
│   └── api.openapi.yml         (minimal OpenAPI doc with /health and /health/database)
└── stage/
    ├── Dockerfile              (Python + pytest + httpx — stage-tester image)
    ├── stage_test.sh           (POSIX shim that runs pytest against $STAGING_URL)
    └── tests/
        └── test_smoke.py       (one trivial check against STAGING_URL/health)
```

The contract file must declare:
- `paths: /health: { get: ... }` — required because `api` is on the `web` network.
- `paths: /health/database: { get: ... }` — required because `api` declares `depends_on: [database]` and `database` cannot be checked from the open web.

For the stage tester:
- `infra/stage/Dockerfile`: `FROM python:3.12-slim`, install `pytest` + `httpx`, COPY tests in.
- `infra/stage/stage_test.sh`: `set -eu; exec pytest -q /project/infra/stage/tests`
- `tests/test_smoke.py`: a single `def test_health(): assert httpx.get(f"{os.environ['STAGING_URL']}/health").status_code == 200`.

Also add `infra/deploy_creds/stage` and `infra/deploy_creds/prod` placeholder SSH private key files (use `ssh-keygen -t ed25519` to generate genuine keys for the fixture; they won't authenticate anywhere, but they must parse as valid keys for ansible to load them). Add `infra/deploy_creds/.gitignore` (already exists from Phase 1 bootstrap) — verify it ignores the private keys.

These additions make `check`'s contract gate, `release`'s ansible invocation, and `stagetest` exercisable in tests without external infrastructure.

### Step 6: `containerize`

`src/docex/pipeline/containerize.py` per [docex.md § containerize](../../doctrine/infrastructure/docex.md#containerize) and [cicd.md § Containerize Step](../../doctrine/infrastructure/cicd.md#containerize-step).

1. Validate preconditions:
   - Working tree is clean (`git.is_clean(project_root)`).
   - Current branch is `main`.
   - `project.yml` version corresponds to an existing tag `v<version>` on `HEAD` — confirms images get pushed for a real, tagged commit.
2. Resolve the registry: `infra.yml`'s `container_registry` field (required on fixed; per Phase 1 validation, set on all fixed projects).
3. Resolve the target platform: default `linux/amd64`; allow per-project override via a `host_machine.platform` field on the project (deferred; default for Phase 3).
4. For each core service:
   - `docker.buildx_build(context=core/<svc>, dockerfile=core/<svc>/Dockerfile, target="prod", platform=<target>, tag=<full_tag>)`.
   - `full_tag = ${container_registry}/${project_name}/${service_name}:${version}`.
5. `docker.push(<full_tag>)` for each tagged image. The host's `~/.docker/config.json` is mounted into the container per the shim — `docker push` uses whatever credentials are already there.
6. Exit 0 on full success; non-zero on the first failure (skip remaining services on failure).

Extend `DockerClient` with `buildx_build(context, dockerfile, target, platform, tag)` and `push(tag)`. Both return exit codes. `SubprocessDockerClient` implements both via `docker buildx build` and `docker push` respectively.

Print one line per built+pushed image: `containerize: pushed <full_tag> (sha256:...)`.

### Step 7: `check` — the ephemeral worktree and gate-check sequence

`src/docex/pipeline/check.py` per [docex.md § check](../../doctrine/infrastructure/docex.md#check) and [cicd.md § Check Step](../../doctrine/infrastructure/cicd.md#check-step).

This is the largest Phase 3 command. The sequence:

1. **Pre-check on the developer's working tree:**
   - `git.is_clean(project_root)` — refuse if dirty. Error: `WorkingTreeDirty`.
   - Determine the feature branch (`git.current_branch(project_root)`); refuse if it equals `main`.
2. **Fetch latest origin:** `git.fetch(project_root, remote="origin")`. Surface the result.
3. **Create the ephemeral worktree:**
   - Worktree path: `<project_root>/.docex/worktrees/check-<short_sha>` where `<short_sha>` = `git.head_sha(project_root, short=True)`.
   - `git.worktree_add(project_root, path=worktree_path, branch=<temp_branch>, ref=<feature_branch>)`. The temp branch name should encode the feature branch + timestamp so concurrent `check` invocations don't collide.
4. **Rebase feature onto fresh origin/main inside the worktree:**
   - `git.rebase(cwd=worktree_path, onto="origin/main")`. If it fails (merge conflicts), abort, report, clean up worktree, exit non-zero.
5. **Gate checks** (each is its own function in `check.py`; collect all failures and report together, just like Phase 1's compile-time validation rule aggregation):
   - **Working tree clean** inside the worktree (defensive — should hold by construction).
   - **Latest main is used:** the rebase landed on top of the actual `origin/main` HEAD; not a stale local main.
   - **Version bumped:** `project.yml`'s version in the worktree is strictly greater than the version on `origin/main` (semver compare).
   - **Version not already released:** no existing tag matches `v<version>` (use `git.list_tags(pattern="v*")`).
   - **No merge conflicts:** confirmed by step 4's exit code; record as a check anyway for the report.
   - **Contracts exist:** for each core service that is a provider (i.e. has at least one `depends_on` arrow pointing at it from another core service), there must be a file at `infra/contracts/<svc>.<fmt>.yml` where `<fmt>` is derived from the communication mechanism. For Phase 3, infer the format from the consumer's relationship — HTTP consumers ⇒ openapi, queue consumers ⇒ asyncapi. Default to `openapi` if unclear.
   - **Health-check endpoints:** for each contract file whose service is on the `web` network, load the YAML and verify it declares `/health` as a path with a GET operation. For each downstream service in the dependency chain that is NOT on the web network, verify `/health/<service>` exists. Use `pyyaml` for the load; do not pull in a full OpenAPI parser (those are heavy and Phase 3's needs are minimal).
   - **Service scripts:** for each core service, verify `build.sh`, `test.sh`, and (if `schema_owned_by` references this service from any backing service) `migrate.sh` all exist and are executable.
6. **Ensure build doesn't fail:** run `compile` against the worktree, then `docker compose -f infra/output/test/docker-compose.yml build` to confirm every `docker build` succeeds. This catches Dockerfile errors without running tests.
7. **Run build test:** call `docex.orchestrate.test.run_test(worktree_ctx, docker)` against the worktree. Reuses Phase 2's test machinery wholesale.
8. **Cleanup**, on success or failure: `git.worktree_remove(project_root, worktree_path)` (with `--force` if removal fails normally). Delete the temp branch.

The aggregation pattern: collect each gate-check's outcome into a list; print a clean summary table at the end; exit non-zero if any failed. The developer should see all problems in one pass.

Add `_aggregate_check_report(...)` helper that formats results with rich's table or a plain text-format equivalent.

### Step 8: `merge`

`src/docex/pipeline/merge.py` per [docex.md § merge](../../doctrine/infrastructure/docex.md#merge) and [cicd.md § Merge](../../doctrine/infrastructure/cicd.md#merge).

1. **Re-run gate checks defensively** — call `check`'s entry point. Catches race conditions where `main` moved between `docex check` and `docex merge`.
2. **Identify feature branch:** `git.current_branch(project_root)`.
3. **Fetch + rebase:** `git.fetch`, then `git.rebase(cwd=project_root, onto="origin/main")`. This time we rebase the developer's actual working tree, not a worktree.
4. **Fast-forward main to the rebased tip:** `git.fast_forward(cwd=project_root, branch="main", to_ref=feature_branch)`.
5. **Tag:** `git.tag(name=f"v{project.version}", ref="main")`. Refuse with `VersionAlreadyReleased` if the tag exists.
6. **Push:** `git.push(remote="origin", refs=["main", f"v{project.version}"])`.
7. **Delete feature branch:** `git.delete_branch(name=feature_branch, remote=False)` then `git.delete_branch(name=feature_branch, remote=True)`.

If any step fails after the rebase, leave the local branch in its rebased state (don't try to unwind — the operator can see what happened in `git log`).

### Step 9: `release <env>` — fixed only

`src/docex/pipeline/release.py` per [docex.md § release](../../doctrine/infrastructure/docex.md#release) and [release_mechanism.md § Fixed Foundation: Ansible](../../doctrine/infrastructure/specifics/release_mechanism.md#fixed-foundation-ansible).

1. Validate `env in {"stage", "prod"}`. `release dev` / `release test` is an error pointing at `docex up`.
2. Determine the project's foundation. If `elastic`: print a Phase 4 "not yet implemented" stub and exit 2. **The fixed path is the only one this phase implements.**
3. Validate prerequisites:
   - The expected image tag exists locally OR can be pulled from the registry (skip pre-check; let ansible's `docker pull` surface the error).
   - `infra/deploy_creds/<env>` exists (the SSH private key).
   - `infra/secrets/<env>.env` exists.
4. Call `ensure_compiled(ctx)` — `release` requires fresh output.
5. Resolve paths emitted by the compiler:
   - playbook: `infra/output/<env>/playbook.yml`
   - inventory: `infra/output/<env>/inventory.yml`
   - config: `infra/output/<env>/ansible.cfg`
6. Invoke `ansible.run_playbook(playbook, inventory, config=cfg, private_key=infra/deploy_creds/<env>)`. The playbook does the rest: docker pull, render configs, run migrations, start the stack.
7. Exit 0 on success; surface the playbook's exit code on failure.

No retries, no rollback. Re-running on an already-converged target is a no-op per ansible idempotence.

### Step 10: `stagetest`

`src/docex/pipeline/stagetest.py` per [docex.md § stagetest](../../doctrine/infrastructure/docex.md#stagetest) and [cicd.md § Staging Tests](../../doctrine/infrastructure/cicd.md#staging-tests).

1. Determine `STAGING_URL` from `infra.yml`'s `domain` field: `https://stage.<domain>`.
2. Build the stage tester image:
   - Context: `infra/stage/` of the project.
   - Tag: `<project_name>-stage-tester:<short_sha_of_infra_stage>` (or just `<project_name>-stage-tester:latest` and rely on docker's content-addressed layer caching).
   - Skip the build if the image exists and the `infra/stage/` tree's mtime is older than the image's create time. Implementation can just always build — docker caches; the doctrine doesn't require an mtime check.
3. Spawn the ephemeral container:
   - `docker run --rm --network host -v <project_root>:/project -e STAGING_URL=<url> <project>-stage-tester /project/infra/stage/stage_test.sh`
   - `--network host` is the simple choice for "container needs to reach the deployed staging URL." If the deployment is internal-only and the operator's machine has VPN access, this works. Document that projects with stricter network needs may have to override.
4. Propagate the container's exit code as the command's exit code.

Add `DockerClient.build_image_with_tag(context, dockerfile, tag)` if not already covered by Phase 2's `build_image` — adjust as needed.

### Step 11: `migrate stage` / `migrate prod` — fixed only

`src/docex/orchestrate/migrate.py` already exists from Phase 2. Update its stage/prod branch:

```python
if env in ("stage", "prod"):
    foundation = ctx.infra.foundation
    if foundation == "elastic":
        # Still a stub; Phase 4 wires this.
        print(f"'docex migrate {env}' on elastic foundation is part of Phase 4; not yet implemented in docex {__version__}", file=sys.stderr)
        return 2
    # Fixed foundation: invoke the migrate task of the playbook.
    playbook = ctx.project_root / "infra" / "output" / env / "playbook.yml"
    inventory = ctx.project_root / "infra" / "output" / env / "inventory.yml"
    config = ctx.project_root / "infra" / "output" / env / "ansible.cfg"
    private_key = ctx.project_root / "infra" / "deploy_creds" / env
    return ansible.run_playbook(
        playbook, inventory,
        config=config,
        private_key=private_key,
        tags=["migrate"],
    )
```

The playbook's migration task must be tagged `migrate` so `tags=["migrate"]` runs only that step. Update the compiler's playbook template (`src/docex/emit/templates/playbook.yml.j2`) to add `tags: [migrate]` on the migration tasks.

Add the same elastic stub for `release stage/prod` already covered in Step 9.

### Step 12: Wire dispatcher

In `src/docex/__main__.py`, replace the five Phase 3 stubs (`check`, `merge`, `containerize`, `release`, `stagetest`) with real handlers wired to the orchestrate / pipeline entry points. The `migrate` handler already exists from Phase 2 — extend it to thread through the new `AnsibleRunner` dependency.

Bump version-stub messages to reference `docex 0.3.0`. Keep `bootstrap` stubbed (Phase 4).

The dispatcher constructs the production clients once at top:

```python
docker = SubprocessDockerClient()
git = SubprocessGitClient()
ansible = subprocess_run_playbook  # from docex.ansible.subprocess_runner
```

and passes them to each command.

### Step 13: Unit tests with mocked clients

Under `tests/unit/`, add one test file per pipeline command:

- `test_pipeline_check.py` — uses `FakeGitClient` + `FakeDockerClient`. Asserts:
  - Refuses to run with a dirty working tree.
  - Worktree is created and torn down even on failure.
  - All gate checks run; failures aggregate in the report.
  - Contract-missing produces `ContractMissing`.
  - Health-check endpoint missing surfaces a clear error.
  - Version-already-released catches a duplicate tag.
- `test_pipeline_merge.py` — asserts gate checks run defensively before rebase, rebase failure aborts before push, tag created with right name, push includes both `main` and the new tag, feature branch deleted local + remote.
- `test_pipeline_containerize.py` — asserts platform default, full-tag format, push call per service, working-tree-dirty / not-on-main / tag-missing refuse to run.
- `test_pipeline_release.py` — asserts fixed path calls ansible with right args, elastic path stubs out with exit 2, `release dev` / `release test` refused.
- `test_pipeline_stagetest.py` — asserts `STAGING_URL` is built from `domain`, container args include the bind mount and `--rm`, exit code propagates.
- `test_orchestrate_migrate_stage.py` — asserts fixed stage/prod call ansible with `tags=["migrate"]`, elastic still stubs.

Add `FakeGitClient` and `fake_run_playbook` fixtures to `tests/conftest.py` alongside the existing `FakeDockerClient`.

### Step 14: Integration tests with real git and ansible

Under `tests/integration/`, add (all gated by `@pytest.mark.integration`):

- `test_check_real.py` — creates a temporary git repo with the sample fixture, makes a feature branch with a version bump, runs `docex check`. Asserts a worktree is created under `.docex/worktrees/`, gate checks pass, tests run, worktree is removed. Then introduces a deliberate contract violation (delete `/health` from the OpenAPI) and reruns to confirm failure is reported.
- `test_merge_real.py` — same setup, runs `docex merge`. Asserts main is fast-forwarded, tag is created, feature branch is gone. Use a temp upstream (`git init --bare`) so push has a real destination.
- `test_containerize_real.py` — actually runs `docker buildx build --target prod` against the fixture and asserts a tagged image lands in the local image store. Skip the `push` step (or push to a local registry container that the test brings up and tears down).
- `test_stagetest_real.py` — brings up the dev stack (acting as a stand-in for "staging"), runs `docex stagetest` with the staging URL pointed at `http://localhost:8080`. Asserts the smoke test passes.

`test_release_real.py` is **deliberately omitted** — the release path requires an SSH-reachable target host and live registry credentials. Integration testing it would mean spinning up a sshd container with the project pre-configured; that's more scaffolding than this phase warrants. Manual smoke (Step 15) covers it.

### Step 15: End-to-end smoke test

The Phase 3 acceptance gate. Manually:

1. Rebuild the image: `docker build -t docex:0.3.0 .`
2. Bump the fixture's `project.yml` to `docex_version: "0.3.0"`.
3. Initialize a fresh git repo from the fixture, create a feature branch, make a trivial change (e.g. add a comment to `src/app.py`), bump `project.yml` version to `0.1.1`.
4. Run `./bin/docex check`. Confirm:
   - A worktree appears under `.docex/worktrees/` while running.
   - Gate checks all pass.
   - Build + test succeed.
   - The worktree is gone after the command exits (success or failure).
5. Modify `infra/contracts/api.openapi.yml` to delete the `/health` endpoint. Re-run `docex check`. Confirm the contract gate fails with a clear error pointing at the missing endpoint.
6. Restore the contract, then run `./bin/docex merge`. Confirm:
   - `main` was fast-forwarded.
   - `v0.1.1` tag exists locally.
   - Both `main` and the tag were pushed to the upstream (a `git init --bare` in `/tmp/origin`).
   - The feature branch is deleted locally and on the upstream.
7. Set up a tiny local registry: `docker run -d -p 5000:5000 --name local-registry registry:2`. Update `infra.yml`'s `container_registry` to `localhost:5000`.
8. Run `./bin/docex containerize`. Confirm `localhost:5000/sample/api:0.1.1` appears via `curl http://localhost:5000/v2/sample/api/tags/list`.
9. (Optional — needs an SSH-reachable target.) Set up an SSH-reachable VM or LXC container with docker installed. Update the fixture's `inventory.yml` (or `domain:` field) to point at it. Put an authorized key on the target matching `infra/deploy_creds/stage`. Run `./bin/docex release stage`. Confirm the playbook runs cleanly and the container is up on the target.
10. Run `./bin/docex stagetest`. Confirm the smoke test passes (against either the deployed stage or the local dev stack acting as a stand-in).
11. Stubs still work: `./bin/docex release prod` (if foundation=elastic) and `./bin/docex bootstrap` print Phase 4 messages.

If steps 1-8, 10, and 11 succeed, Phase 3 is done. Step 9 is operator-dependent; if you don't have an SSH target handy, manually trace the playbook by running `ansible-playbook --check --diff` against a fake inventory and confirm the task list reads correctly.

## Things to Avoid

- **Don't bypass `GitClient` or the ansible runner.** Every git/ansible call goes through the abstraction. Same rule as Phase 2's DockerClient: tractable unit testing depends on it.
- **Don't fold `check` and `merge` into one command.** They're explicitly separated in the doctrine because `check` is a read-only safety net and `merge` is destructive. Keeping them separate lets a developer iterate on `check` without polluting their git history.
- **Don't try to make `check` automatically re-run after fixing a single failing gate.** The doctrine prescribes "fix and re-invoke"; auto-retry hides the failing state.
- **Don't pre-implement elastic release / elastic migrate / elastic stagetest in Phase 3.** All Phase 4. Elastic-foundation projects can still use `check`, `merge`, `containerize`, and `stagetest` — those are foundation-agnostic. Only `release` and `migrate stage/prod` branch on foundation.
- **Don't pull in a heavy OpenAPI/AsyncAPI library** for the contract gate. Phase 3 only checks that specific paths and operations exist; a `yaml.safe_load` followed by dict lookups is enough. Schemathesis-style conformance is a separate concern.
- **Don't reach for `docker login` in `containerize`.** The shim mounts `~/.docker/config.json` from the host; `docker push` uses whatever auth is already configured there. Forcing login from inside docex would re-prompt and reauthenticate every run.
- **Don't add a `--dry-run` flag to `release` or `merge` yet.** Useful, but adds permanent surface; the doctrine doesn't prescribe it.
- **Don't break the Phase 1 / Phase 2 regression tests.** The Step 1 `disk:` patch touches the compose emitter — re-run the full test suite after every change, the same way Phase 2 did.

## What Happens After Phase 3

When Phase 3 ships, the doctrine is *fully runnable for fixed-foundation projects* — from local dev iteration through tagged release to deployed prod. Elastic-foundation projects can still author and locally test, but `release stage/prod` will stub out.

Phase 4 (`bootstrap`, `release` for elastic, the elastic `migrate stage/prod` paths, plus the elastic HCL emission fixes called out in earlier reviews) closes the elastic side and finishes the docex command surface defined in the design proposal.
