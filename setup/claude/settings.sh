#!/usr/bin/env bash
#
# setup.sh — Merge jean's settings.json into ~/.claude/settings.json.
#
# Behavior:
#   - jean's settings are the source of truth for keys it defines.
#   - Existing keys in ~/.claude/settings.json that jean doesn't touch are preserved.
#   - Arrays (e.g. permissions.allow) are unioned, not replaced.
#   - Safe to run multiple times.
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

# --- 2. Merge -----------------------------------------------------------------

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

# --- 3. Idempotency: only write if the result actually differs ----------------

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