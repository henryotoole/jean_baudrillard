# Mod 122 — Implementation

Executes the design in [`overview.md`](./overview.md). All four design
questions were ruled by the operator; the rulings are folded into the steps
below and restated where they change what you would otherwise do.

**Read [`overview.md`](./overview.md) first.** It carries the reasoning; this
file carries the edits.

## Ground rules

1. **Both seeds stay byte-identical under `core/`.** Every change to
   `fixed/core/api/tests/**` is applied identically to
   `elastic/core/api/tests/**`. Verify at the end with
   `diff -rq docex/test_projects/{fixed,elastic}/core` — the only permitted
   output is `__pycache__` lines under `dist/`.
2. **Do not touch `docex/src/**` or either seed's `core/api/src/**`.** This mod
   changes tests, two shell scripts, one checklist, and one doctrine file. If
   you find yourself editing product source, stop and report.
3. **Absolute paths.** `$JB` = `/home/ubuntu/.claude/jean_baudrillard`.
4. Do **not** run any `./bin/docex` command, and do **not** run the smoke walk.
   Verification steps 5–7 of the overview are the corporal's, not yours. Your
   verification is step 9 below.

---

## Step 1 — `test_jobs_alogic.py` (new, both seeds)

Create `$JB/docex/test_projects/fixed/core/api/tests/test_jobs_alogic.py` and
the identical file under `elastic/`.

This is the alogic tier: a stub `QueueJobs`, no database, no `root` import, no
`_dsn_from_env`. Model it on `test_clock_smoke.py`, which is the seed's
existing no-database file.

**Module docstring must carry three things:**

- That this is the **alogic tier**, tested with a stubbed driven port per
  `hex_overview.md § Tests` — which is why it touches no database.
- **The rule this mod establishes**, stated plainly: *a test running in the
  `test` env has no sole agency, because `docex test` brings the whole stack up
  (`cicd.md § Build Test Step`) and a live `api.worker` is draining the same
  queue. Assertions that require being the only actor belong here, where the
  collaborator is a stub — not against the live database.*
- That the filename **deliberately** breaks the seed's `…_smoke.py` habit to
  name the tier, and that this is the doctrine's vocabulary winning over a
  local convention in reference material. (Operator ruling, Q4.) Write it as a
  statement of intent so it does not read as an accident.

**Stub:**

```python
class _StubQueue:
    """Stub QueueJobs. Records calls; stores nothing."""
    # enqueue(name) -> UUID, recording ("enqueue", name)
    # claim(limit)  -> a list of Job objects seeded by the test
    # complete(id, at) / fail(id, at, error) -> record the call
```

`Job` is imported from `hex.jobs.domain.job`. `claim` must return real `Job`
instances with `started_at` set, because `JobRunnerService` calls
`job.finish(...)` and the domain refuses to finish a job that never started.

**Tests to write** (each replaces a racing DB-tier assertion — the mapping
matters, so keep the names close to the originals):

| Test | Asserts |
| ---- | ------- |
| `test_run_once_returns_the_number_performed` | Seed 3 claimable jobs; `run_once()` returns exactly 3. `==`, not `>=` — with a stub queue there is no third party, which is the entire reason this moved. |
| `test_prune_pings_dispatches_to_retention` | `prune_pings` calls `ContRetention.prune` exactly once; `heartbeat` does not call it at all. |
| `test_a_failing_handler_records_the_error_and_the_next_job_still_runs` | A raising `_StubRetention`: the `prune_pings` job gets `fail(...)` with the exception text, the following `heartbeat` job still gets `complete(...)`, and `run_once` counts only the successful one. |
| `test_a_name_with_no_handler_is_failed_not_raised` | A job named `no_such_job` gets `fail(...)` carrying `no handler`, `run_once` returns 0, and nothing propagates out. |
| `test_the_clock_defers_and_does_not_work` | `JobService(queue=stub).prune_pings()` performs **exactly one** `enqueue("prune_pings")` and no other call on the queue. This is the race-free replacement for the deleted `started_at is None` assertion — comment it as such, naming `clock.md § The clock defers; it does not work`. |

Reuse the existing `_StubRetention` shape from `test_jobs_smoke.py` (a `prune()`
counting calls, with an optional `raises` flag).

---

## Step 2 — `test_jobs_smoke.py` (rewrite, both seeds)

`$JB/docex/test_projects/{fixed,elastic}/core/api/tests/test_jobs_smoke.py`.

**Delete** these four tests — they moved to Step 1:

- `test_run_once_returns_the_number_performed`
- `test_a_failing_handler_records_the_error_and_the_next_job_still_runs`
- the `retention.calls >= 1` and `_row(job_id)[1] is None` assertions inside
  `test_enqueued_job_is_claimed_performed_and_completed`
- `test_claim_returns_started_jobs`'s `assert job_id in claimed`

**Keep** the file, `_row`, `_drain_until_finished` and `_DRAIN_PASSES`, and
leave exactly two tests:

**`test_an_enqueued_job_reaches_a_finished_row`** (renamed from
`test_enqueued_job_is_claimed_performed_and_completed`)

1. `job_id = JobService(queue=QueueJobsPostgres(dsn=_dsn_from_env())).prune_pings()`
2. Drive an in-process `JobRunnerService` through the existing bounded
   `_drain_until_finished` loop. It already returns early if the row is
   finished, which is now the *expected* outcome when the live worker wins —
   not a failure.
