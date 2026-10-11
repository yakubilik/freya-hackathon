# Case I: Tamsin Finance (synthetic brief I), in the final's shape

Test material for `python3 builder/build.py cases/I <mock_url>`. This is the raw-material brief: a cover mail and
three separate documents, like the final's zip. Copied from `synthetic/I/`; the originals stay in place
(`synthetic/I/brief.md` is the same material already joined). The answer key (`synthetic/I/README.md`) is deliberately
not in this folder.

- `BRIEF.md`: the mail from the payments team lead that introduces the material, removes the recording notice,
  defines a bare weekday, repeats the vague-period rule and lists the holidays (`synthetic/I/mail.md`). Read it first.
- `documents/procedure.md`: the Past-Due Contact Procedure, revision 7, numbered sections; the rules of the call
  (`synthetic/I/policy.md`).
- `documents/change-notice.md`: change notice PT-26-09, the amendments to revision 7 that apply from October 5, 2026
  (`synthetic/I/memo.md`). Where it disagrees with the procedure, the change notice wins.
- `documents/code-sheet.md`: the ledger code sheet, the allowed outcome, reason, note, queue and product values
  (`synthetic/I/codes.md`).
- `contract/openapi.json`: the service contract, the OpenAPI document of the tools (`synthetic/I/api.json`). Its
  server is replaced by the mock URL at build time.
- `test-customers.json`: the 30 test customers of this brief (`synthetic/I/cases.json`). The mock is built from it with
  `python3 mock/make_customers.py cases/I/test-customers.json`.
