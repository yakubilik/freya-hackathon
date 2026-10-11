## FINDINGS

1. **MAJOR — I/policy.md, §1.3 and §5.1 first sentence.** “I am sorry for your loss.” copies Public Brief A rule 9; “Ask for the full past-due amount first.” copies Public Brief A rule 24. Both violate the explicit no-copied-sentence requirement. **Smallest fix:** independently reword both sentences.

2. **MAJOR — I/policy.md, §§5.4, 6.1–6.2 versus §§5.6, 2.5 and 7.4.** Notes are required while the conversation continues, but a subsequent transfer prohibits every note on that call. A later do-not-call request also requires `do_not_call` notes for products already noted, conflicting with exactly one note per product. No tool removes or changes notes. **Smallest fix:** keep dispositions provisional and emit final notes only after establishing that the call will end without transfer; explicitly define do-not-call precedence.

3. **MAJOR — I/policy.md, §7.4, “Every product without a promise gets exactly one `add_note`.”** This unqualified obligation conflicts with the no-note instructions for unverified and transferred calls. In particular, I-06 expects no note despite its fetched product having no promise. Neither the mail nor memo resolves this conflict. **Smallest fix:** explicitly restrict this obligation to verified, non-transferred calls.

4. **MAJOR — I/policy.md, §2.5 versus §8.1; I/codes.md, `no_promise` outcome definition.** A do-not-call request after a recorded promise requires `no_promise/do_not_call` under §2.5, but §8.1 requires `promise` unless a transfer follows. The code sheet also defines `no_promise` as having no promise. **Smallest fix:** retain `promise` when a promise already exists, note only remaining products `do_not_call`, and use `no_promise/do_not_call` otherwise.

5. **MAJOR — I/policy.md, §5.4, “After the attempt the product is noted refused.”** This orders a refusal note even when the customer accepts the persuasion offer and confirms a promise. **Smallest fix:** require the refusal disposition only if the offer is rejected and no promise results.

6. **MAJOR — I/cases.json, every `variables` object and every `products[]` object.** All cases omit `customer_id`; all fixture products omit `product_id`, although tool requests require these identifiers and expectations reference `p1`/`p2`. No supplied convention explains their injection or mapping. **Smallest fix:** supply explicit identifiers or document deterministic fixture expansion.

## DATE ARITHMETIC

- **I-01, p1:** Excluding today, October 10–11 weekend and October 12 holiday: October 13–16 = business days 1–4; October 19–23 = 5–9; October 26 = 10. **Deadline October 26; floor `"35.00"`**. Coming Monday is October 12; roll forward to Tuesday October 13. Her final correction preserves Tuesday. **Agrees:** `"312.40"` on `2026-10-13`; close `promise`, no reason, notes, callbacks or transfers.

- **I-02, p1:** December 1–4 = business days 1–4; December 7–11 = 5–9; December 14 = 10. **Deadline December 14; floor `"20.00"`**. The reported Friday payment is November 27; its holiday status does not invalidate a payment claim. The following two business days are November 30 and December 1. **Agrees:** no promise for p1, one `paid` note; overall close `promise` because of p2.

- **I-02, p2:** December 1 = business day 1; December 2 = 2. **Deadline December 2; floor `"295.00"`**. Bare “Wednesday” means December 2, exactly the deadline. **Agrees:** `"295.00"` on `2026-12-02`; no p2 note, callbacks or transfers; close `promise` without a reason. The old percentage floor would be `"118.00"`, so the amount distinguishes the memo.

- **I-03, p1:** November 26–27 are holidays; November 28–29 are weekend days. November 30 = business day 1; December 1–4 = 2–5. **Deadline December 4; floor `"155.00"`**. **Agrees:** one `do_not_call` note, no promise; close `no_promise/do_not_call`, with no callback or transfer.

- **I-03, p2:** Continuing the same count: December 7–11 = business days 6–10. **Deadline December 11; floor `"15.00"`**. **Agrees:** one `do_not_call` note, no promise; same overall closing and empty callback/transfer lists.

- **I-04, p1 and rejected callbacks:** October 26–30 = business days 1–5; October 26 is not a Tamsin holiday. **Deadline October 30; floor `"228.00"`**. “Tonight at nine” = Saturday October 24 at 21:00, outside 08:00–20:00. “Tomorrow at ten” = Sunday October 25 at 10:00, neither today nor the next business day, Monday October 26. **Agrees:** neither callback is booked; close `not_reached/no_callback`, with no promises, notes or transfers.

- **I-05, p1:** December 2, 3, 4, 7, 8 = business days 1–5, skipping December 5–6. **Deadline December 8; floor `"210.00"`**. The vague period and unsuccessful clarification lead to the deadline proposal, which she accepts. **Agrees:** `"840.00"` on `2026-12-08`; close `promise`, no reason, notes, callbacks or transfers. The old sixth-business-day rule gives December 9, so this case distinguishes the memo.

- **I-06, p1:** November 13 = business day 1; November 14–15 are weekend days; November 16 = 2. **Deadline November 16; floor `"330.00"`**. **Agrees with the transfer-specific instructions:** transfer to `hardship_team`, close `transferred/hardship`, no promises, notes or callbacks; the universal-note conflict is finding 3. The queue distinguishes the memo from the old `collections_team`.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
