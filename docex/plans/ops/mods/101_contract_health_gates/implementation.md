# Mod 101 — Implementation steps

Design record: [`overview.md`](./overview.md). **Rule of record:
`doctrine/infrastructure/contracts.md` § Contracts and § Health Checks** — implement
against that file, not against `plans/advances/004_next/service_processes_refactor.md`,
wherever the two differ.

All paths are relative to `/home/ubuntu/.claude/jean_baudrillard/docex` unless prefixed
`doctrine/`, which is relative to `/home/ubuntu/.claude/jean_baudrillard`.

## Ground rules

- **The tree is dirty with work that is not yours.** Ten staged `campaigns/` →
  `advances/` renames, plus modified `tests/unit/test_pipeline_projinfra.py`,
  `tests/unit/test_hcl_emitter.py`, and an untracked `docex/uv.lock`. **Do not commit,
  revert, stage, or otherwise disturb any of it.** Do not run `git add -A` or
  `git commit -a`. If you commit at all, use an explicit pathspec.
- **Use `python3 -m pytest`, never `uv run pytest`** (the latter regenerates a stray
  lockfile).
- Baseline to beat: `python3 -m pytest tests/unit` = **926 passed**;
  `python3 -m pytest tests/` = **990 passed / 17 deselected**. Both numbers must go up,
  never down. **If a pre-existing test fails, stop and report — do not delete or weaken
  a test to get green.**
- Branch is `main` and that is correct for this repo (`plans/core/docex_process.md`
  § Git). Do not create a branch.

---

## Step 1 — `cicl.md` rule 25 gains a scheduler clause

**File:** `doctrine/infrastructure/cicl.md`, line 589 (the rule-25 list entry).

This is one of exactly three authorized doctrine edits. **Change nothing else in this
file.**

Replace:

```
25. `consumes` names only core process types, fully qualified as `<service>.<process>`. A bare core service name is an error, and a process type may not consume itself.
```

with:

```
25. `consumes` names only core process types, fully qualified as `<service>.<process>`. A bare core service name is an error, and a process type may not consume itself. A `scheduler` process type may not be a `consumes` target: cron invokes it and nobody else does, so it exposes no boundary to consume and is exempt from the health fan-out that `consumes` drives.
```

---

## Step 2 — `contracts.md § Fan-out`: two clauses

**File:** `doctrine/infrastructure/contracts.md`, § Health Checks → #### Fan-out
(currently lines 62-69). The other two authorized edits. **Change nothing else in this
file** — in particular leave § Self health, § Declared by fields, § Standards, and the
provider-set sentence at line 21 exactly as they are.

Replace this paragraph:

```
The fan-out set is the **union of `consumes` and [`depends_on`](./cicl.md#depends-on-relationships)**, not `depends_on` alone. The union matters: a web edge does not `depends_on` its worker (it needs the *broker* up, not the consumer), so keying off `depends_on` would silently stop requiring `/health/api/worker` — and a dead consumer is invisible from outside, because requests keep returning 200 while work piles up behind them.
```

with these two paragraphs:

```
The fan-out set is **`consumes`**, restricted to targets not themselves on the `web` network. A target on `web` is publicly reachable and answers its own `/health` at its own hostname, so there is nothing for a consumer to proxy — that is what "expose the health of those that aren't" means above.

`consumes` is the source rather than [`depends_on`](./cicl.md#depends-on-relationships) because a web edge does not `depends_on` its worker: it needs the *broker* up, not the consumer. Keying off `depends_on` would silently stop requiring `/health/api/worker`, and a dead consumer is invisible from outside because requests keep returning 200 while work piles up behind them. (This rule was once written as the *union* of the two, from a time when `depends_on` could still name a core service. [Rule 24](./cicl.md#validation-rules) has since restricted `depends_on` to backing services, which have no `<service>/<process>` form at all, so the union's second arm can no longer contribute a target. It is stated as `consumes` alone so nobody restores an arm that cannot fire.)
```

Also amend the § Fan-out opening sentence so it does not contradict the carve-out.
Replace:

```
Each `web`-network process type must additionally expose the health of everything it talks to, at:
```

with:

```
Each `web`-network process type must additionally expose the health of everything it talks to that is not itself publicly reachable, at:
```

---

## Step 3 — `ProcessType.consumes_refs()` on the model

**File:** `src/docex/cicl/model.py`, class `ProcessType`.

