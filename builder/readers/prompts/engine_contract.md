# Engine contract: the exact shapes the call engine reads

Your table is executed by a fixed call engine. It reads only the parameter paths, value shapes, phrase ids and
trigger names below. Use them exactly; a value in another shape is ignored and the rule is lost. Everything in
angle brackets is a placeholder you fill from the brief; never copy a placeholder literally. Where the brief has
no such rule, give the path with `"confidence": "not_specified"` and no `value`, and leave the phrase out.

## Parameter values (the `value` of each entry)

- `party.confirmation_words`: list of strings; the customer's own name is written `{customer_own_name}`.
- `party.non_confirmation_words`: list of strings.
- `party.max_asks`: integer, total number of right-party asks including the first.
- `third_party.callback.window`: `{"days_expr": [<one expression per allowed day, e.g. "today", "next_business_day(today)">],
  "start": "HH:MM", "end": "HH:MM", "inclusive": true|false, "later_than": "now" | null}`.
- `third_party.callback.max_invalid`: integer, how many out-of-window proposals end the attempt (the first plus the retries).
- `identity.questions`: list of `{"id": <wire field name>, "wire_field": <exact enum value of the verify tool's field>,
  "type": "date" | "digits:<N>" | "year" | "text", "order": 1.., "text": <the question>,
  "parse_rule": <how to read the answer; for a date say "day, then month, then year" or "month, then day, then year">}`.
  Use the wire field itself as `id`.
- `identity.max_wrong`: integer (total wrong answers that end the check). Set it only when the brief states a total.
- `identity.max_wrong_per_question`: integer, only when the brief's limit is per question (two wrong answers on the
  same question end the check; one wrong answer on each of two questions does not). A question entry may carry its own
  `max_wrong` instead when the limits differ per question.
- `identity.hint_rule`: `{"hint": <exact hint value the verify tool returns>, "ask": <what to ask>, "counts_as_wrong": true|false}`.
- `identity.decline_rule`: `{"explain_once": <what to explain>, "max_declines": <integer: declines that close>,
  "question_about_call_counts_as_decline": true|false}`.
- `calendar.holidays`: list of ISO dates. `calendar.business_days`: a string such as "Monday to Friday" or a list of weekday names.
- `bands`: list of `{"id", "condition", "deadline_expr", "attempts": <integer>}`; `condition` is an expression over
  `product.<field of the account tool's product>` (chained comparisons allowed: `1 <= product.days_late <= 7`).
- `dates.non_business_rule`: an expression over `date` giving the replacement date (e.g. `next_business_day(date)`).
- `dates.after_deadline_rule`: an expression giving the date to offer instead (e.g. `deadline`).
- `dates.vague_rule`: `{"ask_once": true|false, "then": <expression for the date to propose after that>}`.
- `dates.this_next_rule`: `{"this": "this_weekday(w)" | <other>, "next": "next_weekday(w)" | <other>}`; the engine's
  `this_weekday` is the day in the current calendar week, `next_weekday` the day in the following calendar week.
- `dates.bare_weekday_rule`: `{"rule": "next_occurrence" | "current_week"}` or not_specified.
- `amounts.floor_expr`: ONE expression, conditional with `a if cond else b` (never `?:`), e.g.
  `product.<field_a> if product.type == '<type>' else product.<field_b>`.
- `amounts.range_rule`: `{"min": "floor", "max": "product.<field>", "inclusive": true|false, "below_floor": <text>}`.
- `amounts.too_much_rule`: `{"offer": "floor", "once": true|false, "say": <text>}`.
- `attempts`: list of `{"n": 1.., "amount_rule": <"floor" | "same" | expression; `item.too_much` is true once the
  customer said the full amount is too much>, "date_expr": <expression; `deadline` is the item's deadline>,
  "band": <band id> | "any"}`.
