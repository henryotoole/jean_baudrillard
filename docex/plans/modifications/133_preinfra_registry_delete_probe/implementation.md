# Mod 133 — Implementation steps

Design: [`overview.md`](./overview.md). Read Part 1 before writing code — it
contains the measurements that decided the mechanism, and Part 2's ruling on
exit codes is the part most likely to be implemented from habit instead of from
the design.

**Interpreter:** `.venv/bin/python`. `python` is not on `PATH`, and **bare
`pytest` cannot collect this suite** (it reports 17 deselected while nothing
runs). Always `.venv/bin/python -m pytest`.

**Baseline at `bd69ed6`:** `pytest tests` → 1174 passed, 18 deselected;
`pytest tests -m integration` → 18 passed (**run alone**).

**The one rule that governs every step below:** a verdict of "capability
present" may be produced *only* by an observation that positively proves it.
Everything else is either the ABSENT finding (rc 1) or a printed declination
(rc 0). No branch may fall through to a pass.

---

## Step 1 — `src/docex/registry/client.py` (new)

Create `src/docex/registry/__init__.py` (empty) and `client.py`:

```python
"""``RegistryClient`` protocol and its result type. Mod 133.

The development-side preinfra check verifies that the container registry
will accept a manifest DELETE — the capability every `fixed` project's
`teardown.sh` depends on. The runtime implementation is in
`urllib_client.py`; unit tests inject a fake.

WHY the result carries the registry's own error code and not just the HTTP
status: a reverse proxy in front of the registry can produce a bare 405
(method rejected) or a bare 404 (wrong route), and reading either as a
verdict invents a misconfiguration that does not exist. Only the registry's
own `errors[].code` distinguishes its answer from something else's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ManifestDeleteResult:
    """Outcome of one ``DELETE /v2/<repo>/manifests/<ref>``.

    Exactly one of ``status`` and ``failure`` is set. ``status`` means a
    response was received; ``failure`` means no response could be obtained
    and names why, so the caller can decline with a specific resolution
    rather than a generic one.
    """

    status: int | None = None
    error_code: str | None = None
    failure: str | None = None   # "no_credential" | "bad_credential_store" | "transport"
    detail: str = ""


class RegistryClient(Protocol):
    """Abstraction over the Registry V2 HTTP API. Never raises: a request
    that cannot be made or completed comes back as a ``failure`` result, so
    the caller decides whether that is a finding or a declination."""

    def delete_manifest(
        self, host: str, repository: str, reference: str,
    ) -> ManifestDeleteResult:
        ...
```

## Step 2 — `src/docex/registry/urllib_client.py` (new)

The runtime implementation. Requirements:

