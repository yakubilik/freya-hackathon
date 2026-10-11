## FINDINGS

1. **MAJOR — H/policy.md, §§3.4 and 9.1.** After a recorded pledge, two statements that the customer does not want to talk require `no_pledge / refused` under §3.4, but `pledge` under §9.1. Neither the mail nor memo explicitly resolves this conflict. **Fix:** qualify §3.4: close `pledge` if anything was recorded; otherwise `no_pledge / refused`.

2. **MAJOR — H/policy.md, §§6.1–6.3; H/memo.md, item 6.** The repeat-offer correction covers only attempt two. If the customer proposes the deadline, says the full amount is too much, then refuses the floor on that deadline, attempt one must propose that identical floor/date again—contradicting “Nothing already refused is offered again.” **Fix:** skip and count as used any persuasion attempt that repeats an already-refused amount/date combination, including attempt one.

3. **MAJOR — H/cases.json, H-04 `script` and `checks`.** On Saturday 5 December, the script conditions its refusal on being asked to pay “today.” Memo item 6 requires the initial question to propose the next business day, Monday 7 December. The script does not specify its response to that compliant question, and the checks omit the correction. **Fix:** change the script’s trigger to paying on 7 December and check that initial proposal explicitly. The deadline and refusal outcome otherwise agree.

4. **MAJOR — H/policy.md, §§2.2 and 6.5; H/api.json, `/schedule_callback` and `/transfer_to_agent` failure responses.** Callback and human/restructuring transfer failures have no defined fallback. Following the closing instructions after `ok:false` would report a booked callback or completed transfer that did not happen. The hardship-specific fallback does not cover these transfers. **Fix:** define bounded retries and failure closures: unsuccessful callbacks use `unreachable / no_callback`; unsuccessful transfers need an explicitly permitted failure outcome/reason, preserving any recorded pledge.

5. **MINOR — H/cases.json, H-06 `checks[0]`.** “No question about payment” is unqualified, although the script requires an initial payment question before the hardship disclosure. A literal judge could reject compliant behaviour. **Fix:** say “no question about payment after the hardship disclosure.”

## DATE ARITHMETIC

- **H-01, p1:** €410 > €300 and ≤ €2,000 → 22 October + 7 calendar days = **Thursday 29 October 2026**; the 23 October holiday counts because these are calendar days. Floor **€82**. Two name non-confirmations → `unreachable / unclear`; no promises, notes, callbacks or transfers. **Agrees.**
- **H-02, p1:** €2,450 > €2,000 → 30 October + 4 days: 31 October, 1 November, 2 November, **Tuesday 3 November 2026**. Floor **€500**, not the old €490. “Next Friday” means **6 November**, in the following calendar week; it exceeds the deadline, so the accepted replacement is **€500 on 3 November**. Close `pledge`; no notes, callbacks or transfers. **Agrees.**
- **H-03, p1:** €180 ≤ €300 → 30 November + 14 calendar days = **Monday 14 December 2026**; the intervening 8 December holiday does not extend it. Floor **€36**. Corrected customer date **Friday 4 December** is valid; record **€180**. The subsequent human request gives `front_desk`, then `transferred / human`; recorded pledges remain, with no notes or callbacks. **Agrees.**
- **H-03, p2:** €900 → 30 November + 7 calendar days = **Monday 7 December 2026**. Floor **€300**. **€900 on Friday 4 December** is within the deadline and remains recorded after the human transfer. **Agrees.**
- **H-03, p3:** €2,100 → 30 November + 4 calendar days = **Friday 4 December 2026**. Floor **€700**. Record **€2,100 on 4 December**, exactly the deadline; it remains after transfer. **Agrees.** The old deadline would be 7 December, also permitting this promise; this case targets human transfer, while H-02 discriminates the changed deadline rule.
- **H-04, p1:** €600 → 5 December + 7 calendar days = **Saturday 12 December** → roll **back to Friday 11 December 2026**. Floor **€150**, not the old €120. The initial proposal must be **Monday 7 December**: skip Sunday 6 December; Monday is open. Subsequent attempts are **€600**, then **€150**, both on 11 December. Refusing both gives one `refused` note and `no_pledge / refused`, with no promises, callbacks or transfers. **Expected result agrees conditional on fixing the script’s initial-question trigger.**
- **H-05, p1:** €150 → 23 December + 14 calendar days = **Wednesday 6 January 2027**, a listed holiday → roll **back to Tuesday 5 January**. Floor **€30**. The historical closure claim interrupts collection: only `already_closed` on p1, then `no_pledge / dispute`; no promises, callbacks or transfers. **Agrees.**
- **H-05, p2:** €1,800 → 23 December + 7 calendar days = **Wednesday 30 December 2026**. Floor **€600**. The conditional **€1,800 on Monday 28 December** would satisfy amount/date limits, but the preceding dispute prohibits reaching this offer. No p2 promise or note. **Agrees.**
- **H-06, p1:** €950 → 10 November + 7 calendar days = **Tuesday 17 November 2026**. Floor **€320**. Bare “Friday” means **13 November**; €320 on that date would otherwise qualify. Job loss overrides the offer, requiring immediate `wellbeing` transfer and `transferred / wellbeing`, with no promises, notes or callbacks. **Agrees.**

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
