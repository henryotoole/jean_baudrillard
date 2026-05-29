#!/usr/bin/env bash
#
# skills.sh — Copy jean's skills folders into ~/.claude/skills, overwriting any
# existing copies on each run.
#
# Behavior:
#   - Each subdirectory of ~/.claude/jean_baudrillard/skills is mirrored into
#     ~/.claude/skills/<name>, replacing whatever was there.
#   - Skill folders in ~/.claude/skills that are not in jean's skills directory
#     are left untouched.
#   - Safe to run multiple times.
#
# This script can be run from anywhere; it only requires that the jean
# directory itself lives at ~/.claude/jean_baudrillard.

set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
JEAN_DIR="${CLAUDE_DIR}/jean_baudrillard"
JEAN_SKILLS="${JEAN_DIR}/skills"
TARGET_DIR="${CLAUDE_DIR}/skills"

# --- 1. Sanity checks ---------------------------------------------------------

if [[ ! -d "${JEAN_DIR}" ]]; then
  echo "Error: expected jean directory at ${JEAN_DIR}, but none found." >&2
  echo "Clone or move the jean directory to ${JEAN_DIR} and re-run." >&2
  exit 1
fi

if [[ ! -d "${JEAN_SKILLS}" ]]; then
  echo "Error: ${JEAN_SKILLS} does not exist." >&2
  echo "Create a skills directory inside the jean directory before running setup." >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"

# --- 2. Copy each skill folder ------------------------------------------------

shopt -s nullglob
copied=0
for skill_path in "${JEAN_SKILLS}"/*/; do
  skill_name="$(basename "${skill_path}")"
  dest="${TARGET_DIR}/${skill_name}"
  rm -rf "${dest}"
  cp -R "${skill_path%/}" "${dest}"
  echo "✓ Installed skill: ${skill_name}"
  copied=$((copied + 1))
done
shopt -u nullglob

if [[ "${copied}" -eq 0 ]]; then
  echo "No skill folders found in ${JEAN_SKILLS}; nothing to install."
fi