Add a method after `_validate_command_nonempty`. It moves
`validate._parsed_consumes`'s body onto the model so there is one parser, per that
function's own docstring ("a second parser would be a second place for that rule to
drift"). `ProcessRef` is already defined above in this file.

```python
    def consumes_refs(self) -> set[str]:
        """This process type's ``consumes:`` targets, normalized to dotted form.

        Entries that do not parse are dropped rather than passed through: rule 25
        reports each one once, and a malformed entry must not ALSO surface
        downstream — as a mystifying rule-7 miss, or as a missing contract for a
        target the author plainly named. Both the validator (rule 7) and
        ``check.py``'s contract / health gates read through here, so the
        dots-for-reference parse lives in exactly one place.
        """
        out: set[str] = set()
        for raw in (self.consumes or []):
            try:
                out.add(ProcessRef.parse(raw).dotted)
            except ValueError:
                continue
        return out
```

## Step 4 — retire `validate._parsed_consumes`

**File:** `src/docex/cicl/validate.py`.

1. Delete the `_parsed_consumes` function (currently ~lines 589-602, immediately under
   the `# Rule 25:` banner comment). Keep the banner comment.
2. At its one call site (currently line 486, inside the `scan(...)` call in the
   core-process loop), replace `_parsed_consumes(proc)` with `proc.consumes_refs()`.
3. Confirm no other references remain: `grep -rn "_parsed_consumes" src/ tests/` must
   come back empty.

## Step 5 — rule 25's scheduler check in the validator

**File:** `src/docex/cicl/validate.py`, function `_validate_consumes`.

Add the check **after** the `ref.process not in target.processes` block — the target
must be known to exist before its role can be judged, and an author who typo'd the
process name should get the unresolved message, not this one. The existing block ends
with an `issues.append(...)` and no `continue` (it is the last statement of the loop
body); add a `continue` to it so the new check does not also fire on an unresolved ref,
then append:

```python
            if target.processes[ref.process].role == "scheduler":
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_scheduler",
                    message=(
                        f"process type {label!r} lists {raw!r} in `consumes:`, but "
                        f"{raw!r} is a `scheduler` process type. Cron invokes a "
                        f"scheduler and nobody else does, so it exposes no boundary "
                        f"to consume — and it is exempt from the health fan-out that "
                        f"`consumes` drives. See cicl.md rule 25 and "
                        f"contracts.md § Health Checks."
                    ),
                    where=where,
                ))
                continue
```

Verify the surrounding loop's control flow after editing: every branch that reports an
issue for a given `raw` must `continue`, so one entry never produces two issues.

## Step 6 — `check.py`: contract format from role

**File:** `src/docex/pipeline/check.py`.

Delete `_infer_contract_format` (lines 109-136) **and its section banner's stale
title**. Replace the whole `# Contract-format inference.` section with:

```python
# ---------------------------------------------------------------------------
# Contract format.
# ---------------------------------------------------------------------------

# contracts.md § Standards: the format follows from the PROVIDER'S ROLE, not from
# the shape of the graph — the role is what fixes the communication mechanism, so
# it is the honest source. `scheduler` is absent because a scheduler is never a
# provider (see `_gate_contracts`).
_CONTRACT_FORMAT_BY_ROLE = {
    "web": "openapi",
    "worker": "asyncapi",
}
_FALLBACK_CONTRACT_FORMAT = "openapi"


def _contract_format_for_role(role: str) -> tuple[str, bool]:
    """``(format, role_recognized)`` for a provider process type.

    Mod 101 replaces a heuristic (`_infer_contract_format`) whose asyncapi branch
    was unreachable from the day it was written: its only call site passed a CORE
    service name, the function then looked that name up in `backing_services`, and
    `model.py` forbids the overlap — so it returned "openapi" every time it was
    ever called. That is why the async-contract path was never exercised.

    WHY a fallback rather than a raise: an unrecognized core role is already a
    transfer-table load error, and raising here would deny the operator every other
    gate's result — the aggregation pattern exists precisely to avoid that. The
    caller surfaces the fallback in the gate detail so it is never silent.
    """
    fmt = _CONTRACT_FORMAT_BY_ROLE.get(role)
    if fmt is None:
        return _FALLBACK_CONTRACT_FORMAT, False
    return fmt, True
```

Add to the imports at the top of the file:

