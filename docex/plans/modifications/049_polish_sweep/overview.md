# Mod 049 — Polish Sweep (Gaps C, J, K)

Patch mod bundling three small, low-risk, **docex-source-only** items from the post-shape-overhaul gap roadmap ([`plans/advances/post_shape_overhaul.md`](../../advances/post_shape_overhaul.md)). None touch the doctrine; none require a smoke walk. This is the warm-up cut of the post-1.0.0 polish advance — the doctrine-and-walk-heavy minors (050–052) follow.

The three:

- **Gap C** — `docex merge` hard-fails on a repo with no `origin` remote.
- **Gap J** — display strings still print the raw underscored project name for resources whose real names are hyphenated.
- **Gap K** — `docex envinfra up dev` leaves a partial bring-up with no readable diagnostic.

Cut shape: patch, **1.0.3 → 1.0.4**. Per [`docex_process.md § Lifecycle`](../../core/docex_process.md), patch cuts skip the test-project smoke walk; unit tests carry the proof.

---

## Gap C — `docex merge` requires `origin`

**Symptom:** `docex merge` exits non-zero with `fatal: 'origin' does not appear to be a git repository` on any inner repo with no remote configured. The test projects under `test_projects/` deliberately have no remote (per `test_projects.md`), so the smoke walker does the rebase + tag by hand (`git checkout main && git merge --ff-only <feature> && git tag v<version>`).

