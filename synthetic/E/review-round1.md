## FINDINGS

1. **MAJOR — E/brief.md — §2 “Name check”; §9 “Read-back”.** “Am I speaking with {title} {last_name}?” and “Do you confirm?” reproduce sentences from Public Brief A, rules 2 and 34. **Fix:** replace both sentences with original wording.

2. **MAJOR — E/brief.md — §8 “Payment plan or more time” versus §6 date rules.** “I need until next Friday” requests more time and proposes a date. One rule requires an arrangement callback and discarding pending agreements; the other permits a promise. **Fix:** explicitly exclude ordinary promise-date proposals from the arrangement trigger.

3. **MAJOR — E/brief.md — §8 “First question” versus §6 “Valid promise date”.** The mandatory first question proposes payment today even on weekends and holidays, when today cannot be a valid promise date. Calls are not restricted to business days. **Fix:** on nonbusiness days, make the initial proposal for the next business day.

4. **MAJOR — E/brief.md — §4 “Do not call us again”; §8 callback rows; §9 “Changes later”; §10 outcome table.** A request arriving after a successful recording produces conflicting instructions: §10 requires `promise`, while the interruption requires `no_promise / do_not_call` or `callback_booked`. “Nothing agreed is recorded” also fails to distinguish pending agreements from immutable recorded promises. **Fix:** preserve existing recordings, discard only unrecorded agreements, and exclude these interrupted calls from the ordinary `promise` closing row. Specify that prohibitions on notes concern subsequent note calls.

5. **MAJOR — E/brief.md — §8 “Hardship”, “Already paid”, “Dispute”, and “Persuasion attempts”; §10 `no_promise`.** Hardship requires every product without a promise to receive `hardship`, including products already noted `settled`, `disputed`, or `declined`. This creates multiple reasons for one product, with no rule identifying which determines closure. A combined hardship and arrangement request also has incompatible recording instructions. **Fix:** limit hardship notes to unresolved products, and make the hardship and arrangement branches mutually exclusive with an explicit combined-request rule.

6. **MAJOR — E/brief.md — §9 “Success wording” and “Confirmation”.** If every `create_promise` fails twice, the unconditional confirmation instruction still announces a letter confirming an arrangement, although no promise exists. **Fix:** require the letter sentence only when at least one recording succeeds.

7. **MAJOR — E/brief.md — §7 “Floor”; E/api.json — `/get_account` response `products.items.properties.past_due_cents`.** No minimum balance excludes sub-dollar debts. For a $0.50 debt, the floor becomes $1.00, exceeding the full balance and making the permitted amount interval empty. **Fix:** cap the rounded floor at the full past-due amount.

8. **MAJOR — E/cases.json — every case’s `variables` and `products`; expected `product_id` references.** Required `customer_id` values are absent, and products lack the identifiers referenced as `p1` and `p2`. No supplied harness contract defines their injection or mapping. **Fix:** supply these identifiers explicitly, or document their deterministic generation and inclusion in tool responses.

9. **MINOR — E/cases.json — E-01 `checks[1]` (zero-based).** “Both products stated … before any ask” conflicts with mandatory name and security questions before disclosure. The intended payment-stage check is transcript-observable, but its literal wording rejects compliant calls. **Fix:** say “after verification, before any payment question.”

## DATE ARITHMETIC

- **E-01, p1:** Deadline counting excludes Nov 26–27 holidays and weekends: Nov 30 = day 1; Dec 1–4 = 2–5; Dec 7–11 = 6–10; Dec 14–18 = 11–15, so **Dec 18**. Floor = ceil($842.50 × 30%) = **$253 / 25300 cents**. Bare “Friday” = Nov 27, a holiday; roll forward over Nov 28–29 to **Nov 30**. Full promise **84250 cents on 2026-11-30 agrees**.
- **E-01, p2:** Nov 30 = day 1; Dec 1–4 = 2–5; Dec 7–9 = 6–8, so deadline **Dec 9**. Floor = ceil($2,500 × 30%) = **$750 / 75000 cents**. The ninth is a business day exactly at the deadline: **75000 cents on 2026-12-09 agrees**. Joint confirmation supports `promise`, absent reason, and empty notes/callbacks/transfers.
- **E-02, p1 / callback:** Deadline business days after Dec 18: Dec 21(1), 22(2), 23(3), 28(4), 29(5), 30(6), 31(7), Jan 4(8); Dec 24–25 and Jan 1 are holidays. Deadline **2027-01-04**; floor = ceil($1,900 × 30%) = **$570 / 57000 cents**. Monday Dec 21 is the first next business day; **08:00** is included in the window and later than `now`. Callback **2026-12-21 08:00**, reason `unavailable`, closure `callback_booked / unavailable`, and no promises/notes/transfers **agree**.
- **E-03, p1:** Dec 1–4 = business days 1–4; Dec 7–10 = 5–8, so deadline **Dec 10**. Floor = ceil($1,280 × 30%) = **$384 / 38400 cents**. The script gives a final refusal without a specified hardship trigger: note `declined`, close `no_promise / declined`, with no promises/callbacks/transfers **agrees**.
- **E-04, p1 / callback:** Dec 2–4 = business days 1–3; Dec 7–11 = 4–8, so deadline **Dec 11**. Floor = ceil($3,200 × 30%) = **$960 / 96000 cents**. The business day immediately after Tuesday Dec 1 is **Wednesday Dec 2**; the arrangement rule fixes **10:00**. Callback **2026-12-02 10:00**, reason `arrangement`, closure `callback_booked / arrangement`, and no promises/notes/transfers **agree**.
- **E-05, p1:** Oct 30 = business day 1; Nov 2–6 = 2–6; Nov 9–13 = 7–11; Nov 16–19 = 12–15, so deadline **Nov 19**. Nov 11 is a business day under E’s calendar. Floor = ceil($420 × 30%) = **$126 / 12600 cents**. Today, **Thursday Oct 29**, is valid; the previously agreed card survives hardship and is confirmed: **42000 cents on 2026-10-29 agrees**.
- **E-05, p2:** Oct 30 = business day 1; Nov 2–6 = 2–6; Nov 9–10 = 7–8, so deadline **Nov 10**. Floor = ceil($3,100 × 30%) = **$930 / 93000 cents**. Business failure triggers `hardship`, without a loan promise. The loan note, retained card promise, overall `promise` outcome with absent reason, and empty callbacks/transfers **agree**.
- **E-06, p1:** After Saturday Nov 14: Nov 16–20 = business days 1–5; Nov 23–25 = 6–8; Nov 26–27 are holidays; Nov 30 = 9; Dec 1–4 = 10–13; Dec 7–8 = 14–15. Deadline **Dec 8**; floor = ceil($560 × 30%) = **$168 / 16800 cents**. Wrong company number → correct retry → wrong founding year totals two wrong answers. Closure `id_failed / wrong_answers`, with no promises/notes/callbacks/transfers, **agrees**; these account calculations must not be disclosed.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
