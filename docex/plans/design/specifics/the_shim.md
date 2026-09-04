# The Shim

`./bin/docex` is a small bash script, checked into every project. Its responsibilities:

1. Read `docex_version` from `project.yml`.
2. Construct the `docker run` invocation with the full
   [mount set](../structures_and_views.md#filesystem-surface). Mounts mirror their host
   paths inside the container — the project root, the operator's HOME, and credential
   directories are visible at the same path the host sees them. This makes DooD path
   resolution agree in both directions: build contexts and bind-mount sources resolve
   consistently for compose's in-container client and the host's docker daemon (see
   [Docker-outside-of-Docker](../concepts_and_decisions.md#docker-outside-of-docker)).
   Concrete flags:
   - `--rm` so containers don't accumulate.
   - `--user "$(id -u):$(id -g)"` so writes to the project tree land operator-owned on the
     host (not root) and so `git` doesn't trip on dubious-ownership.
   - `--group-add` for the host's docker-socket gid so the non-root in-container user can
     use `/var/run/docker.sock`.
   - `-t -i` allocated **only** when the caller has an interactive terminal (both stdin and
     stdout are ttys) — needed for `docex secrets set`'s no-echo prompt; skipped for
     piped/non-interactive runs (which must use `--from-file`). Additive and
     backward-compatible: an older image tolerates the extra `-it`.
   - `-e "HOME=$HOME"` — mirror host HOME inside the container.
   - `-w "$PROJECT_ROOT"` — working directory matches the host's project path.
   - `-v "$PROJECT_ROOT:$PROJECT_ROOT"` — project tree at its host path.
   - `-v /etc/passwd:/etc/passwd:ro` and `-v /etc/group:/etc/group:ro` so `getpwuid()`
     resolves the running uid (ssh requires this).
   - `-v /var/run/docker.sock:/var/run/docker.sock` — DooD.
   - `-v "$HOME/.docker:$HOME/.docker"` — rw so docker CLI can write buildx state,
     credential cache, etc.
   - `-v "$HOME/.aws:$HOME/.aws:ro"` — elastic foundation creds.
   - `-v "$HOME/.gitconfig:$HOME/.gitconfig:ro"` and `-v "$HOME/.ssh:$HOME/.ssh:ro"` — git
     ops (`check`, `merge`).
   - `-v "$SSH_AUTH_SOCK:/ssh-agent.sock" -e "SSH_AUTH_SOCK=/ssh-agent.sock"` when an
     ssh-agent is present, so agent-only authentication setups work.
3. Pass through all CLI args.

Mounts that don't exist on the host (e.g. `~/.aws` on a fixed-only developer's box) are
skipped by the shim — docex will fail loudly inside the container if a missing mount is
actually needed by the requested command. `~/.docker` is the exception: the shim creates
it on the host if missing so the in-container docker CLI always has a writable state dir.

**Host-resolved git credentials (opt-in).** The static credential mounts above cover git
auth that is a *file* or an *agent key*. They cannot cover an environment whose git auth is
brokered by a `credential.helper` that talks to host-local state (a helper binary, a
socket) — that machinery does not exist inside the container. When the **environment** sets
`DOCEX_GIT_CREDENTIAL_PASSTHROUGH` (never the project repo), the shim forwards **each**
in-container `git credential` request back out to the host's own `git credential fill`
(git's own machinery, driving whatever helper the host has configured), so every
in-container fetch/push mints a **fresh** short-lived credential rather than reusing one
captured up front. This matters because brokered tokens are hard-capped at ~1h: a
resolve-once copy could expire during a long command (e.g. `merge`, whose defensive
`check` may run for minutes before its `push`), and in-container git cannot re-broker. The
mechanism: the shim writes two tiny helper scripts into a mode-700 host temp dir at runtime
(heredocs, not image subcommands) — a host-side `responder.py` that binds a Unix socket and
pipes each request through `git credential fill`, and an in-container `forward.py` set as
git's `credential.helper` (a transparent pipe over the socket; `store`/`erase` are no-ops
since nothing is persisted). It starts the responder in the background, mounts the temp dir
(socket + `forward.py`) into the container at its host path, and points in-container git at
`forward.py` (resetting any inherited helper and forcing `useHttpPath=true`, so the
repository **path** survives into the credential request and a path-scoped host helper —
one that authorizes per repository — can serve it; the host-side `git credential fill`
forces the same, so both gates agree by construction). So the cleanup actually runs, the
shim **does not `exec`** when this is staged (an `exec` would replace the shell and the
cleanup trap would never fire) — it runs docex as a child, then kills the responder and
removes the dir afterward. Passthrough mode requires **`python3` on the host** for the
responder (the container's python3 is always present); the path is scoped to `https`
origins, fails open to the static behavior when nothing resolves, and is a complete no-op
when the signal is unset. See
[credentials.md § Git Host Credentials](../../../../doctrine/infrastructure/credentials.md#git-host-credentials).

The shim is **version-independent** — one shim serves every `docex` version. Changes to it
are kept **additive and backward-compatible** (an image of any version tolerates a newer
shim), so it is not pinned per version. The `docex_install.sh` script in the
`jean_baudrillard` repo copies it into projects and writes the `docex_version` pin into
their `project.yml`. The same script upgrades a project from one `docex` version to
another and picks up an updated shim.

## Credentials & ambient host state

`docex` consumes credentials and host state from well-known locations. It does **not**
manage credential storage itself.

| Need | Source | Used by |
| ---- | ------ | ------- |
| Container registry push/pull | `~/.docker/config.json` | `containerize`, `release` (fixed pull side is the *target host*'s config, not the operator's), `preinfra development` (fixed — authenticates the manifest-delete probe; absent credential *declines*, never fails) |
| AWS API access | `~/.aws/credentials` (or env vars / OIDC if present) | `projinfra`, `release` (elastic), `containerize` (when ECR) |
| SSH to fixed-foundation hosts | `infra/deploy_creds/<env>` (private key) + `~/.ssh/known_hosts`; and on the target host, passwordless `sudo` for the `deploy` user | `release` (fixed); `preinfra production` (fixed); `stagetest`'s pre-step (fixed — `docker inspect` per core container, which needs the sudo because the playbook runs `become: true` and the containers are root-owned) |
| Git identity & remote push | `~/.gitconfig`, `~/.ssh/` | `merge`, `check` (worktree creation) |
| Git remote auth via a host credential helper (opt-in) | host `git credential fill` for `origin`, brokered per-op via a forwarding socket — see [The Shim](#the-shim) | `merge`, `check`, `rollback` when `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set |
| Docker daemon | `/var/run/docker.sock` | every command that touches docker |

If a required credential is missing, `docex` fails loudly with a message pointing at the
conventional location, never with a silent fallback.
