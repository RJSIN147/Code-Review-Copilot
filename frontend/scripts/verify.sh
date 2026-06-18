#!/usr/bin/env bash
# verify.sh - curl-based API contract verification for Code-Review-Copilot frontend.
#
# PREREQUISITES:
#   - Backend running via `docker compose up` (or equivalent) on localhost:8000.
#   - Database migrations applied.
#   - curl and jq available on PATH.
#
# This script validates the API contract the frontend depends on:
# health, validation errors, task submission, listing, status, and cancellation.
# It does NOT wait for a task to reach a completed state (analysis takes minutes);
# instead it cancels the submitted task to confirm DELETE works end-to-end.

set -u
set -o pipefail

ROOT_URL="${ROOT_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL:-${ROOT_URL}/api/v1}"
TOTAL=0
PASSED=0
FAILED=0
TASK_ID=""

# Helpers ---------------------------------------------------------------------

print_step() {
    printf "\n=== %s ===\n" "$1"
}

record() {
    local name="$1"
    local expected="$2"
    local actual="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "$expected" == "$actual" ]]; then
        printf "[PASS] %-50s (expected=%s, got=%s)\n" "$name" "$expected" "$actual"
        PASSED=$((PASSED + 1))
    else
        printf "[FAIL] %-50s (expected=%s, got=%s)\n" "$name" "$expected" "$actual"
        FAILED=$((FAILED + 1))
    fi
}

require_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: jq is required for JSON parsing. Install jq and retry." >&2
        exit 2
    fi
}

cleanup() {
    if [[ -n "$TASK_ID" ]]; then
        # Best-effort cleanup if a prior step left a task dangling.
        curl -sS -o /dev/null -X DELETE "${BASE_URL}/tasks/${TASK_ID}" || true
    fi
}
trap cleanup EXIT

# Pre-flight -------------------------------------------------------------------

require_jq

# 1. Health --------------------------------------------------------------------

print_step "1. Health check"
HEALTH_CODE=$(curl -sS -o /tmp/verify_health.json -w "%{http_code}" "${ROOT_URL}/health")
record "GET /health -> 200" "200" "$HEALTH_CODE"

# 2. Validation error ----------------------------------------------------------

print_step "2. Validation error on POST /analyze-pr"
VALIDATION_BODY='{"repo_url":"not-a-url","pr_number":0}'
VAL_CODE=$(curl -sS -o /tmp/verify_validation.json -w "%{http_code}" \
    -X POST "${BASE_URL}/analyze-pr" \
    -H "Content-Type: application/json" \
    -d "$VALIDATION_BODY")
record "POST /analyze-pr (invalid) -> 422" "422" "$VAL_CODE"

# 3. Successful submission -----------------------------------------------------

print_step "3. Submit a valid analyze-pr task"
SUBMIT_BODY='{"repo_url":"https://github.com/spoo-me/url-shortener","pr_number":79}'
SUBMIT_CODE=$(curl -sS -o /tmp/verify_submit.json -w "%{http_code}" \
    -X POST "${BASE_URL}/analyze-pr" \
    -H "Content-Type: application/json" \
    -d "$SUBMIT_BODY")
record "POST /analyze-pr (valid) -> 202" "202" "$SUBMIT_CODE"

TASK_ID=$(jq -r '.task_id // .id // empty' /tmp/verify_submit.json 2>/dev/null || true)
if [[ -z "$TASK_ID" ]]; then
    echo "ERROR: could not extract task_id from submit response:" >&2
    cat /tmp/verify_submit.json >&2
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
    record "extract task_id from submit response" "present" "missing"
else
    echo "Submitted task_id=${TASK_ID}"
fi

# 4. List tasks ----------------------------------------------------------------

print_step "4. List tasks"
LIST_CODE=$(curl -sS -o /tmp/verify_list.json -w "%{http_code}" \
    "${BASE_URL}/tasks?limit=10&offset=0")
record "GET /tasks?limit=10&offset=0 -> 200" "200" "$LIST_CODE"

IS_ARRAY=$(jq -r '(.tasks | type) == "array"' /tmp/verify_list.json 2>/dev/null || echo "false")
record "GET /tasks response contains tasks array" "true" "$IS_ARRAY"

# 5. Status retrieval ----------------------------------------------------------

if [[ -n "$TASK_ID" ]]; then
    print_step "5. Get status for task ${TASK_ID}"
    STATUS_CODE=$(curl -sS -o /tmp/verify_status.json -w "%{http_code}" \
        "${BASE_URL}/status/${TASK_ID}")
    record "GET /status/${TASK_ID} -> 200" "200" "$STATUS_CODE"
else
    print_step "5. Get status (skipped, no task_id)"
fi

# 6. Cancellation --------------------------------------------------------------

if [[ -n "$TASK_ID" ]]; then
    print_step "6. Cancel task ${TASK_ID}"
    CANCEL_CODE=$(curl -sS -o /tmp/verify_cancel.json -w "%{http_code}" \
        -X DELETE "${BASE_URL}/tasks/${TASK_ID}" \
        -H "Content-Type: application/json" \
        -d '{"reason":"verify cleanup"}')
    record "DELETE /tasks/${TASK_ID} -> 200" "200" "$CANCEL_CODE"

    CANCEL_STATUS=$(jq -r '.status // empty' /tmp/verify_cancel.json 2>/dev/null || echo "")
    record "cancellation response status == cancelled" "cancelled" "$CANCEL_STATUS"

    # The task_id is now cancelled - prevent trap from re-cancelling.
    TASK_ID=""
else
    print_step "6. Cancellation (skipped, no task_id)"
fi

# Summary ----------------------------------------------------------------------

echo
echo "================================================================"
echo "Results: ${PASSED}/${TOTAL} passed, ${FAILED} failed"
echo "================================================================"

if [[ "$FAILED" -gt 0 ]]; then
    exit 1
fi
exit 0
