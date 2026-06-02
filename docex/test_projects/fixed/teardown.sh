#!/usr/bin/env bash
# teardown.sh — fully retire docex_smoke_fixed from the dev machine.
#
# Idempotent: safe to re-run. Brings down every env's compose stack
# (named volumes included, since this project is retired), then deletes
# registry images for this project.
#
# Does NOT touch:
#   - Traefik (machine-wide prerequisite)
#   - The Docker Registry V2 itself (machine-wide prerequisite)
#   - DNS records at the registrar (operator's responsibility)
#   - SSH keypairs in infra/deploy_creds/ (operator may want to reuse)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="docex_smoke_fixed"
# Hyphenated form. Doctrine name-translation rules (transfer_tables.md
# § naming) produce hyphenated container/network/volume names from
# underscore project names; teardown's `docker ... --filter name=…`
# substring matching needs both forms to find every running resource.
PROJECT_NAME_HYPHEN="${PROJECT_NAME//_/-}"
REGISTRY_HOST="registry.luxrnd.tech"

echo "==> tearing down $PROJECT_NAME"

# -- 1. Compose stacks ----------------------------------------------------
for env in prod stage test dev; do
  compose_file="$PROJECT_ROOT/infra/output/$env/docker-compose.yml"
  if [[ -f "$compose_file" ]]; then
    echo "-- compose down: $env"
    docker compose --project-directory "$PROJECT_ROOT" -f "$compose_file" down -v --remove-orphans \
      || echo "   (warning: $env compose down had non-zero exit; continuing)"
  fi
done

# -- 2. Stray containers/networks/volumes by name prefix ------------------
# WHY: compose-named resources should be caught above, but a partial run
# can leave artifacts that compose's project filter no longer sees. We
# loop over both name forms because docex's name-translation produces
# hyphenated runtime names (`docex-smoke-fixed-…`) from the underscore
# project name (`docex_smoke_fixed`), and `--filter name=` is substring
# match — the underscore form never appears in hyphenated runtime names.
echo "-- stray docker resources by name prefix"
# Run the sweep twice with a brief pause: docker network rm fails when
# any container still has an endpoint on it, and containers from step 1
# (compose down) can take a moment to fully release their networks.
# The first pass kills any stray containers + clears volumes; the second
# pass picks up networks released by container shutdown.
for sweep in 1 2; do
  for pattern in "$PROJECT_NAME" "$PROJECT_NAME_HYPHEN"; do
    for container in $(docker ps -aq --filter "name=${pattern}" 2>/dev/null || true); do
      docker rm -f "$container" >/dev/null 2>&1 || true
    done
    for network in $(docker network ls -q --filter "name=${pattern}" 2>/dev/null || true); do
      docker network rm "$network" >/dev/null 2>&1 || true
    done
    for volume in $(docker volume ls -q --filter "name=${pattern}" 2>/dev/null || true); do
      docker volume rm "$volume" >/dev/null 2>&1 || true
    done
  done
  [ "$sweep" = "1" ] && sleep 2
done

# -- 3. Local images for this project ------------------------------------
echo "-- local docker images"
for image in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "(^|/)${PROJECT_NAME}/" || true); do
  docker rmi -f "$image" >/dev/null 2>&1 || true
done

# -- 4. Registry images for this project ---------------------------------
# Uses the Docker Registry V2 HTTP API. Requires the registry to allow
# image deletion (storage.delete.enabled: true in the registry config).
echo "-- registry images at $REGISTRY_HOST"
for service in web worker; do
  repo="${PROJECT_NAME}/${service}"
  tags_json="$(curl -fsS "https://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null || echo '{}')"
  for tag in $(echo "$tags_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(d.get('tags') or []))" 2>/dev/null || true); do
    digest="$(curl -fsSI -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
        "https://${REGISTRY_HOST}/v2/${repo}/manifests/${tag}" 2>/dev/null \
        | awk -F': ' 'tolower($1)=="docker-content-digest" {gsub(/\r/,"",$2); print $2}')"
    if [[ -n "$digest" ]]; then
      curl -fsS -X DELETE "https://${REGISTRY_HOST}/v2/${repo}/manifests/${digest}" >/dev/null \
        || echo "   (warning: failed to delete ${repo}:${tag})"
    fi
  done
done

# -- 5. Compiled output --------------------------------------------------
echo "-- compiled infra/output"
rm -rf "$PROJECT_ROOT/infra/output/dev" \
       "$PROJECT_ROOT/infra/output/test" \
       "$PROJECT_ROOT/infra/output/stage" \
       "$PROJECT_ROOT/infra/output/prod"

echo "==> teardown complete. run verify_clean.sh to confirm."
