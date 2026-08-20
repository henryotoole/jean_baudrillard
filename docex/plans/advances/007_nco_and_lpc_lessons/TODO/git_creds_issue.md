# Doctrine change — `docex merge` cannot authenticate git on a dev box

**Status:** APPLIED in mod 136, shipped in doctrine **2.0.1**. The shim path-preservation
fix (gates 1 + 2) and separate fault #1 (`check` warns where `merge` errors) were both
fixed. Separate fault #2 (intermittent host-push `remote: Repository not found`) remains
open. Original investigation record preserved below.
**Investigated:** 2026-08-11, against doctrine/docex **2.0.0**.
**Recurrence:** this bug has survived **1.4.3 → 1.4.4 → 2.0.0**.

---

## Symptom

On a Periscope dev box, `./bin/docex merge` dies at its first network operation:

```
docex: brokering per-call git credentials via the host for https://github.com/luxedo-tacticals/<name>.git
fatal: could not read Username for 'https://github.com': No such device or address
error: 'git fetch origin' exited 128.
exit=128
```

Plain host git against the same remote works, which is what makes it look mysterious.
Nothing is left half-done — merge aborts before the rebase, so it is cleanly retry-able.

## Root cause

**The docex shim strips the repo path out of the git credential request, and a
path-scoped credential helper cannot authorize a request that does not name a repo.**

`bin/docex` (~line 224) injects into the docex container:

```
-e GIT_CONFIG_KEY_2=credential.useHttpPath -e GIT_CONFIG_VALUE_2=false
```

With `useHttpPath=false`, git sends the helper only `protocol=https` + `host=github.com` —
**no `path=`**. The shim's `forward.py` relays that pathless request to the host's real
helper, which on a dev box is `periscope-git-credential`. That broker's entire job is to
confirm *which repo* is being requested belongs to the box principal's department, so with
no path it sees the repo as literally `github.com` and fails closed. Git gets nothing back.

Confirmed at three layers:

| Layer | Evidence |
| --- | --- |
| Config | Runner container has `credential.usehttppath = true` (so **host** git works); the shim forces `false` **inside the container** |
| Runner log | `IPC request failed: repo 'github.com' is not a tactical of department 1` — the broker receiving the host, not the repo |
| Experiment | `false` → helper gets no `path=`, no credential; `true` → `path=` arrives, credential issued |

### Why the line exists, and why the reason expired

Not arbitrary. **Mod 061** resolved the credential once on the host and baked a *static,
pathless `store` file* into the container; a `store` entry is keyed pathlessly, so forcing
`useHttpPath=false` made the container's lookups match **that docex-written store**.
Correct for that model.

**Mod 068** replaced it with per-call forwarding to the host's own credential machinery —
and carried the line across verbatim, citing *"same reasons as mod 061"*. The premise was
gone: the request now reaches the host's **real** helper, which may be path-scoped, and
stripping the path destroys information that helper needs.

Note the tension with mod 068's own stated goal — *"docex stays agnostic to the host's
helper."* Forcing `useHttpPath` is docex imposing policy on a helper it claims to be
agnostic about.

Mod 061's problem statement is *this exact bug*, verbatim: *"`docex merge` on a Periscope
box dies at its first network op with `fatal: could not read Username`… (exit 128)."* So
061 was the fix attempt, 068 revised the mechanism, and **both carried the line forward** —
which is why it keeps reproducing.

## Two gates, not one

The path can be stripped in **two** places, and both must carry it:

| Gate | Where | Governed by |
| --- | --- | --- |
| 1 | container git → `forward.py` | the shim's injected `credential.useHttpPath` (line 224) |
| 2 | `responder.py` → `git -C $PROJECT_ROOT credential fill` → real helper | the **host's** git config |

Gate 2 is real — git normalizes the *incoming* request against the host's config before
any helper sees it:

```
host useHttpPath=unset -> HELPER SAW: protocol=https / host=github.com          # stripped
host useHttpPath=true  -> HELPER SAW: protocol=https / host=github.com / path=… # survives
```

