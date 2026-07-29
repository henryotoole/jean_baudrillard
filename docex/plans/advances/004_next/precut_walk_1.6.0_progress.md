# 1.6.0 Pre-Cut Walk — Progress and Handoff

State of the [`PRE_CUT_CHECKLIST`](../../../test_projects/PRE_CUT_CHECKLIST.md)
walk for the **1.6.0 service-process-types** cut, written at the handoff point
between the fixed-foundation walk (complete) and the elastic walk (not started).

**Status: fixed foundation ✅ complete and torn down clean. Elastic ❌ not
started. The cut is NOT yet safe to perform** — `PRE_CUT_CHECKLIST § E` requires
both walks green.

---

## What is done

| Section | Result |
| ------- | ------ |
| `docex:1.6.0` image | **built** locally; `./bin/docex --version` → `docex 1.6.0` from inside the container |
| `pytest tests/unit` | **983 passed** |
| `pytest -m integration` | **17 passed** (started at 7 failed / 9 passed / 1 skipped — see [Defects found](#defects-found-and-fixed)) |
| A. Prerequisites | satisfied; several checklist claims found stale (see [Checklist corrections](#checklist-corrections-owed)) |
| B. Conformance audit | key mechanical items verified (core parity, entrypoints, no activation in `root.py`, contracts, `cicl_version: "2"`, `domain_default_process`) |
| **C.1–C.11 fixed walk** | **all green**, `verify_clean.sh` → clean, zero remnants |
| D. elastic walk | **not started** |

### The two things only this walk covers — both now proven on fixed

1. **Scheduler end-to-end** (`§ B` note 1). `docex test` produced
   `reaper-exec-run-… → 3 passed`: a scheduler-only codebase running its tests
   **through the exec service**, which is Mod 103's deletion of
   `_run_scheduler_tests` validated by real execution. `reaper-prune-scheduler`
   came up in dev, stage, and prod.
2. **The fixed replica unroll** (`§ C.9`). Live and verified:
   - two containers `…-prod-api-worker-1` / `-2`, both `(healthy)`
   - one otelcol sidecar each, netns-paired
   - both carrying the shared alias `docex-smoke-fixed-prod-api-worker`
   - `POST /pings` → 201 → `processed_at` set, and **worker-1 consumed it while
     worker-2 did not** — independent consumers, no double-processing
   - the unroll survived a `rollback` and came back healthy

`replicas` had been declared, documented, and read by no emitter for its entire
existence. C.9 is the only thing anywhere that executes the multi-service form.

### Other confirmations worth keeping

- **One image, two process types**: `registry.luxrnd.tech/docex_smoke_fixed/api:0.0.15`
  on both `api-web` and `api-worker`. Registry has `api` + `reaper` at `0.0.15`;
  the legacy `web`/`worker` repos have **no** `0.0.15` tag. No third repo.
- **`docex check`: all 10 gates pass**, including `contracts_exist — 2 contract(s)`,
  which is the first time Mod 101's **asyncapi** branch has ever executed, and
  `health_endpoints` asserting the `/health/<svc>/<proc>` fan-out.
- **One migration per codebase**: ansible ran a single `TASK [Run migrations for api]`;
  dev/test migrate went through `api-exec-run-…`.
- **Three prod URLs all 200 with matching version** — canonical two-segment
  (`api-web.prod.…`), bare-env via `domain_default_process`, and bare-project.
- **Fan-out `/health/api/worker` → 200**, and it correctly returned **503** while
  the worker was down. The loop-liveness rule works in both directions.
- **SIGTERM handling** in the seed worker: `caught signal 15, stopping after
  current iteration` → `stopped` (Mod 103's main-thread loop).
- `rollback prod 0.0.15` → migrations skipped, all URLs reverted, data preserved;
  `--dry-run` exits 0 with no mutation.

---

## Defects found and fixed

Committed as `c9ededc` ("pre-cut repair").

1. **All four test fixtures declared `command: ["python", "/service/dist/root.py"]`
   — a file no fixture has ever contained.** `build.sh` copies `src/`→`dist/`,
   where the module is `app.py`. Mod 096 made `command:` mandatory and reached for
   the doctrine's composition-root filename instead of the fixture's real entry
   module. Every fixture container crash-looped and its netns-paired sidecar
   could not attach. **Invisible to 983 unit tests** — they only *compile*
   fixtures; nothing runs one — and integration was `--collect-only` for the
   whole advance.
2. **Two integration tests asserted the pre-advance one-segment identity.**
   `test_up_down_real` matched `endswith("api")`; `test_stagetest_real` built
   `{seg}-dev-api`. Compose keys are now per process type, so the name is
   `sample-dev-api-web` and `sample-dev-api` names nothing. This is exactly the
   debt every corporal from Mod 099 on flagged as "goes blind".

---

## Traps that will bite the elastic walk

Ordered by how much time they cost me.

### 1. A fresh codebase cannot start in `dev` until `docex build` runs

The dev compose bind-mounts `./core/<svc>/dist:/service/dist`, so `/service/dist`
is the **host's** directory, which **shadows** whatever `docker build` put in the
image. Mod 107 created a brand-new `api` codebase, so its host `dist/` still held
the *old* `web` codebase's `root.py` and `hex/` — no `entrypoints/`. Result:
`api-web` and `api-worker` crash-loop with
`python: can't open file '/service/dist/entrypoints/web.py'`.

**Fix: run `./bin/docex build` before (or after a failed) `envinfra up dev`.**
`docex build` only requires *some* service in the stack to be running, and
backing services come up fine, so it works from the failed state.

**The elastic project has the same new `api` codebase and will hit this at D.6.**
It does *not* affect stage/prod on elastic (images come from ECR; no bind mount).

### 2. `docex build` cannot recover from root-owned files in `dist/`

26 root-owned `__pycache__` dirs, written by a container running as root in an
earlier walk, made the dist-wipe step die with
`PermissionError: [Errno 13] ... dist/hex/pings/ports/driving/__pycache__`.
The shim runs docex as the host uid, so it can *never* delete them.

**Fix:** `sudo find core -name __pycache__ -type d -prune -exec rm -rf {} +`

Check the elastic project for the same before D.6. This is a genuine docex
robustness gap, not advance-caused — worth filing.

### 3. Disk fills fast, and the biggest consumer is invisible

Hit `no space left on device` **twice** — once breaking `tofu init` (which made
three `test_hcl_validate_real` tests fail for reasons that looked like invalid
HCL), once breaking the stage release's image extraction.

- **`/tmp/pytest-of-ubuntu` reached 30 GB** across five integration runs — each
  test downloads a ~600 MB tofu provider into its own tmpdir. Delete it between
  runs. This was ~85% of the problem.
- Docker build cache regrows to 20 GB+; `docker builder prune -af` is safe.
- Old `docex:*` images are safe to remove — `docex_process.md` states the
  determinism promise rests on rebuilding from the `v<v>` git tag, not on
  keeping the image. Keep the current release and the candidate.
- **Do NOT `docker volume prune`.** 86 volumes, only 9 active; the "reclaimable"
  16 GB includes `field-radio`'s and `transcript-archive`'s database data.
- The elastic walk pulls more tofu providers and provisions RDS/ECS; **check
  `df -h /` before D.3 and before D.9.**

### 4. Docker address pools were exhausted; now widened

`/etc/docker/daemon.json` **did not exist**; docker's defaults gave ~32 networks
and 28 were allocated across four projects. The next `172.x` slot is the host's
own VPC (`172.31.0.0/16`), which docker correctly refuses. Now:

```json
{ "default-address-pools": [
    { "base": "172.16.0.0/12",  "size": 16 },
    { "base": "192.168.0.0/16", "size": 20 },
    { "base": "10.128.0.0/12",  "size": 24 } ] }
```

4096 extra networks, verified allocating (`10.128.1.0/24`). **Clear of the master
VPC's `10.20.0.0/16`**, which matters for the elastic walk. Required a daemon
restart (operator authorized; the other projects recovered via restart policy).

### 5. `containerize` must run from `main` — the checklist omits `merge`

`C.6`/`D.8` list `check` then `containerize`, but `containerize` refuses off
`main`. The real chain is **`check` (on the feature branch) → `merge` → `containerize`**.

Also: **`merge` prints `error: failed to push some refs` while still exiting 0**
when the feature branch was never pushed to origin (it tries to delete the remote
branch). Alarming, harmless.

### 6. Restart backoff makes logs look stale

After fixing the `dist/` problem the worker kept logging the *old* error, which
looked like the bind mount not propagating. It was docker's exponential restart
backoff — attempt gaps of 14s → 27s → 52s, so every logged line predated the fix.
**Read log timestamps against the fix time** (`docker logs -t`), or force
`docker restart` to get a decisive answer.

### 7. ACME races the first probe

Both dev and stage returned traefik's `404 page not found` on the first curl, then
200 seconds later once HTTP-01 issued. Don't diagnose a 404 immediately after
`envinfra up` / `release`; re-probe. Also **`curl -I` returns 405** — the seed app
only implements GET.

---

## Elastic-walk-specific state

### Git — the elastic project needs the same restructure the fixed one got

Current: branch **`smoke-walk-1.6.0`**, `version: "0.0.15"`, `origin/main` at
**`v0.0.14`**, tree clean, Mod 107's migration committed on the branch.
That is already the shape `check` wants. The sequence from here is
`compile → check → merge → containerize` (see trap 5).

The fixed project finished at `main` / `v0.0.16` (it needed a second version for
the C.10 rollback walk; do the same at D.12).

### DNS — created, and one leftover to clean

13 A-records added to `luxrnd.tech` (zone **`Z05249222MUE7QVI7SG0I`**) →
**`3.214.203.31`**, TTL 60. Four are the elastic dev/test out-of-band records
`{dev,test}` and `*.{dev,test}.docex-smoke-elastic.luxrnd.tech` that
`preinfra development` requires (A.4.2). Nine are the fixed project's and can be
removed now that its walk is done.

**Note the per-env wildcards already cover the new two-segment hostnames**
(`api-web.dev.…`), because the process segment shares the service's DNS label.
`A.4.1` says this explicitly; `upgrade_1.6.0.md` tells downstream projects the
opposite, and both are right — those projects hold per-host records, these hold
wildcards.

**Leftover from a prior walk:** hosted zone **`docex-smoke-elastic-stage.`**
(`/hostedzone/Z00031833M2SHLRRAE294`, 2 records, ~$0.50/mo). Bare zone name with
no parent suffix — an old-docex artifact. `verify_clean` checks the child *zone*,
so this one slipped through. Worth deleting.

D.3's NS delegation is manual: phase 1 prints the four NS hostnames; create an
`NS` record at `docex-smoke-elastic.luxrnd.tech` in zone `Z05249222MUE7QVI7SG0I`,
wait for `dig NS docex-smoke-elastic.luxrnd.tech @1.1.1.1`, then re-run phase 2.

### AWS

Account **`256071447730`**, creds via the EC2 instance role (`dev-instance-role`)
— there is **no `~/.aws/credentials`**; `~/.aws` holds `config` + `sso` only. The
shim mounts `~/.aws:ro` and in-container AWS calls worked throughout, so this is
fine, but don't be alarmed by the missing file.

Master VPC **`vpc-07e85ecd250b5af29`** `10.20.0.0/16`, 4 subnets
(`us-east-1a`/`1b` × public/private, `tier` tagged), NAT
`nat-07e5c78da3ce46ce3` **available** in the `1a` public subnet.

---

## Checklist corrections owed

Found while walking; **none blocked progress**, all should be fixed in
`PRE_CUT_CHECKLIST.md`.

1. **A.3.2 names the wrong tags.** It says the master VPC carries
   `Name=docex-master-vpc` and `managed_by=docex-preinfra`. Reality —
   and the `cicl.md § Elastic Foundation` preinfra convention — is
   `Name=master_network_VPC`, `managed_by=doctrine-operator`,
   `shape_name=master_network`, `infra_tier=prerequisite`. The infrastructure is
   right; the checklist is stale.
2. **C.6 / D.8 omit `docex merge`** between `check` and `containerize` (trap 5).
3. **A.1 says `~/.aws/credentials` must be present.** It isn't, and doesn't need
   to be — an instance role works.
4. Mod 106's note stands: `§ C.9`'s prod sidecar count is a **sum** over
   non-scheduler process types × their replicas, not a product.

---

## Resumable state

- Working tree: the advance's 30 commits plus `c9ededc` (pre-cut repair) and the
  test-project catchups are on `main`.
- **Not done:** no `v1.6.0` git tag, no image published anywhere, elastic walk
  untouched. `VERSION`/`pyproject`/`__init__`/`plugin.json` are all at `1.6.0`.
- Fixed project torn down; `verify_clean.sh` green; no AWS resources created by
  the fixed walk.
- Open items for the cut remain in
  [`service_processes_implementation_plan.md § Flagged for operator`](./service_processes_implementation_plan.md#flagged-for-operator)
  — the headline being that **no `queue` backing role exists**, so 1.6.0 ships a
  first-class `worker` with nothing first-class for it to consume.
