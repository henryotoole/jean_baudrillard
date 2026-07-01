# Mod 068 — Per-call brokered git credentials (B2)

## Problem

Mod 061 gave the shim host-resolved git credentials for brokered-credential
environments (Periscope dev boxes): when `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set,
the shim runs `git credential fill` **once at invocation**, bakes the result into a
static `store` credential mounted into the container, and in-container git uses that
static copy for its network ops.

That resolve-**once** model is fragile for any docex command that does long work
*before* an in-container git network op. The brokered credential is a GitHub App
installation token, which GitHub **hard-caps at ~1 hour and will not issue for
longer** (`periscope/core/backend/src/shared/clients/github_app.py:197` — "the API
does not accept a custom TTL on this route"; `github_repo_token_ttl_seconds` is
already the 3600 s max). `docex merge` runs a full defensive `check` (cold image
build + the service test suite) *before* its `git fetch`, and the terminal `git
push` comes later still — so on a slow/cold run the baked token expires before the
git op and in-container git **cannot re-broker** (the helper + its socket don't
exist inside the container). Result: `docex merge` dies with `fatal: could not read
Username … (exit 128)` on **every** dev box using brokered git — the formal pipeline
is blocked. (Lifecycle-test finding **B2**.)

"Lengthen the TTL" (the finding's cheapest suggested fix) is **not available** — the
token is already at GitHub's immutable 1 h ceiling. Reordering `merge` to fetch
earlier does not close it either, because the `push` is dead last, after the long
`check`. The fix must make in-container git obtain a **fresh** credential *per
network operation*.

## Design intent

Replace the shim's resolve-**once** static-`store` injection with a **per-call
forwarding channel**: in-container git brokers a **fresh** credential on *every*
network op by forwarding each `git credential` request back out to the host's own
`git credential fill` (which drives whatever helper the host has — a fresh 1 h token
each time on a Periscope box). This permanently kills the whole "long work before an
in-container git op" bug class, not just `merge`.

Two principles carry over from mod 061 and are preserved:

- **Not Periscope-specific.** docex learns nothing about runners, sockets, or
  Periscope. It forwards to the standard `git credential fill`; any brokered-helper
  environment benefits identically. The environment supplies the helper; docex
  supplies the capability.
- **Entirely in the shim; no image change; version-independent.** The forwarding
  helper is a tiny script the shim **writes at runtime** into the mounted temp dir
  (not a new docex-image subcommand), so any docex image tolerates the newer shim —
  the "one shim serves every version, additive & backward-compatible" invariant
  holds. docex's in-container git and all merge/release orchestration are unchanged.

## Mechanism

When `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set and `origin` is `https://*` (else the
static path is used unchanged):

1. Create a mode-700 host temp dir (`mktemp -d`, `umask 077`).
2. Write two tiny helper scripts into it (heredocs — self-contained, no distribution
   change):
   - **`responder.py`** — runs **on the host**. Binds a Unix domain socket in the
     temp dir; on each connection reads the git credential attributes, runs the
     host's `git credential fill` (fresh broker → fresh token), and writes the
     `username`/`password` back. An accept-loop serves the sequential requests one
     docex run makes (fetch, then push).
   - **`forward.py`** — runs **in the container** as git's `credential.helper`. On a
     `get`, reads git's attributes from stdin, round-trips them through the mounted
     socket, and writes the returned credential to stdout. `store`/`erase` are no-ops
     (nothing is persisted — the point of per-call).
3. Start `responder.py` on the host in the background; record its PID.
4. Mount the temp dir (socket + `forward.py`) into the container at its host path
   (paths already mirror, so the socket is reachable at the same path both sides).
5. Configure in-container git via `GIT_CONFIG_*` to use `credential.helper=!python3
   <dir>/forward.py`, resetting any inherited helper and forcing
   `useHttpPath=false` (same reasons mod 061 documented).
