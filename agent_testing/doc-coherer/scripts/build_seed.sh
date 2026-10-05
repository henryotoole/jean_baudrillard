#!/usr/bin/env bash
# Build the immutable seed: a pristine snapshot of the nasmyth project at a pinned
# commit, as a tarball in fixtures/. Run ONCE (or to re-pin). The seed carries no
# .git — reset.sh re-inits a repo so each run yields a clean diff.
#
# Usage: build_seed.sh [nasmyth_repo] [git_ref]
set -euo pipefail

NASMYTH="${1:-$HOME/projects/nasmyth}"
REF="${2:-b692c00a}"   # pristine tip, BEFORE any agent test edits
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="$HERE/fixtures/seed_nasmyth.tgz"

cat >&2 <<'NOTE'
------------------------------------------------------------------------------
 doc-coherer test seed
 The seed tarball (fixtures/seed_nasmyth.tgz) is git-IGNORED — large (~58MB) and
 regenerable, so it is not committed. A fresh checkout will NOT have it, and the
 test CANNOT run until this script builds it. That is what this script is for.
------------------------------------------------------------------------------
NOTE

if [ ! -d "$NASMYTH/.git" ]; then
  echo "error: source repo $NASMYTH is not a git repo — cannot build the seed," >&2
  echo "       and without the seed the doc-coherer test cannot run." >&2
  echo "       Pass the nasmyth repo path as arg 1, e.g. build_seed.sh ~/projects/nasmyth" >&2
  exit 1
fi

# git archive emits only tracked files at REF — deterministic, no working-tree
# leakage, no .git. That is exactly the pristine seed we want.
git -C "$NASMYTH" archive --format=tar.gz -o "$SEED" "$REF"
echo "wrote $SEED"
echo "  ref:    $REF ($(git -C "$NASMYTH" rev-parse --short "$REF"))"
echo "  bytes:  $(stat -c%s "$SEED")"
