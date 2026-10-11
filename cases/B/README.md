# Case B: Brief B (the public follow-up brief), in the final's shape

Test material for `python3 builder/build.py cases/B <mock_url>`. Brief B builds on brief A, so both texts are in this
folder and it stands alone. Copied from the kit; the originals stay in place.

- `BRIEF.md`: the bank's brief, brief B, the changes and additions on top of brief A
  (`kit/build-the-builder/briefs/brief-b.md`). Read it first.
- `documents/brief-a.md`: brief A, the background brief B refers to (`kit/build-the-builder/briefs/brief-a.md`).
  Where the two disagree, `BRIEF.md` wins.
- `contract/openapi.json`: the service contract, the OpenAPI document of the seven tools
  (`kit/build-the-builder/tools/openapi.json`). Its server is replaced by the mock URL at build time.
- `test-customers.json`: the test customers of this brief, the 3 public cases of brief B from
  `kit/build-the-builder/public-test-set.json`. The mock is built from it with
  `python3 mock/make_customers.py cases/B/test-customers.json`.
