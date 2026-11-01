#!/usr/bin/env bash
# Proves the breaking-change gate can fail: each mutation of api/openapi.yaml below must be flagged (breaking) or passed (safe) by oasdiff. Needs: oasdiff, yq, jq.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
spec=api/openapi.yaml
dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
fails=0

check() { # kind name yq-expression
  local kind="$1" name="$2" expr="$3" n; local out="$dir/$2.yaml"
  yq "$expr" "$spec" > "$out"
  n=$(oasdiff breaking "$spec" "$out" --fail-on WARN -f json 2>/dev/null | jq 'length')
  oasdiff breaking "$spec" "$out" --fail-on WARN >/dev/null 2>&1; local rc=$?
  if { [ "$kind" = breaking ] && [ "$rc" -ne 0 ]; } || { [ "$kind" = safe ] && [ "$rc" -eq 0 ]; }; then
    printf 'ok   %-8s %-34s findings=%s exit=%s\n' "$kind" "$name" "$n" "$rc"
  else
    printf 'FAIL %-8s %-34s findings=%s exit=%s\n' "$kind" "$name" "$n" "$rc"; fails=$((fails + 1))
  fi
}

check breaking delete-path          'del(.paths."/capabilities")'
check breaking delete-operation     'del(.paths."/retouch".post)'
check breaking delete-response-200  'del(.paths."/capabilities".get.responses."200")'
check breaking required-body-field  '.paths."/retouch".post.requestBody.content."multipart/form-data".schema.required += ["tenant"] | .paths."/retouch".post.requestBody.content."multipart/form-data".schema.properties.tenant = {"type":"string"}'
check breaking required-query-param '.paths."/capabilities".get.parameters += [{"name":"tenant","in":"query","required":true,"schema":{"type":"string"}}]'
check breaking response-type-change '.components.schemas.RetouchResult.properties.status.type = "integer" | del(.components.schemas.RetouchResult.properties.status.enum)'
check breaking response-prop-removed 'del(.components.schemas.RetouchResult.properties.faces)'
check breaking request-enum-removed '.components.schemas.Capability.enum -= ["hair"]'
check breaking request-prop-removed 'del(.components.schemas.BatchRequest.properties.webhookUrl)'
check safe     add-path             '.paths."/v1-new" = {"get":{"operationId":"newOp","responses":{"200":{"description":"ok"}}}}'
check safe     add-optional-query   '.paths."/capabilities".get.parameters += [{"name":"verbose","in":"query","required":false,"schema":{"type":"boolean"}}]'
check safe     add-optional-prop    '.components.schemas.BatchRequest.properties.note = {"type":"string"}'
check safe     edit-description     '.info.description = "edited"'
check safe     bump-version         '.info.version = "0.2.0"'

exit "$fails"