6. Dispatch **without `exec`** (a temp dir + a background process must be cleaned up):
   run docex as a child, then kill the responder and `rm -rf` the dir; `trap` on
   `EXIT INT TERM` as backstop. (Extends 061's non-exec cleanup dispatch.)

Each in-container `git fetch`/`push` now invokes `forward.py` → socket →
`responder.py` → host `git credential fill` → **fresh** short-lived token. A
multi-minute `check` before the op no longer matters: the token is minted at the
moment of the op, not up front.

## Behavior contract (unchanged from 061 except the freshness guarantee)

- **Opt-in, environment-driven** (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, set by the
  environment, never the repo). Signal unset ⇒ the shim is byte-for-byte the static
  path — the hard no-regression requirement.
- **Scoped to `https` `origin`**; ssh / remoteless fall through unchanged.
- **Fail-open**: if `git credential fill` yields nothing, the responder returns
  nothing, git falls through / fails cleanly — the shim never hangs or hard-fails.
- **Short-lived, off the container env, cleaned up on exit.** Nothing is baked into
  a persisted store file anymore; credentials exist only transiently in the socket
  round-trip. The socket + scripts live in a mode-700 dir owned by the run uid
  (same threat surface as 061's mounted cred file), removed on exit.

## New dependency (the one real cost)

Passthrough mode now requires **`python3` on the host** (for `responder.py`) in
addition to the container's python3 (for `forward.py`, always present — docex is a
python image). Mod 061 needed only bash + git on the host. This is acceptable and
bounded: passthrough is opt-in and set by the *environment*, and every environment
that enables it (the Periscope dev-box image) ships python3. Documented as a
passthrough-mode prerequisite. (A bash-only responder via `socat`/`nc -lU` was
considered and rejected as more fragile and itself a non-universal dependency.)

## Scope of change (aligned artifacts, per docex_process)

- **Doctrine prose (rule of record) — requires operator OK before editing:**
  - `doctrine/infrastructure/credentials.md` § *Git Host Credentials* — change
    "passes the resolved, short-lived credential into the container" to the per-call
    framing (fresh credential per in-container network op). **Proposed wording is in
    §"Proposed doctrine delta" below for approval.**
  - `doctrine/infrastructure/docex.md` — 061 already softened the shim-immutability
    line to "additive, backward-compatible"; verify it still reads correctly with
    this change. Likely no edit; touch only if it references the store mechanism.
- **docex design docs:** `docex/plans/core/masterplan.md` — *The Shim* and
  *Credentials & Ambient Host State* sections (replace the store-injection
  description with per-call forwarding).
- **docex code:** `docex/bin/docex` (the shim — the only code change).
- **Changelog:** doctrine-wide `CHANGELOG.md` `[Unreleased]` (Changed) — no version
  bump here; the cut is a campaign-end step (this rides the lifecycle-fix campaign).
- **Tests:** no `src/` change, so the pytest suite is untouched (sanity: it still
  passes). The shim is bash with no pytest coverage (per docex_process). The
  responder↔forwarder round-trip is smoke-tested locally against a stub `git
  credential fill` during implementation; the real end-to-end box proof is a
  campaign/rollout verification.

No transfer-table change. No docex **image** change.

## Proposed doctrine delta (for operator approval)

`doctrine/infrastructure/credentials.md § Git Host Credentials`, final sentence —
from:

> For these machines `docex` resolves the git credential **on the host** — through
> git's own credential machinery (`git credential fill`), so it stays agnostic to
> which helper is configured — and passes the resolved, short-lived credential into
> the container.

to:

> For these machines `docex` brokers git credentials **on the host** — through git's
> own credential machinery (`git credential fill`), so it stays agnostic to which
> helper is configured — and makes that resolution available to the in-container git
> **per network operation**, so each fetch/push obtains a *fresh* short-lived
> credential rather than a single one captured up front. This keeps long-running
> commands (e.g. `merge`, whose defensive `check` may run for minutes before its
> `push`) from failing on a credential that expired between capture and use.

## Verification

- **pytest sanity:** `docex/src` untouched ⇒ `python -m pytest tests/unit -q`
  unaffected.
- **Local round-trip smoke:** start `responder.py` against a stub `git credential
  fill`, run `forward.py` against the socket, assert the stubbed creds round-trip.
- **Box proof (campaign/rollout):** deploy the new shim to a dev box exporting
  `DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, run a real `docex merge` on a registered
  tactical — it now completes fetch **and** push after a full `check`.
- **Laptop proof:** signal unset ⇒ static-credential git ops unchanged.

## Out of scope / deferred

- Multi-remote resolution (still `origin`-only — every pipeline network op uses it).
- A bash-only (dependency-free) responder — deferred unless python3-on-host proves a
  real burden for some passthrough environment.
- Retiring 061's static-`store` path for the *non*-passthrough case — untouched;
  only the passthrough block is replaced.
