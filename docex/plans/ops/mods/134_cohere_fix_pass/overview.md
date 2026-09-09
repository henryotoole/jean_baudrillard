# Mod 134 — Advance 006 Cohere Fix Pass

## Goal

Close out advance 006 by repairing the prose, factual, and citation defects that
`project-cohere` surfaced, in the shape of advance 005's mod 121. Every edit falls in
one of five sanctioned classes: repair prose, correct a factual claim to match
measured behavior, fix an example so it obeys a rule already written, complete a list
that has silently lost a member, or repoint a citation. **No edit changes what a rule
means.**

## Scope decision — this mod is Tier 1 + Tier 3; Tier 2 becomes mod 134b

The C.O. offered a split along the Tier1/Tier2 line and asked to hear early rather
than late. **I am taking the split**, with one adjustment to where the line falls.

Verified edit counts, after checking every claim against the tree:

| Tier | Files | Discrete edits | Notes |
| ---- | ----- | -------------- | ----- |
| 1 | 8 | ~28 | includes a checklist cascade and two new boxes |
| 2 | 13 | ~20 | code docstrings + core docs; self-contained |
| 3 | 3 | 1 brief + 3 tokens | brief is written from data now in hand |

**Mod 134 takes Tier 1 and Tier 3. Mod 134b takes Tier 2.**

Tier 3 travels with Tier 1 rather than with Tier 2 because its brief is the expensive
part and the audit data behind it is verified and in hand *right now*. Deferring it
would mean re-deriving an 18-file audit, a per-file blame ratio, and a
`shape.md`↔`index.yml` diff from scratch — the single most wasteful thing in the whole
pass. Tier 2, by contrast, is a clean handoff: seventeen independent claims, each with
its own file and its own verified truth, none of which depends on anything in Tier 1.

## Escalations — three, all resolved

**All three were escalated at the design gate and answered. Decisions are recorded
inline below.** The split (134 = Tier 1 + Tier 3, 134b = Tier 2) is approved, as are
all five of the corrections this mod made to the brief it was given.

### E1. Rule 33 was factually wrong about the ec2_traefik target group — RESOLVED at the source

**DECISION: the C.O. fixed rule 33 himself in `7f8d261`. Do not edit rule 33; align
items 2 and 3 to its new text. Item 5 is dropped. The stale `hcl.py:830-837` docstring
moves into Tier 1 as this mod's to kill.**

The corrected rule now reads: consumed by the ALB target group on `elastic` + `alb`
**alone**, and **no consumer at all everywhere else**, uniformly — rather than
special-cased per proxy. It still requires the field everywhere for portability, and it
now records that neither traefik path routes on health in any case.

Worth keeping on the record, because it is this advance's own defect class committed
into the rule of record: the false clause was built on `render_target_group`'s
docstring, which describes a cleanup that had already happened. **Two docstrings in one
file contradict each other** — `_destination_applicable`'s is correct,
`render_target_group`'s is stale — and the stale one was cited as evidence about
current behavior. It was caught by checking the claim against the code instead of
against the citation.

#### The original escalation, retained for the record

**Tier 1 item 5 is inverted.** The brief says `ec2_traefik.md:198-203`'s env-tier list
omits an `aws_lb_target_group` the compiler emits per `web` core service on that path.
It does not omit it. **The compiler does not emit one.**

`emit/hcl.py:1085-1090`, `_destination_applicable`, reached from the dispatcher at
`:1112`:

```python
if dest == "target_group":
    if "web" not in svc.networks:
        return False
    if ctx is not None and ctx.reverse_proxy != "alb":
        return False
    return True
```

So the doctrine list is correct and needs no edit. Two other things are wrong instead:

1. **`render_target_group`'s docstring (`emit/hcl.py:830-837`) is stale.** It says "We
   still emit the target group: ... even when traefik is the front door the
   target-group resource is harmless (no ALB attaches to it). Future cleanup mod can
   prune." The function is never reached on `ec2_traefik`. That cleanup already
   happened; the docstring did not notice. **This is the docstring the brief cited as
   corroboration** — it is the defect, not the evidence.

