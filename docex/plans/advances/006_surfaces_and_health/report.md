# Advance 006 — Report

**Target cut: 1.7.0**, shipping alongside advance 005 in one release. Eleven mods
(125–135), two close-out audits, two skill gates, and a pre-cut walk. Status at
writing: **mods complete; walk sections A and B green; C, D, E outstanding.**

The design record [`surfaces_and_health.md`](./surfaces_and_health.md) was settled
before the advance began and **never had to be reopened.** Every mod landed, no
design decision was reversed, and the two halves shipped as specified. What
consumed this advance was not the design. It was the **instruments**.

## Goals — outcomes

**Goal 1 — `surfaces:` replaces role-derived contract selection.** Achieved. A core
service declares `surfaces:`; `api_styles` resolve to exactly one contract format;
each surface compiles to one contract at
`${codebase}.${service}.${surface}.${format}.${ext}`. A core service is a provider
**iff** it declares surfaces. `_CONTRACT_FORMAT_BY_ROLE`, `_FALLBACK_CONTRACT_FORMAT`
and the two-armed provider union are gone; rules 29–33 enforce the new model and
rule 28 is tombstoned. Both seeds carry three surfaces across two core services,
including two surfaces of one format resolving to distinct filenames — a shape
nothing in the repo previously exercised.

**Goal 2 — health leaves HTTP.** Achieved. The container probe is
`["CMD", "./health.sh", "<service>"]`, emitted from transfer-table `defaults` on
both foundations, and **absent** from every `-otelcol` sidecar, `-exec` block and
migrate task — verified by a census over all eight compiled artifacts, not by
reading. The `/health/<codebase>/<service>` fan-out is deleted. `GET /health`
survives only for `web`-network services. `docex stagetest` reads liveness and
version from the orchestrator before it builds the tester image, with 22
can't-answer modes each demonstrated red.

**Goal 3 — the cut stays shippable.** Substantially achieved, walks outstanding.
Six-artifact alignment swept; `upgrades/upgrade_1.7.0.md` extended to cover both
advances; `PRE_CUT_CHECKLIST.md` rewritten and then repaired again by its own first
execution. `cicl_version` stays `"3"` — generation 3 was introduced by advance 005
and never released, so folding `surfaces:` into it avoids manufacturing a second
rollback-unavailable boundary inside one cut.

## The instruments were the advance

Advance 005 catalogued **eight** instances of one defect: *something that could not
answer reported zero, and zero read as clean.* This advance found that shape, or its
mirror, **twenty-one times** — and the mirror is worse, because it provokes wrong
repairs rather than merely permitting them.

