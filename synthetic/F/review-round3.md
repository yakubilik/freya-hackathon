## FINDINGS

1. **MAJOR — F/brief.md — “Identity,” do-not-call paragraph; “Closing,” “nothing the customer says changes the result except a transfer.”** A do-not-call request after a recorded promise requires both `refused/no_contact` and `promise`. **Fix:** Explicitly exempt `no_contact` from the post-promise closing rule, preserving the recorded promise while recording the note and closing `refused/no_contact`.

2. **MAJOR — F/brief.md — “Closing,” “Every call has one `close_call`” versus “When a tool other than `create_promise` is not ok … tries one more time.”** The retry rule includes `close_call`, requiring a second invocation when the first fails. **Fix:** Exclude `close_call` from retries and specify that its single invocation ends tool use even on failure.

3. **MAJOR — F/brief.md — “Identity,” “says the wish is noted and calls `add_note`”; “Closing,” prohibition on claiming unsuccessful actions.** The instruction announces successful noting before the tool succeeds. A failed note therefore makes compliance with both instructions impossible. **Fix:** Acknowledge the request first; say it was noted only after `add_note` returns `ok: true`. Specify the wording after two failures.

4. **MAJOR — F/brief.md — “Identity,” impossible birth dates; “Closing,” two unsuccessful `verify_identity` calls.** Impossible dates produce `ok: false` and require another question without counting a wrong answer. The general failure rule nevertheless terminates verification after two such responses. Validation failures and service failures are conflated. **Fix:** Exclude invalid-date responses from the service-failure counter and specify how to identify them, such as a documented `error` value.

5. **MAJOR — F/brief.md — “Closing,” failed-transfer recovery.** “Continues like the customer said no to it” has no defined continuation for `plans` or `people`. Moreover, two failed `care` transfers after a recorded promise require `refused/no_money`, conflicting with the rule preserving `promise` unless a transfer occurs. **Fix:** State the continuation for each queue and whether a promise already exists; explicitly preserve `promise` when a subsequent transfer fails.

6. **MINOR — F/api.json — every `200` response schema, especially `/get_account` and `/verify_identity`.** All response properties are optional: `{}` and successful responses without account or identity results satisfy the schemas, although the brief requires those results to proceed. This is a contract-completeness defect, not invalid OpenAPI syntax. **Fix:** Require `ok`; define success branches requiring the relevant result fields and required product data. OpenAPI 3.0.3 supports these schema constraints. [OpenAPI specification](https://spec.openapis.org/oas/v3.0.3.html#schema-object)

## DATE ARITHMETIC

F-01 — p1/card: 12 days late → month-end rule; October 27, 28, 29, 30 give four working days remaining, so limit = **2026-10-30**; floor = **€40**. Following calendar week is November 2–8, so “next Friday” = November 6, beyond the limit; customer accepts October 30. **€210 on 2026-10-30 agrees**; `promise`, no reason, notes, callbacks or transfers agrees.

F-02 — p1/consumer_loan: 8 days late → month-end rule; October 29 and 30 give only two working days remaining, so use next month’s last working day: Monday **2026-11-30**; November 11’s holiday does not change that endpoint. Floor = **€60**. Non-answer triggers the single minimum-at-limit offer, accepted and confirmed. **€60 on 2026-11-30 agrees**; `promise`, no reason, notes, callbacks or transfers agrees.

F-03 — p1/auto_loan, callback: 20 days late → working days after November 7 are November 9 (1), 10 (2), skip holiday 11, 12 (3), 13 (4), skip weekend 14–15, 16 (5); limit = **2026-11-16**, floor = **€180**. Callback starts from tomorrow, Sunday November 8, rolling forward to Monday **November 9**; 09:00 is outside 10:00–18:00, replacement 11:00 is valid. **2026-11-09 at 11:00 agrees**; `not_reached/callback`, no promises, notes or transfers agrees.

F-04 — p1/card, no promise: 22 days late → after December 18, skip weekend 19–20; December 21 (1), 22 (2), 23 (3), skip holidays 24–25 and weekend 26–27, 28 (4), 29 (5); limit = **2026-12-29**, floor = **€70**. Offered **€100 on December 22** meets amount/date constraints, but hospitalization requires immediate `care` transfer. **No promise and `transferred/care` agree**; one `care` transfer, no notes or callbacks agrees.

F-05 — p1/consumer_loan, no promise: 45 days late → after November 30, December 1 (1), 2 (2), 3 (3), 4 (4), skip weekend 5–6, 7 (5); limit = **2026-12-07**, floor = **€190**. All three supplied dates are valid calendar dates but wrong birth dates, exhausting verification. **`not_verified/failed` agrees**; no promises, notes, callbacks or transfers agrees.

F-06 — p1/auto_loan: 7 days late → month-end rule; November 4, 5 and 6 alone establish at least three working days remaining, so limit = Monday **2026-11-30**; floor = **€150**. Today, Wednesday **November 4**, is a working day within the limit. **€450 on 2026-11-04 agrees**; subsequent insistence on a human produces one `people` transfer and `transferred/human`, preserving the promise; no notes or callbacks agrees.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
