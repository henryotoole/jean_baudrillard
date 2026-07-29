# Mod 104 — Implementation

Implementation steps for [`overview.md`](./overview.md). Written for a fresh
context: everything needed is below, but read `overview.md` first for *why*.

Repo root is `/home/ubuntu/.claude/jean_baudrillard`; all paths below are
relative to `/home/ubuntu/.claude/jean_baudrillard/docex` unless stated. Run
tests with **`python3 -m pytest`** (not `uv run`).

**Do not touch any doctrine file.** `doctrine/infrastructure/docex.md § describe`
will read stale after this mod; that is Mod 106's, by plan. See
[Notes for Mod 106](#notes-for-mod-106) — a record, not a step.

## Line numbers

Cited against the tree at the design commit. Anchor on the quoted code, not the
number.

---

## Step 1 — carry `consumes` onto `CompiledService`

`src/docex/cicl/compile.py`.

### 1a. The dataclass field

`CompiledService` ends its Mod 096 "Process expansion" block with
`replicas: int = 1` (`:518-521`). Append after it:

```py
    # Rule 25's interface edges, as COMPILED identities (`api-worker`) — the
    # same keys into `CompiledEnv.services` that `depends_on` holds, so an edge
    # of either relation resolves with one dict lookup. Empty for a backing
    # service, which has no `consumes:` (rule 14). Mod 104 compiles it for
    # `describe`'s union view; it is a declared field on both models, so it
    # cannot reach field translation and nothing is emitted from it.
    consumes: list[str] = field(default_factory=list)
```

**WHY it sits here rather than beside `depends_on`** (`:468`), which is where it
belongs conceptually: `depends_on` is in the dataclass's *non-defaulted* region,
and a required field inserted there would break the three sites that construct
`CompiledService` directly (`tests/unit/test_replicas.py:339`,
`test_naming_policy_leak.py:77`, `test_emit_dispatch.py:62`). Put that reason in
the comment as a one-line `WHY:` so the placement is not "corrected" later.

### 1b. Populate it

In the `CompiledService(...)` call (`:997`), after
`replicas=(svc.replicas if is_core else 1),`:

```py
            # `consumes_refs()` (Mod 101) is the ONE parse of rule 25's field —
            # it normalizes to the dotted reference form and drops entries that
            # do not parse, so a malformed entry is reported once by rule 25 and
            # never resurfaces here as a phantom node. Re-parsing dotted →
            # compiled is the price of not writing a second parser; every entry
            # is known-parseable by construction.
            consumes=(
                sorted(
                    ProcessRef.parse(dotted).compiled
                    for dotted in svc.consumes_refs()
                )
                if is_core else []
            ),
```

`ProcessRef` is already imported (`:32`). `svc` is the `ProcessType` when
`is_core`; `consumes_refs()` exists only there, hence the guard.

Nothing else in `compile.py` changes.

---

## Step 2 — `describe/dag.py`: one derivation, both relations

`src/docex/describe/dag.py`.

### 2a. Imports and module docstring

Import `CompiledService` and `ProcessRef` alongside the existing `CompiledEnv`:

```py
from docex.cicl.compile import CompiledEnv, CompiledService
from docex.cicl.model import ProcessRef
```

Amend the module docstring's second paragraph to say the renderer emits **both**
relations — `depends_on` (readiness) and `consumes` (interface) — and that the
rendered union is a directed graph which **may legally contain cycles**, since
`consumes` is a cyclic digraph by doctrine. Keep it to two or three sentences.

### 2b. Three module-level functions

Insert after the four tier constants (`_PROJECT_ELASTIC`, ending `:41`) and
before `render_dag`. These are the **graph-view API** — deliberately public,
unlike the tier constants `llm.py` already imports, because the cross-module use
is intentional.

```py
def node_id(svc: CompiledService) -> str:
    """The display id of one compiled service — a ``describe`` node id.

    Dotted for a core process type (``api.web``), bare for a backing service
    (``appdb``), per cicl.md § Dots for reference, hyphens for emission, which
    names ``describe`` node ids in its dotted list. The compiled key is
    hyphenated (``api-web``) and does not decompose, since both segments may
    themselves contain ``-``; a view whose whole purpose is human understanding
    uses the reference form and shows the emitted name beside it.
    """
    if svc.core_service is not None and svc.process is not None:
        return ProcessRef(svc.core_service, svc.process).dotted
    return svc.name


def target_id(compiled: CompiledEnv, key: str) -> str:
    """Display id for an edge target named by its compiled key.

    Falls back to the raw key when the target is absent. ``run_describe`` calls
    ``compile_env`` WITHOUT ``validate_document``, so a document with an
    unresolvable ``consumes`` target reaches the renderer; ``describe`` is
    purely illustrative and must degrade to printing an odd token rather than
    raise.
    """
    target = compiled.services.get(key)
    return node_id(target) if target is not None else key


def collect_edges(compiled: CompiledEnv) -> list[tuple[str, str, str]]:
    """Every edge of both relations, as ``(from_id, to_id, kind)``.

    The single derivation behind both renderers. ``llm.py`` ran a second,
    independent copy of this loop until Mod 104: there is one graph and two
    *renderings* of it, so there is one derivation.

    Readiness edges first, each group sorted by source then target, so the
    output is order-stable.

    A flat pass over ``CompiledEnv.services`` — deliberately NOT a graph walk.
    ``consumes`` is a cyclic digraph by doctrine (``web ↔ worker`` is legal and
    the most common topology there is), so a traversal here would need a
    visited set and would be one forgotten line away from unbounded recursion.
    Keep it flat: there is no traversal to get wrong.
    """
    edges: list[tuple[str, str, str]] = []
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for dep in sorted(svc.depends_on):
            edges.append((node_id(svc), target_id(compiled, dep), "depends_on"))
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        for consumed in sorted(svc.consumes):
            edges.append((node_id(svc), target_id(compiled, consumed), "consumes"))
    return edges
```

### 2c. Node lines use the display id, and columns line up

In `render_dag`, the network loop (`:74-79`) and service loop (`:81-88`) both pad
the *name* rather than the whole `kind:name` token, which leaves the two kinds'
columns misaligned (`core` and `backing` differ in width — visible in today's
output). Build the label first and pad that, at width 24 to match the
prerequisite/project tier lines above:

```py
        for n in networks:
            full = f"{compiled.project}_{compiled.env}_{n}"
            kind = "docker network" if compiled.foundation == "fixed" else "AWS security group"
            label = f"network:{n}"
            lines.append(f"  - {label:<24} {full}  ({kind})")
    # Services.
    for name in sorted(compiled.services):
        svc = compiled.services[name]
        kind = "core" if svc.is_core else "backing"
        # WHY the pad spans `kind:id` and not the id alone: padding the id left
        # the `core:` and `backing:` rows in different columns.
        label = f"{kind}:{node_id(svc)}"
        lines.append(
            f"  - {label:<24} {svc.global_name}  "
            f"[role={svc.role}, engine={svc.engine}, networks={svc.networks}]"
        )
```

The emitted `global_name` stays where it is — the reference form and the
hyphenated emitted name sitting side by side is the point.

### 2d. Both edge groups

Replace the whole flat edge block (`:87-96`, from the `# Depends-on edges.`
comment to the end of the loop) with:

```py
    # Both relations, visually distinguished. The kind is carried TWICE — glyph
    # and heading — because this output is as often grepped as read: `grep
    # consumes` must find the interface edges. `->` / `..>` is mermaid's
    # solid/dashed (`-->` / `-.->`) rendered in ASCII.
    edges = collect_edges(compiled)
    groups: list[list[str]] = []
    for kind, heading, arrow in (
        ("depends_on", "depends_on edges (readiness) — solid:", "->"),
        ("consumes", "consumes edges (interface) — dashed:", "..>"),
    ):
        rendered = [
            f"  {src} {arrow} {dst}" for src, dst, k in edges if k == kind
        ]
        if rendered:
            groups.append([heading, *rendered])
    for i, group in enumerate(groups):
        if i:
            lines.append("")
        lines.extend(group)

    return "\n".join(lines)
```

The blank line goes *between* groups, so the output gains no trailing newline.
An empty relation renders no heading, as today.

---

## Step 3 — `describe/llm.py`: consume the shared derivation

`src/docex/describe/llm.py`.

### 3a. Imports

Add `collect_edges`, `node_id`, `target_id` to the existing `from
docex.describe.dag import (...)` block.

### 3b. Node dicts carry both axes and both relations

In the service loop (`:32-43`), change `"short"` and add three keys:

```py
        env_resources.append({
            "kind": "core_service" if svc.is_core else "backing_service",
            "name": svc.global_name,
            "short": node_id(svc),
            # Both axes independently readable, so a consumer never splits a
            # hyphenated string to recover them (the same argument Mod 102 made
            # for two OTel attributes over one fused `service.name`). None for a
            # backing service, which has no process dimension.
            "core_service": svc.core_service,
            "process": svc.process,
            "role": svc.role,
            "engine": svc.engine,
            "networks": svc.networks,
            "port": svc.port,
            "depends_on": svc.depends_on,
            # Display ids, so a node's relations join to node `short` values
            # exactly as `depends_on` already does.
            "consumes": [target_id(compiled, k) for k in svc.consumes],
        })
```

### 3c. Edges

Replace the second, independent edge pass (`:45-49`) with:

```py
    edges = [
        {"from": src, "to": dst, "kind": kind}
        for src, dst, kind in collect_edges(compiled)
    ]
```

Nothing else in `llm.py` changes; the doc dict and `json.dumps(...,
sort_keys=True)` stay as they are.

---

## Step 4 — dev DNS: pin the per-process-type enumeration

**No production code changes.** `_check_dev_dns` (`src/docex/pipeline/preinfra.py:165`)
delegates to `web_hostnames_for_env`, which Mod 096 already moved to process
types (`cicl/compile.py:435-438` iterates `doc.all_processes()`). Verified by
reading; do not "fix" it.

What is missing is coverage *at the preinfra layer*: its tests run against the
sample fixture, which has exactly one process type, so nothing there would fail
if the enumeration collapsed back to one host per codebase.

Add to `tests/unit/test_pipeline_preinfra.py`, next to the existing dev-DNS block
(`:110-200`), following the shape of `test_preinfra_dev_dns_all_resolve_passes`
exactly:

```py
def test_preinfra_dev_dns_enumerates_per_web_process_type(
    sample_ctx, fake_docker, fake_dns,
):
    """A codebase with TWO web process types has TWO dev hosts checked.

    Mod 104. The check delegates to `web_hostnames_for_env`, which is
    per-process-type since Mod 096 — but every other test in this module runs
    against the one-process-type sample fixture, so a regression that collapsed
    the enumeration back to one host per CODEBASE would pass all of them. This
    test fails against such an implementation.
    """
    import yaml
    from docex.context import load_project_context

    infra_path = sample_ctx.project_root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["core_services"]["api"]["processes"]["admin"] = {
        "role": "web",
        "command": ["python", "/service/dist/admin.py"],
        "port": 8081,
        "networks": ["web", "internal"],
        # Rule 7: the fixture's DATABASE_* refs are declared at the SERVICE
        # level, so every process type of `api` owes the readiness edge.
        "depends_on": ["appdb"],
        "resources": {"cpu": 0.5, "memory": "1GB", "disk": "20GB"},
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    ctx = load_project_context(sample_ctx.project_root)

    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_dns.default = True
    rc = run_preinfra(
        ctx, fake_docker, aws=None, side="development", dns=fake_dns,
    )
    assert rc == 0
    # Both web process types of the ONE codebase, plus the bare-env host that
    # `api.web` earns as `domain_default_process`.
    assert set(fake_dns.asked) == {
        "api-web.dev.sample.example.com",
        "api-admin.dev.sample.example.com",
        "dev.sample.example.com",
    }
```

Hostnames are the **emitted** (hyphenated) form here — these are data-plane
names, not `describe` node ids. If the actual host set differs, fix the
assertion to what `web_hostnames_for_env` produces and keep the "two hosts, one
codebase" property; do **not** weaken it to a subset check.

---

## Step 5 — new unit tests for `describe`

New file `tests/unit/test_describe.py`. There is no unit-level describe test
today (only `tests/integration/test_compile.py::test_describe_dag_and_llm`), and
these renderers are pure functions over a `CompiledEnv`, so the unit layer is
their home.

Build the `CompiledEnv` in memory, in the style of
`tests/unit/test_web_hostnames.py`:

```py
import json
import yaml

from docex.cicl.compile import compile_env
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.describe.dag import collect_edges, node_id, render_dag
from docex.describe.llm import render_llm


def _compiled(src: str, env: str = "prod"):
    return compile_env(
        CICLDocument.model_validate(yaml.safe_load(src)),
        load_transfer_tables(project_root=None),
        env=env,
        project_name="sample",
        project_version="0.1.0",
    )
```

A document with the legal `web ↔ worker` interface cycle, a replica count, and a
backing service:

```yml
cicl_version: "2"
foundation: fixed
apex_domain: example.com
container_registry: registry.example.com
observability_backend_url: "https://obs.example.com"
domain_default_process: api.web
core_services:
  api:
    processes:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        port: 8080
        networks: [web, internal]
        depends_on: [appdb]
        consumes: [api.worker]
        resources: {cpu: 1.0, memory: 2GB, disk: 20GB}
      worker:
        role: worker
        command: ["python", "-m", "worker"]
        networks: [internal]
        depends_on: [appdb]
        consumes: [api.web]
        replicas: 4
        resources: {cpu: 0.5, memory: 1GB, disk: 20GB}
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    port: 5432
    networks: [internal]
    schema_owned_by: api
```

Cover **all** of the following. Each is a distinct failure mode; do not merge
them into fewer, broader tests.

1. **`consumes` compiles to compiled identities.**
   `services["api-web"].consumes == ["api-worker"]` and
   `services["api-worker"].consumes == ["api-web"]`. Not dotted — these are keys
   into `services`, so assert the lookup succeeds too.
2. **A backing service compiles to an empty `consumes`.**
   `services["appdb"].consumes == []`.
3. **Malformed entries are dropped, as in every other reader.** A variant doc
   whose `web` carries `consumes: ["appdb", "api"]` (a backing target and a bare
   name — both rule-25 violations) compiles to `consumes == []`. `compile_env`
   does not validate, so this is the property that keeps a rejected entry from
   surfacing as a phantom node.
4. **The DAG renders both kinds, distinguishably.** Both headings present;
   `"  api.web -> appdb"` present; `"  api.web ..> api.worker"` present. Assert
   the readiness line does **not** use `..>` and vice versa.
5. **Node ids are dotted; the emitted name still appears.** `"core:api.web"` in
   the output and `"core:api-web"` **not** in it, while
   `"sample-prod-api-web"` (the `global_name`) **is**.
6. **A `consumes` cycle renders without recursing or erroring.** `web ↔ worker`:
   both directions appear, and **each edge exactly once** — a naive walk would
   either recurse forever or emit duplicates. `render_dag` is called directly, so
   a recursive implementation fails the test by blowing the stack.
7. **`replicas: 4` still yields one node.** Exactly one line containing
   `core:api.worker`; exactly two `core:` lines in total; and
   `services["api-worker"].replicas == 4`, so the test proves the count is
   *carried but not multiplied* rather than merely absent.
8. **The LLM JSON carries both edge kinds.** `{e["kind"] for e in edges} ==
   {"depends_on", "consumes"}`, and the `consumes` edge's `from`/`to` are dotted.
9. **LLM nodes carry both axes and their `consumes`.** The `api.web` node has
   `short == "api.web"`, `core_service == "api"`, `process == "web"`,
   `consumes == ["api.worker"]` (display ids); the `appdb` node has
   `core_service is None` and `process is None`.
10. **One derivation, two renderings.** The `(from, to, kind)` set from
    `collect_edges` equals the set built from the parsed LLM JSON edges, and
    every arrow line in the DAG has a matching tuple. This is the regression
    guard against the duplicated loop coming back.
11. **An unresolvable `consumes` target degrades rather than raising.** A variant
    doc whose `web` carries `consumes: ["ghost.web"]` — well-formed, so
    `consumes_refs()` keeps it, but naming no compiled service. `render_dag` must
    render `api.web ..> ghost-web` (the raw key fallback) and not raise.

---

## Step 6 — update the one pre-existing assertion

`tests/integration/test_compile.py::test_describe_dag_and_llm` (`:914-917`)
asserts `edge["from"] == "api-web"`. Change it to `"api.web"`.

This is an **update, not a deletion**: the assertion predates this mod, and the
form it asserted was never the doctrine's — `cicl.md § Dots for reference,
hyphens for emission` has named `describe` node ids as dotted all along. Leave
the `assert "depends_on" in out` check alone; it still holds.

Check the rest of that test file for any other assertion against a `describe`
node id (`grep -n 'api-web' tests/integration/test_compile.py` will over-match,
since `api-web` is also the legitimate emitted name in dozens of compose/HCL
assertions — only `describe`-scoped ones change).

---

## Step 7 — verify

```
python3 -m pytest tests/unit -q
python3 -m pytest tests/ -q
```

Expected: **more than 962** unit passed (baseline 962, this mod adds ~12) and
**more than 1026** in the full run with 17 deselected. Report both numbers.

If anything was 962-green before and is red now, that is a real regression —
stop and report it rather than adjusting the test.

Also render the DAG by hand once and read it, since the deliverable is a human
view:

```
python3 -c "
import yaml
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.compile import compile_env
from docex.describe.dag import render_dag
src=open('tests/fixtures/sample_project/infra/infra.yml').read()
doc=CICLDocument.model_validate(yaml.safe_load(src))
c=compile_env(doc, load_transfer_tables(project_root=None), env='prod',
              project_name='sample', project_version='0.1.0')
print(render_dag(c))
"
```

Confirm the columns line up and the node ids are dotted. (The sample fixture has
no `consumes`, so no interface group appears — that is correct.)

---

## Out of scope

- **Any doctrine file.** Not `docex.md`, not `cicl.md`, not `contracts.md`.
- Rollback (Mod 105), version artifacts / smoke projects / changelog (Mod 107).
- `CHANGELOG.md` — Mod 107 owns it, consistent with Mods 094-103.
- Renaming the `--format dag` flag. Decided against; see below.
- `check.py`'s health/contract gates. They read `consumes` from the **authoring**
  model and correctly continue to, because they run pre-compile. The new
  compiled field is not a reason to reroute them, and `consumes_refs()` remains
  the single parse behind all three readers.
- Core planning docs (`docex/plans/core/*.md`) — the mod's documentation step,
  owned by the C.O. after review, not by this implementation.

---

## Notes for Mod 106

**RECORD ONLY — do not edit any doctrine file in this mod.**

`doctrine/infrastructure/docex.md § describe` says:

> `dag` - Describe the infrastructure shape with a directed acyclic graph.

After this mod that is **false, not merely stale**. The rendered union includes
`consumes` edges, and `consumes` is a cyclic digraph by doctrine — `web ↔ worker`
is legal (rule 25, asserted by
`tests/unit/test_consumes_relation.py::test_12_consumes_cycle_is_legal_while_a_depends_on_cycle_is_fatal`)
and is the most common topology there is.

The amendment: **"directed acyclic graph" → "directed graph"**, noting that the
readiness relation (`depends_on`) alone is the acyclic one, which is why rule 6's
cycle detection runs over the backing-service graph and not over `consumes`.

The **flag name `dag` stays.** A format name is a label identifying which
renderer to invoke, not a claim; the sentence is what asserts the property, and
the sentence is the thing that is wrong. Renaming is a user-facing CLI change
this advance does not need to spend, and it costs the same later if the operator
wants it. Decided by the C.O. during Mod 104's design review — recorded so it is
not re-litigated.

The same section's `preinfra` blurb ("each `dev` `web`-service hostname") is
already per-*service* wording for what is now per-*process-type* behavior. Mod
096 caused that; Mod 104 pins it with a test. Mod 106 should fix the wording.
