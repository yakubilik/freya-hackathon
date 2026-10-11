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
