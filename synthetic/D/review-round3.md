## FINDINGS

1. **MAJOR — D/brief.md — “Security,” pre-verification do-not-call sentence; “Recording,” final paragraph; “Closing,” successful-tool requirement.** The caller must say the request “is noted,” but notes are forbidden on unverified calls, and claiming something was noted requires a successful tool response. **Fix:** acknowledge the request and end the call without claiming it was recorded.

2. **MAJOR — D/brief.md — “Closing,” the two sentences governing disputes after recording.** “A dispute raised after promises were recorded still gets its `dispute` note” includes disputes about an already-promised account. The later sentence permits matching notes only for accounts **without** promises. These instructions conflict for that account. **Fix:** explicitly restrict the earlier note requirement to accounts without recorded promises.

3. **MAJOR — D/brief.md — “Amounts,” restriction on repeating refused dates; “The ask and the two attempts,” mandatory second attempt and skip condition.** The second attempt can repeat an earlier rejected offer even when it differs from the first persuasion attempt. Example: the customer rejects the floor on the deadline during negotiation, then rejects the floor on the next business day during attempt one. Attempt two requires the already-rejected floor/deadline offer, which both sections prohibit. The stated skip condition covers only repetition of attempt one. **Fix:** also skip and count as used any attempt prohibited by the earlier-refusal rules.

4. **MAJOR — D/brief.md — “Closing,” general tool-retry sentence; “Recording,” mandatory notes.** No terminal behavior is defined when `add_note` fails twice. The brief still requires a note, and its closing decision depends on recorded notes. For a sole refused account, neither requirement can reliably be fulfilled. **Fix:** after two failed note attempts, permit closing using the previously decided account reason, without claiming the note succeeded.

5. **MAJOR — D/brief.md — “Deadlines and dates,” arrears bands; D/api.json — `/get_account` response, `accounts.items.properties.days_in_arrears`.** Deadlines exist only for arrears ages 1–60, but neither the brief’s scope nor the API excludes accounts over 60 days late. Such an account has no computable deadline. **Fix:** explicitly limit eligible accounts to 1–60 days and constrain that response field accordingly, or define the missing band.

6. **MINOR — D/api.json — all `200` response schemas, especially `/verify_identity` and `/get_account`.** All response properties are optional: `{}` and successful account responses missing product identifiers, balances or floors satisfy the schemas but cannot support the brief. This is contract incompleteness, **not invalid OpenAPI**; the document has the required structure and exactly the seven requested paths. **Fix:** require `ok` and define success/error alternatives requiring the fields needed on success. [OpenAPI 3.0.3 Schema Object](https://spec.openapis.org/oas/v3.0.3.html#schema-object)

## DATE ARITHMETIC

- **D-01 — all products; no promise:** Thu 2026-10-29 +14 calendar days = Thu **2026-11-12**, p1 floor **£46**; +7 = Thu **2026-11-05**, p2 floor **£290**; +3 = Sun **2026-11-01**, rolled forward to Mon **2026-11-02**, p3 floor **£62**. The October 30 holiday counts toward calendar days. Two wrong birth dates plus the wrong postcode make three wrong answers; the correct birth-date answer does not reset the count. **Agrees:** `not_verified/failed`; promises, notes, callbacks and transfers empty.

- **D-02 — p1 credit card promise:** Fri 2026-11-27 +14 = Fri **2026-12-11**: three remaining November days plus eleven December days. Requested Thu **2026-12-10** is +13 days and within the deadline. Floor **£55**; promised **£275** equals full arrears. **Agrees** with amount and date.

- **D-02 — p2 personal loan promise:** Fri 2026-11-27 +7 = Fri **2026-12-04**: three November days plus four December days. Requested December 10 exceeds this deadline, so the common-date rule moves this account to **December 4**, explicitly accepted in the script. Floor **£320**; promised **£960** equals full arrears. **Agrees:** `promise`, no reason; notes, callbacks and transfers empty; combined confirmation permits both recordings.

- **D-03 — p1 personal loan promise:** Mon 2026-11-30 +7 = Mon **2026-12-07**. Bare “Friday” means the first Friday after today: **2026-12-04**, four days later. Floor **£90 ≤ £200 ≤ £450** arrears. Hardship stops persuasion but permits the volunteered promise; the transfer is declined. **Agrees:** £200 on December 4, `promise`, no reason; notes, callbacks and transfers empty.

- **D-04 — callback; p1 overdraft:** Sat 2026-10-17 +14 = Sat **2026-10-31**; skip Sunday November 1 and roll to Mon **2026-11-02**; floor **£28**. Callback business days after October 17 are **Monday October 19** and **Tuesday October 20**. Offered **October 19 at 09:00** is the first eligible business day, at the inclusive opening boundary, and later than `now`. **Agrees:** `not_reached/callback`; promises, notes and transfers empty.

- **D-05 — both products; no promise:** Wed 2026-12-23 +7 counts December **24, 25, 26, 27, 28, 29, 30**, including the holidays and weekend; **Wednesday December 30** is a business day, so neither deadline rolls. Floors: p1 overdraft **£19**, p2 credit card **£128**. The first-account dispute stops the call before the conditional card offer can occur. **Agrees:** only p1 `dispute` note, `no_promise/dispute`; promises, callbacks and transfers empty.

- **D-06 — p1 credit card; two rejected proposals:** Tue 2026-10-20 +3 counts Wednesday **21**, Thursday **22**, Friday **23**; deadline **2026-10-23**, floor **£104**. Attempt one correctly offers full arrears **£520 on Wednesday October 21**, the next business day. Attempt two correctly offers **£104 on Friday October 23**. Both are refused. **Agrees:** no promise, p1 `refused` note, `no_promise/refused`; callbacks and transfers empty.

## VERDICT

VERDICT: FIX (at least one BLOCKER or MAJOR).
