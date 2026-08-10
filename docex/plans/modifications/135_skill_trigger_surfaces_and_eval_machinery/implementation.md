# Mod 135 — Implementation Steps

All paths are absolute from the repo root `/home/ubuntu/.claude/jean_baudrillard`. Nothing under
`docex/src/` is touched by this mod. **Do not edit any file under `doctrine/`** — doctrine prose
is out of scope; if you believe a doctrine file is wrong, stop and report it rather than fixing it.

There are six steps. Steps 1-2 are the trigger descriptions, 3-4 the outcome-eval cases, 5 the
query set, 6 the dangling reference. They are independent; do them in order anyway so the
verifiers at the end run against a complete change.

---

## Step 1 — `infra-compile` description

File: `/home/ubuntu/.claude/jean_baudrillard/skills/infra-compile/SKILL.md`

In the YAML frontmatter, replace this fragment of the `description:` value:

```
adding a service/role/engine, declaring the secrets or config a service requires (its
`secrets:` / `config:` blocks), or extending docex with a project-local transfer table
```

with:

```
adding a service/role/engine, declaring what a core service exposes or requires in its
`surfaces:` / `uses:` / `secrets:` / `config:` blocks, or extending docex with a project-local
transfer table
```

The description is a **single line** in the frontmatter — do not introduce line breaks. The
resulting full value must read exactly:

> Doctrine for authoring a project's infra.yml and the transfer tables that compile it into per-foundation infrastructure. Use this whenever you are writing or changing infra.yml, adding a service/role/engine, declaring what a core service exposes or requires in its `surfaces:` / `uses:` / `secrets:` / `config:` blocks, or extending docex with a project-local transfer table for an engine it doesn't ship — and whenever reasoning about how CICL compiles to docker-compose or OpenTofu, even if you never name CICL or transfer tables.

**Change nothing else in this file.** The body's `Thread` section already carries the
surfaces-authoring role; this step only makes the trigger interface match it.

---

## Step 2 — `contracts` description

File: `/home/ubuntu/.claude/jean_baudrillard/skills/contracts/SKILL.md`

In the YAML frontmatter, replace this fragment of the `description:` value:

```
or wiring health checks, even if the words "contract" or "surface" are never used.
```

with:

```
or wiring health checks — including deciding whether a given core service needs an HTTP health endpoint at all, and how a service that owns a loop proves it is still alive — even if the words "contract" or "surface" are never used.
```

Again a single line. The resulting full value must read exactly:

> Doctrine for defining core-service surfaces and their contracts — which API styles share a surface, the OpenAPI/AsyncAPI format each resolves to, and the health probe every core service owes. Use this whenever you are declaring or changing a service's surfaces, writing a contract, adding a provider/consumer relationship, or wiring health checks — including deciding whether a given core service needs an HTTP health endpoint at all, and how a service that owns a loop proves it is still alive — even if the words "contract" or "surface" are never used.

**Do not add the phrase `web`-network, `health.sh`, or the 10s/30s thresholds to this
description.** The first is the tell whose presence masks the hole this edit closes; the other
two are body content. This is deliberate and was approved as drafted.

**Change nothing else in this file.**

---

## Step 3 — `outcome/contracts/evals.json`

File: `/home/ubuntu/.claude/jean_baudrillard/skill_iter/eval/outcome/contracts/evals.json`

Replace the **entire file** with the content below. Two cases: case 1 repairs the existing web
contract case (its two old delta drivers pointed at the `/health/worker` fan-out and the
three-segment contract path, both of which advance 006 deleted — run as written a *correct*
answer failed both); case 2 is new and covers the worker's liveness story.

