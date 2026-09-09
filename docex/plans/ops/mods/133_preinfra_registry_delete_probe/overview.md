# Mod 133 — `preinfra development` probes the registry's manifest-delete capability

Mod 9 of 9 in advance 006. Unrelated to surfaces or health; folded in from
advance 005's deferrals by operator ruling. Specification:
[`_advance_006_preinfra_registry_delete_check.md`](../_advance_006_preinfra_registry_delete_check.md).

## Goal

`./bin/docex preinfra development` gains one check: on a `fixed`-foundation
project, the container registry must accept a manifest `DELETE`. Every `fixed`
project's `teardown.sh` depends on that capability; without it, `DELETE
/v2/<repo>/manifests/<digest>` returns `405` and each project leaks one registry
tag per release. The requirement is stated in the doctrine
([`container_registry.md § Registry container`](../../../../doctrine/infrastructure/preinfra/container_registry.md#registry-container));
this mod makes it *checked*.

---

## Part 1 — What the probe actually is, and why the brief's shape is not it

The brief recommends a three-call probe: push a throwaway tag, `HEAD` it for a
digest, `DELETE` the digest and require `202`. It also poses the design question
a builder must answer — that pushing an image on every invocation is far heavier
than anything else `preinfra development` does.

**I answered that question empirically before designing, against real
`registry:2` and `registry:3` containers on this machine, plus the live
`registry.luxrnd.tech` registry.** The results change the design, so they are
recorded here as the design's evidence rather than as a footnote.

### The measurements

`Z` below is a well-formed but nonexistent digest (`sha256:` + 64 zeros) against
a **nonexistent** repository — a request with no side effects whatsoever.

| Registry | `REGISTRY_STORAGE_DELETE_ENABLED` | Request | Status | Body error code |
| --- | --- | --- | --- | --- |
| `registry:2` | unset (disabled) | `DELETE …/manifests/Z` | **405** | `UNSUPPORTED` |
| `registry:2` | `"true"` | `DELETE …/manifests/Z` | **404** | `MANIFEST_UNKNOWN` |
| `registry:2` | unset | `DELETE …/manifests/<real digest>` | **405** | `UNSUPPORTED` |
| `registry:2` | unset | `DELETE …/manifests/<tag>` | **405** | `UNSUPPORTED` |
| `registry:3` | unset | `DELETE …/manifests/Z` | 404 | `MANIFEST_UNKNOWN` |
| `registry:3` | `"true"` | `DELETE …/manifests/Z` | 404 | `MANIFEST_UNKNOWN` |
| `registry:3` | unset | `DELETE …/manifests/<real digest>` | **202** | — |
| `registry:3` | unset | `DELETE …/manifests/<tag>` | **202** | — |

And against the real registry (`registry:2`, htpasswd auth, TLS via its
dedicated traefik, delete **enabled**):

| Request | Status |
| --- | --- |
| unauthenticated `GET /v2/` | 401 |
| unauthenticated `DELETE …/manifests/Z` | **401** |
| authenticated `DELETE …/manifests/Z` | **404** `MANIFEST_UNKNOWN` |
| wrong-password `DELETE …/manifests/Z` | 401 |

### What these mean

1. **`registry:2` discriminates on a nonexistent digest.** `deleteEnabled` is
   checked *before* any manifest lookup, so the 405 arrives without a manifest
   needing to exist. The push in the brief's recommended shape is unnecessary:
   one request, zero bytes uploaded, zero side effects, and the discriminating
   `405 UNSUPPORTED` is still the real registry refusing a real delete.

2. **`registry:3` does not honour the flag at all.** Manifest `DELETE` by digest
   returns `202` with the flag unset. There is no misconfiguration to detect on
   distribution 3.0 — the capability is unconditionally present. So the
   nonexistent-digest probe's `404 → capability present` reading is *correct on
   both versions*: on `registry:2` because the gate was passed, on `registry:3`
   because the capability genuinely is there.

3. **Unauthenticated is useless.** A `401` arrives for *every* DELETE regardless
   of the flag — the auth middleware runs ahead of the handler. This is the exact
   trap the brief names: the smoke project's `verify_clean.sh` could not tell a
   `401` from a clean registry. The probe **must** authenticate, and a `401`
   must be a loud can't-answer, never a pass and never a finding.

### The residual fragility, and how it is pinned

Reading `404` as "capability present" is an *inference* — it infers that the
delete gate was passed because a later stage (manifest lookup) was reached. It
is empirically true of distribution 2.x and 3.x, which is every version in
existence, and the doctrine pins `registry:2`. But a hypothetical future version
that both honours the flag *and* checks existence first would return `404` in
both arms, and the probe would read a delete-disabled registry as enabled. That
is precisely the failure mode this advance is under orders not to ship.

**The pin is a test, not a comment.** The integration test in Part 5 brings up
the doctrine-pinned registry image with the flag *off* and asserts the probe
reports the capability **absent**. If a registry-version bump ever destroys the
inference, that test goes red and forces the re-derivation. The probe's
soundness is therefore mechanically guarded rather than trusted.

### Rejected alternatives

- **Push a synthetic manifest and observe `202` directly** (the brief's shape,
  minus the Docker Hub round trip — a blob `POST`/`PUT` plus a manifest `PUT` is
  a few hundred bytes over ~5 calls). This is a *direct* observation rather than
  an inference and is version-proof. Rejected because it **writes to
  machine-wide shared preinfra on every invocation**, including when `preinfra
  development` runs as the `envinfra up dev` precondition, and every failure
  path then owns cleanup it may not get to run. Raised as design question Q2 —
  this is the one place I am overriding the brief, and I am doing it on evidence,
  so it should be ruled on rather than assumed.
- **`docker inspect registry` for the env var.** Cheap and exact but only works
  when the registry is local (true here, false in general), and it trusts the
  container's environment to reflect the running registry's behaviour — which
  measurement 2 above shows is *not* a safe assumption, since on `registry:3`
  the variable is present-and-meaningless. Rejected outright; not even kept as a
  fallback, because a second mechanism producing a second verdict is a worse
  outcome than one honest "could not determine".
- **A `--deep` flag / production-side only.** Unnecessary once the probe costs
  one request. The mod goal names `preinfra development`; that is where it lands.

---

## Part 2 — The check

**Scope gate.** The check runs when all of: `ctx.infra is not None` (matching
every other infra-dependent check — the inception-step-3 standalone run is a
no-op), `side == "development"`, `ctx.infra.foundation == "fixed"`, and
`ctx.infra.container_registry` is set.

**The request.** `DELETE https://<registry>/v2/preinfra-smoke/delete-probe/manifests/sha256:<64 zeros>`,
authenticated with the registry credential from the operator's Docker config,
with an explicit timeout. `preinfra-smoke/` is the namespace the doctrine
already reserves for registry verification; the repository does not exist and
the digest cannot exist, so the request is side-effect-free by construction.

