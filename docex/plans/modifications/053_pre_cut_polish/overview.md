# Mod 053 — Pre-Cut Polish (1.1.0 smoke-walk findings)

The `1.1.0` candidate (mods 049–052) was walked through both smoke-test
projects per [`PRE_CUT_CHECKLIST.md`](../../../test_projects/PRE_CUT_CHECKLIST.md)
against real infrastructure. **Both walks passed functionally** — every
`docex` command produced working infrastructure, and all five campaign gaps
(A HTTP-01 certs, B project-scoped traefik, C no-origin merge, E CloudWatch
logs incl. the migrate stream, I curl gate) verified. This mod folds in the
ergonomic/robustness findings the walk surfaced so the `1.1.0` cut can proceed
clean. No finding produced broken infrastructure; the fixes are correctness,
cleanup, and UX.

The findings are labelled `F1`–`F18` to match the smoke-walk report.

## Doctrine status across this mod

**No doctrine prose changes.** Every fix lands in `docex` code, the
test-project seeds (`test_projects/`), or the checklist — all `docex`-repo
artifacts. Two items were checked specifically:

- **F1** (`TRAEFIK_DNS_PROVIDER`) appears *only* in `PRE_CUT_CHECKLIST.md`; the
  doctrine (`fixed_reverse_proxy.md`) already describes HTTP-01. Checklist-only.
- **Acme volume name** — `fixed_reverse_proxy.md` already states the volume is
  named `${project_name}-traefik-acme` (it tells operators to
  `docker volume rm ${project}-traefik-acme`). Today's emit declares the volume
  *without* an explicit `name:`, so Compose prefixes it (`infra_…`) and reality
  diverges from the doctrine. The fix makes the emit honor the name the doctrine
  *already* prescribes — so it's a code change that removes drift, not a doctrine
  edit.

If implementation uncovers a genuine doctrine gap, stop and raise it before
editing any doctrine file (per `docex_process.md`).

---

## Cluster 1 — Compose project identity (F11, F12, F18-networks, volume drift)

**The core finding.** docex never passes an explicit `--project-name` to
`docker compose`; it lets Compose derive the name from the basename of
`--project-directory`. `subprocess_client.py:_resolve_project_dir` computes that
directory as `compose_file.parent.parent.parent.parent` ("up 4 levels"), which
is correct for **env-tier** files (`infra/output/<env>/…` → `<project_root>`,
basename = project name) but **off-by-one for project-tier** files, which are
nested one level deeper:

```
<root>/infra/output/project/development/docker-compose.yml
        ^4     ^3      ^2       ^1
up 4 →  <root>/infra      → Compose project name "infra"
```

So every project's projinfra stack runs under the generic, non-project-scoped
name **`infra`**. Because Compose tracks resources by the
`com.docker.compose.project` label, a name that is wrong (not the project), not
project-scoped (collides across projects on a shared dev host), and unstable
across docex versions (observed acme volumes prefixed both `infra_` *and*
`elastic-projinfra_`) breaks Compose's adopt-on-rerun logic. Consequences:

- **F11** — `projinfra up development` aborts with a Docker *name conflict* when
  the project traefik (fixed `container_name`) already exists from a prior
  run/version whose project label doesn't match → not idempotent (doctrine
  promises idempotency). Manual `docker rm -f` was the only way forward.
- **F12** — `projinfra down development` removes the traefik but leaves the four
  `-web` networks (their project label ≠ "infra"), plus emits
  `network … not created for project infra / set external: true` warnings on
  every `up`.
- **Volume drift** — the acme volume's real name is `<derived>_…-traefik-acme`,
  not the doctrine's `${project}-traefik-acme`.

### Fix (docex code)

1. **Pass an explicit, stable `--project-name`** on every projinfra/env compose
   invocation, project-scoped and version-stable:
   - project-tier: `${project_dns_label}-projinfra-${side}`
   - env-tier: `${project_dns_label}-${env}` (keep current effective scoping but
     make it explicit rather than path-derived).
   `_compose_base` grows a `project_name` parameter; callers pass it. This makes
   labels/adoption deterministic and fixes F11/F12 outright (Compose now
   recognizes its own resources on re-run and removes them on `down`).
2. **Fix `_resolve_project_dir`** so `--project-directory` resolves to the true
   `<project_root>` for *both* tiers. Prefer deriving the root robustly (the
   caller already holds `ProjectContext.project_root`) over counting parents,
   which is fragile to layout depth. `--project-directory` and `--project-name`
   become independent inputs rather than one being a side effect of the other.
3. **Declare the acme volume with an explicit `name:`** in the project compose
   emit (`emit/compose.py`) so its real name is exactly
   `${project_dns_label}-traefik-acme`, matching the doctrine. (Networks already
   carry explicit `name:`; the volume should too.)

### Tests

