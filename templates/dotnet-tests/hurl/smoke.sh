#!/usr/bin/env bash
# The spec's local-call tables (docs/specs/v0.1.md C1-C6, docs/specs/v0.2-weight-controller.md WC1-WC4) as hurl files in acceptance/.
# Starts `subgate serve` with examples/config.yaml, waits for /healthz, runs the files of SMOKE_SPEC (default v0.1) and stops the server.
# With SUBGATE_URL set it starts nothing and checks the instance there. Exit 0 only when every assertion holds.
# Needs: hurl, curl; SUBGATE_CONSUMER_TOKEN and SUBGATE_SIGNAL_TOKEN (the placeholders in examples/README.md).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

spec="${SMOKE_SPEC:-v0.1}"
base="${SUBGATE_URL:-http://localhost:8070}"
bin="${SUBGATE_BIN:-out/Subgate}"

for tool in hurl curl; do
  command -v "$tool" >/dev/null || { echo "smoke: $tool is not installed" >&2; exit 2; }
done
: "${SUBGATE_CONSUMER_TOKEN:?smoke: set SUBGATE_CONSUMER_TOKEN to the example consumer placeholder token}"
: "${SUBGATE_SIGNAL_TOKEN:?smoke: set SUBGATE_SIGNAL_TOKEN to the example signal reporter placeholder token}"
[ -d "acceptance/$spec" ] || { echo "smoke: no acceptance/$spec" >&2; exit 2; }

server=
if [ -z "${SUBGATE_URL:-}" ]; then
  [ -x "$bin" ] || { echo "smoke: $bin is not built (dotnet publish src/Subgate -c Release -o out)" >&2; exit 2; }
  "$bin" serve --config examples/config.yaml &
  server=$!
  trap 'kill "$server" 2>/dev/null' EXIT
fi

for _ in $(seq 1 50); do
  curl -sf -o /dev/null "$base/healthz" && break
  if [ -n "$server" ] && ! kill -0 "$server" 2>/dev/null; then echo "smoke: subgate serve exited before /healthz answered" >&2; exit 1; fi
  sleep 0.2
done

hurl --test --jobs 1 --file-root . \
  --variable "base_url=$base" \
  --variable "consumer_token=$SUBGATE_CONSUMER_TOKEN" \
  --variable "signal_token=$SUBGATE_SIGNAL_TOKEN" \
  "acceptance/$spec"/*.hurl
