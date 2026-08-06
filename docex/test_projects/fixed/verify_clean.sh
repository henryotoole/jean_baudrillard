#!/usr/bin/env bash
# verify_clean.sh — fail loudly if any docex_smoke_fixed resources remain.
#
# Filters by project-name prefix (every doctrine-emitted resource carries
# the project name). Exits 0 if everything is clean, non-zero with a
# report otherwise.
#
# THE RULE THIS SCRIPT IS BUILT ON: a check that cannot answer must FAIL,
# not report zero.
#
# Every false green this script has produced came from the same pattern —
# a query that errored (401, 404, unparseable body) was swallowed with
# `|| true` / `|| echo '{}'`, produced an empty result, and was reported as
# "clean". A cleanup check that cannot fail is worse than no check at all,
# because it gets cited as proof. Do NOT add `|| true` to a query path to
# quiet a noisy failure; the noise is the feature.

set -uo pipefail

PROJECT_NAME="docex_smoke_fixed"
# Hyphenated form. Doctrine name-translation rules (transfer_tables.md
# § naming) produce hyphenated image/container names from underscore
# project names, and docex's own test images use the hyphenated form.
PROJECT_NAME_HYPHEN="${PROJECT_NAME//_/-}"
REGISTRY_HOST="registry.luxrnd.tech"

remaining=0

# Run a query command, test ITS exit status, and only then look at the
# output.
#
# The shape this replaces was `count="$("$@" 2>/dev/null | wc -l)"`, which is
# the exact pattern the header condemns: an unreachable docker daemon makes
# `docker ps -aq` fail, `wc -l` count zero lines, and the check print OK —
# clean-looking output from a check that never ran. All three call sites
# (containers, networks, volumes) were affected.
#
# stderr is captured and PRINTED on failure rather than sent to /dev/null:
# it is the only thing that tells the operator *why* the check could not
# answer, and "could not answer" with no reason is barely better than a
# false green.
check() {
  local label="$1"; shift
  local out err rc
  err="$(mktemp)"
  out="$("$@" 2>"$err")"
  rc=$?
  if [[ "$rc" != "0" ]]; then
    echo "FAIL: $label — the check could not answer (exit $rc):"
    sed 's/^/   /' "$err"
    rm -f "$err"
    remaining=$((remaining + 1))
    return 0
  fi
  rm -f "$err"
  # An EMPTY result from a command that SUCCEEDED is the clean answer, and
  # the only case that may print OK.
  if [[ -n "$out" ]]; then
    local count
    count="$(printf '%s\n' "$out" | wc -l | tr -d ' ')"
    echo "FAIL: $label — $count item(s) remaining:"
    printf '%s\n' "$out" | sed 's/^/   /'
    remaining=$((remaining + count))
  else
    echo "OK:   $label"
  fi
}

check "docker containers"  docker ps -aq --filter "name=${PROJECT_NAME}"
check "docker networks"    docker network ls -q --filter "name=${PROJECT_NAME}"
check "docker volumes"     docker volume ls -q --filter "name=${PROJECT_NAME}"

# -- Local images ---------------------------------------------------------
# Both name forms, and NO left anchor. Four real shapes must match, and the
# old pattern — `(^|/)${PROJECT_NAME}/` — caught only the first two:
#   docex_smoke_fixed/api:0.0.18                          (bare repo)
#   registry.luxrnd.tech/docex_smoke_fixed/api:0.0.18     (registry-prefixed)
#   docex_smoke_fixed-stage-tester:latest                 (hyphen, not slash)
#   docex-test-docex-smoke-fixed-api:latest               (docex-built test image)
# The last two are why the separator class is [-_/:] and why there is no
# `^`: the project name appears MID-STRING in both. Derived from the
# elastic seed's DynamoDB check (elastic/verify_clean.sh, `ddb_tables`),
# widened for the two extra forms a docker image name can take.
#
# The docker call and the grep are deliberately SEPARATE statements. `grep`
# exits 1 when nothing matches, which is the CLEAN answer and the one case
# where a non-zero status is not an error — but a single piped `|| true`
# cannot tell "nothing matched" from "the docker daemon is not running",
# and would report the second as clean. That is the rule at the top of this
# file, applied to the one place in it that is not a registry call.
if ! all_images="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null)"; then
  echo "FAIL: local docker images — \`docker images\` failed; the check could not answer"
  remaining=$((remaining + 1))
else
  local_images="$(printf '%s\n' "$all_images" \
    | grep -E "(${PROJECT_NAME}|${PROJECT_NAME_HYPHEN})[-_/:]" || true)"
  if [[ -n "$local_images" ]]; then
    count=$(echo "$local_images" | wc -l | tr -d ' ')
    echo "FAIL: local docker images — $count item(s):"
    echo "$local_images" | sed 's/^/   /'
    remaining=$((remaining + count))
  else
    echo "OK:   local docker images"
  fi
fi

