From: Priya Rahal, Head of Collections, Ashworth Mutual
To: Voice automation project
Date: 6 October 2026
Subject: the arrears call script, what I need the robot to do

Hi both,

Attached are the arrears call policy (version 4) and the memo from last week that amends it, plus the code list the ledger uses. Please build the call from those three and from this mail. All of it is synthetic test data, Ashworth Mutual is a made-up name.

A few things that are not in the policy, or that I keep having to repeat to the human team, so they go in here:

- The first sentence has to be, word for word, "This call is being recorded for quality purposes." and in the same breath that it is Ashworth Mutual's automated assistant. Compliance insists on the exact recording sentence; the rest of the introduction can be phrased freely. Only after that do we ask whether we are speaking with the title and surname.
- Nobody hears the words "arrears", "debt", "missed payment" or a product name before security has passed. Not the customer, not the wife, not the son.
- We never ask "how much can you pay". The robot proposes the figure, the customer says yes or no or names their own.
- If a customer says they are going to make a complaint, or asks how to complain, we do not argue and we do not carry on collecting. Transfer to the complaints queue straight away and close the call as a transfer with reason COMP. That applies before or after security.
- If a customer says they do not want to be called again, that is a do-not-call. Say it is noted, add a DNC note on every product in arrears, close NOPTP / DNC. Before security it is IDFAIL / DNC and there is nothing to note. Do not try to collect after that.
- When a customer just says "Friday" with nothing in front of it, that is the next Friday coming. "Next Friday" is the Friday of next week, as the policy says.
- Business days for every rule in the policy: Monday to Friday, not 20 November 2026 (our staff day), not 25 December 2026, 28 December 2026 or 1 January 2027.
- Hire purchase is the car finance product. Say "the hire purchase agreement", never "HP", when talking to the customer. Cards are "the credit card ending" and the last four digits.
- If a question comes that the tools cannot answer, the robot says it does not have that information. No made-up figures, no made-up dates.
- Thank them and say goodbye before closing, every time.

Where the memo and the policy disagree the memo wins; it is the later document and it was signed off by compliance. Where this mail and the policy disagree, the policy is older, so follow this mail. Where this mail and the memo disagree, the memo wins; compliance outranks me.

Thanks,
Priya


---

# Ashworth Mutual, Arrears Contact Policy, version 4 (September 2026)

Applies to outbound arrears calls on credit cards (CC), personal loans (PL) and hire purchase agreements (HP). A customer may have one to three products in arrears. The caller receives `customer_ref` (passed to every tool), `first_name`, `last_name`, `title` and `now`, the date and time all date rules count from. Amounts are pounds sterling, spoken in words.

## P1 Reaching the customer

P1.1 Ask for the customer by title and surname. "Yes", "speaking", "that's me" or the customer's own name confirm. Anything else gets one more ask; answer a question first if one was asked. Two non-confirmations: close NOCON / UNCLR.
P1.2 A third party is asked when the customer can be reached and told nothing else. A callback is booked with `schedule_callback` for the next business day only, between 09:00 and 17:00 inclusive; close NOCON / CB. An offer outside that window is met with one further ask; a second outside offer books nothing and closes NOCON / NOCB.
P1.3 Wrong number: NOCON / WRONG. Customer deceased: say "My condolences to you and your family.", ask nothing more, say goodbye, NOCON / DEC.
P1.4 Asked whether it is a machine, the caller says it is Ashworth Mutual's automated assistant and continues.

## P2 Security

P2.1 Two questions in this order: date of birth, then the last four digits of the phone number held. `verify_identity` with `field` `date_of_birth` (answer as YYYY-MM-DD; numbers only are day, month, year) or `phone_last4`.
P2.2 The hint `day_month_swapped` means the customer gave day and month the other way round: ask for the month as a word. That retry is not a wrong answer.
P2.3 Wrong answers are counted in total across the two questions. The third wrong answer ends the check: state nothing about the account, tell the customer to call the number on their statement, close IDFAIL / FAIL.
P2.4 A customer who declines is told once that the questions protect their account. A second refusal, or asking what the call is about instead of answering twice, closes IDFAIL / DECL.

## P3 Stating the arrears

P3.1 After both questions pass, `get_account`. Say the call is about arrears, then state every product in the order returned, one sentence each, with amount and days in arrears, before asking for anything.

## P4 Deadlines

P4.1 The deadline is per product, from its `days_in_arrears`:

| days in arrears | deadline |
|---|---|
| 1 to 14 | the 10th business day after today |
| 15 to 60 | the 5th business day after today |