```python
from docex.cicl.model import CICLDocument, ProcessRef, ProcessType  # noqa: F401
```

(the existing line imports `CICLDocument` only; keep the `noqa` comment).

## Step 7 — `check.py`: right-anchored filename parser

Add alongside `_contract_format_for_role`:

```python
def _parse_contract_filename(name: str) -> tuple[str, str, str] | None:
    """``"api.web.openapi.yml"`` → ``("api", "web", "openapi")``; else ``None``.

    RIGHT-anchored, per contracts.md's `${service}.${process}.${format}.yml`. The
    left-anchored `name.split(".", 1)[0]` this replaces yielded "api" — a valid
    `core_services` key purely because the codebase happens to be the first segment
    — and discarded the process entirely, so the health gate reasoned at codebase
    granularity and silently `continue`d on anything it could not match.

    Exactly three segments are required: `_SERVICE_NAME_RE` (model.py) admits no
    dots in a service or process name, so a canonical contract filename has three
    and nothing else is a name this gate authored.
    """
    stem = name
    for suffix in (".yml", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        return None
    parts = stem.split(".")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        return None
    return parts[-3], parts[-2], parts[-1]


def _resolve_process(
    infra: CICLDocument, dotted: str
) -> tuple[str, str, ProcessType] | None:
    """``"api.worker"`` → ``("api", "worker", <ProcessType>)`` if it names a real
    core process type, else ``None``.

    Returning ``None`` for an unresolvable reference is deliberate: rule 25 already
    reports it, and this gate must not double-report it as a missing contract or a
    missing probe endpoint.
    """
    try:
        ref = ProcessRef.parse(dotted)
    except ValueError:
        return None
    svc = infra.core_services.get(ref.service)
    if svc is None:
        return None
    proc = svc.processes.get(ref.process)
    if proc is None:
        return None
    return ref.service, ref.process, proc
```

## Step 8 — `check.py`: `_gate_contracts` provider criteria

Rewrite `_gate_contracts`'s docstring and body between the `if infra is None:` guard
and the `if missing:` reporting block. Delete the `dependants` dict entirely (it is
dead: its keys come from `depends_on`, which rule 24 restricts to backing services, so
`dependants.get(svc_name)` for a core name has always been empty — the old provider
test was already web-network-only in effect) and delete the `# Mod 101` marker comment
block at lines 318-331.

New docstring:

```python
    """Verify every required contract file is present.

    Per contracts.md, **the provider set is (`consumes` targets) ∪ (`web`-network
    process types)**, minus `scheduler` process types. Both arms are load-bearing:
    the first is the declared interface graph; the second catches every publicly
    reachable boundary even when nothing inside the project consumes it, which is
    what gives the health-endpoint gate something to validate. Driving the set off
    `consumes` alone would silently switch that gate off for a public edge.

    Providers ship a contract at ``infra/contracts/<svc>.<proc>.<fmt>.yml``. The
    path is process-keyed unconditionally: one codebase may run two HTTP process
    types — a public `api` and an internal `admin` — and both are genuine
    boundaries deserving their own contract.

    Returns (existing_contracts, providers) — the contract paths that DO exist,
    for the next gate to scan, and the provider process refs, dotted.
    """
```

New body:

```python
    # Every `consumes` target in the document, dotted. Mod 101 is the first
    # reader of `consumes`; it lives on the AUTHORING model (Mod 098 kept it off
    # `CompiledService` deliberately), which is what this gate reads.
    consumed: set[str] = set()
    for _s, _p, _svc, proc in infra.all_processes():
        consumed |= proc.consumes_refs()

    contracts_dir = worktree / "infra" / "contracts"
    missing: list[str] = []
    fallbacks: list[str] = []
    for svc_name, proc_name, _svc, proc in infra.all_processes():
        # contracts.md § Health Checks: `scheduler` process types are exempt.
        # Rule 25 now forbids consuming one and rule 27 forbids `web` in its
        # networks, so neither arm can reach a scheduler — the gate states the
        # exemption anyway so it does not depend on the validator to be correct.
        if proc.role == "scheduler":
            continue
        label = ProcessRef(svc_name, proc_name).dotted
        on_web = "web" in (proc.networks or [])
        if not (on_web or label in consumed):
            continue  # not a provider
        providers.append(label)
        fmt, role_known = _contract_format_for_role(proc.role)
        if not role_known:
            fallbacks.append(f"{label} (role {proc.role!r})")
        candidate = contracts_dir / f"{svc_name}.{proc_name}.{fmt}.yml"
        if candidate.is_file():
            existing.append(candidate)
        else:
            missing.append(f"{label} (expected {candidate.relative_to(worktree)})")
```