```json
{
  "skill_name": "contracts",
  "evals": [
    {
      "id": 1,
      "prompt": "I'm building a project that follows a strict in-house engineering doctrine. The codebase is called `api` and it declares two core services: `web` — an HTTP REST API that accepts `POST /pings`, is publicly routed, and is the project's public entry point — and `worker` — a background service that consumes jobs off a task queue. `web` enqueues the jobs that `worker` processes, and `web` also reads and writes Postgres. I need the provider contract for `web`'s REST boundary. Produce the complete contract file contents and tell me the exact repo path it should live at. Include everything the doctrine requires to appear in that document — I've been told a release fails its check step if anything mandatory is missing. Keep it focused.",
      "expected_output": "An OpenAPI document for `api.web`'s `rest` surface at infra/contracts/api.web.rest.openapi.yml, defining POST /pings and GET /health, where /health returns the version in the shape {\"version\": \"x.x.x\"} — and defining NO endpoint that reports on the worker, the queue, or Postgres.",
      "expectations": [
        "DELTA DRIVER (doctrine-specific, not inferable): the contract defines a GET /health endpoint whose response body carries the service version in the mandated shape {\"version\": \"x.x.x\"}. The gate run's baseline omitted GET /health from the contract on principle — treating health as an operational concern outside the described boundary — so both halves count: that it appears at all, and that its body shape is the mandated one.",
        "DELTA DRIVER (doctrine-specific, not inferable): the contract defines NO endpoint that reports on any dependency — no /health/worker, no /health/db, no readiness or deep-health endpoint aggregating downstream status. No service reports on another; there is no proxying and no fan-out. A consumer's health says nothing about its dependencies and it is not asked to. Grade this as FAILED if any such endpoint appears, however named.",
        "DELTA DRIVER (doctrine-specific, not inferable): states the condition under which GET /health belongs in a contract at all — it appears here because this core service is publicly routed AND declares an `openapi` surface. A core service that declares no surface, or declares only non-openapi surfaces, still serves GET /health but carries no contract obligation for it. The field covers both cases; the contract covers only the described boundary.",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): the contract is an OpenAPI document, not AsyncAPI — the boundary's api_styles are REST-shaped.",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): the path is infra/contracts/api.web.rest.openapi.yml — the five-segment ${codebase}.${service}.${surface}.${format}.${ext} form. Resident-stratum-supplied (infrastructure.md), so a correct baseline reaches it too.",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): POST /pings is defined with a request and response schema."
      ]
    },
    {
      "id": 2,
      "prompt": "Same project, same in-house doctrine. Now focus on the `worker` core service of the `api` codebase: a long-running Python process that pulls jobs off a task queue in a receive loop and processes them, some of which take a couple of minutes. Nothing routes to it — it isn't publicly reachable and no other service calls it over HTTP. `web` declares that it uses `worker`. Two things. First: does `worker` need to serve an HTTP health endpoint of its own? Second: whatever the answer to that, tell me concretely how anything outside the process is supposed to find out that `worker` has stopped doing its job — the failure I'm worried about is a wedged receive loop inside a process that is still very much running. Give me the actual mechanism, the file it lives in, how it gets invoked, and any numbers the doctrine fixes rather than leaving to me. Also tell me what `worker` owes by way of a contract file, if anything.",
      "expected_output": "worker serves no HTTP health endpoint and declares no health_check_path. Liveness is a command probe: health.sh at the container root, invoked as ./health.sh worker, exit 0 healthy / non-zero not. The receive loop records a monotonic tick each iteration where a separate process can observe it (a touched file); health.sh fails when the tick is stale. The loop ticks at least every 10 seconds even when idle and the staleness threshold is 30 seconds — both doctrine-fixed, no per-project knob. The tick belongs to the receive loop, not to the unit of work, so a two-minute job does not threaten it. Because web uses worker, worker must declare a surface; a queue boundary is api_styles: [events] → asyncapi → infra/contracts/api.worker.events.asyncapi.yml.",
      "expectations": [
        "DELTA DRIVER (doctrine-specific, not inferable): answers the first question NO — `worker` serves no HTTP health endpoint and declares no health_check_path. A core service that nothing routes to has no load balancer in front of it and needs no HTTP surface of any kind; a queue consumer built under this doctrine listens on nothing. Grade FAILED if the answer has the worker expose an HTTP health route, or hedges toward 'expose one anyway for consistency'. This is the expectation the unloaded model gets confidently wrong.",
        "DELTA DRIVER (doctrine-specific, not inferable): both thresholds are given as doctrine-fixed with no per-project knob — the loop ticks at least every 10 seconds even when idle (its receive must be bounded, not indefinite) and the staleness threshold is 30 seconds. Grade FAILED on any other numbers, on numbers presented as the answerer's own judgment or a tunable, or on thresholds omitted. The gate run's baseline invented 60s and called it 'my engineering judgment'.",
        "DELTA DRIVER (doctrine-specific, not inferable): explicitly rejects the two naive probes and says why — checking that the process exists proves nothing, because a deadlocked process exists; and a separate liveness thread proves LESS than nothing, because it will report health forever while no work is consumed, converting a loud failure into a silent one. Liveness must be sourced from the loop itself.",
        "DELTA DRIVER (doctrine-specific, not inferable): the tick belongs to the receive loop rather than to the unit of work, so the stated two-minute jobs do not threaten the 10s cadence. This is the reasoning that makes the fixed thresholds survive contact with slow work, and its absence is what pushes an unaided answer toward inventing a larger window.",
        "DELTA DRIVER (doctrine-specific, not inferable): nothing asserts `worker`'s health over the network. Its state is read from the orchestrator, staging tests do not assert liveness and cannot reach a non-web core service at all, and no other service's /health reports on it.",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): the probe is a health.sh at the container root (/service/health.sh), invoked per core service as ./health.sh worker, whose entire contract is its exit code — 0 working, non-zero not. Resident-stratum-supplied (infrastructure.md).",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): the mechanism is a monotonic tick recorded by the loop each iteration somewhere observable from a separate process — a touched file being the obvious choice. Resident-stratum-supplied (internal_dependency_rules.md names the tick and points at healthchecks.md for thresholds), so the tick idea alone shows ~zero delta; only the thresholds above do.",
        "CONFIRMATORY (inferable, expect ~zero with/without-skill delta): because `web` uses `worker`, `worker` must declare at least one surface, and a queue boundary resolves to asyncapi — infra/contracts/api.worker.events.asyncapi.yml."
      ]
    }
  ]
}
```

