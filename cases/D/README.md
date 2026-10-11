# Case D: Marlowe & Finch Bank (synthetic brief D), in the final's shape

Test material for `python3 builder/build.py cases/D <mock_url>`. Copied from `synthetic/D/`; the originals stay in
place. The answer key (`synthetic/D/README.md`, derived dates and expected outcomes) is deliberately not in this
folder: it is not brief text.

- `BRIEF.md`: the bank's brief, prose sections with no rule numbers; every sentence that says what the caller does is
  a rule (`synthetic/D/brief.md`).
- `contract/openapi.json`: the service contract, the OpenAPI document of the tools with this brief's names and fields
  (`synthetic/D/api.json`). Its server is replaced by the mock URL at build time.
- `test-customers.json`: the 30 test customers of this brief (`synthetic/D/cases.json`: id, variables, identity,
  products, script, expected). The mock is built from it with `python3 mock/make_customers.py cases/D/test-customers.json`.
