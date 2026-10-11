# Freya Build the Builder

A builder for the Freya x YC "Build the Builder" hackathon (10-11 October 2026). It reads a bank's brief, or a folder
of the bank's documents, and creates a phone agent on Freya with no manual step. Solo entry by Yakup Keskin.

## Final submission

| | |
|---|---|
| Agent | `submission/final.workflow.json`: agent `ee825e04`, version 18, built by commit `7026c42` |
| Trace | `traces/final.log`, plus the builder's Claude session logs and self-test results in `runs/20261011-183322-final-case-joined/` |
| Run | `python3 builder/build.py final/final-case https://freya-statement-mock.yakuupkeskin.workers.dev` |
| Mock | `mock/statement/`, a Cloudflare Worker that serves the case's test customers |
| Our test | 6/6, 5/6 and 6/6 on the case's six example scenarios, in simulations after the run |

## How it works

1. **Main path** (built for the announced brief form): an LLM reads the brief into a rule table, Claude and a second
   model family read it independently and are reconciled, and a deterministic engine and emitter compile the table
   into a workflow for the brief's OpenAPI tool file.
2. **Floor** (fallback): when the main path cannot run, a Claude coding-agent session reads the whole case folder,
   writes the workflow with its tools on the given mock, and saves it.
3. **Self-test and review**: the floor tests its own agent with platform simulations of callers it writes from the
   case folder, fixes what fails, then a second model family (Codex) reviews the workflow against the documents and
   Claude applies the findings it can verify. Every model call and test is in the trace.

## What changed after the final case opened, and why

We built for the final that was announced: one Markdown brief with an OpenAPI tool file, the same seven tools, debt
collection, English. The final came as a folder of documents with a prose contract, different services, another
domain and Turkish. Our main path needs the OpenAPI file, so the builder stopped without an agent. We changed code
only to adapt the input path; nothing from the case is in the builder.

- `f8d84ad`: no OpenAPI file -> go to the floor, which now reads the case folder (not the practice kit).
- `f113646`: the floor keeps our two model families (Claude builds, Codex reviews) and tests its own agent with
  simulations, as the kit's example builder did.
- `5b738d3`, `7026c42`: wording; up to 6 self-test simulations; no example values in fields the model fills.
- `9f2c42a`, `76d5dbb`: after the submitted run (reviewer model setting; wait for a free simulation slot).

This cost accuracy: the case ran on the fallback instead of our engine, each run's first agent hit a platform trap
that only its self-tests caught, and results vary between runs. Known weak spots of the submitted agent: cards that
share a name and last four digits, and a failing e-mail lookup.

## Run it

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
# .env: FREYA_API_KEY, FREYA_WORKSPACE_ID, FREYA_API_URL, FREYA_BANK_TEAM_KEY
# Claude: `claude login` or ANTHROPIC_API_KEY. Optional second family: the `codex` CLI or OPENAI_API_KEY.
python3 builder/build.py <case_folder> <mock_url> 2>&1 | tee traces/final.log
python3 builder/build.py <brief.md> <api.json>                  # the practice form: a brief and its tool file
```

A run takes 15-30 minutes (a 30-minute budget is enforced). Without the Freya keys it stops at once; `--no-deploy`
runs offline. Without a second model family the review step is skipped and the trace says so.

Tests: `.venv/bin/python -m pytest -q tests` (no platform calls).

## Repository

- `builder/`: `build.py` (stages and trace), `readers/` (brief to rule table), `engine/` and `emitter/` (rule table to
  workflow), `floor/` (the case-folder fallback: runner and skill).
- `mock/statement/`: the final's bank mock (Cloudflare Worker); `bank/`, `mock/worker/`: the practice bank mock.
- `final/final-case/`: the final case as published. `kit/`: the organisers' kit. `tests/`: unit and integration tests.
- `spec/interfaces.md`: contracts between the parts.

## Reference: builder options

- `<brief-dir-or-brief.md>`: a brief file, or a directory of brief material joined in file-name order.
- `<case_folder> <mock_url>`: the final's form. An OpenAPI contract in the folder goes to the main path with its server
  on the mock; a prose contract goes to the floor (trigger T0). Text documents are joined into
  `<case_folder>.joined.md`; images and binaries are listed in the trace.
- `--slot`: the workflow slot; a rerun updates the same Freya workflow in place (`builder/.freya-agents.json`).
- Output: the workflow on Freya, its export in `submission/`, the trace `runs/<run_id>/trace.log` (also on stdout),
  `trace.jsonl` and `manifest.json`. Keys are never written to the trace.
- Environment: `BUILDER_MODEL` (Claude model, default `claude-opus-5-5`), `R4_MODEL` (second family's model, default
  `gpt-6-astra`).
