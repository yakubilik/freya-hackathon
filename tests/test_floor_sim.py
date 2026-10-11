"""The case floor's simulation helper (sim.py, written by builder/floor/runner.py into floor-work): one bounded
simulation of the saved agent with callers the session writes, its trace lines, and the skill text that allows and
bounds it. The platform is faked (a stand-in for kit/freya.py and a fake clock); nothing reaches Freya, a model or a
mock. The case data is invented and domain-neutral.
"""
import io
import json
import os
import pathlib
import sys
import types
from contextlib import redirect_stdout

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "builder" / "floor"))
import runner  # noqa: E402
from builder import build  # noqa: E402

MOCK = "http://127.0.0.1:9999"
SAVED = {"workflow_id": "wf-1", "agent_id": "ag-1", "version": 1}
CALLERS = [
    {"name": "plain ask", "prompt": "You are Ada. You want the colour of widget W1. Short sentences.",
     "variables": {"caller_ref": "R-1"}, "success_criteria": "The agent states the colour."},
    {"name": "unknown widget", "prompt": "You are Bo. You ask about widget W9, which does not exist.",
     "variables": {"caller_ref": "R-2"}, "success_criteria": "The agent says it cannot find the widget."},
    {"name": "pushy", "prompt": "You are Cy. You ask the colour of a widget, then change your mind about which widget once.",
     "variables": {"caller_ref": "R-3"}, "success_criteria": "The agent declines politely and offers one widget."},
]


def _workdir(tmp_path, left_s=1200):
    case = tmp_path / "case"
    case.mkdir(parents=True)
    (case / "BRIEF.md").write_text("# Widget desk\nThe caller asks for the colour of a widget.\n")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"slot-x": SAVED}))
    work = tmp_path / "work"
    clock = [1_000_000.0]
    runner.prepare_workdir(work, case, MOCK, "slot-x", state, clock[0] + left_s, tmp_path / "floor-sims.jsonl")
    (work / "out" / "workflow.json").write_text(json.dumps({"steps": [{"name": "colour"}]}))
    (work / "callers.json").write_text(json.dumps(CALLERS))
    return work, state, clock


class FakePlatform:
    """Stands in for kit/freya.py: personas, one simulation, its iteration and calls."""

    def __init__(self, status="completed", fail_start=False):
        self.status, self.fail_start = status, fail_start
        self.personas, self.started = [], []
        self.AGENT_LLM, self.SIM_LLM = {"provider": "p", "model": "a"}, {"provider": "p", "model": "s"}

    def create_personas(self, personas):
        made = []
        for p in personas:
            self.personas.append(p)
            made.append({"id": "pe-%d" % len(self.personas), **p})
        return {"personas": made}

    def api(self, method, path, body=None, **params):
        if method == "POST" and path == "/api/v2/simulations":
            if self.fail_start:
                raise RuntimeError("HTTP 500 from the platform")
            self.started.append(body)
            return {"simulation": {"id": "sim-%d" % len(self.started)}}
        if path.endswith("/iterations"):
            return {"iterations": [{"id": "it-1"}]}
        if path.startswith("/api/v2/simulations/"):
            return {"simulation": {"status": self.status}}
        raise AssertionError("unexpected call %s %s" % (method, path))

    def get_iteration(self, sim_id, it_id):
        body = self.started[-1]
        runs = []
        for i, pid in enumerate(body["selectedPersonaIds"]):
            runs.append({"personaId": pid, "callId": "call-%s" % pid, "outcome": "pass" if i == 0 else "fail",
                         "reason": "ok" if i == 0 else "the agent transferred in the first turn"})
        return {"runs": runs}

    def get_call(self, call_id):
        ev = [{"event": "function_call_start", "function": "colour_lookup",
               "args": {"url": MOCK + "/widgets/colour", "method": "POST", "body": {} if "2" in call_id else {"widget": "W1"}}},
              {"event": "function_call_complete", "function": "colour_lookup", "result": {"colour": "teal"}}]
        return {"endedReason": "end_call_done", "transcript": "...",
                "messages": [{"role": "system", "message": json.dumps(e)} for e in ev]}


def _run_sim(work, monkeypatch, fake, clock):
    """Runs sim.py as the session would (cwd = floor-work) with the fake platform and a fake clock."""
    monkeypatch.chdir(work)
    monkeypatch.setitem(sys.modules, "freya", types.SimpleNamespace(**{
        k: getattr(fake, k) for k in ("api", "create_personas", "get_iteration", "get_call", "AGENT_LLM", "SIM_LLM")}))
    import time as _time

    def sleep(s):
        clock[0] += s
    monkeypatch.setattr(_time, "sleep", sleep)
    monkeypatch.setattr(_time, "time", lambda: clock[0])
    monkeypatch.setattr(sys, "argv", ["sim.py", "callers.json"])
    out, code = io.StringIO(), None
    with redirect_stdout(out):
        try:
            exec(compile((work / "sim.py").read_text(), "sim.py", "exec"), {"__name__": "__main__"})
        except SystemExit as e:
            code = e.code
    return out.getvalue(), code


