"""Fixture support of our bank: custom customers, faults, profile switches, and profiles built from a tool API file."""
import copy, json, pathlib, sys, time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bank import replay  # noqa: E402
from bank.adapters import profile_from_openapi  # noqa: E402

OPENAPI = json.load(open(ROOT / "kit" / "build-the-builder" / "tools" / "openapi.json"))


@pytest.fixture(scope="module")
def base():
    srv, url = replay.start_server()
    yield url
    srv.shutdown()


def customer(**over):
    c = {"id": "EXT-001", "variables": {"first_name": "Ada", "last_name": "Byron", "title": "Ms", "now": "2026-12-24T18:30"},
         "identity": {"date_of_birth": "1975-12-05", "phone_last4": "6630"},
         "products": [{"type": "credit_card", "card_last4": "1111", "past_due": 420.0, "days_late": 6, "minimum_payment": 126.0},
                      {"product_id": "loan", "type": "personal_loan", "past_due": 1320.5, "days_late": 16, "instalment_amount": 440.0}]}
    c.update(over)
    return c


def open_session(base, spec):
    status, r = replay.http(base, "/v1/practice/sessions", {"customer": spec})
    assert status == 200 and r["ok"], r
    return r["variables"]["customer_id"]


def call(base, tool, cid, **body):
    return replay.http(base, "/v1/" + tool, {"customer_id": cid, **body})


def ledger(base, cid):
    status, led = replay.http(base, "/v1/practice/ledger/" + cid)
    assert status == 200, led
    return led


def verify_both(base, cid):
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="5 December 1975")[1]["verified"]
    assert call(base, "verify_identity", cid, field="phone_last4", answer="6630")[1]["all_verified"]


# ---- custom customers --------------------------------------------------------------------------------------

