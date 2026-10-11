# Synthetic briefs C to J: manifest

Eight invented collections-call briefs with their own tool API files and practice cases, written 2026-10-11 to test the reader and the emitter on material they have never seen. Everything is synthetic and in English. Nothing here is copied from the public briefs A and B; the rules and values differ everywhere, the structure is deliberately similar because the hidden briefs are "the same kind of call with different rules".

Authoritative constraints followed (runs/night/facts.md): every `api.json` has exactly the seven public tool names (`verify_identity`, `get_account`, `create_promise`, `schedule_callback`, `transfer_to_agent`, `add_note`, `close_call`); only fields, allowed values, response shapes and the calendar vary. Each brief states its own holidays and business-day definition. `now` varies across cases. Every brief carries the five talking styles on at least two cases and at least one case whose correct outcome is a non-promise.

## Conventions in cases.json

- Format is that of `kit/build-the-builder/public-test-set.json` (id, brief, family, level, title, variables, identity, products, script, expected, checks), plus an optional `style`, `faults` and `third_party`.
- `products` use the field names of that brief's `api.json` (`kind`/`type`/`product`, `overdue_amount`/`arrears`/`past_due_cents`/...). Product ids are `p1`, `p2`, `p3` in `get_account` order.
- `expected.promises[].amount` is in the brief's own unit: a number, an integer in cents (E), or a two-decimal string (I). `expected.notes[].reason` holds the `flag` value for J; `expected.outcome` / `expected.reason` hold J's `result` / `detail` and G's upper-case codes.
- `identity` keys are the ones the kit's persona builder knows (`date_of_birth`, `phone_last4`, `postcode`, `birth_year`, `company_number`, `founded_year`). Brief F sends the date of birth as `birth_date` in its API; the case key stays `date_of_birth` so the persona says it right.
- Every expected date was computed by hand from the brief's own rule and calendar and then re-derived by `_tools/derive.py` (`_tools/validate.py` runs both checks; see each README for the table).

## The eight briefs

| Brief | Form | Files | Bank, currency | Identity (limit) | Products | Deadline rule | Floor | Attempts | Hardship | Dispute | Confirmation | Recording notice |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | clean, numbered rules | brief.md | Halvard Credit Union, EUR in words | postcode + birth year (2 per question) | 1 (`kind` card/loan/overdraft) | by amount: 10th calendar day rolled back, or 5th business day | 25 % rounded up | 1 (floor on deadline) | always `welfare` hand-over | close `no_pledge`/`disputed` | email sentence | exact sentence |
| D | clean, prose sections | brief.md | Marlowe & Finch, GBP in words | dob + postcode + phone (3 total) | 1 to 3 (`accounts`) | by days in arrears: 14/7/3 calendar days rolled forward | `minimum_due` | 2 (next business day, then floor on deadline) | offer `vulnerable_customers` once | `add_note dispute`, call stops | email sentence | free wording with "recorded" |
| E | clean, tables | brief.md | Northgate Savings, USD in cents | company number + founded year (2 total) | 1 to 3 | by amount: 15th / 8th business day | 30 % rounded up to the dollar | 0 | support phone number, no transfer | note `disputed`, continue | letter sentence | none |
| F | clean, broken English prose | brief.md | Cresta Bank, EUR in words | date of birth only (3) | 1 (`product` object) | last working day of this/next month, or 5th working day | `monthly_instalment` | 1 (minimum on limit) | always `care` transfer | close `refused`/`dispute` | SMS sentence (no tool) | exact sentence |
| G | raw: mail, policy, memo, codes | 4 files | Ashworth Mutual, GBP | dob + phone (memo: 2 per question) | 1 to 3 (`CC`/`PL`/`HP`) | by days in arrears: 10th / 6th / 3rd business day (memo) | 25 % (memo) | 1 (memo) | offer `financial_support` once (renamed) | note `DISP`, continue | text message sentence (memo) | exact sentence (mail) |
| H | raw, with a contradiction the memo resolves | 4 files | Portmann Bank, EUR | postcode + birth year (2 total) | 1 to 3 | by amount: 14/7/4 calendar days rolled back (memo adds the 4) | `floor` field (memo) | 2 (both on the deadline; memo resolves 6.1 vs 6.3) | always `wellbeing` transfer (renamed) | `add_note not_mine/already_closed/amount_wrong`, call stops | SMS sentence | withdrawn by memo |
| I | raw, US consumer finance | 4 files | Tamsin Finance, USD as strings | dob + ZIP + phone (2 per question) | 1 to 3 | by days late: 10th / 5th / 2nd business day (memo) | `min_due` field (memo) | 1 (3rd business day or deadline) | offer `hardship_team` once (renamed) | note `dispute`, continue | email sentence (memo) | none (mail) |
| J | raw, lettered sections | 4 files | Kestrel Bank, GBP in words | dob + postcode (3 total) | 1 to 3 (`debts`, incl. `mortgage_arrears`) | by amount: 10th / 4th business day; mortgage arrears always 3rd (memo) | `minimum` field (memo) | 2 (last business day of the week, then minimum on deadline) | offer `customer_care` once (renamed) | flag `disputed`, continue | none (memo withdraws it) | required, free wording |

