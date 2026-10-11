# Review of out/workflow.json (codex, gpt-6-astra)

1. **All seven API requests omit the required envelope.** Their `body.properties` puts service fields at the root; the contract requires `{"data": {...}, "call": {...}}`. **Where:** `load_cards`, `get_balance`, `get_email`, `week_get`, `week_decide`, `week_change`, `pdf_send`. **Source:** `2026-10-01-service-contract.md`, §§3, 5.

2. **Transfers only hang up.** Every terminal uses `__function__:end_call` with a spoken message, without a routing destination or IVR agent flag. Saying “aktarıyorum” does not implement a transfer. **Where:** all `end_*` nodes intended for menu/agent routing. **Source:** `2026-10-08-statement-debt-analysis.md`, §10.

3. **Authentication is missing.** Requests have no bearer header, token acquisition/cache, or refresh-and-retry branch for HTTP 401. Test services ignore authentication, but the contract explicitly still requires the headers. **Where:** all API tools. **Source:** `2026-10-01-service-contract.md`, §§2, 4.

4. **Success checks can announce an unconfirmed transaction.** `week_change` checks only `exitState == "OK"`, omitting `responseCode == 0`, successful `returnCode`, and HTTP 200. `pdf_send` similarly checks only `"DONE"`; other service branches also omit HTTP validation, and `week_decide` ignores `responseCode`. **Source:** `2026-10-01-service-contract.md`, §§3, 5.4–5.5, 5.7.

5. **Cut-day and overdue readings use the wrong amounts.** `build_reading` adds the special date announcement but still reads `statementDebt` and minimum-payment figures instead of per-currency `totalDebt`. Its statement-debt filtering can also omit currencies with only new spending. **Source:** `2026-10-08-statement-debt-analysis.md`, §4.10; `2026-10-10-follow-up-session-transcript.txt`, 00:08:34–00:09:06.

6. **An email lookup failure is treated as “no registered email.”** `get_email` always continues; `build_reading` turns a non-success `em_rc` into `has_email = "no"` and offers a week change. This can falsely tell the caller no address exists instead of transferring on failure. **Source:** `2026-10-08-statement-debt-analysis.md`, §§6, 8.3; `test-customers.json`, customer `92335586`.

7. **Masked-card matching fabricates the last six digits.** `resolve_card` strips asterisks, turning `540000******4253` into `5400004253`, then compares its last six (`004253`). Those include prefix digits, not the actual last six; legitimate answers fail or match incorrectly. **Source:** `2026-10-01-service-contract.md`, §5.1; `2026-10-09-decisions-recap.txt`, point 4 and production-masking correction.

8. **A single supplementary card bypasses eligibility checks.** `prep_cards` automatically selects any single card and fetches its balance; `isMainCard` is checked only in `resolve_card`. **Source:** `2026-10-08-statement-debt-analysis.md`, §3.3, “Supplementary card only.”

9. **Third-party callers get the wrong destination.** `end_security` announces the main menu instead of the IVR login step. This follows the simplified main-menu outcome in example 5 rather than the explicit security routing requirement. **Source:** `2026-10-08-statement-debt-analysis.md`, §§8.6, 10; `2026-09-24-kickoff-questions.txt`, Q8; `example-scenarios.md`, example 5.

10. **Three-silence handling is absent.** There is no silence counter, two short reprompts, or terminal with the required silence-disconnect sentence. **Where:** conversation nodes and `global_nodes`. **Source:** `2026-10-08-statement-debt-analysis.md`, §8.2; `2026-10-09-decisions-recap.txt`, point 1.

11. **Retry limits count turns rather than three failed answers per question.** Conversation limits range from four to eight turns; `select_tries` counts only unmatched nonempty card hints. “All cards,” refusals and unclear replies do not consistently consume tries, while repeat requests have no exemption from turn limits. **Source:** `2026-10-08-statement-debt-analysis.md`, §§3.3, 8.1; `2026-10-09-decisions-recap.txt`, point 3.

12. **Persistent anger never triggers the required escalation.** The system prompt asks for politeness, but there is no counter or route after three calming replies. **Where:** `system_prompt`, `global_nodes`. **Source:** `2026-10-09-decisions-recap.txt`, Selin’s correction; `2026-10-08-statement-debt-analysis.md`, §8.3.

13. **No-statement-debt callers receive an unauthorized follow-up offer.** `build_reading` always appends an offer for a single card; `after_reading` also offers actions after declining another card. This branch should return to the main menu. It additionally omits the required total when `totalDebt` is exactly zero. **Source:** `2026-10-08-statement-debt-analysis.md`, §4.7; `2026-10-10-follow-up-session-transcript.txt`, 00:04:49–00:04:57.

14. **New cards omit the available first statement date.** The `not st` branch in `build_reading` says no statement exists but ignores `b_nextStatementDate`, although it is fetched. **Source:** `2026-10-10-follow-up-session-transcript.txt`, 00:06:51–00:07:20.

15. **Transferred foreign debt can go unannounced.** `build_reading` announces `transferAmount > 0` only when that currency remains in `has`. A currency fully transferred into Turkish Lira can have no remaining foreign debt and be skipped. **Source:** `2026-10-08-statement-debt-analysis.md`, §4.4.

16. **Arrival requests are not carried into the flow.** `prep_cards` clears `card_hint`; there is no initial route for an already named card, “just the due date,” or debt-plus-email. The full reading and offer are generated before these preferences are handled. **Source:** `2026-10-08-statement-debt-analysis.md`, §§3.1, 8.5.

17. **Out-of-scope handling is missing during card selection and prompt-only after reading.** `g_oos` excludes `select_card`, whose prompt has no such branch. In `after_reading`, a long prompt carries the menu-confirmation subflow without its own state or retry counter. **Source:** `2026-10-09-decisions-recap.txt`, point 2, which supersedes the direct-transfer rule in the October analysis.

18. **The “another card?” question never exhausts the cards.** `multi` remains true throughout the call; no read-card set is maintained, so `build_reading` keeps asking even after every eligible card has been read. **Source:** `2026-10-08-statement-debt-analysis.md`, §5.1; `2026-10-10-follow-up-session-transcript.txt`, 00:04:13–00:04:44.

19. **Week requests send the current day as a string.** `week_decide.body.statementDay` and `week_change.body.statementDay` declare `"type": "string"`; the contract specifies numeric current-day values. String-or-number acceptance is explicitly granted only to `newStatementWeek`. **Source:** `2026-10-01-service-contract.md`, §§5.3–5.5.

20. **The current-week explanation skips required information and a choice.** `week_prep` moves directly to choosing a new week instead of asking whether to proceed after reading current dates. For joint statements it names the selected card without its last four digits, although both cards must be identified that way. **Source:** `2026-10-08-statement-debt-analysis.md`, §7, step 2.

21. **Email edge branches are incomplete.** `end_email_sent` immediately terminates, leaving no resend path or three-send counter. Paper requests are redirected toward email rather than explained and returned to the menu; `email_confirm` also reads every address verbatim without shortening long or messy addresses. **Source:** `2026-10-08-statement-debt-analysis.md`, §6.

22. **Slow services leave the caller in silence.** All API nodes enter silently, disable inactivity monitoring, and provide no waiting announcement during their 20-second timeout. **Source:** `2026-10-08-statement-debt-analysis.md`, §8.3, requires “Bilgilerinizi kontrol ediyorum.”
