# Mod 004 — Teardown filter fix + dead-code cleanup

## Problem

Two scoped findings left over from the C.* walk of `test_projects/fixed`:

1. **`test_projects/fixed/teardown.sh` stray-resource filter is broken.** The script's "compose down" step (step 1) walks the local `infra/output/<env>/docker-compose.yml` paths. For dev/test those are the real running compose project, so it works. For stage/prod, the actual running stack was deployed by ansible to `/opt/<project>/<env>/`, so step 1 is a no-op. The script then relies on its "stray docker resources" filter (step 2) to mop up. That filter uses `name=${PROJECT_NAME}` — but `PROJECT_NAME` is `docex_smoke_fixed` (underscores), while the running container/network/volume names use hyphens (`docex-smoke-fixed-prod-web`, …). Docker's `--filter name=…` is a substring match, and the underscore string never appears in the hyphen names. So the filter matches nothing. Stage/prod stacks survive teardown; `verify_clean.sh` reports them as still-present.

2. **`_image_for` in `src/docex/emit/ansible.py` is dead code.** It exists only to feed the old migration playbook task that used `community.docker.docker_container` with an explicit `image:` field. Mod 003 replaced that with `docker compose run --rm <svc> /service/migrate.sh`, which gets the image from the compose service definition rather than needing the playbook to specify it. The function is defined and registered as a Jinja helper (`image_for=_image_for`) but no template uses it anymore.

## Design

### Fix 1: teardown.sh — loop both underscore and hyphen forms in the stray-resource filter

The minimal fix is to expand step 2's filter to match BOTH forms. The doctrine's name-translation rule (per `transfer_tables.md § naming` and the postgres engine's `naming.separator: hyphen` etc.) means a project named `foo_bar` produces container names like `foo-bar-…`. For teardown purposes — which is just "remove anything that looks like ours" — running the cleanup twice, once per form, is the simplest correct behavior.

```bash
# After existing PROJECT_NAME line:
PROJECT_NAME_HYPHEN="${PROJECT_NAME//_/-}"

# Step 2 rewrite:
echo "-- stray docker resources by name prefix"
for pattern in "$PROJECT_NAME" "$PROJECT_NAME_HYPHEN"; do
  for container in $(docker ps -aq --filter "name=${pattern}" 2>/dev/null || true); do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  for network in $(docker network ls -q --filter "name=${pattern}" 2>/dev/null || true); do
    docker network rm "$network" >/dev/null 2>&1 || true
  done
  for volume in $(docker volume ls -q --filter "name=${pattern}" 2>/dev/null || true); do
    docker volume rm "$volume" >/dev/null 2>&1 || true
  done
done
```

Step 1 (compose down on local paths) stays as-is. For stage/prod it remains a no-op — the local compose file doesn't correspond to a running project — but that's fine because step 2 forcefully removes the actual running containers by name. The trade-off: stage/prod stacks get `docker rm -f` instead of a graceful `compose down`. That's acceptable for a "fully retire" teardown script.

Why not also fix step 1 to point at `/opt/<project>/<env>/` for stage/prod? Two reasons:
- Those paths are root-owned (`become: true` deployed them); compose-down from there needs sudo.
- It's redundant given step 2's force-rm covers the same containers.

Minimal-change-for-correctness wins here.

### Fix 2: drop `_image_for` from `src/docex/emit/ansible.py`

Delete:
- Lines 9: `from docex.cicl.compile import CompiledEnv, CompiledService` → drop `CompiledService` (only used by the function being removed)
- Lines 15–19: the `_image_for` function definition
- Line 45: the `image_for=_image_for,` line in the `playbook_tpl.render(...)` call

After deletion, run `python3 -m pytest tests/unit/` to confirm nothing breaks. Existing tests cover the playbook emitter's behavior; they should pass unchanged.

The elastic-side teardown at `test_projects/elastic/teardown.sh` already handles the hyphen translation correctly (it pre-computes `PROJECT_AWS_PREFIX="${PROJECT_NAME//_/-}"` for the same reason). Mod 004 brings the fixed-side teardown to parity. No changes needed to the elastic teardown.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | No change. This is project-local script + dead-code cleanup; no doctrinal prose. |
| `docex/plans/core/*.md` | No change. |
| `tables/roles/*.yml` | No change. |
| `src/docex/**` | `src/docex/emit/ansible.py` — drop `_image_for` and its registration. |
| `tests/**` | No new tests. Existing unit tests cover ansible.py's playbook rendering and will continue to pass. teardown.sh isn't unit-tested in this repo; its integration test is the C.10 walk-and-verify_clean cycle. |

Plus `docex/test_projects/fixed/teardown.sh` — project-local, not doctrine.

## Validation

1. `python3 -m pytest tests/unit/` — all tests still pass (170 expected).
2. Re-run `docex compile` for `test_projects/fixed` — produces identical output (the dead `_image_for` was never referenced by the live templates). Spot-check by comparing pre/post stage `playbook.yml` if curious.
3. **Teardown integration test** (the actual coverage for the bash change):
   - Bring up `test_projects/fixed` stage stack via `./bin/docex release stage`.
   - Run `bash teardown.sh && bash verify_clean.sh` from `test_projects/fixed/`.
   - `verify_clean.sh` should report "clean." with no leftover containers/networks/volumes.
   - **This is operator-side validation.** The mod 003 walk left no live stacks, so this can run cleanly when the operator next wants to verify the fix.

## Decisions captured

1. **Minimal teardown fix.** Just expand the filter to cover both name forms. Don't refactor step 1 to point at `/opt/…` paths — redundant with step 2 and adds sudo complexity.
2. **No new unit tests.** teardown.sh doesn't have a test harness; adding one is out of scope. The walk validation is sufficient.
3. **No doctrine prose changes.** Both fixes are local — teardown.sh is per-project, `_image_for` was internal-to-docex dead code. The doctrine doesn't reference either.

## No pause needed

Both changes are mechanical and don't touch operator-approved prose. Going straight to implementation.md after this overview is approved.