def test_sim_py_is_written_with_its_bounds(tmp_path):
    work, state, clock = _workdir(tmp_path)
    assert (work / "sim.py").read_text() == runner.SIM_PY
    run = json.loads((work / "run.json").read_text())
    assert run["sims_max"] == runner.SIMS_MAX == 3 and run["sims_log"].endswith("floor-sims.jsonl")
    for helper in ("left.py", "save.py", "chat.py"):
        assert (work / helper).exists()


def test_a_simulation_prints_callers_and_tool_bodies(tmp_path, monkeypatch):
    work, state, clock = _workdir(tmp_path)
    fake = FakePlatform()
    out, code = _run_sim(work, monkeypatch, fake, clock)
    assert code is None
    body = fake.started[0]
    assert body["agentId"] == "ag-1" and len(body["selectedPersonaIds"]) == 3
    assert body["customerVariablesMap"]["pe-2"] == {"caller_ref": "R-2"}           # per-caller variables, as run_cases
    assert "PASS plain ask" in out and "FAIL unknown widget" in out and "transferred in the first turn" in out
    assert '"body": {}' in out and '"widget": "W1"' in out and "teal" in out         # every request body is shown
    assert "1 / 3 passed" in out and "sim-1" in out
    raw = json.loads((work / "out" / "sim-1.json").read_text())
    assert raw["simulation_id"] == "sim-1" and raw["callers"][1]["tools"][0]["body"] == {}
    row = json.loads((tmp_path / "floor-sims.jsonl").read_text().splitlines()[0])
    assert row["callers"] == 3 and row["passed"] == 1 and row["status"] == "completed" and row["n"] == 1

    # the same names and texts are reused, not created again
    out, code = _run_sim(work, monkeypatch, fake, clock)
    assert len(fake.personas) == 3 and len(fake.started) == 2
    assert json.loads((tmp_path / "floor-sims.jsonl").read_text().splitlines()[1])["n"] == 2


def test_simulations_are_bounded(tmp_path, monkeypatch):
    work, state, clock = _workdir(tmp_path, left_s=200)
    out, code = _run_sim(work, monkeypatch, FakePlatform(), clock)
    assert code and "not enough for a simulation" in code

    work, state, clock = _workdir(tmp_path / "b", left_s=5000)
    fake = FakePlatform()
    for _ in range(runner.SIMS_MAX):
        _run_sim(work, monkeypatch, fake, clock)
    out, code = _run_sim(work, monkeypatch, fake, clock)
    assert code and "no more simulations" in code and len(fake.started) == runner.SIMS_MAX


def test_nothing_saved_means_no_simulation(tmp_path, monkeypatch):
    work, state, clock = _workdir(tmp_path)
    state.write_text("{}")
    fake = FakePlatform()
    out, code = _run_sim(work, monkeypatch, fake, clock)
    assert code and "nothing saved" in code and not fake.started


@pytest.mark.parametrize("fake", [FakePlatform(status="running"), FakePlatform(fail_start=True)])
def test_a_hung_or_failed_simulation_keeps_the_saved_workflow(tmp_path, monkeypatch, fake):
    work, state, clock = _workdir(tmp_path)
    start = clock[0]
    out, code = _run_sim(work, monkeypatch, fake, clock)
    assert clock[0] - start <= 240 + 10                                     # bounded wait, never past the deadline
    assert json.loads(state.read_text())["slot-x"] == SAVED
    assert json.loads((work / "out" / "workflow.json").read_text())
    row = json.loads((tmp_path / "floor-sims.jsonl").read_text().splitlines()[-1])
    assert row["status"].startswith("not finished") or row["status"].startswith("error")


def test_skill_allows_and_bounds_simulations():
    text = (ROOT / "builder" / "floor" / "SKILL.md").read_text()
    assert "Never start simulations" not in text and "python3 sim.py callers.json" in text
    assert "At most 3 simulations" in text and "one at a time" in text and "python3 left.py" in text
    assert "main path" in text and "unusual case" in text and "tries to misuse the agent" in text
    assert "request body" in text and "hooks" in text and "kit/docs/tools-and-code.md" in text


def test_trace_lines_for_simulations(tmp_path):
    tr = build.Trace(tmp_path / "run", build.Schedule(1800))
    p = tmp_path / "floor-sims.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"n": 1, "callers": 4, "passed": 1, "simulation_id": "sim-a", "status": "completed", "seconds": 31.0,
         "failed": ["x", "y", "z"]},
        {"n": 2, "callers": 4, "passed": 4, "simulation_id": "sim-b", "status": "completed", "seconds": 40.2,
         "failed": []}]) + "\n")
    build._trace_floor_sims(tr, p)
    log = (tmp_path / "run" / "trace.log").read_text()
    assert "floor simulation 1 of the saved phone agent (4 simulated callers)" in log
    assert "1 / 4 passed, simulation sim-a, status completed, 31.0 s" in log
    assert [t["result"] for t in tr.tests] == ["FAIL", "PASS"]

    tr2 = build.Trace(tmp_path / "run2", build.Schedule(1800))
    build._trace_floor_sims(tr2, tmp_path / "missing.jsonl")
    assert "floor simulations: none ran" in (tmp_path / "run2" / "trace.log").read_text() and not tr2.tests
