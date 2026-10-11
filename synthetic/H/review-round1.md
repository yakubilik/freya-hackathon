## FINDINGS

1. **MAJOR — H/policy.md, §2.1, second sentence.** “Ask when the customer can be reached.” copies Public Brief A, rule 5, verbatim. **Fix:** Rephrase that sentence.

2. **MAJOR — H/policy.md, §§5.2 and 6.5.** A customer requesting a date beyond the deadline triggers both an offer of the deadline and an immediate restructuring transfer. Neither the mail nor memo resolves this conflict. **Fix:** Add explicit memo precedence distinguishing a proposed payment date from a request for an extended payment arrangement.

3. **MAJOR — H/policy.md, §6.3, attempts one/two and final sentence.** When the full amount is already unaffordable, attempt one offers the floor on the deadline. After rejection, attempt two repeats precisely that offer, contradicting “Nothing already refused is offered again.” **Fix:** State in the memo whether this particular repeat is permitted or the second attempt is skipped.

4. **MAJOR — H/policy.md, §§4.1 and 7.1; H/cases.json, H-05 script and expected result.** Section 4.1 requires every product to be stated; §7.1 prohibits discussing another product after a dispute. H-05 interrupts the first product’s disclosure, making both instructions impossible to satisfy. **Fix:** Explicitly establish in the memo that a dispute interrupts and overrides the remaining disclosure requirement.

5. **MAJOR — H/policy.md, §8.4 versus §§7.1 and 6.5; H/cases.json, H-05 and H-06 `expected.notes`.** The universal requirement to note every product without a pledge conflicts with the dispute rule’s prohibition on other notes and the transfer rule’s prohibition on notes. H-05 omits the car-loan note; H-06 omits the hardship product’s note. These match the intended special handling, but not §8.4. **Fix:** Add explicit memo exceptions to §8.4 for dispute-stopped products and successful transfers.

6. **MAJOR — H/policy.md, §§7.1 and 9.1.** A refusal on the first product followed by a dispute on the second must close both `no_pledge / dispute` under §7.1 and `no_pledge / refused` under §9.1’s first-non-paid-note rule. **Fix:** Give dispute closure explicit precedence in the memo.

7. **MAJOR — H/policy.md, §§6.4 and 9.1.** If hardship arises after a pledge was recorded and the transfer fails twice, §6.4 requires `no_pledge / hardship`, while §9.1 requires `pledge` because no successful transfer followed. **Fix:** Explicitly define this combination in the memo, retaining `pledge` when a recorded pledge remains.

8. **MAJOR — H/cases.json, H-02 `products[0].floor`, second checks entry, and expected promise amount.** The supplied floor, €490, equals the obsolete calculation: `ceil(2450 × 20%) = 490`. The test cannot distinguish the memo from the policy. Moreover, “not a computed percentage” asserts an internal process that a transcript cannot establish. **Fix:** Use a different returned floor, such as €500, update the expected amount, and check only that the offered and recorded amount equals the tool-returned floor.

9. **MAJOR — H/cases.json, H-02 script, third checks entry, and expected promise date.** The promised Tuesday, 3 November, is valid under both the new deadline, 3 November, and the old deadline, 6 November. Merely accepting Tuesday does not demonstrate that the four-day amendment was applied, despite the check explicitly targeting it. **Fix:** Have the customer request the latest permissible date; retain 3 November as the expected date.

10. **MINOR — H/cases.json, every case’s `variables` and `products`; H/README.md, fixture documentation.** Every tool requires `client_ref`, and product operations require `product_id`, but neither identifier appears in the input fixtures. Expected results assume `p1`, `p2`, and `p3` without documenting their assignment. **Fix:** Supply the identifiers or document the harness’s injection and product-order mapping.

## DATE ARITHMETIC

- **H-01 — p1:** €410 ⇒ 7 calendar days: Thu 2026-10-22 + 7 = Thu 2026-10-29; the 23 October holiday counts inside the interval. Floor €82. No promise after two non-confirmations; `unreachable / unclear`, no notes, callbacks, or transfers. **Agrees.**
- **H-02 — p1:** €2,450 ⇒ 4 calendar days: Oct 31 = day 1, Nov 1 = day 2, Nov 2 = day 3, Tue Nov 3 = day 4. Floor €490; Tuesday means 2026-11-03, a business day exactly on the deadline. Promise €490; `pledge`, no reason, notes, callbacks, or transfers. **Agrees numerically; amendment discrimination fails as noted above.**
- **H-03 — p1:** €180 ⇒ 14 calendar days: Mon 2026-11-30 + 14 = Mon 2026-12-14; the 8 December holiday is counted, not skipped. Floor €36. Corrected date Fri 2026-12-04 is within the deadline; full €180 is valid. **Agrees.**
- **H-03 — p2:** €900 ⇒ 7 calendar days: Dec 1–7 = seven days, giving Mon 2026-12-07. Floor €300. Promise €900 on Fri 2026-12-04 precedes the deadline. **Agrees.**
- **H-03 — p3:** €2,100 ⇒ 4 calendar days: Dec 1–4 = four days, giving Fri 2026-12-04. Floor €700. Promise €2,100 on that deadline is valid. All three pledges remain when the subsequent human request triggers `front_desk`; `transferred / human`, no notes or callbacks. **Agrees.**
- **H-04 — p1:** €600 ⇒ 7 calendar days: Sat 2026-12-05 + 7 = Sat 2026-12-12, rolled **back** to Fri 2026-12-11. The 8 December holiday still counts. Floor €150. Offers are €600, then €150, both on 11 December; both are refused. No promise; one `refused` note, `no_pledge / refused`, no callbacks or transfers. **Agrees.**
- **H-05 — p1:** €150 ⇒ 14 calendar days: Dec 24–31 = eight days, Jan 1–6 = six more; raw deadline Wed 2027-01-06 is a listed holiday, rolled **back** to Tue 2027-01-05. Floor €30. No promise; `already_closed` note and `no_pledge / dispute`. **Agrees with §7.1, subject to the unresolved precedence findings.**
- **H-05 — p2:** €1,800 ⇒ 7 calendar days: Dec 24–30 = seven days, giving Wed 2026-12-30; Christmas counts inside the interval. Floor €600. Conditional full-payment date Mon 2026-12-28 would be valid, but the earlier dispute stops negotiation. No promise, note, callback, or transfer. **Agrees with §7.1; conflicts with the universal disclosure/note rules identified above.**
- **H-06 — p1:** €950 ⇒ 7 calendar days: Tue 2026-11-10 + 7 = Tue 2026-11-17. Floor €320. Bare Friday is 2026-11-13, within the deadline, and €320 meets the floor; nevertheless, hardship suppresses recording and triggers `wellbeing`, closing `transferred / wellbeing`. **Agrees with the hardship/transfer rules; empty notes conflict with §8.4.**
- **H-01–H-06 — callbacks:** No script requests a callback; every expected callback array is empty. No callback date arithmetic applies. **Agrees.**

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
