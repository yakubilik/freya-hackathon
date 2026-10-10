"""Offline tests for builder/readers: segmentation, JSON extraction, mechanical checks, adjudication, read()."""
import copy
import json
import pathlib

import pytest

from builder.readers import adjudicate as adj
from builder.readers import models, r1, r4, read_brief
from builder.readers.api_file import load_api
from builder.readers.checks import run_checks
from builder.readers.jsonx import NoJSON, OpError, apply_ops, extract_json, parse_jsonl
from builder.readers.segment import lossless, quote_to_units, segment

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIEFS = ROOT / "kit" / "build-the-builder" / "briefs"
API_PATH = ROOT / "kit" / "build-the-builder" / "tools" / "openapi.json"
TABLE_A = ROOT / "fixtures" / "tables" / "brief-a.json"

RAW_MATERIAL = """From: Collections Policy Desk
To: Dialogue vendor
Subject: Updated calling rules
Date: 2026-11-02

Please apply the attached policy extract. The memo below changes one rule.

---

# Policy extract COL-7

1. Ask two security questions: date of birth, then the postcode.
2. Three wrong answers end the check.
3. A promise date must not be after the 10th business day after today.

---

MEMO
5 November 2026

Effective 2026-11-09, rule 3 of COL-7 is replaced: a promise date must not be after the 6th business day after today.

# Code list

| Code | Outcome | Reason |
|------|---------|--------|
| P1 | `promise` | none |
| R1 | `no_promise` | `refused` |
"""


@pytest.fixture(scope="module")
def api():
    return load_api(API_PATH)


@pytest.fixture(scope="module")
def table_a():
    return json.loads(TABLE_A.read_text())


# ------------------------------------------------------------------------------------------------
# segmentation


@pytest.mark.parametrize("name", ["brief-a.md", "brief-b.md"])
def test_segment_public_briefs_lossless(name):
    src = (BRIEFS / name).read_text()
    seg = segment(src)
    assert lossless(src, seg["units"])
    assert len(seg["documents"]) == 1
    assert all(u["text"] == src[u["offset"]:u["end"]] for u in seg["units"].values())


def test_segment_brief_b_on_base_gives_two_documents():
    src = (BRIEFS / "brief-a.md").read_text() + "\n\n---\n\n" + (BRIEFS / "brief-b.md").read_text()
    seg = segment(src)
    assert [d["kind"] for d in seg["documents"]] == ["brief", "brief"]
    assert lossless(src, seg["units"])


def test_segment_raw_material_with_amendment():
    seg = segment(RAW_MATERIAL)
    kinds = [d["kind"] for d in seg["documents"]]
    assert kinds[0] == "mail" and "memo" in kinds
    mail = seg["documents"][0]
    assert mail["issue_date"] == "2026-11-02" and mail["title"] == "Updated calling rules"
    memo = next(d for d in seg["documents"] if d["kind"] == "memo")
    assert memo["issue_date"] == "2026-11-05"
    assert lossless(RAW_MATERIAL, seg["units"])
    # the amending sentence and the amended rule are separate units in different documents
    amending = quote_to_units("rule 3 of COL-7 is replaced", seg["units"])
    amended = quote_to_units("not be after the 10th business day after today", seg["units"])
    assert amending and amended
    assert seg["units"][amending[0]]["doc_id"] != seg["units"][amended[0]]["doc_id"]
    rows = [u for u in seg["units"].values() if u["kind"] == "row"]
    assert any("`refused`" in r["text"] for r in rows)


def test_segment_raw_fixture_file():
    src = (ROOT / "tests" / "fixtures" / "raw_brief.md").read_text()
    seg = segment(src)
    assert lossless(src, seg["units"])
    assert [d["kind"] for d in seg["documents"]][:2] == ["mail", "memo"]


# ------------------------------------------------------------------------------------------------
# JSON extraction


def test_extract_json_messy_replies():
    obj = {"table": {"a": 1}, "reader_notes": "x"}
    s = json.dumps(obj)
    assert extract_json(s) == obj
    assert extract_json("Here you go:\n```json\n" + s + "\n```\nHope this helps.") == obj
    assert extract_json("Sure! " + s + " trailing {not json") == obj
    assert extract_json('{"x": 1} and then ' + s, require_key="table") == obj
    with pytest.raises(NoJSON):
        extract_json("no json at all")
    with pytest.raises(NoJSON):
        extract_json('{"x": 1}', require_key="table")


