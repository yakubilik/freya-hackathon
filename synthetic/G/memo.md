# Memo: amendments to the Arrears Contact Policy v4

From: Compliance and Collections, Ashworth Mutual
Date: 2 October 2026
Applies from: 5 October 2026, to every outbound arrears call, automated or not

The following replace the corresponding parts of policy version 4. Everything not mentioned stands.

1. **Deadline bands (P4.1).** The band 15 to 60 days now gives the 6th business day after today, not the 5th. A new band is added: 61 to 90 days in arrears, deadline the 3rd business day after today. The 1 to 14 band is unchanged.

2. **Security limits (P2.3).** Wrong answers are no longer counted in total. The limit is two wrong answers on the same question: the second wrong date of birth, or the second wrong phone answer, ends the check. A wrong date of birth followed by a wrong phone answer does not end it.

3. **Minimum (P5.1).** The minimum is 25 percent of the product's arrears, rounded up to the whole pound. For arrears of 1,000.00 the minimum is 250.00; for 999.00 it is 250.00 as well.

4. **Confirmation (P8.3).** Letters are discontinued. The sentence in P8.3 is withdrawn. After the last recording say instead: "You will get a text message confirming your promise." Nothing is posted.

5. **Queue name (P6.3).** The welfare_team queue has been renamed financial_support. The offer to the customer and the `transfer_to_agent` call both use the new name. The close code stays XFER / WELF.

6. **Persuasion (P6.2).** The second attempt is withdrawn. Each product gets one persuasion attempt, the one described as attempt one. After it, the product is noted REF.

7. **Persuasion dates (P6.2).** A date proposed in a persuasion attempt is never after the product's deadline: when the rule's date would be later, the product's deadline is proposed instead. When the last business day of this week is today or already past, the last business day of next week is used. An attempt that would repeat an offer the customer already refused (same amount, same date) is skipped and counts as used; otherwise the attempt may name the minimum again with a new date. On a day that is not a business day the first question asks for the next business day rather than today.

8. **Notes (P8.4).** Notes are written just before `close_call`, once it is clear the call ends verified and without a transfer. No note of any kind on a call closed XFER, IDFAIL or NOCON. A reason decided earlier in the call (PAID, DISP, REF) is held until then. A DNC request after a recorded promise: the promise stays, the call closes PTP, and only products without a promise are noted DNC.

9. **Tool failures.** `schedule_callback` and `transfer_to_agent` are retried once on `ok: false` or failure. A callback that still cannot be booked closes NOCON / NOCB; a transfer that still cannot be made is said to be unavailable: for a hardship transfer the call continues as if the customer had declined it; for a complaint, arrangements or agent transfer the call ends with no notes, IDFAIL / DECL before security and NOPTP / REF after it, or PTP if a promise is already recorded. `close_call` is not retried. A complaint wins over a DNC request in the same utterance; hardship wins over a plan request. A failed `verify_identity` or `get_account` after one retry closes IDFAIL / FAIL or NOPTP / ERR with an apology; a failed `add_note` is not retried further and does not change the outcome; `close_call` is retried until it succeeds. Nothing is said to be booked, transferred or noted unless the tool returned `ok: true`.

10. **After a recorded promise.** Nothing said after a promise is recorded changes the close except a transfer: a dispute, a payment claim, a DNC request or a refusal to talk is acknowledged in one sentence, noted on products without a promise, and the call closes PTP.

Questions to compliance.
