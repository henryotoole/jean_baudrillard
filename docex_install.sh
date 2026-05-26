#!/usr/bin/env bash
# Install docex into a project.
#
# Usage: docex_install.sh <target_directory>
#
# Copies the canonical docex shim to <target>/bin/docex and writes
# the currently-shipped docex_version into <target>/project.yml.
# Idempotent: re-running upgrades both the shim and the pin in place,
# and is the supported way to bump a project's docex version.
#
# This script is doctrine-side: it lives next to the doctrine repo,
# not bundled into the docex image. Project-structure scaffolding
# (folders, gitignores, etc.) is handled by inception.md, not here.

set -euo pipefail

DOCEX_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/docex" && pwd)"
SHIM="$DOCEX_REPO/bin/docex"

if [[ ! -f "$SHIM" ]]; then
  echo "error: docex shim missing at $SHIM" >&2
  exit 1
fi

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $(basename "$0") <target_directory>" >&2
  exit 64
fi
if [[ ! -d "$TARGET" ]]; then
  echo "error: target directory does not exist: $TARGET" >&2
  exit 1
fi
TARGET="$(cd "$TARGET" && pwd)"

if [[ ! -f "$TARGET/project.yml" ]]; then
  echo "error: $TARGET/project.yml not found." >&2
  echo "       run the inception flow first to scaffold the project." >&2
  exit 1
fi

DOCEX_VERSION="$(grep -E '^version' "$DOCEX_REPO/pyproject.toml" \
  | head -1 \
  | sed -E 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"

echo "installing docex $DOCEX_VERSION into $TARGET"

# --- Shim --------------------------------------------------------------
mkdir -p "$TARGET/bin"
cp "$SHIM" "$TARGET/bin/docex"
chmod +x "$TARGET/bin/docex"

# --- project.yml docex_version pin ------------------------------------
# Upsert the docex_version field: replace the existing line if present,
# otherwise append.
if grep -qE '^docex_version[[:space:]]*:' "$TARGET/project.yml"; then
  sed -i.bak -E "s|^docex_version[[:space:]]*:.*|docex_version: \"$DOCEX_VERSION\"|" "$TARGET/project.yml"
  rm -f "$TARGET/project.yml.bak"
else
  printf 'docex_version: "%s"\n' "$DOCEX_VERSION" >> "$TARGET/project.yml"
fi

echo "install complete."
echo
echo "verify with: cd $TARGET && ./bin/docex --version"