- **Sole transport importer.** Say so in the docstring, mirroring
  `dns/dnspython_resolver.py` ("the only module in docex permitted to
  `import dns`"). This is the only module permitted `urllib.request` for
  registry HTTP.
- `__init__(self, *, docker_config_path: Path | None = None, timeout: float = 10.0)`.
  Default path `Path.home() / ".docker" / "config.json"`. The override exists so
  the integration test exercises the real credential-reading code.
- **Credential read.** Parse the config JSON, take `auths[host]["auth"]`, which
  is base64 `user:password`. Map each failure to a `failure=` result, never an
  exception:
  - file missing → `failure="no_credential"`, detail names the path.
  - unparseable JSON → `failure="no_credential"`, detail says the file could not
    be parsed.
  - no `auths` entry for `host` → `failure="no_credential"`.
  - entry present but no `auth` key → `failure="bad_credential_store"`, detail
    notes the credential is held by a `credsStore`/`credHelpers` helper that
    docex will not invoke.
  - `auth` not valid base64, or decodes without a `:` → `failure="no_credential"`.
- **Never log, print, or place the credential (or the decoded password) in any
  result field.** `detail` is operator-facing text and must stay
  credential-free. This is the one hard security constraint in the mod.
- **Scheme.** `https` unless the host is `localhost` / `127.0.0.1` (bare or with
  a `:port`), in which case `http`. Comment the WHY: this mirrors Docker's own
  insecure-registry default rather than being a test affordance.
- **Request.** `DELETE {scheme}://{host}/v2/{repository}/manifests/{reference}`
  with `Authorization: Basic <auth>` and `Accept: application/json`, under
  `timeout`.
- **Response handling.** Use `urllib.error.HTTPError` — it *is* a response, so a
  4xx/5xx must produce `status=...`, **not** `failure=...`. Read the body (bounded,
  e.g. 64 KiB), try `json.loads`, and pull `errors[0]["code"]` if present;
  `error_code` stays `None` when the body is absent, not JSON, or has no code.
  `URLError`, `socket.timeout`, and TLS/DNS errors → `failure="transport"` with
  the exception text in `detail`.

> The `HTTPError`-is-a-response point is the single easiest thing to get wrong
> here, and getting it wrong turns the ABSENT finding — a 405 — into a
> declination, silently deleting the only branch that can fail.

## Step 3 — `src/docex/pipeline/preinfra.py`

### 3a. Module docstring

**Rewrite the exclusion list; do not append to it.** Today it reads:

> Container registry *availability / reachability* — whether the registry itself
> is up and serving (`docex containerize` surfaces that naturally). …

It must now state three things:

1. Under "what gets checked → any project, `development` side": the registry
   manifest-delete capability, on `fixed` projects with a `container_registry`.
2. That this is a **configuration** question — does the registry permit deletes —
   and therefore in scope.
3. That **reachability and auth remain excluded**, which is *why* those outcomes
   decline (rc 0) instead of failing, and that `containerize` is where they
   surface. Name `teardown.sh` as the dependent.

A stale exclusion list is how the next reader concludes this probe was a mistake
and deletes it. Treat this as a deliverable, not a comment tidy-up.

### 3b. Signature and declination plumbing

`run_preinfra` gains `registry: RegistryClient | None = None`. It must now
collect **two** lists: the existing `failures` and a new `declined`. Output:

```
preinfra <side> side: N check(s) failed:
  - ...
```
then, when `declined` is non-empty:
```
Declined — printed, not failures. A verifier may decline to answer, but not quietly:
  - <mode>: <detail>. <resolution>
```
`return 1 if failures else 0` — **`declined` never affects the exit code.** On a
run with declinations and no failures, still print the existing
`preinfra <side> side: all checks passed.` line, so the declined block reads as
an addendum rather than a verdict.

### 3c. The check

Gate, inside the existing `side == "development" and ctx.infra is not None`
block (add alongside the DNS check, so the `ctx.infra is None` no-op is inherited):

```python
if ctx.infra.foundation == "fixed" and ctx.infra.container_registry:
    if registry is None:
        failures.append(
            "development side requires a registry client but none was "
            "provided (this is a dispatcher bug)."
        )
    else:
        f, d = _check_registry_manifest_delete(ctx, registry)
        failures.extend(f); declined.extend(d)
```

The `None` guard is a **failure**, matching the existing `aws`/`ssh`/`dns`
guards: a forgotten dispatcher call site must be loud, never a silent skip.
Elastic, and fixed-without-`container_registry`, produce **nothing at all** —
not a declination. The question does not apply (design Q3).

`_check_registry_manifest_delete(ctx, registry) -> tuple[list[str], list[str]]`:

- Module constants: `_DELETE_PROBE_REPOSITORY = "preinfra-smoke/delete-capability-probe"`,
  `_DELETE_PROBE_DIGEST = "sha256:" + "0" * 64`. Comment that `preinfra-smoke/`
  is the namespace the doctrine already reserves, the repository does not exist,
  and the digest cannot exist — so the request is side-effect-free by
  construction.
- Call `registry.delete_manifest(host, _DELETE_PROBE_REPOSITORY, _DELETE_PROBE_DIGEST)`.
- Verdict mapping, in this order:

| Condition | Outcome |
| --- | --- |
| `failure == "no_credential"` | declined; resolution `docker login <host>` |
| `failure == "bad_credential_store"` | declined; resolution: docex will not invoke a credential helper |
| `failure == "transport"` | declined; resolution: registry unreachable, `containerize` owns reachability |
| `status == 405 and error_code == "UNSUPPORTED"` | **FAILURE** (see message below) |
| `status == 405` (other/absent code) | declined: a 405 without the registry's `UNSUPPORTED` code — something between docex and the registry rejected the method |
| `status in (401, 403)` | declined: credential rejected or lacks delete scope |
| `status == 404 and error_code in {"MANIFEST_UNKNOWN", "NAME_UNKNOWN", "BLOB_UNKNOWN"}` | **pass** — nothing appended |
| `status == 202` | **pass** — capability directly observed |
| `status == 404` (no registry code) | declined: a 404 without a registry error code is a proxy 404 |
| anything else | declined: unexpected status, quote it and the code |

Write the mapping as an explicit ladder ending in a catch-all declination.
**There must be no implicit fall-through to pass**; only the two pass rows above
may return an empty verdict.

The failure message must name: the host, that manifest DELETE is refused with
`405 UNSUPPORTED`, `REGISTRY_STORAGE_DELETE_ENABLED: "true"`, the compose block
(`/opt/docex-preinfra/container_registry/registry/docker-compose.yml`), and the
consequence — every `fixed` project's `teardown.sh` leaks one registry tag per
release, and registry garbage collection cannot start.

## Step 4 — `src/docex/__main__.py`

Add a lazy constructor beside `_make_ssh_client`:

```python
def _make_registry_client() -> "object":
    from docex.registry.urllib_client import UrllibRegistryClient
    return UrllibRegistryClient()
```

Thread it into **all three** call sites that can pass `side="development"`. Each
already has the shape to copy:

1. `_cmd_envinfra` (~line 204) — `run_preinfra(ctx, docker, aws=None, side="development", dns=..., registry=_make_registry_client())`.
2. `_cmd_preinfra` (~line 263) — construct only when
   `ctx.infra is not None and ctx.infra.foundation == "fixed" and ns.side == "development"`,
   mirroring the existing `needs_aws` / `needs_ssh` pattern.
3. `_cmd_projinfra` fixed-up (~line 325) — `ns.side` may be `development`.

Site 4 (`run_preinfra(ctx, docker, aws, side="production")`, ~line 349) is
production-only; leave it.

## Step 5 — `tests/conftest.py`

Add `FakeRegistryClient` + a `fake_registry` fixture, in the style of
`FakeDnsResolver`/`FakeSSHClient` (dataclass, scriptable, recording):

- `result: ManifestDeleteResult` — what `delete_manifest` returns. **Default it
  to the passing observation** (`status=404, error_code="MANIFEST_UNKNOWN"`) so
  the ~10 existing dev-side tests need only the fixture threaded, not a scripted
  result.
- `results: dict[tuple[str, str], ManifestDeleteResult]` keyed on
  `(host, repository)`, consulted before `result`.
- `calls: list[tuple]` recording every invocation, so tests can assert the probe
  targeted the reserved repository and the zero digest — and that it was *not*
  called on the elastic / no-registry paths.

## Step 6 — `tests/unit/test_pipeline_preinfra.py`

**Thread `fake_registry` into the ~10 existing `side="development"` tests.** The
fixture is `sample_project`, which is `foundation: fixed` with
`container_registry: "registry.example.com"`, so the gate fires for all of them;
without the fixture they hit the dispatcher-bug guard and fail. That churn is
expected and is not a defect.

### Red before green

Write these **first** and observe them fail, before Step 3c's ladder exists.
Design Part 5 requires the honest failure plus at least two can't-answer modes;
implement all four, and record the observed red output in the mod folder as
`red_before_green.md` (paste the failing pytest output — this is the mod's
evidence, and a claim of "demonstrated red" with nothing to show is worth
nothing):

1. `405` + `UNSUPPORTED` → **rc 1**; output contains
   `REGISTRY_STORAGE_DELETE_ENABLED`.
2. `401` → **rc 0**; the mode is named in the `Declined` block; and assert the
   output contains **neither** `all checks passed`-implying-verified language for
   the capability **nor** the `REGISTRY_STORAGE_DELETE_ENABLED` finding. This is
   the trap that hid the original defect for several releases.
3. `failure="no_credential"` → **rc 0**, named declination, `docker login` in the
   resolution.
4. `405` with `error_code=None` → **rc 0**, declined as a proxy/method rejection,
   and explicitly **not** reported as a delete-disabled registry. This is the
   false-positive arm.

### Remaining coverage

- `404 MANIFEST_UNKNOWN` → rc 0, nothing in `Declined`, `all checks passed`.
- `202` → pass.
- `bad_credential_store`, `transport`, `403`, bare `404`, `500`, and
  `400 DIGEST_INVALID` → each rc 0 and each *individually named*.
- Scope: `elastic_ctx` development side → `fake_registry.calls == []`, no
  declination printed. A fixed ctx with `container_registry` unset → same.
- `ctx.infra is None` → no call, no output about the registry.
- `registry=None` on a fixed dev side → failure mentioning "dispatcher bug".
- The probe targets `preinfra-smoke/delete-capability-probe` and the 64-zero
  digest (assert from `calls`) — pins the side-effect-free contract.

## Step 7 — `tests/unit/test_dispatcher.py`

`test_preinfra_dev_dispatches_to_run_preinfra_without_aws` monkeypatches a
`fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None)` (~line 99).
**Add `registry=None` to that signature** or the new kwarg raises `TypeError`.
Add an assertion that the development-side dispatch passes a non-`None`
`registry` for the fixed fixture — otherwise nothing catches a dropped call site.

## Step 8 — `tests/integration/test_preinfra_registry_delete_real.py` (new)

The positive control, and the version pin. `@pytest.mark.integration`; the
existing `tests/integration/conftest.py` auto-skips when docker is unreachable.

Model the container handling on `test_clock_delivery_real.py` (subprocess
`docker run` / `docker rm -f` in a fixture with teardown in a `finally`).

Fixture brings up **two `registry:2` containers** on free ephemeral ports:

- `-e REGISTRY_STORAGE_DELETE_ENABLED=true` → the **known-good** arm.
- no such env → the **known-bad** arm.

Poll `GET /v2/` until 200 (or 401) before probing rather than sleeping a fixed
interval. Write a temp Docker config containing an `auths` entry for each
`localhost:<port>` and pass its path to `UrllibRegistryClient(docker_config_path=...)`,
so the real credential-reading path is exercised.

Assertions:

1. Flag **on** → verdict PRESENT (`404`/`MANIFEST_UNKNOWN`), `run_preinfra`-level
   rc 0 with nothing declined.
2. Flag **off** → verdict **ABSENT**: `status == 405`, `error_code == "UNSUPPORTED"`,
   and `run_preinfra` rc **1** naming `REGISTRY_STORAGE_DELETE_ENABLED`.
3. A third arm with a **wrong credential** in the temp config → `401` →
   declined, rc 0.

Docstring must state, in these terms, that **assertion 2 is the version pin**:
the registry image is `registry:2` because that is what the doctrine pins;
`registry:3` does not honour the flag (measured: manifest DELETE returns 202 with
the flag unset), so if a future doctrine bump changes the image, this assertion
goes red and forces the inference in overview.md Part 1 to be re-derived rather
than silently lost. Also state that the registries run without htpasswd (auth is
covered by arm 3's wrong-credential case) and that no image is pushed — the probe
is side-effect-free.

## Step 9 — `doctrine_excerpts/container_registry.md`

Two edits, both narrow. **Do not restate the mod** — this is a `docex why`
excerpt and its job is orientation.

1. The fixed bullet gains a pointer to the resource's doctrine home. Currently
   the reader is sent only to the `container_registry:` *field*. Mention that on
   fixed the registry is operator-managed preinfra whose setup, delete-capability
   requirement, and GC procedure live in
   `infrastructure/preinfra/container_registry.md`.
2. Rewrite the closing citation into the **bounded** form — the whole citation
   inside one inline-code span — and add the preinfra file:

   ```
   Doctrine reference: `infrastructure/cicl.md § Container Registry and Service Images`; `infrastructure/preinfra/container_registry.md`.
   ```

   WHY bounded: `linkcheck.py` classifies a citation's heading only when the path
   and the `§` sit inside one common inline-code span; otherwise the heading is
   counted `unbounded` and never checked. Measured: this change moves the line
   from `unbounded` to `exact` (unbounded 25 → 24, exact 238 → 239).

**Do not "fix" the old heading text as though it were dead** — `§ Container
Registry` is an accepted *truncation* of `§ Container Registry and Service
Images` under `classify_citation`'s truncated-title rule. See overview.md Part 6
for the retraction. The reason to rewrite the line is verifiability, not
correctness.

Then run, from `$jb`:

```
python3 skills/cohere/executor/linkcheck.py
```

Expect green with `24 unbounded`. If it reports `BAD CITATION` you have the
heading wrong; if `unbounded` is still 25, the span is not bounded.

## Step 10 — `test_projects/PRE_CUT_CHECKLIST.md` § A.5

Add one box to A.5, keyed on **what the tool prints** (per `test_projects.md`'s
own lesson — do not restate a configuration):

- [ ] `./bin/docex preinfra development` from `test_projects/fixed` reports no
  registry failure and no registry declination. A **declination** here means the
  probe could not reach or authenticate to the registry, not that deletion is
  broken — fix A.5's other boxes first and re-run.

Immediately below, a short note in the checklist's own voice: this machine's
registry already has `REGISTRY_STORAGE_DELETE_ENABLED=true`, so a green walk
exercises the **pass arm only** and proves nothing about the ABSENT branch. The
fail arm is covered exclusively by
`tests/integration/test_preinfra_registry_delete_real.py`. A walker must not read
a green box here as having tested the failure path.

## Step 11 — Verify

From the project root, with `.venv/bin/python -m pytest`:

1. `pytest tests` — expect **1174 + new** passed, 18 deselected. Report the
   number.
2. `pytest tests -m integration` — **run alone**; expect **18 + 1** passed.
3. `python3 skills/cohere/executor/linkcheck.py` from `$jb` — green, 24 unbounded.
4. Live sanity, which is available on this machine and is not a substitute for
   either suite: from `test_projects/fixed`, `./bin/docex preinfra development`
   should pass with no declination (the real registry has the flag set and the
   operator's config has the credential).

Do **not** commit. The mod cycle's commits are the C.O.'s.

---

## Out of scope — do not touch

- **All doctrine.** Two findings (`registry:3` not honouring the flag; `cicl.md`
  permitting registries that cannot support `teardown.sh`) are the operator's and
  are recorded in overview.md.
- **`skills/cohere/executor/linkcheck.py`.** Its unbounded-citation class never
  reaches the `Declined` block despite its docstring saying it does. Raised in
  overview.md Part 6; mod 132 is closed and the output-volume call is not ours.
- **Anything from mods 125–132** — surfaces, health, contracts, `stagetest`.
- `plans/core/*` and `CHANGELOG.md` — the documentation step, handled by the C.O.
