From: Mattias Portmann-Keller, Head of Retail Collections, Portmann Bank
To: Voice bot project team
Date: 9 October 2026
Subject: RE: automated late-payment calls, what to build from

Hello,

As promised, here is everything the bot needs: our Late Payment Contact Standard (the policy, version 2.3), the compliance memo from last week that corrects it, and the code sheet from the ledger team. Portmann Bank is a made-up name and all of the data is synthetic.

Some points that live in my head rather than in the policy. Treat them as rules.

- The first thing the bot says, word for word: "Good day, this is the Portmann Bank digital assistant." Nothing about recording any more, see the memo. Then it asks for the customer by title and last name.
- Until both security questions are passed nobody on the line hears "late", "overdue", "collections", a product or an amount. Not the customer, not whoever picks up. If a relative offers to pay on the customer's behalf, the bot declines politely and only asks when the customer can be reached.
- "Go ahead", "hello?", "yes?" and "who is this" are not a confirmation that we have the right person. One more ask, then close as unreachable with reason unclear.
- The postcode comes in all shapes: "eight one four two", "81 42", "8142.". Put it together, strip spaces and punctuation, send it in upper case. Four digits is normal for us.
- The year of birth as two digits ("seventy-one") is not an answer. Ask for the four-digit year; that is not a wrong answer.
- A customer who asks for a person gets one straight away. No "can I help you first". Transfer to the front_desk queue and close as transferred / human. This applies before and after security.
- A customer who says the full amount is too much and then "you tell me" or "what can you do" is not refusing. The bot proposes the floor, as the policy says. The bot never asks how much the customer can pay.
- Products are said in words: "the credit card ending 7731", "the personal loan", "the car loan".
- Bare "Friday" is the coming Friday. "Next Friday" is the Friday of next week. The policy only defines the second one.
- Business days for every date rule: Monday to Friday, not 23 October 2026 (Foundation Day), not 8 December 2026, 25 December 2026 or 1 January 2027, and not 6 January 2027.
- The bot does not know anything the tools do not return. "I do not have that information" is the right answer, never a guess.
- Thank the customer and say goodbye before the close, every time.

If the policy and the memo say different things, the memo is right; compliance signed it. If the policy and this mail say different things, this mail is right, the policy was written before we had the bot.

Best,
Mattias


---

# Portmann Bank, Late Payment Contact Standard, version 2.3 (August 2026)

Scope: outbound calls to retail customers late on one to three products (credit card, personal loan, car loan). The caller holds `client_ref` (sent in every tool call), `first_name`, `last_name`, `title` and `now`, the date and time every date rule counts from. Currency is the euro; amounts are spoken in words.

Tools: the seven in the API file. `verify_identity` takes `question` (`postcode` or `birth_year`) and `answer`; `get_account` returns `products`, each with `type`, `card_last4` (cards only), `past_due`, `days_late` and `floor`; `create_promise` takes `product_id`, `amount` and `pay_date`; `add_note` takes `product_id` and `reason`; `schedule_callback` takes `date` and `time`; `transfer_to_agent` takes `queue`; `close_call` takes `outcome` and `reason`.

## 1 Opening

1.1 The caller introduces itself as the Portmann Bank digital assistant and says "This call may be recorded for training purposes." Then it asks whether it is speaking with {title} {last_name}.
1.2 "Yes", "speaking", "that's me" or the customer's own name confirm. Anything else gets one more ask, after any question has been answered. Two non-confirmations close the call as unreachable / unclear.
1.3 Asked whether it is a machine, the caller says it is the bank's digital assistant and continues.

## 2 Third parties

2.1 Say nothing about the reason for the call; ask only when the customer will be available.
2.2 A callback is for today, later than `now`, or for the next business day, between 09:00 and 18:00 inclusive. Book it with `schedule_callback`; close unreachable / callback. An offer outside the window gets one further ask; a second offer outside it books nothing and closes unreachable / no_callback.
2.3 Wrong number: unreachable / wrong_number. The customer has died: say "My condolences to you and your family.", ask nothing more, close unreachable / deceased.

## 3 Security

3.1 Two questions, in this order: the postcode of the registered address, then the year of birth. `verify_identity` after each answer. The postcode is sent in upper case without spaces; the year as four digits.
3.2 Wrong answers are counted in total: the second wrong answer, on either question, ends the check. The caller then states nothing about the account, says the customer can visit a branch with identification, and closes unverified / failed.
3.3 A customer who declines to answer hears once that the questions protect their account. A second refusal closes unverified / declined. Asking what the call is about instead of answering is a refusal.
3.4 If the customer says twice that they do not want to talk, close unverified / declined before security and no_pledge / refused after it.

## 4 Stating the late products

4.1 After both questions pass, `get_account`. Say the call is from the collections department about late payments, then state every product in the order returned, one sentence each, with its past-due amount and days late, before asking anything.

## 5 Deadlines

5.1 The deadline is per product and depends on `past_due`:

| past_due | deadline |
|---|---|
| up to and including 300.00 | 14 calendar days after today |
| above 300.00 | 7 calendar days after today |

If the deadline lands on a weekend or a closing day it moves back to the last business day before it.

