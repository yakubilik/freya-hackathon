# Brief I: what it varies and the derived dates

Brief I (Tamsin Finance) is **raw material** from a US consumer-finance payments team: a mail, a procedure with numbered sections, a change notice and a code sheet. Amounts are US dollars carried as **strings with two decimals** (`"312.40"`), three security questions (date of birth, ZIP code sent as `postcode`, phone last four) with a **per-question** limit of two, and a bare numeric date is read month-day-year. The change notice moves the 16-to-45 band from the 6th to the 5th business day, adds a 46-to-90 band (2nd business day), replaces the 10 percent minimum with the `min_due` field, renames `collections_team` to `hardship_team` and swaps the letter sentence for an email sentence. The mail removes any recording notice, defines a bare weekday, repeats the vague-period rule and gives the holidays. One persuasion attempt: the full amount (or the minimum) on the 3rd business day after today or the deadline, whichever is earlier. Hardship offers `hardship_team` once; plans and humans go to `payments_team`; a verified do-not-call notes the products without a promise and closes `no_promise` / `do_not_call`, or `promise` if one was recorded. Holidays: 2026-10-12, 2026-11-11, 2026-11-26, 2026-11-27, 2026-12-25, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| I-01 | Fri 2026-10-09 17:30 | p1 store_card 312.40, 8 d | Mon 2026-10-26 | 35.00 | promise 312.40 on Tue 2026-10-13; close promise |
| I-02 | Mon 2026-11-30 21:00 | p1 store_card 140.00, 14 d | Mon 2026-12-14 | 20.00 | note paid; close promise |
| I-02 | Mon 2026-11-30 21:00 | p2 auto_loan 1180.00, 50 d | Wed 2026-12-02 | 295.00 | promise 295.00 on Wed 2026-12-02 |
| I-03 | Wed 2026-11-25 10:00 | p1 instalment_loan 620.00, 22 d | Fri 2026-12-04 | 155.00 | note do_not_call; close no_promise / do_not_call |
| I-03 | Wed 2026-11-25 10:00 | p2 store_card 88.50, 6 d | Fri 2026-12-11 | 15.00 | note do_not_call |
| I-04 | Sat 2026-10-24 12:00 | p1 auto_loan 910.00, 30 d | Fri 2026-10-30 | 228.00 | close not_reached / no_callback |
| I-05 | Tue 2026-12-01 14:00 | p1 instalment_loan 840.00, 20 d | Tue 2026-12-08 | 210.00 | promise 840.00 on Tue 2026-12-08; close promise |
| I-06 | Thu 2026-11-12 16:00 | p1 auto_loan 1320.00, 48 d | Mon 2026-11-16 | 330.00 | transfer hardship_team; close transferred / hardship |
| I-07 | Wed 2026-10-14 09:00 | p1 store_card 245.60, 7 d | Wed 2026-10-28 | 25.00 | promise 245.60 on Wed 2026-10-14; close promise |
| I-08 | Tue 2026-10-20 13:00 | p1 auto_loan 980.00, 20 d | Tue 2026-10-27 | 245.00 | promise 980.00 on Tue 2026-10-20; close promise |
| I-08 | Tue 2026-10-20 13:00 | p2 store_card 120.00, 5 d | Tue 2026-11-03 | 15.00 | promise 120.00 on Tue 2026-10-20 |
| I-09 | Fri 2026-11-20 17:45 | p1 instalment_loan 560.00, 18 d | Tue 2026-12-01 | 140.00 | callback Mon 2026-11-23 09:00; close not_reached / callback |
| I-10 | Sat 2026-12-12 11:00 | p1 auto_loan 430.00, 9 d | Mon 2026-12-28 | 108.00 | close not_reached / deceased |
| I-11 | Tue 2026-11-10 15:00 | p1 instalment_loan 430.00, 12 d | Wed 2026-11-25 | 45.00 | promise 430.00 on Fri 2026-11-13; close promise |
| I-12 | Sat 2026-10-31 10:00 | p1 store_card 210.00, 20 d | Fri 2026-11-06 | 25.00 | close not_verified / failed |
| I-13 | Wed 2026-11-04 19:30 | p1 store_card 88.00, 8 d | Thu 2026-11-19 | 15.00 | close not_reached / unclear |
| I-14 | Thu 2026-12-24 16:30 | p1 auto_loan 1250.00, 30 d | Mon 2027-01-04 | 313.00 | close not_verified / declined |
| I-14 | Thu 2026-12-24 16:30 | p2 store_card 140.00, 8 d | Mon 2027-01-11 | 20.00 |  |
| I-15 | Wed 2026-10-14 09:00 | p1 store_card 310.00, 3 d | Wed 2026-10-28 | 35.00 | promise 310.00 on Mon 2026-10-19; close promise |
| I-16 | Mon 2026-10-12 10:00 | p1 auto_loan 640.00, 18 d | Mon 2026-10-19 | 160.00 | promise 640.00 on Tue 2026-10-13; close promise |
| I-17 | Thu 2026-12-31 20:30 | p1 store_card 150.00, 9 d | Fri 2027-01-15 | 20.00 | promise 150.00 on Mon 2027-01-04; close promise |
| I-18 | Tue 2026-11-10 15:00 | p1 instalment_loan 520.00, 30 d | Wed 2026-11-18 | 130.00 | promise 520.00 on Wed 2026-11-18; close promise |
| I-19 | Sat 2026-12-12 11:00 | p1 auto_loan 1050.00, 50 d | Tue 2026-12-15 | 263.00 | promise 1050.00 on Tue 2026-12-15; close promise |
| I-20 | Wed 2026-11-04 19:30 | p1 store_card 400.00, 25 d | Thu 2026-11-12 | 40.00 | promise 40.00 on Fri 2026-11-06; close promise |
| I-21 | Tue 2026-10-20 13:00 | p1 store_card 200.00, 10 d | Tue 2026-11-03 | 20.00 | promise 20.00 on Fri 2026-10-23; close promise |
| I-21 | Tue 2026-10-20 13:00 | p2 instalment_loan 900.00, 40 d | Tue 2026-10-27 | 225.00 | promise 900.00 on Mon 2026-10-26 |
| I-22 | Sat 2026-10-31 10:00 | p1 instalment_loan 330.00, 20 d | Fri 2026-11-06 | 83.00 | note paid; close paid |
| I-23 | Thu 2026-12-24 16:30 | p1 auto_loan 1400.00, 20 d | Mon 2027-01-04 | 350.00 | transfer payments_team; close transferred / plan |
| I-23 | Thu 2026-12-24 16:30 | p2 store_card 260.00, 8 d | Mon 2027-01-11 | 30.00 |  |
| I-24 | Fri 2026-11-20 17:45 | p1 store_card 190.00, 12 d | Tue 2026-12-08 | 20.00 | promise 190.00 on Fri 2026-11-20; transfer payments_team; close transferred / human |
| I-24 | Fri 2026-11-20 17:45 | p2 auto_loan 820.00, 30 d | Tue 2026-12-01 | 205.00 | promise 820.00 on Fri 2026-11-20 |
| I-25 | Wed 2026-10-14 09:00 | p1 instalment_loan 275.00, 8 d | Wed 2026-10-28 | 30.00 | promise 275.00 on Mon 2026-10-19; close promise |
| I-26 | Tue 2026-11-10 15:00 | p1 store_card 160.00, 16 d | Wed 2026-11-18 | 40.00 | note service_error; close no_promise / service_error |
| I-27 | Fri 2026-11-20 17:45 | p1 store_card 95.00, 60 d | Tue 2026-11-24 | 15.00 | note dispute; close promise |
| I-27 | Fri 2026-11-20 17:45 | p2 auto_loan 1400.00, 14 d | Tue 2026-12-08 | 350.00 | promise 1400.00 on Fri 2026-12-04 |
| I-27 | Fri 2026-11-20 17:45 | p3 instalment_loan 300.00, 20 d | Tue 2026-12-01 | 75.00 | note refused |
| I-28 | Thu 2026-12-24 16:30 | p1 store_card 180.00, 8 d | Mon 2027-01-11 | 20.00 | promise 180.00 on Tue 2027-01-05; close promise |
| I-28 | Thu 2026-12-24 16:30 | p2 auto_loan 760.00, 35 d | Mon 2027-01-04 | 190.00 | promise 760.00 on Mon 2027-01-04 |
| I-28 | Thu 2026-12-24 16:30 | p3 instalment_loan 240.00, 55 d | Tue 2026-12-29 | 60.00 | promise 240.00 on Tue 2026-12-29 |
| I-29 | Sat 2026-10-31 10:00 | p1 store_card 260.00, 9 d | Mon 2026-11-16 | 30.00 | note hardship; close no_promise / hardship |
| I-29 | Sat 2026-10-31 10:00 | p2 auto_loan 1100.00, 35 d | Fri 2026-11-06 | 275.00 | note hardship |
| I-30 | Wed 2026-11-04 19:30 | p1 store_card 160.00, 10 d | Thu 2026-11-19 | 30.00 | promise 160.00 on Fri 2026-11-06; close promise |
| I-30 | Wed 2026-11-04 19:30 | p2 instalment_loan 450.00, 22 d | Thu 2026-11-12 | 90.00 | note refused |

Talking styles: I-01 corrects, I-02 pieces, I-03 talkative, I-05 asks_back, I-06 in_words, I-07 pieces, I-08 in_words, I-12 asks_back, I-14 asks_back, I-15 talkative, I-16 pieces, I-17 corrects, I-18 in_words, I-19 corrects, I-20 in_words, I-21 corrects, I-22 talkative, I-23 asks_back, I-24 in_words, I-25 talkative, I-26 pieces, I-27 talkative, I-28 corrects, I-29 pieces, I-30 asks_back.
