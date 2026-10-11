## FINDINGS

1. **MAJOR — J/policy.md, D2 and E4; J/memo.md, §1.** Attempt one can exceed the deadline. On Friday 16 October, E4 proposes Friday 23 October, but mortgage arrears expire Thursday 22 October. E4 also mandates attempt two even when it would repeat an already-refused amount/date, which its final sentence prohibits. **Fix:** explicitly cap persuasion dates at the product deadline and skip duplicate offers, defining when attempts are exhausted.

2. **MAJOR — J/policy.md, F1–F2, G2, G4 and E6.** Products are flagged as they are handled, but a subsequent transfer requires “no flags on a routed call.” Previously written notes cannot be removed through this API. G4 also unconditionally requires flags for every unarranged product, including calls terminated before security, contradicting the intended empty notes in J-03 and J-06. **Fix:** require flags to remain pending until immediately before a verified, non-routed close; explicitly exempt unverified and unreached calls.

3. **MAJOR — J/policy.md, B5–B6 versus H1.** After a successful recording, “do not call me again” or twice declining further conversation requires `no_arrangement`, while H1 requires `arranged` whenever anything was recorded, with only transfers exempted. Neither mail nor memo resolves this. **Fix:** state explicitly which outcome wins after a recorded arrangement and align the ledger meanings.

4. **MAJOR — J/policy.md, E5–E6; J/memo.md, §4.** A customer reporting hardship while requesting lower payments activates two incompatible routes: offer `customer_care` and await acceptance, or transfer directly to `arrangements`. The amendment renames the hardship route without establishing precedence. **Fix:** add an explicit priority rule for hardship combined with a payment-plan request.

5. **MAJOR — J/policy.md, A3; J/cases.json, J-06 `checks[0]`.** “I am sorry for your loss.” exactly reproduces the sentence in public Brief A, rule 9. It breaches the requested absolute prohibition on copied sentences, despite being conventional wording. **Fix:** replace that required sentence and its matching check with independently worded sympathy.

6. **MINOR — J/cases.json, J-02 `script`, `expected.promises[0].date` and `checks[2]`.** The date test does not distinguish the amended four-business-day deadline from the original five-day deadline: 9 November satisfies both 10 November and 11 November. The £400 amount does distinguish the minimum rules, but the deadline assertion lacks a discriminating interaction. **Fix:** have the customer request 11 November and accept an explicitly offered 10 November; update the expected date and check.

7. **MINOR — J/cases.json, every case’s `variables`, `products` and expected product references.** Every API request requires `account_no`, and product operations require `product_id`, but fixtures supply neither. Expected references such as `p1` have no documented assignment rule. **Fix:** supply these identifiers or document the harness’s deterministic injection and mapping.

## DATE ARITHMETIC

Business-day counts below exclude today, weekends and the mail’s four holidays. All floors come directly from `minimum`. Empty callbacks and transfers are confirmed except J-03’s stated transfer; no case schedules a callback.

- **J-01, p1 card:** After 16 October: Oct 20(1), 21(2), 22(3), 23(4), 26(5), 27(6), 28(7), 29(8), 30(9), Nov 2(10); Oct 19 is excluded. Deadline **2 November**, floor **£90**. Full **£450 on 28 October** is valid; agrees with expected.
- **J-01, p2 mortgage_arrears:** Oct 20(1), 21(2), 22(3) → deadline **22 October**, floor **£650**. Requested 28 October exceeds the deadline; the customer accepts **£1,300 on 22 October**. Agrees; combined close `arranged`, no reason or notes.
- **J-02, p1 loan:** After 4 November: Nov 5(1), 6(2), 9(3), 10(4) → deadline **10 November**, floor **£400**. Bare “Monday” means the next Monday, **9 November**. **£400 on 9 November**, `arranged`, no reason or notes: agrees. Original-policy deadline would be Nov 11(5), so the date alone does not discriminate.
- **J-03, p1 card:** After Saturday 31 October: Nov 2(1), 3(2), 4(3), 5(4), 6(5), 9(6), 10(7), 11(8), 12(9), 13(10) → deadline **13 November**, floor **£46**. November 11 is not a Kestrel holiday. Complaint before verification → no promise or callback; transfer `complaints`, close `routed / complaint`, no notes. Agrees with the complaint branch, subject to finding 2’s global flag conflict.
- **J-04, p1 card:** After 21 December: Dec 22(1), 23(2), 24(3), 29(4), 30(5), 31(6), Jan 4(7), 5(8), 6(9), 7(10); exclude Dec 25/28 and Jan 1 plus weekends. Deadline **7 January 2027**, floor **£60**. Ownership dispute → no promise, note `disputed`; agrees.
- **J-04, p2 loan:** Same ten-day sequence → deadline **7 January 2027**, floor **£130**. Recent-payment claim → no promise, note `paid` and the one-business-day explanation; agrees. The reported payment date is not a promise date.
- **J-04, p3 mortgage_arrears:** Dec 22(1), 23(2), 24(3) → deadline **24 December**, floor **£1,000**. Christmas Friday is excluded, so that week’s last business day is Thursday 24 December. Rejected offers are **£2,000 on 24 December**, then **£1,000 on 24 December**; no promise, note `refused`. Agrees; first non-paid flag is p1’s `disputed`, giving `no_arrangement / disputed`.
- **J-05, p1 loan:** After 22 October: Oct 23(1), 26(2), 27(3), 28(4), 29(5), 30(6), Nov 2(7), 3(8), 4(9), 5(10) → deadline **5 November**, floor **£200**. Customer voluntarily offers **£200 on Friday 30 October** after declining transfer; valid without persuasion. `arranged`, no reason, hardship note or transfer: agrees.
- **J-06, p1 loan:** After 29 December: Dec 30(1), 31(2), Jan 4(3), 5(4), 6(5), 7(6), 8(7), 11(8), 12(9), 13(10); exclude Jan 1 and weekends. Deadline **13 January 2027**, floor **£70**. Daughter reports death → no promise, callback, transfer or notes; `not_reached / deceased` agrees with A3, subject to finding 2’s global flag conflict.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
