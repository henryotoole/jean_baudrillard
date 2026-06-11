# Mod 053 — Implementation Steps

Execution plan for [`overview.md`](./overview.md). Written for a fresh context.
Read `overview.md` first for the *why*; this file is the *how*.

## Ground rules

- **Trunk-based, on `main`** — `docex` commits directly to `main` per
  `docex_process.md § Git`. Do not branch.
- **No doctrine prose changes.** Everything here is `docex` code, the
  test-project seeds under `test_projects/`, or `PRE_CUT_CHECKLIST.md`. If you
  find a real doctrine gap, STOP and surface it — do not edit doctrine.
- **No core-planning-doc edits** (per `modifications.md`). The design context
  agent updates `plans/core/*` after review; not you.
- **No contract changes** — this mod touches no core-service contract.
- **Tests:** add/extend unit tests for every code change; mark docker-touching
  tests with `@pytest.mark.integration`. Finish with `pytest` green (and
  `pytest -m integration` for the docker-marked ones where a daemon is
  available). The pre-mod baseline is **537 passed**.
- Five-artifact alignment (per `docex_process.md`): keep code + tests aligned;
  no doctrine/table changes expected here.

---

## Step 1 — Compose project identity (Cluster 1; the core fix)

This is the highest-care step; it touches the shared docker client and every
compose caller. Get the env-tier/project-tier naming coherent.

### 1a. `src/docex/docker/subprocess_client.py`

- **`_resolve_project_dir`** (≈ line 24): the `parent.parent.parent.parent`
  ("up 4") is correct for env-tier (`infra/output/<env>/…`) but wrong for
  project-tier (`infra/output/project/<side>/…`, one level deeper → lands on
  `<root>/infra`). Make it resolve to the true `<project_root>` for **both**
  tiers. Preferred: when `project_dir` is not passed, walk up to the directory
  containing `project.yml` (mirror `context._find_project_root`) instead of a
  fixed parent count. Keep the explicit-`project_dir` precedence (used by
  `check`'s worktree).
- **`_compose_base`** (≈ line 74): add a `project_name: str | None` parameter.
  When set, insert `["--project-name", project_name]` into the compose command
  (before the subcommand, alongside `--project-directory`).
- Thread `project_name` through the public methods that call `_compose_base`:
  `compose_up`, `compose_down`, `compose_exec`, `compose_ps`,
  `compose_ps_status`, `compose_run` (whichever exist). Default `None` so
  unrelated call sites are unaffected.
- **`any_env_compose_up`** (≈ line 365): it builds targets
  `f"{project_name}-{env}"`. This MUST match the explicit env-tier project name
  chosen in 1c. Today it's called with `ctx.project.name` (underscored,
  `docex_smoke_elastic`) but real stacks were named by the derived basename —
  a latent mismatch. Change it to accept/derive the **same** env-tier name form
  used by `compose_up` (the `dns_label`-based form from 1c), so the
  refuse-if-envs-up gate actually matches running stacks.

### 1b. `src/docex/docker/client.py` (the `DockerClient` Protocol)

Mirror the signature changes (add `project_name: str | None = None` to the
compose methods; update `any_env_compose_up` if its signature changes). Update
docstrings: note that `project_name`, like `project_dir`, must match between
`up` and `down` for compose to find its resources.

### 1c. Define one env-tier + one project-tier name helper

Add small helpers (suggest `src/docex/orchestrate/_common.py` for env, and reuse
in `pipeline/projinfra.py` for project tier), using `naming.dns_label`:

- `env_compose_project(ctx, env)` → `f"{dns_label(ctx.project.name)}-{env}"`
- project-tier → `f"{dns_label(ctx.project.name)}-projinfra-{side}"`

Use `dns_label(ctx.project.name)` (hyphenated, lowercased) consistently — NOT
the raw underscored name — so the compose project name is a valid, stable,
data-plane-style identifier.

### 1d. Pass the explicit name at every env-tier call site

Update these to pass `project_name=env_compose_project(ctx, env)` **and**
`project_dir=ctx.project_root` (so the fixed parent-count is no longer relied
on):
- `orchestrate/up.py` (compose_up, compose_ps_status, compose_exec) — `up`/`down`
- `orchestrate/down.py` (compose_down)
- `orchestrate/test.py` (compose_up, compose_exec×2, compose_down) — env `test`
- `orchestrate/build.py` (compose_ps, compose_ps_status, compose_exec)
- `orchestrate/migrate.py` (compose_exec)

