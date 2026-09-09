# Proposal: Parallel Test Environments

**Status:** proposal / design exploration — not yet a mod.
**Goal:** let a developer run *N* independent `test` environments on one fixed
machine at once, so the slow, no-mock flow/integration tier can be sharded
across them and run in parallel.

## Motivation

Flow tests are the longest-running tests we have and, by design, they do **not**
mock infrastructure — they exercise the composed codebase against real backing
services (real test DB, real cache), stubbing only external-system gateways. See
[hex_overview.md § Tests](../../../../../doctrine/hexagonal_architecture/hex_overview.md#tests)
and [tests.md § Codebase-Level](../../../../../doctrine/infrastructure/tests.md).
That makes them the natural target for parallelism, and the natural unit of
parallelism is a whole `test` stack: full-stack isolation handles *every* case
(destructive truncation, migration-exercising tests, hardcoded IDs) with
certainty, rather than relying on per-worker data-namespacing discipline inside
a single shared stack.

The doctrine today fixes exactly four environments — `dev`, `test`, `stage`,
`prod` — and asserts it across
[infrastructure.md](../../../../../doctrine/infrastructure/infrastructure.md),
the lexicon, `configurable.md`, and `cicd.md`. "Heavier test topology" sits
under that file's **Deferred** list. This proposal is therefore a **doctrine
change**, not merely a `docex` change — but a contained one, because of how the
mechanics already fall out (below).

## Why this is mechanically cheap

Every physical resource name is already `{project}_{env}_…`
(`compile.py:_global_service_name`, `_network_name`, `codebase_global_name`,
`_env_subdomain`). Config/secrets/tte are keyed `infra/<kind>/<env>.env`. And
**nothing publishes a host port** — `web` services are reached by the reverse
proxy over the docker network, backing services publish nothing
([networks.md:46](../../../../../doctrine/infrastructure/specifics/networks.md),
`emit/compose.py`). So the collision surface between two concurrent `test`
stacks is *not* ports and *not* the `.env` files. It is purely **names** — and
`env` is already the segment that distinguishes names.

That is the crux of the design: we make the shard part of the **name-generating
identity**, reusing the existing interpolation, rather than bolting on a second
namespacing mechanism (which is what the `--project-name` override in
`docex check` does today — and it misses exactly the resources compose does not
re-prefix; see [§ Subsumes an existing latent bug](#subsumes-an-existing-latent-bug)).

## Design

### 1. A new axis: `env_number`

Add an *instance* segment to interpolated physical names, analogous to
`replicas` but at the environment level:

```
{project}_{env}_{env_number}_{codebase}_{service}
```

Rules, mirroring `replicas` exactly:

- **Default is 1, and instance 1 emits NO suffix.** Just as a single-replica
  service gets no `-N`, a single-instance env emits today's names byte-for-byte.
  The feature is purely additive: existing `dev`/`test`/`stage`/`prod` output is
  unchanged until someone asks for parallelism.
- The segment appears only on **physical resource names** — volumes, networks,
  container names, the compose project name.

### 2. Env identity stays `test` — this is the payoff

The instance is **not** a new environment string (`test_a`). The environment
remains `test`; only the instance number differs. Consequently everything that
keys off the *env* needs **zero** special-casing:

- `_env_foundation("test")` → still `fixed`.
- `aggregate(env="test")` and the `infra/{config,secrets,tte}/test.env` lookups
  → **shared across all instances**, which is exactly what we want (no operator
  hand-maintains N identical secret files).
- The Mod 054 routing exclusion (`compiled.env != "test"`) → unchanged.

Only physical names take the `{k}` segment. There is no "strip the shard back to
base `test`" logic anywhere, which is the wrinkle the distinct-env-string
approach (`test_a`) would have forced into every `.env` and foundation lookup.

### 3. Usage lives outside `infra.yml` — it is a runtime parameter

`replicas` belongs in `infra.yml` because production replica count is a **shape**
property. Test-instance count is not: it is "how many shards does *this machine*
want right now," which depends on the developer's box (RAM especially — see
[§ Costs](#costs-the-honest-price)) and their current need. Baking it into
committed infra.yml would hardcode a machine-dependent knob into project shape.

So the instance is a **compile/runtime parameter**, never a declared field:

```
docex test --instances N       # dense 1..N, ephemeral fleet run
docex up   test --instance k   # persistent single instance, for inspection
docex down test [--instance k | --all-instances]
```

Mechanically, `compile(env="test", instance=k)` →
`infra/output/test/i{k}/docker-compose.yml` with names `{project}_test_{k}_…`;
`--instances 1` (the default) emits no suffix and writes to today's
`infra/output/test/`. The compose project name per instance is
`{project}-test-i{k}` (`env_compose_project`) so `up`/`down`/`ps` address each
stack independently.

### 4. The test web network must be re-tiered (env-tier, per-instance)

This is the one resource the `env_number` axis cannot namespace on its own, and
it must be handled explicitly.

`run_test` does a full `compose up -d` of the default-profile stack
(`test.py:79`), not just backing services + exec. Mod 054 stripped Traefik
labels from `test` web services but **left them on the `-web` network**
(`compose.py:449-456`: *"remain on the `-web` network"*). That network,
`{project}-test-web`, is emitted `external: true` and is **owned by projinfra**
— one of the "four `-web` networks" the project-tier stack creates
(`compose.py:750-760`, `pipeline/projinfra.py`, `__main__.py:286`).

projinfra is a **different infrastructure tier** than the env-tier `env_number`
axis. Two test instances would both `compose up` core containers onto the *same*
shared `{project}-test-web` bridge and both register the same network alias
`{project}_test_{svc}` — duplicate aliases, nondeterministic resolution,
isolation gone.

**Resolution — finish what Mod 054 started.** Mod 054 established that `test` is
never routed, never browsed, no TLS, no Traefik. A network with no ingress
purpose has no reason to be projinfra-owned or `external`. So for `test`, emit
the web network as an ordinary **env-tier, per-instance** bridge
(`{project}-test-{k}-web`, `external: false`) directly in the instance's compose
file — exactly like the `-internal` bridge. This keeps any flow test that
reaches the live `-web` container over HTTP working, makes every instance fully
self-contained, and removes `test`'s last dependency on projinfra. It is a small,
principled extension of "test isn't routed" from *labels* to *ownership*.

(See [open question (a)](#open-questions): if flow tests drive the app
in-process rather than over HTTP to the live container, the core containers in
`test` are dead weight and could be profiled out entirely — lighter still — but
that is an optimization, not a prerequisite for this axis.)

### 5. Lifecycle: count-based, dense deterministic IDs, self-healing

The instances are **fungible anonymous shards** for the flow-test use case, so
the developer specifies a **count**, never IDs. Developer-chosen IDs would push
bookkeeping onto the human, which is precisely what creates orphans.

An undetectable orphan requires two things together: **monotonic IDs**
(each run grabs the next-highest free number, climbing forever) **and** no
reclaim path. Kill either and the orphan class dies. The design kills both:

- **Dense, deterministic IDs.** `--instances N` always uses `1..N` — never "next
  free." A stack's compose project name is therefore always derivable
  (`{project}-test-i{k}`); an interrupted run leaves stacks at *known* names.
- **Reaper as preflight.** Because the pattern is deterministic,
  `docker compose ls --filter name={project}-test-i` enumerates every test
  instance on the host. `docex test` runs this *before* starting and reaps
  anything left by a prior interrupted run
  (*"stale test instances i3, i7 — reaping"*). Every run self-heals; even a
  SIGKILL orphan is gone by the next invocation.
- **`finally`-teardown** stays (already in `run_test`), so the only way to
  orphan at all is a hard kill — which the preflight then mops up.

IDs still *exist as derivations*, for two non-allocation purposes only:

- **Debug reattach.** On failure, tear the passing instances down but **leave
  the failed instance up**, and print `docex down test --instance 5` to reclaim
  it. The developer inspects that instance's live database. Deterministically
  named → a debug artifact, not an orphan.
- **Manual single-instance** via `docex up test --instance k` for hands-on work.

### 6. Bridging docex → project test code

docex does not own the tests (the doctrine is emphatic that developers write
their own). The bridge must therefore be a **stable, documented, one-way
contract**, on the exact model of the `stagetest` injection
([tests.md § Injected environment](../../../../../doctrine/infrastructure/tests.md)),
where docex injects `STAGING_URL`/`PROJECT_VERSION` and the project's tests read
or ignore them.

The subtlety that makes this small: the project test code needs two things from
N instances, but **only one crosses the boundary**.

- **Isolation needs no bridge — it is already handled, invisibly.** Each instance
  is a whole stack, so its postgres is `{project}_test_{k}_appdb`, and the
  `DATABASE_HOST` env var the compiler injects into instance `k`'s exec container
  *already points there*. The test code connects the way it always does, via the
  provided connection parts, and lands in its own instance's DB automatically.
  The test author writes zero isolation logic and need not even know the instance
  number exists. This is the whole reason to do isolation at the compile/infra
  layer instead of in fixtures.

- **Distribution is the only thing the bridge carries.** docex injects two env
  vars into each instance's `test.sh` run:

  | Variable | Source | Purpose |
  | --- | --- | --- |
  | `DOCEX_TEST_INSTANCE` | the `k` docex is running | This container's shard index (1-based). |
  | `DOCEX_TEST_INSTANCES` | the `N` from `--instances` | Total shards, so `test.sh` computes its slice. |

  This contract is one-way and stable — the project reads or ignores it; adding
  to it is a doctrine change, never a project change.

Two things the doctrine should **recommend but not mandate** (staying inside
"tests use whatever tooling suits the codebase"):

1. **How to split** — a default such as `pytest-split`
   (`--splits $DOCEX_TEST_INSTANCES --group $DOCEX_TEST_INSTANCE`) or an xdist
   distribution. Recommend one; require none.
2. **Shard only the slow tier.** Do not fan the *whole* suite across N stacks —
   paying N× stack-bringup to also parallelize millisecond unit tests is waste.
   The recommended pattern: fast tiers (unit, contract) run **once** (e.g. on
   instance 1), and only the no-mock flow/integration tier is distributed across
   `1..N`. `test.sh` implements this with a trivial
   `if [ "$DOCEX_TEST_INSTANCE" = 1 ]` branch.

**Division of labor:** docex owns *isolation* (per-instance compilation) and
*coordinates* (the two injected vars); the project owns *distribution* (which
slice, which tiers). docex never parses tests; the project never wires databases.

## Subsumes an existing latent bug

`docex check` already runs a throwaway `test` stack concurrently with a real one
by overriding the compose `--project-name` (`test.py:57-60`, `pipeline/check.py`).
But compose only re-prefixes *auto-named* resources — it does **not** re-prefix
the explicit `name:` volumes/networks and `container_name` fields the emitter
writes (`emit/compose.py` named volumes, non-web networks, otelcol + replica
container names). So two truly-concurrent checks on one host have a latent
**DB-volume collision** on `{project}_test_{svc}_data` today.

The `env_number` axis **replaces** that half-measure: it namespaces *every*
resource including the explicit-name ones, because they all interpolate the
instance segment. This feature therefore closes an existing latent bug rather
than adding a parallel mechanism beside it. (Verifying whether checks are
serialized today, and thus whether the collision is currently reachable, is
[open question (b)](#open-questions).)

## Costs — the honest price

Full-stack isolation is the source of the "handles all cases with certainty"
guarantee, and it is not free:

- **N full stacks** = N postgres + N of every core container + N otelcol
  sidecars. This is **RAM-bound, not just core-bound** — which is exactly why
  `--instances` is a per-invocation runtime knob sized to the developer's box,
  not an `infra.yml` field.
- **migrate runs N times** (once per instance's own DB), before each instance's
  `test.sh`. This is the price of per-instance DBs versus a single shared one.
- The preflight reaper is also what keeps a crashed fleet from piling memory
  until the machine chokes.

## Touch-points (for the eventual implementation.md)

- `cicl/compile.py` — thread an `instance` param through `_global_service_name`,
  `_network_name`, `codebase_global_name`, output-dir selection; default-1
  emits no suffix.
- `emit/compose.py` — re-tier the `test` web network to an env-tier,
  per-instance, non-external bridge (§4).
- `orchestrate/test.py` — `--instances N` loop: preflight reap, compile+up+
  migrate+test.sh per instance, inject `DOCEX_TEST_INSTANCE`/`_INSTANCES`,
  finally-teardown, keep-failed-up.
- `orchestrate/_common.py` — `env_compose_project` gains an instance suffix;
  `up`/`down` gain `--instance` / `--all-instances`.
- `__main__.py` — the `--instances` / `--instance` flags (argparse `choices`
  for env are untouched — env stays `test`).
- A reaper helper keyed on the deterministic `{project}-test-i` name pattern.
- Doctrine: `tests.md` (the injection contract + recommended split/tier
  pattern), and the four-env framing in `infrastructure.md` / lexicon /
  `configurable.md` (the axis is env-instance, not a fifth env).

## Open questions

- **(a)** Do flow tests hit the live `-web` container over HTTP, or drive the app
  in-process via a test client? If in-process, the core containers in `test` are
  dead weight and could be profiled out (lighter still); if over HTTP, they must
  stay up and on the per-instance web bridge from §4. Either way §4's re-tiering
  is required; this only decides whether an extra optimization is available.
- **(b)** Are `docex check` runs serialized today? This decides whether the
  latent DB-volume collision above is currently reachable, and confirms the
  subsumption is real rather than theoretical.
