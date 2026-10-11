# Brief D: what it varies and the derived dates

Brief D (Marlowe & Finch Bank) is written as prose sections with no rule numbers; every sentence that says what the caller does is a rule. It varies: three security questions (date of birth, postcode, phone last four) with a **total** limit of three wrong answers; `get_account` returns `accounts` with `product`, `arrears`, `days_in_arrears`, `minimum_due`; `create_promise` takes `promise_amount` and `promise_date`; pounds in words; deadlines in **calendar days** by days in arrears (14, 7 or 3) rolled **forward** to a business day; two persuasion attempts (the full arrears on the next business day, then the floor on the deadline); a dispute is an `add_note` with reason `dispute` that **stops the call at once** even with other accounts open; hardship offers the `vulnerable_customers` queue once; callbacks today or on either of the next two business days, 09:00 to 20:00; do-not-call before and after verification; the opening wording is free but must contain "recorded"; confirmation by email. Closing days: 2026-10-30 (Founders' Day), 2026-12-25, 2026-12-28, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| D-01 | Thu 2026-10-29 16:00 | p1 credit_card 230.0, 9 d | Thu 2026-11-12 | 46.0 | close not_verified / failed |
| D-01 | Thu 2026-10-29 16:00 | p2 personal_loan 1450.0, 25 d | Thu 2026-11-05 | 290.0 |  |
| D-01 | Thu 2026-10-29 16:00 | p3 overdraft 310.0, 40 d | Mon 2026-11-02 | 62.0 |  |
| D-02 | Fri 2026-11-27 17:30 | p1 credit_card 275.0, 10 d | Fri 2026-12-11 | 55.0 | promise 275.0 on Thu 2026-12-10; close promise |
| D-02 | Fri 2026-11-27 17:30 | p2 personal_loan 960.0, 25 d | Fri 2026-12-04 | 320.0 | promise 960.0 on Fri 2026-12-04 |
| D-03 | Mon 2026-11-30 20:15 | p1 personal_loan 450.0, 20 d | Mon 2026-12-07 | 90.0 | promise 200.0 on Fri 2026-12-04; close promise |
| D-04 | Sat 2026-10-17 11:00 | p1 overdraft 140.0, 5 d | Mon 2026-11-02 | 28.0 | callback Mon 2026-10-19 09:00; close not_reached / callback |
| D-05 | Wed 2026-12-23 10:00 | p1 overdraft 95.0, 12 d | Wed 2026-12-30 | 19.0 | note dispute; close no_promise / dispute |
| D-05 | Wed 2026-12-23 10:00 | p2 credit_card 640.0, 12 d | Wed 2026-12-30 | 128.0 |  |
| D-06 | Tue 2026-10-20 09:05 | p1 credit_card 520.0, 35 d | Fri 2026-10-23 | 104.0 | note refused; close no_promise / refused |
| D-07 | Mon 2026-10-26 11:00 | p1 credit_card 180.0, 7 d | Mon 2026-11-09 | 36.0 | promise 180.0 on Mon 2026-10-26; close promise |
| D-08 | Wed 2026-11-11 14:00 | p1 credit_card 310.0, 12 d | Wed 2026-11-18 | 62.0 | promise 310.0 on Wed 2026-11-11; close promise |
| D-08 | Wed 2026-11-11 14:00 | p2 overdraft 95.0, 4 d | Wed 2026-11-25 | 19.0 | promise 95.0 on Wed 2026-11-11 |
| D-09 | Fri 2026-12-18 17:40 | p1 personal_loan 760.0, 18 d | Tue 2026-12-29 | 152.0 | callback Mon 2026-12-21 10:00; close not_reached / callback |
| D-10 | Fri 2026-10-30 10:00 | p1 credit_card 420.0, 8 d | Fri 2026-11-13 | 84.0 | transfer vulnerable_customers; close transferred / vulnerable |
| D-10 | Fri 2026-10-30 10:00 | p2 personal_loan 1100.0, 20 d | Fri 2026-11-06 | 220.0 |  |
| D-10 | Fri 2026-10-30 10:00 | p3 overdraft 230.0, 40 d | Mon 2026-11-02 | 46.0 |  |
| D-11 | Tue 2026-11-03 09:30 | p1 personal_loan 640.0, 22 d | Tue 2026-11-10 | 128.0 | close not_verified / declined |
| D-12 | Tue 2026-11-03 09:30 | p1 credit_card 230.0, 8 d | Tue 2026-11-17 | 46.0 | promise 230.0 on Mon 2026-11-09; close promise |
| D-12 | Tue 2026-11-03 09:30 | p2 personal_loan 640.0, 22 d | Tue 2026-11-10 | 128.0 | promise 640.0 on Mon 2026-11-09 |
| D-13 | Wed 2026-11-11 14:00 | p1 credit_card 240.0, 9 d | Wed 2026-11-25 | 48.0 | promise 240.0 on Fri 2026-11-20; close promise |
| D-14 | Thu 2026-12-24 15:00 | p1 personal_loan 880.0, 26 d | Thu 2026-12-31 | 176.0 | promise 880.0 on Thu 2026-12-31; close promise |
| D-15 | Mon 2026-10-26 11:00 | p1 overdraft 150.0, 33 d | Thu 2026-10-29 | 30.0 | promise 150.0 on Thu 2026-10-29; close promise |
| D-16 | Tue 2026-11-03 09:30 | p1 personal_loan 500.0, 15 d | Tue 2026-11-10 | 100.0 | promise 500.0 on Fri 2026-11-06; close promise |
| D-17 | Fri 2026-12-18 17:40 | p1 credit_card 600.0, 20 d | Tue 2026-12-29 | 120.0 | promise 120.0 on Tue 2026-12-29; close promise |
| D-18 | Wed 2026-11-11 14:00 | p1 credit_card 200.0, 5 d | Wed 2026-11-25 | 40.0 | promise 40.0 on Fri 2026-11-13; close promise |
| D-18 | Wed 2026-11-11 14:00 | p2 personal_loan 1000.0, 40 d | Mon 2026-11-16 | 200.0 | promise 1000.0 on Mon 2026-11-16 |
| D-19 | Sat 2026-11-14 10:30 | p1 overdraft 75.0, 14 d | Mon 2026-11-23 | 15.0 | note paid; close paid |
| D-20 | Tue 2026-12-29 21:30 | p1 personal_loan 1300.0, 45 d | Mon 2027-01-04 | 260.0 | transfer arrangements; close transferred / arrangements |
| D-21 | Mon 2026-10-26 11:00 | p1 personal_loan 400.0, 10 d | Mon 2026-11-09 | 80.0 | transfer general; close transferred / human |
| D-22 | Mon 2026-10-26 11:00 | p1 credit_card 260.0, 6 d | Mon 2026-11-09 | 52.0 | promise 260.0 on Mon 2026-11-02; close promise |
| D-23 | Wed 2026-11-11 14:00 | p1 overdraft 120.0, 12 d | Wed 2026-11-18 | 24.0 | note service_error; close no_promise / service_error |
| D-24 | Thu 2026-12-24 15:00 | p1 credit_card 300.0, 9 d | Thu 2027-01-07 | 60.0 | promise 300.0 on Wed 2026-12-30; close promise |
| D-24 | Thu 2026-12-24 15:00 | p2 personal_loan 1500.0, 28 d | Thu 2026-12-31 | 300.0 | note refused |
| D-24 | Thu 2026-12-24 15:00 | p3 overdraft 200.0, 50 d | Tue 2026-12-29 | 40.0 | promise 40.0 on Tue 2026-12-29 |
| D-25 | Fri 2026-12-18 17:40 | p1 credit_card 180.0, 6 d | Mon 2027-01-04 | 36.0 | promise 180.0 on Wed 2026-12-30; close promise |
| D-25 | Fri 2026-12-18 17:40 | p2 personal_loan 700.0, 25 d | Tue 2026-12-29 | 140.0 | promise 700.0 on Tue 2026-12-29 |
| D-25 | Fri 2026-12-18 17:40 | p3 overdraft 260.0, 35 d | Mon 2026-12-21 | 52.0 | promise 260.0 on Mon 2026-12-21 |
| D-26 | Tue 2026-12-29 21:30 | p1 credit_card 350.0, 20 d | Tue 2027-01-05 | 70.0 | close not_verified / do_not_call |
| D-27 | Sun 2026-11-22 19:00 | p1 credit_card 410.0, 12 d | Mon 2026-11-30 | 82.0 | note refused; close no_promise / do_not_call |
| D-27 | Sun 2026-11-22 19:00 | p2 personal_loan 850.0, 30 d | Mon 2026-11-30 | 170.0 | note refused |
| D-28 | Sat 2026-11-14 10:30 | p1 credit_card 275.0, 14 d | Mon 2026-11-23 | 55.0 | note hardship; close no_promise / hardship |
| D-28 | Sat 2026-11-14 10:30 | p2 personal_loan 920.0, 21 d | Mon 2026-11-23 | 184.0 | note hardship |
| D-29 | Mon 2026-10-26 11:00 | p1 credit_card 90.0, 3 d | Mon 2026-11-09 | 18.0 | close no_promise / dispute |
| D-29 | Mon 2026-10-26 11:00 | p2 personal_loan 640.0, 16 d | Mon 2026-11-02 | 128.0 | note dispute |
| D-30 | Tue 2026-12-29 21:30 | p1 personal_loan 350.0, 20 d | Tue 2027-01-05 | 70.0 | note refused; close no_promise / refused |

Talking styles: D-01 in_words, D-02 corrects, D-03 talkative, D-05 asks_back, D-07 pieces, D-08 in_words, D-10 talkative, D-11 asks_back, D-12 asks_back, D-13 corrects, D-14 in_words, D-15 talkative, D-16 pieces, D-17 in_words, D-18 corrects, D-19 talkative, D-20 talkative, D-21 in_words, D-22 pieces, D-23 in_words, D-24 corrects, D-25 corrects, D-27 pieces, D-28 asks_back, D-29 pieces, D-30 asks_back.
