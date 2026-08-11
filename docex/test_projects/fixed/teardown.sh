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
# § Naming Policies) produce hyphenated container/network/volume names from
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
# Both name forms, and NO left anchor. Four real shapes must match, and the
# old pattern — `(^|/)${PROJECT_NAME}/` — caught only the first two, which
# is why the last two were never DELETED, not merely never reported:
#   docex_smoke_fixed/api:0.0.18                          (bare repo)
#   registry.luxrnd.tech/docex_smoke_fixed/api:0.0.18     (registry-prefixed)
#   docex_smoke_fixed-stage-tester:latest                 (hyphen, not slash)
#   docex-test-docex-smoke-fixed-api:latest               (docex-built test image)
# The last two are why the separator class is [-_/:] and why there is no
# `^`: the project name appears MID-STRING in both.
for image in $(docker images --format '{{.Repository}}:{{.Tag}}' \
                 | grep -E "(${PROJECT_NAME}|${PROJECT_NAME_HYPHEN})[-_/:]" || true); do
  docker rmi -f "$image" >/dev/null 2>&1 || true
done

# -- 4. Registry images for this project ---------------------------------
# Uses the Docker Registry V2 HTTP API. Requires the registry to run with
# `REGISTRY_STORAGE_DELETE_ENABLED: "true"` — see
# doctrine/infrastructure/preinfra/container_registry.md § Registry
# container. Without it every manifest DELETE below returns 405 and this
# project leaks a tag per release. That requirement used to live ONLY in
# this comment, which is precisely how a machine-wide misconfiguration
# survived several releases; it is now doctrine.
echo "-- registry images at $REGISTRY_HOST"

# The registry is htpasswd-protected (container_registry.md § Design, key
# choice 1), so every /v2/ call needs an Authorization header. Source it
# from the operator's ~/.docker/config.json — the artefact
# PRE_CUT_CHECKLIST § A.5 already requires.
#
# NOTE: this helper is duplicated verbatim in verify_clean.sh. These two
# scripts are standalone by design (an operator copies one into a project
# and runs it) and must not acquire a shared library, so the duplication is
# intentional. Change one, change the other.
REGISTRY_CURL_CONFIG=""
cleanup_registry_config() {
  [[ -n "$REGISTRY_CURL_CONFIG" ]] && rm -f "$REGISTRY_CURL_CONFIG"
  return 0
}
trap cleanup_registry_config EXIT

# WHY the credential goes through a `curl -K` config file and never `-u`:
# `-u` and `-H` both put the credential in argv, where any user on the host
# can read it from `ps`. The config file is mode 600 and removed on exit.
# It must never be echoed, and this script must never be run under `set -x`.
init_registry_auth() {
  local b64
  b64="$(python3 -c "
import json, os, sys
p = os.path.expanduser('~/.docker/config.json')
try:
    auth = json.load(open(p))['auths']['${REGISTRY_HOST}']['auth']
except Exception:
    sys.exit(1)
print(auth)
")" || {
    echo "   FAIL: registry credential — no entry for ${REGISTRY_HOST} in ~/.docker/config.json"
    echo "         Resolution: docker login ${REGISTRY_HOST}  (PRE_CUT_CHECKLIST § A.5)"
    return 1
  }
  REGISTRY_CURL_CONFIG="$(mktemp)"
  chmod 600 "$REGISTRY_CURL_CONFIG"
  printf 'header = "Authorization: Basic %s"\n' "$b64" > "$REGISTRY_CURL_CONFIG"
}

if ! init_registry_auth; then
  echo "   (registry images NOT purged — verify_clean.sh will report what survived)"
else
  # Enumerate what the registry HOLDS, not what the project currently
  # declares. The old loop was hardcoded to `for service in api`, so repos
  # retired by a rename — `reaper`, `web`, `worker` — could never be purged
  # at all, and that is where 26 of the 30 tags leaked by the 2.0.0 fixed
  # walk actually sat.
  catalog_status="$(curl -sS -K "$REGISTRY_CURL_CONFIG" \
    -o /tmp/${PROJECT_NAME}-catalog.json -w '%{http_code}' \
    "https://${REGISTRY_HOST}/v2/_catalog?n=1000" 2>/dev/null || echo "000")"
  if [[ "$catalog_status" != "200" ]]; then
    echo "   FAIL: /v2/_catalog returned HTTP ${catalog_status} — no repos purged"
    repos=""
  else
    # An unparseable body is reported, not swallowed into "no repos". A
    # silent empty list here is indistinguishable from a clean registry and
    # is exactly how this script leaked 30 tags while claiming to purge.
    if ! repos="$(python3 -c "
import json, sys
try:
    data = json.load(open('/tmp/${PROJECT_NAME}-catalog.json'))
