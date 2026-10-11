"""The emitter: compile Brief A and B, walk them clean, and run scripted calls through the local simulator against
the in-process bank, asserting the ledger equals each scenario's `expected`.

Each customer turn is a bundle of engine events (the same bundles as tests/test_engine_step.py); the test turns a
bundle into the extraction values of the node the call is in (`<node>_reply1`, `<node>_date1`, ...), so the
dialogue and extraction models are the only parts replaced by a script. Everything else (dispatchers, the engine
code node, baked writes, hooks, result mapping, routing, close nodes) runs as emitted.
"""
import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bank import replay  # noqa: E402
from builder.emitter.emit import emit, counts  # noqa: E402
from builder.emitter.fragments import STAGE_NODE, STAGE_FIELDS, EmitError  # noqa: E402
from builder.emitter.walk import walk  # noqa: E402
from builder.readers.api_file import load_api  # noqa: E402
from harness.simulator import Simulator, open_bank_session, bank_ledger  # noqa: E402

TABLE_A = json.load(open(ROOT / "fixtures" / "tables" / "brief-a.json"))
TABLE_B = json.load(open(ROOT / "fixtures" / "tables" / "brief-b.json"))
API_PATH = ROOT / "kit" / "build-the-builder" / "tools" / "openapi.json"
API_RAW = json.load(open(API_PATH))
API = load_api(API_PATH)
PUBLIC = {c["id"]: c for c in json.load(open(ROOT / "kit" / "build-the-builder" / "public-test-set.json"))}
EXTENDED = {c["id"]: c for c in json.load(open(ROOT / "scenarios" / "extended-test-set.json"))}
CASES = dict(PUBLIC)
CASES.update(EXTENDED)
NODE_STAGE = {v: k for k, v in STAGE_NODE.items()}


@pytest.fixture(scope="module")
def bank():
    srv, url = replay.start_server()
    yield url
    srv.shutdown()


@pytest.fixture(scope="module")
def workflows(bank):
    return {"A": emit(TABLE_A, API, variant="test", bank_url=bank), "B": emit(TABLE_B, API, variant="test", bank_url=bank)}


# ---------------------------------------------------------------------------------------------
# compile and walk


@pytest.mark.parametrize("brief,table", [("A", TABLE_A), ("B", TABLE_B)])
@pytest.mark.parametrize("variant", ["final", "test"])
def test_emit_and_walk_clean(brief, table, variant):
    wf = emit(table, API, variant=variant, bank_url="http://127.0.0.1:9" if variant == "test" else None)
    assert walk(wf, table, API_RAW) == []
    assert wf["initial_node"] == "setup" and "engine" in wf["nodes"]
    urls = [fn["function"]["parameters"]["properties"]["url"]["default"]
            for n in wf["nodes"].values() for fn in n.get("pre_actions") or [] if fn["function"]["handler"].endswith("api_call")]
    origin = "https://freya-bank-mock.freyavoice.workers.dev/v1/" if variant == "final" else "http://127.0.0.1:9/v1/"
    assert urls and all(u.startswith(origin) for u in urls)
    assert json.dumps(emit(table, API, variant=variant, bank_url="http://127.0.0.1:9" if variant == "test" else None)) == json.dumps(wf)


def test_emit_accepts_raw_openapi_and_counts():
    wf = emit(TABLE_A, API_RAW)
    c = counts(wf)
    assert c["nodes"] == len(wf["nodes"]) and c["by_type"]["end_call"] == 1


def test_speech_prompts_preserve_instructions_without_a_sentence_cap():
    table = copy.deepcopy(TABLE_B)
    table["parameters"]["organisation.name"]["value"] = "Example Cooperative"
    wf = emit(table, API)
    assert "Example Cooperative" in wf["system_prompt"]
    assert "one or two" not in wf["system_prompt"]
    for name in ("greeting", "identity", "negotiate", "readback"):
        node = wf["nodes"][name]
        prompt = node["on_enter"]["prompt"]
        assert "one or two" not in prompt
        assert "Preserve each supplied product's details" in prompt
        assert "not words to say to the customer" in prompt
        assert "your own help, not offering a transfer" in node["task_message"]
        assert "do not say goodbye" in node["task_message"]
        assert "Freya Bank" not in node["task_message"]


