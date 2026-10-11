# Amendment 2026-10 to CCS-A issue 5

From: Collections Policy, Kestrel Bank plc
Date: 2 October 2026
Effective: 5 October 2026, every outbound arrears call, human or automated

The following replace the matching parts of CCS-A issue 5. Everything else stands.

1. **Deadlines (D1).** The band above 1,000.00 now gives the 4th business day after today, not the 5th. In addition, mortgage arrears (kind `mortgage_arrears`) always have the 3rd business day after today as their deadline, whatever the amount. The band up to 1,000.00 is unchanged for cards and loans.

2. **Minimum (E1).** The half rule is withdrawn. The minimum for a product is the `minimum` value `get_account` returns for it. The agent does not compute it.

3. **Confirmation (G3).** The text message service is withdrawn. The sentence in G3 is not said. No confirmation sentence of any kind replaces it; after the last recording the agent goes on to the goodbye.

4. **Queue name (E5).** The welfare queue is renamed customer_care. The offer to the customer and the `transfer_to_agent` call both use the new name. The close detail is now customer_care as well; welfare is no longer a valid detail.

5. **Complaints.** A customer who says they want to complain, or asks how to complain, is routed to the complaints queue at once. Close routed / complaint. This applies before and after security and stops all collection.

6. **Attempt dates (E4).** A persuasion date is never after the product's deadline: when the rule's date would be later, the deadline is proposed instead. Any attempt that would repeat an offer the customer already refused (same amount, same date) is skipped and counts as used. On a day that is not a business day the first question asks for the next business day rather than today.

7. **Flags (G4, B5, B6).** Flags are written just before `close_call`, once the call ends verified and without a transfer; no flag on a call closed routed, not_verified or not_reached. A reason decided earlier (paid, disputed) is held until then. "Do not call me again" or a second "I do not want to talk" after a recorded arrangement: the arrangement stays, only products without an arrangement are flagged, and the call closes arranged. Without a recorded arrangement, B5 and B6 decide the detail (do_not_call, refused) whatever flags other products carry; H1's first-flag rule applies only when the call ends by running out of products. Nothing else said after a recorded arrangement changes the close except a transfer.

8. **Priority.** When one utterance triggers several rules: a complaint first, then do-not-call, then hardship, then a request for a person, then a plan request. A hardship customer who also asks for lower payments gets the customer_care offer, not the arrangements transfer.

9. **Tool failures.** Any tool other than `create_promise` that returns `ok: false` or fails is retried once. A callback that still cannot be booked closes not_reached / no_callback; a transfer that still cannot be made is said to be unavailable and the call continues as if the customer had declined it (a complaint: close no_arrangement / refused after security, not_verified / declined before, no flags, arranged if an arrangement is recorded); a flag that fails twice is dropped and the detail is the one it would have carried; `close_call` is not retried; a failed `verify_identity` or `get_account` after the retry closes not_verified / failed or no_arrangement / failed with an apology. Nothing is said to be booked, transferred, flagged or recorded unless the tool returned `ok: true`. A date in the past is answered with today or the next business day.

Questions to Collections Policy.