- Unit: `_resolve_project_dir` returns `<root>` for both an env-tier and a
  project-tier compose path; assert the off-by-one is gone.
- Unit: `_compose_base` includes `--project-name <expected>` for env and
  project tiers.
- Unit (emit): the project compose YAML declares the acme volume with explicit
  `name: ${project_dns_label}-traefik-acme`.
- Integration (docker-marked): `projinfra up development` twice in a row is a
  no-op the second time (idempotent); `projinfra down development` removes the
  traefik **and** all four `-web` networks; no `not created for project` warning.

---

## Cluster 2 — Elastic teardown + verify_clean completeness (F15, F18-teardown)

- **F18 (teardown)** — the elastic `teardown.sh` clears `infra/output` (and
  focuses on AWS) but never brings the **local dev-side projinfra** down, so the
  dev traefik + `-web` networks are orphaned; a later `projinfra down
  development` no-ops because the compose file is already gone. (This is how the
  24h-stale traefik that triggered F11 accumulated.)
- **F15 (verify_clean)** — `verify_clean.sh` searches the **hyphenated** project
  prefix, so it misses **underscored** AWS resources (IAM roles, SSM params,
  DynamoDB tables). A prior walk's orphaned `docex_smoke_elastic_task_execution`
  IAM role was reported "clean", then blocked this walk's projinfra phase-2 with
  `EntityAlreadyExists`. verify_clean's blind spot *masked* the orphan.

### Fix (test-project seed)

1. `teardown.sh` (both foundations): tear down the dev-side projinfra
   (`projinfra down development`) **before** clearing `infra/output`, so the
   compose file still exists. With Cluster 1's fix the `-web` networks also get
   removed. Order: env-tier down → (elastic) AWS env+project destroy → projinfra
   down development → clear output.
2. `verify_clean.sh` (elastic): check **both** the hyphenated and underscored
   project prefixes for IAM / SSM / DDB (and anywhere else underscored names are
   used), so an orphaned underscored resource is reported, not hidden.

### Tests

- These are smoke-only shell wrappers (no docex unit surface). Validation is the
  re-walk: after teardown, `verify_clean.sh` is green *and* a direct AWS query
  for the underscored IAM role name returns empty; the dev-side traefik +
  networks are gone.

---

## Cluster 3 — Elastic projinfra UX (F13, F14)

- **F14** — when phase-2 `tofu apply` fails for *any* reason, docex prints a
  generic "Most common cause: the parent zone has not been NS-delegated …" and
  "re-run `docex bootstrap`". During the walk the real error was the IAM
  conflict; the canned NS message misdirected debugging.
- **F13** — phase-1 and phase-2 messages tell the operator to "re-run
  `docex bootstrap`", a stale command name; the command is now
  `docex projinfra up production`.

### Fix (docex code, `pipeline/projinfra.py` + bootstrap helper)

1. Surface the **actual** `tofu apply` stderr on phase-2 failure. Keep the NS
   hint, but as a *secondary* "if the error above mentions ACM/validation,
   the most likely cause is NS delegation" — not the headline.
2. Replace "re-run `docex bootstrap`" with "re-run
   `./bin/docex projinfra up production`" in all projinfra display strings.

### Tests

- Unit: the phase-2 failure path includes the captured tofu error text in its
  message; the NS hint is present but not the sole content.
- Unit/grep: no user-facing projinfra string says "docex bootstrap".

---

## Cluster 4 — Seed stage-test TLS verification (F7)

- **F7** — the fixed stage test still uses `httpx.Client(verify=False)`
  (`test_projects/fixed/infra/stage/tests/test_smoke.py:37`) with a comment
  referencing the old mod-036 DNS-01 behavior. Gap A (mod 051) made HTTP-01 real
  certs work; the handoff said to remove it. Real-cert HTTPS was confirmed
  working independently during the walk, so the seed bypassing verification is
  pure debt.

### Fix (test-project seed)

Drop `verify=False` (and its comment) in the fixed stage test; let httpx verify
the real LE cert. (Elastic already terminates at ACM; confirm its stage test
also verifies — align both.)

### Tests

- Re-walk: `docex stagetest` passes for fixed over verified TLS.

---

## Cluster 5 — Cosmetic / doc (F1, F2, F3, F6, F8, F17)

Low-severity; batched. Each is independent and safe.

