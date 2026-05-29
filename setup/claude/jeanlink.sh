#!/usr/bin/env bash
#
# jeanlink.sh — Ensure ~/.claude/CLAUDE.md loads jean's JEAN.md via @file directive.
#
# Behavior:
#   - Guarantees the line `@./jean_baudrillard/JEAN.md` is present in CLAUDE.md.
#   - If CLAUDE.md doesn't exist, it's created containing only the directive.
#   - If CLAUDE.md exists but lacks the directive, it's prepended to the top so
#     doctrine loads before any user-authored content.
#   - Any other existing content is preserved verbatim.
#   - Safe to run multiple times.
#
# This script can be run from anywhere; it only requires that the jean
# directory itself lives at ~/.claude/jean_baudrillard.

set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
JEAN_DIR="${CLAUDE_DIR}/jean_baudrillard"
JEAN_FILE="${JEAN_DIR}/JEAN.md"
TARGET_FILE="${CLAUDE_DIR}/CLAUDE.md"
DIRECTIVE="@./jean_baudrillard/JEAN.md"

# --- 1. Sanity checks ---------------------------------------------------------

if [[ ! -d "${JEAN_DIR}" ]]; then
  echo "Error: expected jean directory at ${JEAN_DIR}, but none found." >&2
  echo "Clone or move the jean directory to ${JEAN_DIR} and re-run." >&2
  exit 1
fi

if [[ ! -f "${JEAN_FILE}" ]]; then
  echo "Error: ${JEAN_FILE} does not exist." >&2
  echo "The @file directive would point at a nonexistent file." >&2
  exit 1
fi

mkdir -p "${CLAUDE_DIR}"

# --- 2. Ensure directive is present ------------------------------------------

if [[ -f "${TARGET_FILE}" ]] && grep -Fxq "${DIRECTIVE}" "${TARGET_FILE}"; then
  echo "✓ ${TARGET_FILE} already loads JEAN.md."
  exit 0
fi

if [[ -f "${TARGET_FILE}" ]]; then
  backup="${TARGET_FILE}.backup.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET_FILE}" "${backup}"
  echo "Backed up previous CLAUDE.md to ${backup}."

  tmp="$(mktemp)"
  {
    echo "${DIRECTIVE}"
    cat "${TARGET_FILE}"
  } > "${tmp}"
  mv "${tmp}" "${TARGET_FILE}"
  echo "✓ Prepended @JEAN.md directive to ${TARGET_FILE}."
else
  echo "${DIRECTIVE}" > "${TARGET_FILE}"
  echo "✓ Created ${TARGET_FILE} with @JEAN.md directive."
fi
