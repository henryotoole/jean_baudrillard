# Mod 122 — Fixed-walk findings

Repairs the five findings the 1.7.0 fixed-foundation smoke walk surfaced.
Finding 1 blocks the CI/CD chain and blocks the elastic walk behind it; the
rest are correctness repairs to the walk's own instruments and to the
checklist that drives them.

Scope discipline note: the elastic walk hits Finding 1 identically at D.8, so
every code change here lands in **both** seeds and the two `core/` trees stay
byte-identical (B.14 parity). Nothing else in this mod is foundation-general —
Findings 2–4 are fixed-seed and preinfra territory.

---

## Finding 1 — the jobs tests race the live `api.worker`

### What is actually wrong

`docex test` brings the whole `test` env up before running `test.sh`
(`cicd.md § Build Test Step`), so a live `api.worker` container is polling the
same `jobs` table while the suite runs. Any test that assumes it is the sole
claimer or the sole performer is wrong by construction.

The walk named two failures. They are not the only ones — **the entire
`test_jobs_smoke.py` file races**, and the two reported are simply the ones
whose window is widest:

| Test | Racing assertion | Why it usually passed |
| ---- | ---------------- | --------------------- |
| `test_jobs_concurrency.py::test_two_consumers_claim_every_job_exactly_once` | `set(all_claimed) == enqueued` | The worker only wins rows if it polls inside the enqueue loop |
| `test_jobs_smoke.py::test_run_once_returns_the_number_performed` | `total >= len(ids)` | Same |
| `test_jobs_smoke.py::test_enqueued_job_is_claimed_performed_and_completed` | `_row(job_id)[1] is None`, then `retention.calls >= 1` | Worker must win within microseconds of the enqueue, then perform with the *real* retention so the stub is never called |
| `test_jobs_smoke.py::test_a_failing_handler_records_the_error_and_the_next_job_still_runs` | `poisoned_error is not None` | The live worker has a *working* `prune_pings` handler, so a job it wins finishes clean |
| `test_jobs_smoke.py::test_claim_returns_started_jobs` | `job_id in claimed` | Worker must win in the gap between `enqueue` and `claim` |

The author anticipated a live *clock* — hence the marker name, the `strays`
bucket and the `>=` — but a clock only *adds* rows. A worker *removes* them,
and no amount of marker-scoping survives another process taking your row.

### The rule this establishes

> **A test running in the `test` env has no sole agency.** The doctrine
> mandates that the whole stack be up. A test may therefore assert on
> *outcomes* observable in shared state, and on *its own* components' behaviour
> — never on being the only actor. Assertions that require sole agency belong
> at the alogic tier, where the collaborator is a stub.

This is written into the seed's test docstrings because downstream projects
copy this tree, and the current files teach the opposite by example.

### The fix, by test

**No product change is required, and none is proposed.** `src/` is untouched:
no `queue` column, no claim predicate, no name filter, no private table. The
real `QueueJobsPostgres.claim()` still runs `FOR UPDATE SKIP LOCKED` against
the real `jobs` table created by the real migration. The escalation gate in the
kickoff prompt is therefore *not* tripped — this is stated explicitly rather
than left to inference.

**1. `test_jobs_concurrency.py` — keep it at the DB tier and make the worker a
third participant.**

The live worker's claims of marker-named rows are *observable*: it has no
handler for `conc_<hex>`, so `JobRunnerService.run_once()` calls
`queue.fail(...)` and stamps `error = "no handler for job name 'conc_…'"` on
the row. Nothing else in the run writes that column — the in-test consumers
only `claim` and later `complete`. So:

- `worker_claimed` := marker rows carrying an error, read **before** cleanup.
- `ours` := the ids the two in-test consumers returned.
- Assert `claimed[0] ∩ claimed[1] == ∅` (unchanged, the original property).
- Assert `ours ∩ worker_claimed == ∅` — cross-process exclusivity.
- Assert `ours ∪ worker_claimed == enqueued` — completeness, restored.

