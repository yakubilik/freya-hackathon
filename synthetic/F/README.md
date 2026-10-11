# Brief F: what it varies and the derived dates

Brief F (Cresta Bank) is written in slightly broken English by a non-native head of collections, as unnumbered prose. It varies: a **single** security question, the date of birth, sent as `birth_date` (no question field) with `matched` and `tries_left` in the response, three wrong answers allowed; `get_account` returns one `product` object, not a list; euros in words; the floor is `monthly_instalment` for every product type; the "limit" for customers 15 days late or less is the **last working day of this month**, or of next month when fewer than three working days are left in this month counting today, and the 5th working day after today for 16 days or more; one try (the minimum on the limit); hardship transfers to `care` without asking, even when an amount and a date are named; callbacks are for tomorrow or the first working day after, never today, 10:00 to 18:00; the SMS is sent by the bank's own system, the robot only says the sentence; `add_note` is used only for a do-not-call wish; refusals close as `refused` with reasons `no_money`, `dispute`, `system`, `no_contact`. Closed days: 2026-11-11, 2026-12-24, 2026-12-25, 2026-12-31, 2027-01-01, 2027-01-06.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| F-01 | Tue 2026-10-27 11:00 | p1 card 210.0, 12 d | Fri 2026-10-30 | 40.0 | promise 210.0 on Fri 2026-10-30; close promise |
| F-02 | Thu 2026-10-29 18:30 | p1 consumer_loan 180.0, 8 d | Mon 2026-11-30 | 60.0 | promise 60.0 on Mon 2026-11-30; close promise |
| F-03 | Sat 2026-11-07 10:00 | p1 auto_loan 540.0, 20 d | Mon 2026-11-16 | 180.0 | callback Mon 2026-11-09 11:00; close not_reached / callback |
| F-04 | Fri 2026-12-18 17:30 | p1 card 330.0, 22 d | Tue 2026-12-29 | 70.0 | transfer care; close transferred / care |
| F-05 | Mon 2026-11-30 21:40 | p1 consumer_loan 760.0, 45 d | Mon 2026-12-07 | 190.0 | close not_verified / failed |
| F-06 | Wed 2026-11-04 09:00 | p1 auto_loan 450.0, 7 d | Mon 2026-11-30 | 150.0 | promise 450.0 on Wed 2026-11-04; transfer people; close transferred / human |

Talking styles: F-01 in_words, F-02 talkative, F-04 asks_back, F-05 pieces.
