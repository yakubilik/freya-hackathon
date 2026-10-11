From: Gareth Llewellyn, Collections Operations Manager, Kestrel Bank plc
To: Automation partner
Date: 7 October 2026
Subject: Arrears call automation, the pack

Hi,

Here is the pack for the automated arrears call: the Customer Contact Standard for Arrears (CCS-A, issue 5), the October amendment that overrides parts of it, and the ledger code list. Kestrel Bank is a fictitious name; all customers and balances in the test data are invented.

Things I need the agent to do that CCS-A does not say, or says badly:

- Open with the bank's name, "automated assistant" and the fact that the call is recorded. The exact words are yours; the three elements must be in the first sentence.
- Nothing about arrears, a missed payment, a product or a sum before both security checks have passed. To nobody. A husband or wife offering to settle it is thanked and asked when the customer is free.
- The word "complaint" from the customer, at any point, stops collection, before anything else in that message is acted on: say you will put them through to the complaints team, route to the complaints queue and close as routed / complaint. Before or after security.
- "I'll have to see" or "I'm not sure" with no day and no sum is not an answer. It counts as a refusal and uses an attempt.
- A customer who says the full amount is too much and then "you tell me" is not refusing: offer the minimum once, as CCS-A says. We never ask how much a customer can pay.
- A bare weekday ("Friday") is the next one coming. "Next Friday" is the Friday of next week, as CCS-A says.
- A customer who gives a wrong answer and then corrects it in the same breath ("the fourteenth, no, the fourth") has given one answer, the corrected one. Send only that.
- Business days for every rule: Monday to Friday, not 19 October 2026 (systems day), not 25 and 28 December 2026, not 1 January 2027.
- Products in words: "the credit card ending 4471", "the loan", "the mortgage arrears". Never "kind" or a code.
- If the tools do not say it, the agent does not know it. No guessed dates, no guessed sums.
- Thank the customer and say goodbye before closing. Every call.

The amendment overrides CCS-A where they differ. This mail overrides CCS-A where they differ; it does not touch anything in the amendment.

Regards,
Gareth


---

# Kestrel Bank, Customer Contact Standard for Arrears (CCS-A), issue 5, June 2026

Scope: outbound calls to personal customers overdue on one to three products: a credit card, a loan, or mortgage arrears. The agent holds `account_no` (sent in every tool call), `first_name`, `last_name`, `title` and `now`, the date and time all date rules count from. Currency: pounds sterling, spoken in words.

Tools: the seven in the API file. `verify_identity` takes `check` (`date_of_birth` or `postcode`) and `value`; `get_account` returns `debts`, each with `kind`, `card_last4` (cards only), `amount_due`, `days_overdue` and `minimum`; `create_promise` takes `product_id`, `amount` and `pay_by`; `add_note` takes `product_id` and `flag`; `schedule_callback` takes `date` and `time`; `transfer_to_agent` takes `queue`; `close_call` takes `result` and `detail`.

## A Reaching the customer

A1 Ask for the customer by title and surname. "Yes", "speaking", "that's me" or the customer's own name confirm. Anything else: answer a question if one was asked, then ask once more. A second non-confirmation closes not_reached / unclear.
A2 A third party is told nothing about the reason for the call and asked when the customer can be reached. A callback is booked with `schedule_callback` for today after `now` or for the next business day, 09:00 to 18:00 inclusive; close not_reached / callback. An offer outside the window gets one more ask; a second outside offer books nothing, close not_reached / no_callback.
A3 Wrong number: not_reached / wrong_number. Customer deceased: say "My condolences to you and your family.", ask nothing more, say goodbye, close not_reached / deceased.
A4 Asked whether it is a machine, the agent says it is Kestrel Bank's automated assistant and continues.

## B Security

B1 Two checks in this order: date of birth, then postcode. `verify_identity` after each answer. Date of birth as YYYY-MM-DD; a date given only in numbers is day, month, year. Postcode in upper case without spaces.
B2 The hint `day_month_swapped` means day and month were given the other way round: ask for the month as a word. That retry is not a wrong answer.
B3 Wrong answers are counted in total across both checks. The third wrong answer ends the check: say nothing about the account, tell the customer to call the number on their card or statement, close not_verified / failed.
B4 A customer who declines is told once that the checks protect their account. A second refusal, or asking what the call is about instead of answering twice, closes not_verified / declined.
B5 "Do not call me again": say it is noted. Before security, close not_verified / do_not_call with no flag. After security, flag every product without an arrangement do_not_call and close no_arrangement / do_not_call. Ask nothing after that.
B6 A customer who says twice that they do not want to talk: not_verified / declined before security, no_arrangement / refused after it.

## C Stating the debts

C1 After both checks pass, `get_account`. Say the call is about arrears, then every product in the order returned, one sentence each, with the amount due and the days overdue, before asking for anything.

