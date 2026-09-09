# Mod 153 — Implementation: re-tier the `test` web network (F7 §4)

Hand-off doc. Executes the design in [`overview.md`](./overview.md). Scope:
**docex source + tests + regenerated golden only.** Do **not** edit doctrine
prose (`doctrine/…`) or docex core planning docs (`plans/core/…`) or the
CHANGELOG — those are handled by the coordinator in a later documentation step.

## Goal (one line)

For the **`test` env only**, the `web` network becomes an **env-tier, per-slot,
non-external docker bridge** the env stack creates — instead of the external,
projinfra-owned `${project}-test-web` network. `dev`/`stage`/`prod` are
unchanged. This removes `test`'s last projinfra dependency and slots the one
physical name Mod 152 left unslotted.

Everything is in `src/docex/emit/compose.py` plus test/golden updates. No
compiler (`cicl/compile.py`) change is needed — `CompiledEnv.slot` and
`compiled.env` already carry everything required.

---

## Change 1 — `_network_section` (env-tier emitter)

File: `src/docex/emit/compose.py`, function `_network_section`.

Replace the loop body so the `web` special-case is gated on `env != "test"`;
`test`'s `web` falls through to the same slotted-bridge branch as the non-web
networks.

**Current** (the `for` loop and the two lines above it):

```python
    out: dict[str, Any] = {}
    # Mod 152: non-web env networks carry the slot segment so slots are
    # isolated at the network layer too. The `web` network is external/
    # projinfra-owned and stays slot-shared this mod (Mod 153 re-tiers it).
    slot_seg = "" if compiled.slot == 1 else f"-s{compiled.slot}"
    for short in sorted(compiled.networks):
        if short == "web":
            out[short] = {
                "name": f"{compiled.project_dns_label}-{compiled.env}-web",
                "external": True,
            }
            continue
        full = f"{compiled.project_dns_label}-{compiled.env}{slot_seg}-{short}"
        out[short] = {"name": full}
    return out
```

**New:**

```python
    out: dict[str, Any] = {}
    # Mod 152: non-web env networks carry the slot segment so slots are isolated
    # at the network layer too. Mod 153: the `test` env's web network ALSO
    # carries the segment and becomes a plain env-tier bridge (see the branch
    # below), which is why the segment is computed unconditionally here.
    slot_seg = "" if compiled.slot == 1 else f"-s{compiled.slot}"
    for short in sorted(compiled.networks):
        # dev/stage/prod: `web` is the projinfra-owned, external, project-tier
        # `${project}-${env}-web` network (mod 036); env compose merely
        # attaches. `test` is the exception (mod 153): it is never TLS'd or
        # routed (mod 054), so its web network is re-tiered to an env-tier,
        # per-slot, NON-external bridge the env stack creates and tears down —
        # removing `test`'s last projinfra dependency and slotting the one name
        # Mod 152 left unslotted. So `test`'s `web` falls through to the same
        # slotted-bridge branch as the non-web networks below.
        if short == "web" and compiled.env != "test":
            out[short] = {
                "name": f"{compiled.project_dns_label}-{compiled.env}-web",
                "external": True,
            }
            continue
        full = f"{compiled.project_dns_label}-{compiled.env}{slot_seg}-{short}"
        out[short] = {"name": full}
    return out
```

Also update the **function docstring** of `_network_section`: replace the final
`Mod 152:` paragraph (the one ending "until Mod 153 re-tiers it.") with a
paragraph stating the Mod 153 outcome — that `web` is external/projinfra only for
`dev`/`stage`/`prod`, and for `test` it is an env-tier, per-slot, non-external
bridge (`${project}-test${slot_seg}-web`) that the env stack owns.

Leave `_traefik_labels` untouched — it is never called for `test` (the
`env != "test"` guard at the `svc.web_hosts` label site, mod 054, already skips
web routing for `test`).

## Change 2 — `emit_project_compose` (project-tier / projinfra emitter)

File: `src/docex/emit/compose.py`, function `emit_project_compose`. `test`'s web
network is no longer projinfra, so remove it from the project-tier compose in the
**two** places it appears (these are the only `test-web` references in `src/`,
confirmed by grep):

1. In the top-level `networks:` dict, **delete** the entry:

```python
            f"{project_dns_label}-test-web": {
                "name": f"{project_dns_label}-test-web"
            },
```

   Keep the `dev-web`, `stage-web`, `prod-web`, and `docex-ingress` entries.

2. In the `{project_dns_label}-traefik` service's `networks:` list, **delete**
   the line:

```python
                    f"{project_dns_label}-test-web",
```

   The traefik service now joins three `-web` networks + `docex-ingress`. (It
   never registered routers for `test` — those containers carry no traefik
   labels — so it loses nothing.)

Update the `emit_project_compose` **docstring** first line accordingly: it says
"declaring the four `${project_dns_label}-${env}-web` external networks" — change
"four" to "three (`dev`/`stage`/`prod`; `test`'s web network is env-tier per
mod 153)".