def test_parse_jsonl_truncation_safe():
    text = "\n".join([
        "```jsonl",
        '{"kind": "item", "id": "R4-1", "quote": "a"},',
        "",
        '{"kind": "inventory", "id": "R4-I1"} {"kind": "item", "id": "R4-2"}',
        '[{"kind": "case", "id": "R4-C1"}]',
        '{"kind": "case", "id": "R4-C2", "turns": [{"say": "trunc',
        "```",
    ])
    objs, bad = parse_jsonl(text)
    assert [o["id"] for o in objs] == ["R4-1", "R4-I1", "R4-2", "R4-C1"]
    assert len(bad) == 1


def test_apply_ops_all_or_nothing(table_a):
    t, done = apply_ops(table_a, [{"op": "set_parameter", "path": "identity.max_wrong", "entry": {"value": 4, "type": "integer", "confidence": "quoted"}}])
    assert t["parameters"]["identity.max_wrong"]["value"] == 4 and table_a["parameters"]["identity.max_wrong"]["value"] == 3
    with pytest.raises(OpError):
        apply_ops(table_a, [{"op": "set_parameter", "path": "x", "entry": {}}, {"op": "remove_obligation", "id": "O-nope"}])


# ------------------------------------------------------------------------------------------------
# mechanical checks


def _messages(res):
    return [f["message"] for f in res["findings"]]


def test_checks_clean_on_hand_table(table_a, api):
    res = run_checks(table_a, api)
    assert res["counts"]["fatal"] == 0
    assert not [f for f in res["findings"] if f["path"].startswith("obligations/") and f["check"] in ("quote", "wire", "unit_exists")]
    assert not [f for f in res["findings"] if f["check"] in ("disposition", "closing", "plan")]
    verified = [e for e in res["example_results"] if e["status"] == "verified"]
    assert len(verified) >= 5 and not [e for e in res["example_results"] if e["status"] == "mismatch"]


def test_checks_bad_quote(table_a, api):
    t = copy.deepcopy(table_a)
    t["obligations"][0]["quote"] = "Say you are a human banker."
    assert any("quote not in cited units" in m for m in _messages(run_checks(t, api)))


def test_checks_unknown_enum(table_a, api):
    t = copy.deepcopy(table_a)
    for o in t["obligations"]:
        for a in o["then"]:
            if "transfer" in a:
                a["transfer"]["queue"] = "hardship_desk"
    assert any("queue 'hardship_desk' not in enum" in m for m in _messages(run_checks(t, api)))
    t["parameters"]["identity.questions"]["value"][0]["wire_field"] = "dob"
    assert any("wire_field 'dob'" in m for m in _messages(run_checks(t, api)))


def test_checks_unparseable_expression(table_a, api):
    t = copy.deepcopy(table_a)
    t["parameters"]["bands"]["value"][0]["deadline_expr"] = "business_days_after(today, 12"
    t["parameters"]["amounts.floor_expr"]["value"] = "product.minimum_payment ? 1 : 2"
    paths = {f["path"] for f in run_checks(t, api)["findings"] if "unparseable expression" in f["message"]}
    assert {"bands[0].deadline_expr", "amounts.floor_expr"} <= paths


def test_checks_unknown_response_field(table_a, api):
    t = copy.deepcopy(table_a)
    t["parameters"]["bands"]["value"][0]["condition"] = "1 <= product.days_overdue <= 7"
    assert any("product.days_overdue is not a field" in m for m in _messages(run_checks(t, api)))


def test_checks_orphan_close_row_and_close_action(table_a, api):
    t = copy.deepcopy(table_a)
    rows = t["parameters"]["closing.rows"]["value"]
    rows.append({"outcome": "not_reached", "reason": "busy", "triggers": [], "precedence": 6})
    t["obligations"][0]["then"].append({"close": {"outcome": "no_promise", "reason": "too_late"}})
    msgs = _messages(run_checks(t, api))
    assert any("not_reached/busy has no trigger" in m for m in msgs)
    assert any("not_reached/busy has no trigger obligation" in m for m in msgs)
    assert any("close no_promise/too_late has no closing row" in m for m in msgs)


def test_checks_example_mismatch_and_plan(table_a, api):
    t = copy.deepcopy(table_a)
    t["examples"][0]["expected"] = "2026-10-30"
    t["plan"] = list(reversed(t["plan"]))
    res = run_checks(t, api)
    assert any(f["check"] == "example" for f in res["findings"])
    assert res["counts"]["fatal"] >= 1