| # | The instrument | What it reported | The truth |
| --- | --- | --- | --- |
| 1 | `pytest tests/unit` | green, 3× across 3 briefs | 12 tests red; 60 unmarked tests live under `tests/integration/`, so the habitual pair of invocations has a **60-test hole invisible from either side**. Two had been red since advance 005. |
| 2 | `test_check_real_happy_path` | red, blamed on this advance | Already red before it began. `FROM python:3.12-slim` is a floating tag; Debian dropped `curl`. Advance 005's "integration 20/0" decayed unobserved. |
| 3 | `linkcheck.py` | *"No broken links, bad anchors, or duplicate filenames found"* | Skipped anchor checks **silently** for any link outside its roots — and mod 121's changelog already reported that fail-open as *fixed*. Adding a root closed the instance and left the class. |
| 4 | `verify_examples.py` | never run | **Seven** doctrine CICL examples no longer compiled, for the length of an advance. The standing check was `linkcheck`, which reads links and not YAML. |
| 5 | the seed projects | "expected red until mod 129" | Nothing references `test_projects/`. Their staleness was **real, present and invisible to pytest**, surfacing only on a walk. |
| 6 | `PRE_CUT_CHECKLIST` B.10 | would have failed the elastic walk | Its no-fan-out grep read gitignored `dist/`. A guaranteed false failure **against correct source**, on the file that gates both walks. |
| 7 | `PRE_CUT_CHECKLIST` D.11 | asserted a 200 | On a route this advance deleted. A walker following it records a failure against working code and stops the cut. |
| 8 | `PRE_CUT_CHECKLIST` B.12 | green, and still does | Titled "reversible" while citing the section that requires **forward-only**. The grep passes either way, so it reports green while misinstructing. |
| 9 | outcome-eval cases (×2) | would fail a **correct** answer | Their delta drivers were the fan-out and the three-segment path — the doctrine this advance deleted. |
| 10 | mod 131's anchor checker | 2 dangling anchors | Stripped `_` as markdown emphasis. Nearly "fixed" two correct links. |
| 11 | mod 132's first citation arm | 98 findings | On a clean tree. The dominant citation form is inside a markdown link, which check 1 already resolved. |
| 12 | `docex_process.md` | "17 deselected instead of 18" | 21. In the one section whose entire subject is plausible-but-wrong counts. |
| 13 | "nine of eighteen excerpts stale" | quoted by me as evidence twice | Doesn't reconcile with its own table; 15 of 18, and only **one** caused by this advance. A static ordinal about a drifting artifact. |
| 14 | the trigger eval | *"precision 1.00, no poaching"* | The harness ran the model **inside this repo**, so it could `grep doctrine/` instead of loading a skill. The confound **systematically converted precision failures into recall failures** — the one direction that makes a trigger surface look healthier than it is. |
| 15–17 | three checks of mine | web demux down; region unset; observability backend dead | All three my own error: I grepped `haproxy` for a container named `web_demux`, read a region IMDS supplies, and ate a URL scheme with `sed`. |
| 18 | my A.2.1 check | `tag_at_head=NO` | `git rev-parse` prints the ref name to stdout on failure, so my `||` fallback concatenated two lines. |
| 19 | four seed versions with no changelog entry | four | Sixteen — 36% of all tagged versions. The eyeball count read only each file's recent tail. |
| 20 | `git blame` | credits stale content to 2026-08-10 | Mod 131 touched two lines without fixing the stale token *on* them. **An advance cannot use blame to bound its own responsibility.** |
| 21 | the same trigger eval, again | a recall failure | A query that **timed out** was scored as ∅ — indistinguishable from a skill declining to fire. So the same command on the same tree yields different "findings" depending on what else the machine is doing. The only **load-dependent** defect of the twenty-one, and the only non-deterministic one. |

Two of those defects were **committed by me into the rule of record**, and both were
caught by a corporal checking the claim instead of the citation:

- Rule 33 said that on `ec2_traefik` the compiler "still emits a target group… so the
  value is inert." It emits none. I had built the clause on `render_target_group`'s
  docstring — which described a cleanup mod 070 had already performed. **Two
  docstrings in one file contradicted each other and I cited the stale one.**
- I told mod 134 that `PRE_CUT_CHECKLIST` needed a target-group box added on that
  same false premise, and gave three mods a `pytest` invocation that cannot import
  `tests.conftest` and reports one deselect short while collecting nothing.

## What the corporals refused

Every one of these was a subordinate declining an instruction and being right.

1. **Mod 126** refused to delete the self-`GET /health` contract assertion. The
   committed doctrine asks for it twice in narrowed form — including in the
   enumerated list of `check`'s own duties. It reached that by applying the test I
   had given it for a *different* gate and getting the opposite answer.
2. **Mod 127** refused "the elastic probe reaches the container def via the
   `container_definition` merge target." `transfer_tables.md` says `defaults:` cannot
   route to a non-default target. Its evidence: `launch_type` and `network_mode` sit
   in every core role's elastic defaults and are **read by nothing**.
3. **Mod 129** refused my nominated RPC boundary (`getJobStatus`) as a contrivance —
   one codebase, one composition root, one `jobs` table — and proposed `POST /drain`,
   whose cross-process necessity is *doctrinal*. The seeds gained the canonical
   consumer-side gateway they previously lacked.
4. **Mod 134** refused two Tier-1 items and a table row: the `ec2_traefik` target
   group (above), `${project_version}` as a substitution variable it is not, and a
   checklist version operand whose repair would have asserted the next cut's SemVer
   level.
5. **Mod 135** reverted its own `contracts` edit once the corrected harness showed
   the hole was mostly artifact — and that `contracts` is the *aggressor* in that
   pair, so widening it would have worsened the real defect while fixing a phantom.

Four completion signals I specified did not hold mechanically: "expected red" for
the seeds; ordering-vs-reachability in mod 126; `docex check` green for mod 129
(`check` refuses `main`); and `docex check` green for mod 130 (same reason, plus
A.2.1 requires the seeds *stay* on `main`).