## D Deadlines

D1 The deadline is per product, from its `amount_due`:

| amount due | deadline |
|---|---|
| up to and including 1,000.00 | the 10th business day after today |
| above 1,000.00 | the 5th business day after today |

D2 An arrangement date is today or later, a business day, and not after the product's deadline. A weekend day or holiday the customer names becomes the next business day if that is inside the deadline. A vague period gets one request for the exact day, then the deadline is proposed. "Next <weekday>" is that weekday in the following calendar week. A date after the deadline is refused, the deadline is named and offered. One date for all products that is after one product's deadline: that product on its own deadline, the others on the named date, said at the read-back.

## E Amounts and persuasion

E1 Ask for the full amount due first. The minimum is half of `amount_due`, rounded up to the whole pound.
E2 "Too much": offer the minimum once, say the rest stays overdue. Refusing the minimum is a refusal. An amount from the minimum to the amount due inclusive is accepted; below the minimum it is declined and the minimum offered once; above the amount due, the amount due is recorded. The agent never asks what the customer can pay.
E3 First question: can the customer pay today (one product) or clear all of them today (several). If not, product by product in the order returned; today is not asked again.
E4 A refusal or a non-answer on a product uses one of its two persuasion attempts. Attempt one: the full amount (or the minimum, if the customer already called the full amount too much) on the last business day of this week; if today is that day or later in the week, the last business day of next week. Attempt two: the minimum on the product's deadline. After both the product is flagged refused. A date or amount the customer proposes is never a refusal. Nothing already refused is offered again.
E5 Hardship (illness, bereavement, job loss, cannot afford essentials): one sentence of sympathy, no persuasion attempt on any product from then on, one offer to transfer to the welfare queue. Accepted: `transfer_to_agent`, close routed / welfare. Declined: continue without persuasion; a date or amount the customer still names is recorded; products without an arrangement are flagged hardship.
E6 A request for a plan or lower payments: describe nothing, transfer to the arrangements queue, close routed / arrangements. A request for a person: ask once whether the agent can help; if the customer insists, transfer to the agent queue, close routed / human. Arrangements agreed but not yet recorded are dropped on any transfer; no flags on a routed call.
E7 Never offer a discount, a waiver, a payment holiday or a plan.

## F Disputes and payments

F1 A product the customer says is not theirs, was closed or settled long ago, or shows the wrong amount: do not argue, flag it disputed, continue with the others.
F2 A product the customer says they paid recently: say a payment can take one business day to show, flag it paid, continue.

## G Recording

G1 Read all agreed arrangements back together with one question. After a clear yes, `create_promise` once per product. A change at the read-back is checked again and read back again.
G2 Say an arrangement is recorded only after `ok: true`. Retry a failed call once; a second failure is flagged failed for that product, the others stand.
G3 After the last recording say: "We will send you a text message confirming this arrangement."
G4 Every product without an arrangement gets exactly one flag. A recorded arrangement is not changed on the call; changes go through online banking.

## H Closing

H1 Exactly one `close_call`, last. arranged whenever an arrangement was recorded, unless a transfer followed (routed with its detail). No arrangement and every product flagged paid: paid. Otherwise no_arrangement with the flag of the first product in `get_account` order whose flag is not paid. Full vocabulary on the code list.


---

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


---

# Kestrel Bank arrears ledger codes (issue October 2026)

## close_call: result

| result | meaning | detail required |
|---|---|---|
| arranged | at least one arrangement recorded | no |
| paid | every product reported paid, nothing to arrange | no |
| routed | the call was transferred | yes |
| no_arrangement | verified, nothing arranged | yes |
| not_verified | security not passed | yes |
| not_reached | customer not reached | yes |

## close_call: detail

| detail | with | meaning |
|---|---|---|
| customer_care | routed | hardship transfer |
| arrangements | routed | payment plan request |
| human | routed | customer asked for a person |
| complaint | routed | customer wants to complain |
| refused | no_arrangement | refused after the attempts, or did not want to talk |
| hardship | no_arrangement | hardship, transfer declined |
| disputed | no_arrangement | the first unpaid product was disputed |
| failed | no_arrangement | recording failed |
| do_not_call | no_arrangement, not_verified | asked not to be called |
| failed | not_verified | wrong answers |
| declined | not_verified | refused to answer |
| callback | not_reached | callback booked |
| no_callback | not_reached | no callback possible |
| wrong_number | not_reached | wrong number |
| deceased | not_reached | customer deceased |
| unclear | not_reached | person on the line not confirmed |

## add_note: flag

refused, hardship, disputed, paid, failed, do_not_call

## transfer_to_agent: queue

customer_care, arrangements, complaints, agent

## get_account: kind

card, loan, mortgage_arrears

## Region codes (reporting only, never used on a call)

LDN, MID, NTH, SCO, WAL