Then extend the reporting so the role fallback is never silent:

```python
    if missing:
        report.add(
            "contracts_exist",
            False,
            "missing contract(s): " + "; ".join(missing),
        )
    else:
        detail = (
            f"{len(existing)} contract(s) present"
            if existing
            else "no provider process types — nothing to check"
        )
        if fallbacks:
            detail += (
                "; unrecognized role, assumed openapi: " + ", ".join(fallbacks)
            )
        report.add("contracts_exist", True, detail)
    return existing, providers
```

If `missing` is non-empty **and** `fallbacks` is non-empty, append the same fallback
clause to the failure detail too — the fallback is likely to be *why* the contract
appears missing.

## Step 9 — `check.py`: `_gate_health_endpoints`

Replace the function wholesale. Two phases: contract-declared endpoints, then
field-declared probeability.

```python
def _gate_health_endpoints(
    worktree: Path,
    ctx: ProjectContext,
    contracts: list[Path],
    report: CheckReport,
) -> None:
    """Assert the doctrine's health model (contracts.md § Health Checks).

    Three things, per process type:

    1. **Self health** — every OpenAPI provider declares ``GET /health``. § Self
       health says *every* long-running process type serves it; a `worker` is not
       checked here because its contract is AsyncAPI, which has no natural place
       for an HTTP path — not because it is exempt. Its self-health is asserted
       through its fields instead (3).
    2. **Fan-out** — every `web`-network process type declares
       ``GET /health/<svc>/<proc>`` for each of its `consumes` targets that is not
       itself on `web`. Keyed off `consumes`, not `depends_on`: a web edge does not
       depend on its worker (it needs the *broker* up), and rule 24 now forbids a
       core `depends_on` outright, so a `depends_on`-keyed gate requires nothing at
       all of a web → worker edge. A dead consumer is invisible from outside —
       requests keep returning 200 while work piles up behind it. Targets on `web`
       are skipped: they are publicly reachable and answer their own `/health`, so
       there is nothing to proxy. Backing services have no `<svc>/<proc>` form and
       are not required (mod 047); a project may still declare them voluntarily.
    3. **Probeability** — a `consumes` target declares both `port` and
       `health_check_path`. Per § Declared by fields those two fields *are* the
       health declaration. On elastic the `port` is also exactly what makes the
       target Service-Connect-discoverable, which is what lets a sibling `web`
       process reach its `/health` one hop away. Distinct from rule 28, which
       constrains a process type that *has* `health_check_path`; this requires a
       consumes target to have it at all.

    `scheduler` process types are exempt throughout.
    """
    infra = ctx.infra
    if infra is None:
        report.add("health_endpoints", True, "no infra.yml — skipped")
        return

    problems: list[str] = []

    # --- 1 + 2: what the contracts must declare -------------------------
    for path in contracts:
        parsed = _parse_contract_filename(path.name)
        if parsed is None:
            continue  # not a contract filename this gate authored
        svc, proc_name, fmt = parsed
        resolved = _resolve_process(infra, f"{svc}.{proc_name}")
        if resolved is None:
            continue  # contract for an unknown process type — skip
        _s, _p, proc = resolved
        if proc.role == "scheduler":
            continue

        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: malformed YAML ({exc})")
            continue
        paths_map = (doc.get("paths") or {}) if isinstance(doc, dict) else {}

        def _declares(key: str) -> bool:
            node = paths_map.get(key)
            return isinstance(node, dict) and "get" in {k.lower() for k in node}

        if fmt == "openapi" and not _declares("/health"):
            problems.append(
                f"{path.name}: missing 'GET /health' (contracts.md § Self health "
                f"— every long-running process type serves it)"
            )

        if "web" not in (proc.networks or []):
            continue
        for dotted in sorted(proc.consumes_refs()):
            target = _resolve_process(infra, dotted)
            if target is None:
                continue
            t_svc, t_proc_name, t_proc = target
            if t_proc.role == "scheduler":
                continue
            if "web" in (t_proc.networks or []):
                continue  # publicly reachable; nothing to proxy
            key = f"/health/{t_svc}/{t_proc_name}"
            if not _declares(key):
                problems.append(
                    f"{path.name}: missing 'GET {key}' (required because "
                    f"{svc}.{proc_name} consumes non-web {dotted})"
                )

    # --- 3: what the consumed process type's FIELDS must declare --------
    # Keyed by target so two consumers of one under-declared target produce one
    # problem naming both, not two problems saying the same thing.
    underdeclared: dict[str, tuple[list[str], set[str]]] = {}
    for svc_name, proc_name, _svc, proc in infra.all_processes():
        for dotted in sorted(proc.consumes_refs()):
            target = _resolve_process(infra, dotted)
            if target is None:
                continue
            _t_svc, _t_proc_name, t_proc = target
            if t_proc.role == "scheduler":
                continue
            absent = []
            if t_proc.port is None:
                absent.append("port")
            if (t_proc.model_extra or {}).get("health_check_path") is None:
                absent.append("health_check_path")
            if absent:
                entry = underdeclared.setdefault(dotted, (absent, set()))
                entry[1].add(ProcessRef(svc_name, proc_name).dotted)
    for dotted in sorted(underdeclared):
        absent, consumers = underdeclared[dotted]
        problems.append(
            f"consumes target {dotted!r} declares no "
            f"{' and no '.join(absent)} — those fields ARE its health "
            f"declaration (contracts.md § Declared by fields), and on elastic "
            f"the port is what makes it Service-Connect-discoverable. "
            f"Consumed by: {', '.join(sorted(consumers))}."
        )

    if problems:
        report.add("health_endpoints", False, "; ".join(problems))
    else:
        report.add(
            "health_endpoints",
            True,
            f"all required endpoints present in {len(contracts)} contract(s)",
        )
```

