#!/usr/bin/env bash
#
# setup.sh — Merge jean's settings.json into ~/.claude/settings.json.
#
# Behavior:
#   - jean's settings are the source of truth for keys it defines.
#   - Existing keys in ~/.claude/settings.json that jean doesn't touch are preserved.
#   - Arrays (e.g. permissions.allow) are unioned, not replaced.
#   - Installs & enables the jean plugin via the official `claude plugin` CLI:
#     it adds the local-only "jean-local" marketplace from this on-disk repo,
#     then installs the plugin (which copies it into the version-keyed plugin
#     cache and enables it). The CLI owns the enabledPlugins / extraKnownMarket-
#     places settings keys, so they are NOT hand-merged here.
#   - Safe to run multiple times (the merge and both CLI calls are idempotent).
#
# This script can be run from anywhere; it only requires that the jean
# directory itself lives at ~/.claude/jean_baudrillard.

set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
JEAN_DIR="${CLAUDE_DIR}/jean_baudrillard"
JEAN_SETTINGS="${JEAN_DIR}/setup/claude/settings.json"
TARGET_FILE="${CLAUDE_DIR}/settings.json"

# --- 1. Sanity checks ---------------------------------------------------------

if [[ ! -d "${JEAN_DIR}" ]]; then
  echo "Error: expected jean directory at ${JEAN_DIR}, but none found." >&2
  echo "Clone or move the jean directory to ${JEAN_DIR} and re-run." >&2
  exit 1
fi

if [[ ! -f "${JEAN_SETTINGS}" ]]; then
  echo "Error: ${JEAN_SETTINGS} does not exist." >&2
  echo "Create a settings.json inside the jean directory before running setup." >&2
  exit 1
fi

if ! jq empty "${JEAN_SETTINGS}" >/dev/null 2>&1; then
  echo "Error: ${JEAN_SETTINGS} is not valid JSON." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed." >&2
  echo "  macOS:  brew install jq" >&2
  echo "  Debian: sudo apt install jq" >&2
  exit 1
fi

mkdir -p "${CLAUDE_DIR}"

# --- 2. Ensure the jean plugin is installed & enabled -------------------------

# The resident-stratum loader ships as a SessionStart hook inside the jean
# plugin. Enabling it requires the plugin to be INSTALLED (copied into the
# version-keyed plugin cache) — declaring settings keys alone does not trigger
# that. So we drive the official, idempotent CLI: `marketplace add` registers
# the local-only jean-local marketplace against this repo (writing
# extraKnownMarketplaces), and `install` caches + enables the plugin (writing
# enabledPlugins). Both are safe to re-run. The cache is keyed by plugin.json
# version, so each version bump yields an independent snapshot.
#
# Runs before the settings merge so the merge's "already up to date" early-exit
# can never skip it.
if command -v claude >/dev/null 2>&1; then
  claude plugin marketplace add "${JEAN_DIR}" \
    || echo "Warning: 'claude plugin marketplace add' failed; the plugin may not load." >&2
  claude plugin install "jean-baudrillard@jean-local" \
    || echo "Warning: 'claude plugin install' failed; the plugin may not load." >&2
else
  echo "Warning: 'claude' CLI not on PATH; skipping plugin install." >&2
  echo "  Run later: claude plugin marketplace add \"${JEAN_DIR}\" && claude plugin install jean-baudrillard@jean-local" >&2
fi

# --- 3. Merge -----------------------------------------------------------------

# Recursive merge: jean's values win on scalar conflicts; arrays are unioned and
# de-duplicated; objects are merged key-by-key all the way down.
MERGE_FILTER='
  def deepmerge(a; b):
    if (a | type) == "object" and (b | type) == "object" then
      reduce ((a + b) | keys_unsorted[]) as $k
        ({}; .[$k] = deepmerge(a[$k]; b[$k]))
    elif (a | type) == "array" and (b | type) == "array" then
      (a + b) | unique
    elif b == null then a
    else b
    end;
  deepmerge($existing; $jean_arr[0])
'

if [[ -f "${TARGET_FILE}" ]]; then
  if ! jq empty "${TARGET_FILE}" >/dev/null 2>&1; then
    backup="${TARGET_FILE}.invalid.$(date +%Y%m%d%H%M%S)"
    echo "Existing ${TARGET_FILE} isn't valid JSON; moving it to ${backup}." >&2
    mv "${TARGET_FILE}" "${backup}"
    existing_json='{}'
  else
    existing_json="$(cat "${TARGET_FILE}")"
  fi
else
  existing_json='{}'
fi

merged="$(jq -n \
  --argjson existing "${existing_json}" \
  --slurpfile jean_arr "${JEAN_SETTINGS}" \
  "${MERGE_FILTER}")"

# --- 4. Idempotency: only write if the result actually differs ----------------

if [[ -f "${TARGET_FILE}" ]] && \
   diff <(jq -S . "${TARGET_FILE}") <(echo "${merged}" | jq -S .) >/dev/null 2>&1; then
  echo "✓ ${TARGET_FILE} already up to date."
  exit 0
fi

if [[ -f "${TARGET_FILE}" ]]; then
  backup="${TARGET_FILE}.backup.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET_FILE}" "${backup}"
  echo "Backed up previous settings to ${backup}."
fi

echo "${merged}" | jq . > "${TARGET_FILE}"
echo "✓ Merged jean settings into ${TARGET_FILE}."