2. **Rule 33 itself, `cicl.md:619`, states the same false thing.** Verbatim: "On the
   `ec2_traefik_eip` / `_pip` variants the compiler still emits a target group carrying
   the path, but no ALB attaches to it, so the value is inert." There is no target
   group at all, so on `ec2_traefik` `health_check_path` has **no consumer whatsoever**
   — the identical position it holds on `fixed`.

This is `8537083`'s own B2, written a few hours ago. I am flagging rather than editing
because Tier 1 items 2 and 3 are both "align to rule 33", and aligning to a sentence
that misstates the compiler would propagate the error into two more files.

The correction is narrow and does not change what rule 33 *requires* — the field is
still mandatory on `web`, still forbidden off it, still consumed on `elastic` + `alb`
and there alone. It only corrects *why* it is inert elsewhere, and it makes the rule
stronger: the inert case is now uniform rather than special-cased. **Proposed
replacement for that one clause:**

> On the `ec2_traefik_eip` / `_pip` variants the compiler emits no target group at all
> — `emit/hcl.py`'s `_destination_applicable` suppresses it whenever `reverse_proxy` is
> not `alb` — so the field has no consumer there either; traefik's ECS provider routes
> on `lastStatus == RUNNING`, which is a lifecycle state and not a health verdict.

**Requested:** approve this wording (or supply your own) before items 2 and 3 land.
If you would rather rule 33 not move at all this cycle, say so and I will fix only the
`hcl.py` docstring and leave items 2/3 aligned to the rule as written — but then the
doctrine keeps a measurably false sentence in a numbered rule.

### E2. `${project_version}` is not a compile-time variable — RESOLVED

**DECISION: approved as corrected. Add `${service}` and `${codebase_name}`; do not add
`${project_version}`. Annotate `transfer_tables.md:793` rather than rewrite it. Fix
`${networks}`'s "the list" while in the table.**

Item 6 asks for `${service}`, `${codebase}`, and `${project_version}` to be added to
`transfer_tables.md`'s always-available table. Measured against
`cicl/compile.py:740-760`, which builds the substitution context as a single dict
literal:

- **`${service}` is real** (`compile.py:755`) and load-bearing in shipped tables
  (`web.yml:36,67`, `worker.yml:39,61`, `clock.yml:53,75`). Add it. This is the residue
  `fa5d3fb` left.
- **`${codebase}` does not exist. The key is `codebase_name`** (`compile.py:759`). Add
  `${codebase_name}`.
- **`${project_version}` is not a table variable at all.** It is a Python parameter
  (`compile.py:588,672`) that the emitter interpolates into f-strings. Adding a row for
  it would *create* a false claim in the very table whose purpose is to enumerate what
  resolves — the opposite of the fix.

`substitute.py` adds nothing (`:74` is a bare `ctx[name]`), so that dict is the
complete set. Two consequences:

- **`transfer_tables.md:793`** uses `${project_version}` and `${codebase}` in its
  `OTEL_RESOURCE_ATTRIBUTES` row. That string is *compiler-composed*
  (`compile.py:1009-1020`), not table-interpolated, so under the file's own validation
  rule 5 two of its five tokens would not resolve. **Proposed:** annotate the row as
  compiler-composed rather than rewrite it, since rewriting would misrepresent where
  the string comes from. Flagging because it is a judgement call about a rule-5
  boundary, not a typo.
- **`${networks}` is described as "The list of networks"** but is
  `",".join(svc.networks)` — a string (`compile.py:745`). Factual correction, in-file,
  taking it.

### E3. `PRE_CUT_CHECKLIST` A.2 is a whole release behind — RESOLVED

**DECISION: approved. Make A.2 version-agnostic — a box that reads the version rather
than restating it stops going stale every cut. No version number is baked in.**

