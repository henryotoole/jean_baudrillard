# Mod 061 — Implementation steps

Target: the feature branch `feat/host-resolved-git-credentials` off doctrine
`main`. No version cut (proven-candidate endpoint); the operator publishes.

## 1. Shim — `docex/bin/docex`

Add an **opt-in, additive** block. Default path (signal unset) must be unchanged.

Place the new block **after** the existing static credential mounts
(`~/.gitconfig`, `~/.ssh`) and the `RUN_FLAGS`/ssh-agent setup, just before the
final `exec docker run`, so it composes with — and takes precedence over — the
static config already mounted.

Logic, gated on `[[ -n "${DOCEX_GIT_CREDENTIAL_PASSTHROUGH:-}" ]]`:

1. Read `origin`: `git -C "$PROJECT_ROOT" remote get-url origin` (tolerate
   absence/non-zero → skip).
2. Proceed only if the URL is `https://*` (skip ssh / other).
3. Resolve on the host, non-interactively:
   ```
   GIT_TERMINAL_PROMPT=0 printf 'url=%s\n\n' "$url" \
     | git -C "$PROJECT_ROOT" credential fill
   ```
   Parse `protocol`, `host`, `username`, `password` from the output. If any of
   username/password is empty → skip (fail-open: inject nothing).
4. Write a host temp file (mode 600), single line in git-`store` format:
   `<protocol>://<username>:<password>@<host>`. Use `umask 077` / `mktemp` so the
   file is never world/group readable. `trap 'rm -f "$credfile"' EXIT`.
5. Mount it read-only at its host path and configure in-container git to use it,
   resetting any inherited helper first so a broken in-container helper (e.g. the
   box's own `credential.helper`, visible via mounted `~/.gitconfig`) is never
   invoked:
   ```
   MOUNTS+=(-v "$credfile:$credfile:ro")
   RUN_FLAGS+=(
     -e GIT_CONFIG_COUNT=2
     -e GIT_CONFIG_KEY_0=credential.helper -e GIT_CONFIG_VALUE_0=
     -e GIT_CONFIG_KEY_1=credential.helper -e "GIT_CONFIG_VALUE_1=store --file=$credfile"
   )
   ```
   (`GIT_CONFIG_*` env config is applied after the config files, so the empty
   reset clears file-level helpers and the `store` entry is the only one left.)

Notes:
- Keep `set -euo pipefail` safe: guard every git call with `|| true` where a
  non-zero exit is an expected "skip" condition, and capture into locals.
- Do **not** echo the token. A short stderr note that host-resolve engaged (no
  secret) is fine for operator diagnostics.

## 2. Doctrine prose

- `doctrine/infrastructure/credentials.md` § *Git Host Credentials*: generalize.
  Keep the static key/agent sentence as the default; add that where the host is
  configured with a git **credential helper**, docex resolves the credential on
  the host (via git's own credential machinery) and passes it into the container
  — the general statement, no Periscope mention.
- `doctrine/infrastructure/docex.md`: adjust the "the shim itself never changes
  between docex versions" sentence to "the shim is version-independent; it may
  gain additive, backward-compatible capabilities, picked up by re-running
  `docex_install.sh`." Preserve the surrounding upgrade-story wording.

## 3. docex design docs — `docex/plans/core/masterplan.md`

- *The Shim*: add the opt-in host-resolve responsibility; reconcile the
  "never changes between versions" line the same way as the doctrine.
- *Credentials & Ambient Host State* table: add the host-resolved git-credential
  case (source = host `git credential fill`; used by `merge`/`check`/`rollback`
  when `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set).

## 4. Changelog

Add an entry under the existing `## [Unreleased]` section (Added) describing the
opt-in host-resolved git-credential passthrough. No version bump.

## 5. Verification (no pytest changes)

- Confirm `src/` is untouched and the existing suite is unaffected:
  `cd docex && python -m pytest tests/unit -q` (sanity; should be unaffected).
- Box proof: deploy the new shim to `lead_finder` on the Johnny Dev box, ensure
  the box exports `DOCEX_GIT_CREDENTIAL_PASSTHROUGH=1`, run a real `docex merge`.
- Laptop proof: with the signal unset, run a docex git-network command against a
  repo using static credentials; confirm unchanged behavior.