## Doctrine edits

Fourteen, under the operator's grant. Four repaired the operator's own step-3/4
edits; **six were defects a corporal found**; two corrected errors I had introduced.
Highest-value: `contracts.md`'s format table could not render (a GFM table cannot
interrupt a paragraph) — the one table this advance was about, in a file the
`contracts` skill marks *read now*. And `inception.md` claimed an empty `health.sh`
"exits 0 and so reports healthy": measured, it is **exit 255, exec format error** —
the probe is exec-form, so a zero-byte file has no shebang. The same holds for
`test.sh` and `migrate.sh`; only `build.sh` survives emptiness.

## Process changes earned rather than proposed

- The default suite is **`pytest tests`**, not `tests/unit`; `-m integration` runs
  **alone**; always `python -m pytest`, always from `docex/`.
- `RELEASING.md` gained a row for **`cohere`'s executor tooling** — a change to
  `linkcheck.py` or `verify_examples.py` fired *neither* existing gate, so the
  verifiers were the only thing in the repo ungated. Its doctrine row now requires
  `verify_examples.py` green, and its skills row names `run_suite.py` as the
  trustworthy runner and `run_eval.py` as still confounded.
- A verifier **may decline to answer but may not decline quietly** — now `linkcheck`'s
  own `Declined` block, `preinfra`'s failure/declination split, and the honest limit
  that unbounded citations are *counted, not enumerated*.
- **An instrument that cannot say "I failed to measure" will say something else, and
  that something else gets acted on.** All three `run_suite.py` defects shared this
  shape: each reported a condition *unrelated to the measurement* as the measurement,
  and each failed in the direction that looks like an actionable finding rather than a
  broken tool. `TIMEOUT` is now a sentinel excluded from the vote, unscored queries are
  counted, and a run with any reports `n/a` rather than a fabricated accuracy.
- **Run a new check against the instance that motivated it, and confirm it fires.**
  Mod 132's citation arm was demonstrated against a reconstruction it wrote in
  bounded form; `doctrine_excerpts/` is unbounded in 14 of 16 lines, so the arm is
  near-blind in the directory whose defect motivated building it.

## Booked to advance 007

Nine briefs: the `doctrine_excerpts` overhaul (15 of 18 entries, overwhelmingly
pre-existing, `docex why web_network` fails outright); `run_eval.py`'s confound;
`project-upgrade`'s recall figure (**re-measure first** — it was measured on the
confounded harness and may be the same artifact inverted); fixture base-image
digests; the misfiled compile tests; contract spec-version gating; `merge`'s
unenforced changelog obligation; `traefik_acme_email` plus the project-name
normalization (four template sites, two omitting `| lower`, nothing validating the
name to lowercase); rule 32's unused-target port; `_env_subdomain`'s fourth copy;
and the changelog's frozen-section link paths.

## State at handoff

- Eleven mods complete. **Unit 1199, integration 21** (measured, each invoked alone),
  `linkcheck` and `verify_examples` green.
- `docex:1.7.0` rebuilt at HEAD — it was 9 hours stale and predated three mods.
- Both seeds: `main`, clean, tags at HEAD, **recompile verified idempotent**
  (fixed 0.0.20 `cb16e12`, elastic 0.0.24 `60c22b0`).
- Walk **A + B green on both foundations**, executed rather than read. The elastic
  dev A-records were created (temporary; section E deletes them).
- `health.sh` exercised inside the real image: unknown service → 2, no args → 2,
  absent tick → 1, fresh tick → 0, 60s-stale tick → 1. Worker and clock wedged from
  the host and observed going `unhealthy` at `failing_streak=3` in Docker's own
  health log.

**Outstanding:** walk C (fixed), walk D (elastic), section E, then the cut per
`RELEASING.md` — the operator's.

## The lesson worth keeping

Advance 005's was *a verification step's pass is worthless until the step has been
observed failing.* This advance earns the next clause: **and an instrument's report
is worthless until the instrument has been run against a case whose answer you
already know.** Every one of the twenty defects above passed a plausibility check.
None survived being *executed* against a known case — which is why the seed's tick
file was wedged from the host, the probe census was run over all eight artifacts, the
empty shim was actually executed in a container, and the trigger eval was re-run from
an empty directory.