A.2 says the seeds "sit at `1.6.0` today" and asks for a repin to `1.7.0`. Measured:
both seeds **and** `/VERSION` are already `1.7.0` (`test_projects/fixed/project.yml`,
`test_projects/elastic/project.yml`). So the box is stale in both operands, including
its `docker images docex:1.7.0` line — as written it asks the walker to repin a repo
that is already correct, and the following box then has nothing to commit.

Writing `1.7.0 → 1.8.0` asserts the next cut is a MINOR. **That is a release-scope
decision and is not mine.** **Proposed:** make the box version-agnostic — refer to
"the candidate version" and "the released version" rather than literals, so the box
stops going stale every cut. This is the fix that cannot be wrong regardless of what
the next number turns out to be. Confirm, or give me the number.

## Design — Tier 1

Ordered so the two items that depend on E1 come after it.

1. **`cicd.md:60`** — restates rule 32 without the `web`-network exemption, reproducing
   the form that made rules 15 and 32 contradict on the `frontend`/`api` topology. Add
   the exemption in the same terms rule 32 now uses.
2. **`cicd.md:61`** and **`healthchecks.md:73`** (not `:71`) — both say
   `health_check_path` is "what the load balancer probes / reads", unqualified. Narrow
   both to `elastic` + `reverse_proxy: alb`, in the form E1 settles.
3. **`reasoning/cicl_reasoning.md:22`** (path is `reasoning/`, not `specifics/`) — uses
   `health_check_path` as the canonical example of a field that "follows `role`". Rule
   33 keys it on network membership. **`schedules` is the correct example and is
   already on the same line**: it exists only in `clock.yml:81` and rule 4 rejects it on
   every other role. Swap the example; the derivation at `:24` then stands unchanged.
4. **`ec2_traefik.md:59` and `:152`** — "health-gating" and "health-aware routing" over
   a `lastStatus == RUNNING` filter, plus "drops a task from the pool as soon as it
   leaves `RUNNING`". Recast as lifecycle-state load-balancing. Note the surviving true
   claim: traefik does balance across all running task IPs, which DNS round-robin
   cannot; only the *health* framing is false.
5. **`ec2_traefik.md:198-203` — no edit; the list is correct.** Replaced by killing
   **`emit/hcl.py:830-837`**, `render_target_group`'s stale docstring. It claims "We
   still emit the target group … even when traefik is the front door the target-group
   resource is harmless (no ALB attaches to it). Future cleanup mod can prune." Mod 070
   already pruned it: `_destination_applicable` returns `False` for `target_group`
   whenever `reverse_proxy != "alb"`, so the function is never reached on that path. The
   two docstrings in this one file contradict each other, and the stale one is what
   misled the rule of record. It is the thing that will mislead the next reader the same
   way.
6. **`transfer_tables.md:50-65`** — add `${service}` and `${codebase_name}`; correct
   `${networks}`; annotate `:793` per E2.
7. **`docex_process.md`** — `:170-172` says the bare binary "reports **17** deselected
   instead of 18". **Both numbers are stale; measured is 21** (itemized: 21 integration
   marks across 14 files). And `:147`/`:153-154`'s "Nine of eighteen" / "eight of the
   nine" do not reconcile with the table at `:138-145`, which names **ten** distinct
   files. Per instruction, replace the ordinal with the *method* rather than a new
   number. **`:154`'s "The four still open" is correct** — the three `booked, not fixed`
   rows name exactly four files. Do not touch it.
8. **`RELEASING.md:73`** — "`pytest` (incl. `-m integration`)". `pyproject.toml:49` sets
   `addopts = "-m 'not integration'"`, so `-m integration` composes to
   `-m 'not integration' -m integration` and matches nothing while exiting 0. Replace
   with the two-invocation pair. This is the file's only pytest invocation.
