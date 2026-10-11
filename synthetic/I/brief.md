From: Dana Whitlock, Payments Team Lead, Tamsin Finance
To: Conversational AI vendor team
Date: October 8, 2026
Subject: Past-due reminder calls, materials for the bot

Hi team,

Attached: our Past-Due Contact Procedure (rev. 7), the October 1 change notice that overrides parts of it, and the code sheet for the ledger. Tamsin Finance is a fictional company and every customer in your test data is invented.

Things I want nailed down that the procedure does not spell out:

- We do not announce recording on this line; do not say "recorded" at all. The bot opens by saying it is calling from Tamsin Finance and is an automated assistant, then asks for the customer by title and last name.
- Nobody hears "past due", "collections", "balance", a product or a dollar figure before all three security questions are passed. That includes a spouse who offers to take care of it.
- Customers read their phone digits with a period at the end or a question in the same breath ("8864. How much do I owe?"). The digits are the answer; the question gets answered after the check, not before.
- When a customer gives a date in words, year included ("the twenty-eighth of April nineteen ninety-three"), the bot converts it. A date given as bare numbers is month, day, year, the American way: "four twenty-eight ninety-three" is April 28, 1993. Send it to the tool as YYYY-MM-DD.
- Amounts in our systems are strings with two decimals. The bot says them in dollars and cents and sends them as "125.00", never as a bare number.
- The bot never asks "how much can you pay". It proposes; the customer accepts, declines or names their own figure.
- A "bare" weekday ("Thursday") is the coming one. "Next Thursday" is the Thursday of next week.
- A customer who gives a period ("after the first", "when my check comes") and then "I don't know exactly" when asked for the day gets the deadline proposed. That is in the procedure, I repeat it because the human team keeps asking a third time.
- Business days: Monday to Friday except October 12, 2026, November 11, November 26 and 27, December 25, 2026 and January 1, 2027.
- The "postcode" security question is the five-digit ZIP code of the billing address. Customers say it digit by digit; send the five digits.
- Products in words: "the store card ending 2210", "the installment loan", "the auto loan".
- Anything the tools do not return, the bot does not know. No guesses.
- Thank the customer and say goodbye before closing. Every call.

The change notice wins over the procedure. This mail wins over the procedure too; it does not contradict the change notice, if you think it does, the change notice wins.

Thanks,
Dana


---

# Tamsin Finance, Past-Due Contact Procedure, revision 7 (July 2026)

Applies to outbound reminder calls to consumers past due on one to three products: store card, installment loan, auto loan. The caller receives `customer_id` (passed in every tool call), `first_name`, `last_name`, `title` and `now`, the date and time every date rule counts from. Amounts are US dollars.

Tools: the seven in the API file. `verify_identity` takes `field` (`date_of_birth`, `postcode`, `phone_last4`) and `answer`; `get_account` returns `products`, each with `type`, `card_last4` (store cards only), `past_due`, `days_late` and `min_due`; `create_promise` takes `product_id`, `amount` and `date`; `add_note` takes `product_id` and `reason`; `schedule_callback` takes `date` and `time`; `transfer_to_agent` takes `queue`; `close_call` takes `outcome` and `reason`.

## 1 Reaching the customer

1.1 Ask for the customer by title and last name. "Yes", "speaking", "this is he/she" or the customer's name confirm. Anything else: answer any question, ask once more. A second non-confirmation closes the call as not_reached / unclear.
1.2 Someone else on the line is told nothing about the reason for the call and is asked when the customer can be reached. A callback is booked with `schedule_callback` for today after `now` or for the next business day, between 08:00 and 20:00 inclusive; close not_reached / callback. An offer outside the window gets one more ask; a second offer outside books nothing, close not_reached / no_callback.
1.3 Wrong number: not_reached / wrong_number. Customer deceased: say "Please accept my condolences.", ask nothing more, say goodbye, close not_reached / deceased.
1.4 Asked whether it is a bot, the caller says it is Tamsin's automated assistant and continues.

## 2 Security

2.1 Three questions, one at a time, in this order: date of birth, postcode, last four digits of the phone number on file. `verify_identity` after each answer. Date of birth as YYYY-MM-DD; postcode upper case without spaces; four digits for the phone.
2.2 The hint `day_month_swapped` on a date of birth means the customer most likely gave day and month the other way round; ask for the month as a word. That retry is not a wrong answer.
2.3 The limit is per question: the second wrong answer on the same question ends the check. One wrong date of birth and one wrong postcode do not end it. When the check ends: say nothing about the account, tell the customer to call the number on their statement, close not_verified / failed.
2.4 A customer who declines is told once that the questions protect their account. A second refusal closes not_verified / declined. Asking what the call is about instead of answering is a refusal.
2.5 "Do not call me again": say it is noted. Before security, close not_verified / do_not_call with no note. After security, note every product without a promise do_not_call and close no_promise / do_not_call. Nothing is asked after that.

## 3 Stating the balances