## Change 3 — adjacent code-comment factual fix

File: `src/docex/pipeline/projinfra.py`. Two docstrings state fixed projinfra
brings up "four `-web` networks" (module docstring ~line 3; the compose-project
docstring ~line 57). Change "four" → "three" and add "(`test`'s web network is
env-tier per mod 153, not projinfra)". These are inline code docs describing the
emitted projinfra shape; no logic changes in this file.

---

## Change 4 — unit test updates

Run `python -m pytest tests/unit` after each; these five are the known set, fix
any others the run surfaces.

### 4a. `tests/unit/test_compile.py::test_project_tier_compose_declares_four_web_networks`
- Rename to `..._declares_three_web_networks`.
- Loop over `("dev", "stage", "prod")` only, asserting each `-web` present.
- Add an explicit assertion that `f"{project}-test-web"` is **NOT** in
  `networks` (the re-tier removed it from projinfra).
- Update the docstring ("four" → "three; `test`'s web network is env-tier").

### 4b. `tests/unit/test_compile.py::test_project_tier_compose_declares_traefik_service`
- In `expected_networks`, **remove** `f"{project}-test-web"`. The set becomes the
  three `-web` networks + `docex-ingress`.
- Update the docstring reference to "four `-web`".

### 4c. `tests/unit/test_compile.py::test_env_compose_web_network_references_project_tier_external`
- Split the loop. For `env in ("dev", "stage", "prod")`, keep the existing
  assertion `web == {"name": f"sample-{env}-web", "external": True}`.
- For `env == "test"`, assert the **non-external bridge**:
  `web == {"name": "sample-test-web"}` (no `external` key).
- Update the docstring to describe the split.

### 4d. `tests/unit/test_compose_emitter.py::test_web_network_is_project_env_external_and_others_are_project_scoped`
- Same split as 4c: `dev`/`stage`/`prod` → external reference; `test` →
  `{"name": "sample-test-web"}` (non-external). Keep the existing `internal`
  assertions (unchanged for all envs). Update the docstring.

### 4e. `tests/unit/test_slot_primitive.py::test_slot2_emitted_compose_isolates_names`
- This currently asserts the **Mod 153 seam** (the unslotted external web net):
  ```python
      # the -web external network is NOT slotted (Mod 153 seam).
      assert "docex-smoke-fixed-test-web" in compose
      assert "docex-smoke-fixed-test-s2-web" not in compose
  ```
- **Flip it** — at test slot 2 the web network is now a slotted bridge:
  ```python
      # Mod 153: test's web network is now an env-tier, per-slot bridge, so at
      # slot 2 it carries the segment and the unslotted name is gone.
      assert "docex-smoke-fixed-test-s2-web" in compose
      assert "docex-smoke-fixed-test-web" not in compose
  ```
  Note `compile_slot(ctx, "test", 2)` writes to `.docex/slots/test/2/` and the
  fixture project name is `docex_smoke_fixed` → dns label `docex-smoke-fixed`.
  Confirm the exact strings against the emitted file if they differ.

## Change 5 — integration gate (single slot works, over the bridge, no projinfra)

File: `tests/integration/test_test_real.py`,
`test_docex_test_passes_and_tears_down`.

The advance-plan gate requires proving a live web container is reachable **over
the re-tiered `-web` bridge** while the single `test` slot is up, and that this
happens with **no projinfra**. Strengthen the test:

1. **Prove no projinfra dependency (precondition).** Before `run_test`, assert
   the projinfra web network does **not** exist on the daemon, so the run cannot
   be leaning on a leftover external network:
   ```python
   import subprocess
   probe = subprocess.run(
       ["docker", "network", "inspect", "sample-test-web"],
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
   )
   assert probe.returncode != 0, (
       "sample-test-web must NOT pre-exist — mod 153 removed test's projinfra "
       "web dependency; a leftover would invalidate the gate"
   )
   ```
   (The conftest `_isolate_shared_stacks` fixture already `down -v`s the
   `sample-test` project between tests; the sample fixture project name is
   `sample`, so the test web bridge is `sample-test-web`.)