`up`/`down` for a given env MUST pass the identical `project_name`.

### 1e. `pipeline/check.py` — keep the worktree stack isolated

`check` builds+downs a test stack in an ephemeral worktree (≈ lines 787/795).
Its compose project name must NOT collide with a real `test` env stack on the
same host. Derive a worktree-unique name (e.g.
`f"{dns_label(ctx.project.name)}-check-{env}"` or fold in the worktree slug) and
pass the matching `project_dir=<worktree path>` it already uses. Verify `check`
still tears its stack down cleanly.

### 1f. `pipeline/projinfra.py` — project-tier name + pass-through

- `run_projinfra_fixed_up` (≈ line 61): `compose_up(..., project_name=<proj-tier
  name>, project_dir=ctx.project_root)`.
- `run_projinfra_fixed_down` (≈ line 93): same `project_name` so `down` removes
  the traefik **and** the `-web` networks.
- The `any_env_compose_up(ctx.project.name)` call (≈ line 80) must pass whatever
  form 1a now expects.

### 1g. `src/docex/emit/compose.py` — explicit acme volume name

`emit_project_compose` (≈ line 515/566) declares `"volumes": {acme_volume: {}}`.
Change to `{acme_volume: {"name": acme_volume}}` so the real volume name is
exactly `${project_dns_label}-traefik-acme` (matches `fixed_reverse_proxy.md` and
the env-tier pattern already at line 419). 

### Step 1 tests

- `_resolve_project_dir` → `<project_root>` for an env-tier path AND a
  project-tier path (the off-by-one regression test).
- `_compose_base` includes `--project-name <x>` when passed; omits when `None`.
- `any_env_compose_up` targets match the env-tier name form from 1c.
- emit: project compose YAML has acme volume with explicit
  `name: <label>-traefik-acme`.
- `@pytest.mark.integration`: `projinfra up development` ×2 → second is a no-op
  (no name-conflict error); `projinfra down development` removes traefik + all
  four `-web` networks; no "not created for project" warning.

---

## Step 2 — Elastic projinfra UX (Cluster 3; F13, F14)

In `src/docex/pipeline/bootstrap.py` (the phase-1/phase-2 driver invoked by
`projinfra up production` on elastic):

- **F14:** on phase-2 `tofu apply` failure, capture and print the **actual**
  tofu stderr/return as the primary message. Keep the NS-delegation hint but
  demote it to a secondary "if the error above is an ACM/validation timeout, the
  likely cause is NS delegation not yet propagated." Do not present NS delegation
  as the cause unconditionally.
- **F13:** replace every user-facing "re-run `docex bootstrap`" with "re-run
  `./bin/docex projinfra up production`" (search `bootstrap.py` and any
  projinfra display strings). The internal function/module can stay named
  bootstrap; only operator-facing text changes.

### Step 2 tests
- Unit: phase-2 failure message includes the captured tofu error text; the NS
  hint is present but secondary.
- Unit/grep test: no operator-facing string instructs "docex bootstrap".

---

## Step 3 — Fargate-tier note dedupe (Cluster 5; F17)

`src/docex/cicl/compile.py` (≈ lines 202 & 220) prints the "resources rounded to
Fargate tier" note; it surfaced 4× per command because compile runs multiple
times per invocation. Make each unique note print **once per compile run**
(dedupe by `(service, message)` within a run, or collect and emit once). Don't
suppress legitimately distinct notes (different services/values).

### Step 3 tests
- Unit: compiling an elastic project that triggers rounding for 2 services emits
  each service's note once, not duplicated across internal compile passes.

---

## Step 4 — Shim ergonomics (Cluster 5; F3, F6)

`bin/docex` (the shim). It already `mkdir -p "$HOME/.docker"` (≈ line 66).

