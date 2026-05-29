#!/bin/sh
# build.sh — canonical build entry point for `web`.
# Copies src/ -> dist/. Pure-Python service, so no compilation.
set -eu

cd "$(dirname "$0")"

# Clear dist contents (not the dir — it may be a bind-mount in dev).
mkdir -p dist
find dist -mindepth 1 -delete
cp -r src/. dist/

echo "build: deposited $(find dist -type f | wc -l) files in dist/"