**Root cause:** `src/docex/pipeline/merge.py` already distinguishes a *third* state — `empty_origin` (origin exists but `origin/main` ref doesn't, lines 64–84) — and seeds main from the feature tip in that case. But two steps still assume a remote is present unconditionally:

- Step 3 (line 59): `git.fetch(project_root, remote="origin")` — hard-fails when there is no `origin` remote at all.
- Step 6 (line 122): `git.push(project_root, remote="origin", refs=[...])` — same.

So the *missing-origin* case (distinct from empty-`origin/main`) falls through to the step-3 fetch failure and never reaches the rebase/tag.

**Fix:** Add a no-remote detection at the top of step 3 (a new `GitClient.remote_exists(project_root, "origin")`, implemented via `git remote get-url origin` exit code). When origin is absent:

1. Skip the fetch (step 3).
2. Rebase the feature branch onto **local `main`** (not `origin/main`) — then fast-forward main + tag, exactly as the remote path does but against the local trunk. This matches the walker's manual `merge --ff-only` and preserves a real local integration.
3. Skip the push (step 6) and the remote feature-branch delete (step 7); the local branch delete still runs.
4. Log one line: `merge: no 'origin' remote — performing local merge only (no fetch/push).`

**Design note for review — rebase target.** The advance's one-liner said "skip fetch/push, still perform the local rebase + tag." The accurate behavior depends on local-`main` existence:
- Local `main` exists (the test-project case — they sit on `main` with the version tagged at HEAD): rebase feature onto local `main`, ff, tag. This is the proposed default.
- Local `main` absent: fall through to the existing `empty_origin` seed path (ff a fresh `main` to the feature tip).

The proposed implementation collapses these by reusing the existing seed branch when `main` doesn't exist and rebasing onto local `main` when it does — so the no-remote path shares machinery with `empty_origin` rather than duplicating it.

---

## Gap J — Display strings still use raw `${project}` for hyphenated resources

**Symptom:** `docex bootstrap` (the `projinfra up production` path on elastic) prints `bootstrap: Route53 hosted zone for 'docex_smoke_elastic.luxrnd.tech' created.` — but the actual zone is `docex-smoke-elastic.luxrnd.tech` (mod 046 hyphenated the *emit*; the *print* still uses the raw name). Reading docex output then `aws route53 list-hosted-zones` shows a confusing name mismatch.

**Root cause:** Mod 046 introduced `compiled.project_dns_label` (the hyphenated, lowercased project segment) and swept the *emit* sites onto it — `emit/compose.py` uses it throughout. But the *display/log* statements weren't swept. Confirmed exemplar in `src/docex/pipeline/bootstrap.py`:

- Line 111: `project = ctx.project.name` (raw, underscored).
- Line 178: `project_subdomain = f"{project}.{apex_domain}"` — built from the raw name.
- Line 181: `print(f"bootstrap: Route53 hosted zone for {project_subdomain!r} created.")` — prints the underscored form.

**Fix:** Form any display string that names a **DNS / docker / ECS / registry** resource from the DNS-labeled project segment, not the raw `ctx.project.name`. Concretely:

1. In `bootstrap.py`, derive the subdomain from the dns-label form (the same `replace("_","-").lower()` rule `naming.py:128` already encodes; prefer routing it through a single shared helper rather than re-inlining).
2. Sweep the rest of `src/docex/` for the same class of leak: `grep -rn` for display/log statements that interpolate `ctx.project.name` (or a `project` local bound to it) while naming a hyphenated resource. The advance names `__main__.py` and `bootstrap.py` as suspects.

**Scope boundary — leave correct uses alone.** Where a message refers to the **project itself** (its machine name, which legitimately *is* underscored — e.g. `bootstrap.py:165` `project {project!r} fully bootstrapped`), the raw name is correct and stays. The fix targets only strings naming a *resource* whose emitted name is hyphenated. Inert record-key identifiers (IAM, SSM, DDB) keep underscores per their naming policies, so their display strings are likewise left raw.

---

## Gap K — `docex envinfra up dev` doesn't surface a partial bring-up

**Symptom:** When something fails mid-`envinfra up dev` (a healthcheck that never goes healthy, a missing env var, a bind-mount permission error), the stack is left partial — some containers up, some restart-looping. `run_up` exits non-zero but prints no per-service diagnosis; the walker has to `docker logs <svc>` each container to find the cause.

**Root cause:** `src/docex/orchestrate/up.py::run_up` runs `compose_up` then immediately attempts migrations (`compose_exec`). On failure it surfaces only the raw compose/exec exit code — no inspection of which core service is unhealthy or why.

**Fix:** After `compose_up` (and before / on failure of migrations), inspect each core service's container state via a new `DockerClient` query (`compose ps --format json` or `inspect`). For any service that is `restarting` or `unhealthy`, print one diagnostic line per service mapping the common causes:
- `restarting` → "container is restart-looping; check `docker logs <name>` — common causes: missing env var, crash on startup."
- `unhealthy` → "healthcheck never passed; verify the healthcheck endpoint/tooling (see Gap I — curl-based checks need curl in the image)."

Diagnosis only — **no auto-fix, no auto-teardown** (consistent with `up.py`'s existing "a half-up stack is what the developer needs to debug" contract).

**Narrowed scope (observation):** `up.py` already carries `_ensure_initial_dev_build`, which proactively populates an empty `dist/` before bring-up — so the **empty-`dist/`** trigger the advance lists as Gap K's commonest case is *already* handled for `dev`. Gap K's diagnostic therefore now covers the residual failure modes (unhealthy/never-healthy, missing env var, bind-mount perms), not empty-dist.

---

## Observation — possible roadmap drift on Gap D (not actioned here)

While grounding Gap K, I found that `up.py::_ensure_initial_dev_build` already implements **Gap D's** "path 1" fix (detect empty `dist/`, populate via a no-bind-mount ephemeral build-stage container) and it is **committed**, not working-tree dirt. The advance still lists Gap D as *open* (slated for Mod 050). This looks like roadmap drift — Gap D's core may already be closed.

Not touched in this mod (Gap D is Mod 050's concern). Flagging so Mod 050's scope can be re-confirmed against the live code before it opens — its remaining surface may be only the residual edge cases (root-owned `dist/`, the `Restarting`-state `docex build` refusal) rather than the whole gap.

---

## What lands in this mod

| Change | File(s) |
| ------ | ------- |
| `GitClient.remote_exists` + no-remote path in `run_merge` (skip fetch/push, rebase onto local `main`) | `src/docex/git/client.py`, `src/docex/pipeline/merge.py` |
| Display-string sweep onto the dns-label form | `src/docex/pipeline/bootstrap.py` (+ any sites the sweep finds) |
| Post-bring-up health diagnostic | `src/docex/orchestrate/up.py`, `src/docex/docker/client.py` (container-state query) |
| Mod-049 design + impl docs (this folder) | `plans/modifications/049_polish_sweep/` |
| CHANGELOG entry + version bump (1.0.3 → 1.0.4) | `CHANGELOG.md`, `pyproject.toml`, `src/docex/__init__.py` |

Tests (per `docex_process.md` — unit by default; integration only where a real boundary is crossed):
- Gap C: unit test `run_merge` against a no-remote repo (the git boundary is real → a small integration-style test using a tmp `git init` repo with no remote is appropriate).
- Gap J: unit test that the bootstrap subdomain display string is hyphenated for an underscored project name.
- Gap K: unit test that `run_up` emits the per-service diagnostic when a (mocked) `DockerClient` reports a service `unhealthy`/`restarting`.

## Cut shape

Patch cut: docex **1.0.4**. No doctrine changes, no transfer-table changes, no smoke walk. The five-artifact-alignment check still applies, but only the `src/**` ↔ `tests/**` ↔ `docex/plans` layers move; `doctrine/**` and `tables/**` are untouched.
