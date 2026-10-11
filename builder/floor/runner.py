"""The case-folder floor: Claude reads a case folder, builds the phone agent with its tools on the mock, saves it
into one slot and tests it with a few bounded simulations of its own callers.

    python3 builder/floor/runner.py <case_folder> <mock_url> --run-dir runs/<run_id> --slot NAME --state-file PATH
                                    [--budget SECONDS]

Modelled on the kit's examples/agent_builder.py (Claude Agent SDK, tools Read/Write/Edit/Glob/Grep/Bash, permission
mode dontAsk), with our own skill (SKILL.md next to this file) instead of the kit's, which reads the kit's practice API
and tests on the kit's practice customers. The run happens in <run_dir>/floor-work: a copy of the case folder, a copy
of the kit's docs, base agent and freya.py, and four helpers (left.py, save.py, chat.py, sim.py: one bounded
simulation of the saved agent with callers the session writes, at most SIMS_MAX per run, each line in
<run_dir>/floor-sims.jsonl). save.py saves through
freya.save_workflow(<slot>, wf, state_file=<state_file>), so the caller finds the ids under the slot in that file.
Every message is written to <run_dir>/floor-session.jsonl. Needs FREYA_API_KEY and a Claude login or ANTHROPIC_API_KEY.

When the first session saved a workflow and at least REVIEW_MIN_S are left, a second model family (builder/readers/
models.py: the OpenAI API, else the codex CLI) reviews the saved out/workflow.json against the case folder's documents,
blind to Claude's reasoning, into floor-work/out/review.md; a second Claude session in the same folder verifies the
findings, applies the ones that hold, saves again and records them in out/decisions.md (session log
<run_dir>/floor-fix-session.jsonl). Each step (model, purpose, seconds, outcome, or why it was skipped) goes to
<run_dir>/floor-steps.json for the caller's trace. A failed review or fix leaves the saved workflow as it was.
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
REVIEW_MIN_S = 600         # the review and the fix session run only with this much left after the first session
REVIEW_TIMEOUT_S = 300     # the reviewer's own timeout, well inside the budget
SIMS_MAX = 6               # simulations sim.py runs in one run, over all sessions (each took 0.5-1 min live)
FIX_MIN_S = 180            # the fix session is not started with less than this left after the review
DOC_CHARS_MAX = 300_000    # text of the case documents given to the reviewer
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".xml", ".html", ".htm", ".ini", ".toml"}
REVIEW_PURPOSE = "floor review: second-family audit of the saved workflow against the case documents"
FIX_PURPOSE = "floor fix: apply the verified review findings"
FIRST_PURPOSE = "case floor: read the case folder, build the agent with its tools on the mock, check and save it"

REVIEW_SYSTEM = """You review a phone agent workflow (JSON for a voice-agent platform) against the documents of the case it
was built from. You did not build it. Be concrete and brief. Report defects only, no praise, no rewrite of the workflow."""

REVIEW_PROMPT = """Below are the case documents and the workflow built from them. List the workflow's defects against
the documents, most harmful first. Look for:
- tool requests that do not match the service contract (paths, methods, field names, types, allowed values, envelope);
- call variables the documents say are passed in at the start of the call that the agent asks the caller for instead;
- missing or wrong branches (outcomes of a tool, error responses, caller choices the documents describe);
- rules the documents state that the workflow breaks or misses;
- decisions where the documents disagree, and which way the workflow went;
- fixed sentences not in the language the calls are in;
- honesty: the agent claims something is done or recorded without a tool result confirming it;
- flow carried by one long prompt where routes or code should carry it.
For each finding: a number, what is wrong, where in the workflow (step / tool / field), and which document (file name
and section) says so. Write "No findings." when there are none.

Files of the case folder that are not text (not included): {binaries}

{documents}

=== the saved workflow (out/workflow.json) ===
{workflow}
"""

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

SIM_PY = r'''"""One simulation of the saved agent with the simulated callers you wrote:
    python3 sim.py callers.json
