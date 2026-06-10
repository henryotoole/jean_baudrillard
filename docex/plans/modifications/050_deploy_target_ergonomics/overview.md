# Mod 050 — Deploy-Target Ergonomics (Gaps G, D)

Second of three mods (050/051/052) feeding a **single** `1.1.0` minor cut at the end of the post-shape-overhaul polish campaign. No per-mod cut, no per-mod version bump — changes accumulate under `CHANGELOG.md`'s `[Unreleased]`.

The two:
- **Gap G** — first fixed `docex release` fails at image pull with a registry `401`; nothing catches the missing target-host creds before then. *(The substantive item; carries a doctrine touch.)*
- **Gap D** — empty-`dist/` chicken-and-egg on first `envinfra up dev`. **Largely already closed** by the committed `up.py::_ensure_initial_dev_build` (path 1); this mod adds only a small clarifying diagnostic and marks the gap closed.

Operator decisions (this session): Gap G → **Path 1 (preinfra probe)**; Gap D → **close + tiny `build.py` diagnostic**.

---

## Gap G — `docex release` doesn't verify target-host registry creds

**Symptom:** First-ever `docex release stage` on a fixed project fails at `docker compose pull` with `401 Unauthorized` from the registry. Resolution is manual: populate `~/.docker/config.json` for both `deploy` and `root` on the target host (`PRE_CUT_CHECKLIST.md A.7`).

**Root cause:** `release.py::_release_fixed` runs the emitted playbook, which pulls via `community.docker.docker_compose_v2` with `pull: always` and **no `docker_login` task** — it relies on the target host's `~/.docker/config.json` being populated out-of-band (per `release.md § Registry Credentials`). Meanwhile `preinfra.py` *explicitly* documents (lines 31–32) that it does **not** check registry creds. So the gap is invisible until the release-time 401.

**Decision — Path 1 (preinfra probe).** `docex preinfra production` (fixed) gains a check that the target host carries the registry cred at both paths the playbook uses:
- `/home/deploy/.docker/config.json` (pulls run as the `deploy` user)
- `/root/.docker/config.json` (`docker compose up` runs under `become: true`)

Failing with a clear message + resolution (`docker login <registry>` as both users). This matches preinfra's "check status; don't create" contract and surfaces the problem at the right layer (preinfra → projinfra → release), one tier before release.

**Fix shape (SSH probe — a local check is impossible):** `docex` runs as the operator user (the shim's `--user`), and `/root/.docker/config.json` sits under a mode-`700` `/root`, so a *local* `Path.is_file()` from a non-root process can't distinguish "missing" from "unreadable". The reliable check therefore mirrors exactly how release reaches the host — SSH as `deploy` via `infra/deploy_creds/<env>`, with `sudo` for the root path. This reuses only what already exists: the per-env deploy keys, the apex-derived host (`release.md § Inventory`), and the host-side `deploy` user + passwordless `sudo` release already assumes. **No new credentials, no new project structure.**

1. New minimal `SSHClient` (Protocol + subprocess impl + conftest fake — the established three-place client pattern) exposing `run(host, key_path, command, *, user="deploy") -> int` via `ssh -i <key> -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 <user>@<host> '<cmd>'`.
2. `run_preinfra` gains an `ssh: SSHClient | None = None` param (mirrors the lazy-`aws` pattern); the dispatcher constructs it only for `(fixed, production)`. A `None` on that branch is a defensive "dispatcher bug" failure, like the `aws`-None guard.
3. New `_check_fixed_registry_creds(ctx, ssh)` probes **both** `stage` and `prod`:
   - Deploy key absent (`infra/deploy_creds/<env>`) → enumerated failure ("…needed to reach the host"), skip that env's probe.
   - Host derived from `apex_domain` via `dns_label` (stage → `stage.<label>.<apex>`; prod → `<label>.<apex>`).
   - One SSH command per env: `test -f /home/deploy/.docker/config.json && sudo -n test -f /root/.docker/config.json`. Exit 0 → ok; `255` → distinct "could not reach `<env>` host" failure; other non-zero → "registry creds missing on `<env>` host — run `docker login <registry>` as both `deploy` and `root`".
4. Reuse `run_preinfra`'s accumulate-all-failures style; for a single shared fixed host the two env probes harmlessly hit the same machine.

**Doctrine touch (Path-1 requires it — drafted for approval before any edit):**
- `preinfra/container_registry.md` — the doc already states (line ~268) that production hosts need the cred in `~/.docker/config.json`; add that `docex preinfra production` (fixed) now *verifies* its presence at `/home/deploy/.docker/config.json` and `/root/.docker/config.json`, and fails with the `docker login` resolution.
- `specifics/release.md § Registry Credentials` — currently frames detection as a release-time loud failure; add one sentence that preinfra now pre-checks this so the gap surfaces a tier earlier.
- `preinfra.py`'s own docstring (code, not doctrine) flips its "registry availability NOT checked" note — narrowly: we check *target-host creds*, still not registry *availability/reachability* (that remains `containerize`'s natural surface). The doctrine wording should preserve that distinction.

