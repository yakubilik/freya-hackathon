## FINDINGS

1. **MAJOR — F/brief.md — “Getting the promise,” sentence “After the try, finish, close `refused` / `no_money`.”** This mandates refusal even when the customer accepts the offer, contradicting confirmation/recording and F-02’s expected promise. **Fix:** Make this closing conditional on the customer rejecting the offer or remaining noncommittal.

2. **MAJOR — F/brief.md — “When it is another person,” deceased instruction; “Closing,” final paragraph.** After the condolence, “nothing more” prohibits the mandatory thank-you and goodbye. Both instructions cannot be followed. **Fix:** Explicitly exempt deceased calls from the spoken closing.

3. **MAJOR — F/brief.md — “Identity,” do-not-call paragraph; “Getting the promise,” hardship paragraph.** A verified customer saying “I lost my job; do not call me again” triggers both `refused / no_contact` and immediate `transferred / care`. Hardship precedence covers money and dates, not contact withdrawal. **Fix:** State which instruction wins when both triggers occur, preferably completing the no-contact note and closing without transfer.

4. **MAJOR — F/brief.md — deceased response and confirmation question.** “I am sorry for your loss.” and “Do you confirm?” exactly match sentences in Public Brief A, rules 9 and 34. Despite being conventional phrases, they fail the requested absolute prohibition on copied sentences. **Fix:** Replace both with distinct wording.

5. **MINOR — F/cases.json — F-06, `script`, “Pays the full amount today and confirms.”** This describes payment rather than a commitment to pay. An actual payment report invokes `paid`, whereas the remainder assumes a recorded promise. **Fix:** Change “Pays” to “Agrees to pay”.

## DATE ARITHMETIC

- **F-01 — p1:** October 27–30 supplies **four** remaining working days, counting today; October 31 is Saturday, so limit = **2026-10-30**. Following calendar week = November 2–8; “next Friday” = **November 6**, beyond the limit. Accepted replacement = October 30. Floor **€40**; full **€210** is valid. **Agrees:** €210 promise on October 30, `promise` without reason, no notes/callbacks/transfers.

- **F-02 — p1:** October 29–30 supplies **two** remaining working days; fewer than three moves the limit to next month’s final working day, **Monday 2026-11-30**. November 11 is excluded but does not change that month-end. Floor **€60**; the single offer is €60 on November 30. **Date and amount agree; outcome is contradictory:** acceptance supports the expected promise, but the unconditional post-try instruction requires `refused / no_money`. Empty notes/callbacks/transfers agree.

- **F-03 — p1 / callback:** Five working days after Saturday November 7 are **November 9 (1), 10 (2), 12 (3), 13 (4), 16 (5)**; November 11 is closed. Product limit = **2026-11-16**, floor **€180**. Callback starts with tomorrow, Sunday November 8, then rolls forward to **Monday November 9**. **09:00** is outside 10:00–18:00; replacement **11:00** is valid. **Agrees:** callback November 9 at 11:00, `not_reached / callback`, no promises/notes/transfers.

- **F-04 — p1, no recorded promise:** After December 18, count **December 21 (1), 22 (2), 23 (3), 28 (4), 29 (5)**; skip weekends December 19–20 and 26–27 and holidays December 24–25. Limit = **2026-12-29**, floor **€70**. Offered **€100 on December 22** satisfies amount/date constraints, but hospital hardship overrides recording. **Agrees:** transfer to `care`, `transferred / care`, no promises/notes/callbacks.

- **F-05 — p1, no promise/callback:** Five working days after November 30 are **December 1 (1), 2 (2), 3 (3), 4 (4), 7 (5)**, skipping December 5–6. Limit = **2026-12-07**, floor **€190**. All three supplied birth dates differ from **1984-11-03**; identity failure prevents account disclosure and negotiation. **Agrees:** `not_verified / failed`, no promises/notes/callbacks/transfers.

- **F-06 — p1:** November has **18** working days remaining from November 4, counting today and excluding November 11; the limit stays at **Monday 2026-11-30**. Today, **Wednesday November 4**, is eligible. Floor **€150**; full **€450** is valid. **Agrees under the intended commitment reading:** €450 promise on November 4, followed by queue `people` and `transferred / human`; no notes/callbacks. The script’s payment wording needs clarification as finding 5 states.

## VERDICT
VERDICT: FIX (at least one BLOCKER or MAJOR).
