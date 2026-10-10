"""Step 3: reconcile R1's table with R4's blind audit and the mechanical findings, apply one correction cycle,
then freeze and hash.

Pairing is code: each R4 item is paired with the table's obligations and parameters by unit ids (its quote mapped
to units) and by parameter path (from its category). R1 exclusions are units R1 dispositioned as non-operative
that R4 quotes as operative, and API enum values R1 marked unused that R4 uses. R4 cases are compared with the
table's own expectation (closing row, band deadline, floor) and only disagreements go to the adjudicator.
Mechanical item findings go too. Corrections: overturned verdicts first (item id order), then contested ones in
the interpretation order (rule 1 first, then item id); a correction touching a location an earlier one already
changed is skipped and logged as a conflict; a correction that breaks the schema is rejected.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import re

from builder.engine.calendar import calendar_from_table, eval_expr

from . import models
from .api_file import api_summary
from .jsonx import NoJSON, OpError, apply_ops, extract_json, op_paths
from .r1 import prompt_text, units_listing, validation_errors

CATEGORY_PATHS = {
    "verification_predicate": ["identity."],
    "closing_row": ["closing."],
    "dates": ["dates.", "bands", "calendar."],
    "effective_date": ["third_party.callback", "calendar.", "bands"],
    "amounts": ["amounts.", "attempts"],
    "persuasion": ["attempts", "bands"],
    "recording": ["recording."],
    "situation": ["situations"],
    "multi": ["multi.", "notes."],
    "mandatory_communication": [],
    "prohibition": [],
    "amendment": [],
}
INTERPRETATION = {1: "authority and applicability evidence", 2: "explicit beats inferred", 3: "narrower scope beats general",
                  4: "later issue date", 5: "R4's source reading", 6: "the reading that forbids more"}
NON_OPERATIVE = {"informational", "superseded", "example", "definition"}


def _natkey(s):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", str(s))]


def _param(table, path):
    e = (table.get("parameters") or {}).get(path)
    if not isinstance(e, dict) or e.get("confidence") == "not_specified" or "value" not in e:
        return None
    return e["value"]


# ------------------------------------------------------------------------------------------------
# pairing


def _indexes(table):
    by_unit_obl, by_unit_par = {}, {}
    for o in table.get("obligations") or []:
        for u in o.get("units") or []:
            by_unit_obl.setdefault(u, []).append(o["id"])
    for path, e in (table.get("parameters") or {}).items():
        for u in (e.get("units") or []) if isinstance(e, dict) else []:
            by_unit_par.setdefault(u, []).append(path)
    return by_unit_obl, by_unit_par


def table_expectation(table, case):
    """What the table says for an R4 case: closing row present, per-product band, deadline and floor."""
    exp = case.get("expected") or {}
    rows = _param(table, "closing.rows") or []
    out = {"row_exists": any(r.get("outcome") == exp.get("outcome") and r.get("reason") == exp.get("reason") for r in rows),
           "products": {}, "disagreements": []}
    if not out["row_exists"]:
        out["disagreements"].append(f"no closing row {exp.get('outcome')}/{exp.get('reason')}")
    now = case.get("now")
    if not now:
        return out
    try:
        C = importlib.import_module("builder.engine.step")._context(table, now)
    except Exception:  # noqa: BLE001 - a malformed case must not stop adjudication
        return out
    cal, _ = calendar_from_table(table)
    floor_expr = _param(table, "amounts.floor_expr")
    for p in case.get("products") or []:
        if not isinstance(p, dict):
            continue
        ctx = {"now": C["now"], "cal": cal, "rules": C["rules"], "product": p, "customer": {}, "call": {}}
        info = {}
        try:
            for b in _param(table, "bands") or []:
                if eval_expr(b.get("condition", "false"), ctx):
                    info["band"] = b.get("id")
                    info["deadline"] = str(eval_expr(b.get("deadline_expr", ""), ctx))
                    break
            if floor_expr:
                info["floor"] = eval_expr(floor_expr, ctx)
        except Exception as e:  # noqa: BLE001
            info["error"] = f"{type(e).__name__}: {e}"
        out["products"][p.get("product_id")] = info
    for pr in exp.get("promises") or []:
        info = out["products"].get(pr.get("product_id")) or {}
        if info.get("deadline") and pr.get("date") and str(pr["date"]) > info["deadline"]:
            out["disagreements"].append(f"{pr.get('product_id')}: promise date {pr['date']} after the table's deadline {info['deadline']}")
        if info.get("floor") is not None and isinstance(pr.get("amount"), (int, float)) and pr["amount"] < float(info["floor"]):
            out["disagreements"].append(f"{pr.get('product_id')}: amount {pr['amount']} below the table's floor {info['floor']}")
    return out


def build_items(table, audit, findings):
    """Adjudication items: r4_item, r1_exclusion, r4_case (disagreements only), check_finding."""
    by_unit_obl, by_unit_par = _indexes(table)
    obligations = {o["id"]: o for o in table.get("obligations") or []}
    disp = table.get("dispositions") or {}
    items, n = [], 0

    def add(kind, body):
        nonlocal n
        n += 1
        items.append({"item_id": f"A-{n}", "kind": kind, **body})

    audit = audit or {}
    for it in audit.get("items") or []:
        units = list(dict.fromkeys((it.get("units") or []) + (it.get("exception_of_units") or []) + (it.get("precedence_over_units") or [])))
        oids = list(dict.fromkeys(o for u in units for o in by_unit_obl.get(u, [])))[:8]
        paths = set(p for u in units for p in by_unit_par.get(u, []))
        for pref in CATEGORY_PATHS.get(it.get("category"), []):
            paths.update(p for p in (table.get("parameters") or {}) if p.startswith(pref))
        amend = [a for a in table.get("amendments") or [] if a.get("amending_unit") in units or set(a.get("amended_units") or []) & set(units)]
        add("r4_item", {"r4": {k: v for k, v in it.items() if k not in ("kind",)},
                        "candidates": {"obligations": [obligations[o] for o in oids],
                                       "parameters": {p: table["parameters"][p] for p in sorted(paths)},
                                       "amendments": amend,
                                       "dispositions": {u: disp.get(u) for u in units}}})
    # R1 exclusions R4 treats as operative
    r4_units = {}
    for it in audit.get("items") or []:
        for u in it.get("units") or []:
            r4_units.setdefault(u, []).append(it.get("id"))
    for u in sorted(r4_units, key=_natkey):
        d = disp.get(u) or {}
        if d.get("kind") in NON_OPERATIVE and not by_unit_obl.get(u):
            add("r1_exclusion", {"unit": u, "text": (table.get("units") or {}).get(u, {}).get("text"), "r1_disposition": d,
                                 "r4_items": r4_units[u]})
    enums = (table.get("wire_map") or {}).get("enums") or {}
    r4_wire = {(w.get("tool"), w.get("field"), str(w.get("value"))) for it in audit.get("items") or []
               for w in [it.get("wire")] if isinstance(w, dict)}
    for key, e in enums.items():
        parts = key.split(".")
        if isinstance(e, dict) and e.get("unused") and len(parts) >= 3 and (parts[0], parts[1], ".".join(parts[2:])) in r4_wire:
            add("r1_exclusion", {"enum": key, "r1_unused_reason": e.get("unused")})
    # R4 cases where the table's own expectation differs
    consistent = []
    for case in audit.get("cases") or []:
        te = table_expectation(table, case)
        if te["disagreements"]:
            add("r4_case", {"case": case, "table_expectation": te})
        else:
            consistent.append(case.get("id"))
    # mechanical findings (missing dispositions grouped)
    missing = [f for f in findings if f["severity"] == "item" and f["check"] == "disposition" and "no disposition" in f["message"]]
    if missing:
        add("check_finding", {"check": "disposition", "message": "units without disposition",
                              "units": [u for f in missing for u in f["units"]]})
    for f in findings:
        if f["severity"] == "item" and f not in missing:
            add("check_finding", {"check": f["check"], "path": f["path"], "message": f["message"], "units": f["units"]})
    return items, consistent


# ------------------------------------------------------------------------------------------------
# the adjudicator call


def _slim(table):
    t = {k: v for k, v in table.items() if k not in ("units", "run_metadata")}
    t["wire_map"] = {k: v for k, v in (table.get("wire_map") or {}).items() if k != "tools"}
    return t


def build_prompt(table, api, items):
    return "\n\n".join([
        prompt_text("adjudicator.md"),
        prompt_text("engine_contract.md"),
        "# The brief as units (id [kind] exact text)\n\n" + units_listing(table["units"]),
        "# The tool API (parsed)\n\n" + api_summary(api),
        "# R1's table (units and wire_map.tools omitted)\n\n" + json.dumps(_slim(table), separators=(",", ":")),
        "# Adjudication items\n\n" + json.dumps(items, separators=(",", ":")),
        f"Decide all {len(items)} items. Return the single JSON object.",
    ])


def call_adjudicator(table, api, items, *, deadline=None, timeout_s=300):
    text, usage = models.claude_text(build_prompt(table, api, items), deadline=deadline, timeout_s=timeout_s, purpose="adjudicate")
    try:
        reply = extract_json(text, require_key="verdicts")
    except NoJSON:
        reply = {"verdicts": [], "parse_error": True}
    return reply, usage, text


# ------------------------------------------------------------------------------------------------
# applying verdicts


def _quotes_of(item):
    q = []
    if item["kind"] == "r4_item":
        q.append(("R4", item["r4"].get("quote")))
        for o in item["candidates"]["obligations"]:
            q.append((o["id"], o.get("quote")))
    elif item["kind"] == "r1_exclusion" and item.get("text"):
        q.append((item.get("unit"), item.get("text")))
    return [{"source": s, "quote": t} for s, t in q if t]


def apply_verdicts(table, items, reply):
    """One correction cycle. Returns (table, log)."""
    by_id = {it["item_id"]: it for it in items}
    verdicts = {}
    for v in reply.get("verdicts") or []:
        if isinstance(v, dict) and v.get("item_id") in by_id and v.get("item_id") not in verdicts:
            verdicts[v["item_id"]] = v
    log = []
    for iid, it in by_id.items():
        v = verdicts.get(iid)
        entry = {"item_id": iid, "kind": it["kind"], "outcome": (v or {}).get("outcome", "undecided"),
                 "citations": (v or {}).get("citations", []), "reasoning": (v or {}).get("reasoning", ""),
                 "r1_position": (v or {}).get("r1_position"), "r4_position": (v or {}).get("r4_position"),
                 "quotes": _quotes_of(it), "applied": False}
        if it["kind"] == "r4_item":
            entry["r4_id"] = it["r4"].get("id")
        if v and v.get("outcome") == "contested":
            rule = v.get("interpretation_rule")
            entry.update({"readings": v.get("readings", []), "taken": v.get("taken"),
                          "interpretation_rule": rule if rule in INTERPRETATION else None,
                          "distinguishing_expectation": v.get("distinguishing_expectation")})
        if v and v.get("outcome") in ("overturned", "contested") and v.get("correction"):
            entry["correction"] = v["correction"]
        log.append(entry)
    order = sorted([e for e in log if e["outcome"] == "overturned" and e.get("correction")], key=lambda e: _natkey(e["item_id"]))
    order += sorted([e for e in log if e["outcome"] == "contested" and e.get("correction")],
                    key=lambda e: (e.get("interpretation_rule") or 9, _natkey(e["item_id"])))
    touched = {}
    for e in order:
        ops = e["correction"] if isinstance(e["correction"], list) else [e["correction"]]
        paths = [p for op in ops if isinstance(op, dict) for p in op_paths(op)]
        clash = [p for p in paths if p in touched]
        if clash:
            e["correction_error"] = f"conflict with {touched[clash[0]]} on {clash[0]}"
            continue
        try:
            new, done = apply_ops(table, ops)
        except OpError as err:
            e["correction_error"] = str(err)
            continue
        errs = validation_errors(new)
        if errs:
            e["correction_error"] = f"schema: {errs[0]['message'][:200]}"
            continue
        table = new
        e["applied"] = True
        e["applied_ops"] = done
        for p in paths:
            touched[p] = e["item_id"]
    oq = list(table.get("open_questions") or [])
    for e in log:
        if e["outcome"] == "contested":
            rule = e.get("interpretation_rule")
            oq.append({"topic": f"{e['item_id']}: " + str(e.get("r4_position") or e.get("reasoning") or "")[:200],
                       "readings": [str(r) for r in e.get("readings") or []], "taken": str(e.get("taken") or ""),
                       "rule": f"interpretation order ({rule}) {INTERPRETATION.get(rule, 'not stated')}"})
    if oq != (table.get("open_questions") or []):
        table = copy.deepcopy(table)
        table["open_questions"] = oq
    return table, log


def summarize(log):
    out = {"accepted": 0, "overturned": 0, "contested": 0, "undecided": 0, "applied": 0, "rejected_corrections": 0}
    for e in log:
        out[e["outcome"]] = out.get(e["outcome"], 0) + 1
        out["applied"] += int(e["applied"])
        out["rejected_corrections"] += int(bool(e.get("correction_error")))
    return out


def adjudicate(table, api, audit, findings, *, deadline=None, timeout_s=300):
    """Pair, call, apply. Returns (table, record) where record = {items, verdict reply, log, summary, usages}."""
    items, consistent = build_items(table, audit, findings)
    record = {"items": items, "consistent_cases": consistent, "usages": [], "raw": ""}
    if not items:
        record.update(log=[], summary=summarize([]))
        return table, record
    reply, usage, text = call_adjudicator(table, api, items, deadline=deadline, timeout_s=timeout_s)
    record["usages"].append(usage)
    record["raw"] = text
    record["new_positions"] = reply.get("new_positions", [])
    record["adjudicator_summary"] = reply.get("summary")
    table, log = apply_verdicts(table, items, reply)
    record["log"] = log
    record["summary"] = summarize(log)
    return table, record


# ------------------------------------------------------------------------------------------------
# freeze


def canonical(table: dict) -> str:
    return json.dumps({k: v for k, v in table.items() if k != "run_metadata"}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def table_hash(table: dict) -> str:
    return hashlib.sha256(canonical(table).encode()).hexdigest()


def freeze(table: dict, run_metadata: dict) -> dict:
    t = copy.deepcopy(table)
    rm = dict(t.get("run_metadata") or {})
    rm.update(run_metadata)
    rm["table_hash"] = table_hash(t)
    t["run_metadata"] = rm
    return t


def main(argv=None):
    """Re-run Step 2 and Step 3 on a finished reading with a (late) R4 audit:
    .venv/bin/python -m builder.readers.adjudicate runs/<id>/table.json runs/<r4>/r4.json API.json --out runs/<id>/adjudicated/"""
    import argparse
    import pathlib
    import time

    from .api_file import load_api
    from .checks import run_checks

    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("audit")
    ap.add_argument("api")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    table = json.loads(pathlib.Path(a.table).read_text())
    prior = table.pop("run_metadata", {})
    audit = json.loads(pathlib.Path(a.audit).read_text())
    api = load_api(a.api)
    checks = run_checks(table, api)
    t0 = time.monotonic()
    new, record = adjudicate(table, api, audit, checks["findings"], timeout_s=600)
    seconds = round(time.monotonic() - t0, 1)
    after = run_checks(new, api)
    frozen = freeze(new, {**prior, "adjudication": record.get("summary"), "assurance": audit.get("assurance", "two model families"),
                          "findings": {"before": checks["counts"], "after": after["counts"]},
                          "adjudication_seconds": seconds, "adjudication_usage": record.get("usages")})
    (out / "table.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
    (out / "adjudication.json").write_text(json.dumps({k: v for k, v in record.items()}, indent=1, ensure_ascii=False, default=str))
    (out / "checks.json").write_text(json.dumps({"before": checks, "after": after}, indent=1))
    print(json.dumps({"seconds": seconds, "items": len(record.get("items", [])), "summary": record.get("summary"),
                      "findings_before": checks["counts"], "findings_after": after["counts"],
                      "table_hash": frozen["run_metadata"]["table_hash"], "usage": record.get("usages")}, indent=1, default=str))


if __name__ == "__main__":
    main()