Other axes: callback windows (C next business day only 09-17; D today or next two business days 09-20; E 08-18 and callbacks as the only route to a person; F tomorrow or the first working day after, never today, 10-18; G next business day only 09-17; H and J today or next business day 09-18; I 08-20). Human request: at once (C, H by mail) or after one "can I help" (D, F, G, I, J) or a callback (E). Do-not-call rule in C, D, E, F, G, I, J (H has none). Complaints rule in G and J. Field renames: `client_ref` (C, F, H), `customer_ref` (G), `account_no` (J); `question`/`answer` (C, D, H), `check`/`value` (J), `birth_date` only (F); `pay_date` (C, E, F, H), `promise_date`/`promise_amount` (D), `pay_by` (J); `callback_date`/`callback_time` (C, E); `flag` (J); `result`/`detail` (J). Response shapes: `wrong_left_on_question` (C), `wrong_total` (D, H, J), `wrong_answers_left` (E), `tries_left`/`matched` (F), `wrong_on_this_field` (G, I); `accounts` (D), `debts` (J), single `product` (F).

## Failure modes of facts.md item 6, where each is tested

| Failure mode | Cases |
|---|---|
| "the full amount" as words in a product slot | C-01 |
| dates in words, year included; "fourteen oh three eighty-eight" | D-01, G-03, I-01; F-01 |
| full stop after a number | E-03, H-04, I-02 |
| two things in one message ("8864. How much do I owe?") | G-01 |
| "I do not want to be transferred" after a support offer | D-03, G-06, J-05 |
| "paid it off last year, I owe nothing" is a dispute | C-04, H-05 |
| hardship plus a concrete amount and date in one breath | C-05, F-04, H-06 (transfer wins); D-03, J-05 (recorded) |
| human or plan request right after the promise is recorded | F-06, H-03 |
| third party who offers to pay | C-02, E-02 |
| refusal that is only "I will have to see" | D-06, F-02 |
| vague period then "I do not know exactly" | C-03, I-05 |
| full amount too much and "you tell me" | C-03, H-02, J-02 |
| wrong answer then the right one | C-04, D-05, E-06, H-05, I-05 |
| three wrong answers split across two questions | D-01 (and G-03: two on one question under the memo) |
| never confirms the name ("go ahead", "hello?") | E-03, H-01 |
| goodbye while the agent still has a question | C-06 |
| tool failure on create_promise | not included: the mock bank's `faults` field needs the harness; add `"faults": [{"tool": "create_promise", "fail_first_n": 1}]` to any promise case to exercise it |

`now` values cover a Friday 17:30 (C-01, D-02, E-02, F-04, H-02, I-01, J-01), Saturdays (C-02, D-04, E-06, F-03, G-04, H-04, I-04, J-03), the day before a holiday (D-01, E-01, G-01, H-01, I-01, I-03), month end (C-04, D-03, E-03, F-05, G-03, H-03, I-02) and late evenings (C-03, D-03, E-03, F-05, G-06, H-06, I-02, J-04).

## Review

Codex (`gpt-6-astra`, reasoning effort high, read-only, from a temporary directory, files in the prompt) reviewed each brief against: internal consistency, every case's expected values recomputed by hand from the brief's calendar, OpenAPI validity and the seven fixed tool names, judgeable checks, no copying from A/B, facts.md items 2, 4 and 7. Reviews are saved as `<letter>/review-roundN.md`.