3. Assert on the **row**: `name == "prune_pings"`, `started_at is not None`,
   `finished_at is not None`, `finished_at >= started_at`, `error is None`.

Comment the deletion of the `retention.calls` assertion explicitly: it asserted
**agency** (that *we* performed it) rather than **outcome** (that the deferral
contract held), and the live `api.worker` has a working `prune_pings` handler,
so a job it wins finishes clean and the stub is never called. Point at
`test_jobs_alogic.py::test_prune_pings_dispatches_to_retention` as where that
assertion now lives.

**`test_claim_starts_the_rows_it_returns`** (renamed from
`test_claim_returns_started_jobs`)

1. Enqueue one `heartbeat` through `JobService`.
2. `claimed = queue.claim(limit=32)`. Assert **every** returned `Job` has
   `started_at is not None`. This is the adapter's contract and holds for
   whatever subset we win, including the empty set.
3. Separately, poll the row (bounded, reuse `_DRAIN_PASSES` or a short sleep
   loop ≤30 s) until our enqueued id has `started_at IS NOT NULL` in the table —
   *someone* claimed it. Assert that it does.
4. Keep the existing cleanup: `complete(...)` everything this test claimed, so
   nothing is left started-but-unfinished for the real worker to never drain.

**Module docstring** must be rewritten to name **both** live actors — the clock
*and the worker* — and to state that the file asserts outcomes in shared state,
never agency, with a pointer to `test_jobs_alogic.py` for the agency-shaped
assertions. The current docstring says the tests "tolerate a concurrently-running
`api.clock`", which is the exact half-truth that let this bug through; it must
not survive in that form.

---

## Step 3 — `test_jobs_concurrency.py` (rewrite, both seeds)

`$JB/docex/test_projects/{fixed,elastic}/core/api/tests/test_jobs_concurrency.py`.

Keep the structure: marker name, 40 jobs, two `QueueJobsPostgres` instances in
two threads, `_BATCH = 4`. Change the accounting.

**After both drain threads join**, and **before** any cleanup:

1. **Settle poll (bounded, ≤60 s, ~0.5 s between passes).** Read all 40 marker
   rows. A row is *accounted* if it is in `ours` (the union of what the two
   in-test consumers returned) or has a non-NULL `error`. Loop until every row
   is accounted, or fail with the unaccounted ids.

   Comment why: between our drain returning and this read, a row the live
   worker has claimed but not yet failed is indistinguishable from one of ours
   — `started_at` set, `finished_at` and `error` NULL. A worker that claims and
   never records an outcome is a real defect and must fail this test rather
   than be waited on forever.

2. `worker_claimed` := the marker ids whose row has a non-NULL `error`.

   Comment why this identifies the worker unambiguously: the live
   `api.worker`'s `JobRunnerService` has no handler for `conc_<hex>`, so it
   calls `queue.fail(...)` and stamps
   `error = "no handler for job name 'conc_…'"`. Nothing else in this run
   writes that column — the in-test consumers only `claim`, and only
   `complete` at cleanup. **The read must therefore happen before cleanup**,
   because `complete` sets `error = NULL`.

3. **Assertions** (replacing `set(all_claimed) == enqueued`):

   ```
   claimed[0] and claimed[1] are disjoint          # the original property
   len(ours) == len(set(ours))                     # no id twice within ours
   ours & worker_claimed == set()                  # CROSS-PROCESS exclusivity
   ours | worker_claimed == enqueued               # completeness, restored
   ```

   Give each assertion a message naming what its failure means; keep the
   existing "FOR UPDATE is not holding" wording for the duplicate case.

4. **Cleanup unchanged**: `complete(...)` every id in `ours` plus `strays`.
   Worker-claimed rows are already finished, so `complete`'s
   `WHERE finished_at IS NULL` makes it a no-op on them — say so in a comment
   so nobody adds a redundant filter.

**Module docstring** — rewrite the "What is asserted, and what is not" section:

- The live `api.worker` is a **third claimer**, not interference. Explain the
  observability mechanism (the error stamp) in one sentence.
- State that this is **stronger** than the two-thread form it replaces:
  exclusivity now holds across a separate container on a separate connection
  pool, which is closer to what `SKIP LOCKED` defends against in production
  than two threads in one process were.
- **Keep the existing `SKIP LOCKED` liveness caveat verbatim.** It is still
  true and still the only thing standing between that clause and a plausible
  cleanup.
- Keep the note that the two consumers usually win all 40 (they spin; the
  worker polls at 1 s with `batch_size=8`), so `worker_claimed` is often
  empty — and that this is fine, because the assertions are not conditioned on
  it being non-empty.

---

## Step 4 — `fixed/verify_clean.sh`

`$JB/docex/test_projects/fixed/verify_clean.sh`.

### 4a. The rule, as a comment block

Immediately below the header comment, add — this is an operator-mandated
comment, not optional:

```sh
# THE RULE THIS SCRIPT IS BUILT ON: a check that cannot answer must FAIL,
# not report zero.
#
# Every false green this script has produced came from the same pattern —
# a query that errored (401, 404, unparseable body) was swallowed with
# `|| true` / `|| echo '{}'`, produced an empty result, and was reported as
# "clean". A cleanup check that cannot fail is worse than no check at all,
# because it gets cited as proof. Do NOT add `|| true` to a query path to
# quiet a noisy failure; the noise is the feature.
```