def test_checks_amendment_authority(table_a, api):
    t = copy.deepcopy(table_a)
    uid = next(iter(t["units"]))
    t["amendments"] = [{"amending_unit": uid, "amended_units": [uid], "path": "bands", "old": 12, "new": 6,
                        "authority": "explicit_effective_date", "scope": "clause", "effective": {"from": "2026-11-09"}}]
    msgs = _messages(run_checks(t, api))
    assert any("effective window without anchor" in m for m in msgs)


# ------------------------------------------------------------------------------------------------
# adjudication


def test_adjudication_applies_overturned_and_rehashes(table_a, api):
    t = copy.deepcopy(table_a)
    h0 = adj.table_hash(t)
    items = [{"item_id": "A-1", "kind": "r4_item", "r4": {"id": "R4-1", "quote": "Three wrong answers in total end the check"},
              "candidates": {"obligations": [], "parameters": {}, "amendments": [], "dispositions": {}}},
             {"item_id": "A-2", "kind": "r4_item", "r4": {"id": "R4-2", "quote": "x"},
              "candidates": {"obligations": [], "parameters": {}, "amendments": [], "dispositions": {}}},
             {"item_id": "A-3", "kind": "check_finding", "check": "quote", "path": "p", "message": "m", "units": []}]
    entry = dict(t["parameters"]["identity.max_wrong"], value=2)
    reply = {"verdicts": [
        {"item_id": "A-1", "outcome": "overturned", "citations": ["a.r12"], "reasoning": "r",
         "correction": [{"op": "set_parameter", "path": "identity.max_wrong", "entry": entry}]},
        {"item_id": "A-2", "outcome": "contested", "citations": ["a.r12"], "readings": ["2", "3"], "taken": "3",
         "interpretation_rule": 2, "correction": [{"op": "set_parameter", "path": "identity.max_wrong", "entry": entry}]},
        {"item_id": "A-3", "outcome": "overturned", "citations": ["a.r1"],
         "correction": [{"op": "set_parameter", "path": "identity.questions", "entry": {"value": 1}}]},
    ]}
    new, log = adj.apply_verdicts(t, items, reply)
    assert new["parameters"]["identity.max_wrong"]["value"] == 2
    by = {e["item_id"]: e for e in log}
    assert by["A-1"]["applied"]
    assert "conflict" in by["A-2"]["correction_error"]           # same location, later in the order
    assert by["A-3"]["correction_error"].startswith("schema")   # breaks the schema: rejected
    assert any(q["rule"].startswith("interpretation order (2)") for q in new["open_questions"])
    frozen = adj.freeze(new, {"assurance": "test"})
    assert frozen["run_metadata"]["table_hash"] == adj.table_hash(new) != h0
    assert adj.table_hash(frozen) == adj.table_hash(new)        # run_metadata is not hashed


def test_build_items_pairs_by_units(table_a):
    units = table_a["units"]
    audit = r4.parse_reply("\n".join([
        json.dumps({"kind": "item", "id": "R4-1", "category": "verification_predicate",
                    "quote": "Three wrong answers in total end the check, whichever question they were on."}),
        json.dumps({"kind": "case", "id": "R4-C1", "now": "2026-10-14T11:00",
                    "products": [{"product_id": "p1", "type": "credit_card", "past_due": 400, "days_late": 14,
                                  "minimum_payment": 50, "instalment_amount": 0}],
                    "expected": {"outcome": "promise", "reason": None,
                                 "promises": [{"product_id": "p1", "amount": 400, "date": "2026-10-30"}]}}),
    ]), units)
    items, consistent = adj.build_items(table_a, audit, [])
    r4_item = next(i for i in items if i["kind"] == "r4_item")
    assert any(o["id"] == "O-a.r12" for o in r4_item["candidates"]["obligations"])
    assert "identity.max_wrong" in r4_item["candidates"]["parameters"]
    case = next(i for i in items if i["kind"] == "r4_case")
    assert "after the table's deadline 2026-10-23" in case["table_expectation"]["disagreements"][0]


# ------------------------------------------------------------------------------------------------
# full read() with stub backends


