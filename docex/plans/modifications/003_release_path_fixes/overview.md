# Mod 003 — Release path fixes (image, emitter, checklist)

## Problem

The first end-to-end walk of `test_projects/fixed` past C.6 (containerize) into C.7 (release stage) surfaced a cluster of bugs in the docex image, the compose/Ansible emitter, and the operator-prereq checklist. None individually fatal, but together they prevent `docex release` from completing without manual intervention.

Findings, in the order they're encountered during a release:

1. **Ansible collections missing from the docex image.** The doctrine-emitted playbook uses `community.docker.docker_compose_v2` and `community.docker.docker_container`; the image bundles `ansible-core` but no collections. First task fails with `Unable to resolve module/action 'community.docker.docker_compose_v2'`.
2. **Emitted `ansible.cfg` references a deprecated callback.** `stdout_callback = yaml` was a `community.general` plugin removed in v12. Ansible refuses to load the playbook.
3. **Operator `deploy` user not documented in PRE_CUT_CHECKLIST A.7.** The doctrine prescribes deploys land as user `deploy` (docker group + passwordless sudo); the checklist only says "append .pub keys to `~/.ssh/authorized_keys`." Ansible connects as `deploy@<host>` and gets `Permission denied (publickey)`.
4. **Operator `docker login` not documented in PRE_CUT_CHECKLIST A.7.** Both the `deploy` user (for `docker compose` pulls when run unprivileged) AND `root` (because the playbook uses `become: true` and runs `docker compose` as root) need `~/.docker/config.json` populated for the project's container registry.
5. **Migration playbook task masks failures.** Emitted with `auto_remove: true`; when the migration container exits non-zero, Ansible can't read its exit code or logs and reports the unhelpful `Cannot retrieve result as auto_remove is enabled`.
6. **Migration playbook task doesn't inherit the application's env vars.** The compile-time-resolved `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_NAME` live in the compose file's `web.environment:` block. The migration task uses `community.docker.docker_container` with only `env_file: .env` — which contains just `POSTGRES_USER` / `POSTGRES_PASSWORD`. `migrate.sh` looks for `DATABASE_HOST` and exits with `DATABASE_HOST must be set`. This is the actual root blocker for C.7.

Two additional findings discovered tangentially that I've already fixed inline this session and want to formally fold into this mod for completeness:

7. **`.pyc` files were tracked in docex with no `.gitignore`.** Fixed: added `docex/.gitignore`, untracked 82 stale `.pyc` files (commit on master).
8. **Test projects aren't their own git repos.** Fixed: `git init` + `v0.0.1` tag in `test_projects/{fixed,elastic}/`, plus PRE_CUT_CHECKLIST A.2.1 documenting it (uncommitted).
9. **Docex container image has no writable HOME.** `/home` is root-owned with no `/home/<operator>` inside; ansible's `~/.ansible/tmp` creation fails with EACCES. Bandage applied: shim in `test_projects/fixed/bin/docex` adds a `~/.ansible` bind mount. Wants folding into the canonical shim or into the image.

## Design

### Fix 1+9 (image gaps) — `Dockerfile` bundles collections + env vars at known paths

Add to `docex/Dockerfile`:

```dockerfile
# Ansible collections needed by doctrine-emitted playbooks. Installed
# at the system-wide path so they don't depend on $HOME existing in the
# container — operator HOME isn't a directory the image controls.
RUN ansible-galaxy collection install community.docker:5 -p /usr/share/ansible/collections

# Redirect ansible's runtime scratch (tmp dir, control sockets) to /tmp
# so HOME doesn't need to be writable for ansible to function.
ENV ANSIBLE_LOCAL_TEMP=/tmp/.ansible-tmp
ENV ANSIBLE_PERSISTENT_CONTROL_PATH_DIR=/tmp/.ansible-cp
```

`community.docker:5` is pinned to a major-line that still has `docker_compose_v2`/`docker_container` and is current as of 2026. We bundle ONE collection — `community.general` isn't needed once Fix 2 lands, and `ansible.posix` isn't used by the emitted playbook.

The `ANSIBLE_LOCAL_TEMP` env var redirects ansible's per-run scratch dir to `/tmp/<id>` instead of `$HOME/.ansible/tmp/<id>`. Same for control persistence. With these, ansible doesn't write under `$HOME` at all — meaning the operator's bandaged `~/.ansible` mount in the shim is no longer needed and the shim stays clean.

