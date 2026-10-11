---
name: build-case-agent
description: Build a Freya phone agent from a case folder (brief, documents, a service contract in any form) with its tools on a given mock base URL, save it and test it with a few bounded simulations. Use when asked to build a phone agent from a case folder.
---

# Build a phone agent from a case folder

You work in a scratch folder. It holds:

- `case/`: the case folder, a copy. Everything you need to know about the bank, the call and the tools is in here.
- `kit/`: the platform's documentation and helpers. Read-only reference: `kit/docs/workflow-format.md`,
  `kit/docs/tools-and-code.md`, `kit/docs/api.md`, `kit/examples/base-agent.json`.
- `run.json`: the mock base URL, the slot, the deadline.
- `left.py`, `save.py`, `sim.py`, `chat.py`: helpers (below). `out/`: where you write the workflow.

Use only what the case folder says. Do not copy rules from another brief, from the kit's examples or from memory.

## Time

The run has a hard deadline. `python3 left.py` prints the seconds left. Check it between steps. Save a first complete
workflow early (by the time half the budget is gone) and improve it after; never be without a saved workflow when
fewer than 5 minutes are left. When less than 3 minutes are left, stop changing things and finish.

Use the budget. Finishing early is not a goal: after the first save, improve the structure while time remains. Move
flow and rules out of long prompts into steps, routes on tool results and code, check the changed tools again, and
save again after each improvement that passes the dry run.

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
8. Test the saved agent with one simulation (below, "Simulations"), read the result, fix `out/workflow.json`, save
   again and, if time allows, simulate again.
9. Optional, only with time left after the simulations: a few single chat turns (at most five) with
   `python3 chat.py --vars '{...}' '<what the caller says>'`, then `--call <call_id> '<next turn>'` and
   `--end <call_id>`. Chat turns can time out on the platform; a timed-out turn proves nothing either way.
10. Finish with one line: the `workflow_id`, the `agent_id`, and what you checked (tools on the mock, dry run, each
    simulation with passed/total).

## Tool requests

- Write each tool's request body directly in the tool definition, with the platform's variable syntax
  (`kit/docs/tools-and-code.md`). Do not add hooks or code that rewrite request bodies unless a simulation shows the
  rewritten request arrives as the contract wants it.
- Declare every field the model fills as a leaf directly under `body.properties` (`kit/docs/tools-and-code.md`).
  A field the model fills inside a nested object of the body can arrive empty: the nested object goes out without
  it. When the contract wants a nested shape, fill the nested parts from workflow variables with `{{...}}` defaults,
  or check what the service accepts with curl, and confirm the shape in a simulation.
- In every simulation result, check every tool request body: each one must carry the fields the contract requires,
  with values (not empty, not a placeholder). An empty or partial body is a defect even when the call went on.
- Node prompts are instructions to the agent, never lines to say. In the simulation transcript the agent must not
  read its rules or its plan aloud.

## Simulations

`python3 sim.py callers.json` runs ONE simulation of the saved agent with the simulated callers in `callers.json`, waits
for it and prints, per caller, pass or fail, the judge's reason, every tool request with its body and its result, and
how the call ended. The raw result is in `out/sim-<n>.json`.

`callers.json` is a list of 3 to 6 callers you write from the case folder itself:

```json
[{"name": "short unique name", "prompt": "who the caller is, what they want, what they know and how they talk, in the language of the calls",
  "variables": {"<call variable>": "<value>"}, "success_criteria": "what must be true at the end of the call"}]
```

- Take them from the folder: its example conversations or scenarios if it has them, else its test customers or sample
  records and the brief. The variables are the call variables the brief says are passed in, with values from those
  records (the mock must know them). Never invent rules that are not in the folder.
- Cover the main path, at least one unusual case, and one caller who says no or tries to misuse the agent.
- Keep the names stable between runs: the same name with the same text is reused, not created again.
- Read every failure and every tool request body; fix the workflow, save, and run again if time allows.
- At most 3 simulations in the run, one at a time. Start one only when `python3 left.py` shows enough for it to finish
  and a save after it (about 4 minutes for the simulation plus 1 for the save; sim.py refuses otherwise). A simulation
  that fails or does not finish leaves the saved workflow as it was.


## When the documents disagree

Documents can contradict each other. The newest decision or an explicit amendment wins over the older text. Write
each such choice in `out/decisions.md` (which documents, what you chose, why) and mention it in your last line.

## When out/review.md exists

A reviewer from another model family read the case documents and the saved `out/workflow.json` and listed defects in
`out/review.md`. The reviewer can be wrong. For each finding, most harmful first:

1. Check it against the documents yourself (and against the mock with curl for tool findings).
2. If it holds, change `out/workflow.json`; if it does not, leave the workflow alone.
3. Record it in `out/decisions.md`: the finding's number, accepted or rejected, and why (which document says so).

Save with `python3 save.py out/workflow.json` after each group of changes; if `python3 left.py` still shows enough
time, one more simulation (`python3 sim.py callers.json`, same callers) checks the changes; a rejected dry run leaves the last saved
workflow in place, so fix and save again. Re-check with curl every tool you changed. Keep watching `python3 left.py`
and stop when less than 3 minutes are left: the last saved workflow is the one that counts. Finish with one line: the
`workflow_id`, how many findings you accepted and rejected.

## Rules

- Write your own messages (progress notes, the final summary) in plain, neutral English: they go into the build
  trace that reviewers read. The agent's own lines are in the call's language.

- Never edit the agent on the platform by hand. Change the file and save it.
- When a tool call fails, the agent must say so. It must never tell the caller something is recorded or done when the
  tool did not confirm it.
- A caller that is handled right once can be handled wrong the next time. Prefer rules in routes and code over rules
  in prompts.
- Do not read or print key values (`.env`, environment variables with KEY, TOKEN or SECRET in the name).