- `situations`: object; each key present only when the brief has the rule:
  - `hardship`: `{"obligation", "triggers": [..], "say": .., "offer": .., "transfer_queue": <exact queue or null>,
    "accept_close": [<outcome>, <reason>], "decline_close": [<outcome>, <reason>], "persuasion": "none" | ..,
    "voluntary_promise": "record" | "drop"}`
  - `paid`, `dispute`: `{"obligation", "say"?, "close": [<outcome>, <reason or null>],
    "multi": {"note": <note reason>, "continue": true, "obligation"} (only when one product's claim does not end the call)}`
  - `plan_request`, `human`, `support`: `{"obligation", "transfer_queue": <exact queue>, "close": [<outcome>, <reason>],
    "ask_first_once": true|false (human)}`
  - `scam`, `robot`, `unknown_question`: `{"obligation", "say": .., "then": "continue"}`
  - `deceased`, `wrong_number`: `{"obligation", "say_exact"?: .., "close": [<outcome>, <reason>]}`
  - `dont_want_to_talk`: `{"obligation", "count": <integer>, "close_verified": [..], "close_unverified": [..]}`
  - `do_not_call` (only when the brief has a rule for a customer who asks not to be called again, distinct from not
    wanting to talk now): `{"obligation", "note": <exact note reason or null>, "close_verified": [<outcome>, <reason>],
    "close_unverified": [<outcome>, <reason>], "after_promise_close": [<outcome>, <reason>] (only when the brief says
    what closes after a recorded promise)}`. The engine writes the note, ends the call at the first request and makes
    no transfer.
  - `service_error`: `{"obligation", "note": <note reason>, "continue": true}` (only when a failed write is noted per product)
- `recording.retries`: integer, extra tries after the first failure.
- `multi.max_items`: integer. `multi.order`: string. `multi.pay_today_once`: true when the pay-today question is asked once
  for all products. `multi.common_date_rule`: string, set only when one date named for all products is recorded on each
  product's own deadline where it is too late. `multi.readback`: string.
- `notes.reasons`: list of exact note reasons, set only when the brief requires per-product notes.
  `notes.on_transfer`: string. `transfer.unrecorded_rule`: string, what happens to agreed-but-unrecorded promises on a transfer.
- `closing.rows`: list of `{"outcome", "reason" (null for none), "triggers": [<engine trigger names, below>],
  "precedence": <integer, lower wins>, "obligations": [<obligation ids>], "units": [<unit ids>], "line": <phrase id or omitted>}`.
- `call_variables`: list of variable names.

## Closing-row triggers (engine vocabulary; each row needs at least one)

`promise_recorded`, `paid_claim`, `all_items_noted_paid`, `transfer_done:<exact queue>`, `attempts_exhausted`,
`dont_want_twice_verified`, `dont_want_twice_unverified`, `hardship_support_declined`, `dispute`,
`record_failed_twice`, `identity_failed`, `identity_declined`, `callback_booked`, `callback_refused_twice`,
`wrong_number`, `deceased`, `party_unclear_twice`, `fetch_failed_twice`, `first_non_paid_note:<exact note reason>`.
Rank `precedence` from the brief's precedence statements; rows the brief does not rank share a number.

## Phrase ids the engine speaks (use these ids; `exact: true` only when the brief gives the words in quotes)

`opening` (first sentence), `party_question`, `robot_answer`, `callback_question`, `sorry_loss`,
`ask_<identity question id>` (one per identity question), `month_as_word` (the hint retry), `questions_protect`
(the decline explanation), `use_app_or_branch` (after identity failure), `disclosure`, `pay_today` (the first ask),
`rest_overdue`, `below_floor`, `latest_is_deadline` (may use `{deadline}`), `do_you_confirm`, `text_message`
(sentence after a recorded promise), `promise_recorded`, `could_not_record`, `change_in_app`, `paid_takes_day`,
`sympathy`, `support_offer`, `can_i_help`, `scam_answer`, `no_information`, `thanks_goodbye`, `own_deadline_note`,
and `close_<outcome>` / `close_<outcome>_<reason>` for the line spoken with a closing row (referenced by the row's `line`).
Placeholders the engine fills: `{title}`, `{last_name}`, `{first_name}`, `{deadline}`, `{product}`.
A content phrase (`exact: false`) states what to convey, in the brief's words. Forbidden phrases use ids
`forbid_<short name>`; when exact, `text` lists the literal forbidden strings separated by `;`, and `when` states the
scope, starting with "before identity is verified", "someone else", "negotiation" or "always".

## Plan and examples

- `plan`: the generator builds stage types `party, verify, fetch, disclose, negotiate, readback, record, note, close`
  (plus gate types `consent, say, ask, prompt_only`), each at most once, `party` first, `close` last, and
  `negotiate` before `readback` before `record`. `per_item: true` only on `disclose`, `negotiate`, `record` and
  `note`. A `note` stage only when `notes.reasons` is set.
- `examples[]`: write `input` and `expected` so code can evaluate them, choosing a concrete `now` that matches the
  example's premise (a Friday for "said on a Friday"): a date phrase as `{"now": "YYYY-MM-DDTHH:MM", "text": "<customer
  words>"}` with `expected` an ISO date; a computed date or amount as `{"now": .., "expr": "<expression>", "product":
  {..}}` with `expected` the value; a band as `{"now": .., "days_late": N}` with `expected` `{"band", "deadline", "attempts"}`.
