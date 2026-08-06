# Cohere Findings — Advance 005 (`process_type_solidification`)

Audit run at Mod 118's commit (`78af44c`), tree clean. Whole-corpus conceptual pass
done in one context (53 doctrine files + 22 skills read from disk); mechanical pass
run via `skills/cohere/executor/linkcheck.py` plus a delegated spelling/grammar pass
plus a hand-written skill→doctrine link checker.

**The four defects already known to sarge** (`database` as a reserved name in
`cicl.md` + `shape.md`; literal TABs in 16 of 42 `yml` fences; `cicl.md:22-107`
violating its own rule 7; `cicl.md:376-382`'s undeclared `database`) are **not
repeated below**. Nothing here duplicates them.

---

## Nothing needs fixing before the smoke walks

No finding below blocks either walk. Every one is prose, an illustrative example, a
router pointer, or a chart. The executor is not implicated anywhere except in the
*reverse* direction — F1, where doctrine describes behaviour `docex` does not have
(and correctly does not have). The `docex` implementation of the reconcile,
`wait_for_steady_state`, `schedules.yml` / `DOCEX_SCHEDULES_YAML`, the `uses`-driven
contract and health gates, and the rollback `cicl_version` pre-flight were all spot-
checked against source and match the current doctrine prose.

**Mechanical / semantic split:** 21 findings are mechanical (a stale name, a wrong
path, a dangling concept, a garbled sentence). 6 are semantic and want a ruling.
They are marked **SEMANTIC** inline and collected in the last section.

---

## Tier 1 — a doctrine file describes a mechanism the doctrine retired

### F1. `reasoning/elastic_release_pattern.md` documents the pre-advance Service Connect model — **SEMANTIC**, highest consequence

`doctrine/infrastructure/reasoning/elastic_release_pattern.md:18` and `:22`:

> "...for name resolution to work, all ECS services must be launched *twice*; once
> to fill out the Cloud Map registry, and then once again to ensure all ECS tasks
> actually have that registry."
>
> "...any release which adds a new named piece of infrastructure must perform a
> double-rollout. ... This shape-changing detection is part of the release process."

This contradicts, point for point, what mods 119/120 landed:

| `elastic_release_pattern.md` says | `release.md § Service Connect Consumer Reconcile` says |
| --- | --- |
| all services relaunched | "The comparison is **per-consumer**, not per-namespace." (`release.md:111`) |
| trigger is shape-change detection during the release | "Nothing is carried across the apply... A trigger keyed on *this release's* actions **cannot** do that." (`release.md:106`) |
| a double *rollout* | one bounded `forceNewDeployment` of only the consumers whose oldest task predates a name they `uses` (`release.md:100-104`) |

`cicl.md:416-422` (§ *Resilience covers reachability, not resolvability*) states the
same replacement model a third time. So the corpus now asserts two incompatible
elastic release mechanisms.

**Evidence it is stale, not merely differently-worded:** `grep -rni
'double.rollout|shape.chang' docex/src` returns nothing. `docex` implements exactly
what `release.md` describes (`aws/client.py:301`, `aws/boto3_client.py:489-558`,
`emit/hcl.py:734` for `wait_for_steady_state`). The doc describes behaviour the
executor does not have.

**Why it slipped through:** the file is *new*. `git log` shows it created in
`b9b3cc3` — the 1.7.0 rename commit at the head of this very advance — carrying the
pre-mod-119 understanding, and then never revisited when 119/120 replaced that
understanding. This is an advance-internal seam, exactly the failure mode the brief
predicted.

**Fix is semantic** because someone must decide whether the file is (a) rewritten to
explain *why* Service Connect forces a post-apply reconcile — which is a genuinely
useful reasoning doc the `release.md` prose currently has to carry inline — or (b)
deleted as superseded. Do not leave it as-is: it is the only file in the corpus that
would teach an agent to build a double-rollout.

Knock-on: `elastic_release_pattern.md:20` is the sole inbound link to
`charts/ecs_service_connect.md`. If the file is deleted, that chart needs re-homing
(the natural new parent is `release.md § Service Connect Consumer Reconcile` or
`cicl.md § Resilience covers reachability, not resolvability`).

### F2. Three conditional-stratum files have no router at all — **SEMANTIC**

`doctrine.md` is explicit that the conditional stratum reaches an agent *only*
through thread skills, and that keeping those pointers valid "is the one ongoing cost
of this structure." These three files declare `stratum: conditional` and are
referenced by **zero** skills, zero agents, and zero other doctrine files:

- `doctrine/infrastructure/reasoning/cicl_reasoning.md`
- `doctrine/infrastructure/reasoning/elastic_release_pattern.md`
- `doctrine/infrastructure/reasoning/healthchecks.md`

(Method: for every doctrine file, grepped its basename across `skills/` and
`agents/`. The fourth file in `reasoning/` — `ingress_and_egress.md` — is fine: it is
routed by `network-design` and linked from `cicl.md:456` and
`preinfra/elastic_master_network.md:13`.)

All three were created in `b9b3cc3`, i.e. by this advance. They are unreachable
information: not resident, not routed, not linked. `cicl_reasoning.md` in particular
holds the codebase-vs-core-service **field-scoping heuristic**, which is the single
clearest statement of the rule this whole advance turns on — and nothing points at
it. `infra-compile` is its obvious home.

Semantic because it needs a routing decision per file (which skill, General vs.
Specific Information), and because `healthchecks.md` is two sentences that may
deserve folding into `contracts.md` rather than a pointer of its own.

### F3. `charts/configurable.md:23` — the Config box points at the secrets file

```
 │ infra.yml:  │      `docex config scaffold`            ┌───────────────┬──────────────────────────────┐
 │ config      ├───────────────────────────────────────►│ all           │ $pr/infra/secrets/<env>.env  │
```

Should be `$pr/infra/config/<env>.env`. Copy-paste from the Secrets box two rows up.
Contradicts `configurable.md:72`, `config_and_secrets.md:51`, and `docex.md:137`.
Consequential because this chart is the one artifact an agent reads to learn *where
values live*, and the error puts config into the file agents are forbidden to read.
**Mechanical.**

### F4. `infrastructure.md:276` — TTE records are for `dev` and `test`, not `dev` and `stage`

> **tte** - Read-only records of [tte vars](./configurable.md#tte-vars) for `dev` and `stage`.

Contradicts the directory tree twelve lines earlier in the same file
(`infrastructure.md:174-176` lists only `dev.env` and `test.env`),
`configurable.md:37`, and `config_and_secrets.md:137` ("dev/test: local
`infra/tte/<env>.env`"). Stage's TTE store is the *host*, per
`config_and_secrets.md:139-140`. This is a resident-stratum file, so the wrong
statement is always in context. **Mechanical.**

### F5. `cicd.md:254` — rollback pre-flight names the wrong CICL boundary

> "...a target predating the v1 → v2 boundary cannot be rebuilt"

The boundary that matters after this advance is **v2 → v3**; the CHANGELOG's own
Unreleased entry says so ("the v2→v3 boundary is refused at pre-flight"). The
executor is already generic — `pipeline/rollback.py:316` renders
`f"v{generation}→v{CURRENT_CICL_VERSION} boundary"` — so only the prose is stale.
**Mechanical** (best fix: reword to name no specific generation, matching the code).

---

## Tier 2 — rename-sweep residue that teaches by wrong example

These are the "blind swap / missed swap" class. Each sits *underneath prose in the
same file that states the correct rule*, which is what makes them worth fixing: a
reader who trusts examples over prose gets the retired form.

### F6. `elastic_alb.md` — four sites still use one-segment core-service identity

`doctrine/infrastructure/specifics/projinfra/elastic_alb.md`:

- `:44` — target group rendered example `myproject-stage-web-tg`
- `:49` — `${project}-${env}-${service}-tg`, example `tactical-lifecycle-test-stage-web-tg`
- `:76`, `:81` — `resource "aws_lb_listener_rule" "api"` / `aws_lb_target_group.api`
- `:86` — host-header value `"api.prod.myproject.example.com"`
- `:59` — prose: `Host: api.prod.myproject.example.com`

The correct forms are `myproject-stage-api-web-tg` and
`api-web.prod.myproject.example.com`. Confirmed against the emitter:
`emit/hcl.py:810` renders `apply_policy(f"{svc.global_name}_tg", …)` where
`global_name` is `<project>-<env>-<codebase>-<service>`, and against `shape.md:173`,
which gets it right ("1 ALB target group for the prod `api-web` core service…
`api-web.prod.myproject.example.com`").

Self-contradicting: `elastic_alb.md:64`, immediately above the wrong HCL block, says
"core services that are not the default get only the full
`<codebase>-<service>.<env>.<project>.<apex>` host". **Mechanical.**

Note the length argument at `:49` gets *stronger* with the correct name, not weaker —
worth re-deriving the example so the `hash_truncate` rationale still lands.

### F7. `ec2_traefik.md:65-67` — same residue in the traefik label example

```
traefik.http.routers.api-prod.rule=Host(`api.prod.myproject.example.com`) || …
traefik.http.routers.api-prod.tls.certresolver=doctrine
traefik.http.services.api-prod.loadbalancer.server.port=8080
```

Router key should be `api-web-prod` and the host `api-web.prod.…`. Contradicts
`ec2_traefik.md:61` four lines above — "Router names encode the env
(`<codebase>-<service>-<env>`)". **Mechanical.**

### F8. `hex_overview.md:129` — "service/flow tests… the whole service"

> "The first four each target a distinct layer… the fifth (service/flow tests)
> exercises the whole service at once."

The fifth tier's own heading at `:159` is "Codebase Integration / Flow Tests" and
`:161` says "The scope is the codebase, not one of its core services." The intro
sentence kept the retired noun. Resident-stratum file. **Mechanical.**

### F9. `docex.md:123` — "core `secrets:` blocks"

> "...the deterministic set derived from `infra.yml` + doctrine (core `secrets:`
> blocks, backing engines' `kind: secret` env vars, …)"

`secrets:` is codebase-scoped (`cicl.md:139`, table row *Scope: codebase*), and every
sibling statement of this same manifest says "codebase `secrets:` blocks"
(`config_and_secrets.md:66`, `:165`). "core" here is the pre-1.7.0 word for codebase.
**Mechanical.**

### F10. `skills/project-cohere/SKILL.md:109, 115, 117` — "service" where it means codebase

The chunker walks `core/*/src` — i.e. codebase roots — but the prose reads "one or
more whole **services** packed together", "a subset of a single **service's** hex
modules", "`services` — which service(s) the chunk's code belongs to". After this
advance a "service" is a deployment, and a codebase's core services share one source
tree, so the sentence as written is now false rather than merely old-fashioned.
Worth checking whether `executor/chunk_map.py`'s JSON key is literally `services`; if
so the rename has a small code half. **Mechanical.**

### F11. `infrastructure.md:253` — broken sentence left by the sweep

> "A very simple case is a webapp two codebases: `frontend` and `api`"

Missing "with". Resident file. **Mechanical.**

### F12. `cicl.md:386` — self-doubling sentence left by the sweep

> "Where an engine genuinely needs another container beneath it, which containers an
> engine requires is an *engine* concern and belongs in its transfer table's
> `defaults` block, not in `infra.yml`."

Two clause-heads competing. Reads as: "…, that requirement is an *engine* concern
and belongs in…". This sits inside § *Uses Relationships*, the advance's centerpiece
section. **Mechanical.**

---

## Tier 3 — internal inconsistencies

### F13. "Subsequent releases find the **cluster** present" — two files, same slip

- `cicd.md:209`
- `migrations.md:96`

Both paragraphs *open* by correcting exactly this ("the detector keys off the env's
*service*, not the cluster"; "detects a first release via an ECS-service-existence
probe") and then *close* with "Subsequent releases find the cluster present and
follow the steady-state order." The cluster is project-tier and always present, so
the closing sentence restates the misconception the paragraph exists to kill.
**Mechanical** (→ "find the env's ECS service present"). Not advance residue; it
predates it, but it lives in the two paragraphs this advance's readers land on.

### F14. `chain_of_command.md:46-47` — the escalation column is circular

| Name | … | Escalates To |
| --- | --- | --- |
| private | … | `private` |
| corporal | … | `corporal` |
| sarge | … | Operator |

A rank escalating to itself contradicts `:88` ("it escalates that decision to its
C.O. … decisions ripple all the way up to the human operator") and the whole premise
of the file. Almost certainly should read `corporal` and `sarge`. Marked
**SEMANTIC** only because I will not guess the intended ladder for you — but it is a
two-cell edit once ruled.

### F15. `chain_of_command.md:32` — a second, drifted definition of "Advance"

The file keeps its own private `## Lexicon` defining Advance as "a planned collection
of **mods**", while `practices/advance.md:7` defines it as "a planned collection of
mods **and other processes**" (the difference is load-bearing — `advance.md`'s own
example plan includes a `project-cohere` step and a release step, neither a mod).
Two definitions of one lexicon word in two files. Cosmetic, but it is the exact
mechanism the lexicon exists to prevent. **Mechanical** (delete the duplicate row and
link to `lexicon.md`, or promote the row into `lexicon.md`).

---

## Tier 4 — vocabulary, after two renames in two releases

### F16. `clock` now names two unrelated things — **SEMANTIC**

- `role: clock` — a core service that owns a cron loop and enqueues
  (`specifics/clock.md`, `cicl.md:72-84`).
- `Clock` — a canonical **driven port pattern**, "Abstracts access to the current
  time so alogic remains deterministic and testable" (`hex_overview.md:259`).

Both are resident-or-near-resident vocabulary, both are load-bearing, and neither
file acknowledges the other. The collision is real in code: a `clock` core service
whose alogic depends on the `Clock` driven port yields `ClockClock`-shaped confusion,
and the doctrine's own architecture sketch (`clock.md:65-72`) sidesteps it by naming
the adapter `ContJobsCron` — the cron word, not the clock word.

Needs a ruling. Three defensible outcomes: (a) accept and add one disambiguating
sentence to each file; (b) rename the role to `cron`; (c) rename the driven pattern
(costly — it is the industry-standard name). I lean (a); (b) was presumably already
weighed when the role was named, and I don't want to re-open it silently.

### F17. `lexicon.md` has no entry for `uses`, `role`, or `clock` — **SEMANTIC**

The lexicon carries `Core Service`, `Codebase`, and `Entrypoint` — all three updated
by this advance — but not the relation that replaced two others and is now cited by
name in eleven files. `doctrine.md:40` gives the resident stratum the job of
supplying "skill-triggering vocabulary"; `uses` is the highest-traffic new word in
the corpus and it is absent from the vocabulary file. Same for `role`, which every
service declares.

Semantic because you may deliberately want the lexicon to hold *concepts* rather than
*field names* — there is no entry for `env:` or `networks:` either. But `uses` is not
a field like the others; it is the one relation, and the advance's own framing treats
it as a concept.

---

## Tier 5 — structure and hygiene

### F18. Duplicate filename: `configurable.md` — **SEMANTIC**

`doctrine/charts/configurable.md` and `doctrine/infrastructure/configurable.md`. The
only finding `linkcheck.py` reports, and it fails the cohere skill's check 3 ("all
filenames should be unique"). Pre-existing. Semantic only in that renaming a chart is
a judgement (`configurable_flow.md`? `configurable_chart.md`?) and any inbound link
must move with it (one, from `skills/configurable-vars/SKILL.md`).

### F19. `charts/configurable.md` and `charts/ecs_service_connect.md` carry no `stratum:` frontmatter

`charts/ing.md` does. `doctrine.md:28` states doctrine files carry the frontmatter,
and the SessionStart resident loader is frontmatter-driven, so a missing field is a
silent classification. **Mechanical.**

### F20. `docex.md`'s "Provided Tools" table omits `secrets` and `config`

Both have full `###` sections at `:115` and `:130`, and both are cited from the
resident `configurable.md:57` as the agent's entry point — but neither appears in the
command table an agent scans first. Pre-existing. **Mechanical.**

### F21. `skills/docex-edit/SKILL.md` declares `type: thread` but has none of the thread body structure — **SEMANTIC**

`doctrine/skills/skills.md:24-30` mandates an H1 + intro, a **mandatory**
`## General Information`, an optional `## Specific Information`, and an optional
`## Thread`. `docex-edit` has none of these while claiming thread type. Either the
body is brought to form or the metadata is corrected. Pre-existing; flagged because
`skills.md` calls the `## General Information` section mandatory.

### F22. `linkcheck.py` does not check the links the doctrine says matter most — **SEMANTIC**

The executor walks `doctrine/` only ("Scanned 53 markdown files under …/doctrine").
Skill→doctrine router pointers — the thing `doctrine.md:57` names as "the one ongoing
cost of this structure, and it should be checked mechanically" — are *not* covered.

I checked them by hand this run with a scratch variant that builds the anchor table
from both trees: **all skill router links and anchors currently resolve.** But that
result is not reproducible by the shipped executor, and section renames are precisely
what this advance did three of. Recommend extending `linkcheck.py` to take
`skills/` as an additional source root while resolving anchors against both trees.
Semantic because it is a change to the cohere tooling contract, not a text fix.

---

## Resident-stratum discipline

Checked the thirteen `stratum: resident` files for conditional detail that crept in.
The advance itself added almost nothing objectionable — the one new resident line is
the `Cron` row in `hex_overview.md:279`'s controller-mechanism table, which is
correct placement (that table is the canonical list).

Two standing observations, neither advance-caused:

- **The `docex secrets` op table exists in three places** — resident
  `configurable.md:59-64`, conditional `docex.md:115-128`, and conditional
  `config_and_secrets.md:299-304`. The resident copy is the one that must never
  drift, and it currently differs from the other two in a small way (it says the
  status read reports "declaring codebase"; `config_and_secrets.md` says "source").
  Consider cutting the resident copy to one sentence plus the pointer it already has.
- **`infrastructure.md § Contracts` (`:247-267`) restates `contracts.md`** — the
  provider/consumer example, the filename form, and the "must have a contract to pass
  CI" rule all appear twice. It is also the site of F11. This is the largest resident
  file and the strongest candidate for thinning, but thinning it is a judgement call
  and out of scope for this report.

---

## Spelling and grammar

Delegated pass. All **mechanical**; F8/F11/F12 above are the ones with conceptual
weight and are already covered. The remainder:

| File:line | Text | Fix |
| --- | --- | --- |
| `hex_overview.md:228` | table row missing trailing pipe — cell runs open | append ` \|` |
| `contracts.md:39` | ``the project` won't pass`` | drop stray backtick |
| `chain_of_command.md:23` | "is an differing approach" | "a differing" |
| `chain_of_command.md:59` | "Straightforwards code investigation" | "Straightforward" |
| `chain_of_command.md:88` | "the C.O. agent much choose" | "must choose" |
| `chain_of_command.md:122` | "an agents rank" | "an agent's rank" |
| `chain_of_command.md:129` | "imbedded" | "embedded" |
| `elastic_release_pattern.md:26` | link text `healtchecks.md` | `healthchecks.md` (target is correct) |
| `modifications.md:7` | "implementing changes a project" | "changes to a project" |
| `advance.md:18` | "Good success criteria is specific" | "criteria are specific" |
| `skills/cohere/SKILL.md:19,20` | "conditional strata" / "resident strata" | singular `stratum` both |
| `lexicon.md:13`; `configurable.md:31,43`; `docs.md:13` | `LLM's`, `URI's`, `LLM's`, `README's` | plurals, no apostrophe |
| `inception.md:74,76` | "These can be empty, they must merely exist." ×2 | semicolon |
| `shape.md:55` | "over shared environment [network]." | `[network]s` (twin at `:25` is plural) |
| `cicd.md:209` | "the env's ECS services and RDS the migration task targets don't exist yet" | insert commas / "the RDS instance" |
| `cicl.md:207` | "2. Docker containers `${project}-…`" | add colon (line 206 has one) |
| `tests.md:67` | "- consumer's tests hit the mock" | capitalize |

---

## Semantic findings, collected

These six need a ruling before the fix mod can land them:

1. **F1** — rewrite or delete `reasoning/elastic_release_pattern.md`; decide where
   `charts/ecs_service_connect.md` re-homes. *(Highest consequence in the report.)*
2. **F2** — route or fold the three orphaned `reasoning/` files.
3. **F14** — confirm the intended escalation ladder in `chain_of_command.md`.
4. **F16** — rule on the `clock` role vs. `Clock` driven-pattern collision.
5. **F17** — decide whether `uses` (and `role`) earn lexicon entries.
6. **F18 / F21 / F22** — the hygiene trio: rename one `configurable.md`; bring
   `docex-edit` to thread form or drop its `type: thread`; extend `linkcheck.py` to
   cover `skills/`.

Everything else — 21 findings — is mechanical and can land autonomously.