except Exception:
    sys.exit(2)
for repo in (data.get('repositories') or []):
    if repo.startswith('${PROJECT_NAME}/'):
        print(repo)
")"; then
      echo "   FAIL: /v2/_catalog returned an unparseable body — no repos purged"
      repos=""
    fi
  fi
  rm -f "/tmp/${PROJECT_NAME}-catalog.json"

  for repo in $repos; do
    echo "   repo: $repo"
    tags_status="$(curl -sS -K "$REGISTRY_CURL_CONFIG" \
      -o /tmp/${PROJECT_NAME}-tags.json -w '%{http_code}' \
      "https://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null || echo "000")"
    if [[ "$tags_status" != "200" ]]; then
      echo "   FAIL: ${repo} tags/list returned HTTP ${tags_status} — repo not purged"
      rm -f "/tmp/${PROJECT_NAME}-tags.json"
      continue
    fi
    if ! tags="$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/${PROJECT_NAME}-tags.json'))
except Exception:
    sys.exit(2)
print('\n'.join(d.get('tags') or []))
")"; then
      echo "   FAIL: ${repo} tags/list returned an unparseable body — repo not purged"
      rm -f "/tmp/${PROJECT_NAME}-tags.json"
      continue
    fi
    for tag in $tags; do
      # WHY three Accept types: buildx pushes an OCI INDEX, so offering
      # only `manifest.v2+json` resolves nothing for any image this project
      # has ever produced — the HEAD 404s, no digest is obtained, and the
      # DELETE below never runs. That is the second of the two bugs that
      # made teardown silently leak every tag it claimed to remove.
      #
      # The HEAD and the awk are separate statements rather than one
      # pipeline: `set -euo pipefail` would abort the whole teardown on a
      # transient network failure inside a pipeline, taking steps 5 and 6
      # (projinfra down, compiled output) with it.
      digest=""
      if ! headers="$(curl -sSI -K "$REGISTRY_CURL_CONFIG" \
          -H 'Accept: application/vnd.oci.image.index.v1+json' \
          -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
          -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
          "https://${REGISTRY_HOST}/v2/${repo}/manifests/${tag}" 2>/dev/null)"; then
        echo "   FAIL: ${repo}:${tag} — manifest HEAD request failed"
      else
        digest="$(printf '%s' "$headers" \
          | awk -F': ' 'tolower($1)=="docker-content-digest" {gsub(/\r/,"",$2); print $2}')"
      fi
      if [[ -z "$digest" ]]; then
        echo "   FAIL: ${repo}:${tag} — no docker-content-digest returned; not deleted"
        continue
      fi
      # A DELETE that is not 202 is a FAILURE, not a warning to skim past.
      # 405 means the registry runs without REGISTRY_STORAGE_DELETE_ENABLED
      # (see the section comment above); 401 means the credential is stale.
      delete_status="$(curl -sS -K "$REGISTRY_CURL_CONFIG" -X DELETE \
        -o /dev/null -w '%{http_code}' \
        "https://${REGISTRY_HOST}/v2/${repo}/manifests/${digest}" 2>/dev/null || echo "000")"
      if [[ "$delete_status" != "202" ]]; then
        echo "   FAIL: DELETE ${repo}:${tag} returned HTTP ${delete_status} (expected 202)"
      fi
    done
    rm -f "/tmp/${PROJECT_NAME}-tags.json"
  done
fi

# -- 5. Dev-side projinfra ------------------------------------------------
# Mod 053 (F18): tear the dev-side projinfra (per-project traefik + four
# `-web` networks) down BEFORE clearing infra/output — `projinfra down`
# reads the compiled project compose file, so doing it after the rm would
# no-op and orphan the traefik + networks (the source of the 24h-stale
# traefik that broke a prior walk's `projinfra up`). With mod 053's
# explicit `--project-name`, this down now also removes the four `-web`
# networks, not just the traefik container. The step-2 stray sweep still
# backstops any residue.
if [[ -f "$PROJECT_ROOT/infra/output/project/development/docker-compose.yml" ]]; then
  echo "-- projinfra down development"
  (cd "$PROJECT_ROOT" && ./bin/docex projinfra down development) \
    || echo "   (warning: projinfra down development had non-zero exit; continuing)"
fi

# -- 6. Compiled output --------------------------------------------------
echo "-- compiled infra/output"
rm -rf "$PROJECT_ROOT/infra/output/dev" \
       "$PROJECT_ROOT/infra/output/test" \
       "$PROJECT_ROOT/infra/output/stage" \
       "$PROJECT_ROOT/infra/output/prod" \
       "$PROJECT_ROOT/infra/output/project"

echo "==> teardown complete. run verify_clean.sh to confirm."