On the dev box gate 2 is **already `true`** (runner container's `/etc/gitconfig`), so
fixing gate 1 is sufficient there.

## Two things that do NOT work

- **Omitting the setting.** Git's built-in default for `credential.useHttpPath` is
  **`false`**, so removing the line behaves exactly as today.
- **Relying on the container inheriting the host's config.** The shim mounts
  **`~/.gitconfig` only** (`bin/docex:75`), never `/etc/gitconfig` — and on the box the
  setting lives in `--system` (`/etc/gitconfig`); `~/.gitconfig` holds only the git
  identity. The container would inherit nothing and fall back to `false`.

An **explicit `true`** is required.

---

## The change

All of it is in one doctrine-owned file: **`docex/bin/docex`**, copied into each project by
`docex_install.sh:50`. Note `responder.py` and `forward.py` are **heredocs inside that same
file**, not standalone files.

### Required

| # | Where | Change |
| --- | --- | --- |
| 1 | `bin/docex:224` | `GIT_CONFIG_VALUE_2=false` → **`true`** |
| 2 | `bin/docex:219` | Rewrite the comment — it justifies the line with mod 061's model, which no longer exists |
| 3 | `docex/test_projects/{elastic,fixed}/bin/docex` | Byte-identical fixtures; must move with the canonical shim |

Change 1 is the whole fix.

### Recommended (hardening)

| # | Where | Change |
| --- | --- | --- |
| 4 | `bin/docex:177`, inside the `responder.py` heredoc | `["git", "-C", project_root, "credential", "fill"]` → add `-c credential.useHttpPath=true` |

Makes both gates agree by construction instead of depending on host config, so a future
passthrough environment cannot silently re-break. Trade-off: overrides a host that
deliberately wants pathless matching (no such host is known to exist).

### Docs that currently assert the wrong thing

| # | File | Issue |
| --- | --- | --- |
| 5 | `docex/plans/core/masterplan.md` § The Shim | Documents *"forcing `useHttpPath=false`"* as design of record |
| 6 | `doctrine/infrastructure/credentials.md` § Git Host Credentials | Says docex "stays agnostic to which helper is configured" — should state that **path-scoped** helpers are supported, since that is the capability being restored |

### Test

| # | What |
| --- | --- |
| 7 | A regression test asserting the path reaches the helper. `docex/tests/unit/test_shim_exit_code.py` covers exit codes only — **nothing tests credential content**, which is why this survived three versions. |

### Process

Do it as a **docex mod**, bump the docex version, and re-run `docex_install.sh` per
project. Otherwise the old shim persists silently — a likely reason hand-patching has felt
like it "keeps coming back."

---

## Blast radius

Smaller than "edit the shared shim" sounds:

- The line is inside the `if [[ -n "${DOCEX_GIT_CREDENTIAL_PASSTHROUGH:-}" ]]` block
  (`bin/docex` 136–229). Environments that don't set the flag never execute it; the static
  key/agent path is untouched.
- **Exactly one thing sets the flag:** `periscope/runner/Dockerfile`
  (`ENV DOCEX_GIT_CREDENTIAL_PASSTHROUGH=1`). Verified unset on the operator dev machine
  and on the box *host*; set only inside the runner container.
- The pathless store the line protected was docex's own, and mod 068 deleted it.

Net: a **doctrine-repo change with a Periscope-only blast radius** — and only Periscope can
validate it, which is plausibly why it persisted across versions.

## Verification already done

**End-to-end on a real dev box** (box 4), inside `periscope-runner` where the shim actually
runs, using the forwarder extracted from the box's own shim, against the registered
tactical `stack_test_1`. Read-only (`git ls-remote`; nothing fetched, pushed or mutated):

```
host-side (runner container) useHttpPath: true
host-side helper: /opt/periscope/runner-venv/bin/periscope-git-credential

useHttpPath=false -> AUTH-FAIL      # today's shim
useHttpPath=true  -> AUTH-OK        # the fix
```

The runner log showed exactly one broker rejection, for the `false` case only
(`repo 'github.com' is not a tactical of department 1`), and none for `true`, which minted
a token. Real broker, real GitHub App, real network.

**The broker fails closed**, which is the safe direction —
`git_broker_service.py:85–91` requires an exact name match and raises `AuthorizationError`
otherwise. Pathless requests have been *denied*, never over-granted with a host-wide
credential. The failure mode has been availability, not a security hole.

**Not verified:** the *push* half of `merge`. Same credential obtained the same way, so
risk is low, but only the fetch path was proven.

## Reproducing it locally (no AWS / GitHub / Periscope / dev box)

Runs the shim's own forwarder against the real docex image with a path-scoped
helper stand-in. ~10 seconds.

```bash
W=$(mktemp -d /tmp/gitcred.XXXXXX); cd "$W"
# CRITICAL: isolate from the real machine's git config. Without this the machine's
# own credential helper answers and prints a REAL token to the terminal.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

mkdir proj && git -C proj init -q
git -C proj remote add origin https://github.com/luxedo-tacticals/some_tactical.git
cat > helper.sh <<EOF
#!/bin/sh
{ echo "HELPER SAW:"; sed 's/^/    /'; } > "$W/log"
EOF
chmod +x helper.sh
git -C proj config credential.helper "!$W/helper.sh"
git -C proj config credential.usehttppath true      # gate 2

# Extract the shim's own responder.py / forward.py into "$W/cd", then:
#   python3 "$W/cd/responder.py" "$W/cd/cred.sock" "$W/proj" &
# and run the docex image with the shim's exact GIT_CONFIG_* env, flipping
# GIT_CONFIG_VALUE_2 between false and true:
#   -e GIT_CONFIG_COUNT=3
#   -e GIT_CONFIG_KEY_0=credential.helper -e GIT_CONFIG_VALUE_0=
#   -e GIT_CONFIG_KEY_1=credential.helper -e "GIT_CONFIG_VALUE_1=!python3 <cd>/forward.py <sock>"
#   -e GIT_CONFIG_KEY_2=credential.useHttpPath -e GIT_CONFIG_VALUE_2=<false|true>
# doing:  printf 'protocol=https\nhost=github.com\npath=owner/repo.git\n\n' | git credential fill
```

Expected: `false` → helper sees no `path=`, no credential. `true` → `path=` arrives,
credential issued.

> A complete, runnable version lives in the CRIMBAS repo at
> `plans/advances/001_post_doctrine_debug/todo/repro/004_gitcred_repro.sh` (it extracts the
> heredocs automatically). Note the AF_UNIX socket path limit (~108 chars) — keep the work
> dir short, e.g. under `/tmp`.

---

## Separate faults — NOT fixed by the above

1. **`check` warns where `merge` errors on the identical fetch.** `check.py:719–725`
   downgrades it to `warning: 'git fetch origin' exited …; continuing with potentially
   stale origin/main`, while `merge.py:70–73` returns the error. So `check` reports **9/9
   gates green** on a box where the next pipeline step cannot run, and prints first-release
   advice ("`docex merge` will seed origin/main") describing a step that cannot happen.
   Arguably the more valuable fix — it is what let the failure land mid-pipeline instead of
   at the gate.
2. **Intermittent `remote: Repository not found`** on *host* pushes, which already carry
   the path — a different fault in the broker or token propagation. Two pushes needed an
   immediate retry during the 2026-08-11 run.

---

*Filename note: this describes a fix against doctrine **2.0.0** (current). The `1.7.1` in
the filename predates that — rename if it was not deliberate.*
