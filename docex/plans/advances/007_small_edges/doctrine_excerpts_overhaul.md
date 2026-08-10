# `doctrine_excerpts/` needs an overhaul, not another sweep

## Summary

`docex why <resource>` serves prose out of `docex/doctrine_excerpts/` — eighteen markdown
entries plus an `index.yml` mapping resource names to them. It is the **sixth aligned
`docex` artifact and the only one with no automated consumer**, so nothing fails when it
goes false.

A full audit of all eighteen entries against current doctrine finds:

- **15 of 18 entries carry defects.** Three are substantially clean: `codebase.md`,
  `core_service.md`, and `container_registry.md`.
- **Three entries actively misinstruct** — they state the *inverse* of a doctrine rule,
  with rationale built on top of the inversion. `vpc.md`, `aws_account.md`, and
  `reverse_proxy.md`'s Elastic bullet.
- **`index.yml`'s mapping is a clean 18/18 bijection**, but its *coverage* is not: eight
  `shape.md` resources have no entry, and two keys are spelled opposite to `shape.md`, so
  `docex why web_network` — the only spelling a reader can have learned — exits 1.
- **15 of 16 defect sites predate advance 006**, and **14 trace to a single commit**:
  `307d47a` (2026-05-26), the directory's original authoring. The overhaul is warranted
  by original-authoring debt, **not** by regression.

