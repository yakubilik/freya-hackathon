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

## The final submission, and what changed after the final case opened

Run: `python3 builder/build.py final/final-case https://freya-statement-mock.yakuupkeskin.workers.dev 2>&1 | tee traces/final.log`
(`final/final-case` is the case folder as published; the mock is `mock/statement/`, a Cloudflare Worker that replays the
case's test customers). Submitted: `submission/final.workflow.json` (the export of that run's agent), `traces/final.log`
(that run's trace) and the run directory `runs/<run_id>/` with the floor's Claude session logs (`floor-session.jsonl`,
`floor-fix-session.jsonl`), the second-family review (`floor-work/out/review.md`) and its own simulation results.

Why the builder changed after the case opened. The kit and the event page described each hidden brief as one Markdown
file with its own OpenAPI tool API file, the seven practice tool names unchanged ("the fields and the allowed values can
change"), debt collection, calls in English. The reader, engine and emitter were built to that description. The final
came as one case folder of documents with a prose service contract, other services, another domain and Turkish calls,
and this builder stopped with "no machine-readable service contract" and produced no agent. The commits after the case
opened adapt the input path only:

- `f8d84ad`: a case folder without a machine-readable contract goes to the floor (T0) instead of failing; the floor
  reads the case folder it is given instead of the practice kit's API and practice customers.
- `f113646`: the floor keeps the builder's two model families (a second-family review of the saved workflow, then a
  Claude fix session, as the reader's R1/R4 always did) and tests its own agent with bounded platform simulations of
  callers it writes from the case folder, as the kit's example builder tested its agents.
- `5b738d3`: wording only (a skill rule and a test fixture made neutral).

Reader, engine and emitter are unchanged. No rule, value, name, path or sentence from the case is in the builder; the
tests of these changes use invented data. `bfae95e` and `c2f22c0` (stop early when the Freya or Claude keys are
missing) are operational checks.

Setup: `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`, then put the keys in `.env`
(`FREYA_API_KEY`, `FREYA_WORKSPACE_ID`, `FREYA_API_URL`, `FREYA_BANK_TEAM_KEY`; optional `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OWN_BANK_URL`).
A run without `FREYA_API_KEY` and `FREYA_WORKSPACE_ID` stops at once with exit code 1 (only `--no-deploy` runs offline).
The reader calls Claude through the `claude` CLI (`claude login`, or `ANTHROPIC_API_KEY` in `.env`); without either the
build falls back to the kit's example builder.

Tests: `.venv/bin/python -m pytest -q tests` (engine, emitter, readers, mock bank; no platform) and
`.venv/bin/python tools/offline_gate.py` (every frozen rule table through the emitter and the static walk).

Contracts between the parts are in `spec/interfaces.md`.