### 4b. Registry credential

Add a helper near the top. The registry is htpasswd-protected
(`container_registry.md § Design`, key choice 1), so every `/v2/` call needs
`Authorization: Basic`. Source it from the operator's `~/.docker/config.json`,
which `PRE_CUT_CHECKLIST.md § A.5` already requires — no new secret store.

```sh
REGISTRY_CURL_CONFIG=""
cleanup_registry_config() { [[ -n "$REGISTRY_CURL_CONFIG" ]] && rm -f "$REGISTRY_CURL_CONFIG"; }
trap cleanup_registry_config EXIT

# WHY the credential goes through a `curl -K` config file and never `-u`:
# `-u` and `-H` both put the credential in argv, where any user on the host
# can read it from `ps`. The config file is mode 600 and removed on exit.
# It must never be echoed, and this script must never be run under `set -x`.
init_registry_auth() {
  local b64
  b64="$(python3 -c "
import json, os, sys
p = os.path.expanduser('~/.docker/config.json')
try:
    auth = json.load(open(p))['auths']['${REGISTRY_HOST}']['auth']
except Exception:
    sys.exit(1)
print(auth)
")" || {
    echo "FAIL: registry credential — no entry for ${REGISTRY_HOST} in ~/.docker/config.json"
    echo "      Resolution: docker login ${REGISTRY_HOST}  (PRE_CUT_CHECKLIST § A.5)"
    return 1
  }
  REGISTRY_CURL_CONFIG="$(mktemp)"
  chmod 600 "$REGISTRY_CURL_CONFIG"
  printf 'header = "Authorization: Basic %s"\n' "$b64" > "$REGISTRY_CURL_CONFIG"
}
```

A missing credential increments `remaining` and is reported as a failure — it
is precisely the case the old script passed.

### 4c. Registry check — enumerate `_catalog`, do not assume the repo list

Replace the whole `for service in api; do … done` block.

**Why (bug 4):** a hardcoded codebase list can only find repos the project
*currently declares*. Repos retired by a rename — `reaper`, `web`, `worker` —
are structurally invisible to it, which is where 26 of the 30 leaked tags sat.
Key the check on what the registry **holds**.

```
GET /v2/_catalog?n=1000   (authenticated)
  → repositories[], filtered to those starting with "${PROJECT_NAME}/"
  → for each, GET /v2/<repo>/tags/list
  → report only repos whose "tags" is a NON-EMPTY list
```

Three things to get right, each with a comment:

1. **`tags: null` is not a leftover.** Verified against the live registry on
   2026-08-06: `docex_smoke_fixed/{api,reaper,web,worker}` all return
   `{"tags": null}`. The Registry V2 API keeps a repository entry after its
   last manifest is deleted, until the operator runs
   `container_registry.md § Garbage Collection`. Flagging empty repos would
   make this script fail permanently on four repos that hold nothing. Report
   only non-empty tag lists.
2. **Every HTTP call fails loudly.** Use `curl -fsS -w '%{http_code}'` (or
   check the exit status and status code explicitly) and, on any non-200 or
   any body that does not parse as JSON, print the repo and status and
   increment `remaining`. No `|| true` anywhere on this path.
3. Keep the existing per-repo `FAIL: registry <repo> — N tag(s):` output shape
   and the trailing `OK: registry images` line, so the walk output stays
   comparable across releases. `OK: registry images` must print **only** when
   every query succeeded and every list was empty.

### 4d. Local-image grep (bug 3)

Replace `grep -E "(^|/)${PROJECT_NAME}/"`.

Add `PROJECT_NAME_HYPHEN="${PROJECT_NAME//_/-}"` near the top (mirroring
`teardown.sh:22`) and use:

```sh
# Both name forms, and NO left anchor. Four real shapes must match, and the
# old pattern caught only the first two:
#   docex_smoke_fixed/api:0.0.18                          (bare repo)
#   registry.luxrnd.tech/docex_smoke_fixed/api:0.0.18     (registry-prefixed)
#   docex_smoke_fixed-stage-tester:latest                 (hyphen, not slash)
#   docex-test-docex-smoke-fixed-api:latest               (docex-built test image)
# The last two are why the separator class is [-_/:] and why there is no `^`:
# the project name appears MID-STRING in both.
grep -E "(${PROJECT_NAME}|${PROJECT_NAME_HYPHEN})[-_/:]"
```

Note in the comment that the elastic seed's DynamoDB check
(`elastic/verify_clean.sh:136`) is the shape this derives from, widened for the
two forms a docker image name adds.

---

## Step 5 — `fixed/teardown.sh`

`$JB/docex/test_projects/fixed/teardown.sh`.

1. **Step 3 (local images, `:66-69`)** — same grep fix as 4d, same comment.
   This bug is why the images were never *deleted*, not merely never reported.
