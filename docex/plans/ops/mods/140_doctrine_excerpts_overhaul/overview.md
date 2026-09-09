# Mod 140 — `doctrine_excerpts` overhaul + citation bounding + standing consumer

## Goal

`docex why <resource>` serves prose from `docex/doctrine_excerpts/` (18 `.md`
entries + `index.yml`, read by `why/catalog.py`). It is the **one aligned `docex`
artifact with no automated consumer**, so it drifts silently; mod 134's audit
found 15 of 18 entries carry defects and three actively misinstruct. This mod:

1. **Audits every entry against its current rule of record and rewrites to match**
   (prose only — `docex why` behavior does not change).
2. **Reconciles `index.yml` keys** with `shape.md`'s `[resource]` notation
   (rename two, retire one, add new ones).
3. **Bounds every `Doctrine reference:` footer** so `linkcheck.py`'s citation arm
   can verify the heading (Part 2 of `unbounded_citation_enumeration.md`, half 2
   only — the *conversion*, not the enumerate-in-linkcheck half).
4. **Adds the artifact's first automated consumer** — a unit test asserting every
   `index.yml` key resolves to a `shape.md` resource — so it stops drifting silently.

Doctrine is **not** edited. Every rewrite aligns the excerpt *to* current doctrine.

## Audit results — entry by entry

Verdict legend: **INVERTED** = asserts the opposite of the current rule (often
with rationale built on the inversion); **STALE** = superseded / incomplete but not
opposite; **CURRENT** = content correct today, touched only for citation bounding.

| Entry | Verdict | Defect and correction |
| --- | --- | --- |
| `aws_account` | **INVERTED** | Asserts "one project per AWS account; multi-tenant out of scope" — the exact opposite of doctrine, where **multiple projects share one account and one master VPC** (`shape.md` `aws_account` row + Concrete Example). The whole "isolation is deliberate" paragraph rests on the inversion. Rewrite to multi-project-per-account with the shared master network. |
| `dns` | **INVERTED / STALE** | Uses the removed `domain:` field and a subdomain table mapping `prod → www.<domain>` with no project segment, and claims "apex/bare-project never served". Doctrine (`cicl.md § Domain` / § Bare Subdomains): `<env>.<project_name>.<apex_domain>`; **bare project routes to prod's bare env**; bare env → `domain_default_service`. Full rewrite. |
| `registrar` | **INVERTED / STALE** | Same removed `www.<domain>` scheme as `dns`, no project segment. Rewrite subdomain references to the `apex_domain` scheme. |
| `secrets` | **STALE (misinstructs)** | Describes `example.env` "auto-emitted by `docex compile`; committed" and "the compiler … emits `example.env`" — **mod 092 deleted that emit**. Rewrite to `docex secrets scaffold` → `<env>.env`, keys sourced from the `infra.yml` `secrets:` block + doctrine-mandated keys (`configurable.md § Secrets`). Also currently has **no `Doctrine reference:` footer** — add a bounded one. |
| `vpc` | **RETIRE** | Actively misinstructs — "one VPC per project", "one NAT Gateway per AZ" — the opposite of the shared master VPC + centralized single NAT (`shape.md § Elastic-Foundation`). No `[vpc]` resource exists. Delete `vpc.md` and its key; content is covered by the new `master_network` entry. |
| `cert_manager` | **STALE (inverted specifics)** | Fixed side correct. Elastic side wrong: "one wildcard cert covers every env's ALB listener" — doctrine is **two certs** (per-env stage/prod), **DNS-01**, and it omits the `ec2_traefik` cert path entirely (`shape.md` `cert_manager` row; `cicl.md § Elastic TLS`). Rewrite elastic side. |
| `reverse_proxy` | **STALE (inverted specifics)** | Fixed side correct. Elastic side wrong: "one ALB per environment" — doctrine is **one ALB per project** serving both stage+prod via host-based rules, and the proxy may instead be **`ec2_traefik`** (`shape.md` `reverse_proxy` row + Concrete Example; `cicl.md § Reverse Proxy`). Rewrite elastic side. |
| `environment_config` | STALE | `docex up` → **`docex envinfra up`**; elastic output described as ALB-only (note the `ec2_traefik` alternative). |
| `network` | STALE | Elastic realization says "project VPC" → it is a **security group within the master VPC** (`shape.md` `network` row). Update the `why network_web` / `why network_internal` cross-refs to the renamed keys. |
| `network_internal` | STALE (minor) | SG line says "project VPC" → master VPC (its own egress line already says master VPC). **Rename file → `internal_network.md`.** |
| `network_web` | STALE (minor) | Fixed correct; elastic ALB-only (note `ec2_traefik`). **Rename file → `web_network.md`**; fix cross-refs. |
| `backing_service` | STALE (minor) | Largely current; confirm the "no `resources:` block in v1" claim against `cicl.md`; bound citation. |
| `build_image` | CURRENT | Bound citation only. |
| `codebase` | CURRENT | Bound citations only. |
| `container_registry` | CURRENT | Current (mod 133); citation already bounded. |
| `core_service` | CURRENT | Bound citations only. |
| `host_machine` | CURRENT | Fixed topology correct; bound citation. |
| `service_discovery` | CURRENT | Current (mod 134); citations already bounded. |

