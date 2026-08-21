# Docex Process

How to develop updates for docex.

`docex` is a little unlike other software packages. It automates parts of the *development and release* processes themselves. This means that both development and testing of `docex` diverges from standard doctrine practices. Furthermore, the doctrine and `docex` intertwine substantially. Often a change to one provokes a change in the other.

The rough, toplevel process for change is this:
1. **Alter the doctrine** - If neccessary, change the actual doctrine wording itself. `docex` is *driven* by the doctrine (from a certain perspective the doctrine forms the product documentation for `docex`) so doctrine should always change first.
	1. Always ask the human operator before altering doctrine files! The language of the doctrine is carefully chosen and often every word is load bearing.
2. **Update `docex` to match** - Change the actual code and function of `docex` using regular mod cycles. Taken all together, the sum of mod cycles needed to complete all needed changes forms an "advance". Cutting and releasing is expensive and disruptive, so we always want to bundle as many changes as possible into one advance, even if they split across many mod cycles.
	1. Each cycle will include a design document, implementation steps, sub-agent execution, and the running of standard automated tests at the end as per usual.
	2. Always add good tests for new additions. Unit tests by default; add an integration test when behavior crosses a real boundary (docker / AWS / git).
	3. There is no "manual test" phase for `docex` mod cycles. Do not pause for operator manual tests.
	4. When checking for drift after a mod implementation, check all [artifacts](#additional-artifacts) for alignment.
3. **Run expensive tests** - When mod cycles are complete, run the "expensive" tests. These include:
	1. End-to-end integration tests — see [§ Running the automated tests](#running-the-automated-tests) for the invocation, which is **not** the obvious one.
	2. The ["test project" tests](#test-project-tests), which call for you to manually step through critical `docex` steps for two distinct sample projects with different foundations.
4. **Cut a new version** - a `docex` change ships in a doctrine-wide release; see [`RELEASING.md`](../../../RELEASING.md) and § [Versioning & Releasing](#versioning--releasing) below.

## Docex Documentation

The docex project structure does not adhere to the doctrine-defined standard by design. This means the `src` directory is rather different from a regular doctrine-adherent project and that the project documentation also has slightly different structure.

Toplevel structure is the same:
```
plans
├── modifications
├── core
└── references
```

The interiors of `modifications` and `references` are also the same. `core`, however, is different. It is simply a flat folder containing markdown files (no deeper structure corresponding to modules) because `docex` is not hexagonally-architectured and has no per-module docs to host. It still serves the same purpose of holding "core planning documents":

- [`masterplan.md`](./masterplan.md) — the toplevel architecture / design proposal. Note the framing at the top of that file explaining why a `docex` masterplan reads differently from a standard one.
- [`docex_process.md`](./docex_process.md) — this file. The development process for `docex` itself.
- [`compiler.md`](./compiler.md) — the CICL compiler: service expansion, magic refs, validation, and the emit layer.
- [`release_flow.md`](./release_flow.md) — the release and rollback paths: preconditions, the ephemeral worktree, and the per-foundation apply.
- [`test_projects.md`](./test_projects.md) — the two nested smoke-test projects: why two foundations, their shape, git structure, and commit cadence.

### Additional Artifacts

Unfortunately, the unique nature of `docex` means that it has six successive layers of artifacts which **must** be kept aligned across updates. Drift between them is an extreme hazard.

| Artifact | Role |
| -------- | ---- |
| `doctrine/.../*.md` | The rule of record. The *why* and the canonical statement. |
| `docex/plans/core/*.md` | Architecture and design docs for `docex`. This is the *how*. |
| `tables/roles/*.yml` | Transfer tables — how a role/engine compiles per foundation. |
| `src/docex/**` | Compiler / orchestration code that executes the rule. |
| `tests/**` | Proof the executor matches the rule. |
| `doctrine_excerpts/*.md` + `index.yml` | The prose `docex why <resource>` serves. A *restatement* of the doctrine that long drifted silently — until mod 140 added `tests/unit/test_doctrine_excerpts_index.py`, which now checks its `index.yml` keys against `shape.md`'s resources. |

The sixth is the one most easily forgotten, precisely because nothing fails when it goes stale: it was long the only artifact in the list with no automated consumer. When a doctrine change introduces, retires, or renames a **resource**, `index.yml` needs the corresponding entry added, removed, or moved in the same mod. Mod 110 drifted here; mod 111 added the missing `codebase` entry and wrote this row. Mod 140 later gave the artifact its first automated consumer (see the mod-140 note below), so "no automated consumer" now describes its history, not its present.

**What earns an entry.** `doctrine_excerpts/` indexes **infrastructural
resources** — the nouns a deployed stack is physically made of, tracking
`shape.md`'s `[resource]` notation. It does **not** index CICL *fields*, and it
does **not** index *roles*. Fields are specified by `cicl.md § Service Fields`;
roles are served by `docex role <name>`, which reads `tables/roles/*.yml` and is
therefore generated rather than restated — it cannot drift the way this artifact
can. Adding a hand-maintained third restatement of something two artifacts
already serve correctly buys nothing and creates a new silent-drift surface.

Applying that criterion at advance 005 (mod 118): **`uses` gets no entry** — it
is a relation between resources, not a resource, and its two predecessors
`depends_on` and `consumes` had no entries across their entire lifetimes, so
merging two non-entries yields a non-entry. **`clock` gets no entry** — it is a
role; `docex role clock` already serves it correctly, and no other role
(`web`, `worker`, `cache`, `relational_db`, `object_store`) has an entry either.
The retired `scheduler` role had none, so its deletion removed nothing. Both
decisions are recorded here rather than left implicit, because on this artifact
a silent "no" is indistinguishable from an oversight.

Applying it again at advance 006 (mods 125–131): **`surface` gets no entry**, and
the same answer covers `api_styles`, `health.sh`, and the container probe — stated
together so the next mod does not re-ask it one noun at a time. Three reasons, each
ruling out a different wrong answer. **Nothing is deployed for a surface:** it has
no container, no DNS name, no ARN, and no `[resource]` box in `shape.md` —
`api.worker`'s two surfaces are two documents in the repo and one process. **It is
a CICL field**, which this criterion excludes by name; `cicl.md § Surfaces` and
§ Service Fields specify it, and a third hand-maintained restatement would buy
nothing. And **a probe is a property of a resource, not a resource** — the one
sentence it earned went into the existing `core_service.md` entry rather than a new
one. Mods 126, 127 and 128 each concluded independently that they introduced no
resource; mod 128 recorded its row expressly so this verdict could aggregate them.

And once more at mod 133: **the registry manifest-delete probe gets no entry.**
`container_registry` is already an indexed resource; the mod adds a *check on* it,
and a check is no more a resource than a probe is. The mod did edit that entry —
but for an **omission**, not a contradiction: it described only the
`container_registry:` field and never pointed at
`infrastructure/preinfra/container_registry.md`, the doctrine home of the fixed
registry's setup, its delete requirement, and its GC procedure. So a `docex why
container_registry` on a fixed project reached the field and never the resource.
That is the same class as `codebase.md`'s missing `health.sh` below, and it is the
fifth such omission this advance found.

**A verdict that was retracted, which is worth more than the four that stood.**
Mod 133 first reported that entry's closing citation as a **dead heading** —
`cicl.md § Container Registry` where the real heading is § Container Registry and
Service Images. That was wrong. `linkcheck.py`'s `classify_citation` accepts an
anchor that *starts with* the cited slug plus `-`, its deliberate truncated-title
rule, so the citation classifies as `truncated` and is valid. The claim was
asserted from reading and withdrawn on measurement. **Sweeping this artifact by
eye produces false positives as readily as false negatives**, and the check is
cheap: force the citation into bounded form and watch which bucket the count moves.

**Bounded vs. unbounded citations, which decides whether a sweep can help at all.**
`linkcheck.py` classifies a citation's heading only when the path **and** the `§`
sit inside one common inline-code span. `doctrine_excerpts/`'s house style puts the
path in backticks and the heading in bare prose, so **fourteen of sixteen**
`Doctrine reference:` lines are counted `unbounded` — file verified, heading never
checked. This directory is in `linkcheck`'s roots *because* a dead citation here
motivated that check, and its own convention places nearly every heading beyond
that check's reach. Worse, `unbounded` is the one declined class that never reaches
the tool's `Declined` block: `cite()` increments a counter and returns, so a run
reports that N headings went unchecked and never *which*. Mod 133 converted its own
line to the bounded form (`unbounded` 25 → 24, `exact` 238 → 239); doing the
remaining thirteen would turn a silent count into thirteen checked citations and is
the cheapest available improvement to this artifact's verifiability. Mod 140 did
exactly that across the whole directory: the overhaul's rewrites put every
`Doctrine reference:` footer's `§` inside the path's inline-code span, taking the
directory to **0 unbounded** citations (34 checked — 33 exact / 1 truncated) and
moving the repo-wide count from 25 unbounded / 250 exact to 10 / 279. (This
converts the footers to bounded form; the separate half of that finding —
enumerating unbounded citations in `linkcheck` itself — remains booked.)

**How this artifact is swept, and the limit that was found the hard way.** Three
mods of advance 006 grepped all eighteen excerpts for
*health / contract / surface / curl* and got zero hits, and concluded nothing
contradicted the new model. That reasoning is sound for a **changed** claim and
structurally blind to an **omission**: `codebase.md` listed the codebase's shims as
"`build.sh` / `test.sh` / `migrate.sh`" and was wrong by omitting `health.sh` — a
line containing none of the four grep terms, only three filenames. **A grep for the
new thing cannot find a list that lacks it.** So a sweep of this artifact needs a
second pass that reads every entry naming a set — files, stages, roles, fields —
and asks whether the set is still complete. The vocabulary grep cannot answer that
question and will keep returning zero while the omission stands.

**Advance 006's sweep found defects in half of this directory, which is what this
row is for.** Only **one** of them was caused by the advance. The tally, because the
proportion is the argument:

| Defect | Files | Found by |
| --- | --- | --- |
| Dead prose citation to an anchor the doctrine rewrite deleted | `service_discovery.md` | the advance's own vocabulary grep |
| Shim list missing `health.sh` | `codebase.md` | the completeness pass |
| **Inverted** fixed-side traefik topology — "machine-wide traefik", the opposite of the project-tier traefik `shape.md` specifies | `reverse_proxy.md`, `cert_manager.md`, `host_machine.md`, `network_web.md` | the completeness pass |
| Stale subdomain scheme (a `domain:` field that no longer exists; no project segment; `prod → www.`) | `dns.md`, `registrar.md` | the completeness pass; **booked**, not fixed |
| `example.env` described as compile-emitted and committed — mod 092 deleted that emit | `secrets.md` | the completeness pass; **booked**, not fixed |
| `docex up` for `docex envinfra up` | `environment_config.md` | the completeness pass; **booked**, not fixed |
| Underscored, three-segment compiled identities — residue of advance 005's rename, which gave the identity a **fourth** segment | `service_discovery.md`, `network_web.md`, `network.md` | mod 134; fixed |

Over half of the eighteen entries, and **the vocabulary grep found exactly one of them.** The
inverted topology claim had propagated to four files and predated the advance
entirely; the stale subdomain scheme predates `apex_domain`. Two lessons follow.
First, an artifact with no automated consumer does not drift *at* the rate its
subject changes — it drifts at the rate nobody looks, so a sweep should expect to
find damage from releases other than the one it is sweeping for. Second, **the
completeness pass is not optional and is not a formality**: every defect above except
that one came from it — count the rows of the table, not this sentence. The four still
open needed a rewrite rather than a corrected clause, so they were folded into the
full overhaul below rather than booked separately.

Mod 134 then audited all eighteen entries against the doctrine rather than against a
term list, and found the drift is far wider than the rows above: **15 of 18 carry
defects and three actively misinstruct.** That audit is booked as a full overhaul at
[`008_housekeeping/doctrine_excerpts_overhaul.md`](../advances/008_housekeeping/references/doctrine_excerpts_overhaul.md),
which subsumes the four still-open defects above. **Mod 140 landed that overhaul.**
All 18 entries were audited against current doctrine and rewritten; the four
still-open defects above are fixed, `aws_account`'s one-project-per-account
inversion and the pre-`apex_domain` `www.` subdomain scheme in `dns` / `registrar`
were corrected, and `secrets`' deleted-`example.env` restatement (mod 092) was
rewritten to the `docex secrets scaffold` model. `vpc` was retired (no `[vpc]`
resource; its content folded into a new `master_network` entry), `index.yml`'s
`network_web` / `network_internal` keys were renamed to `web_network` /
`internal_network` to match `shape.md`, and five missing resource entries were
added: `master_network`, `web_demux`, `observability_backend`, `telemetry_sidecar`,
`nat_gateway`. Two findings belong here rather than
there, because they are about *this* process and not about the excerpts. First, **94% of
the defects predate advance 006 and 14 of them trace to a single commit** — the
directory's original authoring — which is the drift-at-the-rate-nobody-looks claim
measured rather than asserted. Second, `git blame` **flatters** a sweeping advance:
mod 131 edited two of these lines without fixing the stale token already on them, so
blame attributes months-old content to the sweep that touched it. An advance cannot
use blame to bound what it is responsible for.

**Applying the "what earns an entry" criterion at mod 140.** Two `shape.md`
resources were deliberately left without an entry, recorded here so a silent "no"
is not mistaken for oversight. **`repo` gets no entry** — `cicl.md § Git Repo URL`
states it "currently only serves a documentary role" and is unmanaged prerequisite
infra, so a `docex why repo` would restate a field, not describe a deployed
resource anyone provisions. **`configurable_vars` gets no entry** — it is the
*aggregate* of TTE vars, secrets, and config, already served by the `secrets` entry
plus the generated `docex secrets` / `docex config` tooling; a third
hand-maintained restatement is exactly the silent-drift surface this criterion
refuses. (`ecs_cluster` is *not* a `shape.md` `[resource]` token and so was never a
candidate for an entry — the table row is not the notation the criterion tracks.)
Separately, `codebase` and `secrets` remain indexed although neither is a
`[resource]` token — `codebase` is the unit-of-code concept mod 111 deliberately
added, `secrets` a source of `configurable_vars`; both are useful `docex why`
lookups and are the documented `EXCEPTIONS` in the new consumer test.

Keep them aligned. Fixing the code while leaving the rule stale (or vice versa) is the failure mode this process guards against.

## Running the automated tests

Two invocations, and **three ways to get a number that looks like an answer and is
not.** All three were paid for during advance 006; none of them fails loudly.

```sh
python -m pytest tests                  # the default suite
python -m pytest tests -m integration   # the integration suite — run ALONE
```

1. **`python -m pytest`, never bare `pytest`.** The bare binary cannot collect this
   suite. It reports a deselect count one short of the real one and runs nothing — at
   the time of writing 21 integration-marked items exist, and the bare binary's near-miss
   is exactly what makes it believable. Re-derive rather than trust this number:
   `python -m pytest tests -q` prints the deselected count, and
   `python -m pytest tests -q -m integration` prints how many actually run. The
   two must agree.
2. **The default suite is `tests`, not `tests/unit`.** This once hid a real hole:
   sixty-plus fast compile tests lived under `tests/integration/` carrying **no**
   marker, so the conventional pair `pytest tests/unit` + `pytest tests -m integration`
   skipped them from both sides — mod 128 found twelve tests red behind a green
   report that way. Mod 139 relocated those compile tests to `tests/unit/` and added
   `tests/unit/test_collection_partition.py`, a guard that asserts the two buckets
   **partition** the suite
   (`collected(tests/unit) + collected(-m integration) == collected(tests)`), so a
   test invisible to both standard invocations — or double-counted by both — now
   fails loudly wherever it lives. The hole is closed and guarded; `pytest tests`
   remains the canonical full suite regardless.
3. **`-m integration` must run alone.** Run concurrently with anything else it
   produces five convincing false failures in migrate, up/down and build — they
   contend for real docker state.

The common shape is this advance's own recurring defect arriving in the measurement
apparatus rather than the code: *something that could not have detected the failure
reported success.*

## Versioning & Releasing

`docex` no longer carries its own independent version or cut procedure. As of
doctrine version `1.3.0` the version is **doctrine-wide** — doctrine prose,
skills, and `docex` advance together under one number — and a `docex` change
ships as part of a doctrine release. The full procedure (version semantics, the
four synced artifacts, the tag, the image build) lives in
[`RELEASING.md`](../../../RELEASING.md). Cuts now tag `v<v>`, **not** the old
`docex-v<v>` form: the namespacing that once anticipated "a bare version tag
would collide if the doctrine is ever versioned" is now realized by the unified
scheme, so the one version owns the bare tag. Historical `docex-v*` tags remain
only for archaeology.

Two `docex`-specific properties the release process relies on:

- **The image is the unit of determinism.** The image tag always equals the
  version — no floating tags (see [masterplan.md § Distribution](./masterplan.md#distribution)).
  A version is only meaningful once its image is built, and `RELEASING.md` builds
  `docex:<v>` on every cut — even a no-op `docex` rebuild on a doctrine-only
  release, to keep the *doctrine version ⟺ image* invariant.
- **Built images are not git-tracked** — they live in the local Docker store, so
  the determinism promise ("a project pinned to a version gets identical output
  forever") rests on rebuilding a version's image from source. The `v<v>` git
  tag is what makes that source recoverable — without it, finding "the commit
  that was 1.2.0" is archaeology.

### Git

Trunk-based: commit directly to `main`, consistent with the doctrine's
[branch conventions](../../../doctrine/infrastructure/version_control.md#branch-conventions)
and how the rest of this repo is maintained.

## Test Project Tests

Two doctrine-faithful smoke-test projects live at [`docex/test_projects/`](../../test_projects/): one per foundation. Before cutting a minor or major version, the operator walks both through their full release paths (`compile → containerize → release stage → stagetest → release prod → teardown`) against real infrastructure. The procedure — including the pre-walk doctrine-conformance audit — is in [`docex/test_projects/PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md). Patch cuts skip this; minor and major cuts require it green.

For the architecture and design of those projects (why two foundations, code identity, git structure, commit cadence, cut lifecycle), see [`test_projects.md`](./test_projects.md).