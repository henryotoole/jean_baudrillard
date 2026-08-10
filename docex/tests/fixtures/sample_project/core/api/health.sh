#!/bin/sh
# Container health probe. Invoked per core service as `./health.sh <service>`;
# the compiler supplies the argv (cicd.md § Check Step, healthchecks.md § The probe).
set -eu

service="${1:-}"
case "$service" in
  web)
    # Language-native check — this image is python:3.12-slim and carries no curl.
    exec python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
    ;;
  *)
    echo "health.sh: unknown core service '${service}'" >&2
    exit 1
    ;;
esac