Note the `# Mod 101` marker comment at the old `:388` disappears with the rewrite.
`grep -rn "Mod 101" src/` must come back empty afterwards.

## Step 10 — leave the curl gate alone

`_gate_healthcheck_tooling` is **not** modified. It stays keyed off
`health_check_path`, which is correct now that the field is process-scoped; re-keying
it off `role` would be strictly worse, because the compiler emits the curl healthcheck
from the field and `infrastructure.md` states the requirement in those terms. Mod 096
already repaired this gate. Do not touch it.

## Step 11 — stale-path repairs

1. `src/docex/errors.py`, `ContractMissing` docstring: `infra/contracts/<svc>.<fmt>.yml`
   → ``infra/contracts/<svc>.<proc>.<fmt>.yml``.
2. `plans/core/masterplan.md` line 163: same substitution in the § Filesystem Surface
   **Read:** list.
3. In `_gate_contracts`'s new docstring (Step 8) the dangling citation to
   "contracts.md § Contract Location" — a heading that does not exist — is already gone;
   confirm no other file cites that heading: `grep -rn "Contract Location" src/ plans/`.

---

## Step 12 — tests

### 12a. New file `tests/unit/test_contract_health_gates.py`

Follow the inline-`infra.yml` pattern of `_hc_ctx` in `tests/unit/test_pipeline_check.py`
(build a project under `tmp_path`, `load_project_context`, invoke the gate directly).
Write a helper that takes a `core_services:` YAML block and a dict of contract
filename → contract body, and emits:

- `project.yml`: `name: hc`, `version: "0.1.0"`, `docex_version: "1.0.3"`
- `infra/infra.yml` with the standard preamble used by `_hc_ctx` (`cicl_version: "2"`,
  `foundation: fixed`, `apex_domain`, `container_registry`,
  `observability_backend_url`, `domain_default_process: api.web`) plus the caller's
  `core_services:` block
- `infra/contracts/<name>` for each contract given

A minimal well-formed openapi body is
`openapi: "3.0.3"\ninfo: {title: t, version: "0.1.0"}\npaths:\n  /health: {get: {responses: {"200": {description: ok}}}}\n`;
add extra paths per test. An asyncapi body needs no `paths` at all — that is the point.

Required cases:

