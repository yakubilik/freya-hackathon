"""The rendered code-node snippet behaves exactly like calling step() directly.

The snippet is exec'd in a fresh namespace with only `vars` (as a Freya code node would run it) for
several multi-turn sequences on the Brief A and Brief B tables, feeding tool results back as events;
its outputs are compared turn by turn with step(). Also: no `{{`/`}}`, standard library only, never raises.
"""
import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder.engine.snippet import pack, render  # noqa: E402
from builder.engine.step import step, new_state  # noqa: E402

TABLE_A = json.load(open(ROOT / "fixtures" / "tables" / "brief-a.json"))
TABLE_B = json.load(open(ROOT / "fixtures" / "tables" / "brief-b.json"))
NOW = "2026-10-14T11:00"
CALL = {"customer_id": "c_test", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": NOW}
PRODUCTS_A = [{"product_id": "p1", "type": "credit_card", "card_last4": "4821", "past_due": 420, "days_late": 6, "minimum_payment": 126}]
PRODUCTS_B = [{"product_id": "p1", "type": "credit_card", "card_last4": "6604", "past_due": 300, "days_late": 4, "minimum_payment": 90},
              {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300}]


def ev(kind, **kw):
    e = {"kind": kind, "item": None, "text": None, "date_text": None, "time_text": None, "amount": None, "qid": None}
    e.update(kw)
    return e


def tool_ok(tool, data, item=None, args=None):
    return {"kind": "tool_result", "tool": tool, "item": item, "result": "ok", "data": data, "args": args or {}}


def tool_failed(tool, item=None, args=None):
    return {"kind": "tool_result", "tool": tool, "item": item, "result": "failed",
            "data": {"ok": False, "error": "service unavailable, nothing was recorded"}, "args": args or {}}


VERIFIED = [
    [ev("party_confirmed")],
    [ev("id_answer", text="14 March 1988")],
    [tool_ok("verify_identity", {"ok": True, "verified": True, "wrong_answers_left": 3, "all_verified": False})],
    [ev("id_answer", text="4471")],
    [tool_ok("verify_identity", {"ok": True, "verified": True, "wrong_answers_left": 3, "all_verified": True})],
]

SEQUENCES = {
    "A happy path": (TABLE_A, VERIFIED + [
        [tool_ok("get_account", {"ok": True, "products": PRODUCTS_A})],
        [ev("pay_today_yes")], [ev("confirm")],
        [tool_ok("create_promise", {"ok": True, "promise_id": "pr1"}, item="p1")],
        [tool_ok("close_call", {"ok": True})]]),
    "A too much, floor, retry once": (TABLE_A, VERIFIED + [
        [tool_ok("get_account", {"ok": True, "products": PRODUCTS_A})],
        [ev("too_much")], [ev("accept_offer", date_text="this Friday")], [ev("confirm")],
        [tool_failed("create_promise", item="p1")],
        [tool_ok("create_promise", {"ok": True, "promise_id": "pr1"}, item="p1")],
        [tool_ok("close_call", {"ok": True})]]),
    "A third party callback": (TABLE_A, [
        [ev("party_other"), ev("question_back")],
        [ev("callback_offer", date_text="tomorrow", time_text="9 in the morning")],
        [ev("callback_offer", date_text="tomorrow", time_text="2 pm")],
        [tool_ok("schedule_callback", {"ok": True})],
        [tool_ok("close_call", {"ok": True})]]),
    "A hardship declines then refuses": (TABLE_A, VERIFIED + [
        [tool_ok("get_account", {"ok": True, "products": PRODUCTS_A})],
        [ev("hardship")], [ev("refuse")],
        [tool_ok("close_call", {"ok": True})]]),
    "B common date, dispute, notes": (TABLE_B, VERIFIED + [
        [tool_ok("get_account", {"ok": True, "products": PRODUCTS_B})],
        [ev("pay_today_no"), ev("date_proposal", item="p1", date_text="30 October"), ev("dispute", item="p2")],
        [ev("confirm")],
        [tool_ok("create_promise", {"ok": True, "promise_id": "pr1"}, item="p1")],
        [tool_ok("add_note", {"ok": True}, item="p2")],
        [tool_ok("close_call", {"ok": True})]]),
    "B refuses everything": (TABLE_B, VERIFIED + [
        [tool_ok("get_account", {"ok": True, "products": PRODUCTS_B})],
        [ev("refuse")], [ev("refuse")], [ev("refuse")], [ev("refuse")],
        [tool_ok("add_note", {"ok": True}, item="p1")], [tool_ok("add_note", {"ok": True}, item="p2")],
        [tool_ok("close_call", {"ok": True})]]),
    "unknown input never raises": (TABLE_A, [[ev("weird_kind")], [ev("party_confirmed")], [{"kind": None}], [ev("id_answer", text="garbage")]]),
}


def run_snippet(src, turns):
    """exec the snippet once per turn in a fresh namespace; returns the list of output dicts."""
    v = dict(CALL)
    outs = []
    for events in turns:
        v["engine_events"] = json.dumps(events)
        exec(src, {"vars": v})
        outs.append({k: v.get(k) for k in ("engine_state", "engine_next", "say_next", "mandatory_lines", "readback_text",
                                           "engine_writes", "close_outcome", "close_reason", "what_to_do_next", "ask_clarify",
                                           "engine_unsupported")})
        assert v["engine_events"] == ""
    return outs


def run_step(table, turns):
    st = new_state(CALL)
    outs = []
    for events in turns:
        st, out = step(st, events, table, NOW)
        outs.append((json.loads(json.dumps(st)), out))
    return outs


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_snippet_matches_step(name):
    table, turns = SEQUENCES[name]
    src = render(table)
    got = run_snippet(src, turns)
    want = run_step(table, turns)
    assert len(got) == len(want)
    for g, (st, out) in zip(got, want):
        assert json.loads(g["engine_state"]) == st
        assert g["engine_next"] == out["engine_next"]
        assert g["say_next"] == out["say_next"]
        assert g["mandatory_lines"] == "\n".join(out["mandatory_lines"])
        assert g["readback_text"] == out["readback_text"]
        assert json.loads(g["engine_writes"]) == out["writes"]
        close = out["close"] or {}
        assert g["close_outcome"] == (close.get("outcome") or "") and g["close_reason"] == (close.get("reason") or "")
        assert g["what_to_do_next"] == out["what_to_do_next"]
        assert g["ask_clarify"] == ("true" if out["ask_clarify"] else "false")
        assert json.loads(g["engine_unsupported"]) == out["unsupported"]


@pytest.mark.parametrize("table", [TABLE_A, TABLE_B], ids=["A", "B"])
def test_snippet_is_self_contained_and_brace_free(table):
    src = render(table)
    assert "{{" not in src and "}}" not in src
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import left in the snippet"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"base64", "json", "re", "datetime", "decimal"}, imported
    # runs in a namespace with nothing but vars, and produces every routed key
    v = dict(CALL)
    exec(src, {"vars": v})
    for key in ("engine_state", "engine_next", "say_next", "mandatory_lines", "readback_text", "engine_writes",
                "close_outcome", "close_reason", "what_to_do_next", "ask_clarify"):
        assert key in v and isinstance(v[key], str), key
    assert v["ask_clarify"] in ("true", "false") and v["engine_next"] == "party"


def test_snippet_never_raises_and_sets_fallbacks():
    src = render(TABLE_A)
    v = {"engine_state": "{not json", "engine_events": "[]", "now": NOW}
    exec(src, {"vars": v})
    assert v["engine_next"] == "clarify" and v["ask_clarify"] == "true" and v["what_to_do_next"] and v["engine_writes"] == "[]"
    v = {"engine_state": "", "engine_events": "not json either"}
    exec(src, {"vars": v})
    assert v["engine_next"] == "clarify" and json.loads(v["engine_state"])["stage"] == "party"
    v = {}   # no clock, no call variables: the opening still works, date features are marked
    exec(src, {"vars": v})
    assert v["engine_next"] == "party" and "Am I speaking with" in v["mandatory_lines"]
    assert "call.now" in json.loads(v["engine_unsupported"])


def test_render_rejects_double_braces_in_its_own_source(monkeypatch):
    import builder.engine.snippet as snippet
    monkeypatch.setattr(snippet, "_MAIN", snippet._MAIN + "\nX = '{{bad}}'\n")
    with pytest.raises(ValueError):
        render(TABLE_A)


@pytest.mark.parametrize("table", [TABLE_A, TABLE_B], ids=["A", "B"])
def test_packed_snippet_is_small_and_behaves_like_the_plain_one(table):
    """The emitter ships pack(render(table)): under 60 KB (the platform caps code plus variables at 128 KiB and the
    variables grow every turn), brace-free, standard library only, and the same outputs as the plain source."""
    plain, packed = render(table), pack(render(table))
    assert len(packed) < 60000, len(packed)
    assert "{{" not in packed and "}}" not in packed
    imported = {a.name.split(".")[0] for node in ast.walk(ast.parse(packed)) if isinstance(node, ast.Import) for a in node.names}
    assert imported <= {"base64", "zlib"}, imported
    for events in ([], [ev("party_confirmed")]):
        a, b = dict(CALL), dict(CALL)
        a["engine_events"], b["engine_events"] = json.dumps(events), json.dumps(events)
        exec(plain, {"vars": a})
        exec(packed, {"vars": b})
        assert a == b
    # the engine's names are visible to code appended after the packed block (the emitter's epilogue needs them)
    ns = {"vars": dict(CALL)}
    exec(packed + "\nvars['probe'] = str(callable(step)) + str(callable(new_state))\n", ns)
    assert ns["vars"]["probe"] == "TrueTrue"



def test_engine_table_carries_the_derived_flags():
    """Synthetic C-01 (platform, 2026-10-11): the amounts-in-words flag is read from the table's obligations, which the
    engine node does not carry; the emitter embeds the derived flags and the engine reads them back."""
    import json, pathlib, importlib
    from builder.engine import snippet
    step = importlib.import_module("builder.engine.step")
    root = pathlib.Path(__file__).resolve().parent.parent
    table = json.load(open(root / "fixtures" / "tables" / "brief-a.json"))
    table["obligations"] = list(table.get("obligations") or []) + [{"id": "O-x", "status": "effective", "when": {}, "then": [{"say": {"content": "say amounts in words in euros"}}]}]
    table["units"] = {"x.1": {"text": "Declined: continue without persuasion; a date or amount the customer still names is recorded."}}
    small = snippet.engine_table(table)
    assert small["derived"]["amount_words"] is True and small["derived"]["currency"] == "euros" and small["derived"]["hardship_continues"] is True
    assert "obligations" not in small and "units" not in small
    C = step._context(small, "2026-10-16T10:00")
    assert C["amount_words"] and C["currency"] == "euros" and C["hardship_continues"]
    assert step._money(38000, C) == "three hundred and eighty euros"
    plain = step._context(snippet.engine_table(json.load(open(root / "fixtures" / "tables" / "brief-a.json"))), "2026-10-16T10:00")
    assert not plain["amount_words"] and not plain["hardship_continues"]
