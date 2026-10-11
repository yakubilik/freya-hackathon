"""The case-folder floor: Claude reads a case folder, builds the phone agent with its tools on the mock, checks it
without simulations and saves it into one slot.

    python3 builder/floor/runner.py <case_folder> <mock_url> --run-dir runs/<run_id> --slot NAME --state-file PATH
                                    [--budget SECONDS]

Modelled on the kit's examples/agent_builder.py (Claude Agent SDK, tools Read/Write/Edit/Glob/Grep/Bash, permission
mode dontAsk), with our own skill (SKILL.md next to this file) instead of the kit's, which reads the kit's practice API
and tests on the kit's practice customers. The run happens in <run_dir>/floor-work: a copy of the case folder, a copy
of the kit's docs, base agent and freya.py, and three helpers (left.py, save.py, chat.py). save.py saves through
freya.save_workflow(<slot>, wf, state_file=<state_file>), so the caller finds the ids under the slot in that file.
Every message is written to <run_dir>/floor-session.jsonl. Needs FREYA_API_KEY and a Claude login or ANTHROPIC_API_KEY.
"""
import argparse
import asyncio
import dataclasses
import json
import os
import pathlib
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KIT = ROOT / "kit" / "build-the-builder"
KIT_FILES = ("docs/workflow-format.md", "docs/tools-and-code.md", "docs/api.md", "examples/base-agent.json", "freya.py")
SKILL = "build-case-agent"
FINISH_MARGIN_S = 30       # the session is cut this long before the budget so the caller can still export

LEFT_PY = '''import json, time
print(max(0, int(json.load(open("run.json"))["deadline_epoch"] - time.time())))
'''

SAVE_PY = '''"""python3 save.py out/workflow.json: dry run on the platform, then save into this run's slot."""
import json, sys
sys.path.insert(0, "kit")
import freya
run = json.load(open("run.json"))
wf = json.load(open(sys.argv[1]))
try:
    freya.validate_workflow(run["slot"] + " dry run", wf)
except Exception as e:
    sys.exit("dry run rejected the workflow: %s" % str(e)[:3000])
print(json.dumps(freya.save_workflow(run["slot"], wf, state_file=run["state_file"])))
'''

CHAT_PY = '''"""One chat turn against the saved workflow, no simulation:
    python3 chat.py --vars '{"name": "value"}' 'first thing the caller says'
    python3 chat.py --call <call_id> 'next thing the caller says'
    python3 chat.py --end <call_id>"""
import argparse, json, sys
sys.path.insert(0, "kit")
import freya
ap = argparse.ArgumentParser()
ap.add_argument("message", nargs="?")
ap.add_argument("--vars", default="{}")
ap.add_argument("--call")
ap.add_argument("--end")
a = ap.parse_args()
run = json.load(open("run.json"))
if a.end:
    print(json.dumps(freya.api("POST", "/api/v2/chat/end", {"callId": a.end}))[:2000]); sys.exit()
state = json.load(open(run["state_file"])).get(run["slot"])
if not state:
    sys.exit("nothing saved yet: run save.py first")
body = {"workflowId": state["workflow_id"], "message": a.message or ""}
if a.call:
    body["callId"] = a.call
else:
    body["customerVariables"] = json.loads(a.vars)
r = freya.api("POST", "/api/v2/chat/message", body)
print(json.dumps({"callId": r.get("callId"), "response": r.get("response")}, ensure_ascii=False))
'''


def prepare_workdir(work, case_dir, mock_url, slot, state_file, deadline_epoch):
    """The scratch folder the session runs in: the case copy, the kit's reference files, the skill and the helpers."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(case_dir, work / "case", ignore=shutil.ignore_patterns(".*", "__MACOSX"))
    for f in KIT_FILES:
        (work / "kit" / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(KIT / f, work / "kit" / f)
    skill = work / ".claude" / "skills" / SKILL
    skill.mkdir(parents=True)
    shutil.copy2(HERE / "SKILL.md", skill / "SKILL.md")
    (work / "out").mkdir()
    (work / "run.json").write_text(json.dumps({"mock_url": mock_url, "slot": slot, "state_file": str(state_file),
                                               "deadline_epoch": deadline_epoch}, indent=1))
    for name, text in (("left.py", LEFT_PY), ("save.py", SAVE_PY), ("chat.py", CHAT_PY)):
        (work / name).write_text(text)


def prompt_for(mock_url, budget_s):
    return ("Use the %s skill to build a phone agent from the case folder in ./case. The tools call the mock base URL "
            "%s and no other host. You have %d minutes in total (python3 left.py prints the seconds left); save a "
            "complete workflow well before the end." % (SKILL, mock_url, budget_s // 60))


async def session(work, log_path, mock_url, budget_s, model):
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query

    venv_bin = str(pathlib.Path(sys.executable).parent)
    options = ClaudeAgentOptions(
        cwd=work,
        model=model,
        skills=[SKILL],
        setting_sources=["project"],           # only the scratch folder's settings, not the user's
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        permission_mode="dontAsk",             # anything not listed above is refused
        max_turns=200,
        # no test suite runs here; a single command is a curl, a save or a chat turn
        env={"BASH_DEFAULT_TIMEOUT_MS": "300000", "BASH_MAX_TIMEOUT_MS": "600000", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
             "PATH": venv_bin + os.pathsep + os.environ.get("PATH", "")},
    )
    with log_path.open("w") as out:
        out.write(json.dumps({"start": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "case": "case/", "mock_url": mock_url,
                              "model": model, "budget_s": budget_s}) + "\n")
        async for message in query(prompt=prompt_for(mock_url, budget_s), options=options):
            out.write(json.dumps({"type": type(message).__name__, **dataclasses.asdict(message)}, default=str) + "\n")
            out.flush()
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, flush=True)
                    elif isinstance(block, ToolUseBlock):
                        print(f"  [{block.name}] {str(block.input)[:120]}", flush=True)
            elif isinstance(message, ResultMessage):
                print(f"\ndone: {message.num_turns} turns, {message.duration_ms / 1000:.0f} s, ${message.total_cost_usd or 0:.2f}. Trace: {log_path.name}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case_dir")
    ap.add_argument("mock_url")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--slot", required=True)
    ap.add_argument("--state-file", required=True)
    ap.add_argument("--budget", type=float, default=1500)
    a = ap.parse_args(argv)
    run_dir = pathlib.Path(a.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    budget = max(60.0, a.budget - FINISH_MARGIN_S)
    work = run_dir / "floor-work"
    prepare_workdir(work, pathlib.Path(a.case_dir).resolve(), a.mock_url.rstrip("/"), a.slot,
                    pathlib.Path(a.state_file).resolve(), time.time() + budget)
    log_path = run_dir / "floor-session.jsonl"
    print("session log: %s" % log_path, flush=True)
    try:
        asyncio.run(asyncio.wait_for(session(work, log_path, a.mock_url.rstrip("/"), int(budget),
                                             os.environ.get("BUILDER_MODEL", "claude-opus-5-5")), timeout=budget))
    except asyncio.TimeoutError:
        print("session cut at the budget (%.0f s); whatever was saved stays saved" % budget, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