| Test | Shape | Assertion |
| ---- | ----- | --------- |
| `test_worker_provider_gets_asyncapi` | `api.web` (web, port 8080, hcp) `consumes: [api.worker]`; `api.worker` (role worker, internal, port 9090, hcp) | With only `api.web.openapi.yml` present, `contracts_exist` **FAILS** and the detail names `api.worker.asyncapi.yml`. Then with that file added, it **PASSES**. |
| `test_two_web_processes_each_get_a_contract` | `api.web` + `api.admin`, both `networks: [web, internal]`, distinct ports | Both `api.web.openapi.yml` and `api.admin.openapi.yml` are required; deleting either fails the gate naming exactly that one. |
| `test_contract_filename_parsed_right_anchored` | none — call `_parse_contract_filename` directly | `"api.web.openapi.yml"` → `("api","web","openapi")`; `"api.openapi.yml"` → `None`; `"a.b.c.d.yml"` → `None`; `"api.web.openapi.txt"` → `None`. |
| `test_missing_fanout_probe_fails` | as case 1, both contracts present, `api.web.openapi.yml` has `/health` but not `/health/api/worker` | `health_endpoints` fails, detail contains `/health/api/worker`. Adding the path makes it pass. |
| `test_fanout_required_without_depends_on` | as case 1 with **no `depends_on:` anywhere in the document** | The probe is still required. This is the whole point of keying off `consumes` — assert explicitly that the document has no `depends_on`. |
| `test_consumes_target_without_port_fails` | as case 1 but `api.worker` declares `health_check_path` and **no `port`** | `health_endpoints` fails, detail names `api.worker` and `port`. |
| `test_consumes_target_without_health_check_path_fails` | as case 1 but `api.worker` has `port` and no `health_check_path` | fails, detail names `health_check_path`. |
| `test_scheduler_is_never_a_provider` | `api.web` (web) + `jobs.nightly` (role scheduler, internal, with a `schedule:`) | `contracts_exist` passes with only `api.web.openapi.yml`; no `jobs.nightly.*` contract demanded. |
| `test_openapi_provider_requires_self_health` | `api.web` on web, contract with `paths: {/other: ...}` | `health_endpoints` fails naming `GET /health`. |
| `test_internal_openapi_provider_requires_self_health` | `api.web` (web) `consumes: [api.internal]`; `api.internal` role `web`, `networks: [internal]`, port + hcp, contract present but lacking `/health` | fails — the Q5 widening: self-`/health` follows the OpenAPI contract, not web membership. |
| `test_unknown_role_fallback_is_reported` | a process type with `role: bogus` on the web network, with `api.bogus.openapi.yml` present | `contracts_exist` passes (no raise) **and** the detail string mentions the fallback and the role name. |

**The asyncapi case must genuinely have failed before this mod.** Verify it, do not
assume: `git stash push -- src/docex/pipeline/check.py` (or copy the file aside),
re-run just that test, confirm it FAILS, restore. Under the old code `api.worker` is
neither on `web` nor a `depends_on` target, so it is not a provider at all and the gate
passes with only the openapi contract — the assertion that `contracts_exist` fails is
what breaks. Report in your summary that you performed this check and what the old-code
failure output was.

### 12b. Rule 25's scheduler clause

Add `test_consumes_scheduler_rejected` to `tests/unit/test_consumes_relation.py`
(where rule 25's other cases live — match that file's existing fixture style). Assert
the issue's `rule` is `rule_25_consumes_scheduler` and that a `consumes` edge to a
non-scheduler process type in the same document produces no issue.

### 12c. Regression signal

`tests/unit/test_pipeline_check.py` and the `sample_project` / `sample_project_elastic`
fixtures must pass **unchanged**. That shape (one web process, one backing
`depends_on`, no `consumes`) is unaffected by every change here. If a fixture needs
editing to stay green, stop — that means the change altered behavior for a shape it
should not have, and it needs reporting rather than a fixture edit.

---

## Step 13 — run the suites

```
python3 -m pytest tests/unit -q
python3 -m pytest tests/ -q
```

Report **both** counts. Bars: unit ≥ 926 passed; full ≥ 990 passed / 17 deselected.
Integration collection must still yield 17 (`python3 -m pytest tests/integration
--collect-only -q | tail -3`).

## Step 14 — do NOT commit

Leave all changes uncommitted. The mod cycle's review step needs to read them as a
clean diff against the design commit, and the tree contains staged work belonging to
other mods that must not be swept in.

---

## Report back

1. Both suite counts, before/after.
2. The old-code verification result for the asyncapi test (Step 12a).
3. Anything you changed that this document did not specify, and why.
4. Any place the doctrine and the code could not be reconciled — raise it, do not
   paper over it.
