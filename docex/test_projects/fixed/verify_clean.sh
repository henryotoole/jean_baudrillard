#!/usr/bin/env bash
# verify_clean.sh — fail loudly if any docex_smoke_fixed resources remain.
#
# Filters by project-name prefix (every doctrine-emitted resource carries
# the project name). Exits 0 if everything is clean, non-zero with a
# report otherwise.

set -uo pipefail

PROJECT_NAME="docex_smoke_fixed"
REGISTRY_HOST="registry.luxrnd.tech"

remaining=0

check() {
  local label="$1"; shift
  local count
  count="$("$@" 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$count" != "0" ]]; then
    echo "FAIL: $label — $count item(s) remaining:"
    "$@" 2>/dev/null | sed 's/^/   /'
    remaining=$((remaining + count))
  else
    echo "OK:   $label"
  fi
}

check "docker containers"  docker ps -aq --filter "name=${PROJECT_NAME}"
check "docker networks"    docker network ls -q --filter "name=${PROJECT_NAME}"
check "docker volumes"     docker volume ls -q --filter "name=${PROJECT_NAME}"

# Local image list
local_images=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "(^|/)${PROJECT_NAME}/" || true)
if [[ -n "$local_images" ]]; then
  count=$(echo "$local_images" | wc -l | tr -d ' ')
  echo "FAIL: local docker images — $count item(s):"
  echo "$local_images" | sed 's/^/   /'
  remaining=$((remaining + count))
else
  echo "OK:   local docker images"
fi

# Registry images
registry_remaining=0
# One repo per CODEBASE, not per core service: `api` carries both the
# `web` and `worker` core services on one image, so it is one repo. Keep
# this list in sync with infra.yml's `core_services:` keys — the next
# codebase added must be added here or its registry repo survives
# teardown, exactly as `reaper` did before mod 107.
for service in api reaper; do
  repo="${PROJECT_NAME}/${service}"
  tags="$(curl -fsS "https://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(d.get('tags') or []))" 2>/dev/null || true)"
  if [[ -n "$tags" ]]; then
    count=$(echo "$tags" | wc -l | tr -d ' ')
    echo "FAIL: registry $repo — $count tag(s):"
    echo "$tags" | sed 's/^/   /'
    registry_remaining=$((registry_remaining + count))
  fi
done
if [[ "$registry_remaining" == "0" ]]; then
  echo "OK:   registry images"
fi
remaining=$((remaining + registry_remaining))

if [[ "$remaining" != "0" ]]; then
  echo
  echo "verify_clean: $remaining item(s) still present. teardown did not fully complete."
  exit 1
fi

echo
echo "verify_clean: clean."
