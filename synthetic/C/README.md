# Brief C: what it varies and the derived dates

Brief C (Halvard Credit Union) is a clean, numbered specification of 53 rules. It varies: `client_ref` instead of `customer_id`; the security check is postcode then year of birth with a **per-question** limit of two wrong answers (`wrong_left_on_question` in the response); one product per member but `products` is still a list with `kind`, `overdue_amount`, `days_overdue`; euros spoken in words; the deadline is by **amount** (below 500: the 10th calendar day rolled **back** to a business day; 500 or more: the 5th business day); the floor is 25 percent rounded up; one persuasion attempt (the floor on the deadline); hardship is always a hand-over to `welfare`, even when a date is named in the same breath; a request for a person is handed over at once with no question; "next Friday" means the first Friday after today; callbacks only on the next business day, 09:00 to 17:00; confirmation by email; `add_note` is used only for a do-not-call request and has no product on it; a goodbye with a question open counts as the second "do not want to talk"; `close_call` outcomes are `pledge`, `settled`, `handed_over`, `no_pledge`, `unverified`, `unreachable`. Closing days: 2026-11-02, 2026-12-08, 2026-12-24, 2026-12-25, 2026-12-31, 2027-01-01.

## Derived dates per case

Deadline and floor re-derived from the brief's own rules and calendar by `_tools/derive.py`; every value was also computed by hand before the script was written (see the per-case `checks`). Harness convention: the brief's id variable (`client_ref`, `customer_id`, `customer_ref` or `account_no`) is generated per call and injected into every tool body; products get `product_id` `p1`, `p2`, `p3` in the order of the `products` list, which is the order `get_account` returns them.

| Case | `now` | Product | Deadline | Floor | Expected |
|---|---|---|---|---|---|
| C-01 | Fri 2026-10-16 17:30 | p1 card 380.0, 9 d | Mon 2026-10-26 | 95.0 | promise 380.0 on Fri 2026-10-16; close pledge |
| C-02 | Sat 2026-10-31 10:15 | p1 loan 920.0, 18 d | Mon 2026-11-09 | 230.0 | callback Tue 2026-11-03 10:00; close unreachable / callback_booked |
| C-03 | Wed 2026-12-23 19:45 | p1 loan 1240.0, 30 d | Tue 2027-01-05 | 310.0 | promise 310.0 on Tue 2027-01-05; close pledge |
| C-04 | Mon 2026-11-30 11:00 | p1 overdraft 455.5, 22 d | Thu 2026-12-10 | 114.0 | close no_pledge / disputed |
| C-05 | Wed 2026-10-21 14:00 | p1 card 268.0, 6 d | Fri 2026-10-30 | 67.0 | transfer welfare; close handed_over / welfare |
| C-06 | Tue 2026-10-13 09:30 | p1 loan 610.0, 12 d | Tue 2026-10-20 | 153.0 | close no_pledge / refused |

Talking styles: C-03 in_words, C-04 talkative, C-05 corrects, C-06 pieces.
