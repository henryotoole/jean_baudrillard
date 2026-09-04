---
id: 0006
title: host_brokered_git_credentials
status: accepted
date: 2026-09-04
supersedes: []
superseded-by: []
tags: [credentials, git, security]
---

## Context

`docex` runs git inside its container. The static credential mounts (`~/.gitconfig`,
`~/.ssh`, an ssh-agent socket) cover git auth that is a *file* or an *agent key*. They do
**not** cover an environment whose git auth is brokered by a `credential.helper` that talks
to host-local state — a helper binary or a socket that does not exist inside the container.
Such helpers also mint short-lived tokens (hard-capped around an hour): a credential
resolved once and copied in could expire mid-command, and a long command like `merge` (whose
defensive `check` may run for minutes before its `push`) would then fail with no way to
re-broker from inside the container.

## Decision

Add an **opt-in, environment-signaled** path (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, never set
by the project repo) that forwards **each** in-container `git credential` request back out to
the host's own `git credential fill`, so every fetch/push mints a **fresh** short-lived
credential. The shim writes a host-side `responder.py` (binds a Unix socket, pipes each
request through `git credential fill`) and an in-container `forward.py` (git's
`credential.helper`, a transparent pipe; `store`/`erase` are no-ops), mounts the socket in,
and points in-container git at it — forcing `useHttpPath=true` on both sides so a path-scoped
host helper can serve per-repository, and resetting any inherited helper.

## Consequences

- Long commands no longer fail on a credential that expired between capture and use.
- Because a cleanup trap must fire, the shim **does not `exec`** when passthrough is staged
  (it runs docex as a child, then kills the responder and removes the temp dir). For the
  same reason, `merge --detach` is **refused** under active passthrough — a detached job
  would outlive the responder.
- The path is scoped to `https` origins, **fails open** to the static behavior when nothing
  resolves, is a complete no-op when the signal is unset, and requires `python3` on the host
  for the responder. Pairs with
  [`credentials.md § Git Host Credentials`](../../../../doctrine/infrastructure/credentials.md#git-host-credentials);
  mechanism in [`../specifics/the_shim.md`](../specifics/the_shim.md).