---

## Step 4 — `outcome/testing/evals.json`

File: `/home/ubuntu/.claude/jean_baudrillard/skill_iter/eval/outcome/testing/evals.json`

One expectation is reversed by advance 006. **Replace only the final array element** — the
line beginning `"CONFIRMATORY (inferable, expect ~zero with/without-skill delta): staging tests
include liveness/health-check probes` — with the **two** entries below. Leave the `prompt`,
`expected_output`, and every other expectation untouched; they were re-verified against current
doctrine and still hold.

Old (delete):

```
"CONFIRMATORY (inferable, expect ~zero with/without-skill delta): staging tests include liveness/health-check probes and at least one end-to-end smoke test spanning web->worker to confirm services reach each other and secrets/env are wired"
```

New (two entries, in this order — mind the comma between them):

```
"DELTA DRIVER (doctrine-specific, not inferable): staging tests do NOT assert liveness — no per-service health or heartbeat probe belongs in the staging suite. `docex stagetest` reads every core service's health and version from the orchestrator BEFORE the tester image is built and fails there if any is unhealthy or on the wrong version; nothing downstream repeats it. Staging tests assert only what can be seen from outside: that TLS terminates, that DNS resolves, that the reverse proxy routes. Grade FAILED if the answer puts a per-service health check into the staging suite — which is what an unaided answer does, since a liveness probe is the conventional first staging test.",
"CONFIRMATORY (inferable, expect ~zero with/without-skill delta): at least one end-to-end smoke test drives the public edge and observes the effect of the web->worker path, confirming the services reach each other and that secrets/env are wired — driven through the real edge, because a stage test cannot reach a non-web core service directly at all"
```

