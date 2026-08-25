# Mod 152 — The env-agnostic slot primitive in the compiler

**Advance 009 (Test Overhaul), Wave 3, Mod 7. Realizes SC2 (the slot axis) at
the compiler level.** Scope: compiler + doctrine only. No CLI flag, no
orchestration loop, no web-network re-tiering, no shard injection — those are
Mods 153/154.

Design rationale for the slot axis lives in
[`../../advances/009_test_overhaul/pre_plan.md` § SC2](../../advances/009_test_overhaul/pre_plan.md)
and the advance plan's Wave 3 / Goal 4. This overview does not restate it; it
turns SC2 into a concrete compiler change and drafts the doctrine amendments.

## Goal

A **fixed env may be instantiated into multiple isolated slots on one host.**
Build the compiler/naming/output-layout primitive **env-agnostic**
(`compile(env, slot=k)`), with the k-th slot scoping *every physical resource
name* by a slot segment so N stacks of one env coexist on one machine with no
name collision. Default slot 1 emits **no** suffix, so all existing compiled
output is **byte-identical to today**.

The slot is not exposed on the CLI this mod; it is invoked programmatically
(by the test suite here, by Mod 154's orchestration later) as
`compile_env(..., slot=k)`.

## The hard verification gate (proven first)

`compile(env)` / `compile(env, slot=1)` produces output **byte-identical to
today**. This is asserted before any slot>1 behavior is trusted:

- A new suite test compiles `test_projects/{fixed,elastic}` at slot 1 into a
  temp dir and **byte-compares** every file against the committed golden
  `infra/output/` tree (bytes, not parsed YAML — the mod-100 precedent).
- Close-out cross-check: recompile each test project in place and confirm
  `git -C test_projects/<f> diff --exit-code infra/output` is clean.

Because the default path (`docex compile`, i.e. `run_compile`) only ever calls
slot 1, and slot 1 inserts no segment, byte-identity is structural, not
coincidental.

## The slot-segment naming scheme

The compiler joins physical-name parts with `_` internally, then a naming
policy translates them (`transfer_tables.md § Naming Policies`). The slot
segment is inserted **between the env segment and the rest**, per pre_plan's
`{project}_{env}_{k}_{codebase}_{service}`:

| Kind | Slot 1 (today, unchanged) | Slot k>1 |
| --- | --- | --- |
| core service | `{project}_{env}_{codebase}_{service}` | `{project}_{env}_s{k}_{codebase}_{service}` |
| backing service | `{project}_{env}_{name}` | `{project}_{env}_s{k}_{name}` |
| codebase-keyed | `{project}_{env}_{codebase}` | `{project}_{env}_s{k}_{codebase}` |
| network (non-web) | `{project}_{env}_{short}` | `{project}_{env}_s{k}_{short}` |

**Proposed segment token: `s{k}` (e.g. `s2`).** Worked example — the fixed test
project's slot-2 stack:

- container / compose key: `docex-smoke-fixed-test-s2-api-web`
- otelcol sidecar: `docex-smoke-fixed-test-s2-api-web-otelcol`
- exec: `docex-smoke-fixed-test-s2-api-exec`
- internal network: `docex-smoke-fixed-test-s2-internal`
- postgres volume: `docex-smoke-fixed-test-s2-appdb_data`

> **Design question 1 (needs sign-off).** pre_plan wrote the segment as a bare
> `{k}` (→ `docex-smoke-fixed-test-2-api-web`). I recommend `s{k}` instead: it
> reads unambiguously, disambiguates the slot segment from the replica index
> suffix (`-{i}`, e.g. `…-api-web-1`) that sits at the *other* end of the same
> name, and stays grep-friendly (`grep -- -s2-`). Cost is 1 extra char. Fixed
> uses only the roomy hyphen/underscore policies (63/255), so the tight elastic
> `alb`(32)/`iam`(64) ceilings do not bite here. If you prefer literal pre_plan
> fidelity, say so and I will use bare `{k}`.

### Why this covers EVERY physical name — including explicit `name:` / `container_name:`

This is the mechanism that closes the latent `check --project-name` collision
(pre_plan SC2): Compose's `--project-name` only re-prefixes *auto-named*
resources and never touches explicit `container_name:` / top-level
`name:` fields, so two `--project-name`-differentiated stacks still collide on
those. The slot segment sits **inside the emitted identity itself**, so it
namespaces all of them:

- **`container_name:`** (fixed) is `ctx["global_service_name"]` via
  `_apply_fixed_invariants` — slotted at the source.
- **compose service keys** are `svc.global_name` — slotted.
- **`identifier`** (elastic) is `ctx["global_service_name"]` — slotted (env-
  agnostic falls out for free; see below).
- **sidecars / replicas / exec** derive from `global_name` /
  `codebase_global_name` — slotted transitively.
- **volume `name:`** — postgres/clickhouse declare `${global_service_name}_data`,
  so the named-volume top-level block (`_named_volumes`) is slotted transitively.
  This is precisely the DB-volume the collision bug shared.
- **magic-ref resolution** — `provides.host.fixed = ${global_service_name}`
  resolves `DATABASE_HOST` etc. to the *slot's own* container, so a slot is
  internally self-consistent with no extra work.

The only physical name not derived from `global_name` is the network, named in
`emit/compose.py::_network_section` from `project_dns_label`+env+short — handled
by threading the slot onto `CompiledEnv` (below).

## Implementation shape (compiler)

1. **`_global_service_name(project, env, name, policy, *, service=None, slot=1)`**
   — build the raw underscore-joined form with an inserted `s{k}` segment after
   `env` **iff `slot != 1`**. This is the single site the segment is added.
2. **`codebase_global_name(..., slot=1)`** — thread through (public helper; its
   two out-of-compiler re-derivers, `orchestrate/_common.py::exec_service_key`
   and `orchestrate/migrate.py::_migration_task_family`, keep `slot=1` — they
   are never called in a slot context this mod, and their default preserves
   byte-identity).
3. **`compile_env(doc, tables, *, env, project_name, project_version, slot=1,
   notes_seen=None)`** — accept `slot`, thread it into both
   `_global_service_name` call sites (the `ctx` gname and the
   `codebase_global_name`), and store it on the returned `CompiledEnv`.
4. **`CompiledEnv.slot: int = 1`** — new field so the emitter can slot networks.
5. **`emit/compose.py::_network_section`** — insert the `s{k}` segment in the
   **non-web** branch only (`{project_dns_label}-{env}-s{k}-{short}`); the
   `web` branch is untouched (**Mod 153 boundary** — slots share the `-web`
   external network this mod; full per-slot network isolation lands there). For
   the `test` env there are no traefik routing labels anyway (mod 054), so the
   shared `-web` net is inert for the first slot user.
6. **Output emission for slot k.** Refactor `run_compile`'s per-env emit body
   into a reusable helper and add a focused entry point
   `compile_slot(ctx, env, slot)` that compiles one env at a slot and emits to
   the slot's output dir. `run_compile` is **unchanged in behavior** — it
   compiles all four envs at slot 1 to `infra/output/<env>/`.

No change to `validate.py`: rule 5 (uniqueness) runs on the authored doc
*before* the env/slot loop and is slot-independent (within one slot every name
carries the same segment, so relative comparisons are unchanged). No change to
the elastic HCL emitter is required for correctness — `identifier` and tags read
`ctx["global_service_name"]`, already slotted; the primitive is env- and
foundation-agnostic at the naming layer, exercised only for fixed `test` later.

## Output-dir layout for slot k>1

Requirement: slot-1 output stays **exactly** at `infra/output/<env>/`.

> **Design question 2 (needs sign-off).** Two coherent homes for slot-k (k>1)
> compiled output:
>
> - **Option A — `infra/output/<env>/slots/<k>/`.** Matches pre_plan's shorthand
>   (`infra/output/{env}/…`) and preserves the literal "compile writes nothing
>   outside `infra/output/`" invariant. **Cost:** slot dirs would dirty the
>   git-tracked `infra/output/` tree, so every project (and both golden test
>   projects) needs a new `infra/output/**/slots/` gitignore entry — and
>   `docex_install.sh` explicitly does **not** manage gitignores (inception
>   does), so rollout is manual.
>
> - **Option B — `.docex/slots/<env>/<k>/` (RECOMMENDED).** Aligns with SC3-D4's
>   established principle: ephemeral, machine-local state lives under the
>   already-gitignored `.docex/` (beside `runs/` and `checks/`). Slot-k output
>   *is* ephemeral test scaffolding, regenerated per run. Advantages: (a) **no
>   new gitignore** anywhere — `.docex/` is already ignored in both test
>   projects; (b) `infra/output/` stays pristine and slot-1-only, so `git diff
>   infra/output` is trivially clean after *any* compile, strengthening the
>   byte-identical guarantee; (c) compose still resolves `./core/<cb>/…` build
>   contexts correctly because docex passes `--project-directory <root>`
>   explicitly (masterplan DooD point 2), so the compose file's location is
>   irrelevant to path resolution.
>
> I recommend **Option B**. It requires amending compiler.md's "compile writes
> nothing outside `infra/output/`" line to note that the *slot-k programmatic
> path* writes ephemeral output under `.docex/slots/` (the CLI `docex compile`
> = slot 1 remains true to the invariant). pre_plan's `infra/output/{env}/…`
> was shorthand and predates the gitignore consideration.

## Non-slotted by deliberate decision

- **Image tag.** `_image_ref` yields the codebase/version-addressed local tag
  `{project}/{codebase}:{version}` — **not** slotted. Slots of one env run the
  *same* built artifact under test; sharing the tag is correct and avoids
  redundant rebuilds. The concurrency seam (two slots building the same tag at
  once) belongs to Mod 154's orchestration loop, not the compiler.
  > **Design question 3 (confirm).** Agreed that the image tag stays
  > slot-independent?
- **The `-web` external network** — Mod 153 (noted above).

## Seams left for Mod 154

**SC4 partial closure.** The `check --project-name` DB-volume collision is
*begun* here: the slot segment namespacing all physical names is the mechanism.
Full closure lands when `check` adopts a slot in Mod 154. This mod delivers the
namespacing primitive; nothing in `check` consumes a slot yet.

**Two out-of-compiler re-derivers must become slot-aware in Mod 154.**
`orchestrate/_common.py::exec_service_key` (the `-exec` compose key) and
`orchestrate/migrate.py::_migration_task_family` (the `-migrate` task family)
reconstruct `codebase_global_name` outside the compiler and must match it
byte-for-byte. This mod keeps both at `slot=1` (correct — they are never called
in a slot context here, and the default preserves byte-identity). But when Mod
154 brings a slot-k stack up and runs migrations against it, **both must thread
the same `s{k}` segment** or the exec key / migrate family will not match the
slotted `codebase_global_name` the compiler emitted for that slot. This is the
same class of forward-seam Mod 148 recorded; noted here and in `compiler.md` so
Mod 154's corporal inherits it.

## Doctrine amendments (verbatim drafts — for sign-off)

SC2 is a load-bearing doctrine amendment (the four-env symmetry). Each frames
the slot as the **general primitive** with parallel-dev named as the future
user, and carries SC2's two explicit **non-goals now**: (a) do not generalize
the slot *lifecycle* model, and (b) ingress multiplicity is untouched.

### A. `infrastructure.md` § Environments — add after the "as similar as possible" paragraph

> **The slot axis.** Environments are singletons by default, but a **fixed env
> may be instantiated into multiple isolated *slots* on one machine.** A slot is
> not a new environment: the env *string* stays singular (`test`), and each
> slot's stack differs only by a slot *segment* woven into every physical
> resource name — `{project}_{env}_s{k}_{codebase}_{service}` (e.g. `s2` for
> slot 2), analogous to a replica but at the environment level. Slot 1 is the default and adds no
> segment, so a single-slot project is byte-identical to a slotless one. The
> slot is a **general primitive**: its first and, for now, only user is `test`,
> which shards its slow integration tier across N isolated stacks on one host;
> its intended next user is **parallel development** — two agents working
> different modifications on one machine (see § Deferred). Two boundaries hold
> the primitive cheap: a slot shares its env's configurable values (config and
> secrets are looked up per env, not per slot — see
> [`configurable.md`](./configurable.md)), and the slot lifecycle and ingress
> models are *not* generalized here (§ Deferred).

