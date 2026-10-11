# Freya Build the Builder

The builder reads a bank's brief and its tool API file and creates a phone agent on Freya, with no manual step:

    .venv/bin/python builder/build.py <brief-dir-or-brief.md> <api.json> --slot <brief-name> --out-dir runs/<brief-name>

- `<brief-dir-or-brief.md>`: a single brief file, or a directory whose `.md`/`.txt` files are the brief material (a mail,
  a policy extract, a memo, a code list: they are joined in file-name order into `<dir>.joined.md` next to the directory).
- `<api.json>`: the tool API file that comes with the brief.
- The final's form: `python3 builder/build.py <case_folder> <mock_url> 2>&1 | tee traces/final.log`. The case folder
  holds `BRIEF.md`, `README.md`, the documents and the service contract (subfolders are read too); `<mock_url>` is the
  base URL of our mock of the bank. The contract is found in the folder (a `.json`/`.yaml`/`.yml` OpenAPI document;
  YAML through PyYAML or, without it, macOS's Ruby) and copied as `<case_folder>.contract.json` with its server on the
  mock (a mock URL without a path gets the contract's server path, e.g. `/v1`), so every tool of the exported workflow
  calls the mock and nothing else. No machine-readable contract (a prose contract): the run goes to the floor (trigger
  T0, below), which reads the whole folder and builds the tools from the prose contract on the mock. The brief is
  `BRIEF.md`, then `README.md`, then the other text documents (`.md`, `.txt`, `.json`, `.csv`, ...) by path, joined
  into `<case_folder>.joined.md`; images and binaries are listed in the trace and not read.
- Every trace line also goes to stdout; paths in the trace and the manifest are repository-relative and key values are
  masked.
- `--slot`: the workflow slot. One slot per brief: a rerun updates the same Freya workflow in place (state in
  `builder/.freya-agents.json`). Without it the slot is `<brief-slug>-final`.
- Output: the published workflow on Freya, its export `submission/<brief-slug>.workflow.json`
  (`freya.export_workflow`, the file the judges score), the plain-text trace `runs/<brief-name>/trace.log`
  (start and end time, every model call with model and purpose, what was created on Freya, the tests run), plus
  `trace.jsonl` and `manifest.json`. `--deploy-variant test` exports to `submission-test/` instead.
- Stages: read (an LLM turns the brief into a rule table), emit (a deterministic engine and workflow emitter),
  static walk, local self-test on a mock bank, deploy, platform self-test on the public cases when the brief is a public
  one. A run takes 15-20 minutes; the 30-minute budget is enforced per stage.

## Final submission

- Agent: `submission/final.workflow.json` (agent `ee825e04`, version 18), built by commit `7026c42`.
- Trace: `traces/final.log`. The builder's Claude session logs and its self-test results are in
  `runs/20261011-183322-final-case-joined/`.
- Run: `python3 builder/build.py final/final-case https://freya-statement-mock.yakuupkeskin.workers.dev`
- Mock: `mock/statement/`, a Cloudflare Worker that serves the case's test customers.
- Result: passed 6/6, 5/6 and 6/6 of the case's six example scenarios in independent simulations after the run.

### What changed after the case opened, and why

We built for the final that was announced: one Markdown brief with an OpenAPI tool file, the same seven tools, debt
collection, English. The final came as a folder of documents with a prose contract, different services, another
domain and Turkish. Our main path needs the OpenAPI file, so the builder stopped without an agent. We changed code
only to adapt the input path; nothing from the case is in the builder.

- `f8d84ad`: no OpenAPI file -> fall back to the floor, which now reads the case folder (not the practice kit).
- `f113646`: the floor keeps our two model families (Claude builds, Codex reviews) and tests its own agent with
  simulations, as the kit's example builder did.
- `5b738d3`, `7026c42`: wording; up to 6 self-test simulations; no example values in fields the model fills.
- `9f2c42a`, `76d5dbb`: after the submitted run (reviewer model setting; wait for a free simulation slot).

This cost accuracy: the case ran on the fallback instead of our engine, each run's first agent hit a platform trap
that only its self-tests caught, and results vary between runs. Known weak spots of the submitted agent: cards that
share a name and last four digits, and a failing e-mail lookup.

Setup: `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`, then put the keys in `.env`
(`FREYA_API_KEY`, `FREYA_WORKSPACE_ID`, `FREYA_API_URL`, `FREYA_BANK_TEAM_KEY`; optional `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OWN_BANK_URL`).
A run without `FREYA_API_KEY` and `FREYA_WORKSPACE_ID` stops at once with exit code 1 (only `--no-deploy` runs offline).
The reader calls Claude through the `claude` CLI (`claude login`, or `ANTHROPIC_API_KEY` in `.env`); without either the
build falls back to the kit's example builder.

Tests: `.venv/bin/python -m pytest -q tests` (engine, emitter, readers, mock bank; no platform) and
`.venv/bin/python tools/offline_gate.py` (every frozen rule table through the emitter and the static walk).

Contracts between the parts are in `spec/interfaces.md`.