Between the drain returning and the read, a row the worker has claimed but not
yet failed is indistinguishable from one of ours, so the accounting is preceded
by a **bounded poll** (≤60 s) until every marker row outside `ours` carries an
error. A worker that claims and then never records an outcome is a real defect
and should fail this test.

This is **strictly stronger** than what it replaces: exclusivity across three
concurrent claimers, one of them a genuinely separate container on a separate
connection pool, instead of two threads in one process. That gain gets written
down in the docstring so a future reader does not "simplify" it back.

**2. `test_jobs_smoke.py` — split by tier.**

Retained at the DB tier (these hold under any number of concurrent actors):

- An enqueued job reaches a **finished row**: enqueue via `JobService`, drive
  an in-process `JobRunnerService` in the existing bounded loop, poll until
  `finished_at` is set, assert `name`, `started_at ≤ finished_at`,
  `error IS NULL`. Whoever performed it, the deferral contract held. The
  assertion on `retention.calls` goes — it asserts agency, not outcome.
- `claim()` returns rows it has started: assert every `Job` handed back has
  `started_at` set. True of whatever subset we win, including the empty set —
  paired with a bounded poll proving our own enqueued row eventually reaches
  `started_at IS NOT NULL` in the table.

Moved down to a new alogic-tier file with a stub `QueueJobs` (no database, no
`root` import, no live actor — the idiom `test_processor_smoke.py` and
`test_clock_smoke.py` already establish in this seed):

- `run_once()` returns the number performed.
- A handler that raises records the error on that row and the batch continues.
- A name with no handler records "no handler" and does not crash the drain.
- `prune_pings` dispatches to `ContRetention.prune` and `heartbeat` does not.
- **The clock defers and does not work**: `JobService.prune_pings()` enqueues
  exactly once and touches nothing else. This is the race-free replacement for
  the deleted `started_at is None` assertion, and it is a better statement of
  the property — it holds structurally rather than within a timing window.

New file name: **`tests/test_jobs_alogic.py`**. The seed's other stub-based
files are named `…_smoke.py`, which is a small inconsistency I am choosing to
break: this tree is reference material, and naming the tier is the lesson.

### Net coverage

Nothing is lost. Dispatch, error handling and the defer-only rule move from a
tier where they were flaky to the tier the doctrine puts them in, and
cross-process claim exclusivity is gained.

---

## Finding 2 — `verify_clean.sh` has been reporting false greens

Four bugs, three named in the kickoff and one found while reading. All in the
**fixed** seed's `teardown.sh` + `verify_clean.sh`.

1. **No `Authorization` header.** The registry is htpasswd-protected
   (`container_registry.md § Design`, key choice 1), so `/v2/<repo>/tags/list`
   401s. `verify_clean` swallows it via `|| true`, `teardown` via
   `|| echo '{}'`; both conclude "no tags".
2. **Wrong `Accept` header.** buildx pushes an OCI index, so a `HEAD` offering
   only `application/vnd.docker.distribution.manifest.v2+json` 404s and no
   digest is obtained, so the `DELETE` never runs.
3. **The local-image grep.** `(^|/)docex_smoke_fixed/` requires a trailing
   slash and misses `docex_smoke_fixed-stage-tester:latest`. The **elastic**
   seed already has the right shape (`^(${PROJECT_NAME}|${PROJECT_AWS_PREFIX})[-_]`);
   copy it, widening the separator class to `[-_/]` because fixed repo names
   are `project/codebase`. This bug is in `teardown.sh` step 3 as well as in
   `verify_clean.sh`, so the image is never *deleted* either.
4. **(new) The repo loop is hardcoded to live codebases.** `for service in api`
   cannot see the retired `reaper`, `web` and `worker` repos where 26 of the 30
   leaked tags actually live. A repo retired by a rename becomes permanently
   invisible to both scripts. Replace the loop with an enumeration of
   `/v2/_catalog` filtered on the `${PROJECT_NAME}/` prefix, so the check is
   keyed on *what the registry holds* rather than on *what the project
   currently declares*.

### The structural fix underneath all four

