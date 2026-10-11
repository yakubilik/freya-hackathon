## FINDINGS

1. **MAJOR — I/memo.md, item 6, “is not replaced” versus “noted do_not_call”.** Earlier note reasons must remain unchanged, but a later do-not-call request requires `do_not_call` on every product without a promise. Example: p1 is already marked `paid`, p2 receives a promise, then the customer requests no further calls. Both `paid` and `do_not_call` are required for p1. Item 7’s priority applies to triggers in **one message**, so it does not resolve this sequence. **Smallest fix:** explicitly state whether do-not-call replaces previously selected note reasons.

2. **MAJOR — I/memo.md, item 8, failed-transfer continuation; I/policy.md, 5.6.** After two transfer failures, continue “as if the customer had declined it.” That branch exists for hardship, but neither a mandatory plan transfer nor an insisted-on human transfer has a defined declined-transfer branch. The resulting negotiation, pending promises and close outcome are unspecified. **Smallest fix:** define the continuation after an exhausted `payments_team` transfer, including treatment of pending promises and the terminal outcome if negotiation cannot continue.

3. **MAJOR — I/memo.md, item 8, exhausted `add_note` failures; I/policy.md, 7.4 and 8.1.** The generic retry rule covers `add_note`, but supplies no fallback after its second failure. The procedure still requires a note for every unpromised product and derives the close reason from those notes. It is unclear whether an unsuccessful note’s intended reason controls closing or whether the failure changes the outcome. **Smallest fix:** specify that, after the retry, the failed note is abandoned without claiming success and explicitly define which reason controls closing.

## DATE ARITHMETIC

- **I-01, p1:** After Fri **2026-10-09**, skip Oct 10–12; Oct 13–16 = business days 1–4, Oct 19–23 = 5–9, Oct 26 = **10**, the deadline. Floor **35.00**. Coming Monday Oct 12 is a holiday; roll forward to Tue **Oct 13**. Final correction selects Tuesday. Promise **312.40 on 2026-10-13**, close `promise`, no notes/callbacks/transfers — **agrees**.
- **I-02, p1:** After Mon **2026-11-30**, Dec 1–4 = business days 1–4, Dec 7–11 = 5–9, Dec 14 = **10**, the deadline. Floor **20.00**. Recent-payment claim produces one `paid` note and no promise; Friday Nov 27 being a holiday does not invalidate that claim — **agrees**.
- **I-02, p2:** After **2026-11-30**, Tue Dec 1 = business day 1, Wed Dec 2 = **2**, the deadline for 50 days late. Floor **295.00**; “too much” leads to that amount. Coming Wednesday is **2026-12-02**. Promise **295.00**, close `promise`, only p1’s `paid` note, no callbacks/transfers — **agrees**. The former percentage floor would have been **118.00**, so this case distinguishes the new minimum.
- **I-03, p1:** After Wed **2026-11-25**, exclude Nov 26–27 holidays and Nov 28–29 weekend; Nov 30 = business day 1, Dec 1–4 = 2–**5**. Deadline **2026-12-04**, floor **155.00**. Immediate do-not-call produces one `do_not_call` note, no promise — **agrees**.
- **I-03, p2:** Same exclusions; Nov 30–Dec 4 = business days 1–5, Dec 7–11 = 6–**10**. Deadline **2026-12-11**, floor **15.00**. One `do_not_call` note; combined close `no_promise / do_not_call`, no promises/callbacks/transfers — **agrees**.
- **I-04, p1:** After Sat **2026-10-24**, Oct 26–30 = business days 1–**5**. Deadline **2026-10-30**, floor **228.00**. Third-party branch creates no promise, note or transfer — **agrees**.
- **I-04, callback offer 1:** “Tonight at nine” = **2026-10-24 21:00**; later than `now` 12:00, but outside **08:00–20:00**. Reject and ask once more — **agrees**.
- **I-04, callback offer 2:** “Tomorrow at ten” = Sun **2026-10-25 10:00**. Next business day is Mon **Oct 26**; Sunday is neither today nor that day. Reject, book nothing, close `not_reached / no_callback` — **agrees**.
- **I-05, p1:** After Tue **2026-12-01**, Dec 2, 3, 4 = business days 1–3; skip Dec 5–6; Dec 7 = 4, Dec 8 = **5**. Deadline **2026-12-08**, floor **210.00**. Unresolved vague period leads to the deadline; promise **840.00 on Dec 8**, close `promise`, no notes/callbacks/transfers — **agrees**. Old six-business-day deadline: **Dec 9**, so this case distinguishes the memo.
- **I-06, p1:** After Thu **2026-11-12**, Fri Nov 13 = business day 1; skip Nov 14–15; Mon Nov 16 = **2**. Deadline **2026-11-16**, floor **330.00**. Accepted hardship transfer produces `hardship_team`, close `transferred / hardship`, no promises/notes/callbacks — **agrees**.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
