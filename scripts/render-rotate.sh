#!/usr/bin/env bash
# Apply the new non-secret env vars to Cerebrum services on Render and
# trigger a redeploy on each. Existing API keys are NOT touched.
#
# Usage:
#     RENDER_KEY='rnd_...' bash scripts/render-rotate.sh
#
# Optional overrides (defaults shown):
#     API_SERVICE=cerebrum-platform-api
#     UI_SERVICE=cerebrum-platform
#     CORS_ORIGINS='https://cerebrum-platform.onrender.com'
#     API_URL=https://cerebrum-platform-api.onrender.com
#     DRY_RUN=1   # preview only; no writes, no deploys
#
# Merges the env-var updates into the existing list on each service —
# never deletes env vars you already set on Render.

set -euo pipefail

API_SERVICE="${API_SERVICE:-cerebrum-platform-api}"
UI_SERVICE="${UI_SERVICE:-cerebrum-platform}"
CORS_ORIGINS="${CORS_ORIGINS:-https://cerebrum-platform.onrender.com}"
API_URL="${API_URL:-https://cerebrum-platform-api.onrender.com}"
DRY_RUN="${DRY_RUN:-0}"

if [ -z "${RENDER_KEY:-}" ]; then
    echo "ERROR: RENDER_KEY env var is required." >&2
    echo "Run as: RENDER_KEY='rnd_...' bash $0" >&2
    exit 2
fi

for tool in curl jq openssl; do
    command -v "$tool" >/dev/null || { echo "ERROR: $tool is required" >&2; exit 2; }
done

R_HOST="https://api.render.com/v1"
auth_h=(-H "Authorization: Bearer $RENDER_KEY" -H "Accept: application/json")

api() {
    # api METHOD PATH [json-body]
    local method="$1" path="$2" body="${3:-}"
    if [ -n "$body" ]; then
        curl -fsS -X "$method" "${auth_h[@]}" -H "Content-Type: application/json" \
            -d "$body" "${R_HOST}${path}"
    else
        curl -fsS -X "$method" "${auth_h[@]}" "${R_HOST}${path}"
    fi
}

find_service_id() {
    local name="$1"
    local id
    id="$(api GET "/services?name=${name}&limit=1" | jq -r '.[0].service.id // empty')"
    if [ -z "$id" ]; then
        echo "ERROR: no Render service named '$name'" >&2
        return 1
    fi
    echo "$id"
}

merge_env_vars() {
    # merge_env_vars <service-id> <updates-json-array>
    # updates-json-array: [{"key":"X","value":"Y"}, ...]
    local id="$1" updates="$2"
    local current merged
    current="$(api GET "/services/${id}/env-vars?limit=100" | jq '[.[].envVar]')"
    merged="$(jq -n --argjson cur "$current" --argjson upd "$updates" '
        ($upd | map(.key)) as $upd_keys
        | ($cur | map(select(.key as $k | ($upd_keys | index($k)) | not))) + $upd
    ')"
    if [ "$DRY_RUN" = "1" ]; then
        echo "  [dry-run] would PUT ${merged} env vars to /services/${id}/env-vars"
        echo "  [dry-run] update keys: $(echo "$updates" | jq -c '[.[].key]')"
    else
        api PUT "/services/${id}/env-vars" "$merged" >/dev/null
    fi
}

trigger_deploy() {
    local id="$1"
    if [ "$DRY_RUN" = "1" ]; then
        echo "  [dry-run] would POST /services/${id}/deploys"
    else
        api POST "/services/${id}/deploys" '{"clearCache":"do_not_clear"}' \
            | jq -r '"  deploy id=\(.id) status=\(.status)"'
    fi
}

echo "==> Resolving service IDs"
API_ID="$(find_service_id "$API_SERVICE")"
UI_ID="$(find_service_id "$UI_SERVICE")"
echo "    $API_SERVICE -> $API_ID"
echo "    $UI_SERVICE  -> $UI_ID"

echo "==> Updating API service env vars ($API_SERVICE)"
echo "    NOTE: existing CEREBRUM_MASTER_KEY / CEREBRUM_API_KEY_FRONTEND / VITE_API_KEY are NOT touched."
api_updates="$(jq -n --arg cors "$CORS_ORIGINS" '[
    {"key":"CORS_ORIGINS","value":$cors},
    {"key":"LOG_LEVEL","value":"INFO"},
    {"key":"LOG_FORMAT","value":"json"},
    {"key":"ENV","value":"production"}
]')"
merge_env_vars "$API_ID" "$api_updates"

echo "==> Updating UI service env vars ($UI_SERVICE)"
ui_updates="$(jq -n --arg base "$API_URL" '[
    {"key":"VITE_API_BASE","value":$base}
]')"
merge_env_vars "$UI_ID" "$ui_updates"

echo "==> Triggering deploys (API first, then UI)"
trigger_deploy "$API_ID"
trigger_deploy "$UI_ID"

echo
echo "==> Done."
if [ "$DRY_RUN" != "1" ]; then
    echo
    echo "Smoke-test once the API deploy is live (~2-3 min):"
    echo "    curl -i -H \"Authorization: Bearer <your-existing-frontend-key>\" \\"
    echo "         $API_URL/health"
    echo
    echo "Reminder: you still need to set VITE_API_KEY on the UI service to match"
    echo "the frontend bearer key you want the SPA to send. The script does NOT"
    echo "touch any *_KEY env var, so set it manually in the Render dashboard if"
    echo "it isn't already configured."
fi