**INVERTED (asserting the opposite of the rule):** `aws_account`, `vpc` (retired),
and the subdomain mapping in `dns` / `registrar`. `cert_manager` and
`reverse_proxy` carry **inverted elastic specifics** ("one wildcard cert, every
env" / "one ALB per environment") inside otherwise-stale entries. `secrets`
describes a **removed** mechanism (`example.env`) as active — a misinstruct.
Everything else is merely stale or current.

## `index.yml` key plan

- Rename `network_web` → **`web_network`**, `network_internal` → **`internal_network`**
  (file renames too). `docex why web_network` exits 1 today.
- **Retire `vpc`** (delete key + `vpc.md`).
- Add **`master_network`**, **`web_demux`** (required — they are where a preinfra
  question lands).
- Add **`observability_backend`**, **`telemetry_sidecar`**, **`nat_gateway`** —
  *pending design-question 1 below*.
- Keep `codebase` and `secrets` as **documented exceptions** (see below).

### Final key set (if new entries approved)

`aws_account, backing_service, build_image, cert_manager, codebase,
container_registry, core_service, dns, environment_config, host_machine,
master_network, nat_gateway, network, internal_network, web_network,
observability_backend, registrar, reverse_proxy, secrets, service_discovery,
telemetry_sidecar, web_demux` — 22 keys (18 − `vpc` + 5 new).

## Part 2 — citation bounding

Every `Doctrine reference:` footer gets the `§` heading **inside the same
inline-code span as the path**, e.g.
`` `infrastructure/cicl.md § Domain` `` rather than `` `infrastructure/cicl.md` § Domain``.
Done inline as each entry is rewritten. Verified **by measurement**: `linkcheck.py`
run before/after; repo-wide `unbounded` count must **drop by ~15** and `exact`
rise by the same. Baseline measured this session: **25 unbounded / 250 exact**
(the brief cited 24; I report the measured number). The enumerate-in-linkcheck
half of that brief is **not** implemented here — booked.

## Part 3 — the standing consumer

`docex/tests/unit/test_doctrine_excerpts_index.py` (pure unit test, no docker/AWS):

1. Load `index.yml` keys and `doctrine/infrastructure/shape.md`.
2. For each key, assert it appears in `shape.md` as `[<key>]` **or** as a table-row
   name (`| <key> |`) **or** is in a small documented `EXCEPTIONS` set.
3. Assert every index *value* file exists on disk, and every `.md` in the dir
   (except `index.yml`) is referenced by exactly one key (no orphans — catches the
   `vpc.md` deletion staying consistent).

This is the check that would have caught the `network_web` / `vpc` mismatches: on a
bad key (`network_web`) step 2 fails.

**`EXCEPTIONS = {codebase, secrets}`**, documented in the test and in
`docex_process.md`:
- `codebase` — not a `shape.md` `[resource]` (the deployed nouns are
  `core_service` / `backing_service`); it is the fundamental unit-of-code concept
  mod 111 deliberately indexed, and `docex why codebase` is a legitimate lookup.
- `secrets` — a *source* of the `configurable_vars` resource, not itself a
  `[resource]`; retained as a useful `docex why secrets` target.

## Drift check (six artifacts)

- **Rule of record (doctrine):** not edited — excerpts align to it.
- **`doctrine_excerpts/*.md` + `index.yml`:** the mod's whole subject.
- **`docex_process.md § Additional Artifacts`:** update the booking references to
  past tense ("mod 140 landed the overhaul; 15/18 fixed, `vpc` retired, keys
  reconciled, directory converted to bounded citations"); mark the four
  still-open defects fixed; append no-entry verdicts for any resources
  deliberately left without an entry, and the `codebase`/`secrets` exception
  rationale. **Append/adjust only — do not rewrite its history.**
- **`src`/`tests`:** the new consumer test. `catalog.py` behavior unchanged —
  confirm `docex why web_network` now resolves and `docex why vpc` legitimately
  404s.

## Open design questions

1. **New-entry scope.** `observability_backend`, `telemetry_sidecar`, and
   `nat_gateway` are all genuine `shape.md` `[resource]` nouns with no entry. By
   the "what earns an entry" discipline they **earn entries**, and leaving them out
   is exactly the "silent no indistinguishable from oversight" that section warns
   against. **My recommendation: add all three** (they are short) alongside the
   required `master_network` + `web_demux`, so the directory is complete against
   shape's resource set and no future mod re-asks. The brief offered a deferral
   (add only `master_network` + `web_demux`, book the other three). **Confirm: add
   all five, or defer the three?**

2. **Other entryless resources the brief did not name.** `shape.md` also has
   `repo`, `configurable_vars`, and `ecs_cluster` as resources with no entry. My
   proposed disposition is to **record explicit no-entry verdicts** for them in
   `docex_process.md` (matching that section's rigor) rather than add entries:
   - `repo` — `cicl.md § Git Repo URL` states it serves "only a documentary role"
     and is unmanaged prerequisite infra; a restatement buys nothing.
   - `configurable_vars` — the *aggregate* of TTE + secrets + config; the `secrets`
     entry plus `docex secrets` / `docex config` tooling already serve it, and a
     third hand-maintained restatement is the anti-pattern the criterion names.
   - `ecs_cluster` — a narrow elastic project-tier artifact adequately covered by
     `reverse_proxy` / `environment_config`.
   **Confirm this disposition, or add any of them?**

Both questions gate only the *new-entry* count. The 17 rewrites, renames,
`vpc` retirement, citation bounding, and Part-3 test proceed regardless.
