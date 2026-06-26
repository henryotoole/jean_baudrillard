# Mod 061 — Host-resolved git credential passthrough

## Problem

`docex` runs all git operations via `SubprocessGitClient`, i.e. by shelling out
to **git inside the docex container**. For authentication it relies entirely on
the shim mirroring the operator's **static** host credential files into the
container — `~/.gitconfig`, `~/.ssh`, and a forwarded `ssh-agent`. On a normal
operator machine that is sufficient: in-container git inherits the operator's
keys/agent and network ops (`fetch`/`push` during `merge`, the worktree fetch in
`check`, `rollback`'s tag fetch) just work.

This breaks in any environment where git authentication is **brokered through a
credential helper** rather than stored as files — most concretely a Periscope
dev box, whose git access is minted on demand by a `credential.helper` that talks
to a local daemon over a Unix socket. Three pieces of that mechanism are absent
inside the docex container and cannot be cheaply mirrored:

1. the helper program itself (a host binary / venv entry point, not in the image),
2. whatever transport it needs (e.g. a Unix socket), and
3. even the config that *names* the helper, when it lives in the host's **system**
   gitconfig (`/etc/gitconfig`) — the shim mirrors `~/.gitconfig` only.

The observed failure: `docex merge` on a Periscope box dies at its first network
op with `fatal: could not read Username for 'https://github.com/...'` (exit 128).
`check` passes because it never reaches the network. The formal CI/CD pipeline is
therefore unusable on a box without a manual host-git workaround.

## Design intent

Add a **general** capability to docex: when an environment declares it, the shim
resolves the project's git credential **on the host** — using git's own
credential machinery, whatever it is — and injects the resolved credential into
the container as a short-lived, in-memory credential. In-container git then
fetches/pushes with no helper and no socket needed.

Two principles make this the right shape:

- **It is not Periscope-specific.** docex learns nothing about runners, sockets,
  or Periscope. It learns only "git credentials may be resolved on the host via
  `git credential fill`, the standard git command that drives whatever helper the
  host has configured." Any brokered-credential environment (corporate token
  brokers, `git-credential-manager`, AWS CodeCommit's helper, …) benefits
  identically. The environment supplies the values; docex supplies the capability.
- **It extends the shim's existing philosophy.** The shim already passes host
  credentials into the container; today it does so for *static files*. This adds
  the one category it cannot mirror as a file — a *helper-resolved* credential —
  by resolving it on the host (where the helper actually works) and passing the
  result in.

Only the credential *resolution* happens on the host. docex's in-container git
and all of its merge/release orchestration are unchanged — this is deliberately
the smallest seam that closes the gap, and keeps the riskiest docex code
untouched.

## Behavior contract

- **Opt-in, environment-driven.** The new path activates only when the
  environment exports an opt-in signal (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`). The
  signal is set by the *environment* (e.g. a dev box's image), never by the
  project repo — the same repo must behave identically on a laptop and a box.
- **No regression to the static path.** With the signal unset (every existing
  operator machine), the shim is byte-for-byte equivalent to today: it mirrors
  `~/.gitconfig`/`~/.ssh`, forwards `ssh-agent`, and changes nothing. This is the
  hard requirement.
- **Scoped to https `origin`.** Host-resolve applies only when the project's
  `origin` remote is an `https://` URL (the only case a credential helper serves).
  SSH remotes and remoteless projects (e.g. the test projects) fall straight
  through to the existing behavior.
- **Fail-open to the old behavior.** If resolution yields nothing (no helper, no
  creds, non-interactive prompt suppressed), the shim injects nothing and docex
  proceeds exactly as it would today — it does not hang and does not hard-fail
  the invocation in the shim.
- **Short-lived, off the process env.** The resolved credential is written to a
  mode-600 file inside a mode-700 host temp dir, mounted read-write (git's `store`
  helper rewrites it on a successful auth), consumed via git's `store` helper, and
  removed when docex exits. To make that removal real, the shim does **not** `exec`
  when a credential is staged — an `exec` replaces the shell and the cleanup trap
  never fires — so it runs docex as a child and removes the dir afterward (trap as
  backstop). It is not placed on the container's env (so it is not exposed via
  `docker inspect`).

## Scope of change (artifacts)

Per `docex_process.md`, the aligned artifacts touched:

- **Doctrine prose (rule of record):**
  - `doctrine/infrastructure/credentials.md` § *Git Host Credentials* —
    generalize from "static key/agent only" to include host-resolved credential
    helpers.
  - `doctrine/infrastructure/docex.md` — reconcile the "the shim itself never
    changes between docex versions" statement: the shim stays *version-
    independent* but may gain *additive, backward-compatible* capabilities picked
    up by re-running `docex_install.sh`.
- **docex design docs:** `docex/plans/core/masterplan.md` — *The Shim* and
  *Credentials & Ambient Host State* sections.
- **docex code:** `docex/bin/docex` (the shim — the only code change).
- **Tests:** none added. The shim is bash and has no coverage in docex's pytest
  suite; the Python `src/` is untouched. Verification is by the two end-to-end
  proofs below.

No transfer-table change (no role/engine touched). No docex *image* change — the
in-container git already supports `GIT_CONFIG_*` injection and the built-in
`store` helper, so the image is not rebuilt for this behavior.

## Verification

- **Brokered path (Periscope box):** a real `docex merge` on a registered
  tactical (`lead_finder`) completes its fetch/push via a host-brokered token.
- **Static path (operator machine):** with the signal unset, docex's git network
  ops still authenticate via the mounted static credentials, unchanged.

## Out of scope / deferred

- Mirroring the host **system** gitconfig (`/etc/gitconfig`) into the container.
  Not needed: the host-resolve path drives the helper on the host, where system
  gitconfig is already in effect, so the in-container git never needs to see the
  helper config. Left as a possible future general improvement.
- Multi-remote resolution. `merge`/`check`/`rollback` operate against `origin`;
  resolving `origin` covers every network op the pipeline performs today.
- URL-encoding of exotic credential characters in the store-file line (GitHub App
  tokens and `x-access-token` are URL-safe). Noted as a known limitation.