- **F6:** add `mkdir -p "$HOME/.ansible"` next to the `.docker` mkdir so
  ansible can write its local state (fixes the "Failed to create
  /home/ubuntu/.ansible" warning on `release`).
- **F3:** the "Failed to add the host to the list of known_hosts" noise comes
  from docex's own SSH probe writing to a read-only `~/.ssh`. Prefer fixing it
  where docex invokes ssh (preinfra production probe / ansible ssh args) with
  `-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new` rather
  than touching the shim mount. Locate the ssh invocation (preinfra production
  fixed registry-cred probe) and add those options. If it's cleaner shim-side,
  note why.

Shim changes are deliberate (the shim is "permanent"); keep them minimal and
commented.

### Step 4 tests
- Shim is bash, not unit-tested directly. Validate in the re-walk (no
  `.ansible`/known_hosts warnings). Add a comment in the shim referencing F6/F3.

---

## Step 5 — Test-project seeds (Clusters 2 & 4)

Each seed edit dirties both the inner repo (`test_projects/<f>/.git`) and the
outer repo; commit inner-first per `test_projects.md § Commit cadence` (the
design-context agent handles outer-repo catchup, not you — but do make the inner
commits so the seed state is coherent).

### 5a. Teardown ordering (F18) — `test_projects/{fixed,elastic}/teardown.sh`
Tear down the dev-side projinfra **before** clearing `infra/output`. Order:
env-tier down → (elastic) AWS env+project destroy + state-backend/SSM cleanup →
`./bin/docex projinfra down development` (while the compose file still exists) →
clear `infra/output`. With Step 1, the `-web` networks now get removed too.

### 5b. verify_clean underscore coverage (F15) — `test_projects/elastic/verify_clean.sh`
Where it greps/queries by the hyphenated project prefix, also check the
**underscored** form for IAM roles, SSM parameters, and DynamoDB tables (and any
other underscored resource type). An orphaned `docex_smoke_elastic_*` must be
reported, not hidden.

### 5c. Stage-test TLS (F7) — `test_projects/fixed/infra/stage/tests/test_smoke.py`
Remove `httpx.Client(verify=False, ...)` → default (verifying) client, and drop
the stale mod-036 comment. Check `test_projects/elastic/infra/stage/tests/` and
align (it terminates at ACM; it should verify too).

### Step 5 validation
Smoke-only shells — validated by the re-walk (Cluster's "Cut shape" in
overview): teardown leaves dev-side clean, `verify_clean` green incl. a direct
underscored-IAM query, `stagetest` passes over verified TLS.

---

## Step 6 — Checklist (Cluster 5; F1, F2, F8) — `test_projects/PRE_CUT_CHECKLIST.md`

- **F1:** A.3.1 — remove the `TRAEFIK_DNS_PROVIDER` prerequisite; state fixed
  certs use HTTP-01.
- **F2 (locked: document optional):** note `TRAEFIK_ACME_EMAIL` is optional —
  LE registers without a contact email; setting it only enables expiry-reminder
  emails, and threading it through docex is a deferred future option. Remove it
  from the hard prerequisites.
- **F8:** C.6/D.8 — document that `check`/`merge` require a **feature branch**
  (main at the prior release, the new version on a feature branch), and note the
  C.1/C.2 ordering (compile must run before `projinfra up`, since `projinfra up`
  reads the compiled project compose file).

---

## Step 7 — F16 investigation (Cluster 6; investigate ONLY)

Decision locked: characterize, do not fix this mod. On elastic rollback the web
ECS task sat `PENDING` ~10–12 min before `RUNNING` while the worker rolled in
seconds. Investigate likely causes and write findings to
`plans/modifications/053_pre_cut_polish/f16_investigation.md`:
- the web task's `dependsOn` otelcol `HEALTHY` gate (emit/hcl.py task def),
- Service Connect / Envoy injection startup,
- ENI attachment latency, ALB target draining under `minimumHealthyPercent=100`.
Use the next elastic re-walk (or ECS task event timestamps / CloudWatch) to
locate where the time goes. Output: a short root-cause note + a
fix-vs-document recommendation for a follow-up decision. **Do not change
behavior** based on it in this mod unless the cause is trivially and safely a
docex-emitted defect — in which case flag it for the design-context review
before acting.

---

## Step 8 — Finish

1. `pytest` green; `pytest -m integration` green where a docker daemon is
   available (note any skipped for lack of daemon).
2. Leave `pyproject.toml` / `src/docex/__init__.py` at the working-tree `1.1.0`
   (already bumped for the candidate image) — the **cut** formalizes version +
   CHANGELOG; not this mod.
3. Do NOT update `CHANGELOG.md`'s `[Unreleased]` beyond what the campaign needs —
   add 053's bullets under the existing `[Unreleased]` (the cut dates it). Match
   the 049–052 bullet style.
4. Report what changed per file so the design-context agent can review for drift
   (per `modifications.md` step 5) and drive the re-walk.