This fix supersedes the bandage at `test_projects/fixed/bin/docex`; that file gets reverted to match the canonical shim.

### Fix 2 (deprecated callback) — modern `result_format = yaml`

`src/docex/emit/ansible.py` (or wherever ansible.cfg is rendered) currently emits:

```ini
[defaults]
inventory = inventory.yml
host_key_checking = False
retry_files_enabled = False
stdout_callback = yaml
```

Change to:

```ini
[defaults]
inventory = inventory.yml
host_key_checking = False
retry_files_enabled = False
stdout_callback = default
result_format = yaml
```

`stdout_callback = default` selects ansible-core's built-in default callback (always available, no external collection). `result_format = yaml` (introduced in ansible-core 2.13, ~2021) renders task output in the same YAML-block form the legacy `community.general.yaml` callback provided. Modern and dependency-free.

### Fix 5+6 (migration task) — `docker compose run --rm` instead of `community.docker.docker_container`

**This is the interesting one — and it dissolves both findings at once.**

The current emitted task:

```yaml
- name: Run migrations for web
  community.docker.docker_container:
    name: "{{ project }}_{{ env }}_web_migrate"
    image: "registry.luxrnd.tech/docex_smoke_fixed/web:0.0.1"
    command: /service/migrate.sh
    networks:
      - name: "{{ project }}_{{ env }}_internal"
    env_file: "{{ deploy_root }}/.env"
    detach: false
    auto_remove: true
```

This pattern creates a one-off container by hand — image, network, env_file specified imperatively. The problem: it has to manually mirror every aspect of how the `web` service is configured at compose-emit time. The compose file already encodes all of that — image, networks, the env-block with `DATABASE_HOST: docex-smoke-fixed-stage-db`, the env_file reference. The migration task duplicates *some* of that and drops the rest (the compile-time-resolved env vars).

The doctrine's release_mechanism.md is explicit about what we want:

> `migrate.sh` invokes the chosen tool against the database identified by **the same environment variables the service itself uses at runtime**.

The natural way to honor that is to run migration **as the same service**, just with a different command. Docker Compose has a built-in idiom for exactly this:

```
docker compose run --rm <service> <command>
```

`compose run` creates a one-off container from the same service definition the regular stack uses — same image, same `environment:` block (compile-time-resolved DATABASE_*), same `env_file:` (runtime POSTGRES_*), same networks, same volumes. It honors `depends_on` (db comes up if not running). It returns the command's exit code. `--rm` cleans up after.

The replacement task:

```yaml
- name: Run migrations for web
  ansible.builtin.command:
    cmd: docker compose run --rm web /service/migrate.sh
    chdir: "{{ deploy_root }}"
  register: web_migrate
  changed_when: true
  tags:
    - migrate
```

What this solves:

- **Finding 6 (env vars):** the one-off container inherits the web service's complete environment by definition. No drift between "the env vars the web container sees at runtime" and "the env vars the migration container sees" — they're literally the same compose service definition.
- **Finding 5 (auto_remove masking):** `ansible.builtin.command` captures stdout, stderr, and rc no matter the exit code. `--rm` handles cleanup. No more "Cannot retrieve result as auto_remove is enabled."
- **No `community.docker.docker_container` dependency** for migrations.

Costs:

- One additional `docker compose` invocation per migration, but it's a no-op start of dependencies if the stack is already running.
- Loops over schema-owning services if more than one needs migration (only `web` in our test projects today, but the emitter should produce a loop for general cases).

### Fix 3+4 (PRE_CUT_CHECKLIST A.7) — instruct creating the deploy user

`docex/test_projects/PRE_CUT_CHECKLIST.md § A.7` currently says:

> - [ ] Generate an SSH keypair for each env if not already present:
>   ```
>   ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/stage -N ''
>   ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/prod -N ''
>   ```
> - [ ] Append both public keys (`stage.pub`, `prod.pub`) to `~/.ssh/authorized_keys` on the dev machine (which is also the deploy target).

Update to actually instruct creating the `deploy` user the doctrine prescribes, plus the `docker login` work that both `deploy` and `root` need. Wording to be reviewed before writing — I'll show side-by-side before changing prose, per mod 002 protocol.