### B. `infrastructure.md` § Deferred — add a new item

*Deferred-staleness check (done): the live § Deferred lists exactly multi-machine
fixed / automated CI-CD / fundamental stage-tests / defense-in-depth / GPU. **No**
existing item defers a parallel-test-env or heavier-test-topology capability, so
there is nothing the slot axis makes stale to remove — adding item 6 (parallel
development) is the whole amendment.*

> 6. **Parallel development on the slot axis.** The slot axis (§ Environments)
>    is the runtime-name isolation needed for two agents to work different
>    modifications on one machine, and it is delivered now for `test`-sharding.
>    Full parallel development additionally needs code isolation (git worktrees)
>    and, for *browsable* dev stacks, ingress multiplicity (per-slot routing /
>    DNS / cert) — the latter genuinely hard because `dev`, unlike `test`, is
>    publicly routed and TLS'd. Two properties are **explicitly not generalized
>    with the slot primitive**: the slot *lifecycle* (test slots are fungible
>    and reaped when idle; a dev slot is owned by a branch and must survive when
>    idle — antithetical policy on the same name/lock primitive), and ingress
>    multiplicity (untouched here). Headless parallel dev (code + tests, no
>    browsing) nearly falls out of the slot axis directly; browsable parallel
>    dev needs the ingress work.