2. **Step 4 (registry, `:71-93`)**:
   - Same credential helper as 4b. Factor it or duplicate it — these two
     scripts are standalone by design and must not acquire a shared library;
     if you duplicate, say so in a comment in both.
   - Same `_catalog` enumeration as 4c, so retired repos are actually purged.
   - **`Accept` header (bug 2).** The `HEAD` that resolves a tag to a digest
     must offer the OCI index type as well, or buildx-pushed images 404 and no
     digest is obtained, so the `DELETE` never runs:

     ```sh
     -H 'Accept: application/vnd.oci.image.index.v1+json' \
     -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
     -H 'Accept: application/vnd.docker.distribution.manifest.v2+json'
     ```

     Comment it: *buildx pushes an OCI index, so `manifest.v2+json` alone
     resolves nothing for any image this project has ever produced.*
   - **Warnings become failures on the delete path.** A `DELETE` that does not
     return 202 must print the repo, tag and status. Keep `set -euo pipefail`'s
     behaviour intact — teardown may continue to the next tag, but the failure
     must be visible, and `verify_clean.sh` will catch what survived.
3. **The `storage.delete.enabled` comment at `:73`** — replace the bare
   parenthetical with a pointer to the doctrine section Step 7 adds:
   `container_registry.md § Registry container` (`REGISTRY_STORAGE_DELETE_ENABLED`).
   The whole reason this finding existed is that the requirement lived only in
   this comment.

---

## Step 6 — elastic seed: local-image leak (scope addition)

**Read this note before doing it.** This is the one step outside the brief the
corporal was given. It is included because it is the *same defect class* as
Finding 2 bug 3 and it will produce a false green on the elastic walk that
launches immediately behind this mod. Evidence: `elastic/verify_clean.sh` has
**no local-image check at all**, `elastic/teardown.sh` step 9 sweeps
containers, networks and volumes but **not images**, and 13 stale
`docex_smoke_elastic*` images are on this machine right now, including retired
`reaper` ones at `0.0.15`–`0.0.18`.

1. **`elastic/teardown.sh` step 9** — add an image sweep beside the
   container/network/volume sweep, using the pattern from 4d with
   `PROJECT_NAME`/`PROJECT_AWS_PREFIX` (both already defined at `:40`).
   Elastic images additionally carry an ECR host prefix
   (`256071447730.dkr.ecr.us-east-1.amazonaws.com/docex_smoke_elastic/api:0.0.18`),
   which the unanchored pattern handles — note that in the comment.
2. **`elastic/verify_clean.sh`** — add a `local docker images` check mirroring
   the fixed one, placed with the other local-docker checks, using
   `mark_fail` / `report_ok` so it matches that script's idiom rather than the
   fixed script's.
3. Add the same "a check that cannot answer must fail, not report zero" comment
   block from 4a to `elastic/verify_clean.sh`. (Operator instruction: the rule
   goes in the scripts, **in both seeds**.)

Do **not** touch elastic's AWS-facing checks.

---

## Step 7 — doctrine: `container_registry.md` (approved, land it)

`$JB/doctrine/infrastructure/preinfra/container_registry.md`. Operator approved
all four items at design review (Q1). The deciding argument, worth carrying into
the edit's framing: **the file already documents a § Garbage Collection
procedure that cannot run against the registry the same file specifies.** This
is repairing an internal contradiction, not imposing new policy.

1. **§ Implementation → Registry container**, compose `environment:` block —
   add after `REGISTRY_HTTP_HOST`:

   ```yaml
         # Required. The registry refuses manifest DELETE with 405 unless
         # deletion is explicitly enabled; § Garbage Collection's first phase
         # and every project's teardown depend on it. Enabling deletion does
         # NOT make the registry delete anything on its own — the no-retention
         # choice below is unaffected.
         REGISTRY_STORAGE_DELETE_ENABLED: "true"
   ```

   Add a matching bullet to the § Registry container **Notes** list.

