# Compliance memo 26/14: corrections to the Late Payment Contact Standard v2.3

From: Compliance, Portmann Bank
Date: 1 October 2026
Effective: 5 October 2026, every outbound late-payment call, human or automated

The items below replace the matching parts of version 2.3. Everything else stands.

1. **Recording sentence (1.1).** Calls on the automated line are not recorded. The sentence "This call may be recorded for training purposes." is withdrawn and must not be said. The introduction keeps the bank's name and the words "digital assistant".

2. **Persuasion attempts (6.1 and 6.3).** Section 6.1 says one attempt and section 6.3 describes two. Section 6.3 is correct: each product has two persuasion attempts, in the order 6.3 gives. The words "its one persuasion attempt" in 6.1 are a drafting error.

3. **Floor (6.1).** The floor is no longer 20 percent. It is the `floor` value that `get_account` returns for the product, whatever that value is. The caller does not compute it.

4. **Deadline bands (5.1).** A third band is added: `past_due` above 2,000.00 gives 4 calendar days after today. The other two bands and the move back to the last business day are unchanged.

5. **Queue name (6.4).** The care_team queue is now called wellbeing. The `transfer_to_agent` call uses `wellbeing`. The close reason wellbeing is unchanged.

6. **Attempts that repeat (6.3).** Any attempt that would repeat an offer the customer already refused (same amount, same date) is skipped and counts as used. A date in the past is answered with today or the next business day and is not a refusal. Attempt dates are never after the deadline. On a day that is not a business day the first question asks for the next business day rather than today.

7. **Dispute (4.1, 7.1, 9.1).** A dispute interrupts everything: the remaining products are not stated and not negotiated, and the close is no_pledge / dispute whatever notes other products would have had, unless a pledge was already recorded, in which case the pledge stays and the close is pledge. A request for a date after the deadline is handled under 5.2, not as a restructuring request; only a request for a plan, instalments or lower payments triggers 6.5.

8. **Notes and the close after a pledge (8.4, 3.4, 9.1).** Notes are written just before `close_call`, once the call ends verified and without a transfer. No note on a call closed transferred, unverified or unreachable; on a disputed call the only note is the dispute note. Once a pledge is recorded, nothing said afterwards changes the close except a transfer: a refusal to talk, a dispute or a payment claim after the recording is acknowledged in one sentence, noted on products without a pledge, and the call closes pledge. Hardship after a recorded pledge whose transfer fails twice: the pledge stays, remaining products are noted hardship, close pledge.

9. **Priority.** When one utterance triggers several rules, this order wins: a dispute (7.1), then hardship (6.4), then a request for a person (6.5 as corrected by the head of collections' mail), then a plan request (6.5).

10. **Tool failures.** `schedule_callback` and `transfer_to_agent` are retried once on `ok: false` or failure. A callback that still cannot be booked closes unreachable / no_callback. A restructuring or front_desk transfer that still cannot be made is said to be unavailable and the call continues where it was; if the customer then wants nothing else, close no_pledge / refused after security, unverified / declined before it (or pledge if a pledge is recorded). A note that fails twice is dropped; the close reason is the one it would have carried. `close_call` is not retried. A failed `verify_identity` or `get_account` after one retry closes unverified / failed or no_pledge / system_error with an apology. Nothing is said to be booked, transferred, noted or recorded unless the tool returned `ok: true`.

Questions to compliance, extension 4410.
