#!/usr/bin/env bash
#
# setup.sh — Run setup so that jean is linked into whatever ai tooling we are working with.

# WARNING: This is hard-coded for claude right now.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_SETUP_DIR="${SCRIPT_DIR}/setup/claude"

bash "${CLAUDE_SETUP_DIR}/settings.sh"
bash "${CLAUDE_SETUP_DIR}/gen_resident.sh"
bash "${CLAUDE_SETUP_DIR}/jeanlink.sh"