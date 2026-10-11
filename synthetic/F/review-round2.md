## FINDINGS

1. **MAJOR — F/brief.md — “Identity,” do-not-call paragraph, versus “Getting the promise,” hardship paragraph.** Before verification, the first rule requires `not_verified / no_contact`; the hardship override unconditionally requires `refused / no_contact`. A customer mentioning hardship and requesting no further calls before verification triggers both. **Smallest fix:** make the hardship paragraph explicitly reuse the identity-dependent no-contact outcomes.

2. **MINOR — F/brief.md — “Getting the promise,” mandatory first question, versus “The dates,” business-day restriction.** “Can you pay it today?” is mandatory even on weekends and listed holidays, when today cannot be recorded as a promise date. Handling an unqualified “yes” then requires an unstated interpretation of the date-adjustment rule. **Smallest fix:** on non-working days, make the first offer the next working day.

3. **MINOR — F/brief.md — “When it is another person,” callback retry rule.** Only one callback date is permitted, but the retry and termination instructions explicitly address an out-of-window **time**, not an incorrect date. “Tuesday at eleven” when Monday is the permitted day has no explicit correction path. **Smallest fix:** apply the existing one-retry rule to an invalid date **or** time.

4. **MINOR — F/brief.md — “Getting the promise,” quoted question “Is it a scam?”** This complete question also appears verbatim in Public Brief A, rule 43. It is generic wording, not evidence of substantive copying, but violates the requested literal prohibition on matching sentences. **Smallest fix:** replace that example question with differently worded text.

## DATE ARITHMETIC

- **F-01 — p1 card, promise:** `days_late=12`; October working days remaining, including today: Tue 27, Wed 28, Thu 29, Fri 30 = **4**, so limit **2026-10-30**. Following calendar week is November 2–8, making “next Friday” **2026-11-06**, beyond the limit. Customer accepts October 30. Floor **€40**; full **€210** is valid. **Agrees:** promise €210 on October 30; close `promise`, no reason; no notes, callbacks or transfers.

- **F-02 — p1 consumer_loan, promise:** `days_late=8`; October working days remaining are Thu 29 and Fri 30 = **2 < 3**, so use next month’s final working day: **Monday 2026-11-30**. Floor **€60**. The non-answer triggers the single minimum-on-limit offer, which is accepted. **Agrees:** promise €60 on November 30; close `promise`, no reason; no notes, callbacks or transfers.

- **F-03 — p1 auto_loan, callback:** Tomorrow after Saturday November 7 is Sunday November 8; roll **forward** to **Monday 2026-11-09**. Reject 09:00; accept 11:00 within inclusive 10:00–18:00. Separately, product limit counts November **9(1), 10(2), 12(3), 13(4), 16(5)**, skipping holiday November 11 and weekends: **2026-11-16**; floor **€180**. **Agrees:** callback November 9 at 11:00; close `not_reached / callback`; no promises, notes or transfers.

- **F-04 — p1 card, no promise/callback:** Fifth working day after Friday December 18 counts December **21(1), 22(2), 23(3), 28(4), 29(5)**; skip holidays December 24–25 and weekends December 19–20 and 26–27. Limit **2026-12-29**; floor **€70**. Proposed €100 on Tuesday December 22 would satisfy amount/date rules, but hospital hardship overrides promise-taking. **Agrees:** transfer `care`; close `transferred / care`; no promises, notes or callbacks.

- **F-05 — p1 consumer_loan, no promise/callback:** Fifth working day after Monday November 30 counts December **1(1), 2(2), 3(3), 4(4), 7(5)**, skipping December 5–6. Limit **2026-12-07**; floor **€190**. All three supplied birth dates differ from November 3, 1984, so verification fails before account disclosure. **Agrees:** close `not_verified / failed`; no promises, notes, callbacks or transfers.

- **F-06 — p1 auto_loan, promise:** `days_late=7`; **18** working days remain in November including November 4, excluding weekends and holiday November 11, so limit **Monday 2026-11-30**. Today, **Wednesday 2026-11-04**, is valid. Floor **€150**; full **€450** is valid. **Agrees:** promise €450 on November 4 remains recorded; subsequent insistence on a human triggers queue `people` and close `transferred / human`; no notes or callbacks.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