Note the deliberate inversion of grading polarity: the old entry expected an answer to *include*
staging liveness probes and would have failed a doctrine-correct answer that omitted them.

---

## Step 5 — `queries.json`

File: `/home/ubuntu/.claude/jean_baudrillard/skill_iter/eval/queries.json`

### 5a. Delete the `competing_skills` key

Remove the entire `"competing_skills": [...]` array (13 names) from the top-level object.
`run_suite.py` auto-discovers all 19 installed skills from `<plugin_dir>/skills/*/SKILL.md`
when the key is absent, which is what makes the six previously-omitted skills scoreable and
poaching involving them detectable.

Leave `purpose` and `queries` in place. Verify afterwards that the file still parses:
`python3 -c "import json;d=json.load(open('skill_iter/eval/queries.json'));print(len(d['queries']), 'competing_skills' in d)"` → must print `73 False`.

### 5b. Append 17 queries

Append all 17 objects below to the end of the `queries` array, preserving the existing 56
entries **exactly as they are** — including query `[10]`, whose `note` marks its use of the
retired `depends_on` vocabulary as deliberate. Do not "correct" any existing query.

```json
{
  "query": "where in infra.yml does the surfaces block go for a core service, and what actually changes in the compiled output once i declare one?",
  "expect": "infra-compile",
  "note": "The surfaces-AUTHORING half: block placement + compile effect. Boundary with contracts, which owns format choice, splitting, and contract contents. Added mod 135: advance 006 gave infra-compile this role in its body and never touched its description, and this query fired NO skill at all (0/5) before that description was fixed."
},
{
  "query": "i'm adding a uses edge from my frontend core service to the api in infra.yml — what's the syntax, and what does the api side have to declare for the compile to accept it?",
  "expect": "infra-compile",
  "note": "Authoring the `uses:` block. Boundary with contracts, whose description claims 'adding a provider/consumer relationship' — the tell here is infra.yml syntax and compile acceptance, not the contract between them. Added mod 135 as the condition on naming `uses:` in infra-compile's description: unmeasured vocabulary in a durable artifact is a guess."
},
{
  "query": "i'm adding health_check_path to a core service in infra.yml — where in the service block does it belong, and is it validated against anything else i declare there?",
  "expect": "infra-compile",
  "note": "Deliberate pair with the contracts-side health_check_path query below: field PLACEMENT and validation (cicl.md rule 33) is infra-compile; whether a service NEEDS the field and what consumes it is contracts. Splitting the seam this way is what let both label cleanly."
},
{
  "query": "my queue consumer doesn't listen on any port and someone told me every service has to expose a /health route — is that actually true, and if it isn't, how does anything find out the consumer has stopped working?",
  "expect": "contracts",
  "note": "THE DIAGNOSTIC YES/NO FORM. Added mod 135: authoring-shaped health queries fired 5/5 and 3/3 while this form fired 0/5, and the unloaded answer ('yes, expose /health') is doctrine-wrong and confidently delivered. Deliberately carries no 'web-network' tell — the canonical set's other health query passes only because it has one, which masked this hole."
},
{
  "query": "my background worker has no port and nothing routes to it — do i still have to give it a health_check_path, and what actually reads that field?",
  "expect": "contracts",
  "note": "The field-shaped twin of the query above, and the contracts half of the health_check_path seam. Answered by healthchecks.md: a non-routed core service declares none, and the field has exactly one consumer (elastic with reverse_proxy: alb). Deliberate near-duplicate of the previous query on subject but not on vocabulary — phrasing robustness on this exact boundary is the defect class mod 135 exists to fix, so the pair is the measurement, not redundancy."
},
{
  "query": "my api service serves a rest api and also fires webhook callbacks at customers — is that one surface or two, and how many contract files do i end up with?",
  "expect": "contracts",
  "note": "api_styles combining into one surface: styles sharing a format share a surface. Advance 006 vocabulary, previously unrepresented."
},
{
  "query": "i want a public api and an internal admin api out of the same codebase — should that be one surface with two styles, two surfaces on one core service, or two core services?",
  "expect": "contracts",
  "note": "The split-decision table (cicl.md § Surfaces, reached via contracts' Specific Information). Boundary with infra-compile, which authors core services — the tell is that the question is which shape is correct, not where to type it."
},
{
  "query": "writing health.sh for a stream processor — the process stays up even when its loop wedges, so what should the probe actually look at, and how stale is too stale?",
  "expect": "contracts",
  "note": "health.sh authoring for a loop-owning service: the tick mechanism and the doctrine-fixed 10s/30s thresholds. `health.sh` appeared in no query before mod 135."
},
{
  "query": "i'm adding an MCP endpoint to the api codebase — what contract file does that need, and which format is it written in?",
  "expect": "contracts",
  "note": "rpc → asyncapi, the non-obvious row of the api_styles table (MCP reads as HTTP-ish but resolves to asyncapi). Mirrors cicl.md's worked api.mcp example."
},
{
  "query": "i'm writing our staging suite — should it hit each service's health endpoint to confirm everything is up, or is that checked somewhere else?",
  "expect": "testing",
  "note": "Diagnostic yes/no form applied to the staging tier. Advance 006 reversed this: staging tests do NOT assert liveness; docex reads health from the orchestrator before the tester is built. The same reversal made outcome/testing/evals.json stale, so it is now measured from both the trigger and outcome ends."
},
{
  "query": "where do contract tests actually run — inside the service's own test container in the test env, or against the deployed stage environment?",
  "expect": "testing",
  "note": "Tier placement: contract tests are a codebase-level concern run in the test env via the codebase's own test.sh, not part of staging. testing had only 2 queries before mod 135."
},
{
  "query": "i want to write a new skill for our deploy runbook and then actually measure whether its description fires on the right prompts and not on its neighbours' — how do i do both?",
  "expect": "skill-iteration",
  "note": "Authoring + trigger measurement, the two ends of one activity. First query for this skill: it was omitted from the pinned competing_skills list, so the suite could not score it at all before mod 135."
},
{
  "query": "go over the doctrine corpus and find the internal contradictions, the broken links, and the sections that disagree with each other",
  "expect": "cohere",
  "note": "Static soundness of the DOCTRINE corpus. Boundary with project-cohere (a project's docs vs its code) and skill-iteration (behavioral measurement). Newly scoreable in mod 135."
},
{
  "query": "this project's core planning docs have drifted from what the code actually does — go through them and reconcile the two",
  "expect": "project-cohere",
  "note": "A PROJECT's docs against its code, in place. Boundary with cohere, which does the doctrine corpus. Newly scoreable in mod 135."
},
{
  "query": "the dev environment is up — open the app in a real browser, click through the signup flow and screenshot what the dashboard looks like afterwards",
  "expect": "browser-investigate",
  "note": "Manual browser exercise of a running dev stack. Boundary with testing, which owns automated suites — the tell is looking at it by hand. Newly scoreable in mod 135."
},
{
  "query": "i'm about to fan this work out across several subagents — how do i decide which rank owns which piece, and what should an agent do when it hits a decision above its authority?",
  "expect": "chain-of-command",
  "note": "Rank placement + decision-ripple escalation. Newly scoreable in mod 135."
},
{
  "query": "summarize what happened across this agent session including every subagent run, and tell me what the whole thing cost in tokens",
  "expect": "transcript-summary",
  "note": "Session/subagent transcript accounting. Newly scoreable in mod 135."
}
```