| ID | Where | Fix |
| -- | ----- | --- |
| **F1** | `PRE_CUT_CHECKLIST.md` A.3.1 | Remove the `TRAEFIK_DNS_PROVIDER` prerequisite; clarify fixed certs are HTTP-01 and the ACME email is optional (see F2). |
| **F2** | checklist + (maybe) shim | LE registers fine with no contact email, and `TRAEFIK_ACME_EMAIL` can't currently be threaded (shim forwards no env; projinfra `compose_up` passes no env-file). **Decision point below.** |
| **F3** | shim or projinfra ssh opts | `preinfra production` (fixed) prints "Failed to add the host to the list of known_hosts" because `~/.ssh` is mounted read-only. Quiet it with `-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new` on docex's own ssh probe, or a writable known_hosts. |
| **F6** | shim | `release` (fixed) warns "Failed to create `/home/ubuntu/.ansible`". The shim already `mkdir`s `~/.docker`; add `~/.ansible` (or set `ANSIBLE_HOME` to a writable path). |
| **F8** | `PRE_CUT_CHECKLIST.md` C.6/D.8 | Document that `check`/`merge` require a **feature branch** — the walk needs main at the prior release and the new version on a feature branch (the restructure I did by hand). Also note compile must precede `projinfra up` (C.1/C.2 ordering). |
| **F17** | `cicl/compile.py` (or the caller) | The "resources rounded to Fargate tier" note prints 4× per `docex` command (once per internal compile invocation). Emit it once per compile run. |

### F2 — decision point (needs your call)

Gap A intentionally removed DNS-provider creds and made fixed certs "just work".
The LE *contact email* is optional — issuance succeeded with it empty all walk.
Options:

- **(A) Document optional (recommended).** Treat `TRAEFIK_ACME_EMAIL` as
  optional, drop it from the checklist prerequisites, and note LE registers
  without contact (no expiry-reminder emails). Zero code; simplest.
- **(B) Thread it.** Add `TRAEFIK_ACME_EMAIL` to a small shim env-passthrough
  allowlist so an operator who sets it gets LE expiry notifications. Touches the
  "permanent" shim — deliberate, but small.

Recommendation: **(A)**, with a one-line note that (B) is a future option if a
project wants LE notifications.

**Decision (operator, locked):** Option **(A)** — document optional, no code.
Leave a note that we'll revisit threading (B) one day.

---

## Cluster 6 — Slow elastic rollback web task (F16) — investigate, then classify

On elastic rollback, the **worker** task rolled to the target version in
seconds, but the **web** task sat `PENDING` ~10–12 min before reaching
`RUNNING` (it *did* converge; `/health` then reported the rolled-back version).
Root cause not yet isolated — candidates: the web task's `dependsOn` otelcol
HEALTHY gate, Service Connect/Envoy injection startup, ENI attachment, or ALB
target draining under `minimumHealthyPercent=100`.

**Plan:** investigate during implementation. If it's a docex-emitted task-def
shape issue (e.g. an over-strict health gate or a dependency ordering we
control), fix it. If it's AWS-side scheduling latency we don't control, document
it as expected rollback-convergence time and close. Keep this *separable* — if
investigation balloons, it can be split to its own follow-up rather than holding
the cut.

**Decision (operator, locked):** investigate only this mod — characterize the
cause and report findings. The fix-vs-document decision is deferred to *after*
we understand it; do not let it block the cut.

---

## What lands in this mod

**docex code:**
- `docker/subprocess_client.py` — `--project-name` param on `_compose_base`/
  callers; `_resolve_project_dir` correct for both tiers.
- `pipeline/projinfra.py` (+ callers) — pass explicit project names; surface real
  tofu error on phase-2 failure; fix stale "docex bootstrap" strings.
- `emit/compose.py` — explicit `name:` on the acme volume.
- `cicl/compile.py` (or caller) — dedupe the Fargate-tier note.
- `bin/docex` shim — `mkdir ~/.ansible`; (F2-B only if chosen) env passthrough;
  ssh known_hosts opts for F3 if done shim-side.
- Tests for each of the above.

**Test-project seed (`test_projects/`):**
- `{fixed,elastic}/teardown.sh` — projinfra-down before clearing output.
- `elastic/verify_clean.sh` — check underscored prefixes too.
- `fixed/infra/stage/tests/test_smoke.py` — drop `verify=False` (align elastic).

**Checklist (`test_projects/PRE_CUT_CHECKLIST.md`):**
- F1 (drop TRAEFIK_DNS_PROVIDER), F2 (optional email), F8 (feature-branch +
  compile-ordering notes).

## Cut shape

This mod is the last before the `1.1.0` cut. After it lands (unit suite green),
re-walk the **affected** steps — most are cheap/local: both `projinfra up/down
development` idempotency, both teardown + verify_clean, fixed `stagetest` over
verified TLS, and (cost) one elastic projinfra→release→rollback→teardown pass to
confirm F14/F15/F16. Then proceed to the cut per
`docex_process.md § Cutting a version` (`[Unreleased]` → `[1.1.0]`, bump
`pyproject.toml` + `__init__.py`, commit, tag `docex-v1.1.0`, rebuild image,
reinstall consumers), and mark the campaign gaps closed on
[`post_shape_overhaul.md`](../../campaigns/post_shape_overhaul.md).
