# Frozen interfaces (2026-10-10, 17:00 UTC)

Everything below is shared by every lane. Change it only through the integration owner, with a note in this file.
The design behind it lives in the local research notes (`research/builder-architecture.md`, its addendum,
`research/oracle-design.md`); this file is the executable contract.

## 0. Repository layout

```
builder/            build.py (one command), readers/, emitter/, engine/, pipeline/
bank/               server.py, up.sh, replay/ (recorded sequences as acceptance tests)
harness/            chat transport, structured customer, ledger scorer, transcript checker, simulation runner
families/           parametric scenario families (the independent key)
fixtures/           frozen case files
spec/               this file plus the JSON Schemas
tests/              pytest, offline only unless marked live
kit/build-the-builder/   the organizers' kit, untouched
```

Python 3.12 in `.venv` (`uv venv --python 3.12 .venv`), standard library plus `claude-agent-sdk`, `jsonschema`, `pytest`.
Secrets only from `.env` (never printed, never committed). Repo text is English only.

## 1. Rule table

`spec/rule_table.schema.json` is the authority. Summary:

```
rule_table                        (policy content; hashed as canonical JSON, sort_keys, no run_metadata)
  schema_version: "1.0"
  documents[]:    {doc_id, kind, issue_date, role: authoritative|amends|informational|superseded, evidence_units[]}
  units:          {unit_id: {text, doc_id, offset, kind: sentence|row|heading|item|quote, parent}}   (lossless segmentation)
  dispositions:   {unit_id: {kind: obligation|definition|example|informational|superseded|unreadable, refs[], reason}}
  obligations[]:  see below
  parameters:     {dotted.path: value_entry}
  amendments[]:   {amending_unit, amended_units[], path, old, new, authority, issue_date, effective, scope, quotes[]}
  wire_map:       {tools: {tool_name: {path, method, request_fields{}, response_fields{}}},
                   concepts: {concept: {tool, field, wire}},
                   enums: {tool.field.value: {obligations[] | unused: reason}}}
  phrases[]:      {id, kind: mandatory|forbidden, text, exact: bool, obligation, when}
  examples[]:     {unit, input, expected}
  open_questions[]: {topic, readings[], taken, rule}
  plan[]:         {id, type, params, obligations[], units[], per_item, gates[]}       (addendum; default = collections order)
run_metadata      (not hashed): models, timings, capability_report, assurance, hashes
```

**Obligation**

```
{ "id": "O-<unit>.<n>", "units": ["d1.s41"], "quote": "...",
  "when": {"state": <state>, "guards": ["product.band == 'late'"], "event": <event or null>},
  "then": [<action>...],
  "kind": "state|communication|ordering|prohibition|definition",
  "scope": "call|product|document:<doc_id>",
  "exception_of": "O-..." | null, "precedence": ["before O-..."], "status": "effective|superseded|informational",
  "effective": {"from", "to", "anchor", "inclusive"} | null }
```

`state` vocabulary: `pre_verification, identity, verified, third_party, disclosure, negotiation, readback, recording, closing, any`.
`event` vocabulary: the engine event kinds of section 2 plus `customer.<free>` for anything the engine does not model (then the obligation is `prompt_only` or `unsupported`).
`then` actions: `say{exact|content}`, `ask{question_id}`, `offer{amount_rule, date_expr}`, `tool{name,args}`, `close{outcome,reason}`,
`forbid{what}`, `transfer{queue}`, `note{reason,text}`, `callback{}`, `defer{what}`, `count{counter,max}`, `stop`, `other{text}`.

**Value entry**: `{value | windows[{value, effective}], type, quotes[], obligations[], confidence: quoted|derived|not_specified}`.
Wire strings are exact. `not_specified` is explicit; no silent defaults.

**Well-known parameter paths** (absent when the brief is silent):
`party.confirmation_words`, `party.max_asks`, `third_party.callback.window{days_expr,start,end,inclusive}`, `identity.questions[]{id, wire_field, type: date|digits:N|year|text, parse_rule, order}`,
`identity.max_wrong`, `identity.max_wrong_per_question` (2026-10-11, engine-gaps: per-question limit; a question entry may carry `max_wrong`), `identity.hint_rule`, `identity.decline_rule`, `calendar.holidays[]`, `calendar.business_days`, `bands[]{id, condition, deadline_expr, attempts}`,
`dates.vague_rule`, `dates.this_next_rule`, `dates.bare_weekday_rule`, `dates.numeric_order` (2026-10-11, engine-gaps: month_day_year | day_month_year for customer dates in numbers), `amounts.floor_expr`, `amounts.range_rule`, `attempts[]{n, amount_rule, date_expr, band}`,
`situations{hardship, paid, dispute, plan_request, human, scam, robot, deceased, wrong_number, dont_want_to_talk, do_not_call}` (do_not_call: 2026-10-11, engine-gaps), `recording.retries`, `multi.max_items`, `multi.order`,
`closing.rows[]{outcome, reason, triggers[], precedence}`, `call_variables[]`, `products.labels{code: spoken name}` (2026-10-11, engine-gaps).