> **A check that cannot answer must fail, not report zero.** Every `|| true` /
> `|| echo '{}'` on a query path is deleted. A registry query that errors,
> 401s, or returns unparseable output makes `verify_clean.sh` exit non-zero
> with the HTTP status, exactly as a genuine leftover does.

This is the actual defect. Bugs 1–4 are instances; without this rule the next
one produces another false green.

### Credential handling

Both scripts read the registry credential from the operator's
`~/.docker/config.json` (`auths["registry.luxrnd.tech"].auth`, base64) — the
one artefact `PRE_CUT_CHECKLIST.md § A.5` already requires. No new secret
store, no new operator setup. The value is passed to `curl` via `-K -` on
stdin so it never enters `argv`, never enters the environment of a child
process, and never appears in a `set -x` trace. If the credential is absent the
script fails with a resolution line pointing at A.5, rather than proceeding
unauthenticated.

### Registry deletion still needs a preinfra change — see Finding 4

Auth and `Accept` get the *digest*; the `DELETE` itself returns 405 unless the
registry runs with `storage.delete.enabled`. That is Finding 4 and it is
escalated, not landed here. The `verify_clean.sh` repair is independent of it
and lands regardless: with delete disabled, teardown leaves tags and
`verify_clean` correctly goes red — which is the whole point.

### Cleaning up the existing leak

30 leaked tags across `api`, `reaper`, `web`, `worker` are removed as part of
this mod's verification, so `verify_clean.sh` has a genuine green to report.

---

## Finding 3 — `A.4.1` has no create step and contradicts § E

Three facts cannot all hold: A.4.1 reads as standing prerequisites, the records
did not exist, and § E demands no leftover Route53 state.

**Resolution chosen: the nine fixed records are permanent, and the document
says so in both places.**

- **A.4.1** gains an explicit create step in the parent `luxrnd.tech` zone
  (nine `A` records → `$DEV_IP`), in the shape A.4.2 already uses, with a
  sentence saying they are **standing** records that survive teardown —
  reconciling with `teardown.sh:11`'s "DNS records at the registrar (operator's
  responsibility)", which stays true and stops being the only mention.
- **§ E** gains an explicit exemption naming them, so "no leftover state in
  Route53" no longer reads as a demand to delete what A.4.1 requires.

Rejected: making them per-walk create/remove like A.4.2's. A.4.2's records are
temporary because the *child zone* is created and destroyed by
`projinfra up/down production`; the fixed project has no zone lifecycle at all,
so per-walk churn buys nothing and costs a DNS-propagation stall at the front
of every walk.

## Finding 5 — `C.9`'s "POST a ping" has no body shape

The field is `payload` (`api.web.openapi.yml:138` — `required: [payload]`);
`{"message": …}` 422s. C.9 gains a concrete example line:

```
curl -sS -X POST https://docex-smoke-fixed.luxrnd.tech/pings \
  -H 'Content-Type: application/json' -d '{"payload": "walk-ping"}'
```

The same box in D.11 is checked for the same gap and given the same line if it
has one.

---

## Finding 4 — DRAFT ONLY, for operator approval

`teardown.sh:73` asserts the registry needs `storage.delete.enabled: true`, and
that string appears **nowhere else in `doctrine/` or `docex/`**. The preinfra
registry did not set it, so image deletion 405'd for every project on this
machine. The walker enabled it machine-wide
(`REGISTRY_STORAGE_DELETE_ENABLED: "true"`; backup at
`docker-compose.yml.bak-1.7.0-walk`).

**Nothing lands for this finding in this mod without approval.** The draft:

**Target:** `doctrine/infrastructure/preinfra/container_registry.md`.

1. **§ Implementation → Registry container.** Add to the compose `environment:`
   block:

   ```yaml
         # Required. The registry refuses manifest DELETE with 405 unless
         # deletion is explicitly enabled; § Garbage Collection's phase one
         # and every project's teardown depend on it. Enabling deletion does
         # NOT make the registry delete anything on its own — retention
         # (choice 3 below) is unaffected.
         REGISTRY_STORAGE_DELETE_ENABLED: "true"
   ```

