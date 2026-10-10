"""Build-time self-tests that need no platform (tier 0).

    snippet_check(table)                      -> {"name", "result": PASS|FAIL, "detail"} list
    public_cases(table, api, brief_letter)    -> one row per public case of that brief, run through the local
                                                 simulator against an in-process mock bank
    witness_cases(table)                      -> the table's own examples, evaluated by the reader checks

The public-case scripts are the same customer turns as tests/test_emitter.py (engine events turned into the
extraction values of the node the call is in). They run only when the brief is one of the two public briefs.
"""
from __future__ import annotations

import json
import pathlib

from builder.emitter.emit import emit
from builder.emitter.fragments import STAGE_FIELDS, STAGE_NODE
from builder.engine.snippet import render

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC_CASES = ROOT / "kit" / "build-the-builder" / "public-test-set.json"
NODE_STAGE = {v: k for k, v in STAGE_NODE.items()}
OUT_KEYS = ("engine_state", "engine_next", "say_next", "mandatory_lines", "readback_text", "engine_writes",
            "close_outcome", "close_reason", "what_to_do_next", "ask_clarify", "engine_unsupported")
SAMPLE_CALL = {"customer_id": "c_selftest", "first_name": "Dana", "last_name": "Reyes", "title": "Ms",
               "now": "2026-10-14T11:00"}


# --------------------------------------------------------------------------------------------------------------
# the engine snippet, exec'd the way a code node runs it


def _ev(kind, **kw):
    e = {"kind": kind, "item": None, "text": None, "date_text": None, "time_text": None, "amount": None, "qid": None}
    e.update(kw)
    return e


def snippet_check(table, call_vars=None):
    src = render(table)
    rows = []

    def run(name, v, want=None):
        try:
            exec(src, {"vars": v})  # noqa: S102 - our own rendered engine
        except Exception as e:  # noqa: BLE001
            rows.append({"name": name, "result": "FAIL", "detail": "raised %s: %s" % (type(e).__name__, e)})
            return v
        bad = [k for k in OUT_KEYS if not isinstance(v.get(k), str)]
        braces = [k for k in OUT_KEYS if "{{" in str(v.get(k)) or "}}" in str(v.get(k))]
        problem = ("non-string outputs %s" % bad if bad else "") or ("double braces in %s" % braces if braces else "")
        if not problem and want:
            problem = want(v) or ""
        rows.append({"name": name, "result": "FAIL" if problem else "PASS",
                     "detail": problem or "engine_next=%s" % v.get("engine_next")})
        return v

    v = dict(call_vars or SAMPLE_CALL)
    v = run("snippet: first turn, no events", v, lambda v: "" if v["engine_next"] else "empty engine_next")
    state = v.get("engine_state")
    v = dict(call_vars or SAMPLE_CALL, engine_state=state, engine_events=json.dumps([_ev("party_confirmed")]))
    run("snippet: party confirmed", v, lambda v: "" if v["engine_state"] != state else "state did not move")
    v = dict(call_vars or SAMPLE_CALL, engine_state=state, engine_events="not json {")
    run("snippet: error path (unreadable events)", v,
        lambda v: "" if v["engine_next"] == "clarify" and v["ask_clarify"] == "true" else "no fallback on bad input")
    failed = {"kind": "tool_result", "tool": "verify_identity", "item": None, "result": "failed",
              "data": {"ok": False, "error": "service unavailable"}, "args": {}}
    v = dict(call_vars or SAMPLE_CALL, engine_state=state, engine_events=json.dumps([failed]))
    run("snippet: failed tool result", v)
    return rows


# --------------------------------------------------------------------------------------------------------------
# the public cases through the local simulator


def E(kind, item=None, text=None, date=None, time=None, amount=None):
    return {"kind": kind, "item": item, "text": text, "date": date, "time": time, "amount": amount}


def _verified(c):
    i = c["identity"]
    return [[E("party_confirmed")], [E("id_answer", text=i["date_of_birth"])], [E("id_answer", text=i["phone_last4"])]]


