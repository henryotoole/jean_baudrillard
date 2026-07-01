# Mod 068 — Implementation steps

Implements [overview.md](./overview.md): replace the shim's resolve-**once**
static-`store` git-credential block (mod 061) with a **per-call forwarding channel**
so in-container git brokers a fresh credential on every network op.

Branch: `feat/per-call-git-credentials` (off doctrine `main`; already checked out).
Docex mods have **no operator manual-test phase** and no version bump here (the cut
is a campaign-end step). Leave changes uncommitted for the design context to review.

## Key insight that makes this simple and robust

`git credential fill` consumes exactly the same `key=value`-lines-then-blank-line
format that a credential **helper** receives on stdin for a `get`, and emits exactly
the format git expects back. So the forwarder and responder are **transparent
pipes** — no parsing anywhere. The container git's request is piped verbatim to the
host's `git credential fill`, and its output is piped verbatim back.

## 1. Shim — `docex/bin/docex`

**Replace** the existing "Host-resolved git credentials (opt-in; mod 061)" block
(currently ~lines 111–181, the `git credential fill` → temp `store` file →
`GIT_CONFIG_*` logic) with the per-call block below. Also **adjust the dispatch**
(~lines 183–209) so the credential-staged path additionally kills the responder.

Keep everything else byte-identical. The block stays gated on
`[[ -n "${DOCEX_GIT_CREDENTIAL_PASSTHROUGH:-}" ]]` and `https://*` origin; when the
signal is unset the shim is unchanged (hard no-regression requirement).

New block (place where the 061 block was — after the static mounts / ssh-agent,
before dispatch):

```bash
# Per-call brokered git credentials (opt-in; mod 068, supersedes mod 061's
# resolve-once store injection).
#
# WHY per-call: mod 061 resolved the credential ONCE at invocation and baked a
# static `store` copy into the container. Brokered tokens (GitHub App installation
# tokens) are hard-capped at ~1h, so any docex op that does long work before an
# in-container git network op (merge: a multi-minute defensive `check` before its
# fetch, and a `push` later still) could outlive the baked token — and in-container
# git can't re-broker. Instead we forward EACH in-container `git credential` request
# back out to the host's own `git credential fill`, so every fetch/push mints a
# FRESH short-lived credential. docex stays agnostic to the host's helper.
#
# Opt-in via $DOCEX_GIT_CREDENTIAL_PASSTHROUGH (set by the ENVIRONMENT, never the
# repo). Unset => this block is skipped and behavior is identical to the static path.
# Requires python3 on the host (responder) — guaranteed by any environment that sets
# the signal (the dev-box image). The in-container forwarder uses the docex image's
# python3 (always present).
if [[ -n "${DOCEX_GIT_CREDENTIAL_PASSTHROUGH:-}" ]]; then
  ORIGIN_URL="$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || true)"
  if [[ "$ORIGIN_URL" == https://* ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "docex: DOCEX_GIT_CREDENTIAL_PASSTHROUGH set but python3 not found on host; skipping per-call git credentials" >&2
    else
      CRED_DIR="$(umask 077 && mktemp -d "${TMPDIR:-/tmp}/docex-gitcred.XXXXXX")"
      CRED_SOCK="$CRED_DIR/cred.sock"
      # Backstop cleanup (see dispatch note): kill the responder + remove the dir.
      # shellcheck disable=SC2064 - expand now, at trap-set time.
      trap "[[ -n \"\${RESPONDER_PID:-}\" ]] && kill \"\$RESPONDER_PID\" 2>/dev/null; rm -rf '$CRED_DIR'" EXIT INT TERM

      # responder.py — runs on the HOST. Per connection, pipes the request through
      # the host's own `git credential fill` (fresh broker each time) and returns it.
      cat >"$CRED_DIR/responder.py" <<'PYRESP'
import os, socket, subprocess, sys

sock_path, project_root = sys.argv[1], sys.argv[2]
if os.path.exists(sock_path):
    os.unlink(sock_path)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(sock_path)
os.chmod(sock_path, 0o600)
srv.listen(8)
while True:
    try:
        conn, _ = srv.accept()
    except OSError:
        break
    with conn:
        chunks = []
        while True:
            b = conn.recv(4096)
            if not b:
                break
            chunks.append(b)
        request = b"".join(chunks)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        try:
            # Drive the host's configured credential machinery (whatever it is).
            proc = subprocess.run(
                ["git", "-C", project_root, "credential", "fill"],
                input=request, capture_output=True, env=env,
            )
            conn.sendall(proc.stdout)  # fail-open: empty on miss
        except Exception:
            pass  # fail-open: send nothing
PYRESP

      # forward.py — runs IN the container as git's credential.helper. Transparent
      # pipe: git's request on stdin -> socket -> responder -> back to stdout.
      cat >"$CRED_DIR/forward.py" <<'PYFWD'
import socket, sys

sock_path = sys.argv[1]
operation = sys.argv[2] if len(sys.argv) > 2 else ""
if operation != "get":  # store/erase are no-ops (nothing persisted)
    sys.exit(0)
request = sys.stdin.buffer.read()
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall(request)
    s.shutdown(socket.SHUT_WR)  # signal end-of-request
    chunks = []
    while True:
        b = s.recv(4096)
        if not b:
            break
        chunks.append(b)
    sys.stdout.buffer.write(b"".join(chunks))
except Exception:
    sys.exit(0)  # fail-open: no credential
PYFWD

      python3 "$CRED_DIR/responder.py" "$CRED_SOCK" "$PROJECT_ROOT" &
      RESPONDER_PID=$!
      # Bounded wait for the socket to bind (fail-open if it never does).
      for _ in $(seq 1 20); do [[ -S "$CRED_SOCK" ]] && break; sleep 0.1; done

      MOUNTS+=(-v "$CRED_DIR:$CRED_DIR")
      # git appends the operation (get/store/erase) as the final arg, so
      # forward.py sees argv = [forward.py, <sock>, <op>]. Reset any inherited
      # helper and force useHttpPath=false (same reasons as mod 061).
      RUN_FLAGS+=(
        -e GIT_CONFIG_COUNT=3
        -e GIT_CONFIG_KEY_0=credential.helper -e GIT_CONFIG_VALUE_0=
        -e GIT_CONFIG_KEY_1=credential.helper -e "GIT_CONFIG_VALUE_1=!python3 $CRED_DIR/forward.py $CRED_SOCK"
        -e GIT_CONFIG_KEY_2=credential.useHttpPath -e GIT_CONFIG_VALUE_2=false
      )
      echo "docex: brokering per-call git credentials via the host for $ORIGIN_URL" >&2
    fi
  fi
fi
```