**Scheme.** `https`, except for a `localhost` / `127.0.0.1` host, which uses
`http`. This mirrors Docker's own insecure-registry default rather than being a
test affordance, and it is what lets the integration test talk to a real
registry container without standing up TLS.

**Verdict table.** The status code alone is not trusted: a reverse proxy in
front of the registry can produce a bare `405` (method rejected) or a bare `404`
(wrong route), and reading either as a verdict is how a checker invents a
violation that does not exist. So a verdict requires the registry's own error
code in the response body.

| Observation | Verdict | rc |
| --- | --- | --- |
| `405` + `UNSUPPORTED` | capability **ABSENT** — the finding | **1 (fail)** |
| `404` + `MANIFEST_UNKNOWN` / `NAME_UNKNOWN` / `BLOB_UNKNOWN` | capability **PRESENT** | 0 |
| `202` | capability **PRESENT** (directly observed) | 0 |
| everything else | **could not determine** — printed, declined | **0** |

The `ABSENT` resolution line names `REGISTRY_STORAGE_DELETE_ENABLED`, the
compose block that sets it, and the consequence (`teardown.sh` leaks a tag per
release), per the brief.

### Why declined is rc 0 — the sarge's ruling on Q1

My draft made every can't-answer verdict rc 1. Sarge found the fact that
settles it, which neither of us had: `preinfra.py`'s own module docstring
carries an explicit design exclusion —

