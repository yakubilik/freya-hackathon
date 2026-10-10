# Freya Build the Builder

`builder/build.py <brief.md> <tools.json>` reads a bank's brief and its tool API file and creates a phone agent on Freya.

Setup: `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`, then put the keys in `.env`
(`FREYA_API_KEY`, `FREYA_WORKSPACE_ID`, `FREYA_API_URL`, `FREYA_BANK_TEAM_KEY`; optional `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OWN_BANK_URL`).

Contracts between the parts are in `spec/interfaces.md`.
