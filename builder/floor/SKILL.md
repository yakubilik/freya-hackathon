---
name: build-case-agent
description: Build a Freya phone agent from a case folder (brief, documents, a service contract in any form) with its tools on a given mock base URL, check it without simulations and save it. Use when asked to build a phone agent from a case folder.
---

# Build a phone agent from a case folder

You work in a scratch folder. It holds:

- `case/`: the case folder, a copy. Everything you need to know about the bank, the call and the tools is in here.
- `kit/`: the platform's documentation and helpers. Read-only reference: `kit/docs/workflow-format.md`,
  `kit/docs/tools-and-code.md`, `kit/docs/api.md`, `kit/examples/base-agent.json`.
- `run.json`: the mock base URL, the slot, the deadline.
- `left.py`, `save.py`, `chat.py`: helpers (below). `out/`: where you write the workflow.

Use only what the case folder says. Do not copy rules from another brief, from the kit's examples or from memory.

## Time

The run has a hard deadline. `python3 left.py` prints the seconds left. Check it between steps. Save a first complete
workflow early (by the time half the budget is gone) and improve it after; never be without a saved workflow when
fewer than 5 minutes are left. When less than 3 minutes are left, stop changing things and finish.

## Steps

1. Read every document in `case/`: `BRIEF.md` and `README.md` first, then the rest in the order they point to.
   Read PDFs and images too (the Read tool shows them); they can hold rules, flows or tables the text does not.
   Look at data files (JSON, CSV, YAML) for their shape: they can be the service contract, sample records or a list
   of codes.
2. Find the service contract: an OpenAPI/Swagger file, or a prose document (Markdown or PDF) that lists the services,
   their paths, methods, request fields and response shapes in text and tables. Write down every operation: method,
   path, request fields and types, allowed values, response fields, error responses.
3. The tools call the mock base URL in `run.json` and nothing else: the contract's host is replaced by the mock URL,
   the paths stay the same. If the contract's server has a path prefix, check with curl whether the mock serves the
   operation with or without it and use the form that answers. Never put any other host in the workflow.
4. Check each tool against the mock with curl before relying on it: one request per operation with the shape the
   contract gives (`curl -s -X POST "<mock>/<path>" -H 'Content-Type: application/json' -d '{...}'`). Read what comes
   back, including the error shapes, and build the routes on the real response fields. The mock is ours; calling it
   is fine. Use no other network host except the Freya platform through the helpers.
5. Read `kit/docs/workflow-format.md`, `kit/docs/tools-and-code.md` and `kit/examples/base-agent.json`. The example
   is the pattern for the JSON, not the answer.
6. Write the workflow to `out/workflow.json`.
   - The call variables the brief says the platform passes in at the start of the call are workflow variables. The
     agent reads them; it never asks the caller for them.
   - One step per stage of the call. Identity comes first when the brief requires it.
   - Move to the next step on a tool result, not on what the caller says.
   - Take every tool field and allowed value from the contract.
   - The agent speaks the language the brief says the calls are in, in every prompt and every fixed sentence.
   - Leave `agent_config` out.
7. Save it: `python3 save.py out/workflow.json`. It validates the workflow on the platform first (a dry run) and
   prints the errors if any; fix them and save again. On success it prints `workflow_id` and `agent_id`. The same slot
   updates the same workflow in place, so save as often as needed.
8. If time allows (more than 8 minutes left), a handful of single chat turns, at most five in total:
   `python3 chat.py --vars '{...}' '<what the caller says>'` for the first turn (the call variables, invented values of
   the right shape), then `python3 chat.py --call <call_id> '<next turn>'`, and `python3 chat.py --end <call_id>`.
   Use them to see that the workflow starts
   and answers in the right language. Never start simulations and never run test suites.
9. Finish with one line: the `workflow_id`, the `agent_id`, and what you checked (tools on the mock, dry run, turns).

## When the documents disagree

Documents can contradict each other. The newest decision or an explicit amendment wins over the older text. Write
each such choice in `out/decisions.md` (which documents, what you chose, why) and mention it in your last line.

## Rules

- Never edit the agent on the platform by hand. Change the file and save it.
- When a tool call fails, the agent must say so. It must never tell the caller something is recorded or done when the
  tool did not confirm it.
- A caller that is handled right once can be handled wrong the next time. Prefer rules in routes and code over rules
  in prompts.
- Do not read or print key values (`.env`, environment variables with KEY, TOKEN or SECRET in the name).