### Findings 7+8 (already inline)

The `docex/.gitignore` + pyc untrack is already committed on master (commit `b5a4e1f` or wherever it landed). The test-project `git init` + `v0.0.1` tags are already in place. The PRE_CUT_CHECKLIST A.2.1 sentence is already added but uncommitted.

This mod 003 commit picks up the uncommitted A.2.1 addition along with everything else, and reverts the local shim bandage at `test_projects/fixed/bin/docex` (since Fix 1+9's env-var redirect makes the bandage unnecessary).

## Five-artifact alignment

Per [`docex_process.md § Additional Artifacts`](../../core/docex_process.md#additional-artifacts):

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | **Two edits in `PRE_CUT_CHECKLIST.md`:** (1) finalize the A.2.1 addition already inline (test projects must be own git repos with v0.0.1 tag). (2) rewrite A.7 to instruct creating `deploy` user with docker group + passwordless sudo, copying public keys to `/home/deploy/.ssh/authorized_keys`, and running `docker login <registry>` as both `deploy` and `root`. **Pausing for operator review of A.7 wording before committing prose.** No release_mechanism.md edits — its existing prose is correct; the bugs are in the emitter and the checklist. |
| `docex/plans/core/*.md` | No change. |
| `tables/roles/*.yml` | No change. |
| `src/docex/**` | (a) `Dockerfile`: bundle `community.docker:5` collection at `/usr/share/ansible/collections`; set `ANSIBLE_LOCAL_TEMP` and `ANSIBLE_PERSISTENT_CONTROL_PATH_DIR` env vars. (b) ansible.cfg template (wherever it lives — search `src/docex/emit/`): replace `stdout_callback = yaml` with `stdout_callback = default` + `result_format = yaml`. (c) playbook template (probably the same module): replace the `community.docker.docker_container` migration task with `ansible.builtin.command` running `docker compose run --rm <service> /service/migrate.sh`, looped over `schema_owners`. |
| `tests/**` | Three new unit tests: (1) emitted ansible.cfg contains the modern `result_format = yaml` and no `stdout_callback = yaml`. (2) emitted playbook's migration task uses `ansible.builtin.command` with `docker compose run --rm`. (3) emitted playbook does NOT contain `auto_remove`. Integration tests aren't extended here — the test project walk is the integration test for the release path. |

## Validation

1. `python3 -m pytest tests/unit/` — all existing tests pass; new tests pass.
2. Rebuild the docex image: `docker build -t docex:0.7.0 .` from `~/.claude/jean_baudrillard/docex`. The build runs `ansible-galaxy collection install` and bakes in the collection at the system path; the resulting image is bigger by ~10 MB.
3. Revert the shim bandage at `test_projects/fixed/bin/docex` (restore from doctrine-side canonical, or `git checkout`).
4. Recompile both test projects. Spot-check `infra/output/stage/ansible.cfg` for `result_format = yaml`. Spot-check `infra/output/stage/playbook.yml` for `docker compose run --rm web /service/migrate.sh`.
5. Re-run `docex release stage` against `test_projects/fixed`. Expected: playbook reaches "Run migrations for web" task, migration succeeds (because env vars are inherited from the web service definition), then "Bring up the stack" succeeds, and `https://stage.doctrine-fixed.luxrnd.tech/health` returns 200 with a real LE cert.
6. Resume the C.* walk from C.7 onward.

## Decisions captured

1. **Bundle collections in the Dockerfile, not at runtime.** Determinism over flexibility — pinning the collection version at image-build time means every `docex:0.7.x` invocation produces identical playbook behavior.
2. **Use `docker compose run --rm` for migrations.** Best mechanism for "same env as the application." Drops `community.docker.docker_container` dependency for migrations entirely.
3. **Redirect ansible scratch to `/tmp` rather than mount `~/.ansible`.** Avoids growing the shim's mount set for one tool; the env-var approach scales to other tools with similar HOME-write needs.
4. **No release_mechanism.md edits.** The doctrine prose is correct; the bugs are emitter and checklist.

## Pending pause

Before writing the A.7 prose, I'll show side-by-side wording for the operator's sign-off, same protocol as mod 002.