9. **`PRE_CUT_CHECKLIST.md`** — seven repairs:
   - **A.3.1 (`:65`)** — drop the "project-agnostic, run from either root"
     parenthetical. `_check_dev_dns` resolves *this* project's hostnames
     (`preinfra.py:246-258`, via `ctx.project.name`), and the manifest-delete probe
     fires only for `foundation: fixed` with a `container_registry`
     (`preinfra.py:181`). The file already contradicts itself here — `:107` quotes the
     project-specific failure message and A.5 `:123` pins the run to the fixed root.
   - **A.2** — per E3.
   - **A.4.1 (`:89-90`) / A.4.2 (`:106-107`)** — drop the `test` and `*.test` records.
     `test` is no longer routed or TLS'd (`preinfra.py:249-252`) and neither seed's
     compiled `test` compose contains a single `Host(` or `traefik` string. **Cascade:**
     `:83`'s "these nine records" and `§ E :825`'s "nine standing records" become
     seven; A.4.2's "same four records" becomes two. Also a stray backtick pair at
     `:106`, fixed while in the line.
   - **B.11.1 (`:421`)** — `/health/events` → `/diagnostics/events` (real path,
     `root.py:179` in both seeds). The lone holdout; `:490`, `:626`, `:702` already use
     the right path, and `:626` states the rationale.
   - **D.9 (`:665`) / D.11 (`:752`)** — `0.0.21` → `0.0.24` (elastic seed is at
     `0.0.23`; D.12 `:797` bumps once). **Touch only the trailing `skip` clause of that
     one sentence.** The `fire` clause, the derivation halves (`:645-650` / `:732-737`),
     both `N = 2` clauses (`:659-661` / `:746-748`), the verdict tables, the
     "neither line appearing" paragraphs, the blockquotes, and the `aws` command blocks
     are all verified correct and version-independent.
   - **D.8 (`:635`)** — "the D.3/D.7 ordering" → **D.3/D.4**. `:607` is `### D.4
     Compile`; `:629` is `### D.7 Test`, unrelated to the compile/projinfra ordering the
     sentence is about.
   - **New boxes after `:468` (C.6) and `:637` (D.8)** — record `docex check`'s
     `contracts_exist` and `contract_health_path` lines. B.9 (`:251-259`) explicitly
     promises this ("record the gate's line when you get there") and nothing delivers,
     so the **orphan arm** — the only thing that catches a leftover three-segment
     contract sitting *beside* its replacement, per `check.py:413-416` — is asserted
     nowhere. Both seeds hold three contracts and one `web`-network openapi provider, so
     the green lines are known exactly and the box can be written to assert real text.

## Design — Tier 3

One brief at `docex/plans/advances/007_small_edges/doctrine_excerpts_overhaul.md`,
booking the overhaul. **Four of the brief's given figures did not survive verification
and the brief will carry the measured ones:**

- **15 of 18 defective, 3 clean — not 16/2.** `container_registry.md` is a third clean
  file; mod 133 rewrote it (`8bef555`) and it verifies. Overstating by one in a document
  whose subject is plausible-but-wrong counts would be self-defeating.
