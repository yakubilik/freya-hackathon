#!/usr/bin/env bash
# Smoke test of the mock: every tool once, plus the error paths, against one customer.
#   mock/smoke.sh [URL] [CUSTOMER_ID]      defaults: http://127.0.0.1:8787 (npx -y wrangler@4 dev), PUB-01
# Env: DOB, PHONE (the customer's identity answers; defaults are PUB-01's), PRODUCT (p1), TOOL_KEY, ADMIN_KEY.
# The tool and field names are the practice contract's; after renaming them in src/index.js CONTRACT, edit the calls below.
# Exit status: the number of failed checks.
set -uo pipefail
URL="${1:-http://127.0.0.1:8787}"; URL="${URL%/}"
CID="${2:-PUB-01}"
DOB="${DOB:-1988-03-14}"; PHONE="${PHONE:-4471}"; PRODUCT="${PRODUCT:-p1}"
SWAPPED="$(echo "$DOB" | awk -F- '{print $1"-"$3"-"$2}')"
H=(-H "content-type: application/json")
[ -n "${TOOL_KEY:-}" ] && H+=(-H "authorization: Bearer $TOOL_KEY")
[ -n "${ADMIN_KEY:-}" ] && H+=(-H "x-admin-key: $ADMIN_KEY")
FAIL=0; PASS=0

# check <label> <expected substring> <method> <path> [json body]
check() {
  local label="$1" want="$2" method="$3" path="$4" body="${5:-}" out
  if [ "$method" = GET ]; then out="$(curl -sS "${H[@]}" "$URL$path" -w ' [%{http_code}]')"
  else out="$(curl -sS "${H[@]}" -X POST "$URL$path" -d "$body" -w ' [%{http_code}]')"; fi
  if [[ "$out" == *"$want"* ]]; then PASS=$((PASS+1)); printf 'ok    %-34s %s\n' "$label" "${out:0:150}"
  else FAIL=$((FAIL+1)); printf 'FAIL  %-34s want %s\n      got %s\n' "$label" "$want" "${out:0:300}"; fi
}

check "health"                         '"ok":true'                    GET  /health
check "health under /v1"               '"ok":true'                    GET  /v1/health
check "reset $CID"                     '"ok":true'                    POST "/v1/practice/reset/$CID" '{}'
check "unknown tool"                   '[404]'                        POST /v1/no_such_tool "{\"customer_id\":\"$CID\"}"
check "unknown customer"               'unknown customer_id"} [404]'  POST /v1/get_account '{"customer_id":"NOPE-999"}'
check "get_account before verify"      'identity not verified'        POST /v1/get_account "{\"customer_id\":\"$CID\"}"
check "verify: bad field"              'must be'                      POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"pin\",\"answer\":\"1\"}"
check "verify: unreadable date"        'is not a date'                POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"date_of_birth\",\"answer\":\"soon\"}"
check "verify: swapped dob -> hint"    'day_month_swapped'            POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"date_of_birth\",\"answer\":\"$SWAPPED\"}"
check "verify: wrong phone"            '"wrong_answers_left":2'       POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"phone_last4\",\"answer\":\"0000\"}"
check "verify: dob"                    '"verified":true'              POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"date_of_birth\",\"answer\":\"$DOB\"}"
check "verify: phone (no /v1 prefix)"  '"all_verified":true'          POST /verify_identity "{\"customer_id\":\"$CID\",\"field\":\"phone_last4\",\"answer\":\"$PHONE\"}"
check "get_account"                    '"products":['                 POST /v1/get_account "{\"customer_id\":\"$CID\"}"
check "create_promise: bad date"       'must be YYYY-MM-DD'           POST /v1/create_promise "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"amount\":10,\"date\":\"tomorrow\"}"
check "create_promise: bad amount"     'must be a positive number'    POST /v1/create_promise "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"amount\":0,\"date\":\"2026-10-14\"}"
check "create_promise: bad product"    'unknown product_id'           POST /v1/create_promise "{\"customer_id\":\"$CID\",\"product_id\":\"zz\",\"amount\":10,\"date\":\"2026-10-14\"}"
check "create_promise"                 '"promise_id":"pr1"'           POST /v1/create_promise "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"amount\":420,\"date\":\"2026-10-14\"}"
check "create_promise: twice"          'already has a promise'        POST /v1/create_promise "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"amount\":420,\"date\":\"2026-10-14\"}"
check "add_note: bad reason"           'unknown reason'               POST /v1/add_note "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"reason\":\"bored\",\"text\":\"x\"}"
check "add_note"                       '{"ok":true} [200]'            POST /v1/add_note "{\"customer_id\":\"$CID\",\"product_id\":\"$PRODUCT\",\"reason\":\"hardship\",\"text\":\"lost job\"}"
check "schedule_callback: bad time"    'HH:MM'                        POST /v1/schedule_callback "{\"customer_id\":\"$CID\",\"date\":\"2026-10-15\",\"time\":\"3pm\"}"
check "schedule_callback"              '{"ok":true} [200]'            POST /v1/schedule_callback "{\"customer_id\":\"$CID\",\"date\":\"2026-10-15\",\"time\":\"15:00\"}"
check "transfer_to_agent: bad queue"   'unknown queue'                POST /v1/transfer_to_agent "{\"customer_id\":\"$CID\",\"queue\":\"nowhere\"}"
check "transfer_to_agent"              '{"ok":true} [200]'            POST /v1/transfer_to_agent "{\"customer_id\":\"$CID\",\"queue\":\"general\"}"
check "close_call: reason on promise"  'needs one of these reasons'   POST /v1/close_call "{\"customer_id\":\"$CID\",\"outcome\":\"promise\",\"reason\":\"refused\"}"
check "close_call: bad outcome"        'unknown outcome'              POST /v1/close_call "{\"customer_id\":\"$CID\",\"outcome\":\"great\"}"
check "close_call"                     '{"ok":true} [200]'            POST /v1/close_call "{\"customer_id\":\"$CID\",\"outcome\":\"promise\"}"
check "after close"                    'the call is already closed'   POST /v1/add_note "{\"customer_id\":\"$CID\",\"reason\":\"paid\",\"text\":\"x\"}"
check "ledger"                         '"outcome":"promise"'          GET  "/v1/practice/ledger/$CID"
check "ledger: unknown customer"       '[404]'                        GET  /v1/practice/ledger/NOPE-999
check "verify after close: new call"   '"verified":true'              POST /v1/verify_identity "{\"customer_id\":\"$CID\",\"field\":\"date_of_birth\",\"answer\":\"$DOB\"}"
check "ledger history keeps old call"  '"history":[{'                 GET  "/v1/practice/ledger/$CID?history=1"
check "practice session"               '"customer_id":"c_'            POST /v1/practice/sessions "{\"case\":\"$CID\"}"
check "reset $CID (leave it clean)"    '"ok":true'                    POST "/v1/practice/reset/$CID" '{}'

echo "smoke: $PASS passed, $FAIL failed against $URL ($CID)"
exit "$FAIL"
