# Case A: Brief A (the public practice brief), in the final's shape

Test material for `python3 builder/build.py cases/A <mock_url>`. Copied from the kit; the originals stay in place.

- `BRIEF.md`: the bank's brief, the text the agent is built from (`kit/build-the-builder/briefs/brief-a.md`).
- `contract/openapi.json`: the service contract, the OpenAPI document of the seven tools the agent calls
  (`kit/build-the-builder/tools/openapi.json`). Its server is replaced by the mock URL at build time.
- `test-customers.json`: the test customers of this brief, the 10 public cases of brief A from
  `kit/build-the-builder/public-test-set.json` (id, variables, identity, products, script, expected). The mock is built
  from it with `python3 mock/make_customers.py cases/A/test-customers.json`.