**Dispatch adjustment** (the `if [[ -n "${CRED_DIR:-}" ]]` block): keep the non-`exec`
child-run + cleanup, but also stop the responder:

```bash
if [[ -n "${CRED_DIR:-}" ]]; then
  status=0
  docker run "${RUN_FLAGS[@]}" "${MOUNTS[@]}" "docex:$DOCEX_VERSION" "$@" || status=$?
  [[ -n "${RESPONDER_PID:-}" ]] && kill "$RESPONDER_PID" 2>/dev/null || true
  rm -rf "$CRED_DIR"
  exit "$status"
fi

exec docker run "${RUN_FLAGS[@]}" "${MOUNTS[@]}" "docex:$DOCEX_VERSION" "$@"
```

Keep `set -euo pipefail` safe: guard git calls with `|| true`; the `kill`/`rm` are
`|| true`-guarded. Do not echo any token.

## 2. Doctrine prose — `doctrine/infrastructure/credentials.md`

In § *Git Host Credentials*, replace the final sentence (operator-approved wording):

> For these machines `docex` brokers git credentials **on the host** — through git's
> own credential machinery (`git credential fill`), so it stays agnostic to which
> helper is configured — and makes that resolution available to the in-container git
> **per network operation**, so each fetch/push obtains a *fresh* short-lived
> credential rather than a single one captured up front. This keeps long-running
> commands (e.g. `merge`, whose defensive `check` may run for minutes before its
> `push`) from failing on a credential that expired between capture and use. The
> mechanism lives in the [`docex` shim](./docex.md#project-installation); see
> [`docex`'s masterplan](../../docex/plans/core/masterplan.md#the-shim) for specifics.

Check `doctrine/infrastructure/docex.md`: 061 already softened the shim-immutability
line to "additive, backward-compatible." Only touch it if it describes the *store*
mechanism specifically; otherwise leave it.

## 3. docex design docs — `docex/plans/core/masterplan.md`

- *The Shim* → *Host-resolved git credentials (opt-in)* paragraph: replace the
  store-injection description with per-call forwarding (host `responder.py` + a Unix
  socket + an in-container `forward.py` helper; fresh credential per network op).
  Note the python3-on-host prerequisite for passthrough mode, and that it remains a
  no-op / static-path-identical when the signal is unset.
- *Credentials & Ambient Host State* table: update the "Git remote auth via a host
  credential helper (opt-in)" row from "injected as a short-lived `store` entry" to
  "brokered per-op via the host's `git credential fill`."

## 4. Changelog — doctrine-wide `CHANGELOG.md`

Under `## [Unreleased]` → **Changed**: note that docex's opt-in host git-credential
passthrough now brokers a **fresh** credential per in-container network op (was a
single credential captured at invocation), fixing `docex merge` on brokered-git dev
boxes where the long defensive `check` could outlive a ~1h token (lifecycle finding
B2). No version bump (campaign-end cut).

## 5. Verification

- **pytest sanity** (no `src/` change): `cd docex && python -m pytest tests/unit -q`
  — should be unaffected.
- **Local round-trip smoke** (no docker/GitHub needed): put a stub `git` earlier on
  `PATH` whose `credential fill` echoes canned `username=x\npassword=y`, start
  `responder.py` against a temp socket, run `forward.py <sock> get` feeding a sample
  `protocol=https\nhost=github.com\n\n` on stdin, and assert the canned creds come
  back. (Throwaway check; do not commit a stub `git` into the repo. If docex has a
  bash/functional test harness, a committed shell test here is welcome; otherwise a
  reported manual round-trip is sufficient, matching mod 061's shim-testing posture.)
- Confirm the signal-unset path is byte-identical behavior (diff the static branch).

## Out of scope (do not do)

- No docex **image** change (the forwarder is a runtime-written script; the image's
  python3 + git suffice).
- No `src/docex/**` change (merge/git orchestration is unchanged).
- No transfer-table change.
- No version bump / cut (campaign-end).
- Do not touch the non-passthrough static path.