### C. `lexicon.md` — amend the `Environment` row

> | Environment | "env" | A copy of all environment-tier infrastructure that serves a distinct purpose: `dev`, `test`, `stage`, and `prod`. The env is a singleton by default; a **fixed** env may be instantiated into multiple isolated **slots** on one machine, which share the env's identity and configurable values and differ only by a slot number woven into every physical resource name. See [infrastructure.md § Environments](./infrastructure/infrastructure.md#environments). |

*(New adjacent row, same table:)*

> | Slot | | One isolated instance of a **fixed** environment's stack on a single host. The k-th slot scopes every physical resource name with a slot segment (`{project}_{env}_s{k}_…`, e.g. `s2` for slot 2); slot 1 is the default and adds no segment. Slots let N stacks of one env coexist without name collision. The env string stays singular — a slot is not a new environment. |

### D. `configurable.md` § Environment and Foundation — add a note after the circumstances table

> **Slots share an env's configurable values.** A [slot](./infrastructure.md#environments)
> is an isolated stack of a fixed env, not a new environment, so all three
> configurable-value sources are looked up **per env, not per slot**: every slot
> of `test` reads the same `infra/config/test.env`, `infra/secrets/test.env`,
> and `infra/tte/test.env`. The slot number scopes physical resource names only;
> it never fans out the configurable-value namespace.