2. **§ Design, key choice 3 ("No retention policy")** — append:

   > Deletion is nonetheless **enabled** (`REGISTRY_STORAGE_DELETE_ENABLED:
   > "true"`). The two are independent: the registry expires nothing on its
   > own, but an operator — or a project's `teardown.sh` — must be able to
   > delete a manifest when it asks to. Without the flag every
   > `DELETE /v2/<repo>/manifests/<digest>` returns `405 Method Not Allowed`
   > and [§ Garbage Collection](#garbage-collection)'s first phase is
   > impossible.

3. **§ Garbage Collection** — insert before the two-phase description:

   > Phase one requires `REGISTRY_STORAGE_DELETE_ENABLED: "true"` on the
   > registry container ([§ Registry container](#registry-container)). Without
   > it, the procedure below cannot start.

   Also note there that deleting a repository's last tag leaves the repository
   **entry** in `/v2/_catalog` with a null tag list until GC runs; that is
   expected, and a cleanup check should key on tags rather than on repository
   presence. (This is the behaviour Step 4c's implementation depends on;
   verified live 2026-08-06.)

4. **§ Verifying Reachability** — add a fourth numbered verification after the
   round-trip push/pull:

   > 4. **Manifest deletion → 202.** Resolve the throwaway tag to a digest and
   >    delete it:
   >
   >    ```bash
   >    digest="$(curl -fsSI -u '<username>:<password>' \
   >        -H 'Accept: application/vnd.oci.image.index.v1+json' \
   >        -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
   >        https://registry.${base_domain}/v2/preinfra-smoke/hello/manifests/0.0.1 \
   >      | awk -F': ' 'tolower($1)=="docker-content-digest" {gsub(/\r/,"",$2); print $2}')"
   >    curl -fsS -o /dev/null -w '%{http_code}\n' -u '<username>:<password>' \
   >      -X DELETE "https://registry.${base_domain}/v2/preinfra-smoke/hello/manifests/${digest}"
   >    ```
   >
   >    Expect `202`. A `405` means `REGISTRY_STORAGE_DELETE_ENABLED` is
   >    missing. An empty `digest` means the `Accept` headers did not cover the
   >    manifest type actually pushed — buildx pushes an OCI **index**, so
   >    `manifest.v2+json` alone resolves nothing.
   >
   >    This step also **cleans up** the `preinfra-smoke/hello` tag that step 3
   >    leaves behind, which otherwise sits in the registry catalog forever.

   Sentence to include in that subsection's framing: this is what turns the
   requirement from prose into something the setup walk proves — and its
   absence is how a machine-wide misconfiguration survived several releases
   while `verify_clean.sh` reported clean.

**Do not** add a `docex preinfra` check for the flag. That was ruled a
follow-on (Q2) and is Step 8.

---

## Step 8 — log the deferred `preinfra` probe to advance 006

Create
`$JB/docex/plans/modifications/_advance_006_preinfra_registry_delete_check.md`,
following the structure of the existing
`_advance_006_skill_body_conformance.md` in that folder (status banner → the
gap → why deferred → recommendation → reading).

Content:

- **Status:** deferred to advance 006; not a 1.7.0 cut blocker. Ruled by the
  operator at mod 122's design review (Q2).
- **The gap:** `./bin/docex preinfra development` already verifies the
  registry's *credential* side (`container_registry.md § Verification by docex
  preinfra`) but does not verify that the registry accepts manifest deletion.
  Every `fixed` project's `teardown.sh` depends on that flag, and its absence
  is invisible until teardown silently leaks tags — which is exactly what
  happened for several releases.
- **The ruling, with reasoning:** yes in principle — `preinfra` exists to
  verify preinfra is in the needed form, and teardown provably depends on the
  flag, so it belongs in the probe. Not now: it is `docex` code, it needs its
  own tests, and it sits between here and an elastic walk already blocked
  behind mod 122.
- **Recommended shape:** the probe is the same three calls Step 7 item 4 adds
  to the doctrine — push/resolve/DELETE against a throwaway tag, expecting
  `202`. Note the design question a builder must answer: a probe that *pushes*
  is heavier than the rest of `preinfra development`, so an alternative is to
  read the registry container's env directly, which is cheaper but only works
  when the registry is on the same host.
- **Reading:** `container_registry.md § Verification by docex preinfra`,
  `§ Garbage Collection`, `PRE_CUT_CHECKLIST § A.5`, and this mod's
  [`overview.md`](./122_walk_findings/overview.md) § Finding 4 — fix the
  relative path to be correct from the file's own location.

---

## Step 9 — `PRE_CUT_CHECKLIST.md`

`$JB/docex/test_projects/PRE_CUT_CHECKLIST.md`.

### 9a. A.4.1 — create step + permanence (Finding 3)

The nine records are **standing**. Above the existing checkbox list, add a
create step in the shape A.4.2 uses:

- A line stating these are created **once** in the parent `luxrnd.tech` Route53
  zone as `A` records → `$DEV_IP`, and that they are **permanent**: they
  survive teardown by design, because `teardown.sh` disclaims DNS as the
  operator's responsibility (`teardown.sh` header) and because the fixed
  project — unlike elastic — has **no zone lifecycle** for a walk to create and
  destroy. Per-walk churn would buy nothing and cost a propagation stall at the
  front of every walk.
- A concrete creation note: if `dig +short <subdomain>` returns nothing for any
  of the nine, create it in the parent zone before proceeding. (Do not script
  it; the checklist is operator-driven and A.4.2 is prose too.)
- Keep the existing nine checkboxes and the existing `dig` verification line
  unchanged, and keep the CICL-v3 paragraph that follows them unchanged.

### 9b. § E — exempt them

In § E, the bullet currently reading:

> - [ ] No leftover state in Route53 except the parent `luxrnd.tech` zone and
>   any other unrelated records the operator runs.

Rewrite so the exemption is explicit rather than implied by "unrelated": the
parent zone, **the nine standing fixed-walk `A` records from A.4.1**, and any
other unrelated operator records. Add a half-sentence saying those nine are
*expected* to remain and that removing them breaks the next fixed walk at A.4.1
— which is the contradiction this repairs.

### 9c. C.9 — the ping body (Finding 5)

The box `POST a ping to https://docex-smoke-fixed.luxrnd.tech/pings — returns
201.` gains a concrete command. The field is `payload`
(`infra/contracts/api.web.openapi.yml:138`, `required: [payload]`);
`{"message": …}` returns 422.

```
curl -sS -X POST https://docex-smoke-fixed.luxrnd.tech/pings \
  -H 'Content-Type: application/json' -d '{"payload": "walk-ping"}'
```

### 9d. D.11 — same check

Inspect D.11's equivalent ping box. If it is equally underspecified, add the
same line with the elastic hostname. If it already carries a body shape, leave
it and note in your report that it did.

### 9e. C.11 — what `verify_clean.sh` now does

Extend the `verify_clean.sh` box: it now **also fails when a registry query
cannot be answered** — a missing `~/.docker/config.json` credential, a non-200
from `/v2/`, or an unparseable body — rather than reporting "clean". State that
a green run is now evidence the registry was actually *interrogated*. Add that
repositories with a **null tag list** are expected and not leftovers; they
persist until the operator runs `container_registry.md § Garbage Collection`.

---

## Step 10 — verification (yours)

Run these and report the output. Do **not** run any `./bin/docex` command.

1. **Seed parity.**
   `diff -rq $JB/docex/test_projects/{fixed,elastic}/core` — only `__pycache__`
   lines under `dist/` may appear.
2. **Test files are syntactically valid and import-clean at the alogic tier.**
   `python3 -m py_compile` every file under
   `$JB/docex/test_projects/fixed/core/api/tests/`. (The DB-tier files cannot
   be *run* outside the test container — they `sys.path.insert` `/service/dist`
   — so compilation is the bound of what you can check here.)
3. **Shell syntax.** `bash -n` on
   `fixed/{verify_clean,teardown}.sh` and `elastic/{verify_clean,teardown}.sh`.
   Then `shellcheck` them if it is installed; report warnings, do not chase
   every one.
4. **No `|| true` survives on a query path** in either `verify_clean.sh`.
   `grep -n '|| true\||| echo' fixed/verify_clean.sh fixed/teardown.sh` and
   confirm every remaining hit is on a *mutation* path (a best-effort
   `docker rm`/`network rm`), never on a path whose result is reported.
5. **The credential never leaks.** `grep -rn 'auth\|Basic'` the two fixed
   scripts and confirm no line echoes, prints, or `set -x`-exposes the value,
   and that the temp config file is `chmod 600` and removed by a trap.
6. **`docex` suites unchanged.** From `$JB/docex`:
   `pytest tests/unit -q` → **1007** passed; `pytest -m integration -q` → **20**
   passed, 0 failed. Neither suite sees the seeds' own tests, so any movement
   at all is a regression — report the exact numbers.
7. **Nothing forbidden was touched.**
   `git -C $JB status --short` must show no modification under
   `docex/src/`, `docex/test_projects/*/core/api/src/`, or any `doctrine/` file
   other than `infrastructure/preinfra/container_registry.md`.

Do not commit. Do not run the smoke walk. Report what you changed, the exact
test counts, and anything in Steps 1–9 you could not do as written.

---

## Step 11 — clock-side binding validation (addendum)

*Added after Steps 1–10 were written. Operator ruling on the held
binding-coverage item; see [`overview.md`](./overview.md) § Finding 6 for the
reasoning, which you should read before starting.*

This step **does** change product source under `core/api/src/**`, which Ground
Rule 2 otherwise forbids. The rule is suspended for the two files named below
and for nothing else.

Both seeds, byte-identical.

### 11a. `ContJobsCron.unbound()`

`{fixed,elastic}/core/api/src/hex/jobs/adapters/driving/cont_jobs_cron.py`.

Add a classmethod beside `job_names()`:

```python
@classmethod
def unbound(cls, scheduled: Iterable[str]) -> tuple[str, ...]:
    """Scheduled job names this adapter cannot dispatch, sorted.

    Empty means every scheduled name has a binding.
    """
```

Requirements:

- **Classmethod, no instance, no database** — same constraint as `job_names()`,
  and for the same reason. Comment it by reference rather than restating it.
- **One direction only.** It answers "which of these can I not fire?" It must
  **not** report bindings that have no schedule. Comment that asymmetry *here*,
  where the temptation to make it symmetric actually lives:

  > A bound job with **no** schedule is legitimate and must never be reported.
  > The driving port is shared, so a job reachable only over HTTP or CLI is a
  > deliberate design — firing a job by hand stopped being a special path. Do
  > not make this symmetric.
- Sorted output, so the error message is stable and diffable.

**Rewrite the class docstring paragraph** that currently begins *"Binding
coverage is asserted nowhere yet."* — it becomes false with this change.
Replace it with what is now true: coverage **is** asserted, at clock startup,
by `entrypoints/clock.py` calling `unbound()`; the adapter answers the
question and the runtime host owns the policy that an unbound name is fatal.
Keep the surrounding "two dispatch tables are not duplication" paragraph
untouched — it is unrelated and still correct.

`fire()`'s `Raises:` docstring cross-references "the binding-coverage note in
the class docstring". Check that the reference still resolves after the
rewrite and adjust the wording if not; `fire()`'s own `KeyError` behaviour does
**not** change — it remains the last line of defence for a name that somehow
reaches dispatch.

### 11b. `entrypoints/clock.py` — fail fast

`{fixed,elastic}/core/api/src/entrypoints/clock.py`.

Replace the comment block in `main()` that currently begins *"RECORDED
DECISION, not a TODO:"* — the decision is now made — with the validation
itself, placed **immediately after** the existing `logger.info("clock: %d
scheduled job(s): …")` call and **before** the health-server thread starts and
before `next_at` is seeded.

```python
    missing = cron.unbound(schedules)
    if missing:
        logger.error(
            "clock: %d scheduled job(s) have no binding: %s; image implements: %s",
            len(missing), ", ".join(missing), ", ".join(sorted(cron.job_names())),
        )
        raise SystemExit(1)
```

Comment requirements — three WHYs, each earning its line:

1. **Why fatal.** A schedule naming a job this image cannot dispatch is a
   typo, and it is unrunnable. Fail the *deploy*, not the check.
2. **Why here rather than on first fire.** A clock that starts, answers its
   health probe, and then dies at 03:00 is worse than one that never starts.
   The failure must land while someone is watching the deploy.
3. **Why both halves are in the message.** An operator reading a crash-looping
   container needs the offending name *and* the implemented set to see the
   typo; either alone sends them to the source tree.

Keep `raise SystemExit(1)` rather than `sys.exit` — it matches
`_load_schedules()`'s existing idiom in this file, and matching it is the
point.

**Keep the existing "N scheduled job(s) … image implements: …" log line.** It
is what `PRE_CUT_CHECKLIST` C.9 / D.11 tell the operator to look for, and it is
still the positive-path evidence that the schedule arrived.

### 11c. Tests — both directions

`{fixed,elastic}/core/api/tests/test_clock_smoke.py`. Two tests, in that
file's existing no-database, no-`root` idiom:

| Test | Asserts |
| ---- | ------- |
| `test_a_scheduled_name_with_no_binding_is_reported` | `ContJobsCron.unbound(["heartbeat", "nightly_cleanupp"]) == ("nightly_cleanupp",)`. Use a **plausible typo**, not `no_such_job` — the test should look like the failure it defends against. |
| `test_a_binding_with_no_schedule_is_not_reported` | `ContJobsCron.unbound(["heartbeat"]) == ()` even though `prune_pings` is implemented and unscheduled. Comment that this direction is deliberately benign and points at the asymmetry note in the adapter. |

Also assert `unbound(...)` works **off the class**, with no instance
constructed, in at least one of the two — that is the property Mod 117 paid for
and the one a future refactor would silently break.

### 11d. `clock.md` — rewrite the held sentence

`$JB/doctrine/infrastructure/specifics/clock.md`, the line at the end of
§ How the schedule reaches the container:

> The [check step](../cicd.md#check-step) can assert that every declared job
> name has a binding in the clock's dispatch table, catching a schedule that
> names a job nobody implements.

Delete it. Replace with a sentence or two, in the file's voice, saying:

- The clock validates its own schedule **at startup**, against its dispatch
  table, and **refuses to start** if any scheduled name has no binding.
- So a schedule naming a job nobody implements fails the **deploy**, visibly,
  rather than surfacing at 03:00 as a logged failure.
- Say nothing about `docex check`. The claim that it "can assert" this is
  deleted, not softened — nothing implements it and nothing will.

Do not add an open question, a marker, or a "for now". This is settled.

### 11e. Checklist — C.9 and D.11

`PRE_CUT_CHECKLIST.md:270` (C.9) and `:383` (D.11) are the same box on two
foundations. Both currently end:

> **Compare the two lists by eye** — a scheduled name absent from the
> implemented set is a job nobody has written, and nothing currently asserts
> this automatically.

Both clauses are now false. Rewrite each box to say:

- The log line is still the evidence the schedule **arrived**, so keep reading
  it.
- The comparison is now asserted **by the clock itself at startup**; a
  mismatch means the container exits non-zero and never reaches its loop, so
  the observable symptom is a crash-looping clock, not a silently-wrong one.
- Therefore: if the clock is running and logging, the binding check has already
  passed. Preserve each foundation's own log-access mechanism (`docker logs …`
  for C.9, the CloudWatch log group for D.11).

### 11f. Verification additions

Add to Step 10:

- `test_clock_smoke.py` is DB-free, so **run it**:
  `cd $JB/docex/test_projects/fixed/core/api && PYTHONPATH=./src pytest tests/test_clock_smoke.py -q`.
  Report the count. Do the same for the elastic copy.
- Re-run Step 10 check 1 (seed parity) **after** these edits — this step touches
  `core/api/src/**` in both seeds, which is the largest byte-identity risk in
  the whole mod.
- Step 10 check 7 changes: modifications under
  `docex/test_projects/*/core/api/src/` are now **expected**, but only in
  `entrypoints/clock.py` and
  `hex/jobs/adapters/driving/cont_jobs_cron.py`. Any other file under `src/`
  is a violation, and `docex/src/` must still be untouched.
- `doctrine/` may now show **two** modified files:
  `infrastructure/preinfra/container_registry.md` and
  `infrastructure/specifics/clock.md`. No others.

---

## Step 12 — finish sweeping the swallow class (addendum)

*Added after Step 11. Operator ruling: the residual you flagged is fixed here,
in Mod 122, not deferred.*

The reasoning, because it changes how you should judge edge cases below: both
`verify_clean.sh` scripts now **print the rule in a header block** — *a check
that cannot answer must FAIL, not report zero* — and then violate it further
down. A script that condemns a pattern in its header and commits it three lines
later does not merely carry a bug; it **discredits the rule for the next
reader**, and the rule is the more valuable artifact. When in doubt on any
individual call site, resolve toward making the rule true.

### 12a. `fixed/verify_clean.sh` — the `check()` helper

```sh
check() {
  local label="$1"; shift
  local count
  count="$("$@" 2>/dev/null | wc -l | tr -d ' ')"
```

If the docker daemon is unreachable, `docker ps -aq` fails, `wc -l` counts zero
lines, and the check reports `OK`. All three of its call sites — containers,
networks, volumes — are affected.

Rewrite it on the shape you already used for local images: run the command,
test **its** exit status, and only then filter. Requirements:

- A non-zero exit from the queried command prints
  `FAIL: <label> — the check could not answer` plus the captured stderr, and
  increments `remaining`.
- An empty result from a command that **succeeded** is still `OK`.
- Keep the `check "docker containers" docker ps -aq --filter …` call shape at
  all three sites — the helper's signature should not change, only its body.
- Do not silently drop stderr. It is what tells the operator *why* the check
  could not answer.

### 12b. `elastic/verify_clean.sh` — the same class, ~20 times

**This is the more serious half and it is why the ruling went this way.** That
script has **21 swallowing query sites** (`|| true` / `|| echo '[]'` on `aws`
calls), two presence checks of the form
`if aws … >/dev/null 2>&1; then mark_fail … else report_ok`, and **no
credential preflight at all**. With expired AWS credentials, or the wrong
region, or an IAM permission missing, *every one of the ~20 checks reports `OK`
and the script exits 0.* That script is the elastic walk's D.13 gate.

Three changes:

**1. Credential preflight, before any check.** One `aws sts get-caller-identity`
call. If it fails, print the failure and **exit non-zero immediately** rather
than running twenty checks that cannot answer. This is the cheapest guard in
the file: it catches the dominant real-world cause once, instead of twenty
times, and it turns the most likely false-green into the most obvious failure.
Echo the account id and region on success so the operator can see *which*
account was interrogated — a clean run against the wrong account is its own
false green.

**2. An `aws_query` helper, mirroring `registry_get`.**

```sh
AWS_QUERY_OUT=""
aws_query() {   # aws_query <label> <command...>
  # Sets AWS_QUERY_OUT on success. On failure: mark_fail + return 1.
}
```

- **Call it as a plain command and read `AWS_QUERY_OUT`** — never
  `x="$(aws_query …)"`. That is the subshell trap you already hit and
  documented on `registry_get`; the `mark_fail` inside would be discarded.
  Carry the same WHY comment here rather than assuming the other one will be
  found.
- Post-filtering (`tr`, `grep`, `sort -u`, the `python3` filters) moves to the
  **caller**, operating on `$AWS_QUERY_OUT`. `grep` exiting 1 there is the
  *clean* answer and stays tolerated — that distinction is the whole point of
  the split.
- Convert all 21 sites. The `python3` post-filters that currently end
  `|| true` (the VPC one at `:55`, and any like it) must also report a failure
  rather than yield an empty list: an unparseable AWS response is exactly as
  unanswerable as a failed call.

**3. The two presence checks** (`s3api head-bucket` at `:131`,
`dynamodb describe-table` at `:136`) conflate *"the resource is absent"*
(clean) with *"the call failed"* (unanswerable). Distinguish them by
inspecting the error: a `404`/`NoSuchBucket` and a `ResourceNotFoundException`
respectively mean clean; **any other** non-zero outcome is a failure to answer
and must be reported as such. Comment the distinction — it is subtle and a
future reader will otherwise "simplify" it back.

Do **not** change which resource types are checked, the check order, or the
`OK:`/`FAIL:` output vocabulary. This step changes *how failure is detected*,
nothing else. A reviewer diffing this against the previous walk's output should
see the same lines in the same order on a clean run.

### 12c. Verification — a fourth failure proof

Add to the failure-proof set, in **both** seeds:

- **The unanswerable-command case.** Point `DOCKER_HOST` at a nonexistent
  socket (e.g. `DOCKER_HOST=unix:///nonexistent/docker.sock`) for the duration
  of the assertion, run `fixed/verify_clean.sh`, and require:
  1. non-zero exit, and
  2. that the docker container/network/volume lines say the check **could not
     answer** — not `OK`.

  **Hard constraint: do NOT stop the docker daemon.** This machine is shared and
  other services depend on that daemon. `DOCKER_HOST` proves the same property
  safely, and it is the more honest test anyway: what is being defended against
  is *"the command cannot answer"*, not specifically *"dockerd is stopped"*.

- **The elastic equivalent**, in your stubbed harness rather than against real
  AWS: a stubbed `aws` that exits non-zero must make `elastic/verify_clean.sh`
  exit non-zero with **no** `OK:` line for the affected check, and the
  credential preflight must fail closed when `sts get-caller-identity` fails.
  Do not issue real AWS calls.

### 12d. Documentation touch-ups

- `PRE_CUT_CHECKLIST.md` **C.11**: the paragraph you added about registry
  queries generalizes — `verify_clean.sh` now fails whenever **any** check
  cannot be answered, including an unreachable docker daemon. Widen that
  sentence; do not add a new paragraph.
- `PRE_CUT_CHECKLIST.md` **D.13**: add the equivalent, and state the specific
  consequence that motivated it — with expired or wrong-account AWS
  credentials the script previously reported every resource type clean and
  exited 0. Mention the preflight's account/region echo as the thing to eyeball.

If Step 11 has already edited either checklist section, integrate rather than
overwrite.
