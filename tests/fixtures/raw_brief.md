From: Head of Collections
To: Dialogue platform team
Subject: Calling window and outcome codes
Date: 2026-11-02

Please find below the memo that replaces section 4 of the brief dated 14 October 2026. The
callback window in rule 6 is replaced; everything else in that section stays.

---

MEMO
2 November 2026

Effective 2026-11-09, a callback is for today or the next two business days, from 09:00 to 18:00, both
included, and later than `now`. Rule 6 of the brief of 14 October 2026 is replaced by this paragraph. Rule 7
is unchanged: ask once for another time, e.g. an hour later. Dr. Alvarez signed this off.

> Note from the platform team: the old window still applies to calls placed before the effective date.

# Outcome codes

The codes below are sent as `close_call.reason`. The table in the brief lists the outcomes.

| Code | Outcome | Reason |
|------|---------|--------|
| NR-1 | `not_reached` | `callback` |
| NR-2 | `not_reached` | `no_callback` |

```
NR-3  not_reached / wrong_number
NR-4  not_reached / deceased
```

1. Use NR-3 when the person says the number does not belong to the customer. Say nothing else.
2. Use NR-4 when the person says the customer has died. Say "I am sorry for your loss." and ask nothing else.
   - Both codes close the call at once.

Mr. Keskin asked whether 10.5 days counts as late. It does not: days are whole numbers.[^1]

[^1]: `days_late` is an integer in `get_account`.
