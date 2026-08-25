# Mod 153 — Re-tier the `test` web network (F7 §4)

**Advance 009 — Test Overhaul, Wave 3, Mod 8.** Design intent:
[`pre_plan.md` SC2 § Slots as parallel-dev groundwork](../../advances/009_test_overhaul/pre_plan.md#slots-as-parallel-dev-groundwork)
and [`advance_plan.md` Wave 3, Mod 8](../../advances/009_test_overhaul/advance_plan.md).

## Purpose

Today the `test` env attaches its web-facing core services to the shared,
**external, project-tier** `${project}-test-web` network — the projinfra traefik
network, owned by `projinfra up development` and declared `external: true` in the
env compose so `docker compose up` for `test` **fails unless projinfra is
already up** (verified empirically: compose errors *"network … declared as
external, but could not be found"*). That external network is `test`'s **last
projinfra dependency**.

This mod finishes what **Mod 054** started (which stopped emitting traefik
routing labels for `test`, because `test` is never TLS'd or browsed). For the
`test` env specifically the web network becomes:

1. **env-tier, not projinfra** — a plain bridge the env compose stack creates and
   destroys, so `docex test` no longer needs projinfra up.
2. **per-slot** — it carries the `_s{k}`/`-s{k}` slot segment like every other
   env-tier resource, so N slots don't collide. This closes the one physical
   name Mod 152 deliberately left unslotted (the `web` network was its named
   seam), fully subsuming the latent `check --project-name` collision.
3. **a non-external bridge** — no `external: true`; docker creates it.

**Scope is the `test` env only.** `dev`/`stage`/`prod` keep their current
external, projinfra-owned web network — `dev` is publicly routed and TLS'd and
must not be re-tiered.

## Why this is safe / reachability is preserved

`api.web` joins `networks: [web, internal]`; the per-codebase **exec** container
(which runs `migrate.sh` / `test_*.sh`) joins non-web networks only (`internal`).
So the integration/flow test already reaches the web core service **over
`internal`**, and the web network is not even on the test's reach path today —
its only role in `test` is that `web` appears in the service's `networks:` list,
which the emitter maps to the external projinfra network. Re-tiering it to a
stack-local bridge leaves the service on both `web` and `internal` exactly as
before; reachability is unchanged and now needs no projinfra.

## The change (exactly where and how)

### 1. Env-tier emitter — `emit/compose.py::_network_section`

The single branch point is the env. Today the loop special-cases `web`
unconditionally to the external projinfra reference; non-web networks get the
(now slotted, Mod 152) bridge name. The change makes the `web` special-case
**conditional on `env != "test"`**:

- `dev`/`stage`/`prod`: `web` → `{"name": "${project}-${env}-web", "external": True}` — **unchanged**.
- `test`: `web` falls through to the same bridge branch as the non-web networks →
  `{"name": "${project}-test${slot_seg}-web"}` — non-external, slot-segmented.
- non-web networks, all envs: unchanged.

Slot naming is symmetric with the non-web branch: `${project}-test-web` at slot 1
(no segment), `${project}-test-s{k}-web` at slot k>1. No new field, no other
env's output touched.

`_traefik_labels` needs **no change** — it is never called for `test` (Mod 054
already gates web routing on `env != "test"`), so `test`'s web services carry no
router/tls/certresolver labels and keep only the `docex.project` label.

### 2. Project-tier emitter — `emit/compose.py::emit_project_compose`

The projinfra compose declares four `-web` networks and the `<project>-traefik`
service joining all four. Since `test`'s web network is no longer projinfra:

- **Drop `${project}-test-web`** from the top-level `networks:` block (keep
  `dev`/`stage`/`prod`-web + `docex-ingress`).
- **Drop `${project}-test-web`** from the traefik service's `networks:` list
  (traefik joins three `-web` nets + `docex-ingress`). Traefik never registered
  routers for `test` anyway (no labels), so it loses nothing.

This is the one place the change touches the **shared projinfra network model**,
but only by removing `test` from it — `dev`/`stage`/`prod` projinfra web
networks are untouched. Flagged as a design question below.

### How web core services attach

Unchanged. A `test` web service's `networks:` list still contains `web`, which
now resolves (via `_network_section`) to the stack-local `${project}-test-web`
bridge instead of the external projinfra network. Docker embedded DNS on that
bridge resolves the service's container name (`${global_name}`) exactly as
before.

## How `dev`/`stage`/`prod` stay byte-identical

`_network_section`'s `web` branch is gated `env != "test"`, so for the other
three envs it emits the identical external reference it does today; the non-web
branch is unchanged for all envs. Confirmed by the **Mod 152 golden gate**
(`tests/unit/test_slot_golden.py`), which recompiles `test_projects/fixed` and
byte-compares the whole `infra/output/` tree. After this mod:

- `infra/output/{dev,stage,prod}/docker-compose.yml` — **byte-identical**.
- `infra/output/test/docker-compose.yml` — **changes** (web network:
  `external: true` reference → non-external bridge). Golden regenerated
  deliberately.
- `infra/output/project/{development,production}/docker-compose.yml` — **change**
  (test-web dropped from networks + traefik membership). Golden regenerated
  deliberately. `test_project_tier_compose_identical_on_both_sides_for_fixed`
  still holds (both sides drop it symmetrically).

The regenerated golden diff is thus *only* the test-web re-tier and the projinfra
test-web removal — nothing else.

## Verification gate (single slot must still work end-to-end)

Proven via docex's **real-docker integration tier** (`tests/integration/`,
`-m integration`), which is the doctrine-correct vehicle:

- `test_test_real.py::test_docex_test_passes_and_tears_down` already brings up a
  **single** `test` stack (`compose up --build -d`), runs migrate + both shim
  tiers in the exec container, asserts green, and asserts clean teardown. After
  re-tiering it must still pass — and now passes **without any projinfra**
  (the stack creates its own web bridge). That alone proves the single slot works.
- **Strengthen the gate to match the advance-plan wording** ("a flow test
  reaching the live `-web` core-service container over HTTP"): while the stack is
  up, add an assertion that the `api-web` container is reachable **over the
  re-tiered `${project}-test-web` bridge** on HTTP — e.g. a one-off
  `docker run --network sample-test-web … wget -qO- http://sample-test-api-web:8080/health`
  expecting `{"version": "0.1.0"}` (the fixture app serves `GET /health` on
  8080). This proves the per-slot bridge carries real HTTP traffic to the web
  core service, not merely that `compose up` did not error.

Manual testing is **waived** (advance close-out step 13 exercises `--slots 2`
live once Mod 154 lands the CLI); the single-slot gate is proven by the tier
above.

## Tests to update (unit)

The re-tier flips assertions that hard-code `test`'s web network as
external/projinfra. Known set (implementation will run the full suite and fix any
others):

- `tests/unit/test_compile.py::test_project_tier_compose_declares_four_web_networks`
  → three `-web` networks; assert `${project}-test-web` **absent**. Rename.
- `tests/unit/test_compile.py::test_project_tier_compose_declares_traefik_service`
  → `expected_networks` drops `${project}-test-web` (three `-web` + docex-ingress).
- `tests/unit/test_compile.py::test_env_compose_web_network_references_project_tier_external`
  → split: `dev`/`stage`/`prod` external; `test` non-external bridge
  `{"name": "sample-test-web"}`.
- `tests/unit/test_compose_emitter.py::test_web_network_is_project_env_external_and_others_are_project_scoped`
  → same split (test → non-external bridge).
- `tests/unit/test_slot_primitive.py::test_slot2_emitted_compose_isolates_names`
  → **flip the Mod 153 seam**: at test slot 2 the web network is now slotted +
  non-external → assert `docex-smoke-fixed-test-s2-web` **present** and the
  unslotted `docex-smoke-fixed-test-web` **absent** (currently asserts the
  reverse, labeled "Mod 153 seam").

Golden regeneration: recompile `test_projects/fixed` and commit the changed
`infra/output/test/docker-compose.yml` + `infra/output/project/{development,
production}/docker-compose.yml`; verify dev/stage/prod env compose are unchanged
in the diff.

## Contracts

**None.** No surface changes; network tiering does not alter any core service's
contract.

## Doctrine-text amendments (land in this mod; described here for sign-off)

These are the upstream doctrine **spec** (not docex's own core planning docs).
Radius — all scoped to `test`:

- **`doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md`** — the
  "Test-env web network" row, the "traefik joins **all four** `-web` networks"
  line, and the projinfra compose snippet (drop `${project}-test-web`). State
  that `test`'s web network is now **env-tier, per-slot, non-external** and is no
  longer projinfra.
- **`doctrine/infrastructure/specifics/projinfra/projinfra.md`** — § *Why all
  four `-web` networks live on every side* (title + body: four → three, `test`
  excluded), the per-env `-web` list (line ~30), and the "What gets created"
  table row (line ~55).
- **`doctrine/infrastructure/specifics/networks.md`** — the tier table row ("The
  four per-project `-web` networks" → three; note `test`'s web is env-tier
  per-slot) and a short note that `test`'s web network is the one env-tier,
  non-external, per-slot web bridge (finishing Mod 054).
- **`doctrine/infrastructure/infrastructure.md`** — where it lists `test`'s infra
  dependencies / projinfra, note that re-tiering removes `test`'s **last
  projinfra dependency** (so `docex test` runs without projinfra up). Exact
  landing spot to be confirmed during implementation; flagged as uncertain
  in-scope-ness below.

docex's **own** core planning docs (`plans/core/compiler.md` Mod-152 seam note at
line ~481, `masterplan.md` network description) are updated by me in the mod's
documentation step (step 8), not in `implementation.md`.

## Boundaries respected (not built — Mod 154)

- No `--slots N` CLI flag, no N-slot orchestration loop, no shard injection
  (`DOCEX_TEST_SLOT`/`_SLOTS`), no fleet reaper. This mod only makes the `test`
  web network *per-slot-capable* and proves a **single** slot works.
- `exec_service_key` / `_migration_task_family` are **not** made slot-aware — the
  web re-tier does not require it (the exec/migration path is unchanged; only the
  web-network emission changes). Left as Mod 154's inherited seam.

## Design questions

1. **Projinfra-model change (scoped to `test`).** Removing `${project}-test-web`
   from `emit_project_compose` (the projinfra tier) is the one place this touches
   the shared projinfra network model, though only by removing `test` from it —
   `dev`/`stage`/`prod` are untouched. This is squarely F7 §4, but it does change
   `fixed_reverse_proxy.md` / `projinfra.md` from "all four `-web` networks" to
   "three". **Confirm this is in-scope for the mod cycle** and not something you
   want escalated as a projinfra-model amendment in its own right.
2. **Gate strengthening.** I propose adding the explicit HTTP-over-`-web`-bridge
   reachability assertion to the integration tier (beyond the existing
   stack-up/green/teardown check), to literally match the advance plan's "reaches
   the live `-web` container over HTTP" wording. Confirm you want that added
   rather than relying on the existing `run_test` green as sufficient proof.
3. **`infrastructure.md` landing spot.** I want to add a "`test` has no projinfra
   dependency" note, but the cleanest home for it in `infrastructure.md` is
   uncertain (it may fit better wholly inside the projinfra specifics). Flagging
   in case you'd rather keep `infrastructure.md` untouched and land the note only
   in the projinfra/networks specifics.
