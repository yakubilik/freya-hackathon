## FINDINGS

1. **MAJOR — C/brief.md, rule 17.** “After both questions pass, call `get_account`.” copies Public Brief A rule 16 verbatim. **Fix:** rephrase this sentence independently.

2. **MAJOR — C/brief.md, rules 24 and 41.** A request to pay after the deadline requires both offering the deadline and immediately transferring to `arrangements`. No distinction or precedence resolves this. **Fix:** remove “more time than the deadline allows” from rule 41, leaving ordinary date negotiation to rule 24.

3. **MAJOR — C/brief.md, rule 31, “After the attempt is used or skipped…”.** This unconditionally closes `no_pledge / refused` after making the persuasion offer, even if the member accepts it. That conflicts with recording an accepted, confirmed pledge. **Fix:** close as refused only if the attempt is skipped or its offer is rejected; route acceptance to rule 34.

4. **MAJOR — C/brief.md, rule 3 versus rules 6–11; C/cases.json, C-02.** “Anything else” triggers another identity-confirmation question and eventually `no_confirmation`, including an explicit declaration that the speaker is the husband. The third-party rules instead require callback handling. C-02’s expected result depends on choosing the latter branch. **Fix:** restrict rule 3’s retry to ambiguous answers and explicitly route identified third parties to section 4.

5. **MAJOR — C/brief.md, rules 16, 32, 41 and 42.** Simultaneous terminal requests have conflicting mandatory actions. “I lost my job and need a payment plan” triggers both `welfare` and `arrangements`; “stop calling me and connect me to someone” triggers both do-not-call closure and immediate human transfer. Rule 32 establishes precedence only over persuasion and volunteered amounts/dates. **Fix:** define a single routing priority and exclude higher-priority situations from the other rules.

6. **MAJOR — C/brief.md, rule 16 versus rule 47’s outcome table.** A do-not-call request after a recorded pledge requires `no_pledge / do_not_call`, while the table also requires `pledge` when a pledge was recorded. Only transfers receive an explicit exception. **Fix:** explicitly define the closing outcome for this sequence and state that the existing pledge remains recorded.

7. **MAJOR — C/brief.md, rules 7, 16, 32, 41 and 42; C/api.json, corresponding failure responses.** Callback booking, note recording and transfers can return `ok: false` or HTTP 500, meaning no action occurred. Nevertheless, the brief directs successful booking/transfer outcomes or an assurance that the request is noted. Only `create_promise` has failure handling. **Fix:** require successful responses before claiming completion, and specify bounded retries and failure outcomes for the other actions.

8. **MAJOR — C/brief.md, rules 26–28; C/api.json, `/get_account` response `overdue_amount`.** No minimum balance excludes amounts below €1. For €0.50 overdue, the prescribed floor is `ceil(0.50 × 25%) = €1`, exceeding the full balance. Offering that floor conflicts with the prohibition on recording more than the overdue amount. **Fix:** cap the floor at the overdue balance, or explicitly exclude balances below €1 from both the brief and account schema.

9. **MINOR — C/cases.json, every `variables` and `products[0]`; C/README.md.** Cases omit the mandatory runtime `client_ref` and product identifiers, but expectations assume `product_id: "p1"`. No supplied convention explains their injection. This is a fixture-binding gap, not invalid OpenAPI syntax. **Fix:** document that the harness generates `client_ref` and assigns `p1`, or supply those identifiers explicitly.

10. **MINOR — C/cases.json, C-05, `checks[3]`: “no persuasion attempt, no amount proposed”.** The prohibition is unscoped, although the script reaches the initial full-payment request required by rules 25 and 29 before hardship is disclosed. A judge could penalize that required request. **Fix:** say “after the bereavement disclosure, no persuasion attempt or payment amount is proposed.”

## DATE ARITHMETIC

- **C-01 — p1 card, promise:** Deadline = 2026-10-16 + 10 calendar days = Monday **2026-10-26**, which is not a Halvard holiday; floor = ceil(380 × 0.25) = **€95**. Confirmed **€380 on 2026-10-16** is valid; 17:30 creates no payment-date restriction. **Agrees:** `pledge`, no reason, notes, callbacks or transfers.
- **C-02 — p1 loan, callback:** Deadline business-day count after Saturday 2026-10-31: skip Sunday 11-01 and holiday Monday 11-02; **11-03(1), 11-04(2), 11-05(3), 11-06(4), 11-09(5)**. Floor = ceil(920 × 0.25) = **€230**. Next business day is **2026-11-03**; Monday’s offer is invalid, and Tuesday **10:00** is within 09:00–17:00. **Agrees under section 4:** `unreachable / callback_booked`, that single callback, no promises, notes or transfers; rule 3’s conflict remains.
- **C-03 — p1 loan, promise:** Skip closing days 2026-12-24/25 and weekend 12-26/27; count **12-28(1), 12-29(2), 12-30(3)**; skip closing days 12-31/2027-01-01 and weekend 01-02/03; **01-04(4), 01-05(5)**. Deadline = **2027-01-05**; floor = ceil(1240 × 0.25) = **€310**. One unsuccessful exact-date clarification leads to the deadline. **Agrees:** confirmed €310 on 2027-01-05, `pledge`, no reason, notes, callbacks or transfers.
- **C-04 — p1 overdraft, no promise/callback:** Deadline = 2026-11-30 + 10 calendar days = Thursday **2026-12-10**; the intervening 12-08 holiday still counts. Floor = ceil(455.50 × 0.25) = ceil(113.875) = **€114**. One wrong postcode followed by correct answers permits verification; the historical payoff claim is a dispute. **Agrees:** `no_pledge / disputed`, no promises, notes, callbacks or transfers.
- **C-05 — p1 card, no promise/callback:** 2026-10-21 + 10 calendar days = Saturday **2026-10-31**, rolled backward to Friday **2026-10-30**. Floor = ceil(268 × 0.25) = **€67**. The corrected proposed date, Wednesday **2026-10-28**, is within the deadline, but rule 32 explicitly overrides the volunteered payment. **Agrees:** one `welfare` transfer, `handed_over / welfare`, no promises, notes or callbacks.
- **C-06 — p1 loan, no promise/callback:** Business days after Tuesday 2026-10-13 are **10-14(1), 10-15(2), 10-16(3), 10-19(4), 10-20(5)**; deadline = **2026-10-20**. Floor = ceil(610 × 0.25) = ceil(152.50) = **€153**. Goodbye while the payment question is open invokes rule 46. **Agrees:** `no_pledge / refused`, no promises, notes, callbacks or transfers.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