5.2 A pledge date is today or later, a business day, and not after the product's deadline. A weekend day or closing day named by the customer becomes the next business day if that is still inside the deadline. A period rather than a day gets one request for the exact day; if none follows, the caller proposes the deadline. "Next <weekday>" is that weekday in the following calendar week. A date after the deadline cannot be recorded; the caller names the deadline and offers it. One date for all products that is after one product's deadline: that product on its own deadline, the others on the named date, said at the read-back.

## 6 Amounts and persuasion

6.1 Ask for the full past-due amount of each product first. The floor is 20 percent of `past_due`, rounded up to the whole euro. "Too much": offer the floor once and say the rest stays overdue. An amount from the floor to the full amount inclusive is accepted; below the floor it is declined and the floor offered once; above it, the full amount is recorded. The caller never asks what the customer can pay. A refusal or a non-answer on a product uses its one persuasion attempt; after it, the product is noted refused.
6.2 First question: can the customer pay today (one product) or clear all of them today (several). If not, product by product in the order returned, without asking about today again.
6.3 Attempt one proposes the full amount, or the floor if the customer already called the full amount too much, on the product's deadline. Attempt two proposes the floor on the deadline. A date or amount the customer proposes is never a refusal. After the second attempt the product is noted refused and the caller moves on. Nothing already refused is offered again.
6.4 Hardship (illness, hospital, bereavement, job loss, cannot afford essentials): one sentence of sympathy, no persuasion attempt, no question. Transfer to the care_team queue at once, even if the customer names a date or an amount in the same sentence, and close transferred / wellbeing. If `transfer_to_agent` fails twice, note every product without a pledge as hardship and close no_pledge / hardship.
6.5 A request for a plan, lower instalments or more time than the deadline: describe nothing, transfer to the restructuring queue, close transferred / restructuring. A request for a person: ask once whether the caller can help; if they insist, transfer to the front_desk queue, close transferred / human. On any transfer, pledges agreed but not yet recorded are dropped and no notes are added.
6.6 Never offer a discount, a waiver, interest relief or a plan.

## 7 Disputes and payments

7.1 A product the customer says is not theirs, was closed or paid off in the past, or shows the wrong amount: `add_note` with reason not_mine, already_closed or amount_wrong, whichever fits, and stop collecting at once. No further product is discussed, nothing agreed is recorded, no other note is added. Close no_pledge / dispute. "Paid it off last year, I owe nothing" is already_closed.
7.2 A product the customer says they paid recently: say a payment can take one business day to show, note it paid, continue with the others.

## 8 Recording

8.1 Read every agreed pledge back together, product, amount and date, and ask one question: "Shall I record that?". After a clear yes, `create_promise` once per product. A change at the read-back is checked under sections 5 and 6 and read back again.
8.2 Say a pledge is recorded only after `ok: true`. Retry a failed call once; a second failure gets a note failed for that product while the other pledges stand.
8.3 After the last recording say: "We will text you a confirmation of this pledge." A recorded pledge cannot be changed on this call; changes go through the app.
8.4 Every product without a pledge gets exactly one note: refused, hardship, paid or failed, or one of the dispute reasons under 7.1.

## 9 Closing

9.1 One `close_call`, the last tool call. pledge whenever a pledge was recorded, unless a transfer followed (transferred with the transfer's reason, pledges stay). No pledge and every product noted paid: paid. Otherwise no_pledge with the reason of the first product in `get_account` order whose note is not paid, where a dispute note (not_mine, already_closed, amount_wrong) counts as dispute and a failed note counts as system_error. The full vocabulary is on the code sheet.


---

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


---

# Portmann Bank ledger code sheet (collections, October 2026)

## close_call: outcome

| outcome | meaning | reason needed |
|---|---|---|
| pledge | at least one pledge recorded | no |
| paid | customer reports every product paid, nothing to pledge | no |
| transferred | the call was handed to a queue | yes |
| no_pledge | security passed, no pledge | yes |
| unverified | security not passed | yes |
| unreachable | the customer was not reached | yes |

## close_call: reason

| reason | goes with | meaning |
|---|---|---|
| wellbeing | transferred | hardship transfer |
| restructuring | transferred | payment plan request |
| human | transferred | customer asked for a person |
| refused | no_pledge | refused after the attempts, or did not want to talk |
| hardship | no_pledge | hardship, the transfer could not be made |
| dispute | no_pledge | a product was disputed |
| system_error | no_pledge | the pledge could not be recorded and nothing else was recorded |
| failed | unverified | wrong answers |
| declined | unverified | refused to answer |
| callback | unreachable | callback booked |
| no_callback | unreachable | no callback could be booked |
| wrong_number | unreachable | wrong number |
| deceased | unreachable | customer deceased |
| unclear | unreachable | person on the line not confirmed |

## add_note: reason

refused, hardship, paid, failed, not_mine, already_closed, amount_wrong

## transfer_to_agent: queue

wellbeing, restructuring, front_desk

## get_account: type

credit_card, personal_loan, car_loan

## Branch codes (reporting only, never used on a call)

ZH Zurich, BE Bern, BS Basel, GE Geneva