**Expression language** (dates and amounts): arithmetic, `min`, `max`, `round(x, step, mode)`, fields of `product`, `customer`, `call`;
`today`, `tomorrow`, `business_days_after(anchor, n)`, `calendar_days_after(anchor, n)`, `next_business_day(d)`, `on_or_next_business_day(d)`,
`this_weekday(w)`, `next_weekday(w)`, `last_business_day_of_week(d)`, `last_business_day_of_next_week(d)`, `end_of_month(d)`, `deadline`, `deadline - n`,
`in_window(t, start, end, inclusive)`. Calendar named `default`. Unparseable is a mechanical failure; unevaluable disables the dependent family and marks the capability.

**Plan** (addendum): types `party, verify, consent, say, ask, fetch, disclose, negotiate, readback, record, note, close, prompt_only`;
`transfer` and `callback` are situation fragments. Default plan: `party, verify, fetch, disclose, negotiate, readback, record, note, close`.
Hard rules: first `verify` before `fetch`, `disclose`, `record`, promise-block notes; `close` last. Inserted/moved/repeated stages need a cited unit.

## 2. Engine

Module `builder/engine/`. Pure Python, standard library only, no I/O, deterministic. The same code must run inside a Freya `code_exec`
node and in a post-hook, so it is also rendered as a single self-contained snippet (`engine/snippet.py` builds it): reads `vars`, writes `vars`,
contains no `{{` or `}}`, never raises (every path sets fallbacks).

```python
def step(state: dict, events: list[dict], table: dict, now: str) -> tuple[dict, dict]:
    """Apply one observation bundle. Returns (new_state, outputs). Pure."""
```

**State** (JSON-serialisable; stored as a JSON string in `vars["engine_state"]`):

```
{ "rev": int, "stage": str, "party": "unknown|customer|representative|third_party|wrong_number|deceased",
  "identity": {"q_index": int, "wrong": int, "wrong_by_q": {qid: int} (only with a per-question limit), "hinted": bool, "partials": {qid: str}, "passed": [qid], "state": "pending|verified|failed|declined"},
  "callback": {"date": str|null, "time": str|null, "invalid": int},
  "items": [ {"item_id", "type", "label", "past_due", "floor", "days_late", "band", "deadline", "attempts_allowed",
              "attempts_used", "offers_made": [{"amount","date","kind"}], "floor_offered": bool, "too_much": bool,
              "agreed": {"amount","date"}|null, "readback_version": int, "confirmed_version": int,
              "recorded": bool, "record_failures": int, "noted": {"reason","text"}|null, "status": "open|agreed|recorded|noted|skipped",
              "vague_asked": bool } ],
  "current_item": int, "pay_today_asked": bool,
  "global": {"hardship": bool, "support_offered": bool, "human_asked_once": bool, "dont_want": int, "pending_transfer": str|null,
             "paid_claim": bool, "dispute": bool, "turns": int, "pending_lines": [str]},
  "commits": [ {"tool", "args", "result": "ok|failed|unknown", "item_id"} ],
  "close": {"outcome": str, "reason": str|null} | null }
```

**Events** (what the observation layer reports; one bundle per customer turn):

```
{ "kind": <kind>, "item": item_id|null, "amount": number|null, "date_text": str|null, "time_text": str|null,
  "text": str|null, "span": str|null, "qid": str|null }
```

Kinds: `party_confirmed, party_other, party_wrong_number, party_deceased, id_answer, id_decline, question_back, callback_offer,
pay_today_yes, pay_today_no, date_proposal, amount_proposal, too_much, refuse, accept_offer, vague_period, confirm, deny, change,
paid, dispute, plan_request, human, hardship, scam_question, robot_question, dont_want_to_talk, other`,
plus `do_not_call` when the table has that situation (2026-10-11, engine-gaps).

**Outputs**:

```
{ "engine_next": str,              # next stage/node key for routing (emitter maps it to transitions)
  "say_next": str,                 # the content the dialogue model must convey now (may be empty)
  "mandatory_lines": [str],        # exact sentences to speak before anything else (tts)
  "readback_text": str,            # versioned read-back, empty if none
  "writes": [ {"tool", "args", "item_id", "intent_key"} ],   # bank writes to run now, in order
  "close": {"outcome","reason"}|null,
  "what_to_do_next": str,          # one plain instruction line for the model
  "ask_clarify": bool }
```

Write results come back as events of kind `tool_result` with `{"tool", "item", "result": "ok|failed|unknown", "data": {...}}`.
`tool_result` events are applied with `step` too. Three result classes always: `ok` (`data.ok` true), `failed` (`ok` false returned),
`unknown` (timeout, 5xx without body, transport error).

**Calendar core** `builder/engine/calendar.py`: the expression language above, evaluated against `(now, holidays, product, customer)`.
Generalised from `scenarios/brief_calendar.py`; every function pure.

## 3. Fixture and session format

One case (superset of the kit's `public-test-set.json` entries, so the kit's scorer and runner accept it):

```
{ "id": "EXT-001", "brief": "A|B|<hash>", "level": "easy|medium|hard", "family": str, "title": str,
  "variables": {"first_name","last_name","title","now"},           # customer_id is assigned by the bank session
  "identity": {"<wire_field>": "<answer>"},
  "products": [ {"product_id","type","card_last4","past_due","days_late","minimum_payment","instalment_amount"} ],
  "faults": [ {"tool": "create_promise", "fail_first_n": 1} | {"tool": ..., "slow_ms": 20000, "on_call": n} ],
  "profile": { bank behaviour switches, see bank/server.py },
  "third_party": bool,
  "script": str,                      # persona prose (kit style)
  "turns": [ {"say": str, "events": [event...], "expect_agent": {"offer": {...}|null, "says": [str], "not_says": [str]} } ],
  "style": "pieces|corrects|talkative|asks_back|in_words"|null,
  "checks": [str],                    # judge sentences, kit style
  "expected": {"outcome","reason","promises":[{product_id,amount,date}],"notes":[{product_id,reason}],"callbacks":[{date,time}],"transfers":[{queue}]},
  "expected_events": [ {"stage", "tool", "args_subset"} ]      # optional ordering key
}
```

Bank session: `POST /v1/practice/sessions {"case": id}` or `{"customer": <case object>}` returns `{"ok": true, "variables": {...customer_id}}`.
Ledger: `GET /v1/practice/ledger/<customer_id>` in the organizers' shape (see `research/bank-recorded-behaviour.json`).
Result classes for a run: `PASS | FAIL | INVALID | UNKNOWN`, with `reasons[]`, `call_id`, `customer_id`, `agent_version`.

## 4. Candidate manifest and slots

Slot naming: `<brief_slug>-<run_id>-<variant>` where `variant` is `test` (our bank) or `final` (official server). Slots are never reused.
`builder/.freya-agents.json` keeps slot to workflow id (kit `save_workflow` state file).

```
{ "run_id": "20261011-1700-a", "brief_path", "brief_hash", "tools_hash", "table_hash"|"none", "plan_hash"|"none",
  "source_commit": "<40 hex>", "variant": "test|final", "slot", "workflow_id", "agent_id", "version": int,
  "export_path", "export_hash", "bank_url", "endpoint_check": "clean|<diff>", "model_config": {...},
  "tiers_run": ["0","1"], "results": {"PASS": n, "FAIL": n, "INVALID": n, "UNKNOWN": n}, "started", "finished" }
```

Trace: `runs/<run_id>/trace.log` (plain text) and `trace.jsonl`; one line per model call `{model, purpose, tokens, seconds}`.

## 5. Platform facts every lane relies on

- Three model calls per turn: extraction, routing, dialogue. Routing on variables is deterministic. Transitions fire on `not_equals ""` after a dispatcher cleared the field.
- Booleans arrive as strings; route on string flags written by code. No `{{`/`}}` in code. Mapping paths start with `data.`.
- Tool result envelope: `{status, data, message, status_code, header}`; post-hook may add `data.what_to_do_next`.
- Chat API: customer speaks first, initial code node may be skipped, closing turn may 504. Simulations are the official path.
- Organizers' bank rejects a `reason` on `promise`/`paid`; absent field accepted, empty string rejected.
- Agent model `experimental-5` cannot run locally.