> *Container registry availability / reachability — whether the registry itself
> is up and serving (`docex containerize` surfaces that naturally).*

So the brief is asking for a registry probe on a command that **documents
registry reachability as deliberately out of its own scope**, and `preinfra
development` is the gate `envinfra up dev` runs. Uniform rc 1 would have made an
unreachable or un-logged-in registry block a dev stack that never touches a
registry — precisely the outcome that exclusion exists to prevent.

**The split is keyed on the exclusion, not on convenience:**

- **ABSENT is a *configuration* question.** The registry is reachable,
  authenticated, and refusing deletes with its own error code. In scope,
  definitely wrong, fails loudly.
- **Every can't-answer mode is a *reachability or auth* question** — no
  credential, unreachable, timeout, `401`, non-JSON body, a bare `405` from a
  proxy. Those are the excluded concerns, so they are **out of scope rather than
  unanswered**, and `containerize` is where they surface.

This does not retreat from mod 132's rule. *A verifier may decline to answer,
but it may not decline quietly* is honoured in full: every declined mode is
**printed, by name, with its own resolution line**. What is added is that
declining an out-of-scope question is a different act from failing an in-scope
one, and one exit code cannot express both.

It also survives the obvious objection — *then the check can never fail in
practice* — because the ABSENT arm genuinely fails and is pinned by the flag-off
integration test in Part 5. That test is the load-bearing artifact of this mod.

---

## Part 3 — The can't-answer enumeration

