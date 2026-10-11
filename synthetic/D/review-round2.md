## FINDINGS

1. **MAJOR — D/brief.md — “Amounts”: “offers the floor once”; “The ask and the two attempts”: first and second attempts.** After the customer rejects the full amount and then the floor, persuasion requires offering the floor again, potentially twice. This conflicts with the unqualified once-only instruction. **Fix:** Specify that “once” applies to the initial amount negotiation and that subsequent offers follow the persuasion rules.

2. **MAJOR — D/brief.md — “Stating the arrears”: “states every account”; “Disputes, payments already made”: “no further account is discussed”; D/cases.json — D-05.script.** D-05 interrupts the first account’s disclosure with a dispute. Stating every account would require continuing to the credit card; the dispute rule forbids that. The expected immediate stop follows the dispute rule but cannot satisfy the unconditional disclosure requirement. **Fix:** Explicitly exempt calls interrupted by a terminating dispute from the requirement to state every account.

3. **MAJOR — D/brief.md — “Security”, post-verification do-not-call rule; “Disputes, payments already made”, paid-note rule; “Recording”, service-error and deferred-note rules.** Do-not-call requires `refused` notes for **every** account without a promise, including accounts already classified `paid` or `service_error`. Those other rules require different notes, and exactly one note per account is allowed. The stated do-not-call precedence covers closing rules, leaving note classification unresolved. **Fix:** Explicitly preserve `paid` and `service_error` notes and assign `refused` only to other unpromised accounts, or explicitly state that do-not-call replaces those pending reasons.

## DATE ARITHMETIC

- **D-01 — p1/p2/p3, no promises:** p1: 2026-10-29 + 14 calendar days = Thu 2026-11-12, floor £46; p2: +7 = Thu 2026-11-05, floor £290; p3: Oct 30 counts as day 1 despite the holiday, Oct 31 day 2, Nov 1 day 3 → roll forward to Mon 2026-11-02, floor £62. Two wrong birth dates plus the wrong postcode exhaust three errors. **Agrees:** `not_verified/failed`; no promises, notes, callbacks or transfers.
- **D-02 — p1 credit_card:** Fri 2026-11-27 +14 calendar days = Fri 2026-12-11; floor £55. Requested Thu 2026-12-10 is a business day within the deadline; £275 equals full arrears. **Agrees:** £275 on 2026-12-10.
- **D-02 — p2 personal_loan:** 2026-11-27 +7 calendar days = Fri 2026-12-04; floor £320. Shared requested date Dec 10 exceeds this deadline, so the accepted adjustment is Dec 4; £960 equals full arrears. **Agrees:** £960 on 2026-12-04; combined close `promise`, reason absent, no notes, callbacks or transfers.
- **D-03 — p1 personal_loan:** Mon 2026-11-30 +7 calendar days = Mon 2026-12-07; floor £90. Bare “Friday” means the first Friday after today, Dec 4; £90 ≤ £200 ≤ £450. **Agrees:** £200 on 2026-12-04; close `promise`, reason absent; declined transfer and successful promise mean no transfers or hardship notes; no callbacks.
- **D-04 — p1 overdraft / callback:** Sat 2026-10-17 +14 calendar days = Sat Oct 31 → skip Sun Nov 1 → Mon 2026-11-02; floor £28, unused. Next two business days after Oct 17 are Mon Oct 19 and Tue Oct 20. Monday 09:00 is within the inclusive 09:00–20:00 window. **Agrees:** callback 2026-10-19 09:00; close `not_reached/callback`; no promises, notes or transfers.
- **D-05 — p1 overdraft / p2 credit_card, no promises:** Both deadlines: Wed 2026-12-23 +7 calendar days = Wed Dec 30; Dec 25 and Dec 28 count within the seven calendar days. Floors are £19 and £128. **Agrees with the dispute rule, subject to finding 2:** only p1 `dispute` note, close `no_promise/dispute`; no promises, callbacks or transfers. The conditional Dec 30 credit-card offer must not be elicited.
- **D-06 — p1 credit_card, rejected offers:** Tue 2026-10-20 +3 calendar days = Fri Oct 23; floor £104. First attempt: next business day Wed Oct 21, £520. Second attempt: deadline Fri Oct 23, £104. Both rejected. **Agrees:** no recorded promise; one p1 `refused` note; close `no_promise/refused`; no callbacks or transfers.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
