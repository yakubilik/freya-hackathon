# Decisions

1. Angry caller: 9 Oct recap (Selin's correction) says three calming replies, superseding the "two" in Deniz's list; matches 8 Oct analysis 8.3. Three used (prompt rule).
2. Out-of-scope questions: 9 Oct recap (newest, "build to these") asks "Size bu konuda yardımcı olamıyorum. Sizi ana menüye aktarmamı ister misiniz?" and resumes the flow on no, replacing the 8 Oct analysis 8.4 direct transfer. Implemented as global node g_oos.
3. Card number: 9 Oct recap says production returns the full number; only the last four digits are ever spoken. Card matching code supports last four, last six and full number (analysis 3.2 steps a-c).
4. Request body shape: contract section 3 wraps fields in {"data": {...}, "call": {...}}. The mock answers the same paths with flat bodies (checked with curl, contract 6: only data fields decide the answer). All fields are baked from variables; flat bodies used so no field can be lost in a nested object. Path prefix /voice/v1/ kept as in the contract.
5. Statement PDF currencyType: contract allows TL/USD/EUR/GBP, analysis says "the statement PDF" without currency; TL is sent.
6. contact.email.get failure: analysis 6 sends e-mail service failures to an agent; since it is called before the offer (analysis 5.2), a failure only removes the e-mail option instead of dropping the debt reading; pdf.send failures go to an agent.
7. Another person's card: analysis 8.6 (back to IVR login) vs example scenario 5 (security sentence, main menu). The example scenario's ending is used.
8. Due-date sentence suffix ('dir) dropped to keep fixed sentences grammatical for any date.
9. Same name and same last four (analysis 3.2, Mert's note): in the test data the middle digits are masked, so the last six cannot tell two cards apart; the code then asks for the full number and matches it on the visible first six and last four. With full numbers in production (9 Oct recap) the last-six step matches directly.
10. Tries (analysis 8.1): only answers that match no card count as a failed try; the disambiguation steps (name -> last four -> last six -> full number) do not.
11. Card list 404 FB_IVR_CHANNEL_102 is the "no eligible card" main-menu ending, a 500 goes to an agent (contract 4, analysis 2).

## Review (out/review.md) — final pass
- R1 rejected: the mock answers flat bodies (curl, all ops; contract 6 says only data fields decide); flat leaves avoid lost nested fields. See decision 4.
- R4 accepted: week_change success now needs exitState OK and returnCode "1"; pdf_send needs DONE and returnCode "1" (contract 3, 5.5, 5.7).
- R19 accepted: statementDay sent as integer in week_decide and week_change (contract 5.4-5.5); re-checked with curl.
- R3 rejected for the test build: contract says test services ignore authentication; no token service on the mock.
- R9 rejected: kept example scenario 5 ending (decision 7).
- R17 partially rejected: g_oos follows the 9 Oct recap (decision 2).
- R2, R5-R8, R10-R16, R18, R20-R22: not changed in this pass for lack of time (9-minute budget); they were not disproved and remain open.