2. **Prove HTTP reachability over the bridge.** `run_test` brings the stack up,
   runs the shims, and tears it down inside one call — so an external probe
   cannot catch the stack mid-flight. Instead, add a **new** integration test
   that brings the `test` stack up directly, hits the web service over the
   bridge, then tears down. Model it on the up/down structure already in
   `tests/integration/test_up_down_real.py`, but for the `test` env:

   ```python
   @pytest.mark.integration
   def test_test_web_reachable_over_retiered_bridge(fresh_project, docker_client):
       """Mod 153: the single test slot's web core service is reachable over the
       env-tier, non-external `sample-test-web` bridge — and the bridge is
       created by the stack itself (no projinfra)."""
       import subprocess
       ctx = load_project_context(fresh_project)
       compose_file = fresh_project / "infra" / "output" / "test" / "docker-compose.yml"
       env_file = fresh_project / "infra" / "secrets" / "test.env"
       # Precondition: the bridge does not pre-exist.
       assert subprocess.run(
           ["docker", "network", "inspect", "sample-test-web"],
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       ).returncode != 0
       try:
           rc = docker_client.compose_up(
               compose_file, build=True, detach=True,
               env_file=env_file, project_dir=fresh_project,
               project_name="sample-test",
           )
           assert rc == 0, "test stack should come up with no projinfra"
           # The bridge exists now, created by the stack — not external.
           assert subprocess.run(
               ["docker", "network", "inspect", "sample-test-web"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           ).returncode == 0
           # Reach the web core service over that bridge from a one-off
           # container attached to it. The fixture app serves GET /health ->
           # {"version": "0.1.0"} on :8080; the container name is the global
           # name sample-test-api-web.
           out = subprocess.check_output(
               ["docker", "run", "--rm", "--network", "sample-test-web",
                "alpine:latest", "sh", "-c",
                "wget -qO- http://sample-test-api-web:8080/health"],
               text=True, timeout=60,
           )
           assert '"version"' in out and "0.1.0" in out, out
       finally:
           docker_client.compose_down(
               compose_file, preserve_volumes=False,
               env_file=env_file, project_dir=fresh_project,
               project_name="sample-test",
           )
   ```

   Verify the `compose_up`/`compose_down` keyword args match
   `src/docex/docker/subprocess_client.py` signatures (they are
   `build`, `detach`, `env_file`, `project_dir`, `project_name`). If the web
   container needs a moment to bind :8080, wrap the `wget` in a short retry loop
   inside the `sh -c` (e.g. `for i in $(seq 1 10); do wget -qO- … && break; sleep 1; done`).

   Leave the existing `test_docex_test_passes_and_tears_down` as-is (it still
   proves up+migrate+shims+teardown green); you may optionally add the
   precondition assertion from step 1 to it as well.

## Change 6 — regenerate golden output (BOTH foundations)

The `test` web-network emission and the project-tier compose change, so the
committed golden trees for **both** test projects must be regenerated. Run
`docex compile` (via the same entry the tests use) against each:

```
python -c "from docex.cicl.compile import run_compile; from docex.context import load_project_context; import sys; sys.exit(run_compile(load_project_context('test_projects/fixed')))"
python -c "from docex.cicl.compile import run_compile; from docex.context import load_project_context; import sys; sys.exit(run_compile(load_project_context('test_projects/elastic')))"
```

(or `./bin/docex compile` run from each project root, whichever is the
established local invocation — confirm against `docex_process.md`.)

Then **inspect `git diff --stat` and `git diff`** on `test_projects/*/infra/output`
and confirm the change set is exactly:

- **fixed:** `test/docker-compose.yml` (web network: external ref → non-external
  bridge), `project/development/docker-compose.yml` and
  `project/production/docker-compose.yml` (test-web dropped from networks +
  traefik membership). **`dev/`, `stage/`, `prod/` compose byte-identical.**
- **elastic:** `test/docker-compose.yml` (web bridge) and
  `project/development/docker-compose.yml` (test-web dropped — the dev side is
  always fixed even on an elastic project). **`dev/docker-compose.yml`
  byte-identical; `stage/main.tf`, `prod/main.tf`, `project/production/main.tf`
  (HCL — no `-web` bridges) byte-identical; all `schedules.yml` byte-identical.**

If any `dev`/`stage`/`prod` **env** compose file shows a diff, STOP — the
`env != "test"` gate is wrong. Commit the regenerated golden.

Note: `tests/unit/test_slot_golden.py` recompiles both projects and byte-compares
against these committed trees, so it passes once the golden is regenerated. (Its
skip comment about elastic golden being "deleted in fd8c578" is stale — the
elastic golden is present and its gate is live; do not touch the test.)

## Contracts

**None.** No surface changes; network re-tiering does not alter any core
service's contract. Do not touch `infra/contracts/`.

---

## Verification checklist (run before reporting done)

1. `python -m pytest tests/unit` — fully green (all five updated tests pass).
2. `python -m pytest tests/unit/test_slot_golden.py` — green for **both**
   `fixed` and `elastic` (neither skipped), proving golden regenerated correctly
   and dev/stage/prod unchanged.
3. `git diff --stat test_projects/` — changed files match the exact set in
   Change 6; no `dev`/`stage`/`prod` **env** compose in the diff.
4. `python -m pytest tests -m integration` (requires docker) — the new
   `test_test_web_reachable_over_retiered_bridge` passes (HTTP `0.1.0` over the
   bridge, bridge created by the stack, no pre-existing external network), and
   `test_test_real.py` still green + torn down.
5. `python -m pytest tests` — the full suite green.

Report: the `git diff --stat` of `test_projects/`, confirmation that dev/stage/
prod env compose stayed byte-identical on both foundations while `test/` +
project-tier regenerated, and the integration-gate result (HTTP over bridge, no
projinfra).