def _stub_table(seg):
    units = seg["units"]
    uid = lambda q: quote_to_units(q, units)[0]  # noqa: E731
    u_close = uid("Every call ends with exactly one `close_call`")
    u_id = uid("Three wrong answers in total end the check")
    u_q = uid("Ask two security questions, one at a time")
    obligations = [
        {"id": f"O-{u_close}.1", "units": [u_close], "quote": "Every call ends with exactly one `close_call`",
         "when": {"state": "closing", "guards": [], "event": None},
         "then": [{"tool": {"name": "close_call", "args": {"outcome": "{{outcome}}"}}}],
         "kind": "state", "scope": "call", "status": "effective"},
        {"id": f"O-{u_id}.1", "units": [u_id], "quote": "Three wrong answers in total end the check",
         "when": {"state": "identity", "guards": ["identity.wrong == 3"], "event": "id_answer"},
         "then": [{"close": {"outcome": "not_verified", "reason": "failed"}}],
         "kind": "state", "scope": "call", "status": "effective"},
    ]
    disp = {u: {"kind": "informational", "reason": "stub"} for u in units if u not in (u_close, u_id)}
    disp[u_close] = {"kind": "obligation", "refs": [obligations[0]["id"]]}
    disp[u_id] = {"kind": "obligation", "refs": [obligations[1]["id"]]}
    return {"table": {
        "schema_version": "1.0", "documents": [{"doc_id": "d1", "kind": "brief", "role": "authoritative"}],
        "units": {}, "dispositions": disp, "obligations": obligations,
        "parameters": {
            "identity.max_wrong": {"value": 2, "type": "integer", "units": [u_id], "confidence": "quoted"},
            "identity.questions": {"value": [{"id": "date_of_birth", "wire_field": "date_of_birth", "type": "date", "order": 1}],
                                   "type": "list", "units": [u_q], "confidence": "quoted"},
            "closing.rows": {"value": [{"outcome": "not_verified", "reason": "failed", "triggers": ["identity_failed"],
                                        "precedence": 5, "obligations": [obligations[1]["id"]]}],
                             "type": "list", "confidence": "quoted"},
        },
        "amendments": [], "wire_map": {"tools": {}, "concepts": {}, "enums": {}}, "phrases": [], "plan": [],
        "examples": [], "open_questions": [], "bogus_key": 1}, "question_battery": [], "reader_notes": "stub"}


@pytest.fixture
def stubs(monkeypatch):
    calls = []
    seg = segment((BRIEFS / "brief-a.md").read_text())

    def claude_text(prompt, *, purpose="r1", deadline=None, timeout_s=600, **kw):
        calls.append(purpose)
        usage = {"model": "stub-claude", "purpose": purpose, "tokens": 10, "seconds": 0.0, "backend": "stub"}
        if purpose == "r1":
            return "Here is the table:\n```json\n" + json.dumps(_stub_table(seg)) + "\n```", usage
        if purpose == "adjudicate":
            items = json.loads(prompt.split("# Adjudication items\n\n", 1)[1].split("\n\nDecide all", 1)[0])
            target = next((i for i in items if i["kind"] == "r4_item"), None)
            verdicts = [{"item_id": i["item_id"], "outcome": "accepted", "citations": ["d1.s1"], "reasoning": "ok"} for i in items]
            if target is None:
                return json.dumps({"verdicts": verdicts}), usage
            entry = {"value": 3, "type": "integer", "units": target["r4"]["units"], "confidence": "quoted"}
            verdicts = [{"item_id": i["item_id"], "outcome": "accepted", "citations": ["d1.s1"], "reasoning": "ok"} for i in items]
            verdicts[items.index(target)] = {"item_id": target["item_id"], "outcome": "overturned", "citations": target["r4"]["units"],
                                             "reasoning": "three, not two",
                                             "correction": [{"op": "set_parameter", "path": "identity.max_wrong", "entry": entry}]}
            return json.dumps({"verdicts": verdicts, "new_positions": [], "summary": "s"}), usage
        raise AssertionError(purpose)

    def r4_text(prompt, *, purpose="r4", deadline=None, timeout_s=600, **kw):
        calls.append(purpose)
        assert "<<<BRIEF" in prompt and "d1.s" not in prompt  # blind: raw text, no unit ids
        lines = [json.dumps({"kind": "item", "id": "R4-1", "category": "verification_predicate",
                             "quote": "Three wrong answers in total end the check, whichever question they were on."}),
                 json.dumps({"kind": "inventory", "id": "R4-I1", "quote": "Freya Bank is fictional.", "classification": "informational"}),
                 '{"kind": "case", "id": "R4-C1", "turns": [{"say": "trunc']
        return "\n".join(lines), {"model": "stub-r4", "purpose": purpose, "tokens": 5, "seconds": 0.0, "backend": "stub",
                                  "assurance": "two model families"}

    monkeypatch.setattr(models, "claude_text", claude_text)
    monkeypatch.setattr(models, "r4_text", r4_text)
    return calls