2. **§ Design, key choice 3 ("No retention policy").** Append: *"Deletion is
   nonetheless **enabled** — `REGISTRY_STORAGE_DELETE_ENABLED: "true"`. The two
   are independent: the registry expires nothing by itself, but an operator or
   a project's `teardown.sh` must be able to delete a manifest when it asks to.
   Without the flag, every `DELETE /v2/<repo>/manifests/<digest>` returns 405
   and § Garbage Collection's first phase is impossible."*

3. **§ Garbage Collection.** Insert before the two-phase description: *"Phase
   one requires `REGISTRY_STORAGE_DELETE_ENABLED: "true"` on the registry
   container (§ Registry container). Without it the procedure below cannot
   start."* — this section currently documents a procedure that cannot run
   against the registry the same document specifies.

4. **§ Verifying Reachability.** Add a fourth verification: push a throwaway
   tag, `HEAD` its manifest with both
   `application/vnd.oci.image.index.v1+json` and
   `application/vnd.docker.distribution.manifest.v2+json` in `Accept`, then
   `DELETE` the digest and expect `202 Accepted`. A `405` means the flag is
   missing. This is what turns the requirement from prose into something the
   setup walk actually proves — and it is the check whose absence let a
   machine-wide misconfiguration survive several releases.

**Two things the operator should weigh:**

- This is a **new requirement on a shared, machine-wide preinfra resource**.
  Every `fixed` project on this host now depends on the flag, and the doctrine
  change makes that dependency stated rather than assumed. That is the argument
  *for* landing it.
- The change is already **in effect** on this machine, out of band, with a
  backup file beside it. Approving the doctrine change makes the machine and
  the doctrine agree; declining it means the machine should be reverted from
  the backup and `teardown.sh` must instead stop attempting deletion — in which
  case the smoke projects leak registry tags by design and `verify_clean.sh`'s
  registry check has to be reframed as "expected leftovers", which I would
  argue against.

Also worth a ruling but **not drafted**: whether `./bin/docex preinfra
development` should *check* the flag the way it already checks for the pull-side
credential (`container_registry.md § Verification by docex preinfra`). That is a
`docex` code change, so it is a follow-on mod rather than a doctrine edit, and I
have not assumed it.

---

## Changes by file

**Both seeds (byte-identical `core/` trees preserved):**

| File | Change |
| ---- | ------ |
| `{fixed,elastic}/core/api/tests/test_jobs_concurrency.py` | Three-consumer accounting; bounded settle poll; docstring rewritten to the no-sole-agency rule |
| `{fixed,elastic}/core/api/tests/test_jobs_smoke.py` | Reduced to the two DB-tier outcome tests; docstring states which actors are live |
| `{fixed,elastic}/core/api/tests/test_jobs_alogic.py` | **New.** Stub-queue alogic tier: dispatch, failure, no-handler, count, defer-only |

**Fixed seed only:**

| File | Change |
| ---- | ------ |
| `fixed/verify_clean.sh` | Auth via `~/.docker/config.json`; `_catalog` enumeration; `[-_/]` image grep; **all query-path `\|\| true` deleted — an unanswerable query fails the check** |
| `fixed/teardown.sh` | Same auth + `_catalog`; OCI-index `Accept`; `[-_/]` image grep; comment at `:73` points at the doctrine section Finding 4 would add |

**Checklist:**

| Section | Change |
| ------- | ------ |
| `A.4.1` | Create step for the nine records; statement that they are standing and survive teardown |
| `§ E` | Explicit exemption for A.4.1's records |
| `C.9` | Concrete `POST /pings` body example (`{"payload": …}`) |
| `D.11` | Same, if the box is present and equally underspecified |
| `C.11` | Note that `verify_clean.sh` now fails on an *unanswerable* registry query, not only on a found leftover |

**Not touched:** `docex/src/**`, both seeds' `core/api/src/**`, `doctrine/**`.

---

## Verification

1. `pytest tests/unit` — 1007, unchanged. `pytest -m integration` — 20/0,
   unchanged. Neither suite sees the seeds' own tests, so the expectation is
   *literally* unchanged, and any movement is a regression.
