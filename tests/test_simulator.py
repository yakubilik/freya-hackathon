"""End-to-end runs of real workflows through the local simulator against the local bank (offline, no model)."""
import json
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kit" / "build-the-builder" / "tools"))

from harness.simulator import Simulator, rewrite_urls, run_case  # noqa: E402
from score import score_ledger  # noqa: E402  (the kit's ledger scorer)

CASES_PATH = ROOT / "kit" / "build-the-builder" / "public-test-set.json"
CASES = {c["id"]: c for c in json.load(open(CASES_PATH))}
BASE_AGENT = ROOT / "kit" / "build-the-builder" / "examples" / "base-agent.json"
BRIEF_A = pathlib.Path("/tmp/kit-run/out/brief-a.workflow.json")


def _bank_module():
    """Lane A's bank/server.py; the draft copy in harness/_draft_bank.py only as a fallback."""
    if (ROOT / "bank" / "server.py").exists():
        from bank import server
        return server
    import importlib.util
    spec = importlib.util.spec_from_file_location("_draft_bank", ROOT / "harness" / "_draft_bank.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bank():
    srv = _bank_module().serve(0, [str(CASES_PATH)])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def tool(name, **args):
    return {"name": name, "args": args}


def test_rewrite_urls_points_every_tool_at_the_bank():
    wf = json.load(open(BASE_AGENT))
    out = rewrite_urls(wf, "http://127.0.0.1:1234")
    urls = []

    def walk(x):
        if isinstance(x, dict):
            if "url" in (x.get("properties") or {}):
                urls.append(x["properties"]["url"]["default"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(out)
    assert urls and all(u.startswith("http://127.0.0.1:1234/v1/") for u in urls)
    # the original is untouched
    assert "freya-bank-mock" in wf["nodes"]["identity"]["tools"][0]["function"]["parameters"]["properties"]["url"]["default"]


# ---------------------------------------------------------------------------------------------------------------
# 1. the kit's base agent on PUB-01
# ---------------------------------------------------------------------------------------------------------------
def test_base_agent_pub01_promise_and_close_call_last(bank):
    wf = json.load(open(BASE_AGENT))
    script = {
        "turns": [
            {"say": "Yes, this is Daniel Reyes.", "agent": "Thank you. What is your date of birth?"},
            {"say": "14 March 1988", "tool_calls": [tool("verify_identity", field="date_of_birth", answer="1988-03-14")], "agent": "And the last four digits of your phone number?"},
            {"say": "4471", "tool_calls": [tool("verify_identity", field="phone_last4", answer="4471")]},
            {"say": "Yes, I have a minute.", "tool_calls": [tool("get_account")], "agent": "The past due amount is 420. When can you pay?"},
            {"say": "Today, the full amount.", "agent": "420 today. Do you confirm?"},
            {"say": "Yes.", "tool_calls": [tool("create_promise", product_id="p1", amount=420, date="2026-10-14")], "agent": "Recorded. Have a good day."},
            {"say": "Bye.", "tool_calls": [tool("end_call")]},
        ],
        # close_call is a workflow-level end_of_call lifecycle tool; outcome and reason are model-filled
        "end_of_call": {"close_call": {"outcome": "promise", "reason": "none"}},
    }
    record, ledger, session = run_case(wf, script, bank, case="PUB-01")
    assert record["ended"] and record["ended_reason"] == "end_call"
    # the tts entry line of `collection` was spoken right after the second verify_identity result
    assert "Thank you, that's verified" in record["transcript_text"]
    assert record["variables"]["verify_identity_response.data.all_verified"] == "true"
    assert record["variables"]["verify_identity_success_count"] == 2
    # the lifecycle tool fired after the end, and its pre-hook saw `config` and dropped `reason` for a promise
    assert [c["function"] for c in record["tool_calls"]][-1] == "close_call"
    assert "reason" not in record["tool_calls"][-1]["request"]["body"]
    assert record["tool_calls"][-1]["request"]["url"].startswith(bank)
    # the bank's ledger
    assert ledger["outcome"] == "promise" and ledger["reason"] is None
    assert [(p["product_id"], p["amount"], p["date"]) for p in ledger["promises"]] == [("p1", 420, "2026-10-14")]
    assert [c["tool"] for c in ledger["calls"]][-1] == "close_call"
    assert score_ledger(CASES["PUB-01"], ledger)["pass"], score_ledger(CASES["PUB-01"], ledger)
    # the record looks like a kit call record: system rows carry JSON event strings
    kinds = [json.loads(m["message"])["event"] for m in record["messages"] if m["role"] == "system"]
    assert {"node_enter", "function_call_start", "function_call_complete", "route_evaluated"} <= set(kinds)
    assert all({"role", "message", "messageId", "secondsFromStart", "nodeId"} <= set(m) for m in record["messages"])


# ---------------------------------------------------------------------------------------------------------------
# 2. brief-a (built by the kit run) on four public cases
# ---------------------------------------------------------------------------------------------------------------
pytestmark_brief = pytest.mark.skipif(not BRIEF_A.exists(), reason="/tmp/kit-run/out/brief-a.workflow.json not present")


def _brief_a():
    return json.load(open(BRIEF_A))


def _verified_turns(case):
    dob, last4 = case["identity"]["date_of_birth"], case["identity"]["phone_last4"]
    return [
        {"say": "Yes, speaking.", "tool_calls": [tool("transition_to_identity")]},
        {"say": "My date of birth is " + dob, "tool_calls": [tool("verify_identity", field="date_of_birth", answer=dob)], "agent": "Thank you. And the last four digits of your phone number?"},
        {"say": last4, "tool_calls": [tool("verify_identity", field="phone_last4", answer=last4)]},
    ]


@pytestmark_brief
def test_brief_a_pub01_happy_path(bank):
    case = CASES["PUB-01"]
    script = {"turns": _verified_turns(case) + [
        {"say": "Yes, I can pay the full amount today.", "agent": "Credit card ending 4821, 420.00 today. Do you confirm?"},
        {"say": "Yes, I confirm.", "tool_calls": [tool("create_promise", product_id="p1", amount=420.0, date="2026-10-14")]},
        {"say": "No, nothing else. Thanks.", "tool_calls": [tool("close_call", outcome="promise", reason="none")], "agent": "Thank you, goodbye."},
    ]}
    record, ledger, _ = run_case(_brief_a(), script, bank, case="PUB-01")
    assert record["ended"] and record["ended_reason"] == "call_closed", record["warnings"]
    nodes = [e["node"] for e in record["events"] if e["event"] == "node_enter"]
    assert nodes == ["setup", "greeting", "identity", "get_account", "account_facts", "collection", "wrap_up", "end"]
    v = record["variables"]
    # the setup code node ran first (initial code node), then account_facts rebuilt the facts from the real get_account response
    assert v["setup_success_count"] == 1 and v["account_facts_success_count"] == 1
    assert v["facts_state"] == "known"
    assert "credit card ending 4821" in v["product_facts"] and "product_id p1" in v["product_facts"]
    assert "FULL PAST-DUE AMOUNT: 420.00" in v["product_facts"]
    assert v["p_past_due"] == "420" and v["get_account_response.data.ok"] == "true"
    # the get_account result flattened: products is a list -> JSON string
    assert json.loads(v["get_account_response.data.products"])[0]["card_last4"] == "4821"
    assert "The past-due amount is 420.00" in record["transcript_text"]
    assert v["promise_state"] == "recorded" and v["call_closed"] == "yes"
    assert ledger["outcome"] == "promise" and ledger["reason"] is None
    assert score_ledger(case, ledger)["pass"], score_ledger(case, ledger)


@pytestmark_brief
def test_brief_a_pub03_three_wrong_answers(bank):
    case = CASES["PUB-03"]
    wrong = ["1991-07-12", "1992-08-21", "1990-07-21"]
    turns = [{"say": "Yes, that's me.", "tool_calls": [tool("transition_to_identity")]}]
    for d in wrong:
        turns.append({"say": d, "tool_calls": [tool("verify_identity", field="date_of_birth", answer=d)], "agent": "That does not match. What is your date of birth?"})
    turns.append({"say": "How much do I owe?", "agent": "[llm]"})
    record, ledger, _ = run_case(_brief_a(), {"turns": turns}, bank, case="PUB-03")
    assert record["ended"] and record["ended_reason"] == "call_closed"
    nodes = [e["node"] for e in record["events"] if e["event"] == "node_enter"]
    assert nodes == ["setup", "greeting", "identity", "close_failed", "end"]
    assert record["variables"]["id_state"] == "failed"
    assert record["variables"]["verify_identity_response.data.wrong_answers_left"] == 0
    assert "use the mobile app or visit a branch" in record["transcript_text"]
    # the close_failed pre_action is engine-run: outcome and reason baked, customer_id baked from the session
    close = [c for c in record["tool_calls"] if c["function"] == "close_call"]
    assert len(close) == 1 and close[0]["request"]["body"] == {"customer_id": ledger["calls"][-1]["args"].get("customer_id", close[0]["request"]["body"]["customer_id"]), "outcome": "not_verified", "reason": "failed"}
    assert record["variables"]["close_failed_success_count"] == 1
    assert (ledger["outcome"], ledger["reason"]) == ("not_verified", "failed")
    assert [c["tool"] for c in ledger["calls"]] == ["verify_identity"] * 3 + ["close_call"]
    assert score_ledger(case, ledger)["pass"], score_ledger(case, ledger)
    # the fourth customer turn never happened: the call had ended
    assert sum(1 for t in record["transcript"] if t["role"] == "user") == 4


@pytestmark_brief
def test_brief_a_pub02_third_party_callback(bank):
    case = CASES["PUB-02"]
    script = {"turns": [
        {"say": "This is her husband. What is this about?", "agent": "I can only discuss it with Ms Costa personally. When can she be reached?"},
        {"say": "I can pay it myself if you want.", "agent": "I cannot take that. When can Ms Costa be reached?"},
        {"say": "Tomorrow morning, around eleven.", "tool_calls": [tool("schedule_callback", date="2026-10-15", time="11:00"), tool("close_call", outcome="not_reached", reason="callback")]},
    ]}
    record, ledger, _ = run_case(_brief_a(), script, bank, case="PUB-02")
    assert record["ended"] and record["ended_reason"] == "call_closed"
    nodes = [e["node"] for e in record["events"] if e["event"] == "node_enter"]
    assert nodes == ["setup", "greeting", "end"]
    assert record["variables"]["callback_state"] == "booked"
    assert record["variables"]["schedule_callback_args.date"] == "2026-10-15"
    assert ledger["callbacks"] == [{"date": "2026-10-15", "time": "11:00"}]
    assert (ledger["outcome"], ledger["reason"]) == ("not_reached", "callback")
    assert [c["tool"] for c in ledger["calls"]] == ["schedule_callback", "close_call"]
    assert score_ledger(case, ledger)["pass"], score_ledger(case, ledger)


@pytestmark_brief
def test_brief_a_pub10_promise_fails_once_then_succeeds(bank):
    case = CASES["PUB-10"]
    promise = tool("create_promise", product_id="p1", amount=365.0, date="2026-10-16")
    script = {"turns": _verified_turns(case) + [
        {"say": "I cannot pay today.", "agent": "Could you pay 365.00 on Friday 16 October?"},
        {"say": "Yes, Friday works.", "agent": "Credit card ending 7740, 365.00 on Friday 16 October. Do you confirm?"},
        # the model calls create_promise; the bank fails the first call (fixture fault), the model calls it once more
        {"say": "Yes, I confirm.", "tool_calls": [promise, promise]},
        {"say": "No, that's all.", "tool_calls": [tool("close_call", outcome="promise", reason="none")], "agent": "Thank you, goodbye."},
    ]}
    record, ledger, _ = run_case(_brief_a(), script, bank, case="PUB-10")
    assert record["ended"] and record["ended_reason"] == "call_closed"
    v = record["variables"]
    cp = [c for c in record["tool_calls"] if c["function"] == "create_promise"]
    assert [c["result"]["status"] for c in cp] == ["error", "success"]
    assert cp[0]["result"]["status_code"] == 500 and cp[0]["result"]["data"]["ok"] is False
    assert v["create_promise_failure_count"] == 1 and v["create_promise_success_count"] == 1
    assert v["promise_fail"] == 1 and v["promise_state"] == "recorded"
    # the failure did not route away (failed_twice / failure_count > 1 both false), the success went to wrap_up
    routes = [e for e in record["events"] if e["event"] == "route_evaluated" and e["from_node"] == "collection"]
    assert [r["matched"] for r in routes][-2:] == [False, True]
    assert ledger["promises"] and len(ledger["promises"]) == 1
    assert score_ledger(case, ledger)["pass"], score_ledger(case, ledger)
    assert [c["tool"] for c in ledger["calls"]][-3:] == ["create_promise", "create_promise", "close_call"]


@pytestmark_brief
def test_brief_a_chat_route_skips_initial_code_node(bank):
    case = CASES["PUB-02"]
    script = {"turns": [{"say": "Wrong number.", "tool_calls": [tool("close_call", outcome="not_reached", reason="wrong_number")]}]}
    record, ledger, _ = run_case(_brief_a(), script, bank, case="PUB-02", skip_initial_code=True)
    assert "callback_facts" not in record["variables"] and "setup_success_count" not in record["variables"]
    assert record["ended"] and (ledger["outcome"], ledger["reason"]) == ("not_reached", "wrong_number")


def test_cli_runs_a_case(bank, tmp_path, capsys):
    from harness import simulator
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"turns": [{"say": "Yes", "tool_calls": [{"name": "end_call"}]}], "end_of_call": {"close_call": {"outcome": "not_verified", "reason": "declined"}}}))
    out = tmp_path / "rec.json"
    rc = simulator.main([str(BASE_AGENT), "--script", str(script), "--bank", bank, "--case", "PUB-01", "--out", str(out)])
    assert rc == 0
    saved = json.load(open(out))
    assert saved["record"]["ended_reason"] == "end_call" and saved["ledger"]["outcome"] == "not_verified"
    assert "ledger:" in capsys.readouterr().out