**Do not reword any of these.** They are durable artifacts and the wording carries the
boundaries described in each `note`. In particular, none of the health queries may gain a
`web`-network tell.

---

## Step 6 — the dangling `Isolation` reference

File: `/home/ubuntu/.claude/jean_baudrillard/skills/skill-iteration/references/evaluation.md`

### 6a. Make the pointer resolve

In the `### The run pattern` paragraph, replace:

```
(spawned from a context restarted with the on-disk strata active, per Isolation)
```

with:

```
(spawned from a context restarted with the on-disk strata active, per [Isolation](#isolation))
```

### 6b. Add the section it points at

Insert a new `### Isolation` subsection **immediately after** the numbered 1/2/3 run-pattern
list and **before** the line beginning `Case files live at`. Content:

```markdown
### Isolation

The parenthetical above names a real constraint, and it is a bounded one. State the bound
rather than assume it away.

**What cannot be isolated.** A subagent's system prompt loads the Resident stratum. The
baseline arm cannot un-read it — "work only from general knowledge, do not read doctrine files"
withholds only what is on disk waiting to be opened. There is no arm with zero doctrine, and
none can be constructed without running the eval outside this harness entirely.

**What the delta therefore measures.** *Navigation into the conditional stratum* — did the
thread route to the right files — and nothing beyond that. [The System](#the-system) makes this
point about router+thread skills generally; here it becomes an operational ceiling on what a
case may claim.

**The consequence for authoring cases.** Before promoting an expectation to a **delta driver**,
grep it against the files carrying `stratum: resident`. A driver the Resident stratum already
supplies measures leakage rather than value: both arms pass it, the delta reads ≈0, and the
skill looks worthless at precisely the expectation that was mislabeled. Demote such entries to
confirmatory. Worked example, from the `contracts` cases: the Resident stratum supplies surfaces
themselves, the five-segment contract path, the style→format mapping, `health.sh`'s existence,
*and* the loop-liveness tick — while the doctrine-fixed 10s/30s thresholds, `web`-network-only
HTTP health, the `{version}` body shape, and the no-fan-out rule appear nowhere in it. Only the
second group can drive a delta.

**Both arms read the working tree.** Restart the context after any doctrine edit before running
them. The Resident stratum is loaded at session start, so an arm spawned from a stale session
measures the previous revision of the very file under test.
```