def test_custom_customer_any_date_products_and_identity(base):
    spec = customer(identity={"policy_number": "AB-12 34", "birth_year": "1975"})
    cid = open_session(base, spec)
    status, r = call(base, "verify_identity", cid, field="date_of_birth", answer="1975-12-05")
    assert r == {"ok": False, "error": "field must be policy_number or birth_year"}
    assert call(base, "verify_identity", cid, field="policy_number", answer="ab1234")[1]["verified"]       # text: case and spaces ignored
    assert call(base, "verify_identity", cid, field="birth_year", answer="19 75")[1]["all_verified"]       # digits: non-digits stripped
    status, r = call(base, "get_account", cid)
    assert r["products"][0] == {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": 420, "days_late": 6, "minimum_payment": 126}
    assert r["products"][1]["product_id"] == "loan" and r["products"][1]["past_due"] == 1320.5
    assert call(base, "create_promise", cid, product_id="loan", amount="1320.5", date="2027-01-04")[1] == {"ok": True, "promise_id": "pr1"}
    assert call(base, "create_promise", cid, product_id="p1", amount=126, date="2026-12-31")[1] == {"ok": True, "promise_id": "pr2"}
    assert call(base, "close_call", cid, outcome="promise")[1] == {"ok": True}
    led = ledger(base, cid)
    assert led["case"] == "EXT-001" and led["now"] == "2026-12-24T18:30"
    assert led["verified"] == {"policy_number": True, "birth_year": True}
    assert [p["amount"] for p in led["promises"]] == [1320.5, 126]
    assert led["outcome"] == "promise" and led["reason"] is None
    assert [c["tool"] for c in led["calls"]][-1] == "close_call" and "customer_id" not in led["calls"][0]["args"]
    assert list(led.keys()) == ["ok", "case", "team", "now", "verified", "wrong", "hinted", "promises", "notes", "callbacks", "transfers", "outcome", "reason", "failures", "calls", "last_at"]


def test_unknown_case_and_kit_case(base):
    status, r = replay.http(base, "/v1/practice/sessions", {"case": "PUB-99"})
    assert status == 404 and r["ok"] is False
    status, r = replay.http(base, "/v1/practice/sessions", {"case": "PUB-10"})
    assert status == 200 and r["variables"]["first_name"] == "Grace"


# ---- faults --------------------------------------------------------------------------------------------------

def test_fault_fail_first_n(base):
    cid = open_session(base, customer(faults=[{"tool": "create_promise", "fail_first_n": 2}]))
    verify_both(base, cid)
    for _ in range(2):
        status, r = call(base, "create_promise", cid, product_id="p1", amount=1, date="2026-12-24")
        assert (status, r) == (500, {"ok": False, "error": "service unavailable, nothing was recorded"})
    assert call(base, "create_promise", cid, product_id="p1", amount=1, date="2026-12-24")[1] == {"ok": True, "promise_id": "pr1"}
    led = ledger(base, cid)
    assert led["failures"] == {"verify_identity": 0, "create_promise": 2} and len(led["promises"]) == 1
    assert [c["status"] for c in led["calls"]] == [200, 200, 500, 500, 200]


def test_fault_fail_on_call(base):
    cid = open_session(base, customer(faults=[{"tool": "add_note", "fail_on_call": 2}]))
    assert call(base, "add_note", cid, product_id="p1", reason="refused")[0] == 200
    assert call(base, "add_note", cid, product_id="p1", reason="refused")[0] == 500
    assert call(base, "add_note", cid, product_id="p1", reason="refused")[0] == 200
    assert ledger(base, cid)["failures"] == {"add_note": 1}


def test_fault_before_validation_and_after_close(base):
    cid = open_session(base, customer(faults=[{"tool": "transfer_to_agent", "fail_first_n": 1}]))
    assert call(base, "transfer_to_agent", cid, queue="nope")[0] == 500           # fault first, validation never runs
    assert call(base, "transfer_to_agent", cid, queue="nope")[1] == {"ok": False, "error": "unknown queue"}
    assert call(base, "close_call", cid, outcome="not_reached", reason="unclear")[1] == {"ok": True}
    assert call(base, "transfer_to_agent", cid, queue="general")[1] == {"ok": False, "error": "the call is already closed"}


def test_fault_slow_ms(base):
    cid = open_session(base, customer(faults=[{"tool": "get_account", "slow_ms": 600, "on_call": 1}]))
    verify_both(base, cid)
    t0 = time.time(); status, r = call(base, "get_account", cid); slow = time.time() - t0
    assert status == 200 and r["ok"] and slow >= 0.55
    t0 = time.time(); call(base, "get_account", cid); fast = time.time() - t0
    assert fast < 0.3
    assert ledger(base, cid)["failures"] == {"verify_identity": 0, "get_account": 0}


def test_slow_call_times_out_for_the_client(base):
    cid = open_session(base, customer(faults=[{"tool": "close_call", "slow_ms": 1500}]))
    with pytest.raises(Exception):
        replay.http(base, "/v1/close_call", {"customer_id": cid, "outcome": "promise"}, timeout=0.3)
    time.sleep(1.5)
    assert ledger(base, cid)["outcome"] == "promise"       # the bank still wrote it: the client's "unknown" result class


# ---- profile switches ----------------------------------------------------------------------------------------

def test_profile_defaults_match_recorded_behaviour(base):
    cid = open_session(base, customer())
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="1975-05-12")[1] == {"ok": True, "verified": False, "wrong_answers_left": 3, "hint": "day_month_swapped"}
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="1975-05-12")[1] == {"ok": True, "verified": False, "wrong_answers_left": 2, "all_verified": False}
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="1975-12-05")[1]["verified"]
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="x")[1] == {"ok": True, "verified": True, "wrong_answers_left": 2}
    assert call(base, "add_note", cid, product_id="zzz", reason="refused")[1] == {"ok": True}
    assert call(base, "close_call", cid, outcome="promise", reason="")[1] == {"ok": False, "error": "this outcome needs one of these reasons: "}
    assert call(base, "close_call", cid, outcome="paid", reason="refused")[1]["ok"] is False
    assert call(base, "close_call", cid, outcome="paid")[1] == {"ok": True}


def test_profile_switches_off(base):
    profile = {"hint_once": False, "passed_field_omits_all_verified": False, "note_product_unchecked": False, "reason_rejected_on_reasonless": False, "max_wrong": 2}
    cid = open_session(base, customer(profile=profile))
    for _ in range(2):      # hint every time, never counted
        assert call(base, "verify_identity", cid, field="date_of_birth", answer="1975-05-12")[1] == {"ok": True, "verified": False, "wrong_answers_left": 2, "hint": "day_month_swapped"}
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="1975-12-05")[1]["verified"]
    assert call(base, "verify_identity", cid, field="date_of_birth", answer="x")[1] == {"ok": True, "verified": True, "wrong_answers_left": 2, "all_verified": False}
    assert call(base, "verify_identity", cid, field="phone_last4", answer="0000")[1]["wrong_answers_left"] == 1
    assert call(base, "verify_identity", cid, field="phone_last4", answer="0001")[1]["wrong_answers_left"] == 0
    assert call(base, "verify_identity", cid, field="phone_last4", answer="6630")[1] == {"ok": False, "verified": False, "wrong_answers_left": 0, "error": "identity check is over"}
    assert call(base, "add_note", cid, product_id="zzz", reason="refused")[1] == {"ok": False, "error": "unknown product_id"}
    assert call(base, "add_note", cid, product_id="loan", reason="refused")[1] == {"ok": True}
    assert call(base, "close_call", cid, outcome="paid", reason="refused")[1] == {"ok": True}
    led = ledger(base, cid)
    assert led["outcome"] == "paid" and led["reason"] is None and led["wrong"] == 2 and led["hinted"] is True


