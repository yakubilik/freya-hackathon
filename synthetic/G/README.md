# Brief G: what it varies and the derived dates

Brief G (Ashworth Mutual) is **raw bank material**: a mail from the head of collections, policy version 4 with P-numbered rules, a memo that amends the policy in ten points (six substantive changes plus precedence and failure rules added after review), and a code list. The memo changes the 15-to-60-day deadline band from the 5th to the 6th business day, adds a 61-to-90 band (3rd business day), replaces the total wrong-answer limit by a **per-question** limit of two, raises the minimum from 20 to 25 percent, withdraws the letter sentence in favour of a text message sentence, renames the `welfare_team` queue to `financial_support` and withdraws the second persuasion attempt. The mail adds the exact recording sentence, a complaints rule (`XFER` / `COMP`), do-not-call handling with `DNC` notes, the meaning of a bare weekday, and the holidays. Codes are upper-case ledger codes (`PTP`, `NOPTP`, `IDFAIL`, `NOCON`, `XFER`, `PAID`; product types `CC`, `PL`, `HP`), the id is `customer_ref`, amounts are pounds. Holidays: 2026-11-20 (staff day), 2026-12-25, 2026-12-28, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| G-01 | Thu 2026-11-19 16:00 | p1 CC 640.0, 20 d | Mon 2026-11-30 | 160.0 | promise 640.0 on Mon 2026-11-30; close PTP |
| G-02 | Fri 2026-12-11 17:30 | p1 CC 400.0, 12 d | Tue 2026-12-29 | 100.0 | note REF; close NOPTP / REF |
| G-02 | Fri 2026-12-11 17:30 | p2 PL 1200.0, 30 d | Mon 2026-12-21 | 300.0 | note REF |
| G-02 | Fri 2026-12-11 17:30 | p3 HP 800.0, 70 d | Wed 2026-12-16 | 200.0 | note REF |
| G-03 | Mon 2026-11-30 10:30 | p1 PL 560.0, 9 d | Mon 2026-12-14 | 140.0 | close IDFAIL / FAIL |
| G-04 | Sat 2026-10-31 11:00 | p1 HP 1050.0, 16 d | Mon 2026-11-09 | 263.0 | callback Mon 2026-11-02 09:00; close NOCON / CB |
| G-05 | Wed 2026-10-14 11:00 | p1 CC 220.0, 7 d | Wed 2026-10-28 | 55.0 | transfer complaints; close XFER / COMP |
| G-06 | Tue 2026-12-01 19:30 | p1 HP 1000.0, 70 d | Fri 2026-12-04 | 250.0 | promise 250.0 on Fri 2026-12-04; close PTP |
| G-06 | Tue 2026-12-01 19:30 | p2 CC 999.0, 10 d | Tue 2026-12-15 | 250.0 | note HARD |

Talking styles: G-02 talkative, G-03 in_words, G-05 asks_back, G-06 corrects.