---

## Verification

Run all four. Each is its **own** invocation.

| # | From | Command | Expected |
| - | ---- | ------- | -------- |
| 1 | `/home/ubuntu/.claude/jean_baudrillard/docex` | `./.venv/bin/python -m pytest tests -q` | `1199 passed, 21 deselected` |
| 2 | `/home/ubuntu/.claude/jean_baudrillard/docex` | `./.venv/bin/python -m pytest tests -q -m integration` | `21 passed` |
| 3 | repo root | `python3 skills/cohere/executor/linkcheck.py` | green |
| 4 | repo root | `python3 skills/cohere/executor/verify_examples.py` | green |

Never bare `pytest`, never both `-m` flags in one run, never from the repo root for 1 and 2.

**Read 1 and 2 correctly: the counts are expected-unchanged, not a pass.** No file under
`docex/src/` is in this mod's scope, so movement in `1199` or `21` is a **signal that something
went wrong**, not a green light. Report the exact numbers either way.

Verifier 3 matters most here: step 6b adds two in-file anchors (`#isolation`, `#the-system`) and
step 6a converts prose into a link, so `linkcheck.py` is the check that the new pointers
actually resolve. If it reports a dangling anchor, fix the anchor — do not delete the link,
since a pointer to nothing is the exact defect this step exists to remove.

Also confirm both edited JSON files parse:

```
python3 -c "import json,pathlib; [json.loads(pathlib.Path(p).read_text()) for p in ['skill_iter/eval/queries.json','skill_iter/eval/outcome/contracts/evals.json','skill_iter/eval/outcome/testing/evals.json']]; print('json ok')"
```

**Do not run the trigger eval** (`skill_iter/eval/run_suite.py`). It is long-running and its
numbers are the mod owner's to measure and interpret — a precision trade is a design call, not
an execution step.

## Report back

- the four verifier results, with exact numbers for 1 and 2;
- the JSON parse check;
- the final `description:` line of each of the two edited SKILL.md files, quoted, so the trigger
  surfaces can be diffed by eye;
- anything you found wrong in doctrine or in these steps that you did **not** change.
