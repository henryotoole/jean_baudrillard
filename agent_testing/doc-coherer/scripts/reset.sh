#!/usr/bin/env bash
# Reset a scratch working tree to the pristine seed and record a baseline commit,
# so the agent's edits are captured as a clean `git diff`. The scratch dir MUST be
# outside this plugin repo and outside ~/projects/nasmyth.
#
# Usage: reset.sh <scratch_dir>
set -euo pipefail

SCRATCH="${1:?usage: reset.sh <scratch_dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="$HERE/fixtures/seed_nasmyth.tgz"

if [ ! -f "$SEED" ]; then
  echo "error: seed tarball is missing (it is git-ignored, so a fresh checkout" >&2
  echo "       will not have it) — the doc-coherer test cannot run until it exists." >&2
  echo "       Build it: scripts/build_seed.sh [nasmyth_repo]" >&2
  exit 1
fi
case "$(cd "$SCRATCH" 2>/dev/null && pwd || echo "$SCRATCH")" in
  "$HERE"*|"$HOME/projects/nasmyth"*)
    echo "error: refusing to reset inside the plugin repo or the real nasmyth" >&2; exit 1;;
esac

rm -rf "$SCRATCH"
mkdir -p "$SCRATCH"
tar xzf "$SEED" -C "$SCRATCH"
git -C "$SCRATCH" init -q
git -C "$SCRATCH" config user.email test@doc-coherer.local
git -C "$SCRATCH" config user.name "doc-coherer-test"
git -C "$SCRATCH" add -A
git -C "$SCRATCH" commit -qm baseline
echo "$SCRATCH"
