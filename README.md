# Freya Build the Builder

The builder reads a bank's brief and its tool API file and creates a phone agent on Freya, with no manual step:

    .venv/bin/python builder/build.py <brief-dir-or-brief.md> <api.json> --slot <brief-name> --out-dir runs/<brief-name>

- `<brief-dir-or-brief.md>`: a single brief file, or a directory whose `.md`/`.txt` files are the brief material (a mail,
  a policy extract, a memo, a code list: they are joined in file-name order into `<dir>.joined.md` next to the directory).
- `<api.json>`: the tool API file that comes with the brief.
- `--slot`: the workflow slot. One slot per brief: a rerun updates the same Freya workflow in place (state in
  `builder/.freya-agents.json`). Without it the slot is `<brief-slug>-final`.
- Output: the published workflow on Freya, its export `submission/<brief-slug>.workflow.json`
  (`freya.export_workflow`, the file the judges score), the plain-text trace `runs/<brief-name>/trace.log`
  (start and end time, every model call with model and purpose, what was created on Freya, the tests run), plus
  `trace.jsonl` and `manifest.json`. `--deploy-variant test` exports to `submission-test/` instead.
- Stages: read (an LLM turns the brief into a rule table), emit (a deterministic engine and workflow emitter),
  static walk, local self-test on a mock bank, deploy, platform self-test on the public cases when the brief is a public
  one. A run takes 15-20 minutes; the 30-minute budget is enforced per stage.

Setup: `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`, then put the keys in `.env`
(`FREYA_API_KEY`, `FREYA_WORKSPACE_ID`, `FREYA_API_URL`, `FREYA_BANK_TEAM_KEY`; optional `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OWN_BANK_URL`).
The reader calls Claude through the `claude` CLI (`claude login`, or `ANTHROPIC_API_KEY` in `.env`); without either the
build falls back to the kit's example builder.

Tests: `.venv/bin/python -m pytest -q tests` (engine, emitter, readers, mock bank; no platform) and
`.venv/bin/python tools/offline_gate.py` (every frozen rule table through the emitter and the static walk).

Contracts between the parts are in `spec/interfaces.md`.