SCRIPTS = {
    "PUB-01": lambda c: _verified(c) + [[E("pay_today_yes")], [E("confirm")]],
    "PUB-02": lambda c: [[E("party_other"), E("question_back")], [E("callback_offer", date="tomorrow", time="around eleven in the morning")]],
    "PUB-03": lambda c: [[E("party_confirmed")], [E("id_answer", text="12 July 1991")], [E("id_answer", text="21 August 1992")],
                         [E("id_answer", text="21 July 1990")]],
    "PUB-04": lambda c: _verified(c) + [[E("date_proposal", date="6 November"), E("robot_question")], [E("accept_offer")], [E("confirm")]],
    "PUB-05": lambda c: _verified(c) + [[E("hardship"), E("other")], [E("refuse")]],
    "PUB-06": lambda c: _verified(c) + [[E("too_much")], [E("accept_offer", date="this Friday")], [E("confirm")]],
    "PUB-07": lambda c: _verified(c) + [[E("pay_today_no"), E("vague_period", date="the week after next")],
                                        [E("date_proposal", date="Monday the 26th")], [E("accept_offer")], [E("confirm")]],
    "PUB-08": lambda c: _verified(c) + [[E("paid")]],
    "PUB-09": lambda c: _verified(c) + [[E("plan_request")]],
    "PUB-10": lambda c: _verified(c) + [[E("pay_today_no"), E("date_proposal", date="this Friday")], [E("confirm")]],
    "PUB-11": lambda c: _verified(c) + [[E("pay_today_no"), E("date_proposal", date="this Friday")], [E("confirm")]],
    "PUB-12": lambda c: [[E("party_confirmed")], [E("id_answer", text="19 October 1983")], [E("id_answer", text="4401")],
                         [E("id_answer", text="4410")], [E("date_proposal", item="p1", date="tomorrow")], [E("refuse")], [E("refuse")],
                         [E("refuse")], [E("confirm")]],
    "PUB-13": lambda c: _verified(c) + [[E("pay_today_no"), E("date_proposal", date="30 October")], [E("confirm")]],
}


def _extract_for(node, bundle):
    base = node if node in NODE_STAGE else node.rsplit("_", 1)[0]
    if base not in NODE_STAGE:
        raise RuntimeError("the call is in %r, not a listening node" % node)
    stage = NODE_STAGE[base]
    out = {}
    for k, ev in enumerate(bundle, 1):
        src = {"reply": ev["kind"], "item": ev["item"], "amount": ev["amount"], "date": ev["date"], "time": ev["time"],
               "words": ev["text"]}
        for f in STAGE_FIELDS[stage]:
            if src[f] is not None:
                out["%s_%s%d" % (base, f, k)] = str(src[f])
    return out


def _ledger_view(x):
    return {"outcome": x["outcome"], "reason": x.get("reason"),
            "promises": sorted((p["product_id"], round(float(p["amount"]), 2), p["date"]) for p in x["promises"]),
            "notes": sorted((n.get("product_id"), n["reason"]) for n in x["notes"]),
            "callbacks": sorted((c["date"], c["time"]) for c in x["callbacks"]),
            "transfers": sorted(t["queue"] for t in x["transfers"])}


def public_cases(table, api, brief_letter, cases_path=PUBLIC_CASES):
    from bank import replay
    from harness.simulator import Simulator, bank_ledger, open_bank_session

    cases = [c for c in json.loads(pathlib.Path(cases_path).read_text()) if c["brief"] == brief_letter]
    srv, url = replay.start_server()
    rows = []
    try:
        wf = emit(table, api, variant="test", bank_url=url)
        for c in cases:
            row = {"name": c["id"], "result": "FAIL", "detail": ""}
            try:
                session = open_bank_session(url, customer=c)
                if not session.get("ok"):
                    raise RuntimeError("bank session: %s" % session)
                variables = dict(session["variables"])
                sim = Simulator(wf, variables=variables)
                sim.start()
                for b in SCRIPTS[c["id"]](c):
                    if sim.ended:
                        break
                    sim.turn({"say": json.dumps(b), "extract": _extract_for(sim.current, b)})
                rec = sim.record()
                led = bank_ledger(url, variables["customer_id"])
                got, want = _ledger_view(led), _ledger_view(c["expected"])
                errors = [e for e in rec["events"] if e["event"] == "error"]
                tools = [x["tool"] for x in led["calls"]]
                problems = []
                if got != want:
                    problems.append("ledger %s, expected %s" % (
                        {k: v for k, v in got.items() if v != want[k]}, {k: v for k, v in want.items() if v != got[k]}))
                if not tools or tools[-1] != "close_call" or tools.count("close_call") != 1:
                    problems.append("close_call not once and last: %s" % tools)
                if errors:
                    problems.append("engine errors: %s" % errors[:2])
                row.update(result="FAIL" if problems else "PASS",
                           detail="; ".join(problems) or " > ".join(tools))
            except Exception as e:  # noqa: BLE001 - a crash is a failed case, not a failed build
                row.update(result="FAIL", detail="%s: %s" % (type(e).__name__, str(e)[:300]))
            rows.append(row)
    finally:
        srv.shutdown()
    return rows


# --------------------------------------------------------------------------------------------------------------
# the table's own examples (witnesses)


def witness_cases(table):
    from builder.readers.checks import evaluate_example

    rows = []
    for i, ex in enumerate(table.get("examples") or []):
        try:
            status, detail = evaluate_example(table, ex)
        except Exception as e:  # noqa: BLE001
            status, detail = "unevaluated", "%s: %s" % (type(e).__name__, e)
        result = {"verified": "PASS", "mismatch": "FAIL"}.get(status, "UNKNOWN")
        rows.append({"name": "witness %d (%s)" % (i, ex.get("unit")), "result": result, "detail": "%s: %s" % (status, detail)})
    return rows