- **The three misinstructing entries all confirm**, with `reverse_proxy.md`'s bullet
  carrying exactly **four** errors (a fifth, "the project's ACM cert" singular against
  two SAN'd certs, is arguable and will be named as arguable). The bullet is `:7`, the
  Elastic one.
- **The `index.yml` figures confirm exactly**: clean 18/18 bijection, **eight**
  `shape.md` resources with no entry (`web_demux`, `master_network`, `repo`,
  `observability_backend`, `configurable_vars`, `telemetry_sidecar`, `nat_gateway`,
  `ecs_cluster`), and two inverted keys (`shape.md` says `web_network` /
  `internal_network`; `index.yml` says `network_web` / `network_internal`). `docex why
  web_network` prints `unknown resource`, dumps the 18 keys, exits 1
  (`why/catalog.py:66-71`). `index.yml:1-4` states the very rule it breaks.
- **The advance-005 rename residue is not what the brief says.** No stale *nouns*
  survive — one grep hit, and it is a correct unrelated use. The residue is
  **structural**: the rename gave the compiled identity a fourth segment, and the files
  still show three. That is why a vocabulary grep cannot see it — the offending token
  contains no renamed word.
- **Pre-existing ratio: 15 of 16 defect sites (94%) predate advance 006, 14 of them
  from one commit** (`307d47a`, 2026-05-26, the directory's original authoring). The one
  006-attributed site is a cosmetic variable-name leak with a correct rendered value.
  The brief will also record the countervailing fact honestly: advance 006 *improved*
  every excerpt it touched.

Plus `registrar.md:8`'s compound citation, folded in: the `§` sits outside the closing
backtick, so `linkcheck.py:124`'s `CITE_RE` leaves it unbounded, and it names two
headings (`### Fixed-Foundation`, `### Elastic-Foundation`) where no single heading
exists. It is the **only** unresolvable citation in the directory — the other 15 all
resolve — so splitting it is the precondition for mechanically bounding the directory.

### Tier 3 fix-now — three tokens, not two

`service_discovery.md:5` (`myproject_dev_api` → `myproject-dev-api-web`; also "a
service named `api`" is post-005-wrong, `api` is a codebase) and `network_web.md:5`
(`{project}_{env}_web` → `${project}-${env}-web`; underscores *and* missing sigils).

**Adding `network.md:3`** (`${project}_${env}_${name}` →
`${project_name}-${env_name}-${network_definition_name}`). It is the same
two-advance-old residue in the same directory; fixing two of three occurrences leaves
the directory internally inconsistent and the next reader unable to tell which spelling
is current. Ground truth is compiled output:
`docex-smoke-fixed-dev-api-web`, `docex-smoke-fixed-dev-web`.

**`vpc.md:9`'s underscored subnets are deliberately left to the advance** — they are not
repairable by renaming, because those per-env subnets do not exist at all. Renaming them
would make a phantom look canonical.

## Deferred to mod 134b (Tier 2)

Seventeen claims, all verified, with two corrections to the brief worth recording now so
134b does not have to re-derive them:

- **`naming.ecs_cluster_name` is not undocumented.** `release_flow.md:62` and `:141`
  document it thoroughly, both naming the same five readers. It is undocumented only in
  `compiler.md` and `masterplan.md`. The fix is narrower than stated.
- **`stagetest.py:5` has two defects, not one** — the field name (`domain` →
  `apex_domain`) *and* the URL shape: it says `https://stage.<domain>` where the code
  builds the three-segment `f"https://stage.{project_seg}.{apex_domain}"` (`:92`).
- Everything else in Tier 2 verified as stated, including all eight
  silently-shortened lists.

## Cosmetics

Per instruction, taken only where already in the file for a Tier 1/3 reason: the
`:106` stray backtick in the checklist. **Booked, not fixed:**
`ingress_and_egress.md:22-26`'s arithmetic (`70 + 10 + 44×2 = 168`, stated as `158`;
the author dropped the LCU floor — and `:28`'s "half the fixed cost (about $90/yr)" is
not half of either figure), and the excerpts' cosmetic set, of which one is a real
rendering defect rather than a nit: bare `<domain>` inside markdown tables
(`dns.md:7-10`, `cert_manager.md:6`, `registrar.md:5`, `secrets.md:19`, `vpc.md`) is
parsed as an HTML tag and **renders invisibly** under `rich.markdown.Markdown`
(`catalog.py:80`).

No pass over the corpus for punctuation.

## Verification

`pytest docex/tests -q` (1199 passed, 21 deselected), integration alone (21),
`linkcheck.py`, `verify_examples.py`. All four must be green and counted. Two commits.
No manual-test pause.

## Design questions

1. **E1 — approve the rule 33 wording?** This is the blocking one: items 2 and 3 align
   to that sentence. Alternative is to fix only the `hcl.py` docstring and leave a
   measurably false clause in a numbered rule.
2. **E2 — annotate `transfer_tables.md:793` as compiler-composed, or rewrite it?** I
   propose annotate.
3. **E3 — version-agnostic A.2, or do you want the next version number written in?**
4. **Do you accept the 134/134b split as drawn** (Tier 1 + Tier 3 here, Tier 2 next),
   including Tier 3 travelling with Tier 1 for the reason given?