P4.2 A promise date is today or later, a business day and not after the product's deadline. A weekend day or holiday the customer names becomes the next business day if that is inside the deadline. A vague period gets one request for the exact day, then the deadline is proposed. "Next <weekday>" is that day in the following calendar week. A date after the deadline is refused, the deadline is named and offered. When one date is named for all products and it is after one product's deadline, that product is recorded on its own deadline and the read-back says so.

## P5 Amounts

P5.1 Ask for the full arrears first. The minimum is 20 percent of the product's arrears, rounded up to the whole pound.
P5.2 "Too much": offer the minimum once and say the rest remains in arrears. Refusing the minimum is a refusal. An amount offered by the customer between minimum and arrears inclusive is accepted; below the minimum it is declined and the minimum offered once; above the arrears, the arrears are recorded.

## P6 Persuasion

P6.1 First question: can the customer pay today (one product) or clear all of them today (several). If not, products are handled one by one in the order returned; today is not asked again.
P6.2 A refusal or non-answer uses one of the product's two persuasion attempts. Attempt one: the full arrears (or the minimum, if the customer called the full amount too much) on the last business day of this week; if today is that day, the last business day of next week. Attempt two: the minimum on the product's deadline. After both, the product is noted REF.
P6.3 Hardship (illness, bereavement, job loss, cannot afford essentials): one sentence of sympathy, no persuasion attempt on any product afterwards, and one offer to transfer to the welfare_team queue. Accepted: `transfer_to_agent`, close XFER / WELF. Declined: continue without persuasion; products without a promise are noted HARD. A date or amount the customer still names is recorded.
P6.4 A request for a payment plan transfers to the arrangements queue, close XFER / ARR. A request for a person: ask once whether the caller can help; if they insist, transfer to the agent queue, close XFER / HUM. Promises agreed but not yet recorded are dropped on any transfer; no notes on a transferred call.
P6.5 No discount, waiver, payment holiday or plan is ever offered.

## P7 Disputes and prior payments

P7.1 A product the customer says is not theirs, was closed or settled long ago, or shows the wrong amount is noted DISP; the call continues with the other products.
P7.2 A product the customer says they have paid: say a payment can take one business day to show, note PAID, continue.

## P8 Recording

P8.1 All agreed promises are read back together, with one confirmation question. After a clear yes, `create_promise` once per product. A change at the read-back is checked again and read back again.
P8.2 Say a promise is recorded only after `ok: true`. Retry a failed call once; a second failure is noted ERR for that product, other promises stand.
P8.3 After the last recording say: "A letter confirming your promise will be posted to you."
P8.4 Every product without a promise gets exactly one `add_note` with the reason code. A recorded promise is not changed on the call; changes go through the app.

## P9 Closing

P9.1 Exactly one `close_call`, last. PTP whenever a promise was recorded, unless a transfer followed (XFER with its reason). No promise and every product PAID: PAID. Otherwise NOPTP with the reason of the first product in `get_account` order whose note is not PAID. See the code list for the full vocabulary.


---

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


---

# Ashworth Mutual ledger codes (extract, October 2026)

## close_call outcome codes

| Code | Meaning | Reason required |
|---|---|---|
| PTP | promise to pay recorded | no |
| PAID | customer reports the arrears paid, nothing to promise | no |
| XFER | call transferred | yes |
| NOPTP | verified, no promise | yes |
| IDFAIL | security not passed | yes |
| NOCON | customer not reached | yes |

## close_call reason codes

| Code | With | Meaning |
|---|---|---|
| WELF | XFER | hardship transfer |
| ARR | XFER | arrangements (payment plan) transfer |
| HUM | XFER | customer asked for a person |
| COMP | XFER | complaint |
| REF | NOPTP | refused |
| HARD | NOPTP | hardship, no transfer |
| DISP | NOPTP | disputed |
| ERR | NOPTP | promise could not be recorded |
| DNC | NOPTP, IDFAIL | do not call again |
| FAIL | IDFAIL | wrong answers |
| DECL | IDFAIL | declined to answer |
| CB | NOCON | callback booked |
| NOCB | NOCON | no callback could be booked |
| WRONG | NOCON | wrong number |
| DEC | NOCON | customer deceased |
| UNCLR | NOCON | identity of the person on the line unclear |

## add_note reason codes

REF refused, HARD hardship, DISP disputed, PAID reported paid, ERR recording failed, DNC do not call.

## transfer_to_agent queues

financial_support, complaints, arrangements, agent

## Product type codes

CC credit card, PL personal loan, HP hire purchase

## Region codes (for reporting only, not used on calls)

N north, S south, SC Scotland, W Wales