### E. `shape.md` § Shape and Environment — add after the replica table

> **The slot dimension.** The shape of a **fixed** env may be instantiated as
> multiple isolated **slots** on one host — N copies of the env's stack whose
> physical resource names each carry a slot segment
> (`{project}_{env}_s{k}_…`, e.g. `s2` for slot 2), so they coexist without
> collision. A slot is
> orthogonal to the replica dimension above: replicas multiply a core service's
> containers *within* one stack (`prod` only); a slot multiplies the *whole*
> stack. Slot 1 is the default and adds no segment, so a single-slot env is
> byte-identical to a slotless one. Only fixed envs take slots (`dev`/`test` are
> always fixed); the env string stays singular. See
> [infrastructure.md § Environments](./infrastructure.md#environments).

> **Design question 4 (needs sign-off).** These are the four-env-symmetry
> amendments the task named as requiring your explicit sign-off. The wording
> above is drafted for ratification; the cross-file consistency + link integrity
> pass is the advance's close-out `cohere` step (advance plan step 11), not this
> mod.

## Docex core-planning-doc impact (for the project map)

`plans/core/compiler.md` is touched at documentation time (mod step 8): the
naming-flow section gains the slot segment, the "Output layout" section gains
the slot-k dir, and the "compile writes nothing outside `infra/output/`" line is
amended per Option B. No masterplan change; the command surface is unchanged
(no new CLI verb).

## Test plan (proving the gate + slot>1)

1. **Byte-identical gate** (proven first) — golden byte-compare of both test
   projects at slot 1, as above.
2. **Slot>1 name interpolation** — compile the fixed test project at slot 2 to a
   temp/`.docex` dir; assert the `s2` segment appears in container names, the
   compose service keys, the sidecar/exec/replica names, the non-web network
   name, and the postgres volume name; assert the `-web` external network is
   **not** slotted (the Mod 153 seam); assert `DATABASE_HOST`-style magic refs
   resolve to the slot-2 host.
3. **Slot-1 vs slotless equivalence** — assert `compile_env(..., slot=1)`
   produces a `CompiledEnv` whose names are identical to the no-slot call.
4. **Determinism** — two slot-2 compiles produce byte-identical output.

Manual testing is **waived** (advance close-out step 13 exercises `--slots 2`
live once Mod 154 lands the CLI).