def test_profile_enums_and_any_reason(base):
    profile = {"note_reasons": ["lapsed"], "queues": ["claims"], "outcome_reasons": {"settled": [], "escalated": "any", "dropped": ["no_answer"]}}
    cid = open_session(base, customer(profile=profile))
    assert call(base, "add_note", cid, reason="refused")[1] == {"ok": False, "error": "unknown reason"}
    assert call(base, "add_note", cid, reason="lapsed")[1] == {"ok": True}
    assert call(base, "transfer_to_agent", cid, queue="general")[1] == {"ok": False, "error": "unknown queue"}
    assert call(base, "transfer_to_agent", cid, queue="claims")[1] == {"ok": True}
    assert call(base, "close_call", cid, outcome="promise")[1] == {"ok": False, "error": "unknown outcome"}
    assert call(base, "close_call", cid, outcome="escalated")[1] == {"ok": False, "error": "this outcome needs a reason"}
    assert call(base, "close_call", cid, outcome="dropped", reason="busy")[1] == {"ok": False, "error": "this outcome needs one of these reasons: no_answer"}
    assert call(base, "close_call", cid, outcome="escalated", reason="anything at all")[1] == {"ok": True}
    assert ledger(base, cid)["reason"] == "anything at all"


# ---- profiles from a tool API file ---------------------------------------------------------------------------

