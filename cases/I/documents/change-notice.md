# Change notice PT-26-09: Past-Due Contact Procedure rev. 7

From: Payments Operations and Compliance, Tamsin Finance
Date: October 1, 2026
Effective: October 5, 2026, all outbound past-due calls, agent or automated

The items below replace the matching parts of revision 7. Everything not mentioned stands.

1. **Deadline bands (4.1).** The 16 to 45 band now gives the 5th business day after today, not the 6th. A third band is added: 46 to 90 days late, the 2nd business day after today. The 1 to 15 band is unchanged.

2. **Minimum (5.1).** The 10 percent rule is withdrawn. The minimum for a product is the `min_due` value `get_account` returns for it. The caller does not compute a minimum.

3. **Queue name (5.5).** The collections_team queue has been renamed hardship_team. The `transfer_to_agent` call uses `hardship_team`. The close reason hardship is unchanged. The payments_team queue is unchanged.

4. **Confirmation (7.3).** Letters are discontinued. The sentence in 7.3 is withdrawn. After the last recording say instead: "You will receive an email confirming this arrangement." Nothing is mailed.

5. **Refusal note (5.4).** The product is noted refused only when the attempt's offer is refused and no promise results; an accepted offer is recorded as a promise.

6. **Notes (7.4, 2.5).** Notes are written just before `close_call`, once the call ends verified and without a transfer; no note on a call closed transferred, not_verified or not_reached. A reason decided earlier (paid, dispute, refused) is held until then and is not replaced: a later hardship or do-not-call request notes only products with no reason yet. A do-not-call request after a recorded promise: the promise stays, only products without a promise are noted do_not_call, and the call closes promise. Without a recorded promise it closes no_promise / do_not_call whatever other notes would have said.

7. **Priority.** When one message triggers several rules: do-not-call first, then hardship, then a request for a person, then a plan request. Attempt dates are never after the deadline; an attempt that would repeat a refused offer is skipped and counts as used. A date in the past is answered with today or the next business day. On a day that is not a business day the first question asks for the next business day. Once a promise is recorded, nothing said afterwards changes the close except a transfer: a dispute, a payment claim or a refusal to talk after the recording is acknowledged, noted on products without a promise, and the call closes promise.

8. **Tool failures.** Any tool other than `create_promise` that returns `ok: false` or fails is retried once. A callback that still cannot be booked closes not_reached / no_callback; a transfer that still cannot be made is said to be unavailable: for hardship the call continues as if the offer had been declined, for a plan or human request the call ends with no notes as no_promise / refused (promise if one is recorded); a note that fails twice is dropped and the close reason is the one it would have carried; `close_call` is not retried; a failed `verify_identity` or `get_account` after the retry closes not_verified / failed or no_promise / service_error with an apology. Nothing is said to be booked, transferred, noted or recorded unless the tool returned `ok: true`.

Questions to Payments Operations.