This booking fixes nothing. Mod 134 fixed three naming tokens in passing (see
[Already fixed](#already-fixed-by-mod-134)); everything else below needs authorship.

Every figure here is measured. Two of the design-time figures did **not** survive
measurement and are corrected in place — see [Corrections](#corrections-to-the-figures-this-brief-was-scoped-with).

## The three that actively misinstruct

### `vpc.md` — a per-project VPC the doctrine replaced with a shared master network

Three inversions in a twelve-line file:

| `vpc.md` says | The doctrine says |
| --- | --- |
| `:3` "**Project-tier infrastructure**" | prerequisite — `shape.md:67` files `master_network` as `prerequisite` |
| `:3` "one VPC per project" | one VPC shared by all projects — `elastic_master_network.md:42`, "Single VPC per AWS account" |
| `:8` "one NAT Gateway per AZ" | one centralized gateway — `shape.md:68`, "Centralized NAT gateway shared by all projects" |

The NAT inversion is the expensive one: `ingress_and_egress.md:36` prices per-project NAT
at "about $400 / yr" and names it as the thing **explicitly rejected**. An operator
following `why vpc` provisions the rejected topology.

`vpc.md` is also **the only excerpt whose subject resource does not exist in `shape.md` at
all.** There is no `[vpc]`; the resource is `[master_network]`. This entry does not need
correcting so much as replacing: the overhaul should decide whether `vpc` survives as an
alias for `master_network` or is retired outright.

### `aws_account.md:3` — the exact inverse of the tenancy rule

> The doctrine assumes **one project per AWS account** — multi-tenant accounts are out of
> scope.

`shape.md:63`: *"Multiple projects may exist under one account."*

What makes this misinstruction rather than a typo is `:5`, which builds a full paragraph of
rationale on the inverted rule ("This isolation is deliberate… When two projects need to
share resources, they should do so via explicit cross-account roles"). A reader who
notices the tension has been given an argument for the wrong side of it.

### `reverse_proxy.md:7` — four errors in one bullet

The Elastic bullet reads: *"One ALB per environment in the env's public subnets, listening
on 443 with the project's ACM cert. Doctrine-provisioned (not declared in `infra.yml`) —
`docex compile` emits the ALB when any service declares `networks: [web, ...]`."*

| Clause | Reality |
| --- | --- |
| "One ALB per environment" | project-tier, **one per project** — `shape.md:74` and `elastic_alb.md`; `shape.md:166`'s worked output is "1 ALB `myproject-alb` … One ALB serves both stage and prod via host-based listener rules" |
| "in the env's public subnets" | the **master VPC's** public subnets — prerequisite and shared. There are no per-env subnets. |
| "Doctrine-provisioned (not declared in `infra.yml`)" | it **is** declared — `cicl.md:32`'s `reverse_proxy:` field. `alb` is merely the default; `ec2_traefik_eip` / `_pip` are the alternatives. |
| "`docex compile` emits the ALB when any service declares `networks: [web, ...]`" | unconditional project-tier projinfra — no service declaration gates it |

A fifth clause, "the project's ACM cert" (singular) against the doctrine's two SAN'd certs,
is **arguable** rather than wrong — read as "the project's ACM certificate material" it
passes. Named here so the overhaul decides rather than rediscovers; **not counted** among
the four.

One clause in the bullet is correct and should survive the rewrite: *"Doubles as a load
balancer for replicated core services in `prod`"* — `shape.md:74` says exactly that.

## `index.yml`: the mapping is clean, the coverage and the keys are not

Measured: 18 keys → 18 distinct, existing files. No duplicates, no orphans, no missing
targets. The defect is elsewhere.

### Eight `shape.md` resources have no entry at all

`web_demux`, `master_network`, `repo`, `observability_backend`, `configurable_vars`,
`telemetry_sidecar`, `nat_gateway`, `ecs_cluster`.

Derived by differencing `shape.md`'s 23 resource rows against `index.yml`'s 18 keys.
`master_network` and `web_demux` are the two an operator is most likely to reach for
first — they are the resources a *preinfra* question lands on.

### Two keys are spelled opposite to `shape.md`

`shape.md` writes `[web_network]` and `[internal_network]`. `index.yml:14-15` writes
`network_web` and `network_internal`. So:

```
$ docex why web_network
unknown resource: 'web_network'
Available resources:
  - aws_account
  …
```

— `why/catalog.py:66-71` prints the unknown-resource line, dumps all 18 keys, and exits 1.
A reader who took the term from `shape.md`, **the only place it is spelled**, is bounced.
`index.yml:1-4` states the very rule it breaks: keys should *"match the doctrine's
`[resource]` notation in shape.md where possible."*

The two entries' H1s are a third spelling again — `# network: web`, `# network: internal
(and other non-special names)` — matching neither the key nor `shape.md`.

Conversely, three keys name nothing in `shape.md`:

- `codebase` — **legitimate**; it is a `cicl.md` / `lexicon.md` concept, not a shape resource.
- `secrets` — `shape.md`'s resource is `configurable_vars`, and the excerpt correspondingly
  describes only one of the three configurable categories.
- `vpc` — no doctrinal referent at all (see above).

## The two patterns a vocabulary grep cannot find

This is the part worth teaching, and the reason the overhaul should not be scoped as
another grep-driven sweep.

### 1. An inverted claim propagated across three files

`vpc.md:3`, `network.md:8`, and `network_internal.md:6` all say **"project VPC"** where the
doctrine has a master VPC shared by all projects. A grep for the doctrine's own terms —
`master_vpc`, `master_network` — returns **nothing in this directory**, *precisely because
these files never use them.* The wrong phrase is a plausible construction that appears on
no term list, so no vocabulary sweep can be keyed on it.

The only mechanical tell is that `network_internal.md` **contradicts itself four lines
apart**: `:6` says "within the project VPC" and `:10` says "the master VPC's NAT gateway".
`aws_account.md:3` is the same inversion in the tenancy register, with no such tell at all.

**Implication for the overhaul's method:** an inversion is found by reading the entry
against its rule of record, one entry at a time. Nothing cheaper works.

### 2. Advance-005 rename residue that is structural, not lexical

State this precisely, because the loose version of it is wrong:

- **No stale nouns survive.** A grep for `process` / `processes` / `domain_default_process`
  over the directory returns **one** hit — `core_service.md:10`, "Core services execute as
  stateless **processes** (12-factor)" — which is a correct, unrelated use. Commit
  `b9b3cc3` did sweep the nouns.
- What survived is that the rename gave the compiled identity a **fourth segment**
  (`${project}-${env}-${codebase}-${service}`), and files still showed three.

That is *why* no vocabulary grep can see it: the offending token contains no renamed word.
Only comparison against compiled output reveals the missing segment — ground truth being
`test_projects/fixed/infra/output/dev/docker-compose.yml:141`,
`container_name: docex-smoke-fixed-dev-api-web`.

## `registrar.md:8`'s compound citation blocks mechanical bounding

Verbatim:

```
Doctrine reference: `infrastructure/shape.md` § Fixed-Foundation / Elastic-Foundation.
```

Two faults, and they compound:

1. **The `§` sits outside the closing backtick.** `linkcheck.py:124`'s `CITE_RE` requires
   path and `§` to fall inside one common inline-code span for the heading text to have a
   determinable end; `prose_citations` yields `head=None` otherwise. So this citation is
   **unbounded** — the heading runs into the sentence, and it is counted but never verified.
2. **It names two headings** (`### Fixed-Foundation`, `### Elastic-Foundation`) where no
   single heading of that name exists. Any bounder that resolves it as one unit yields a
   **false BAD CITATION**.

**It is the only unresolvable citation in the directory** — 16 of the 18 entries carry a
`Doctrine reference:` footer, and the other 15 all resolve — so splitting it into two
bounded citations is the *precondition* for mechanically bounding this directory at all.
Fold that split into the overhaul.

Two companions for the same sweep:

- `container_registry.md:10` is the only entry putting `§` **inside** the backticks — the
  bounded, checkable form all of them should use. Use it as the model.
- `secrets.md` has **no** `Doctrine reference:` footer at all. `vpc.md` has none either; it
  cites `shape.md` mid-prose at `:12` instead. Both should gain footers.

## `secrets.md` describes a model the doctrine explicitly repudiated

The severest non-inversion defect, and worth its own section.

The entry's tree lists `example.env  # auto-emitted by 'docex compile'; committed`, and
`:14` explains the workflow: the compiler emits `example.env`, *"the operator copies it to
`<env>.env` and fills in real values per environment."*

- **`example.env` appears nowhere in `doctrine/`** — zero grep hits. Mod 092 removed the
  emit.
- `config_and_secrets.md:70` names the repudiated shape in so many words: *"Rather than
  copy a manifest to `<env>.env` and fill it by hand"* — the real mechanism is
  `docex secrets scaffold <env>`.
- The store is now split **three** ways (`infra/secrets/`, `infra/config/`, `infra/tte/`).
  The excerpt shows one, so a reader learns that every per-deploy value is a secret —
  which is exactly the distinction `configurable.md` exists to draw, and the reason
  `POSTGRES_PASSWORD` is a minted TTE value rather than a secret.

An operator following `why secrets` waits for a file that will never appear, and the
natural conclusion is that `compile` failed.

This overlaps
[`doctrine_excerpts_stale_entries.md`](./doctrine_excerpts_stale_entries.md), which books
`secrets.md`, `dns.md`, `registrar.md`, and `environment_config.md` from mod 131's
completeness pass. **The overhaul subsumes that brief** — do not run both.

## A rendering defect in shipped output, not a prose nit

`dns.md:7-10` puts a bare `<domain>` inside a markdown table. `rich.markdown.Markdown`
(`why/catalog.py:80`) parses it as an HTML tag and **drops it**. Measured — this is what
`docex why dns` actually prints today:

```
 Env    Subdomain
 ────────────────
 dev    dev.
 test   test.
 stage  stage.
 prod   www.
```

The table has holes exactly where the operator needs a value. Frame the fix as a defect in
what `docex why` *prints*, not as a style question: the repair is to backtick the token
(or use `${apex_domain}`), and `dns.md`'s whole model needs rebuilding anyway.

**Corrected scope:** this defect exists at `dns.md:7-10` **only**. The other
angle-bracket sites — `cert_manager.md:6`, `registrar.md:5`, `secrets.md:19`, `vpc.md:9` —
already sit inside backticks and render correctly; rich escapes inline code. Verified by
rendering every entry.

## Why this is booked rather than folded into advance 006

**15 of 16 defect sites predate advance 006, and 14 trace to one commit.** Measured by
`git blame` on each site:

| Site | Commit | Date |
| --- | --- | --- |
| `vpc.md:3` (tier + cardinality) | `307d47a` | 2026-05-26 |
| `vpc.md:8` (NAT per AZ) | `307d47a` | 2026-05-26 |
| `aws_account.md:3` (+ `:5` rationale) | `307d47a` | 2026-05-26 |
| `reverse_proxy.md:7` (Elastic bullet) | `307d47a` | 2026-05-26 |
| `index.yml:14-15` (opposite keys) | `307d47a` | 2026-05-26 |
| `network.md:8` ("project VPC") | `307d47a` | 2026-05-26 |
| `network_internal.md:6` ("project VPC") | `307d47a` | 2026-05-26 |
| `secrets.md:14` (`example.env` model) | `307d47a` | 2026-05-26 |
| `dns.md:7-12` (pre-`apex_domain` scheme) | `307d47a` | 2026-05-26 |
| `backing_service.md:3` (engine authority) | `307d47a` | 2026-05-26 |
| `build_image.md:5` (image ref) | `307d47a` | 2026-05-26 |
| `cert_manager.md:6` (one cert) | `307d47a` | 2026-05-26 |
| `environment_config.md:6` (ALB/ECS tier) | `307d47a` | 2026-05-26 |
| `host_machine.md:5` (one host per env) | `307d47a` | 2026-05-26 |
| `registrar.md:8` (compound citation) | `60b97c8` | 2026-06-22 (a cohere pass) |
| `reverse_proxy.md:5` (`project_dns_label` leak) | `1763217` | 2026-08-10 (mod 131) |

Exactly one site is advance-006-attributable, and it is the least consequential: a
`project_dns_label` vocabulary leak whose **rendered value is correct**.

**The honest nuance: `git blame` flatters advance 006 badly here.** Mod 131 touched
`network_web.md:5` and `reverse_proxy.md:5` without fixing tokens that were already
present, so blame attributes 2026-05-26 content to 2026-08-10. `git blame HEAD -L5,5
network_web.md` returns `1763217` for a line whose underscored network name predates it by
two and a half months. Anyone re-deriving this table from blame alone will over-attribute
to advance 006; read the *content*, not the commit.

**And the countervailing fact, recorded rather than suppressed: advance 006 improved every
excerpt it touched.** Mods 130-133 rewrote `container_registry.md` to clean, added the
correct per-core-service health-probe paragraph to `core_service.md` (`:27-33`), fixed a
genuinely inverted host-wide-traefik claim across four files, and added `health.sh` to
`codebase.md`'s shim list.

`container_registry.md` is clean **because mod 133 rewrote it** (`8bef555`). That is the
argument for the overhaul in one line: **the artifact responds to attention.** It has had
none, at the level of authorship, since the day it was written.

## Already fixed by mod 134

Three fix-now naming tokens, repaired against compiled output rather than against prose:

| Site | Was | Now |
| --- | --- | --- |
| `service_discovery.md:5` | `myproject_dev_api`, and "a service named `api`" | `myproject-dev-api-web`, "the core service `web` of codebase `api`" |
| `network_web.md:5` | `{project}_{env}_web` | `${project}-${env}-web` |
| `network.md:3` | `${project}_${env}_${name}` | `${project_name}-${env_name}-${network_definition_name}` |

## Explicitly deferred to the overhaul, with the reason

**`vpc.md:9`'s underscored per-env subnets** — `${project}_${env}_public_a`, `_public_b`,
`_private_a`, `_private_b`.

These are **not repairable by renaming**, because *those subnets do not exist*. The real
four are prerequisite master-network subnets: `master_network_public-az1`,
`public-az2`, `private-az1`, `private-az2`. Renaming a phantom would make it look
canonical, which is strictly worse than leaving it visibly wrong. The whole entry needs
replacing (see above), and the subnet list goes with it.

## The rest of the work list

Per-file, so the overhaul opens with a work list rather than an audit:

| Site | Defect | Rule of record |
| --- | --- | --- |
| `backing_service.md:3` | "the doctrine's transfer tables pick a concrete engine" — the **project** declares `engine:` | `cicl.md:97,104,111` |
| `backing_service.md:3` | "MinIO" capitalized; the doctrine writes `minio` | `configurable.md`, `cicl.md` |
| `build_image.md:5` | image ref `myproject/api:0.4.2` omits the registry host | `container_registry.md:10`'s `${container_registry}/${project_name}/${codebase_name}:${version}` |
| `cert_manager.md:6` | one wildcard cert claimed; the doctrine issues **two** with explicit SAN sets, and the HTTP-01 (fixed) / DNS-01 (elastic) split is omitted | `shape.md:166`, `cicl.md#elastic-tls` |
| `dns.md` (whole entry) | model is pre-`apex_domain`: names a `domain:` field that does not exist, omits the `<project_name>` and core-service segments, gives prod as `www.<domain>` where `cicl.md:600` **forbids** `www` as a name, and `:12`'s apex→`www` redirect contradicts `cicl.md:281` ("these are routing choices, not redirects") | `cicl.md § Domain` |
| `environment_config.md:6` | puts the ALB and ECS cluster in the env `main.tf`; both are **project**-tier, and the whole `infra/output/project/…` tier is omitted | `shape.md:74`, `cicl.md § Compiler Output` |
| `environment_config.md:10` | `docex up` — the command is `docex envinfra up` | `docex.md` |
| `host_machine.md:5` | inverts single-machine hosting: "one host per environment" against *"one machine … hosting all environments"* | `infrastructure.md:304` |
| `network_internal.md:6` | the self-contradicting "project VPC" (`:10` has it right) | `shape.md:67` |
| `network_web.md:1`, `network_internal.md:1` | H1s match neither their `index.yml` key nor `shape.md`'s resource name | `index.yml:1-4` |
| `registrar.md:5` | same stale subdomain list as `dns.md` — one claim written twice | `cicl.md § Domain` |

## Shape of the overhaul

One mod, whole directory, no `docex` behavior change (`why` is a prose server). Per entry:
read the rule of record, rewrite against it, and leave a **bounded** `Doctrine reference:`
footer in `container_registry.md:10`'s form. Then:

1. Decide `vpc`'s fate (alias for `master_network`, or retire the key).
2. Reconcile `index.yml`'s keys with `shape.md` — including the `web_network` /
   `internal_network` spelling, which is a `docex why` **exit-1** today.
3. Add entries for as many of the eight uncovered `shape.md` resources as the mod can
   carry; `master_network` and `web_demux` first.
4. Split `registrar.md:8`'s compound citation, so the directory becomes mechanically
   boundable.
5. Consider whether this artifact can acquire an automated consumer at all — a check that
   every `index.yml` key resolves to a `shape.md` resource or a documented exception would
   have caught items 2 and 3 the day they landed. That is the standing lesson: **an
   artifact with no automated consumer drifts at the rate nobody looks.**

## Corrections to the figures this brief was scoped with

Recorded because this document's own subject is plausible-but-wrong counts.

1. **The `<domain>` rendering defect is `dns.md`-only.** Scoping named five sites
   (`dns.md:7-10`, `cert_manager.md:6`, `registrar.md:5`, `secrets.md:19`, `vpc.md`); four
   of them are backticked and render correctly. Verified by rendering each entry through
   `rich.markdown.Markdown`.
2. **`vpc.md` also lacks a `Doctrine reference:` footer**, not just `secrets.md`. Sixteen
   of eighteen entries carry one; those two are the exceptions.

## Not blocking a cut

Nothing here changes `docex`'s behavior, and none of it is caused by any pending cut. But
it should not wait for the *next* advance's sweep either: the evidence is that the next
sweep will be keyed on the next advance's vocabulary and will find these exactly as often
as this one's grep did — **once out of sixteen.**