Three rounds were run on all eight briefs (every brief changed after each round). Every round ended **FIX** for every brief; no brief reached PASS. The nature of the findings changed from round to round, and the date arithmetic agreed with every expected value in all three rounds (the only round-1 disagreement, G-02's persuasion date past the HP deadline, was a rule gap, fixed in the memo).

| Brief | Round 1 | Round 2 | Round 3 | Remaining findings after round 3 (not re-reviewed) |
|---|---|---|---|---|
| C | FIX: copied sentence, rule 41 vs 24, rule 31 closing after an accepted offer, third-party vs name check, precedence of 16/32/41/42, do-not-call after a pledge, tool failures, tiny-balance floor, id convention | FIX: more simultaneous triggers, outcome after a pledge for rules 39/40/45, verify/get_account failures, past dates, "noted" before `ok` | FIX: rule 50 whitelist too narrow (BLOCKER, fixed), "card" in rule 43 (fixed), add_note failure wording (fixed), README count (fixed) | none known beyond the generic ones below |
| D | FIX: dispute before/after recording, notes vs transfers, do-not-call vs closing, hardship note scope, duplicate attempts, deceased goodbye, ids | FIX: floor "once" vs attempts, dispute during disclosure, do-not-call note scope | FIX: "noted" before verification (fixed), dispute note on a promised account (fixed), repeat of a refused offer by attempt two (fixed), add_note failure (fixed), arrears over 60 days have no band (open), all-optional response properties (open) | over-60-day accounts; schema optionality |
| E | FIX: two copied stock sentences, "more time" vs dates, first question on non-business days, do-not-call after a promise, hardship note scope, letter sentence without a promise, tiny-balance floor, ids, E-01 check | FIX: `promise` row vs later callback, one-date-for-all on a weekend, arrangement vs human precedence, callback `ok` | FIX: close_call in the retry rule (fixed), `promise` row vs later callback (fixed round 2, reviewer wants it in the callback rows too: open), E-05 hardship vs agreed-unrecorded (fixed), week definition (open), E-05 check (fixed) | callback rows after a promise; "following calendar week" undefined |
| F | FIX: try closes refused when accepted, deceased goodbye, hardship vs do-not-call, copied stock sentences, F-06 "pays" | FIX: hardship vs do-not-call before verification, first question on non-working days, callback day retry, "Is it a scam?" | FIX: do-not-call after a promise (fixed), close_call retry (fixed), "noted" before `ok` (fixed), impossible dates vs failures (fixed), failed-transfer continuation for plans/people (open), schema optionality (open) | failed plans/people transfer continuation |
| G | FIX: persuasion date past the deadline (G-02), notes vs transfers, ids, copied condolence, callback/transfer `ok`, G-02 not discriminating | FIX: mail vs memo precedence, past persuasion dates, minimum repeated, failed non-hardship transfers, failures of other tools, README "six" | FIX: §9 vs §10 after a promise (fixed), complaint + DNC in one utterance (fixed), hardship + plan (fixed), over-90-day products (open), schema optionality (open), FAIL/ERR descriptions (open) | over-90-day products; code descriptions |
| H | FIX: copied sentence, 5.2 vs 6.5, attempt two repeats, dispute during disclosure, 8.4 exceptions, dispute vs 9.1, hardship after a pledge, H-02 not discriminating (floor and date), ids | FIX: 3.4 vs 9.1 after a pledge, attempt one repeats, H-04 Saturday question, callback/transfer failures, H-06 check | FIX: dispute vs hardship priority (fixed), failed front_desk before verification (fixed), add_note failure (fixed), schema (open), code descriptions (open), H-04 check wording (fixed), H-02 "you tell me" unsolicited (fixed) | schema optionality; code descriptions |
| I | FIX: two copied sentences, notes vs transfers, 7.4 scope, do-not-call after a promise, refusal note when accepted, ids | FIX: hardship note vs earlier notes, README do-not-call wording | FIX: do-not-call vs earlier notes (fixed), failed plan/human transfer continuation (fixed), add_note failure (fixed) | none known beyond the generic ones below |
| J | FIX: attempt one past the deadline, flags vs transfers, B5/B6 vs H1, hardship + plan, copied condolence, J-02 not discriminating, ids | FIX: B6 vs H1 without an arrangement, J-02 title/script | FIX: failed complaint transfer after an arrangement (fixed), refused first offer repeated by attempt one (fixed), add_note/close_call failure (fixed), README "recording notice" (reviewer misread: the mail requires it; left), schema optionality (open) | schema optionality |

**Generic findings left open on purpose** (they apply equally to the public briefs A and B, and spelling them out further would make the synthetic briefs stricter than any real one): all response properties in every `api.json` are optional (as in the public file); products older than the last deadline band (60 or 90 days) have no computable deadline (Brief A has the same 45-day edge); a judge cannot see `now`, so a check that says "today" relies on the ledger date.

**Post-round-3 edits (applied after the last review, not re-reviewed):** C rules 16, 43, 50, 53; D dispute note on a promised account, do-not-call wording before verification, note failure; E hardship candidates, close_call retry; F do-not-call after a promise, close_call retry, impossible dates vs failures; G complaint vs DNC, hardship vs plan, PTP after failed transfers; H dispute priority, failed transfer before verification; I do-not-call vs earlier notes, failed plan/human transfer; J failed complaint after an arrangement, any repeated offer skipped; cases H-02, H-04, E-05 wording. `_tools/validate.py` still reports 0 problems and every expected date re-derives.

## Where a reader is most likely to misread each brief

- **C**: (1) rule 19, the under-500 deadline is a calendar count rolled **back**, the 500-or-more one a business-day count; (2) rule 23, "next Friday" is the first Friday after today, not the following week's; (3) rule 32 versus rule 30, hardship hands over even when a date or amount is named in the same breath, and rule 42 hands over a human request with no question.
- **D**: (1) the three-question check with a **total** limit, so the third wrong answer can fall on the second question; (2) the dispute paragraph: one `add_note dispute` and the call stops, no other notes, even with promises agreed on other accounts; (3) the two attempts: the first is on the **next business day**, not the end of the week.
- **E**: (1) amounts in **cents** everywhere in the tools but dollars in speech; (2) "no persuasion attempts" means a refusal is final and still gets a `declined` note; (3) `transfer_to_agent` exists but is never called; a human or a plan is a `schedule_callback` with a `reason`, for the next business day at 10:00.
- **F**: (1) the limit for 15 days late or less is the last working day of **this** month unless fewer than three working days remain counting today; (2) `verify_identity` takes `birth_date` only and `get_account` returns a single `product` object; (3) a do-not-call wish is an `add_note` without a product, and "I will have to see" is a refusal.
- **G**: (1) the memo's per-question limit replaces the policy's total limit; (2) the memo withdraws attempt two, so one attempt only, on the last business day of the week (next week when today is that day); (3) codes are the upper-case ledger codes, the queue in the call is `financial_support`, and the confirmation is the text message sentence.
- **H**: (1) 6.1 says one attempt and 6.3 two; the memo says two; (2) deadlines are calendar days moved **back** to the last business day, with the memo's third band above 2,000; (3) the mail overrides 6.5: a human request is transferred at once, and the opening has no recording sentence.
- **I**: (1) amounts are two-decimal **strings** in every tool call; (2) numeric dates are month-day-year, dates in words are converted, and the "postcode" is the ZIP; (3) the single attempt lands on the 3rd business day **or the deadline if earlier**, and the memo's bands (5th, 2nd) replace the procedure's.
- **J**: (1) mortgage arrears always get the 3rd business day whatever the amount; (2) the amendment withdraws the confirmation sentence with **no** replacement; (3) `close_call` uses `result` and `detail`, `add_note` uses `flag`, and the human and plan transfers differ from the complaints rule, which stops everything at once.

## Open doubts

- **Over-specification risk.** Round 1 of the codex review asked for precedence rules the public briefs A and B do not have either (notes written only at the close, do-not-call after a recorded promise, persuasion dates capped at the deadline, tool-failure branches for callbacks and transfers, a priority order between hardship, human, plan and do-not-call). They were added, mostly as extra memo items in the raw briefs. A hidden brief may well leave these gaps open; the reader should not depend on them being spelled out.
- **Unused tool in E.** Brief E keeps `transfer_to_agent` in the API but never calls it (the evening line routes humans to a callback). This is a legitimate variation (Brief A never uses `add_note`) but it is a guess about the hidden briefs.
- **Expected-value units.** `expected.promises[].amount` follows the brief's unit (cents in E, strings in I). A harness comparing against the ledger must do the same conversion the agent does.
- **Styles are declared, not simulated.** The `style` field is passed to the kit's persona builder; whether the simulated customer actually splits numbers or self-corrects depends on the persona model.
- **Judge wording.** Checks were tightened in round 1 where a literal reading would penalise a compliant call (E-01, C-05). Other checks still assume the judge reads "before any ask" as "before any payment question".
- **No `faults` cases.** No synthetic case exercises a failing `create_promise`; add the public set's `faults` field to any promise case when the harness supports it.
