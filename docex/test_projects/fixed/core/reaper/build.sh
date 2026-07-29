#!/bin/sh
# build.sh — canonical build entry point for the `reaper` codebase. Same
# pattern as `api`: pure-Python, so build is a copy of src/ -> dist/.
set -eu

cd "$(dirname "$0")"

mkdir -p dist
find dist -mindepth 1 -delete
cp -r src/. dist/

echo "build: deposited $(find dist -type f | wc -l) files in dist/"
