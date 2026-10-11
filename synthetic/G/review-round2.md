## FINDINGS

1. **MAJOR — G/mail.md, final precedence paragraph and complaint/DNC bullets; G/memo.md, §§8–9.** Both documents override the policy, but neither takes precedence over the other. The mail requires DNC notes on every product and `NOPTP / DNC`; memo §8 preserves recorded promises, closes `PTP`, and notes only unpromised products. The mail also says to acknowledge the note before writing it, whereas memo §9 prohibits acknowledging unsuccessful operations. Complaint-transfer failure creates another mail/memo conflict. **Smallest fix:** explicitly state that memo §§8–9 override the corresponding mail instructions.

2. **MAJOR — G/policy.md, P6.2; G/memo.md, §7.** Persuasion can propose a past date. On Saturday 31 October, “last business day of this week” is Friday 30 October. The existing exception covers only *today being* that business day; the memo adds an upper deadline limit but no lower limit. This contradicts P4.2. **Smallest fix:** choose next week’s last business day whenever this week’s is **on or before today**, then apply the deadline cap.

3. **MAJOR — G/policy.md, P5.2 and P6.2; G/memo.md, §6.** P5.2 allows offering the minimum once. If the customer rejects that offer after saying the full amount is too much, P6.2 requires a persuasion offer at the minimum again. With an unused persuasion attempt, both instructions cannot be satisfied literally. **Smallest fix:** state explicitly whether the single persuasion attempt may repeat a previously refused minimum.

4. **MAJOR — G/memo.md, §9, “continues as if the customer had declined it”; G/policy.md, P6.4.** After two failed arrangements or human transfers, the fallback refers to a declined-transfer branch that P6.4 never defines. Only hardship has such a branch. **Smallest fix:** specify the continuation or terminal outcome for failed `arrangements` and `agent` transfers, including pre-verification calls and calls with recorded promises.

5. **MAJOR — G/api.json, error responses for `/verify_identity`, `/get_account`, `/add_note` and `/close_call`; G/memo.md, §9.** These tools permit failures, but the brief provides no handling for them. For example, a failed `get_account` leaves no products from which to determine the mandatory closing outcome; a failed `close_call` conflicts with completing the call while making exactly one closing invocation. **Smallest fix:** define retry/terminal behavior for these operations and clarify whether the exactly-once closing rule counts attempts or successful closure.

6. **MINOR — G/README.md, opening paragraph, “a memo that amends six points”.** The supplied memo contains nine numbered amendments, including additional date, note and failure rules. **Smallest fix:** change “six” to “nine”.

## DATE ARITHMETIC

- **G-01 — p1 CC:** After Thu 2026-11-19, exclude the 20 November holiday and weekend 21–22; business days are Nov **23(1), 24(2), 25(3), 26(4), 27(5), 30(6)**. Deadline **2026-11-30**; floor `ceil(640 × .25) = £160`. Full £640 on the requested 30th is valid. **Agrees:** promise £640 on 2026-11-30; `PTP`, no reason, notes, callbacks or transfers. The old five-day deadline would be November 27, so this discriminates.

- **G-02 — p1 CC:** After Fri 2026-12-11, Dec **14–18 = days 1–5**, **21–24 = days 6–9**; exclude holidays 25 and 28 and weekend 26–27; **29 = day 10**. Deadline **2026-12-29**; floor **£100**. Today is this week’s last business day, so the sole persuasion offer is **£400 on Friday 18 December**; refused. **Agrees:** no promise, p1 `REF` note.

- **G-02 — p2 PL:** Dec **14(1), 15(2), 16(3), 17(4), 18(5), 21(6)** gives deadline **2026-12-21**; floor **£300**. Next week’s Friday, December 18, is within the deadline; **£1,200 on December 18** is offered and refused. **Agrees:** no promise, p2 `REF` note.

- **G-02 — p3 HP:** Dec **14(1), 15(2), 16(3)** gives deadline **2026-12-16**; floor **£200**. The nominal December 18 persuasion date is capped to December 16; **£800 on December 16** is refused. **Agrees:** no promise, p3 `REF` note; overall `NOPTP / REF`, three notes, no callbacks or transfers. The scripted acceptance of a second proposal makes withdrawal of that attempt discriminating.

- **G-03 — p1 PL:** After Mon 2026-11-30, **Dec 1–4 = days 1–4**, **7–11 = days 5–9**, **14 = day 10**. Deadline **2026-12-14**; floor **£140**, neither reached during the call. Both supplied birth dates are wrong; the second is not a day/month swap. **Agrees:** `IDFAIL / FAIL` after two wrong DOB answers, no phone question, promises, notes, callbacks or transfers. The old three-total-errors rule would not yet terminate verification.

- **G-04 — p1 HP / callback:** After Sat 2026-10-31, business days **Nov 2(1), 3(2), 4(3), 5(4), 6(5), 9(6)** give the unused product deadline **2026-11-09**; floor `ceil(1050 × .25) = £263`. Saturday October 31 at 14:00 is ineligible: callbacks must be next business day. Skip Sunday November 1; **Monday November 2 at 09:00** is eligible, including the opening boundary. **Agrees:** that callback, `NOCON / CB`, no promises, notes or transfers.

- **G-05 — p1 CC:** After Wed 2026-10-14, business days are **Oct 15(1), 16(2), 19(3), 20(4), 21(5), 22(6), 23(7), 26(8), 27(9), 28(10)**. October 26 is not a G holiday. Deadline **2026-10-28**; floor **£55**. The complaint triggers immediate transfer, and deferred dispute notes are suppressed on transfer. **Agrees:** `complaints` transfer, `XFER / COMP`, no promises, notes or callbacks.

- **G-06 — p1 HP:** After Tue 2026-12-01, **Dec 2(1), 3(2), 4(3)** gives deadline **2026-12-04**. Following-week Wednesday is December 9; the customer corrects it to following-week Tuesday, **December 8**. That exceeds the deadline, so December 4 is offered and accepted. Floor `ceil(1000 × .25) = £250`; £220 is rejected and £250 accepted. **Agrees:** promise **£250 on 2026-12-04**, `PTP` without a reason. The old 20% floor would permit £220.

- **G-06 — p2 CC:** Business days **Dec 2–4 = 1–3**, **7–11 = 4–8**, **14(9), 15(10)** give deadline **2026-12-15**; floor `ceil(999 × .25) = ceil(249.75) = £250`. Hardship followed by declined support and inability to pay yields no persuasion or promise. **Agrees:** p2 `HARD` note; overall no callbacks or transfers, and no note on promised p1.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
