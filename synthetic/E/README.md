# Brief E: what it varies and the derived dates

Brief E (Northgate Savings) is a specification made of **tables**; where text and table disagree the table wins. It is a **business** line: the contact is verified with the company registration number and the founding year (total limit of two wrong answers), amounts are US dollars carried as **integers in cents** (`past_due_cents`, `amount_cents`) and spoken in dollars and cents, there is **no recording sentence**, and there are **no persuasion attempts** at all: a refusal is final and the product is noted `declined`. The assistant runs on the evening line and never calls `transfer_to_agent`; a plan request or a request for a person becomes a `schedule_callback` with a `reason` (`arrangement`, `human_requested`) for the next business day at 10:00. Hardship gives a support phone number instead of a transfer. The deadline is by amount in business days (15th up to $1,000, 8th above), the floor is 30 percent rounded up to the dollar, confirmation is by letter, and the outcomes are `promise`, `settled`, `callback_booked`, `no_promise`, `id_failed`, `no_contact`. Holidays: 2026-11-26, 2026-11-27, 2026-12-24, 2026-12-25, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| E-01 | Wed 2026-11-25 15:00 | p1 business_card 84250, 12 d | Fri 2026-12-18 | 25300 | promise 84250 on Mon 2026-11-30; close promise |
| E-01 | Wed 2026-11-25 15:00 | p2 term_loan 250000, 40 d | Wed 2026-12-09 | 75000 | promise 75000 on Wed 2026-12-09 |
| E-02 | Fri 2026-12-18 17:30 | p1 line_of_credit 190000, 22 d | Mon 2027-01-04 | 57000 | callback Mon 2026-12-21 08:00; close callback_booked / unavailable |
| E-03 | Mon 2026-11-30 19:10 | p1 line_of_credit 128000, 20 d | Thu 2026-12-10 | 38400 | note declined; close no_promise / declined |
| E-04 | Tue 2026-12-01 10:00 | p1 term_loan 320000, 33 d | Fri 2026-12-11 | 96000 | callback Wed 2026-12-02 10:00; close callback_booked / arrangement |
| E-05 | Thu 2026-10-29 16:45 | p1 business_card 42000, 5 d | Thu 2026-11-19 | 12600 | promise 42000 on Thu 2026-10-29; close promise |
| E-05 | Thu 2026-10-29 16:45 | p2 term_loan 310000, 50 d | Tue 2026-11-10 | 93000 | note hardship |
| E-06 | Sat 2026-11-14 09:30 | p1 business_card 56000, 15 d | Tue 2026-12-08 | 16800 | close id_failed / wrong_answers |

Talking styles: E-01 in_words, E-03 pieces, E-05 talkative, E-06 asks_back.
