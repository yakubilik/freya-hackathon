# bank: our copy of the organizers' mock bank

Same seven tools, same answers, same ledger; any customer, any date, any products, any identity questions, any fault.
Standard library only. Proven by replaying the 26 recorded sequences (`research/bank-recorded-behaviour.json`).

## Run

```
bank/up.sh                      # 0.0.0.0:${BANK_PORT:-8787}, pid in bank/.pid, log in bank/.log
BANK_TUNNEL=1 bank/up.sh        # also a cloudflared quick tunnel; public URL in bank/.url
bank/down.sh
.venv/bin/python -m bank.replay [--url http://host:port]      # the 26 recorded sequences
.venv/bin/python -m pytest tests/test_bank*.py -q
FREYA_BANK_HOST=http://127.0.0.1:8787 python kit/build-the-builder/tools/run_cases.py <agent_id>   # the kit against our bank
```

Routes under `/v1`: `POST /<tool>` (seven tools, `customer_id` in the body), `POST /practice/sessions`,
`GET /practice/ledger/<customer_id>`, `GET /health`. `x-team-key` is accepted on the practice routes and hashed into `team`.

## Sessions and fixtures

`POST /v1/practice/sessions` with `{"case": "PUB-07"}` (a case of the loaded case files) or `{"customer": <case object>}`:

```
{"id": "EXT-001", "variables": {"first_name", "last_name", "title", "now"},
 "identity": {"date_of_birth": "1975-12-05", "phone_last4": "6630"},          # any fields; type guessed from the answer
 "products": [{"product_id": "p1", "type": "credit_card", "past_due": 420, ...}],   # product_id defaults to p1, p2...
 "faults": [{"tool": "create_promise", "fail_first_n": 1},                    # first n calls answer 500
            {"tool": "close_call", "fail_on_call": 2},                        # only the n-th call answers 500
            {"tool": "get_account", "slow_ms": 20000, "on_call": 1}],         # sleep before answering (every call without on_call)
 "profile": {...}}
```

Answer: `{"ok": true, "variables": {"customer_id": "c_...", ...variables}}`. Ledger shape as recorded: `case, team, now, verified{},
wrong, hinted, promises[], notes[], callbacks[], transfers[], outcome, reason, failures{tool: n}, calls[{n, tool, args, status, result}], last_at`.

## Profile

Defaults in `server.py` `DEFAULT_PROFILE`; a case's `profile` overrides per key. `bank/adapters.py` builds one from an OpenAPI file:

```
from bank.adapters import profile_from_openapi
profile = profile_from_openapi(openapi_doc, outcome_reasons={...from the brief's table...})
```

| key | meaning |
|---|---|
| `max_wrong` | wrong answers before "identity check is over" (3) |
| `identity_types` | field -> `date` / `digits` / `text` |
| `note_reasons`, `queues` | the enums |
| `outcome_reasons` | outcome -> list of reasons; `[]` = takes none; `"any"` = any non-empty string |
| `tools` | role -> wire path name (`{"verify_identity": "check_identity"}`) |
| `fields` | role -> {canonical field -> wire field} (`{"create_promise": {"date": "promise_date"}}`) |
| `customer_id_field` | wire name of the customer id |
| `hint_once` | swap hint once per call, then counted as wrong (true) |
| `passed_field_omits_all_verified` | a field that already passed answers without `all_verified` (true) |
| `note_product_unchecked` | add_note accepts any or no product_id (true) |
| `reason_rejected_on_reasonless` | a reason sent with promise/paid is rejected (true); off: ignored, stored as null |

Error texts use the wire field names (`promise_date must be YYYY-MM-DD`); the ledger keeps the canonical names so the kit's scorer reads it.

## Differences from the organizers' bank

None known on the recorded behaviour (26 of 26 sequences identical). Guessed, never recorded:
unknown case on `/practice/sessions` answers 404; `team` is a hash of `x-team-key`; a fault on a closed call still answers
"the call is already closed" (closed check before fault); abbreviated month names (`21 Jul 1992`) are not readable;
`slow_ms`, `fail_on_call`, renamed tools and fields, and all profile switches are our additions.
