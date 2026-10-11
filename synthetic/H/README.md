# Brief H: what it varies and the derived dates

Brief H (Portmann Bank) is **raw bank material** with a built-in contradiction: the policy says one persuasion attempt in 6.1 and describes two in 6.3; the compliance memo settles it (two). The memo also withdraws the recording sentence (so the opening has **no recording notice**), replaces the 20 percent floor with the `floor` field that `get_account` returns, adds a third deadline band (above 2,000: 4 calendar days) and renames `care_team` to `wellbeing`. The mail overrides the policy on the human request (transfer to `front_desk` at once, no "can I help first") and gives the exact opening sentence, postcode handling (four digits, said in pieces, with punctuation), the two-digit year rule and the holidays. Deadlines are in **calendar days by amount** (14, 7 or 4) moved **back** to the last business day; both persuasion attempts land on the deadline (full amount, then the floor); hardship always transfers; a dispute is an `add_note` with `not_mine`, `already_closed` or `amount_wrong` and stops the call; the id is `client_ref`, amounts are euros. Closing days: 2026-10-23 (Foundation Day), 2026-12-08, 2026-12-25, 2027-01-01, 2027-01-06.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| H-01 | Thu 2026-10-22 18:30 | p1 credit_card 410.0, 14 d | Thu 2026-10-29 | 82.0 | close unreachable / unclear |
| H-02 | Fri 2026-10-30 17:30 | p1 credit_card 2450.0, 9 d | Tue 2026-11-03 | 500.0 | promise 500.0 on Tue 2026-11-03; close pledge |
| H-03 | Mon 2026-11-30 09:15 | p1 credit_card 180.0, 6 d | Mon 2026-12-14 | 36.0 | promise 180.0 on Fri 2026-12-04; transfer front_desk; close transferred / human |
| H-03 | Mon 2026-11-30 09:15 | p2 personal_loan 900.0, 20 d | Mon 2026-12-07 | 300.0 | promise 900.0 on Fri 2026-12-04 |
| H-03 | Mon 2026-11-30 09:15 | p3 car_loan 2100.0, 35 d | Fri 2026-12-04 | 700.0 | promise 2100.0 on Fri 2026-12-04 |
| H-04 | Sat 2026-12-05 10:00 | p1 personal_loan 600.0, 40 d | Fri 2026-12-11 | 150.0 | note refused; close no_pledge / refused |
| H-05 | Wed 2026-12-23 15:00 | p1 credit_card 150.0, 30 d | Tue 2027-01-05 | 30.0 | note already_closed; close no_pledge / dispute |
| H-05 | Wed 2026-12-23 15:00 | p2 car_loan 1800.0, 12 d | Wed 2026-12-30 | 600.0 |  |
| H-06 | Tue 2026-11-10 20:30 | p1 car_loan 950.0, 18 d | Tue 2026-11-17 | 320.0 | transfer wellbeing; close transferred / wellbeing |

Talking styles: H-02 in_words, H-03 corrects, H-04 pieces, H-05 asks_back, H-06 talkative.