# -- Registry images ------------------------------------------------------
# The registry is htpasswd-protected (container_registry.md § Design, key
# choice 1), so every /v2/ call needs an Authorization header. Source it
# from the operator's ~/.docker/config.json — the artefact
# PRE_CUT_CHECKLIST § A.5 already requires. No new secret store.
#
# NOTE: this helper is duplicated verbatim in teardown.sh. These two
# scripts are standalone by design (an operator copies one into a project
# and runs it) and must not acquire a shared library, so the duplication is
# intentional. Change one, change the other.
REGISTRY_CURL_CONFIG=""
REGISTRY_BODY=""
cleanup_registry_config() {
  [[ -n "$REGISTRY_CURL_CONFIG" ]] && rm -f "$REGISTRY_CURL_CONFIG"
  [[ -n "$REGISTRY_BODY" ]] && rm -f "$REGISTRY_BODY"
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
    echo "FAIL: registry credential — no entry for ${REGISTRY_HOST} in ~/.docker/config.json"
    echo "      Resolution: docker login ${REGISTRY_HOST}  (PRE_CUT_CHECKLIST § A.5)"
    return 1
  }
  REGISTRY_CURL_CONFIG="$(mktemp)"
  chmod 600 "$REGISTRY_CURL_CONFIG"
  printf 'header = "Authorization: Basic %s"\n' "$b64" > "$REGISTRY_CURL_CONFIG"
}

# Authenticated GET. Writes the response body to the file named by
# REGISTRY_BODY and sets REGISTRY_STATUS to the HTTP status ("000" if curl
# itself failed). No `|| true`: an unreachable registry surfaces as status
# 000 and the caller treats it as a failure, which is the whole point.
#
# WHY the body goes to a FILE rather than to stdout: a function whose output
# is captured with `body="$(registry_get …)"` runs in a SUBSHELL, so every
# global it assigns — REGISTRY_STATUS included — is discarded when the
# subshell exits. The caller would then read an empty status, compare it
# against "200", and report a failure it cannot explain (or, with the
# comparison inverted, a false green). Call this as a plain command.
REGISTRY_STATUS=""
registry_get() {
  local path="$1"
  [[ -n "$REGISTRY_BODY" ]] && rm -f "$REGISTRY_BODY"
  REGISTRY_BODY="$(mktemp)"
  REGISTRY_STATUS="$(curl -sS -K "$REGISTRY_CURL_CONFIG" \
    -o "$REGISTRY_BODY" -w '%{http_code}' \
    "https://${REGISTRY_HOST}${path}" 2>/dev/null)" || REGISTRY_STATUS="000"
  return 0
}

registry_remaining=0
registry_query_ok=1

if ! init_registry_auth; then
  # A credential we cannot read means the registry was never interrogated.
  # Report it as a failure rather than as an empty result — this is exactly
  # the case the previous version of this script passed.
  registry_query_ok=0
  remaining=$((remaining + 1))
else
  # Enumerate what the registry HOLDS, not what the project currently
  # declares. The old loop was hardcoded to `for service in api`, so repos
  # retired by a rename — `reaper`, `web`, `worker` — were structurally
  # invisible to it, and that is where 26 of the 30 leaked tags found by the
  # 1.7.0 fixed walk actually sat.
  repos=""
  registry_get "/v2/_catalog?n=1000"
  if [[ "$REGISTRY_STATUS" != "200" ]]; then
    echo "FAIL: registry catalog — HTTP ${REGISTRY_STATUS} from /v2/_catalog"
    registry_query_ok=0
    registry_remaining=$((registry_remaining + 1))
  else
    if ! repos="$(python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(2)
for repo in (data.get('repositories') or []):
    if repo.startswith('${PROJECT_NAME}/'):
        print(repo)
" < "$REGISTRY_BODY")"; then
      echo "FAIL: registry catalog — unparseable body from /v2/_catalog"
      registry_query_ok=0
      registry_remaining=$((registry_remaining + 1))
      repos=""
    fi
    for repo in $repos; do
      registry_get "/v2/${repo}/tags/list"
      if [[ "$REGISTRY_STATUS" != "200" ]]; then
        echo "FAIL: registry ${repo} — HTTP ${REGISTRY_STATUS} from /v2/${repo}/tags/list"
        registry_query_ok=0
        registry_remaining=$((registry_remaining + 1))
        continue
      fi
      # A repo whose "tags" is null is NOT a leftover. The Registry V2 API
      # keeps a repository entry after its last manifest is deleted, until
      # the operator runs container_registry.md § Garbage Collection.
      # Verified live 2026-08-06: docex_smoke_fixed/{api,reaper,web,worker}
      # all return {"tags": null} after a clean teardown. Flagging empty
      # repos would make this script fail permanently on four repos holding
      # nothing. Report only NON-EMPTY tag lists.
      if ! tags="$(python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(2)
print('\n'.join(d.get('tags') or []))
" < "$REGISTRY_BODY")"; then
        echo "FAIL: registry ${repo} — unparseable body from /v2/${repo}/tags/list"
        registry_query_ok=0
        registry_remaining=$((registry_remaining + 1))
        continue
      fi
      if [[ -n "$tags" ]]; then
        count=$(echo "$tags" | wc -l | tr -d ' ')
        echo "FAIL: registry $repo — $count tag(s):"
        echo "$tags" | sed 's/^/   /'
        registry_remaining=$((registry_remaining + count))
      fi
    done
  fi
fi

# Prints ONLY when every query succeeded and every tag list was empty.
if [[ "$registry_query_ok" == "1" && "$registry_remaining" == "0" ]]; then
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
