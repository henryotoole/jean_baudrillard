#!/bin/sh
# build.sh — canonical build entry point for the `api` codebase.
# Copies src/ -> dist/. Pure-Python service, so no compilation.
# One build per CODEBASE, shared by every core service it declares.
set -eu

cd "$(dirname "$0")"

# Clear dist contents (not the dir — it may be a bind-mount in dev).
mkdir -p dist
find dist -mindepth 1 -delete
cp -r src/. dist/

echo "build: deposited $(find dist -type f | wc -l) files in dist/"