2. **Re-walk C.1–C.4** on the fixed project (preinfra, projinfra, compile,
   secrets). The walk's teardown removed `infra/output/**` and the projinfra,
   so C.5 cannot be reached cold without them.
3. **C.5** — `./bin/docex test` exits 0. Then run it **five consecutive times
   with images already cached**, which is the condition under which the
   original failed 5/5. A single green run is not evidence here; the defect's
   signature was intermittent greenness.
4. **C.6 in full, by the book** — `check` → `merge` → `containerize`. The
   walker bypassed `merge` by hand, so **`docex merge` has not been exercised
   at all this cycle**; running it for real is an explicit deliverable, not a
   side effect. The feature-branch restructure C.6's preamble describes is
   performed as written.
5. **`verify_clean.sh` is proven able to fail**, in three separate ways —
   because each corresponds to one of the false-green mechanisms:
   1. **A leaked tag.** Push `docex_smoke_fixed/api:0.0.99-leakprobe`, run
      `verify_clean.sh`, require non-zero and require the tag to be *named* in
      the output. Delete it; re-run; require zero.
   2. **A leaked local image.** Tag a throwaway
      `docex_smoke_fixed-stage-tester:leakprobe` — the exact name bug 3 missed —
      and require non-zero.
   3. **An unanswerable query.** Run with the credential deliberately withheld
      and require non-zero *without* the words `OK: registry images`. This is
      the one that distinguishes the new script from the old: the old one
      passed this case.
6. Clear the 30 leaked tags, then a final `verify_clean.sh` green.
7. **C.7–C.11 are not re-walked.** They passed and nothing here reaches them.
   `teardown.sh`'s registry path is exercised by step 6 rather than by a full
   C.11.

---

## State settlement

The walk left the fixed inner repo on `main` at `78ef9d0` / `v0.0.18` with
`infra/output/**` deleted, and the outer repo carrying that plus an
already-inner-committed `project.yml`.

- The deleted `infra/output/**` is **restored by recompiling**, not committed
  as a deletion. The advance plan's drift log records the tracked output as
  what makes audit items B.16/B.17 cheap; committing the deletion silently
  reverses that decision. C.2 in the re-walk regenerates it.
- Inner repo (fixed) first, per `test_projects.md § Commit cadence`, then the
  outer catch-up. Note that C.6's restructure moves `main` and re-creates the
  `v<version>` tag, so the tag is re-pointed at the post-`merge` HEAD as cadence
  step 2 requires — this is `docex merge`'s own doing, not a manual fixup.
- Elastic inner repo is clean at `v0.0.19`; it gains only the three test-file
  changes and one commit.
- Outer repo: path-scoped commits on `005_process_type_solidification`.

---

## Design questions

1. **Finding 4 — approve the drafted `container_registry.md` change?** This is
   the one blocking question. Deciding "no" changes this mod's shape (see the
   Finding 4 section's second bullet). Deciding "yes" means I land items 1–4 of
   the draft; I have written them but not applied them.
2. **Finding 4 follow-on — should `docex preinfra development` gate on the
   flag?** Not drafted, not assumed. It is a `docex` code change and therefore
   a separate mod. Recording the ruling either way is worth more than the code.
3. **Finding 1 — confirming the negative.** No product change to
   `core/api/src/**` is proposed. If your intent behind the escalation gate was
   broader than the schema/predicate examples given — e.g. if you consider the
   seed's *test layout* to be reference material whose tiering split needs your
   sign-off, since downstream projects copy it — say so and I will hold. My
   reading is that it does not, and that the tiering split is exactly the
   doctrine-correct answer, but the trade of "who owns the reference test
   shape" is yours to make.
4. **`test_jobs_alogic.py` naming.** It breaks the seed's `…_smoke.py`
   convention deliberately, to name the tier. If you would rather the seed stay
   internally consistent, it becomes `test_jobs_dispatch_smoke.py` and the
   docstring carries the whole lesson instead. One-line change either way.

## Still held (not this mod)

`clock.md`'s binding-coverage sentence remains with the operator; nothing here
touches it.
