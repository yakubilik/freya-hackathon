## FINDINGS

1. **MAJOR — H/memo.md, items 7 and 9.** Item 7 says a dispute “interrupts everything”; item 9 says hardship wins when an utterance triggers several rules. “That debt is not mine, and I lost my job” therefore requires both a dispute close and an immediate wellbeing transfer. Neither item explicitly resolves this conflict. **Smallest fix:** include disputes in item 9’s precedence order and explicitly make item 7 subject to that order.

2. **MAJOR — H/memo.md, item 10, failed front_desk transfer; H/codes.md, outcome table.** Human requests apply before verification. If that transfer fails twice and the customer wants nothing else, item 10 requires `no_pledge / refused`, although the code sheet restricts `no_pledge` to security-passed calls. **Smallest fix:** specify `unverified / declined` for this branch before verification, retaining `no_pledge / refused` after verification.

3. **MAJOR — H/memo.md, items 8 and 10; H/policy.md, 8.4; H/api.json, `/add_note` responses.** Notes are mandatory on applicable terminal branches, but `add_note` can return `ok: false` or HTTP 500. No rule explains retries, abandonment, or the resulting close when the required note cannot be written. **Smallest fix:** define a bounded note retry and explicitly permit closing after exhausted retries, with a specified outcome/reason and no claim that the note succeeded.

4. **MINOR — H/api.json, `/close_call` request schema and `/get_account` 200-response schema.** The document has valid OpenAPI 3.0.3 structure and exactly the seven required paths, but its schemas understate the documented contract: close reasons are unrestricted and optional for every outcome; successful account responses may omit `products`, contain any number of products, or omit essential product fields. These are contract gaps, not OpenAPI syntax errors. **Smallest fix:** encode the reason vocabulary and outcome-dependent requirements; require account fields on success and constrain `products` to one–three entries. [OpenAPI 3.0.3 schema specification](https://spec.openapis.org/oas/v3.0.3.html#schema-object).

5. **MINOR — H/codes.md, close reasons `system_error` and `failed`; H/memo.md, item 10.** The code sheet describes `system_error` exclusively as failed pledge recording and `failed` as wrong identity answers. The memo also assigns them to account-fetch failures and identity-service failures respectively. The stated precedence does not cover memo-versus-code-sheet conflicts. **Smallest fix:** expand those two descriptions to include the service-failure branches.

6. **MINOR — H/cases.json, H-04, `checks[0]`.** “‘Seventy-one’ is not counted as wrong” can refer to an invisible agent counter. The scripted continuation contains no wrong answer that would expose an erroneous increment. **Smallest fix:** require observable behavior: ask for four digits, do not submit `71` to `verify_identity`, and submit `1971` after clarification. If checking the service counter, explicitly require its returned `wrong_total` in the transcript.

7. **MINOR — H/cases.json, H-02, `title` and `script`.** The advertised “you tell me” behavior occurs only if the assistant first violates the prohibition on asking how much the customer can pay. A compliant run never exercises that clarification. **Smallest fix:** make the customer spontaneously say “The full amount is too much—you tell me what you can offer.”

## DATE ARITHMETIC

H-01 — p1: €410 → 7 calendar days; Thu 2026-10-22 + 7 = Thu 2026-10-29, a business day; floor €82. The 23 October holiday does not extend calendar-day counting. Two non-confirmations prevent account discussion: `unreachable / unclear`, no promises, notes, callbacks or transfers — **agrees**.

H-02 — p1: €2,450 → 4 calendar days: 31 October (1), 1 November (2), 2 November (3), Tue 3 November (4); floor €500. From Fri 30 October, “next Friday” is 6 November, beyond the deadline; the customer accepts 3 November. Record €500 on 2026-11-03, close `pledge`, no notes/callbacks/transfers — **agrees**. The old policy would give €490 and 6 November, so this case distinguishes both memo changes.

H-03 — p1: €180 → 14 calendar days; Mon 2026-11-30 + 14 = Mon 2026-12-14; floor €36. Corrected date Fri 2026-12-04 is within the deadline; record the full €180 — **agrees**.

H-03 — p2: €900 → 7 calendar days; Mon 2026-11-30 + 7 = Mon 2026-12-07; floor €300. Fri 2026-12-04 is within the deadline; record the full €900 — **agrees**.

H-03 — p3: €2,100 → 4 calendar days; Mon 2026-11-30 + 4 = Fri 2026-12-04; floor €700. Record the full €2,100 on that deadline. One combined confirmation precedes all three recordings; the subsequent human request transfers to `front_desk`, preserving promises and closing `transferred / human`, with no notes or callbacks — **agrees**.

H-04 — p1, initial offer: Saturday 2026-12-05 → next business day Monday 2026-12-07; floor €150. The initial payment question must use Monday, and the customer refuses — **agrees**.

H-04 — p1, persuasion offers: €600 → 7 calendar days; Sat 2026-12-05 + 7 = Sat 2026-12-12 → roll back to Fri 2026-12-11. The 8 December holiday does not extend the interval. Offer €600, then €150, both on 11 December; both are refused. No promise; one `refused` note, `no_pledge / refused`, no callbacks/transfers — **agrees**.

H-05 — p1: €150 → 14 calendar days; 23 December + 8 = 31 December, + 6 = Wed 2027-01-06, a listed holiday → roll back to Tue 2027-01-05; floor €30. One incorrect postcode permits a retry. The historical closure claim requires only an `already_closed` note and `no_pledge / dispute` — **agrees**.

H-05 — p2: €1,800 → 7 calendar days; Wed 2026-12-23 + 7 = Wed 2026-12-30; floor €600. The conditional €1,800 offer for Mon 28 December would fit numerically, but the card dispute stops the call before this product is stated or negotiated. No promise or note for p2; no callbacks/transfers — **agrees**.

H-06 — p1: €950 → 7 calendar days; Tue 2026-11-10 + 7 = Tue 2026-11-17; floor €320. Bare “Friday” means Fri 2026-11-13; €320 on that date would meet the amount/date limits. Job loss instead mandates `wellbeing` transfer, no promise or notes, and `transferred / wellbeing`; no callback — **agrees**.

Callbacks — H-01 through H-06: no script requests one; every expected callback list is empty — **agrees**.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
