## FINDINGS

1. **MAJOR — E/brief.md — §8 “Payment plan” / “Request for a person”; §10 `promise` row.** After a recorded promise, §8 requires `callback_booked` for a subsequent plan or human request, while §10 requires `promise` whenever at least one promise was recorded. Both instructions are table rules, so “table wins” resolves nothing. **Smallest fix:** qualify the `promise` row with “unless a callback is booked”; explicitly give `callback_booked` precedence.

2. **MAJOR — E/brief.md — §6 “One date for all products, later than one product’s deadline”.** Keeping “the rest on the named date” can require an invalid weekend/holiday promise. Using E-01’s products, a shared **12 December 2026** produces the loan’s deadline, 9 December, but leaves the card on Saturday 12 December, contradicting the business-day requirement. **Smallest fix:** require business-day normalization for every retained date; here the card becomes Monday 14 December, subject to confirmation.

3. **MAJOR — E/brief.md — §8 “Payment plan”, “Request for a person” and “Hardship”.** “Please have a person call me to arrange instalments” triggers both callback rules, prescribing different reasons: `arrangement` and `human_requested`. Precedence is specified for hardship but not between these two requests. **Smallest fix:** state that an arrangement request takes precedence over a generic human request.

4. **MAJOR — E/brief.md — §3 “Callback window” and §8 callback rows; E/api.json — `/schedule_callback/post/responses`.** The brief unconditionally closes as `callback_booked` after invoking the tool, although its documented responses include `ok: false` and HTTP 500, with nothing recorded. That can label an unsuccessful booking as successful. **Smallest fix:** require `ok: true` before that outcome and specify a bounded retry and failure closing path, including the situation where a promise already exists.

## DATE ARITHMETIC

Business-day counts exclude today, weekends and only Northgate’s listed holidays. Amounts below use cents unless marked otherwise.

- **E-01, p1 promise:** bare “Friday” after Wednesday 25 November means **27 November**, a holiday; 28–29 November are the weekend, so roll forward to **30 November**. Deadline: 30 November–4 December = 5 business days, 7–11 December = 10, 14–18 December = 15 → **18 December**. Floor: ceil($842.50 × 30%) = **$253 = 25300**; full promise **84250** is valid. **Agrees.**
- **E-01, p2 promise:** excluding 26–27 November holidays and 28–29 November weekend, count 30 November(1), 1–4 December(2–5), 7–9 December(6–8) → deadline **9 December**. Floor: $2,500 × 30% = **$750 = 75000**; the accepted **9 December** promise is exactly on deadline. **Agrees.**
- **E-02, callback concerning p1:** after Friday **18 December, 17:30**, skip 19–20 December; next two business days are **21 and 22 December**. “Monday morning at eight” gives **21 December, 08:00**, within the inclusive window and after `now`. **Agrees.**
- **E-04, callback concerning p1:** Tuesday **1 December** + one business day = Wednesday **2 December**; the arrangement rule fixes the time at **10:00**. **Agrees.**
- **E-05, p1 promise:** “today” is Thursday **29 October**, a business day. Deadline: 30 October(1), 2–6 November(2–6), 9–13 November(7–11), 16–19 November(12–15) → **19 November**. Northgate does **not** exclude 11 November. Floor: $420 × 30% = **$126 = 12600**; full promise **42000** today is valid. **Agrees.**

The remaining product calculations, including products whose accounts must not be retrieved during the actual call:

| Case/product | Deadline arithmetic | Floor calculation |
|---|---|---|
| E-02 p1 | 21–23 December(1–3); skip holidays 24–25 and weekend 26–27; 28–31 December(4–7); skip holiday 1 January and weekend 2–3; **4 January 2027(8)** | $1,900 × 30% = **57000** |
| E-03 p1 | 1–4 December(1–4), 7–10 December(5–8) → **10 December** | $1,280 × 30% = **38400** |
| E-04 p1 | 2–4 December(1–3), 7–11 December(4–8) → **11 December** | $3,200 × 30% = **96000** |
| E-05 p2 | 30 October(1), 2–6 November(2–6), 9 November(7), **10 November(8)** | $3,100 × 30% = **93000** |
| E-06 p1 | 16–20 November(1–5), 23–25 November(6–8); skip 26–29; 30 November–4 December(9–13), 7–8 December(14–15) → **8 December** | $560 × 30% = **16800** |

All eight deadline/floor pairs agree with **E/README.md**. Every case’s expected result agrees with its script, assuming successful recording/booking tools:

| Case | Confirmed outcome, reason and remaining actions |
|---|---|
| E-01 | `promise`, no reason; both promises above; no notes, callbacks or transfers. |
| E-02 | `callback_booked / unavailable`; callback above; no verification, promises, notes or transfers. |
| E-03 | `no_promise / declined`; p1 note `declined`; no promises, callbacks or transfers. The stated inability to pay does not itself assert one of the listed hardship circumstances. |
| E-04 | `callback_booked / arrangement`; callback above; no promises, notes or transfers. |
| E-05 | `promise`, no reason; preserve and record the agreed card promise; p2 note `hardship`; support-line information, no callbacks or transfers. |
| E-06 | `id_failed / wrong_answers`; wrong number(1), correct number, wrong founding year(2); no account disclosure, promises, notes, callbacks or transfers. |

The API is valid JSON and structurally conforms to [OpenAPI 3.0.3](https://spec.openapis.org/oas/v3.0.3.html), with exactly the seven required paths. Request bodies and response schemas are valid; optional response properties and description-only 500 responses do not invalidate OpenAPI. Tool names, fields, product types and used reason/outcome values are compatible.

All **25 checks** are transcript-judgeable, including visible tool calls/results. All customers have one or two products; all six `now` values differ; four cases have permitted styles; several non-promise outcomes are correct. No verbatim sentence copy from public A/B was found, and the substantive policy values differ. This is a consolidated brief, so the raw-policy/memo requirement is **not applicable**.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
