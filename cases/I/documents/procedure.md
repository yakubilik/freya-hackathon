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