@pytest.mark.parametrize("variables", [
    {"customer_id": "actual-member", "member_key": "test"},
    {"customer_id": "c_test", "member_key": "actual-member"},
    {"member_key": "actual-member"},
])
def test_customer_identifier_alias_uses_the_live_call_value(variables):
    table, api = copy.deepcopy(TABLE_A), copy.deepcopy(API)
    table["parameters"]["call_variables"]["value"] = [
        "member_key" if name == "customer_id" else name
        for name in table["parameters"]["call_variables"]["value"]
    ]
    for tool in api["tools"].values():
        fields = tool["request_fields"]
        fields["member_key"] = fields.pop("customer_id")
    wf = emit(table, api)
    assert wf["test_variables"]["member_key"] == ""
    code = wf["nodes"]["setup"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    exec(code, {"vars": variables})
    assert variables["customer_id"] == variables["member_key"] == "actual-member"


def test_verification_service_failure_apology_reaches_close_speech():
    from builder.engine.step import new_state, step
    table = copy.deepcopy(TABLE_A)
    table["parameters"]["tools.retries"] = {"value": 0, "confidence": "quoted"}
    table["phrases"].append({"id": "system_unavailable", "kind": "mandatory", "exact": False,
                             "text": "Explain the system is unavailable and apologise."})
    now = "2026-10-14T11:00"
    st, _ = step(new_state(), [E("party_confirmed")], table, now)
    st, _ = step(st, [E("id_answer", text="1984-07-09")], table, now)
    wf = emit(table, API)
    code = wf["nodes"]["engine"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    values = {"now": now, "engine_state": json.dumps(st), "engine_events": json.dumps([
        {"kind": "tool_result", "tool": "verify_identity", "result": "failed",
         "data": {"ok": False, "error": "service unavailable"}}
    ])}
    exec(code, {"vars": values})
    assert values["engine_next"] == "close"
    assert "I am sorry, the system is unavailable right now." in values["close_text"]
    assert "Explain" not in values["close_text"]


def test_close_nodes_one_per_row_reason_absent_when_none():
    wf = emit(TABLE_B, API)
    rows = {(r["outcome"], r["reason"]) for r in TABLE_B["parameters"]["closing.rows"]["value"]}
    closes = {}
    for name, n in wf["nodes"].items():
        for fn in n.get("pre_actions") or []:
            if fn["function"]["name"] == "close_call":
                body = fn["function"]["parameters"]["properties"]["body"]["properties"]
                closes[name] = (body["outcome"]["default"], body["reason"]["default"] if "reason" in body else None)
    assert set(closes.values()) == rows and len(closes) == len(rows)
    assert "reason" not in wf["nodes"]["close_promise_none"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]


def test_verbatim_lines_reach_the_model_word_for_word(bank, workflows):
    """Exact phrases are never tts of the passthrough S_say node (on the platform that node ends the turn and the next
    customer message hangs the chat, measured 2026-10-10): they reach the dialogue model as the head line (before its
    content) or the tail line (after it), word for word. A non-exact table phrase is content, not a sentence."""
    wf = workflows["A"]

    def phrase(pid, **fill):
        text = next(p["text"] for p in TABLE_A["phrases"] if p["id"] == pid)
        for k, v in fill.items():
            text = text.replace("{%s}" % k, v)
        return text

    case = PUBLIC["PUB-01"]
    session = open_bank_session(bank, customer=case)
    sim = Simulator(wf, variables=dict(session["variables"]))
    sim.start()
    assert sim.current == "greeting" and sim.table["say_tts"] == "" and sim.table["speech_source"] == "engine"
    assert "digital assistant" in sim.table["say_content"] and sim.table["say_head_line"] == ""
    verbatim = [sim.table["say_tail_line"]]
    for b in verified(case) + [[E("pay_today_yes")], [E("confirm")]]:
        sim.turn({"say": "x", "extract": extract_for(sim.current, b)})
        assert sim.table.get("say_tts", "") == ""
        verbatim += [sim.table.get("say_head_line", ""), sim.table.get("say_tail_line", ""), sim.table.get("close_text", "")]
    spoken = " ".join(verbatim)
    v = case["variables"]
    for pid in ("party_question", "do_you_confirm", "text_message"):
        assert phrase(pid, title=v["title"], last_name=v["last_name"]) in spoken, pid


def test_cli_writes_and_walks(tmp_path):
    from builder.emitter.emit import main
    out = tmp_path / "wf.json"
    assert main([str(ROOT / "fixtures" / "tables" / "brief-b.json"), "--api", str(API_PATH), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["initial_node"] == "setup"
    from builder.emitter.walk import main as walk_main
    assert walk_main([str(out), "--table", str(ROOT / "fixtures" / "tables" / "brief-b.json"), "--api", str(API_PATH)]) == 0


def test_walk_finds_planted_defects():
    wf = emit(TABLE_A, API)
    bad = copy.deepcopy(wf)
    bad["nodes"]["greeting"]["task_message"] += " Mention the payment."
    bad["nodes"]["negotiate"]["transitions"].append({"target_node": "nowhere", "description": "x", "condition": {"operator": "always"}})
    bad["nodes"]["identity_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"] = "vars['x'] = 1  # }}"
    rb = bad["nodes"]["close_promise_none"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]
    rb["reason"] = {"type": "string", "default": ""}
    rb["amount_typo"] = {"type": "string", "default": "1"}
    bad["nodes"]["engine"]["transitions"] = [t for t in bad["nodes"]["engine"]["transitions"]
                                            if "readback" not in json.dumps(t["condition"])]
    bad["nodes"]["readback_wait"]["task_message"] += " {{never_written}}"
    found = "\n".join(walk(bad, TABLE_A, API_RAW))
    for needle in ("forbidden phrase 'payment'", "unknown node 'nowhere'", "contains '{{' or '}}'", "does not clear identity_reply1",
                   "sends an empty reason", "'amount_typo', not in the close_call request schema", "engine_next 'readback' has no explicit",
                   "{{never_written}}"):
        assert needle in found, needle


def test_plan_reorders_known_fragments_and_rejects_the_rest():
    table = copy.deepcopy(TABLE_A)
    assert list(emit(table, API)["nodes"])[:4] == ["setup", "engine", "greeting_say", "greeting"]
    for mutate, msg in [
        (lambda p: p.insert(1, {"id": "consent", "type": "consent"}), "gate fragment"),
        (lambda p: p.append({"id": "x", "type": "teleport"}), "unknown type"),
        (lambda p: p.pop(6), "omits"),
        (lambda p: p.insert(0, p.pop(2)), "start with party"),
        (lambda p: p.insert(1, p.pop(2)), "before verify"),
    ]:
        t = copy.deepcopy(TABLE_A)
        mutate(t["plan"])
        with pytest.raises(EmitError, match=msg):
            emit(t, API)


def test_test_variant_needs_a_bank_url(monkeypatch):
    monkeypatch.delenv("OWN_BANK_URL", raising=False)
    with pytest.raises(EmitError):
        emit(TABLE_A, API, variant="test")
    monkeypatch.setenv("OWN_BANK_URL", "https://example.trycloudflare.com")
    wf = emit(TABLE_A, API, variant="test")
    assert wf["nodes"]["w_get_account"]["pre_actions"][0]["function"]["parameters"]["properties"]["url"]["default"] == \
        "https://example.trycloudflare.com/v1/get_account"


# ---------------------------------------------------------------------------------------------
# simulated calls


def E(kind, item=None, text=None, date=None, time=None, amount=None):
    return {"kind": kind, "item": item, "text": text, "date": date, "time": time, "amount": amount}


def verified(case):
    ident = case["identity"]
    return [[E("party_confirmed")], [E("id_answer", text=ident["date_of_birth"])], [E("id_answer", text=ident["phone_last4"])]]


def extract_for(node, bundle):
    """The extraction values a correct extraction model would write in `node` for this bundle of events."""
    base = node if node in NODE_STAGE else node.rsplit("_", 1)[0]
    assert base in NODE_STAGE, "the call is in %r, not a listening node" % node
    stage = NODE_STAGE[base]
    out = {}
    for k, ev in enumerate(bundle, 1):
        src = {"reply": ev["kind"], "item": ev["item"], "amount": ev["amount"], "date": ev["date"], "time": ev["time"], "words": ev["text"]}
        for f in STAGE_FIELDS[stage]:
            if src[f] is not None:
                out["%s_%s%d" % (base, f, k)] = str(src[f])
    return out


def run(bank, workflows, case_id, bundles, case=None, skip_initial_code=False):
    case = case or CASES[case_id]
    wf = workflows["B" if case.get("brief") == "B" else "A"]
    session = open_bank_session(bank, customer=case)
    assert session.get("ok"), session
    variables = dict(session["variables"])
    sim = Simulator(wf, variables=variables, skip_initial_code=skip_initial_code)
    sim.start()
    for b in bundles:
        if sim.ended:
            break
        sim.turn({"say": json.dumps(b), "extract": extract_for(sim.current, b)})
    rec = sim.record()
    errors = [e for e in rec["events"] if e["event"] == "error"]
    assert not errors, errors[:3]
    assert not rec["warnings"], rec["warnings"][:3]
    return rec, bank_ledger(bank, variables["customer_id"])


def check(bank, workflows, case_id, bundles, case=None, expected=None):
    case = case or CASES[case_id]
    expected = expected or case["expected"]
    rec, led = run(bank, workflows, case_id, bundles, case=case)
    got = {"outcome": led["outcome"], "reason": led["reason"],
           "promises": [(p["product_id"], float(p["amount"]), p["date"]) for p in led["promises"]],
           "notes": [(n["product_id"], n["reason"]) for n in led["notes"]],
           "callbacks": [(c["date"], c["time"]) for c in led["callbacks"]],
           "transfers": [t["queue"] for t in led["transfers"]]}
    want = {"outcome": expected["outcome"], "reason": expected["reason"],
            "promises": [(p["product_id"], float(p["amount"]), p["date"]) for p in expected["promises"]],
            "notes": [(n["product_id"], n["reason"]) for n in expected["notes"]],
            "callbacks": [(c["date"], c["time"]) for c in expected["callbacks"]],
            "transfers": [t["queue"] for t in expected["transfers"]]}
    trail = "\n".join("%s [%s] %s" % (t["role"], t["node"], t["text"][:160]) for t in rec["transcript"])
    assert got == want, "%s\n%s" % (case_id, trail)
    tools = [c["tool"] for c in led["calls"]]
    assert tools.count("close_call") == 1 and tools[-1] == "close_call", tools
    assert rec["ended"] and rec["ended_reason"] == "call_closed", rec["ended_reason"]
    for t in rec["transcript"]:
        assert "{{" not in t["text"], t
    return rec, led


SCENARIOS = {
    # the 13 public cases
    "PUB-01": lambda c: verified(c) + [[E("pay_today_yes")], [E("confirm")]],
    "PUB-02": lambda c: [[E("party_other"), E("question_back")], [E("callback_offer", date="tomorrow", time="around eleven in the morning")]],
    "PUB-03": lambda c: [[E("party_confirmed")], [E("id_answer", text="12 July 1991")], [E("id_answer", text="21 August 1992")],
                         [E("id_answer", text="21 July 1990")]],
    "PUB-04": lambda c: verified(c) + [[E("date_proposal", date="6 November"), E("robot_question")], [E("accept_offer")], [E("confirm")]],
    "PUB-05": lambda c: verified(c) + [[E("hardship"), E("other")], [E("refuse")]],
    "PUB-06": lambda c: verified(c) + [[E("too_much")], [E("accept_offer", date="this Friday")], [E("confirm")]],
    "PUB-07": lambda c: verified(c) + [[E("pay_today_no"), E("vague_period", date="the week after next")],
                                       [E("date_proposal", date="Monday the 26th")], [E("accept_offer")], [E("confirm")]],
    "PUB-08": lambda c: verified(c) + [[E("paid")]],
    "PUB-09": lambda c: verified(c) + [[E("plan_request")]],
    "PUB-10": lambda c: verified(c) + [[E("pay_today_no"), E("date_proposal", date="this Friday")], [E("confirm")]],
    "PUB-11": lambda c: verified(c) + [[E("pay_today_no"), E("date_proposal", date="this Friday")], [E("confirm")]],
    "PUB-12": lambda c: [[E("party_confirmed")], [E("id_answer", text="19 October 1983")], [E("id_answer", text="4401")],
                         [E("id_answer", text="4410")], [E("date_proposal", item="p1", date="tomorrow")], [E("refuse")], [E("refuse")],
                         [E("refuse")], [E("confirm")]],
    "PUB-13": lambda c: verified(c) + [[E("pay_today_no"), E("date_proposal", date="30 October")], [E("confirm")]],
    # extended: opening and third party
    "EXT-002": lambda c: [[E("other", text="Hello?")], [E("other", text="Go ahead.")]],
    "EXT-008": lambda c: [[E("party_other")], [E("callback_offer", date="today", time="4 pm")]],
    "EXT-010": lambda c: [[E("party_other")], [E("callback_offer", date="this evening", time="9 pm")],
                          [E("callback_offer", date="tomorrow", time="around 2 pm")]],
    "EXT-012": lambda c: [[E("party_wrong_number")]],
    "EXT-013": lambda c: [[E("party_other"), E("party_deceased")]],
    # identity
    "EXT-024": lambda c: [[E("party_confirmed")], [E("id_answer", text="11 2 1979")], [E("id_answer", text="the second of November 1979")],
                          [E("id_answer", text="0358")], [E("date_proposal", date="Monday 19 October")], [E("confirm")]],
    "EXT-031": lambda c: [[E("party_confirmed")], [E("id_decline")], [E("id_decline")]],
    "EXT-133": lambda c: [[E("party_confirmed")], [E("id_answer", text="2 November")], [E("id_answer", text="1979")],
                          [E("id_answer", text="03")], [E("id_answer", text="58")], [E("date_proposal", date="Friday 16 October")], [E("confirm")]],
    # dates, amounts, persuasion
    "EXT-044": lambda c: verified(c) + [[E("pay_today_no"), E("date_proposal", date="Saturday 17 October")], [E("accept_offer")], [E("confirm")]],
    "EXT-052": lambda c: verified(c) + [[E("pay_today_no"), E("vague_period", date="next week")],
                                        [E("date_proposal", date="Wednesday 21 October")], [E("confirm")]],
    "EXT-060": lambda c: verified(c) + [[E("pay_today_no"), E("date_proposal", date="6 November")], [E("refuse")], [E("refuse")],
                                        [E("accept_offer")], [E("confirm")]],
    "EXT-067": lambda c: verified(c) + [[E("amount_proposal", amount=300, date="Friday 16 October")], [E("accept_offer")], [E("confirm")]],
    "EXT-078": lambda c: verified(c) + [[E("refuse")], [E("refuse")], [E("refuse")]],
    # situations
    "EXT-081": lambda c: verified(c) + [[E("hardship")], [E("accept_offer")]],
    "EXT-083": lambda c: verified(c) + [[E("hardship")], [E("refuse")]],
    "EXT-085": lambda c: verified(c) + [[E("paid")]],
    "EXT-094": lambda c: verified(c) + [[E("human")], [E("human")]],
    "EXT-095": lambda c: [[E("party_confirmed")], [E("human")], [E("human")]],
    # read-back and tool failure
    "EXT-099": lambda c: verified(c) + [[E("pay_today_yes")], [E("change", date="Friday the 16th")], [E("confirm")]],
    "EXT-104": lambda c: verified(c) + [[E("pay_today_yes")], [E("confirm")], [E("change", date="next week")]],
    # multi-product (Brief B)
    "EXT-108": lambda c: verified(c) + [[E("pay_today_yes")], [E("confirm")]],
    "EXT-111": lambda c: verified(c) + [[E("pay_today_yes", item="p1"), E("dispute", item="p2")], [E("confirm")]],
    "EXT-115": lambda c: verified(c) + [[E("refuse")]] * 7,
    "EXT-121": lambda c: verified(c) + [[E("hardship")], [E("refuse")]],
    "EXT-122": lambda c: verified(c) + [[E("pay_today_no"), E("amount_proposal", item="p1", amount=200, date="Friday 16 October"),
                                         E("amount_proposal", item="p2", amount=440, date="Friday 16 October"),
                                         E("amount_proposal", item="p3", amount=30, date="Friday 16 October")],
                                        [E("accept_offer", item="p3")], [E("confirm")]],
    "EXT-127": lambda c: verified(c) + [[E("paid", item="p1"), E("paid", item="p2"), E("dispute", item="p3")]],
}


@pytest.mark.parametrize("case_id", sorted(SCENARIOS))
def test_scenario_ledger(bank, workflows, case_id):
    check(bank, workflows, case_id, SCENARIOS[case_id](CASES[case_id]))


def test_promise_fails_twice_brief_a(bank, workflows):
    case = json.loads(json.dumps(PUBLIC["PUB-10"]))
    case["id"] = "FAIL2-A"
    case["faults"] = [{"tool": "create_promise", "fail_first_n": 2}]
    expected = {"outcome": "no_promise", "reason": "service_error", "promises": [], "notes": [], "callbacks": [], "transfers": []}
    rec, led = check(bank, workflows, "FAIL2-A", verified(case) + [[E("pay_today_yes")], [E("confirm")]], case=case, expected=expected)
    assert [c["tool"] for c in led["calls"]].count("create_promise") == 2
    assert "could not record" in rec["transcript_text"]


def test_items_named_in_words_map_to_products(bank, workflows):
    """The extraction reports a product in the customer's words; the dispatcher maps it with the engine's items."""
    case = EXTENDED["EXT-111"]
    types = [p["type"] for p in case["products"]]
    assert types[0] == "credit_card" and types[1] != "credit_card"
    words2 = "the " + types[1].replace("_", " ")
    check(bank, workflows, "EXT-111", verified(case) + [[E("pay_today_yes", item="the card"), E("dispute", item=words2)], [E("confirm")]])


def test_unreadable_extraction_does_not_break_the_call(bank, workflows):
    """A slot value outside the event vocabulary becomes `other`; the call continues and still closes cleanly."""
    case = PUBLIC["PUB-01"]
    bundles = verified(case)[:1] + [[E("mumble")]] + verified(case)[1:] + [[E("pay_today_yes")], [E("confirm")]]
    session = open_bank_session(bank, customer=case)
    sim = Simulator(workflows["A"], variables=dict(session["variables"]))
    sim.start()
    for b in bundles:
        values = extract_for(sim.current, b)
        if b[0]["kind"] == "mumble":
            # the extraction model's enum check would reject it; emulate a value that slipped through
            sim.table[sim.current.rsplit("_", 1)[0] + "_reply1"] = "mumble"
            sim.turn({"say": "mmm"})
            continue
        sim.turn({"say": "x", "extract": values})
    led2 = bank_ledger(bank, session["variables"]["customer_id"])
    assert led2["outcome"] == "promise"


def test_chat_route_without_setup(bank, workflows):
    """The chat route may skip the initial code node: the engine seeds itself and the call still closes cleanly."""
    case = PUBLIC["PUB-10"]
    rec, led = run(bank, workflows, "PUB-10", SCENARIOS["PUB-10"](case), skip_initial_code=True)
    assert led["outcome"] == case["expected"]["outcome"] and len(led["promises"]) == 1



def test_dispatcher_pairs_a_reply_with_the_words_filed_under_another_slot(workflows):
    """Seen on the platform 2026-10-10: identity_reply1 = id_answer, identity_words1 empty, identity_words2 = 4471.
    The dispatcher gives the reply the orphan words; a value next to its own reply stays where it is."""
    code = workflows["A"]["nodes"]["identity_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    v = {"identity_reply1": "id_answer", "identity_words1": "", "identity_reply2": "", "identity_words2": "4471", "engine_state": ""}
    exec(code, {"vars": v})
    evs = json.loads(v["engine_events"])
    assert [(e["kind"], e["text"]) for e in evs] == [("id_answer", "4471")]
    assert v["identity_words2"] == "" and v["identity_reply1"] == ""
    v = {"identity_reply1": "id_answer", "identity_words1": "14 March 1988", "identity_reply2": "question_back",
         "identity_words2": "why do you need that", "engine_state": ""}
    exec(code, {"vars": v})
    assert [(e["kind"], e["text"]) for e in json.loads(v["engine_events"])] == [("id_answer", "14 March 1988"), ("question_back", "why do you need that")]



def test_close_tts_speaks_sentences_not_instructions(bank, workflows):
    """Seen on the platform 2026-10-10 (PUB-02): the close node's tts read "Thank the customer and say goodbye." At a
    close the engine's content lines are instructions; the tts says their sentence form, or nothing, plus one goodbye."""
    case = PUBLIC["PUB-02"]
    rec, led = run(bank, workflows, "PUB-02", [[E("party_other")], [E("callback_offer", date="tomorrow", time="around eleven")]])
    closing = [t["text"] for t in rec["transcript"] if t["role"] == "assistant" and t["node"].startswith("close_")]
    assert closing and all("customer" not in c.lower() and "say goodbye" not in c.lower() for c in closing), closing
    assert closing[-1].lower().count("goodbye") == 1
    assert led["outcome"] == "not_reached" and led["reason"] == "callback"


def test_dispatcher_drops_product_words_that_match_no_product(workflows):
    """Platform EXT-006 (2026-10-10): negotiate_item1 = "the full amount" went through as an item id, the engine found no
    such item and dropped the pay-today-yes. Words that match no product mean no item."""
    code = workflows["A"]["nodes"]["negotiate_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    state = json.dumps({"items": [{"item_id": "p1", "product": {"type": "personal_loan"}}]})
    v = {"negotiate_reply1": "pay_today_yes", "negotiate_item1": "the full amount", "negotiate_amount1": "780",
         "negotiate_date1": "today", "negotiate_words1": "I can pay the full amount today.", "engine_state": state}
    exec(code, {"vars": v})
    evs = json.loads(v["engine_events"])
    assert len(evs) == 1 and evs[0]["kind"] == "pay_today_yes" and evs[0]["item"] is None and evs[0]["amount"] == 780.0
    v = {"negotiate_reply1": "date_proposal", "negotiate_item1": "the loan", "negotiate_date1": "Friday", "engine_state": state}
    exec(code, {"vars": v})
    assert json.loads(v["engine_events"])[0]["item"] == "p1"


def test_dispatcher_hands_a_goodbye_to_the_engine_and_the_call_closes(bank, workflows):
    """Platform EXT-023 (2026-10-10): "Thank you, goodbye." twenty times while the engine still waited for the
    pay-today answer. The dispatcher files it as other (or dont_want_to_talk) with the words; the engine closes."""
    code = workflows["A"]["nodes"]["negotiate_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    for reply in ("other", "dont_want_to_talk", "something_else"):
        v = {"negotiate_reply1": reply, "negotiate_words1": "Thank you, goodbye.", "engine_state": ""}
        exec(code, {"vars": v})
        evs = json.loads(v["engine_events"])
        assert len(evs) == 1 and evs[0]["kind"] in ("other", "dont_want_to_talk") and evs[0]["text"] == "Thank you, goodbye."
    case = PUBLIC["PUB-01"]
    expected = {"outcome": "no_promise", "reason": "refused", "promises": [], "notes": [], "callbacks": [], "transfers": []}
    rec, led = check(bank, workflows, "PUB-01", verified(case) + [[E("other", text="Thank you, goodbye.")]], expected=expected)
    assert sum(1 for t in rec["transcript"] if t["role"] == "assistant" and "goodbye" in t["text"].lower()) == 1


def test_readback_restated_in_other_words_is_recorded_once(bank, workflows):
    case = PUBLIC["PUB-01"]
    rec, led = check(bank, workflows, "PUB-01", verified(case) + [[E("pay_today_yes")], [E("change", date="today", amount=420)]])
    assert len(led["promises"]) == 1
    assert sum(1 for t in rec["transcript"] if t["role"] == "assistant" and t["node"] == "readback") == 1


def test_dispatcher_falls_back_to_the_whole_message_when_words_are_missing(workflows):
    """Platform PUB-03 flake and EXT-027 (2026-10-11): the extractor filled identity_reply1 = id_answer but no words, the
    answer never reached the bank. The schema now also asks for the whole message (identity_raw); the dispatcher uses it
    for the one reply of the turn that has nothing attached."""
    wf = workflows["A"]
    schema = wf["nodes"]["identity"]["extraction_schema"]
    assert any(f["name"] == "identity_raw" for f in schema)
    code = wf["nodes"]["identity_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    v = {"identity_reply1": "id_answer", "identity_words1": "", "identity_raw": "21 August 1992.", "engine_state": ""}
    exec(code, {"vars": v})
    assert json.loads(v["engine_events"])[0]["text"] == "21 August 1992."
    assert v["identity_raw"] == ""   # cleared with the slots
    v = {"identity_reply1": "id_answer", "identity_words1": "", "identity_reply2": "question_back", "identity_raw": "8864. How much do I owe?", "engine_state": ""}
    exec(code, {"vars": v})
    assert json.loads(v["engine_events"])[0]["text"] is None   # two replies: the whole message is not one answer


SYNTH = ROOT / "synthetic"


@pytest.mark.parametrize("letter", ["C", "D", "E", "F", "G", "J"])
def test_emit_handles_an_api_with_other_field_names(letter):
    """The organisers keep the seven tool names; fields and allowed values change (README, "The final"). Synthetic briefs
    C and D (frozen tables from the night's reads) have question/pay_date/callback_date/client_ref and other response
    names; the emitter must map them, not raise."""
    table_path = ROOT / "runs" / "synthetic" / ("build-%s" % letter) / "read" / "table.json"
    if not table_path.exists():
        pytest.skip("no frozen table for %s" % letter)
    from builder.readers.api_file import parse_api
    api_raw = json.load(open(SYNTH / letter / "api.json"))
    api = parse_api(api_raw)
    table = json.load(open(table_path))
    wf = emit(table, api)
    assert walk(wf, table, api_raw) == []
    verify = wf["nodes"]["w_verify_identity"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]
    cid = {"C": "client_ref", "F": "client_ref", "G": "customer_ref", "J": "account_no"}.get(letter, "customer_id")
    assert verify[cid]["default"] in ("{{customer_id}}", "{{%s}}" % cid)
    if letter in ("C", "D"):
        assert verify["question"]["default"].startswith("{{wa_verify_identity__question")
    if letter == "F":   # one question, the answer field is named after it, no question field is sent
        assert set(verify) == {"client_ref", "birth_date"}
    if letter == "E":   # a required enum the engine never fills gets a fixed neutral value
        cb = wf["nodes"]["w_schedule_callback"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]
        assert cb["reason"]["default"] == "unavailable"
    if cid != "customer_id":   # the setup node makes both names carry the id, whichever the call variables bring
        values = {"customer_id": "actual-member", cid: "test"}
        code = wf["nodes"]["setup"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        exec(code, {"vars": values})
        assert values[cid] == values["customer_id"] == "actual-member"


def test_write_result_adds_canonical_response_names():
    """Brief J's API answers passed/wrong_total/all_passed and lists debts with kind/amount_due/days_overdue/minimum;
    the write_result node gives the engine verified/wrong_count/all_verified and products[].type/past_due/days_late."""
    from builder.readers.api_file import parse_api
    from builder.emitter.emit import Ctx
    from builder.emitter import fragments as F
    api = parse_api(json.load(open(SYNTH / "J" / "api.json")))
    ctx = Ctx(TABLE_A, api, "https://x")
    code = F.write_result(ctx).nodes["write_result"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    v = {"write_tool": "verify_identity", "wr_body": json.dumps({"ok": True, "passed": False, "wrong_total": 2, "all_passed": False})}
    exec(code, {"vars": v})
    d = json.loads(v["engine_events"])[0]["data"]
    assert d["verified"] is False and d["wrong_count"] == 2 and d["all_verified"] is False
    v = {"write_tool": "get_account", "wr_body": json.dumps({"ok": True, "debts": [{"product_id": "p1", "kind": "credit_card", "amount_due": 95.5, "days_overdue": 4, "minimum": 30}]})}
    exec(code, {"vars": v})
    p = json.loads(v["engine_events"])[0]["data"]["products"][0]
    assert p["type"] == "credit_card" and p["past_due"] == 95.5 and p["days_late"] == 4 and p["minimum_payment"] == 30


def test_dispatcher_two_products_in_one_reply_filed_positionally(workflows):
    """Platform B EXT-124 and EXT-127 (2026-10-11): one value slot per product, but the reply slots filled positionally:
    slot 2's reply ('paid' / 'dispute') sat on the second product's values while its own words were in slot 3 without a
    reply. The reply slot whose words duplicate slot 1's takes the orphan's values; the orphan with slot 1's words is a
    second product of slot 1's reply."""
    code = workflows["B"]["nodes"]["negotiate_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    state = json.dumps({"items": [{"item_id": "p1", "product": {"type": "credit_card", "card_last4": "2288"}},
                                  {"item_id": "p2", "product": {"type": "personal_loan"}}, {"item_id": "p3", "product": {"type": "car_loan"}}]})
    w1 = "I can pay the credit card and the car loan in full today"
    v = {"negotiate_reply1": "pay_today_yes", "negotiate_item1": "the credit card", "negotiate_date1": "today", "negotiate_words1": w1,
         "negotiate_reply2": "paid", "negotiate_item2": "the car loan", "negotiate_date2": "today", "negotiate_words2": w1,
         "negotiate_item3": "The personal loan", "negotiate_date3": "last week", "negotiate_words3": "The personal loan was paid last week",
         "negotiate_raw": w1 + ". The personal loan was paid last week.", "engine_state": state}
    exec(code, {"vars": v})
    evs = json.loads(v["engine_events"])
    assert sorted((e["kind"], e["item"]) for e in evs) == [("paid", "p2"), ("pay_today_yes", "p1"), ("pay_today_yes", "p3")], evs
    w1 = "I paid the credit card and the personal loan yesterday"
    v = {"negotiate_reply1": "paid", "negotiate_item1": "the credit card", "negotiate_date1": "yesterday", "negotiate_words1": w1,
         "negotiate_reply2": "dispute", "negotiate_item2": "the personal loan", "negotiate_date2": "yesterday", "negotiate_words2": w1,
         "negotiate_item3": "a car loan", "negotiate_words3": "I have never had a car loan with Freya Bank", "engine_state": state}
    exec(code, {"vars": v})
    evs = json.loads(v["engine_events"])
    assert sorted((e["kind"], e["item"]) for e in evs) == [("dispute", "p3"), ("paid", "p1"), ("paid", "p2")], evs
    # the ordinary case is untouched: three replies with their own words
    v = {"negotiate_reply1": "pay_today_no", "negotiate_words1": "no", "negotiate_reply2": "amount_proposal", "negotiate_item2": "the credit card",
         "negotiate_amount2": "200", "negotiate_words2": "200 on the credit card", "engine_state": state}
    exec(code, {"vars": v})
    assert [(e["kind"], e["item"], e["amount"]) for e in json.loads(v["engine_events"])] == [("pay_today_no", None, None), ("amount_proposal", "p1", 200.0)]


def test_dispatcher_reads_an_amount_with_a_full_width_comma(workflows):
    """Platform 2026-10-11 (EXT-068/102/153, B EXT-116): negotiate_amount1 = '，100' (U+FF0C in front), float() failed and
    the amount was lost."""
    code = workflows["A"]["nodes"]["negotiate_observe"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    v = {"negotiate_reply1": "amount_proposal", "negotiate_amount1": "，125.99", "negotiate_date1": "today",
         "negotiate_words1": "I can pay 125.99 today.", "engine_state": ""}
    exec(code, {"vars": v})
    assert json.loads(v["engine_events"])[0]["amount"] == 125.99


def test_callback_stage_hears_the_customer_confirming(bank, workflows):
    """Platform EXT-138 (2026-10-11): after a first answer taken as someone else, 'Fine, yes, this is Victor Ionescu'
    could only be 'other' in the callback stage. The stage now extracts party_confirmed, with its own description."""
    wf = workflows["A"]
    schema = {f["name"]: f for f in wf["nodes"]["callback"]["extraction_schema"]}
    assert "party_confirmed" in schema["callback_reply1"]["enum_values"]
    assert "by their own name" in schema["callback_reply1"]["description"]
    case = EXTENDED["EXT-138"]
    bundles = [[E("party_other", text="This is Freya Bank IT.")], [E("party_confirmed", text="Fine, yes, this is Victor Ionescu.")],
               [E("id_answer", text=case["identity"]["date_of_birth"])], [E("id_answer", text=case["identity"]["phone_last4"])],
               [E("date_proposal", date="Friday 16 October")], [E("confirm")]]
    rec, led = check(bank, workflows, "EXT-138", bundles)
    assert len(led["promises"]) == 1 and led["callbacks"] == []