def test_adapter_on_the_kit_openapi_matches_defaults():
    p = profile_from_openapi(OPENAPI)
    assert p["customer_id_field"] == "customer_id"
    assert p["tools"] == {t: t for t in ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")}
    assert all(c == w for fm in p["fields"].values() for c, w in fm.items())
    assert p["identity_types"] == {"date_of_birth": "date", "phone_last4": "digits"}
    assert p["note_reasons"] == ["refused", "hardship", "dispute", "paid", "service_error"]
    assert p["queues"] == ["restructuring", "general", "support"]
    assert p["outcome_reasons"] == {"promise": [], "paid": [], "transferred": "any", "no_promise": "any", "not_verified": "any", "not_reached": "any"}
    table = {"no_promise": ["refused"], "transferred": ["support"]}
    assert profile_from_openapi(OPENAPI, outcome_reasons=table)["outcome_reasons"]["no_promise"] == ["refused"]


def renamed_openapi():
    """The kit's API with an insurance flavour: other tool names, other field names, other enums."""
    doc = copy.deepcopy(OPENAPI)
    paths = doc["paths"]
    def move(old, new):
        paths[new] = paths.pop(old)
    def props(path): return paths[path]["post"]["requestBody"]["content"]["application/json"]["schema"]
    move("/verify_identity", "/check_identity"); move("/create_promise", "/record_promise"); move("/close_call", "/end_call")
    s = props("/check_identity"); s["properties"]["question"] = s["properties"].pop("field"); s["properties"]["question"]["enum"] = ["policy_number", "date_of_birth"]
    s["properties"]["answer"]["description"] = "For date_of_birth: the date as YYYY-MM-DD. For policy_number: letters and digits."
    s["required"] = ["customer_id", "question", "answer"]
    s = props("/record_promise"); s["properties"]["promise_amount"] = s["properties"].pop("amount"); s["properties"]["promise_date"] = s["properties"].pop("date")
    s["required"] = ["customer_id", "product_id", "promise_amount", "promise_date"]
    s = props("/end_call"); s["properties"]["outcome"]["enum"] = ["settled", "promise", "lapsed"]; s["properties"]["reason"]["description"] = "Required for every outcome except promise."
    s = props("/transfer_to_agent"); s["properties"]["queue"]["enum"] = ["claims", "support"]
    return doc


def test_adapter_renamed_fields_served(base):
    p = profile_from_openapi(renamed_openapi(), outcome_reasons={"lapsed": ["no_contact", "refused"]})
    assert p["tools"]["verify_identity"] == "check_identity" and p["tools"]["create_promise"] == "record_promise" and p["tools"]["close_call"] == "end_call"
    assert p["fields"]["verify_identity"] == {"field": "question", "answer": "answer"}
    assert p["fields"]["create_promise"] == {"product_id": "product_id", "amount": "promise_amount", "date": "promise_date"}
    assert p["identity_types"] == {"policy_number": "text", "date_of_birth": "date"}
    assert p["outcome_reasons"] == {"settled": "any", "promise": [], "lapsed": ["no_contact", "refused"]}
    assert p["queues"] == ["claims", "support"]
    cid = open_session(base, customer(identity={"policy_number": "PN-77-X", "date_of_birth": "1975-12-05"}, profile=p))
    status, r = call(base, "check_identity", cid, question="phone_last4", answer="1")
    assert r == {"ok": False, "error": "question must be policy_number or date_of_birth"}
    assert call(base, "check_identity", cid, question="policy_number", answer="pn77x")[1] == {"ok": True, "verified": True, "wrong_answers_left": 3, "all_verified": False}
    assert call(base, "check_identity", cid, question="date_of_birth", answer="12/05/1975")[1]["hint"] == "day_month_swapped"
    assert call(base, "check_identity", cid, question="date_of_birth", answer="05/12/1975")[1]["all_verified"] is True
    assert call(base, "get_account", cid)[1]["ok"]
    assert call(base, "record_promise", cid, product_id="p1", promise_amount="420", promise_date="24 December")[1] == {"ok": False, "error": "promise_date must be YYYY-MM-DD"}
    assert call(base, "record_promise", cid, product_id="p1", promise_amount=420, promise_date="2026-12-24")[1] == {"ok": True, "promise_id": "pr1"}
    assert call(base, "transfer_to_agent", cid, queue="general")[1] == {"ok": False, "error": "unknown queue"}
    assert call(base, "end_call", cid, outcome="lapsed", reason="busy")[1] == {"ok": False, "error": "this outcome needs one of these reasons: no_contact, refused"}
    assert call(base, "end_call", cid, outcome="promise", reason="x")[1]["ok"] is False
    assert call(base, "end_call", cid, outcome="promise")[1] == {"ok": True}
    assert call(base, "record_promise", cid, product_id="p1", promise_amount=1, promise_date="2026-12-24")[1] == {"ok": False, "error": "the call is already closed"}
    led = ledger(base, cid)
    assert led["promises"] == [{"promise_id": "pr1", "product_id": "p1", "type": "credit_card", "amount": 420, "date": "2026-12-24"}]   # ledger stays canonical
    assert led["calls"][0] == {"n": 1, "tool": "verify_identity", "args": {"question": "phone_last4", "answer": "1"}, "status": 200, "result": {"ok": False, "error": "question must be policy_number or date_of_birth"}}
    assert led["calls"][5]["tool"] == "create_promise" and led["calls"][5]["args"] == {"product_id": "p1", "promise_amount": "420", "promise_date": "24 December"}
    assert led["outcome"] == "promise" and led["reason"] is None
    status, r = call(base, "verify_identity", cid, field="date_of_birth", answer="1975-12-05")     # the old names still route to the role
    assert r == {"ok": False, "error": "the call is already closed"}


def test_absent_field_strict_validation(base):
    """Under a renamed profile the canonical names are strangers: a request that uses them is validated as if the field were absent."""
    p = profile_from_openapi(renamed_openapi())
    cid = open_session(base, customer(identity={"policy_number": "PN-77-X", "date_of_birth": "1975-12-05"}, profile=p))
    status, r = call(base, "check_identity", cid, field="policy_number", answer="PN-77-X")              # `field` instead of `question`
    assert (status, r) == (200, {"ok": False, "error": "question must be policy_number or date_of_birth"})
    status, r = call(base, "check_identity", cid, question="date_of_birth")                               # no answer at all
    assert r == {"ok": False, "error": "answer is not a date. Send it as YYYY-MM-DD."}
    assert call(base, "check_identity", cid, question="policy_number", answer="PN77X")[1]["verified"]
    assert call(base, "check_identity", cid, question="date_of_birth", answer="1975-12-05")[1]["all_verified"]
    status, r = call(base, "record_promise", cid, product_id="p1", amount=420, date="2026-12-24")         # canonical names on the wire
    assert r == {"ok": False, "error": "promise_amount must be a positive number"}
    status, r = call(base, "record_promise", cid, product_id="p1", promise_amount=420, date="2026-12-24")
    assert r == {"ok": False, "error": "promise_date must be YYYY-MM-DD"}
    assert call(base, "record_promise", cid, promise_amount=420, promise_date="2026-12-24")[1] == {"ok": False, "error": "unknown product_id"}
    assert call(base, "schedule_callback", cid, date="2026-12-26")[1] == {"ok": False, "error": "date must be YYYY-MM-DD and time HH:MM"}
    assert call(base, "end_call", cid)[1] == {"ok": False, "error": "unknown outcome"}
    led = ledger(base, cid)
    assert led["promises"] == [] and led["outcome"] is None and len(led["calls"]) == 9
