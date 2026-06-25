#!/usr/bin/env bash
#
# mcp.sh — Pre-register jean's user-scope MCP servers so their tools are live in
# the next Claude session, with no per-skill "install then restart" dance.
#
# Today that means the Playwright MCP server used by the browser-investigate
# skill. Its config is the canonical, digest-pinned JSON in
# playwright_mcp.json (this directory) — the SINGLE source of truth for the pin,
# referenced by both this script and the skill. Bump the digest there and both
# follow.
#
# Why pre-register: MCP servers, like the resident stratum, are read at SESSION
# START. Registering here does not light up tools mid-session; it ensures the
# *next* session has them. That lines up with doctrine-update, which already
# ends by telling the operator to start a fresh session — so the server boots in
# exactly that session and browser-investigate "just works" on first use.
#
# Idempotency (compare-and-replace): we compare the desired {command, args}
# against what is registered at user scope and only rewrite when they differ.
# Comparing command+args (not the whole object) ignores fields the CLI injects
# (e.g. "type") AND correctly re-registers on a digest bump, where args change.
#
# Safe to run multiple times. Degrades gracefully (warn, don't fail) when the
# `claude` CLI or Docker is absent, so setup.sh never breaks on a machine that
# installs them later.
#
# This script can be run from anywhere; it only requires that the jean
# directory itself lives at ~/.claude/jean_baudrillard.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# User-scope MCP servers live in ~/.claude.json at the HOME root — NOT inside
# ~/.claude/. (The `claude mcp add-json -s user` CLI owns the writes; we only
# read this for the compare-and-replace idempotency check.)
CLAUDE_JSON="${HOME}/.claude.json"
MCP_NAME="playwright"
MCP_JSON="${SCRIPT_DIR}/playwright_mcp.json"

# --- 1. Sanity checks ---------------------------------------------------------

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed." >&2
  exit 1
fi

if [[ ! -f "${MCP_JSON}" ]]; then
  echo "Error: ${MCP_JSON} does not exist." >&2
  echo "The canonical Playwright MCP pin is missing from the jean repo." >&2
  exit 1
fi

if ! jq empty "${MCP_JSON}" >/dev/null 2>&1; then
  echo "Error: ${MCP_JSON} is not valid JSON." >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "Warning: 'claude' CLI not on PATH; skipping ${MCP_NAME} MCP registration." >&2
  echo "  Run later: bash ${BASH_SOURCE[0]}" >&2
  exit 0
fi

# --- 2. Register / refresh the server (compare-and-replace) -------------------

# Desired and current reduced to the load-bearing fields. `claude mcp get`
# prints human-readable text, so we read the stored config straight from
# ~/.claude.json (user scope = top-level .mcpServers). `null` when absent.
desired="$(jq -S '{command, args}' "${MCP_JSON}")"
if [[ -f "${CLAUDE_JSON}" ]]; then
  current="$(jq -S --arg n "${MCP_NAME}" \
    '(.mcpServers[$n] // null) | if . == null then null else {command, args} end' \
    "${CLAUDE_JSON}" 2>/dev/null || echo null)"
else
  current="null"
fi

if [[ "${desired}" == "${current}" ]]; then
  echo "✓ ${MCP_NAME} MCP server already registered and current."
else
  # Remove any stale/old-pin entry first; add is not idempotent on a live name.
  # The remove may legitimately find nothing — don't let it abort the script.
  claude mcp remove -s user "${MCP_NAME}" >/dev/null 2>&1 || true
  if claude mcp add-json -s user "${MCP_NAME}" "$(cat "${MCP_JSON}")"; then
    echo "✓ Registered ${MCP_NAME} MCP server at user scope."
  else
    echo "Warning: failed to register ${MCP_NAME} MCP server; the browser-investigate skill may not load it." >&2
    exit 0
  fi
fi

# --- 3. Warm the image so the first browser action isn't a cold pull ----------

# Best-effort: the image pulls lazily on first use anyway. Pre-pulling here just
# spares the first `browser_navigate` a multi-hundred-MB wait. Pinned by digest,
# so this is a no-op once the layers are cached.
IMAGE="$(jq -r '.args[] | select(test("playwright/mcp"))' "${MCP_JSON}" | head -n1)"
if [[ -n "${IMAGE}" ]] && command -v docker >/dev/null 2>&1; then
  if docker pull "${IMAGE}" >/dev/null 2>&1; then
    echo "✓ Pre-pulled ${IMAGE}."
  else
    echo "Note: could not pre-pull ${IMAGE} (it will pull on first use)." >&2
  fi
elif [[ -n "${IMAGE}" ]]; then
  echo "Note: Docker not on PATH; ${IMAGE} will pull on first use." >&2
fi