callers.json is a list of {"name", "prompt", "variables": {...}, "success_criteria"}. Callers are kept on the platform by
name (the same name and text reuses the same one). Prints per caller pass/fail, the judge's reason, every tool request
with its body and result, and how the call ended; the raw result goes to out/sim-<n>.json."""
import hashlib, json, os, sys, time
sys.path.insert(0, "kit")
import freya
SIM_S = 240        # what one simulation may take
SAVE_S = 60        # what a save after it needs
run = json.load(open("run.json"))
left = lambda: run["deadline_epoch"] - time.time()
callers = json.load(open(sys.argv[1]))
state = json.load(open(run["state_file"])).get(run["slot"]) if os.path.exists(run["state_file"]) else None
if not state:
    sys.exit("nothing saved yet: run save.py first")
done = [f for f in os.listdir("out") if f.startswith("sim-") and f.endswith(".started")]
n = len(done) + 1
if n > run.get("sims_max", 3):
    sys.exit("no more simulations in this run (%d done)" % len(done))
if left() < SIM_S + SAVE_S:
    sys.exit("%.0f s left: not enough for a simulation (%d) and a save (%d)" % (left(), SIM_S, SAVE_S))
open("out/sim-%d.started" % n, "w").close()       # a failed simulation counts too
store_path = "out/callers.json"
store = json.load(open(store_path)) if os.path.exists(store_path) else {}
spec = {c["name"]: {"name": c["name"], "prompt": c["prompt"], "successCriteria": c["success_criteria"], "tags": ["floor"]}
        for c in callers}
key = {k: hashlib.sha1(json.dumps(v, sort_keys=True).encode()).hexdigest()[:10] for k, v in spec.items()}
new = [k for k in spec if store.get(k, {}).get("key") != key[k]]
if new:
    made = freya.create_personas([spec[k] for k in new])["personas"]
    store.update({k: {"id": p["id"], "key": key[k]} for k, p in zip(new, made)})
    json.dump(store, open(store_path, "w"), indent=1)
ids = {c["name"]: store[c["name"]]["id"] for c in callers}
t0 = time.time()
row = {"n": n, "callers": len(callers), "passed": 0, "simulation_id": None, "status": None, "seconds": 0, "failed": []}
def record():
    row["seconds"] = round(time.time() - t0, 1)
    if run.get("sims_log"):
        with open(run["sims_log"], "a") as f:
            f.write(json.dumps(row) + "\n")
try:
    while True:
        # the workspace runs one simulation at a time and refuses a second one: wait for the slot while time allows
        try:
            sim = freya.api("POST", "/api/v2/simulations", {
                "agentId": state["agent_id"], "name": "floor sim %d %s" % (n, time.strftime("%H:%M:%S")), "mode": "chat",
                "selectedPersonaIds": list(ids.values()),
                "customerVariablesMap": {ids[c["name"]]: c.get("variables", {}) for c in callers},
                "maxConcurrentCalls": max(1, len(callers)), "runsPerPersona": 1, "maxCallDurationSeconds": 180,
                "assistantLlmOverride": freya.AGENT_LLM, "routingLlmOverride": freya.AGENT_LLM,
                "extractionLlmOverride": freya.AGENT_LLM, "personaLlmOverride": freya.SIM_LLM, "analysisLlmOverride": freya.SIM_LLM})
            break
        except Exception as e:
            if "concurrent" not in str(e) or left() < SIM_S + SAVE_S + 20:
                raise
            print("another simulation is running in the workspace; waiting 20 s", flush=True)
            time.sleep(20)
    sim_id = row["simulation_id"] = (sim.get("simulation") or sim)["id"]
    stop = time.time() + min(SIM_S, left() - SAVE_S)
    status = None
    while time.time() < stop:
        time.sleep(10)
        try:
            s = freya.api("GET", "/api/v2/simulations/%s" % sim_id); status = (s.get("simulation") or s).get("status")
        except Exception as e:
            print("poll failed (%s), retrying" % str(e)[:80], flush=True); continue
        if status in ("completed", "failed", "paused", "cancelled"):
            break
    row["status"] = status if status in ("completed", "failed", "paused", "cancelled") else "not finished in time (%s)" % status
    its = freya.api("GET", "/api/v2/simulations/%s/iterations" % sim_id)
    its = its.get("iterations") or its.get("items") or its
    runs = freya.get_iteration(sim_id, its[0]["id"])["runs"] if its else []
except Exception as e:
    row["status"] = "error: %s" % str(e)[:300]; record()
    sys.exit("simulation failed: %s" % str(e)[:300])
by_persona = {r.get("personaId"): r for r in runs}
out = {"simulation_id": sim_id, "status": row["status"], "callers": []}
for c in callers:
    r = by_persona.get(ids[c["name"]], {})
    one = {"name": c["name"], "outcome": r.get("outcome"), "reason": r.get("reason"), "tools": [], "ended": None}
    if r.get("callId"):
        try:
            call = freya.get_call(r["callId"])
            one["ended"] = call.get("endedReason"); one["transcript"] = call.get("transcript")
            for m in call.get("messages", []):
                if m.get("role") != "system":
                    continue
                try:
                    ev = json.loads(m.get("message") or "{}")
                except ValueError:
                    continue
                if ev.get("event") == "function_call_start":
                    a = ev.get("args") or {}
                    one["tools"].append({"function": ev.get("function"), "url": a.get("url"), "method": a.get("method"),
                                         "body": a.get("body")})
                elif ev.get("event") == "function_call_complete" and one["tools"]:
                    one["tools"][-1]["result"] = ev.get("result")
                elif ev.get("event") == "error":
                    one["tools"].append({"error": ev.get("message"), "details": ev.get("details")})
        except Exception as e:
            one["ended"] = "call unreadable: %s" % str(e)[:200]
    out["callers"].append(one)
    ok = one["outcome"] == "pass"
    row["passed"] += ok
    if not ok:
        row["failed"].append(c["name"])
    print("%s %s | ended: %s\n  judge: %s" % ("PASS" if ok else "FAIL", c["name"], one["ended"], " ".join(str(one["reason"]).split())[:600]))
    for t in one["tools"]:
        print("  tool %s" % json.dumps(t, ensure_ascii=False)[:1500])
json.dump(out, open("out/sim-%d.json" % n, "w"), indent=1, ensure_ascii=False)
record()
print("simulation %d: %d / %d passed, %s, %s, %.0f s; raw result out/sim-%d.json" % (
    n, row["passed"], len(callers), sim_id, row["status"], row["seconds"], n))
'''


def prepare_workdir(work, case_dir, mock_url, slot, state_file, deadline_epoch, sims_log=None):
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
                                               "deadline_epoch": deadline_epoch, "sims_max": SIMS_MAX,
                                               "sims_log": str(sims_log) if sims_log else None}, indent=1))
    for name, text in (("left.py", LEFT_PY), ("save.py", SAVE_PY), ("chat.py", CHAT_PY), ("sim.py", SIM_PY)):
        (work / name).write_text(text)


def prompt_for(mock_url, budget_s):
    return ("Use the %s skill to build a phone agent from the case folder in ./case. The tools call the mock base URL "
            "%s and no other host. You have %d minutes in total (python3 left.py prints the seconds left); save a "
            "complete workflow well before the end." % (SKILL, mock_url, budget_s // 60))


def fix_prompt_for(mock_url, budget_s):
    return ("Use the %s skill. A workflow built from the case folder in ./case is saved and is in out/workflow.json. "
            "A reviewer from another model family wrote out/review.md: follow the skill's section on the review. "
            "The tools call the mock base URL %s and no other host. You have %d minutes in total (python3 left.py "
            "prints the seconds left); the saved workflow stays unless a better one saves. One more simulation (sim.py) is "
            "allowed only if the skill's limits and the time left allow it." % (SKILL, mock_url, budget_s // 60))


def case_documents(case):
    """The text of the case folder's text documents (bounded) and the names of the other files."""
    parts, binaries, used = [], [], 0
    for f in sorted(p for p in case.rglob("*") if p.is_file()):
        name = str(f.relative_to(case))
        text = None
        if f.suffix.lower() in TEXT_SUFFIXES or not f.suffix:
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                text = None
        if text is None:
            binaries.append(name)
            continue
        text = text[:max(0, DOC_CHARS_MAX - used)]
        used += len(text)
        parts.append("=== %s ===\n%s" % (name, text))
    return "\n\n".join(parts), binaries


