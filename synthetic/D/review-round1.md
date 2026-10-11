## FINDINGS

1. **MAJOR — D/brief.md — “Disputes, payments already made,” first paragraph; “Closing,” post-recording dispute rule.** The former unconditionally requires `no_promise / dispute`; the latter requires `promise` when a dispute follows a recorded promise. Both apply to the same event. **Fix:** Make the first instruction explicitly conditional on whether a promise was already recorded.

2. **MAJOR — D/brief.md — immediate `paid` and `service_error` notes; “no notes are added on a transferred call”; “on a disputed call the only note is the dispute note.”** These requirements can become impossible: note p1 as paid, then hear a dispute about p2 or an insistent request for a human. The earlier note cannot be removed with any available tool. **Fix:** Defer non-dispute notes until the final disposition is known, explicitly exempt transferred calls from the general note requirement, and suppress pending notes when a dispute occurs.

3. **MAJOR — D/brief.md — “Security,” post-verification do-not-call instruction; “Closing.”** Security requires `no_promise / do_not_call`. Closing instead requires `promise` if anything was recorded, or the first non-paid note’s reason—typically `refused`—otherwise. **Fix:** Explicitly give post-verification do-not-call precedence over both closing rules.

4. **MAJOR — D/brief.md — hardship paragraph, “any account left without a promise is noted with reason hardship.”** This includes accounts already classified as paid and accounts whose voluntary promises subsequently fail twice, which separately require `paid` and `service_error`. Exactly one note cannot satisfy these competing reasons. **Fix:** Limit hardship notes to unresolved accounts without a paid classification or a failed recording.

5. **MAJOR — D/brief.md — “The ask and the two attempts,” prescribed second attempt versus “nothing already refused is offered again.”** A permitted account can have `minimum_due = arrears`. On Friday 2026-11-27, a 31–60-day account’s deadline and the next business day are both Monday 2026-11-30. Both mandatory attempts then propose the identical amount and date. **Fix:** Explicitly skip a duplicate proposal and treat its attempt as exhausted.

6. **MINOR — D/brief.md — deceased instruction, “hears … and nothing more”; final closing sentence.** The mandatory thanks and goodbye contradict the instruction to say nothing after the condolence. **Fix:** Exempt deceased calls from the closing utterance requirement.

7. **MINOR — D/cases.json — every `variables` object and every `products[]` object.** Fixtures omit `customer_id` and `product_id`, although tool requests require them and expectations reference `p1`, `p2`, and `p3`. No supplied convention specifies their injection. **Fix:** Supply the IDs or document deterministic fixture-to-tool ID assignment.

## DATE ARITHMETIC

- **D-01 — p1 credit_card, p2 personal_loan, p3 overdraft:** p1: 2026-10-29 + 14 calendar days = Thu 2026-11-12, floor £46; p2: +7 = Thu 2026-11-05, floor £290; p3: +3 = Sun 2026-11-01 → Mon 2026-11-02, floor £62. The October 30 holiday counts toward calendar days. Two wrong birth dates plus the wrong postcode exhaust verification; **agrees** with `not_verified / failed`, no promises, notes, callbacks or transfers.
- **D-02 — p1 credit_card promise:** 2026-11-27 + 14 calendar days = Fri 2026-12-11; floor £55. Thu December 10 is a business day before the deadline; £275 equals full arrears. **Agrees** with £275 on 2026-12-10.
- **D-02 — p2 personal_loan promise:** 2026-11-27 + 7 calendar days = Fri 2026-12-04; floor £320. Requested December 10 exceeds this deadline; the script accepts December 4. **Agrees** with £960 on 2026-12-04, overall `promise` without a reason, and no notes, callbacks or transfers.
- **D-03 — p1 personal_loan promise:** 2026-11-30 + 7 calendar days = Mon 2026-12-07; floor £90. Bare “Friday” means the first Friday after today, December 4; £90 ≤ £200 ≤ £450. **Agrees** with £200 on 2026-12-04, `promise` without a reason, and no notes, callbacks or transfers after declining support.
- **D-04 — callback; p1 overdraft:** After Sat 2026-10-17, business days 1 and 2 are Mon October 19 and Tue October 20. Monday 09:00 is inside the inclusive callback window and later than `now`. Unused account deadline: October 17 +14 = Sat October 31 → Mon November 2; floor £28. **Agrees** with callback 2026-10-19 at 09:00, `not_reached / callback`, and no promises, notes or transfers.
- **D-05 — p1 overdraft and p2 credit_card; no promise:** December 23 +7 calendar days counts December 24–30, including closing days December 25 and 28; both deadlines are Wed 2026-12-30. Floors are £19 and £128. The dispute stops processing before p2’s conditional offer can be negotiated. **Agrees** with only p1’s `dispute` note, `no_promise / dispute`, and no promises, callbacks or transfers.
- **D-06 — p1 credit_card, rejected first proposal:** Next business day after Tue 2026-10-20 is Wed October 21; offer full arrears £520. **Agrees** with the first-attempt check; no promise is recorded.
- **D-06 — p1 credit_card, rejected second proposal:** October 20 +3 calendar days = Fri October 23, already a business day; floor £104. **Agrees** with the £104 offer on 2026-10-23, one `refused` note, `no_promise / refused`, and no promises, callbacks or transfers.

## VERDICT
VERDICT: FIX (at least one BLOCKER or MAJOR).
