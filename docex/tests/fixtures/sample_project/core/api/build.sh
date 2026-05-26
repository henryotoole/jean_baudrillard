#!/bin/sh
# build.sh — canonical build entry point for the api core service.
#
# For Python projects this is just a copy from src/ to dist/. The
# doctrine requires the artifact to land in /service/dist (or, when
# invoked on the host via `docex build`, $pr/core/<svc>/dist/).
set -eu

cd "$(dirname "$0")"

# NOTE: `dist/` may be a bind mount under the dev stage, so we can't
# `rm -rf dist` (the directory itself can't be removed). Clear contents
# instead.
mkdir -p dist
find dist -mindepth 1 -delete
cp -r src/. dist/
echo "build: deposited $(ls dist | wc -l) entries in dist/"
