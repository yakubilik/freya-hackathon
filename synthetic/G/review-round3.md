## FINDINGS

1. **MAJOR — G/memo.md, §9 versus §10.** After a recorded promise, a complaint, arrangements or human transfer that fails twice requires `NOPTP / REF` under §9. Section 10 requires `PTP` unless a transfer occurs; a failed transfer has not occurred. No precedence resolves these memo clauses. **Fix:** make §9 preserve `PTP` when a promise already exists.

2. **MAJOR — G/mail.md, complaint and do-not-call bullets.** “I want to complain, and stop calling me” activates incompatible terminal instructions: complaints transfer with `XFER / COMP` and no notes, versus DNC notes with `NOPTP / DNC`. Document precedence does not resolve conflicting clauses within the mail. **Fix:** explicitly choose which request takes priority and specify the accompanying DNC handling.

3. **MAJOR — G/policy.md, P6.3 versus P6.4; G/memo.md, §5.** “I lost my job and need a payment plan” triggers both a `financial_support` offer and an `arrangements` transfer, potentially producing different queues and close reasons. Neither rule has stated precedence. **Fix:** explicitly prioritize hardship or the payment-plan request when both apply.

4. **MAJOR — G/policy.md, opening scope and P4.1; G/memo.md, §1; G/api.json, `/get_account` response field `days_in_arrears`.** The scope has no arrears-age limit, but amended deadlines cover only 1–90 days. A 91-day product is admissible and has no computable deadline. **Fix:** restrict supported products to 1–90 days and add matching API bounds, or define handling above 90.

5. **MINOR — G/api.json, HTTP 200 response schemas, especially `/verify_identity` and `/get_account`.** Every response property is optional: `{}` is valid, as is an account response containing products without identifiers, amounts or arrears ages. Such responses cannot support the required decisions. This is an underspecified contract, **not invalid OpenAPI**; the document otherwise has the requested seven paths and valid request/response structure. **Fix:** require `ok`, security-result fields on successful verification, and complete product records on successful account retrieval. [OpenAPI 3.0.3 schema rules](https://spec.openapis.org/oas/v3.0.3.html#schema-object).

6. **MINOR — G/codes.md, close-reason rows `FAIL` and `ERR`; G/memo.md, §9.** The descriptions cover only wrong answers and failed promise recording, while the memo also assigns these codes to verification-service and account-retrieval failures. **Fix:** broaden the two descriptions to include those service failures.

## DATE ARITHMETIC

- **G-01, p1 CC:** From Thu 2026-11-19, exclude the Nov 20 holiday and Nov 21–22 weekend; business days 1–6 are Nov 23, 24, 25, 26, 27, 30. Deadline **Nov 30**; floor `ceil(640 × 25%) = £160`. Full **£640 on Nov 30** is valid. `PTP`, null reason; no notes, callbacks or transfers. **Agrees.** Old policy deadline was Nov 27, so this discriminates the amendment.
- **G-02, p1 CC:** After Dec 11, business days 1–10 are Dec 14–18, 21–24, 29; exclude Dec 25 and 28 holidays and intervening weekends. Deadline **Dec 29**; floor **£100**. Dec 11 is this week’s last business day, so the sole persuasion offer is **£400 on Dec 18**. Refused → p1 `REF`; no promise. **Agrees.**
- **G-02, p2 PL:** After Dec 11, business days 1–6 are Dec 14–18, 21. Deadline **Dec 21**; floor **£300**. Next week’s last business day, **Dec 18**, is within the deadline: offer **£1,200**, then `REF` after refusal. **Agrees.**
- **G-02, p3 HP:** After Dec 11, business days 1–3 are Dec 14, 15, 16. Deadline **Dec 16**; floor **£200**. Persuasion date Dec 18 exceeds the deadline, so offer **£800 on Dec 16**. Refused → `REF`. Aggregate: three `REF` notes, `NOPTP / REF`, no promises, callbacks or transfers. **Agrees.** The old second attempt would elicit acceptance, so the script discriminates its withdrawal.
- **G-03, p1 PL:** After Nov 30, business days 1–10 are Dec 1–4, 7–11, 14. Hypothetical deadline **Dec 14**; floor **£140**. Neither is used: both supplied birth dates are wrong, and the second wrong answer on that field ends verification. `IDFAIL / FAIL`; no promises, notes, callbacks or transfers. **Agrees.** The old three-total-error rule would not yet terminate verification.
- **G-04, p1 HP / callback:** After Sat Oct 31, business days 1–6 are Nov 2–6, 9: hypothetical deadline **Nov 9**; floor `ceil(1050 × 25%) = £263`. Callback: Oct 31 at 14:00 is invalid because only the next business day is allowed; skip Sun Nov 1 → **Mon Nov 2 at 09:00**, within the inclusive 09:00–17:00 window. `NOCON / CB`; no promises, notes or transfers. **Agrees.**
- **G-05, p1 CC:** After Oct 14, business days 1–10 are Oct 15, 16, 19–23, 26–28. **Oct 26 is a business day in G’s calendar.** Deadline **Oct 28**; floor **£55**. The complaint triggers `complaints`, then `XFER / COMP`; no promises, notes or callbacks. **Agrees.**
- **G-06, p1 HP:** After Tue Dec 1, business days 1–3 are Dec 2, 3, 4 → deadline **Dec 4**. Following calendar week is Dec 7–13; corrected “next Tuesday” means **Dec 8**, beyond the deadline. Customer accepts **Dec 4**. Floor `ceil(1000 × 25%) = £250`; £220 is insufficient, and the customer accepts **£250**. **Agrees.** Under the old 20% minimum, £220 would be accepted.
- **G-06, p2 CC:** After Dec 1, business days 1–10 are Dec 2–4, 7–11, 14–15 → deadline **Dec 15**. Floor `ceil(999 × 25%) = ceil(249.75) = £250`. No payment offered; hardship prevents persuasion → p2 `HARD`. Aggregate: p1 promise **£250 on Dec 4**, `PTP`, null reason, no callbacks or transfers; the support offer was declined. **Agrees.**

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
