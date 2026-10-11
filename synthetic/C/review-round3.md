## FINDINGS

1. **BLOCKER — C/brief.md — rule 50, “Before the security check only rules…”**  
   The exclusive whitelist omits rules 12–14, so the security check itself cannot operate before verification. It also excludes the opening rules 1–2, pre-verification goodbye handling in rule 46, closing requirements and failure handling. The verification-dependent cases are therefore impossible under a literal reading. **Smallest fix:** remove the exhaustive whitelist and explicitly restrict account/payment handling to after verification, while retaining opening, security, termination and tool-failure rules.

2. **MAJOR — C/brief.md — rules 4 and 43; rule 50’s pre-verification applicability.**  
   Rule 4 forbids saying “card” before verification, but rule 43 directs the assistant to recommend the number on the member’s “card or statement.” Rule 50 explicitly makes rule 43 applicable before verification. **Smallest fix:** use “statement” alone in the pre-verification response.

3. **MAJOR — C/brief.md — rule 53, “if `add_note` fails twice, say the request has been passed on instead.”**  
   Both recording attempts failed, and no other tool passes the request anywhere. The mandated acknowledgment claims an action unsupported by the tool results and contradicts rule 47’s success-dependent acknowledgments. Rule 16 also needs to make its “noted” acknowledgment conditional on successful recording. **Smallest fix:** acknowledge recording only after success; after two failures, say the request could not be recorded and retain the prescribed outcome.

4. **MINOR — C/README.md — opening paragraph, “specification of 48 rules.”**  
   The brief contains 53 numbered rules. **Smallest fix:** change `48` to `53`.

## DATE ARITHMETIC

The agreements below concern the substantive case rules, assuming successful tools; finding 1 prevents unconditional agreement with the brief as written.

- **C-01 — p1 card, promise:** €380 < €500 ⇒ 2026-10-16 + 10 calendar days = Monday **2026-10-26**, which is a business day under C’s calendar. Floor = ceil(380 × 0.25) = **€95**. Friday **2026-10-16** is eligible; the customer confirms **€380 that day**. **Agrees:** `pledge`, null reason; notes, callbacks and transfers empty.
- **C-02 — p1 loan, callback:** Floor = ceil(920 × 0.25) = **€230**. Deadline business-day count after Saturday 2026-10-31: Nov 1 weekend, Nov 2 holiday; **Nov 3(1), 4(2), 5(3), 6(4), 9(5)** ⇒ **2026-11-09**. Callback must be the next business day: reject Monday Nov 2; accept Tuesday **2026-11-03 at 10:00**, within 09:00–17:00. **Agrees:** `unreachable/callback_booked`; no promises, notes or transfers.
- **C-03 — p1 loan, promise:** Floor = ceil(1240 × 0.25) = **€310**. After Dec 23, skip Dec 24–25 holidays and Dec 26–27 weekend; count **Dec 28(1), 29(2), 30(3)**; skip Dec 31–Jan 1 holidays and Jan 2–3 weekend; **Jan 4(4), 5(5)** ⇒ deadline **2027-01-05**. The accepted floor and unresolved vague period lead to **€310 on January 5**, then confirmation. **Agrees:** `pledge`, null reason; notes, callbacks and transfers empty.
- **C-04 — p1 overdraft, no promise/callback:** €455.50 < €500 ⇒ Nov 30 + 10 calendar days = Thursday **2026-12-10**; the intervening Dec 8 holiday does not change calendar-day counting. Floor = ceil(455.50 × 0.25) = ceil(113.875) = **€114**. One incorrect postcode permits retry; the historical payoff and denial of liability lead to dispute handling. **Agrees:** `no_pledge/disputed`; promises, notes, callbacks and transfers empty.
- **C-05 — p1 card, suppressed proposed promise:** €268 < €500 ⇒ Oct 21 + 10 calendar days = Saturday **2026-10-31**, rolled **back** to Friday **2026-10-30**. Floor = ceil(268 × 0.25) = **€67**. The corrected proposed date, Wednesday **2026-10-28**, is eligible for €268, but bereavement overrides the payment proposal. **Agrees:** transfer to `welfare`, close `handed_over/welfare`; promises, notes and callbacks empty.
- **C-06 — p1 loan, no promise/callback:** Floor = ceil(610 × 0.25) = ceil(152.5) = **€153**. Business days after Tuesday Oct 13: **Oct 14(1), 15(2), 16(3), 19(4), 20(5)** ⇒ deadline **2026-10-20**. The goodbye while a question is open triggers rule 46, without a persuasion offer. **Agrees:** `no_pledge/refused`; promises, notes, callbacks and transfers empty.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
