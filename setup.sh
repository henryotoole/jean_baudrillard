#!/usr/bin/env bash
#
# setup.sh — Run setup so that jean is linked into whatever ai tooling we are working with.

# WARNING: This is hard-coded for claude right now.

cd ./setup/claude

source settings.sh
. settings.sh
source doctrine.sh
. doctrine.sh

# TODO write @./jean_baudrillard/JEAN.md to CLAUDE.md