def slot_entry(state_file, slot):
    return (json.loads(state_file.read_text()) if state_file.exists() else {}).get(slot)


def review(work, timeout_s):
    """The second family's review of the saved workflow into out/review.md. Returns (usage, path); raises on failure."""
    sys.path.insert(0, str(ROOT))
    from builder.readers import models

    documents, binaries = case_documents(work / "case")
    prompt = REVIEW_PROMPT.format(binaries=", ".join(binaries) or "none", documents=documents,
                                  workflow=(work / "out" / "workflow.json").read_text())
    text, usage = models.r4_text(prompt, system=REVIEW_SYSTEM, timeout_s=timeout_s, purpose=REVIEW_PURPOSE)
    path = work / "out" / "review.md"
    path.write_text("# Review of out/workflow.json (%s, %s)\n\n%s\n" % (usage.get("backend"), usage.get("model"), text))
    return usage, path


def second_family():
    """The second family's backend, or None when only Claude is there."""
    sys.path.insert(0, str(ROOT))
    from builder.readers import models

    b = models.r4_backend()
    return None if b == "claude" else b


def run_session(work, log_path, mock_url, seconds, model, prompt):
    """One Claude session, cut at `seconds`. Returns (outcome, seconds taken)."""
    t0 = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(session(work, log_path, mock_url, int(seconds), model, prompt), timeout=seconds))
        outcome = "finished"
    except asyncio.TimeoutError:
        outcome = "cut at %.0f s" % seconds
    except Exception as e:                     # a failed session never loses what it saved
        outcome = "failed: %s" % str(e)[:300]
    return outcome, round(time.monotonic() - t0, 1)


