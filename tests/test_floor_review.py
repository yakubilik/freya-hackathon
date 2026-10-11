"""The case floor's review and fix (builder/floor/runner.py): after the first Claude session saved a workflow with time
left, a second model family reviews it against the case documents and a second Claude session gets the findings; with
little time, no second family or a failed review the first saved workflow stands. Sessions and model calls are faked;
nothing reaches a model, the platform or a mock. The case data is invented and domain-neutral.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "builder" / "floor"))
import runner  # noqa: E402
from builder import build  # noqa: E402
from builder.readers import models  # noqa: E402

MOCK = "http://127.0.0.1:9999"
SAVED = {"workflow_id": "wf-1", "agent_id": "ag-1", "version": 1}


def _case(tmp_path):
    d = tmp_path / "case"
    d.mkdir()
    (d / "BRIEF.md").write_text("# Widget desk\nThe caller asks for the colour of a widget. Calls are in English.\n")
    (d / "services.md").write_text("POST /widgets/colour with {\"widget\": string}; answers {\"colour\": string}.\n")
    (d / "drawing.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
    return d


@pytest.fixture
def floor(tmp_path, monkeypatch):
    """Runs runner.main with fake sessions: the first one writes out/workflow.json and saves into the slot."""
    case = _case(tmp_path)
    state = tmp_path / "state.json"
    run_dir = tmp_path / "run"
    calls = []

    def fake_session(work, log_path, mock_url, seconds, model, prompt):
        calls.append({"log": log_path.name, "prompt": prompt, "seconds": seconds,
                      "review": (work / "out" / "review.md").read_text() if (work / "out" / "review.md").exists() else None})
        log_path.write_text("{}\n")
        if prompt is None:
            (work / "out" / "workflow.json").write_text(json.dumps({"steps": [{"name": "colour"}]}))
            state.write_text(json.dumps({"slot-x": SAVED}))
        return "finished", 1.0

    monkeypatch.setattr(runner, "run_session", fake_session)
    monkeypatch.setattr(runner, "second_family", lambda: "codex")

    def go(budget=1500):
        code = runner.main([str(case), MOCK, "--run-dir", str(run_dir), "--slot", "slot-x", "--state-file", str(state),
                            "--budget", str(budget)])
        steps = json.loads((run_dir / "floor-steps.json").read_text())
        return code, steps
    return go, calls, state, run_dir


def test_review_runs_after_a_save_and_reaches_the_fix_session(floor, monkeypatch):
    go, calls, state, run_dir = floor
    seen = {}

    def fake_r4(prompt, *, system=None, timeout_s=600, deadline=None, purpose="r4"):
        seen.update(prompt=prompt, timeout=timeout_s, purpose=purpose)
        return "1. The tool path is wrong (step colour; services.md).", {"model": "m2", "backend": "codex", "seconds": 3.0, "tokens": 10}

    monkeypatch.setattr(models, "r4_text", fake_r4)
    code, steps = go()
    assert code == 0
    assert "=== BRIEF.md ===" in seen["prompt"] and "=== services.md ===" in seen["prompt"]
    assert "drawing.png" in seen["prompt"] and "\"colour\"" in seen["prompt"]          # binaries listed, workflow in
    assert seen["timeout"] <= runner.REVIEW_TIMEOUT_S and seen["purpose"] == runner.REVIEW_PURPOSE
    review = run_dir / "floor-work" / "out" / "review.md"
    assert "tool path is wrong" in review.read_text()
    assert [c["log"] for c in calls] == ["floor-session.jsonl", "floor-fix-session.jsonl"]
    assert calls[1]["prompt"] and "out/review.md" in calls[1]["prompt"] and "tool path is wrong" in calls[1]["review"]
    assert [s["name"] for s in steps] == ["first", "review", "fix"]
    assert steps[1]["outcome"] == "ok" and steps[1]["review"] == "floor-work/out/review.md"
    assert steps[2]["purpose"] == runner.FIX_PURPOSE and "first saved workflow stands" in steps[2]["outcome"]
    assert json.loads(state.read_text())["slot-x"] == SAVED


def test_review_skipped_when_time_is_short(floor, monkeypatch):
    go, calls, state, run_dir = floor
    monkeypatch.setattr(models, "r4_text", lambda *a, **k: pytest.fail("no review with little time"))
    code, steps = go(budget=500)
    assert code == 0 and len(calls) == 1
    assert steps[-1]["name"] == "review" and steps[-1]["outcome"].startswith("skipped:")
    assert "needed" in steps[-1]["outcome"] and not (run_dir / "floor-work" / "out" / "review.md").exists()


def test_review_skipped_without_a_second_family(floor, monkeypatch):
    go, calls, state, run_dir = floor
    monkeypatch.setattr(runner, "second_family", lambda: None)
    monkeypatch.setattr(models, "r4_text", lambda *a, **k: pytest.fail("no review without a second family"))
    code, steps = go()
    assert code == 0 and len(calls) == 1 and "no second model family" in steps[-1]["outcome"]


def test_review_failure_keeps_the_saved_workflow(floor, monkeypatch):
    go, calls, state, run_dir = floor

    def boom(*a, **k):
        raise models.ModelCallError("every R4 backend failed: codex: exit 1")

    monkeypatch.setattr(models, "r4_text", boom)
    code, steps = go()
    assert code == 0 and len(calls) == 1                                    # no fix session after a failed review
    assert steps[-1]["name"] == "review" and steps[-1]["outcome"].startswith("failed:")
    assert json.loads(state.read_text())["slot-x"] == SAVED
    assert json.loads((run_dir / "floor-work" / "out" / "workflow.json").read_text())


def test_trace_lines_for_review_and_fix(tmp_path):
    s = build.Schedule(1800)
    tr = build.Trace(tmp_path / "run", s)
    steps = [{"name": "first", "model": "c", "purpose": runner.FIRST_PURPOSE, "seconds": 400, "outcome": "finished"},
             {"name": "review", "model": "m2", "backend": "codex", "purpose": runner.REVIEW_PURPOSE, "seconds": 90.0,
              "tokens": 10, "outcome": "ok", "review": "floor-work/out/review.md"},
             {"name": "fix", "model": "c", "purpose": runner.FIX_PURPOSE, "seconds": 500, "outcome": "finished, saved again",
              "log": "floor-fix-session.jsonl"}]
    p = tmp_path / "steps.json"
    p.write_text(json.dumps(steps))
    build._trace_floor_steps(tr, p)
    log = (tmp_path / "run" / "trace.log").read_text()
    assert "purpose=floor review: second-family audit of the saved workflow against the case documents" in log
    assert "purpose=floor fix: apply the verified review findings" in log
    assert "floor-work/out/review.md" in log and "floor-fix-session.jsonl" in log
    assert [c["purpose"] for c in tr.model_calls] == [runner.REVIEW_PURPOSE, runner.FIX_PURPOSE]

    tr2 = build.Trace(tmp_path / "run2", s)
    p.write_text(json.dumps([{"name": "review", "purpose": runner.REVIEW_PURPOSE, "outcome": "skipped: 300 s left, 600 needed"}]))
    build._trace_floor_steps(tr2, p)
    log2 = (tmp_path / "run2" / "trace.log").read_text()
    assert "skipped: 300 s left, 600 needed; the first saved workflow stands" in log2 and not tr2.model_calls