3.1 After the third question passes, `get_account`. Say the call is about past-due balances, then every product in the order returned, one sentence each, with its past-due amount and days late, before asking for anything.

## 4 Deadlines and dates

4.1 The deadline is per product, from its `days_late`:

| days late | deadline |
|---|---|
| 1 to 15 | the 10th business day after today |
| 16 to 45 | the 6th business day after today |

4.2 A promise date is today or later, a business day, and not after the product's deadline. A weekend day or holiday the customer names becomes the next business day if that is inside the deadline. A period gets one request for the exact day; if none comes, the deadline is proposed. "Next <weekday>" is that day in the following calendar week. A date after the deadline is declined; the deadline is named and offered. One date for all products that is after one product's deadline: that product on its own deadline, the others on the named date, said at the read-back.

## 5 Amounts and persuasion

5.1 The first figure the caller asks for is always the full past-due amount of the product. The minimum is 10 percent of `past_due`, rounded up to the whole dollar.
5.2 "Too much": offer the minimum once, say the rest stays past due. Refusing the minimum is a refusal. A customer's own amount from the minimum to the past-due amount inclusive is accepted; below the minimum it is declined and the minimum offered once; above the past-due amount, the past-due amount is recorded.
5.3 First question: can the customer pay today (one product) or all of them today (several). If not, product by product in the order returned; today is not asked again.
5.4 A refusal or a non-answer on a product uses its single persuasion attempt: the full amount, or the minimum if the customer already called the full amount too much, on the 3rd business day after today, or on the product's deadline if that is earlier. After the attempt the product is noted refused. A date or amount the customer proposes is never a refusal. Nothing already refused is offered again.
5.5 Hardship (illness, hospital, bereavement, job loss, cannot afford essentials): one sentence of sympathy, no persuasion attempt on any product from then on, and one offer to transfer to the collections_team queue for hardship help. Accepted: `transfer_to_agent`, close transferred / hardship. Declined: continue without persuasion; a date or amount the customer still names is recorded; products without a promise are noted hardship.
5.6 A request for a payment plan: say the payments team handles plans, transfer to the payments_team queue, close transferred / plan. A request for a person: ask once whether the caller can help; if the customer insists, transfer to the payments_team queue, close transferred / human. Promises agreed but not yet recorded are dropped on any transfer; no notes on a transferred call.
5.7 Never offer a discount, a waiver, a fee reversal or a plan.

## 6 Disputes and prior payments

6.1 A product the customer says is not theirs, was closed or paid off long ago, or shows a wrong amount: do not argue, note it dispute, continue with the other products.
6.2 A product the customer says they paid recently: say a payment can take two business days to show, note it paid, continue.

## 7 Recording

7.1 Read all agreed promises back together with one question: "Do I have that right?". After a clear yes, `create_promise` once per product, the amount as a two-decimal string. A change at the read-back is checked again and read back again.
7.2 Say a promise is recorded only after `ok: true`. Retry a failed call once; a second failure is noted service_error for that product, other promises stand.
7.3 After the last recording say: "A letter confirming this arrangement will be mailed to you."
7.4 Every product without a promise gets exactly one `add_note`. A recorded promise is not changed on the call; changes go through the customer portal.

## 8 Closing

8.1 Exactly one `close_call`, last. promise whenever a promise was recorded, unless a transfer followed (transferred with its reason). No promise and every product noted paid: paid. Otherwise no_promise with the note reason of the first product in `get_account` order whose note is not paid. See the code sheet.


---

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


---

# Tamsin Finance ledger code sheet (payments team, October 2026)

## close_call: outcome

| outcome | meaning | reason needed |
|---|---|---|
| promise | at least one promise recorded | no |
| paid | customer reports every product paid | no |
| transferred | handed to a queue | yes |
| no_promise | verified, no promise | yes |
| not_verified | security not passed | yes |
| not_reached | customer not reached | yes |

## close_call: reason

| reason | goes with | meaning |
|---|---|---|
| hardship | transferred, no_promise | hardship transfer accepted; or hardship, transfer declined, no promise |
| plan | transferred | payment plan request |
| human | transferred | customer asked for a person |
| refused | no_promise | refused after the attempt or did not want to talk |
| dispute | no_promise | the first unpaid product was disputed |
| service_error | no_promise | the promise could not be recorded |
| do_not_call | no_promise, not_verified | customer asked not to be called |
| failed | not_verified | wrong answers |
| declined | not_verified | refused to answer |
| callback | not_reached | callback booked |
| no_callback | not_reached | no callback could be booked |
| wrong_number | not_reached | wrong number |
| deceased | not_reached | customer deceased |
| unclear | not_reached | person on the line not confirmed |

## add_note: reason

refused, hardship, dispute, paid, service_error, do_not_call

## transfer_to_agent: queue

payments_team, hardship_team

## get_account: type

store_card, instalment_loan, auto_loan (spoken "installment loan")

## State codes (reporting only, never used on a call)

TX, AZ, NV, NM
