# mock: our bank services on Cloudflare Workers

A port of `bank/server.py` to a Worker (plain JS, no build step, no npm deps). Same tools, answers, error texts and
ledger; replays all 26 recorded sequences of the organizers' practice bank identically (`python -m bank.replay --url ...`).
State lives in one SQLite-backed Durable Object per customer id, which works on the free plan.

```
mock/
  worker/wrangler.toml          name freya-mock, DO binding BANK, migration new_sqlite_classes
  worker/src/index.js           CONTRACT (names, enums) -> TOOL LOGIC (one handler per tool) -> PLUMBING
  worker/data/customers.json    customers keyed by customer id (now: the 13 public PUB cases)
  make_customers.py             test-customers file -> customers.json
  smoke.sh                      every tool + error paths against a URL
```

## Routes (each also works without `/v1`)

| | |
|---|---|
| `POST /v1/<tool>` | a tool call; body carries the customer id. Unknown tool: 404 `not found`; unknown id: 404 `unknown customer_id` |
| `GET /v1/health` | `{"ok": true, "customers": n, "tools": [...]}` |
| `GET /v1/practice/ledger/<id>` | the current conversation's ledger (same shape as the organizers'); `?history=1` adds archived ones |
| `POST /v1/practice/reset/<id>` | archive the current conversation, start a fresh one |
| `POST /v1/practice/sessions` | `{"case": "<id>"}` or `{"customer": {...}}` -> a private `c_...` copy (for our own tests) |

Hosting for days: hidden customers call the same customer id many times. A new conversation starts automatically
(old ledger archived, last 50 kept) when the last tool call is more than 10 minutes old, or when `verify_identity`
arrives after `close_call`; also when that customer's record in customers.json changed. Knobs: `fresh_after_idle_ms`,
`fresh_on_verify_after_close`, `history_keep` in CONTRACT. Two evaluations of one customer at the same time would
share a ledger; nothing in the request tells them apart.

Optional secrets: `TOOL_KEY` (tool calls need `Authorization: Bearer <key>` or `x-api-key`), `ADMIN_KEY`
(sessions/reset need `x-admin-key`). Set with `npx -y wrangler@4 secret put TOOL_KEY` inside `mock/worker`.

## At 20:00: adapt to the case folder

1. **Customers.** `python3 mock/make_customers.py <case>/test-customers.json` writes `mock/worker/data/customers.json`.
   It accepts a list, an object keyed by id, or `{"customers": [...]}`; keys by `customer_id`, else `--id-key` (default `id`).
   Each record needs `identity` (question -> answer), `products` (any fields; `product_id` defaults to p1, p2, ...),
   optional `variables`, `faults`, `profile`. If the file is shaped differently, adjust `convert()`, not the worker.
2. **Contract.** In `src/index.js`, section CONTRACT only:
   - `tools`: role -> wire path name; `fields`: role -> {canonical -> wire field}; `customer_id_field`.
   - enums: `identity_types`, `note_reasons`, `queues`, `outcome_reasons` (the brief's outcome/reason table), `max_wrong`.
   - `python3 -m bank.adapters <openapi.json>` prints the renames and enums it reads from a new OpenAPI file: copy them over.
   A tool whose behaviour changed (new response field, new rule): edit its handler in TOOL LOGIC. A new tool: add it to
   `CANONICAL_FIELDS` and `HANDLERS`. Per customer, a `profile` in customers.json overrides any CONTRACT key.
3. **Test locally:** `cd mock/worker && npx -y wrangler@4 dev --port 8799`, then
   `mock/smoke.sh http://127.0.0.1:8799 <one customer id>` (with `DOB=... PHONE=... PRODUCT=...` from that customer;
   edit the tool/field names in smoke.sh if they were renamed), and
   `.venv/bin/python -m bank.replay --url http://127.0.0.1:8799` (only meaningful while the practice contract holds).
4. **Deploy** (below), smoke-test the deployed URL, put the URL in the agent's tools.

## Deploy

```
cd mock/worker
export CLOUDFLARE_API_TOKEN=...   # token with "Edit Cloudflare Workers" permissions
export CLOUDFLARE_ACCOUNT_ID=...
npx -y wrangler@4 deploy          # prints https://freya-mock.<subdomain>.workers.dev
mock/smoke.sh https://freya-mock.<subdomain>.workers.dev PUB-01
```

A first deploy on a fresh account may ask to register a workers.dev subdomain (dashboard: Workers & Pages).
Redeploy after any edit: state survives redeploys; a changed customer record starts that customer fresh.
Logs: `npx -y wrangler@4 tail`. The smoke test resets its customer at the end (the run stays in that customer's
history), so smoke-testing a customer the evaluators will use is safe.

## Smoke test

```
mock/smoke.sh [URL] [CUSTOMER_ID]     # default http://127.0.0.1:8787 PUB-01; exit status = failed checks
```

34 checks: health, reset, unknown tool/customer, every tool's success and validation errors, the swap hint, wrong-answer
counting, closed-call refusal, ledger, restart after close with history, practice session.

## Deployed

- https://freya-mock.yakuupkeskin.workers.dev (2026-10-11 18:38 CEST), token file ~/.config/cloudflare/workers.env (Edit Cloudflare Workers), `cd mock/worker && npx -y wrangler@4 deploy`.
- Cloudflare blocks the `Python-urllib` user agent (error 1010); curl, node and an empty agent pass. Our Python clients send their own agent string.
- Platform check 18:42: brief A with its tools on this mock, Turkish-speaking customer, PUB-01/02/04/05/06/07/09 all pass.