*(Proposed exact wording is presented to the operator for approval in-conversation; the doctrine edit precedes implementation per `docex_process.md`.)*

---

## Gap D — empty-`dist/` chicken-and-egg (largely already closed)

**Symptom (historical):** First `docex envinfra up dev` on a fresh tree crash-looped the web container (`can't open file '/service/dist/root.py'`) because the host `dist/` bind-mount shadowed the in-image artifact; `docex build` then refused to populate `dist/` while the container was `Restarting`.

**Status:** Path 1 is **done and committed** — `up.py::_ensure_initial_dev_build` pre-populates each core service's host `dist/` (via a no-bind-mount build-stage one-shot) before `compose up`, breaking the original chicken-and-egg. The campaign roadmap listing Gap D as fully open is stale.

**Decision — close + tiny diagnostic.** Treat the core as closed. The one residual rough edge: `build.py::run_build` keys off `compose_ps` (running-only, lines 60 & 98), so if a target container is `Restarting` it refuses with a generic "dev container … is not running." Add a clearer diagnostic distinguishing *restarting* from *absent*:

**Fix shape:**
1. `src/docex/orchestrate/build.py` — when the requested service isn't in the running set, consult `compose_ps_status` (the Gap-K method added in mod 049) to distinguish `restarting`/`unhealthy` from genuinely-down, and print a targeted line (e.g. "container is restarting, not running — check `docker logs <name>`; `docex build` needs a healthy dev container"). Still refuses (no behavior change to the success path) — just a readable failure.
2. Mark Gap D **closed** in `plans/campaigns/post_shape_overhaul.md` (status note pointing at `_ensure_initial_dev_build` + this diagnostic).

**Explicitly out of scope** (per the decision): path-2 ephemeral-build-on-restarting and root-owned-`dist/` chown handling. If the one-shot copy's ownership ever bites in practice, that's a follow-up — not pulled into this mod.

---

## What lands in this mod

| Change | File(s) |
| ------ | ------- |
| `_check_fixed_registry_creds` in fixed-production preinfra (Gap G) | `src/docex/pipeline/preinfra.py` |
| Restarting-vs-absent diagnostic in `build` (Gap D) | `src/docex/orchestrate/build.py` |
| Gap D marked closed | `plans/campaigns/post_shape_overhaul.md` |
| Doctrine: preinfra verifies target-host registry creds (Gap G) | `doctrine/.../preinfra/container_registry.md`, `doctrine/.../specifics/release.md` *(pending operator-approved wording)* |
| CHANGELOG `[Unreleased]` entries (no version bump) | `CHANGELOG.md` |

Tests:
- Gap G: unit test `run_preinfra` (fixed, production) with a fake filesystem/docker-creds probe — passes when both config.json paths present, fails (with the resolution message) when either is missing. Existing preinfra tests unaffected (default = creds present).
- Gap D: unit test `run_build` where `compose_ps` reports the service down but `compose_ps_status` reports `restarting` → asserts the restarting-specific diagnostic line.

## Cut shape

No own cut. Contributes to the batched **1.1.0** minor cut performed after 052, which pays the test-project smoke-walk tax once for 049–052 together. Gap G touches the fixed release/preinfra path, so the fixed smoke walk at cut time is the integration proof that the probe + the (still out-of-band) creds flow line up end-to-end.