def test_read_end_to_end_with_stubs(stubs, tmp_path):
    t = read_brief.read(BRIEFS / "brief-a.md", API_PATH, out_dir=tmp_path, deadline_s=600)
    assert sorted(stubs) == ["adjudicate", "r1", "r4"]
    assert t["parameters"]["identity.max_wrong"]["value"] == 3          # overturned by the adjudicator
    rm = t["run_metadata"]
    assert rm["assurance"] == "two model families"
    assert rm["adjudication"]["overturned"] == 1 and rm["adjudication"]["applied"] == 1
    assert rm["table_hash"] == adj.table_hash(t)
    assert "bogus_key" in rm["r1"] or "bogus_key" not in t
    assert set(t["wire_map"]["tools"]) >= {"verify_identity", "close_call"}
    assert len(t["units"]) == len(segment((BRIEFS / "brief-a.md").read_text())["units"])
    for name in ("table.json", "r1.raw.txt", "r4.raw.txt", "checks.json", "adjudication.json", "trace.jsonl"):
        assert (tmp_path / name).exists(), name
    trace = [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert {x["purpose"] for x in trace} == {"r1", "r4", "adjudicate"}
    assert all(set(x) >= {"model", "purpose", "tokens", "seconds"} for x in trace)
    saved = json.loads((tmp_path / "table.json").read_text())
    assert saved["run_metadata"]["table_hash"] == rm["table_hash"]
    assert r1.validation_errors(saved) == []


def test_read_degrades_without_r4(stubs, tmp_path, monkeypatch):
    def broken(*a, **k):
        raise models.ModelCallError("every R4 backend failed")
    monkeypatch.setattr(models, "r4_text", broken)
    t = read_brief.read(BRIEFS / "brief-a.md", API_PATH, out_dir=tmp_path, deadline_s=600)
    assert t["run_metadata"]["assurance"] == "source audit incomplete"
    assert "every R4 backend failed" in t["run_metadata"]["r4_error"]


def test_read_raises_when_r1_fails_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "claude_text", lambda *a, **k: ("I cannot do that.", {"model": "m", "purpose": "r1", "tokens": 0, "seconds": 0}))
    with pytest.raises(r1.ReaderError):
        read_brief.read(BRIEFS / "brief-a.md", API_PATH, out_dir=tmp_path, deadline_s=600, skip_r4=True)


def test_r1_repair_turn_fixes_schema_errors(monkeypatch, api):
    seg = segment((BRIEFS / "brief-a.md").read_text())
    reply = _stub_table(seg)
    reply["table"]["obligations"][0]["kind"] = "duty"            # not in the enum
    purposes = []

    def claude_text(prompt, *, purpose="r1", **kw):
        purposes.append(purpose)
        u = {"model": "m", "purpose": purpose, "tokens": 1, "seconds": 0}
        if purpose == "r1":
            return json.dumps(reply), u
        assert "is not one of" in prompt
        return json.dumps({"ops": [{"op": "set", "path": ["obligations", 0, "kind"], "value": "state"}]}), u

    monkeypatch.setattr(models, "claude_text", claude_text)
    table, usages, info = r1.read_r1(seg, api)
    assert purposes == ["r1", "r1_repair"]
    assert info["schema_errors_initial"] >= 1 and info["schema_errors_final"] == []
    assert table["obligations"][0]["kind"] == "state"


def test_r1_prompt_carries_contract(api):
    seg = segment((BRIEFS / "brief-b.md").read_text())
    p = r1.build_prompt(seg, api)
    assert "Engine contract" in p and "d1.s1 [heading]" in p and "close_call" in p
    assert "? product.minimum_payment" not in p and "a if cond else b" in p


def test_checks_emitter_refusal(table_a, api):
    t = copy.deepcopy(table_a)
    next(s for s in t["plan"] if s["type"] == "readback")["per_item"] = True
    res = run_checks(t, api)
    assert any(f["check"] == "emitter" and "per_item" in f["message"] for f in res["findings"])
    assert not [f for f in run_checks(table_a, api)["findings"] if f["check"] == "emitter"]