Every mode below resolves to **could not determine**: printed by name under a
distinct `Declined` heading, with its own resolution line, and **rc 0** per the
ruling above. None of them can read as "capability present". Each is named
individually so the operator is not left guessing which of fourteen things
happened — a *count* of declinations is not a declaration (see Part 6, where
mod 132's own code makes exactly that mistake).

**No credential to probe with**

1. Docker config file absent.
2. Config parses but has no `auths` entry for the registry host.
3. Entry exists but carries no inline `auth` — the credential lives in a
   `credsStore` / `credHelpers` external helper. This is a genuine
   can't-answer, not a bug: docex will not shell out to a credential helper.
4. `auth` present but not valid base64 / not `user:pass`.
5. Config file present but unparseable JSON.

**No response**

6. DNS failure on the registry host.
7. Connection refused / unreachable.
8. TLS failure (bad cert, wrong SNI).
9. Timeout — bounded explicitly, so a wedged registry cannot hang `envinfra
   up dev` forever.

**A response that cannot be read as a verdict**

10. `401` / `403` — credential rejected or lacks delete scope. Distinguished
    from "no credential", because the resolutions differ.
11. `405` **without** `UNSUPPORTED` — something between docex and the registry
    rejected the method; the registry may never have seen it.
12. `404` **without** a registry error code — a proxy 404, not a registry one.
13. `400 DIGEST_INVALID`, or any other status — includes the case where the
    probe itself is malformed, which must be loud rather than absorbed.
14. Body is not JSON, or is JSON without an `errors[].code`, where the verdict
    required a code.

**Not applicable, and deliberately silent**

Elastic foundation, and a project with no `container_registry`. These are not
declinations — the question does not apply. Elastic uses ECR, where deletion is
IAM-governed and teardown removes the repository wholesale; there is no flag to
probe. Printing "skipped" on every elastic invocation would be noise that
trains the reader to skim. The distinction being drawn: *declining to answer a
question that applies* must be printed; *a question that does not apply* need
not be. Confirmed as Q3.

---

## Part 4 — Components

Follows the existing `preinfra.py` client pattern exactly (`DnsResolver`,
`SSHClient`, `AWSClient`): a Protocol, one runtime implementation that is the
sole module permitted its transport import, and a scriptable fake in
`tests/conftest.py`.

**New**

- `src/docex/registry/client.py` — `RegistryClient` Protocol with one method,
  `delete_manifest(host, repository, reference) -> ManifestDeleteResult`, and
  the frozen `ManifestDeleteResult` dataclass: `status: int | None`,
  `error_code: str | None`, `failure: str | None`, `detail: str`. Exactly one of
  `status` / `failure` is set.
- `src/docex/registry/urllib_client.py` — the runtime impl. Reads the Docker
  config, builds the `Authorization: Basic` header, issues the request with a
  timeout. **The only module permitted to import `urllib.request` for registry
  HTTP**, mirroring the `boto3` / `dnspython` / `subprocess` discipline already
  documented in those clients' docstrings. Takes an optional
  `docker_config_path` (default `~/.docker/config.json`) so the integration test
  exercises the real credential-reading path against a temp config.
- `tests/integration/test_preinfra_registry_delete_real.py` — the positive
  control (Part 5).

**Changed**

- `src/docex/pipeline/preinfra.py` — `_check_registry_manifest_delete()`, a
  `registry: RegistryClient | None = None` parameter, the verdict mapping, and
  the `Declined` output block.
  **The module docstring's exclusion list must be rewritten, not appended to**
  (sarge's requirement 1). Today it reads as though nothing registry-shaped is
  checked on this side. It must state: what *is* now checked; that the
  delete-capability verdict is a **configuration** question and therefore in
  scope; and that **reachability and auth remain excluded** — which is the reason
  those modes decline rather than fail. A stale exclusion list is how the next
  reader concludes this probe was a mistake and deletes it.
- `src/docex/__main__.py` — construct the client on the three call sites that
  can pass `side="development"`: `_cmd_envinfra` (line ~204), `_cmd_preinfra`
  (line ~263), `_cmd_projinfra` fixed-up (line ~325). Lazily, mirroring `aws` /
  `ssh`. A `None` client on a branch that needs one is reported as a dispatcher
  bug, exactly as the `aws`/`ssh`/`dns` guards already do — so a forgotten call
  site fails loudly instead of silently skipping the check.
- `tests/conftest.py` — `FakeRegistryClient` + fixture, scriptable per
  `(host, repository)` with a recording `calls` list.
- `tests/unit/test_pipeline_preinfra.py` — the verdict-mapping and
  can't-answer tests, plus the fixture threading for existing dev-side tests.
- `doctrine_excerpts/container_registry.md` — see Part 6.
- `test_projects/PRE_CUT_CHECKLIST.md` § A.5 — the walker-facing note (sarge's
  requirement 2). A.5 is where a walker reads about the fixed registry, so that
  is where the pass-arm limitation goes.
- `CHANGELOG.md`.

**Untouched:** all doctrine, and every surfaces/health artifact from mods
125–132.

---

## Part 5 — Verification

### Red before green

Per the advance's standing rule, and the C.O.'s instruction to demonstrate red
for the honest failure *and* at least two can't-answer modes. Each of these is
written and observed failing against the unmodified verdict logic before the
mapping is implemented:

1. **The honest failure** — `405` + `UNSUPPORTED` → `ABSENT`, **rc 1**, output
   names `REGISTRY_STORAGE_DELETE_ENABLED`.
2. **Can't-answer: `401`** — the trap that concealed the original defect for
   several releases. Asserts **rc 0**, the mode named in the `Declined` block,
   and — the part that matters — that the output contains **neither** a
   capability-present claim **nor** the `ABSENT` finding.
3. **Can't-answer: no `auths` entry for the host** — the most likely real-world
   mode, and the one that would have blocked `envinfra up dev` under my draft.
   Asserts rc 0 and a named declination.
4. **Can't-answer: `405` without `UNSUPPORTED`** — the false-positive arm. A
   proxy rejecting DELETE must not be reported as a delete-disabled registry.
   This is the branch that, left unexercised, produces this advance's other
   recurring defect.

Each of 2–4 must be shown failing *before* the mapping exists — i.e. against a
verdict function that has not yet learned to distinguish them — so that the
distinction is demonstrated rather than asserted.

Plus unit coverage of the remaining enumeration in Part 3, the scope gate
(elastic and no-registry are silent no-ops; `ctx.infra is None` is a no-op), and
the dispatcher-bug guard.

### The positive control

`tests/integration/test_preinfra_registry_delete_real.py`, marked
`integration`, brings up **two real `registry:2` containers** on ephemeral
ports — one with `REGISTRY_STORAGE_DELETE_ENABLED=true`, one without — and runs
the real `urllib` client against both:

- flag **on** → verdict PRESENT (known-good input),
- flag **off** → verdict ABSENT (known-bad input),

so the finding branch is exercised against a registry that really is
misconfigured, and the pass branch against one that really is not. Both arms,
real software, no fakes. This is also the version pin from Part 1: it is what
goes red if a future registry image stops discriminating.

A third arm covers `401` by pointing the client at a registry whose credential
in the temp Docker config is wrong.

`registry:2` is already present locally and the containers are torn down in a
fixture, following the existing `tests/integration/` container patterns.

### Is the walk the probe's first real execution?

**No.** During design I ran the exact probe — authenticated
`DELETE /v2/preinfra-smoke/…/manifests/<zero digest>` — against the live
`registry.luxrnd.tech` and got `404 MANIFEST_UNKNOWN`, the PRESENT verdict. The
integration test then executes the shipped code against real registries in both
states. The smoke walk is confirmation, not first contact.

**The walk exercises the pass arm only.** This machine's registry already has
`REGISTRY_STORAGE_DELETE_ENABLED=true` (confirmed on the running `registry:2`
container), so a green walk proves the probe agrees with a correctly configured
registry and proves **nothing whatever** about the ABSENT branch. The fail arm
exists nowhere but the flag-off integration test. Per sarge's requirement 2 this
is written into `PRE_CUT_CHECKLIST.md` § A.5 as well as here, so a walker cannot
mistake a green walk for having tested the failure path.

### Suite counts

Baseline at `bd69ed6`: `pytest tests` → 1174 passed, 18 deselected;
`pytest tests -m integration` → 18 passed (run alone). Both re-measured after
implementation with `.venv/bin/python -m pytest`.

---

## Part 6 — Six-artifact alignment

| Artifact | Verdict |
| --- | --- |
| doctrine | **untouched.** The requirement is already stated. Two findings raised as Q4/Q5 below rather than edited. |
| `plans/core` | `masterplan.md` is the only core doc mentioning preinfra checks; updated in the documentation step. |
| `tables` | no change — this is not a compile concern. |
| `src` | new `registry/` client pair; `preinfra.py`; `__main__.py`. |
| `tests` | unit + a new integration module. |
| `doctrine_excerpts` | **no new `index.yml` entry.** The stated criterion is *resources*, and `container_registry` is already a resource with an entry; this mod adds a check on an existing resource, not a new one. Recorded here explicitly because on this artifact a silent no is indistinguishable from an oversight. |

### `doctrine_excerpts/container_registry.md` — and a claim I have to retract

The advance found nine of eighteen excerpt entries stale, so I read this one
rather than assuming. My first report called its closing citation a **dead
heading**. **That was wrong, and I withdraw it.** The line is

```
Doctrine reference: `infrastructure/cicl.md` § Container Registry.
```

and the real heading is `§ Container Registry and Service Images`. I asserted
"dead" from reading; measurement says otherwise. `classify_citation` slugifies
the cited words and accepts an anchor that *starts with* that slug plus `-`
— the deliberate **truncated-title** rule. `container-registry` is a prefix of
`container-registry-and-service-images`, so the citation classifies as
`truncated`, an authorial form the corpus sanctions. I confirmed it by forcing
the bounded form and watching `truncated` go 7 → 8 with the tool still green.

So I nearly filed a violation that does not exist — in the mod whose brief
warns me twice about exactly that, having just built a positive control to
prevent it in my own code. The lesson transfers: I applied the discipline to the
probe I was writing and not to the finding I was reporting. Recorded because it
is the more useful half of this section.

**What is actually wrong with the file** is a content gap, not a citation form:
it never points at
[`infrastructure/preinfra/container_registry.md`](../../../../doctrine/infrastructure/preinfra/container_registry.md),
which is the doctrine home for the *fixed* registry — the delete-enabled
requirement, the setup procedure, the GC procedure, and the reachability
verification. `cicl.md § Container Registry and Service Images` covers only the
`container_registry:` **field**. An agent running `docex why container_registry`
on a fixed project is sent to the field and never to the resource. That is the
fix, and this mod is the right one to make it: the delete capability this probe
checks is documented only in the file the excerpt omits.

While there, the citation is rewritten into the **bounded** form (whole citation
inside one inline-code span) so its heading becomes checkable — see below.

### Does mod 132's citation arm catch this instance? No — it *declines* it.

Asked, measured, and the answer is more interesting than a yes:

1. **The form is unbounded.** `prose_citations` yields a heading only when the
   path **and** the `§` sit inside *one common* inline-code span. Here the path
   is in backticks and `§ Container Registry` is bare prose, so the heading has
   no determinable end. `cite()` hits `head is None`, increments
   `stats["unbounded"]`, and returns. The **file** is verified to exist; the
   **heading is never classified at all.** Current run: `25 unbounded (file
   checked, heading not)`.

2. **So it would not have caught a genuinely dead heading here either** — which
   is the load-bearing point. The truncation rule is why *this* citation is
   valid; unboundedness is why no citation on that line would ever be checked.

3. **The house style of `doctrine_excerpts/` is systematically unbounded.**
   Fourteen of sixteen `Doctrine reference:` lines put the path in backticks and
   the heading in bare prose. `doctrine_excerpts/` was added to
   `DEFAULT_ROOTS` *because* a dead citation there motivated check 1b — and the
   directory's own convention places nearly every heading beyond that check's
   reach. That is the finding worth having.

4. **A defect in mod 132's code, mild but real.** `linkcheck.py`'s module
   docstring says the Declined block prints "anchors whose target is not
   markdown, citations whose filename matches more than one file, **and unbounded
   citations**." It does not. `cite()` increments the counter and returns without
   appending to `declined`, so unbounded is the **one** declined class that never
   reaches the block: you learn that 25 headings went unchecked, never *which*.
   Counted, but not named — a weaker thing than the docstring claims, and the
   only reason the omission in item 3 is invisible in practice.

   Raised, not fixed. mod 132 is closed, and naming 25 previously-silent
   citations in every `cohere` run is an output-volume decision that belongs to
   whoever owns that tool's contract.

**Verified fix, both arms.** Converting this line to the bounded form
``` `infrastructure/cicl.md § Container Registry and Service Images` ``` moves it
from `unbounded` into `exact` (measured: unbounded 25 → 24, exact 238 → 239).
That is a strict improvement — an unverifiable citation becomes a verified one —
and it is why the rewrite is worth doing beyond cosmetics.

---

## Rulings at design review

Recorded so they are not re-litigated. Design approved with one substantive
change (Q1).

- **Q1 — RULED: declined ≠ failed.** ABSENT → rc 1; every can't-answer mode →
  printed in the `Declined` block at rc 0, keyed on `preinfra.py`'s documented
  reachability exclusion. Full reasoning in Part 2. Two requirements attached:
  rewrite the docstring's exclusion list (Part 4), and state the walk's pass-arm
  limitation where a walker reads it (Part 5 + `PRE_CUT_CHECKLIST.md` A.5).
- **Q2 — APPROVED: the one-request inference**, pinned exactly as proposed by a
  flag-off integration test asserting ABSENT. A probe that mutates
  infrastructure shared across projects is not a probe.
- **Q3 — CONFIRMED:** elastic and no-registry stay silent.
- **Q4, Q5 — taken by the operator.** Both are doctrine and neither is touched
  here. Q4 (the `registry:3` version qualifier) gets a clause; Q5 (fixed
  projects permitted a registry that cannot support `teardown.sh`) gets its own
  brief, being a hole in what "fixed foundation" claims to support rather than a
  sentence to patch.
- **`index.yml` — no entry, agreed.**

The original questions are preserved below as the record of what was asked.

---

**Q1 — Does a failed or undetermined verdict block `envinfra up dev`?**
`_cmd_envinfra` gates `up` on `preinfra development` returning 0, so any rc-1
verdict here newly blocks dev bring-up over a capability that only `teardown.sh`
and garbage collection use. The narrow biting case is a fixed project *before*
its first `docker login`: dev builds locally and never touches the registry, so
that operator would be blocked by something dev does not need.
*My recommendation: uniform rc 1 anyway.* Preinfra's job is to say whether
prerequisite infrastructure is in the needed form; a registry that cannot delete
is not. The fix is one env var or one `docker login`, `preinfra` already hard-fails
for a missing `docex-ingress` bridge, and a verdict that changes meaning
depending on which command invoked it is its own trap. The alternative — rc 1
under explicit `docex preinfra`, a printed block under the `envinfra` gate — buys
convenience at the cost of the check being weakest exactly where it runs most
often. I want this ruled on rather than assumed, because it changes the
behaviour of a command the operator runs constantly.

**Q2 — Mechanism: the one-request inference (recommended) or a synthetic
manifest push?** Part 1 has the full argument and the evidence. I recommend the
one-request probe with the integration test as its version pin. This overrides
the brief's recommended shape on the strength of the measurements, which is why
it is here.

**Q3 — Confirm elastic and no-registry stay silent** rather than printing a
skip line. Reasoning in Part 3.

**Q4 — Doctrine finding (operator's; not touched).** The doctrine's registry
prose is version-specific in a way it does not admit.
[`container_registry.md`](../../../../doctrine/infrastructure/preinfra/container_registry.md#registry-container)
states "Without the flag every `DELETE /v2/<repo>/manifests/<digest>` returns
`405 Method Not Allowed`". Measured: true on `registry:2`, **false on
`registry:3`**, where the flag is a no-op and manifest `DELETE` returns `202`
regardless — and where tag deletion also returns `202` against a
delete-disabled registry that `registry:2` would `405`. The doctrine pins
`registry:2`, so nothing is wrong today and this is not a defect. It is a
landmine for whoever bumps the image: the flag would silently become
unnecessary, and the sentence would silently become false. Worth a version
qualifier.

**Q5 — Doctrine question (operator's).**
[`cicl.md § Container Registry and Service Images`](../../../../doctrine/infrastructure/cicl.md#container-registry-and-service-images)
permits a fixed project's `container_registry` to be "a public registry (Docker
Hub, ghcr.io, etc.)". Neither implements the Registry V2 manifest-delete API on
the terms `teardown.sh` assumes, so such a project's teardown cannot work and
this probe would report `could not determine` against it forever. Either the
permission is narrower than stated, or fixed teardown has a documented hole.
Flagged, not resolved — I have no mandate over doctrine and this is larger than
my mod.