async def session(work, log_path, mock_url, budget_s, model, prompt=None):
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
    with log_path.open("a") as out:
        out.write(json.dumps({"start": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "case": "case/", "mock_url": mock_url,
                              "model": model, "budget_s": budget_s}) + "\n")
        async for message in query(prompt=prompt or prompt_for(mock_url, budget_s), options=options):
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
    state_file = pathlib.Path(a.state_file).resolve()
    mock_url = a.mock_url.rstrip("/")
    deadline = time.time() + budget
    sims_log = run_dir / "floor-sims.jsonl"
    sims_log.unlink(missing_ok=True)
    prepare_workdir(work, pathlib.Path(a.case_dir).resolve(), mock_url, a.slot, state_file, deadline, sims_log)
    model = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")
    log_path = run_dir / "floor-session.jsonl"
    log_path.unlink(missing_ok=True)
    steps_path = run_dir / "floor-steps.json"
    steps = []

    def step(**kw):
        steps.append(kw)
        steps_path.write_text(json.dumps(steps, indent=1))

    print("session log: %s" % log_path, flush=True)
    before = slot_entry(state_file, a.slot)
    outcome, took = run_session(work, log_path, mock_url, budget, model, None)
    step(name="first", model=model, purpose=FIRST_PURPOSE, seconds=took, outcome=outcome, log=log_path.name)
    if outcome.startswith("cut"):
        print("session cut at the budget (%.0f s); whatever was saved stays saved" % budget, flush=True)
        return 2
    saved = slot_entry(state_file, a.slot)
    left = deadline - time.time()
    skip = None
    if not saved or saved == before or not (work / "out" / "workflow.json").exists():
        skip = "nothing saved by the first session"
    elif left < REVIEW_MIN_S:
        skip = "%.0f s left, %d needed" % (left, REVIEW_MIN_S)
    elif second_family() is None:
        skip = "no second model family (no OPENAI_API_KEY, no codex CLI)"
    if skip:
        step(name="review", purpose=REVIEW_PURPOSE, outcome="skipped: " + skip)
        print("floor review skipped: %s; the first saved workflow stands" % skip, flush=True)
        return 0
    t0 = time.monotonic()
    try:
        usage, path = review(work, min(REVIEW_TIMEOUT_S, left - FIX_MIN_S))
    except Exception as e:                     # the saved workflow stands
        step(name="review", purpose=REVIEW_PURPOSE, seconds=round(time.monotonic() - t0, 1),
             outcome="failed: %s" % str(e)[:300])
        print("floor review failed (%s); the first saved workflow stands" % str(e)[:300], flush=True)
        return 0
    step(name="review", model=usage.get("model"), backend=usage.get("backend"), purpose=REVIEW_PURPOSE,
         seconds=usage.get("seconds"), tokens=usage.get("tokens"), outcome="ok", review=str(path.relative_to(run_dir)))
    print("floor review written: %s" % path, flush=True)
    left = deadline - time.time()
    if left < FIX_MIN_S:
        step(name="fix", purpose=FIX_PURPOSE, outcome="skipped: %.0f s left after the review, %d needed" % (left, FIX_MIN_S))
        return 0
    fix_log = run_dir / "floor-fix-session.jsonl"
    fix_log.unlink(missing_ok=True)
    print("fix session log: %s" % fix_log, flush=True)
    outcome, took = run_session(work, fix_log, mock_url, left, model, fix_prompt_for(mock_url, left))
    after = slot_entry(state_file, a.slot)
    step(name="fix", model=model, purpose=FIX_PURPOSE, seconds=took, log=fix_log.name,
         outcome="%s, %s" % (outcome, "saved again" if after != saved else "no new save; the first saved workflow stands"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
