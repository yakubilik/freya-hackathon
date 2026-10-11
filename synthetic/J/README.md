# Brief J: what it varies and the derived dates

Brief J (Kestrel Bank) is **raw material** with lettered sections (A to H): a mail, the CCS-A standard, an amendment and a code list. Field names differ throughout: `account_no`, `check`/`value` on `verify_identity`, `debts` with `kind`, `amount_due`, `days_overdue`, `minimum`, `pay_by` on `create_promise`, `flag` on `add_note`, `result`/`detail` on `close_call` (`arranged`, `routed`, `no_arrangement`, ...). The amendment moves the above-1,000 band from the 5th to the 4th business day, gives **mortgage arrears** a fixed 3rd-business-day deadline whatever the amount, replaces the half-rule minimum with the `minimum` field, **withdraws the confirmation sentence with no replacement**, renames `welfare` to `customer_care` and adds a complaints rule. Two persuasion attempts (full amount on the last business day of this week or next, then the minimum on the deadline); wrong answers counted in total, limit three; a correction in the same breath is one answer; pounds in words; recording notice required but free wording. Holidays: 2026-10-19 (systems day), 2026-12-25, 2026-12-28, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| J-01 | Fri 2026-10-16 17:30 | p1 card 450.0, 12 d | Mon 2026-11-02 | 90.0 | promise 450.0 on Wed 2026-10-28; close arranged |
| J-01 | Fri 2026-10-16 17:30 | p2 mortgage_arrears 1300.0, 35 d | Thu 2026-10-22 | 650.0 | promise 1300.0 on Thu 2026-10-22 |
| J-02 | Wed 2026-11-04 11:00 | p1 loan 1600.0, 20 d | Tue 2026-11-10 | 400.0 | promise 400.0 on Tue 2026-11-10; close arranged |
| J-03 | Sat 2026-10-31 09:30 | p1 card 230.0, 8 d | Fri 2026-11-13 | 46.0 | transfer complaints; close routed / complaint |
| J-04 | Mon 2026-12-21 19:00 | p1 card 300.0, 15 d | Thu 2027-01-07 | 60.0 | note disputed; close no_arrangement / disputed |
| J-04 | Mon 2026-12-21 19:00 | p2 loan 520.0, 9 d | Thu 2027-01-07 | 130.0 | note paid |
| J-04 | Mon 2026-12-21 19:00 | p3 mortgage_arrears 2000.0, 28 d | Thu 2026-12-24 | 1000.0 | note refused |
| J-05 | Thu 2026-10-22 10:00 | p1 loan 800.0, 14 d | Thu 2026-11-05 | 200.0 | promise 200.0 on Fri 2026-10-30; close arranged |
| J-06 | Tue 2026-12-29 17:45 | p1 loan 275.0, 40 d | Wed 2027-01-13 | 70.0 | close not_reached / deceased |

Talking styles: J-01 in_words, J-02 talkative, J-03 asks_back, J-04 corrects, J-05 pieces.
