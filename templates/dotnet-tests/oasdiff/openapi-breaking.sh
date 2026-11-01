#!/usr/bin/env bash
# Fails when api/openapi.yaml has a breaking change against BASE_REF (default origin/master). Needs: oasdiff, git.
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
base="${1:-origin/master}"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
git show "$base:api/openapi.yaml" > "$tmp"
oasdiff breaking "$tmp" api/openapi.yaml --fail-on WARN
