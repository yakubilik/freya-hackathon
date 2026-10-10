"""Compare a produced rule table with a reference (hand-written) table.

    .venv/bin/python -m builder.readers.compare runs/<id>/table.json fixtures/tables/brief-a.json [--json out.json]

The two tables use different unit ids, so reference units are mapped to produced units by their text
(``segment.locate_quote``). Reported: parameters present/absent/different by path (with the differing sub-keys),
obligations matched by cited unit (missed, extra, matched with differing close/tool actions), phrases by id,
closing rows by outcome/reason with their triggers.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .segment import locate_quote


def _value(e):
    if not isinstance(e, dict):
        return None
    if e.get("confidence") == "not_specified" or "value" not in e:
        return "NOT SPECIFIED"
    return e["value"]


def _short(v, n=160):
    s = json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


def _diff_value(a, b, path=""):
    """Leaf-level differences between two JSON values (a = produced, b = reference)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k in ("obligation", "obligations", "units", "quotes", "line"):
                continue
            if k not in a:
                out.append(f"{path}.{k}: missing (ref {_short(b[k], 80)})")
            elif k not in b:
                out.append(f"{path}.{k}: extra ({_short(a[k], 80)})")
            else:
                out += _diff_value(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and all(isinstance(x, dict) for x in a + b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff_value(x, y, f"{path}[{i}]")
        return out
    if json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str):
        return [f"{path or '.'}: {_short(a, 80)} != ref {_short(b, 80)}"]
    return []


def unit_map(ref_units: dict, units: dict) -> dict:
    """Reference unit id -> produced unit ids."""
    out = {}
    for uid, u in ref_units.items():
        text = u.get("text") or ""
        # reference rows are often rewritten as "header: cell; ..."; fall back to the cell words
        loc = locate_quote(text, units)
        if not loc["units"] and ";" in text:
            cells = [part.split(":", 1)[-1].strip() for part in text.split(";")]
            loc = locate_quote(" | ".join(cells), units)
        out[uid] = loc["units"]
    return out


def _actions(o):
    acts = set()
    for a in o.get("then") or []:
        if not isinstance(a, dict) or len(a) != 1:
            continue
        k, v = next(iter(a.items()))
        if k == "close":
            acts.add(f"close:{(v or {}).get('outcome')}/{(v or {}).get('reason')}")
        elif k == "tool":
            acts.add(f"tool:{(v or {}).get('name')}")
        elif k == "transfer":
            acts.add(f"transfer:{(v or {}).get('queue')}")
        elif k == "note":
            acts.add(f"note:{(v or {}).get('reason')}")
        else:
            acts.add(k)
    return acts


def compare(produced: dict, reference: dict) -> dict:
    pp, rp = produced.get("parameters") or {}, reference.get("parameters") or {}
    params = {"absent": [], "extra": [], "same": [], "different": {}, "not_specified_in_produced": []}
    for path in sorted(set(pp) | set(rp)):
        if path not in pp:
            params["absent"].append(path)
        elif path not in rp:
            params["extra"].append(path)
        else:
            a, b = _value(pp[path]), _value(rp[path])
            if a == "NOT SPECIFIED" and b != "NOT SPECIFIED":
                params["not_specified_in_produced"].append(path)
            d = _diff_value(a, b)
            if d:
                params["different"][path] = d[:12]
            else:
                params["same"].append(path)

    umap = unit_map(reference.get("units") or {}, produced.get("units") or {})
    prod_by_unit = {}
    for o in produced.get("obligations") or []:
        for u in o.get("units") or []:
            prod_by_unit.setdefault(u, []).append(o)
    matched_prod = set()
    obl = {"missed": [], "matched": 0, "action_diffs": [], "extra": []}
    for o in reference.get("obligations") or []:
        mapped = [u for ru in o.get("units") or [] for u in umap.get(ru, [])]
        cands = {c["id"]: c for u in mapped for c in prod_by_unit.get(u, [])}
        if not cands:
            obl["missed"].append({"id": o["id"], "quote": (o.get("quote") or "")[:140], "mapped_units": mapped})
            continue
        obl["matched"] += 1
        matched_prod.update(cands)
        ra = _actions(o)
        pa = set().union(*(_actions(c) for c in cands.values()))
        key = {x for x in ra ^ pa if x.startswith(("close:", "tool:", "transfer:", "note:"))}
        if key:
            obl["action_diffs"].append({"ref": o["id"], "produced": sorted(cands), "only_ref": sorted(key & ra),
                                        "only_produced": sorted(key & pa)})
    ref_units_mapped = {u for us in umap.values() for u in us}
    for o in produced.get("obligations") or []:
        if o["id"] not in matched_prod:
            obl["extra"].append({"id": o["id"], "quote": (o.get("quote") or "")[:140],
                                 "unit_in_reference_text": any(u in ref_units_mapped for u in o.get("units") or [])})
    obl["counts"] = {"reference": len(reference.get("obligations") or []), "produced": len(produced.get("obligations") or []),
                     "missed": len(obl["missed"]), "extra": len(obl["extra"])}

    rph = {p["id"]: p for p in reference.get("phrases") or []}
    pph = {p["id"]: p for p in produced.get("phrases") or []}
    phrases = {"absent": sorted(set(rph) - set(pph)), "extra": sorted(set(pph) - set(rph)), "text_differs": []}
    for pid in sorted(set(rph) & set(pph)):
        a, b = pph[pid], rph[pid]
        if (a.get("text") or "").strip() != (b.get("text") or "").strip() or bool(a.get("exact")) != bool(b.get("exact")):
            phrases["text_differs"].append({"id": pid, "produced": a.get("text"), "exact": a.get("exact"),
                                            "ref": b.get("text"), "ref_exact": b.get("exact")})

    def rows(t):
        return {(r.get("outcome"), r.get("reason")): r for r in _value((t.get("parameters") or {}).get("closing.rows")) or []
                if isinstance(r, dict)} if isinstance(_value((t.get("parameters") or {}).get("closing.rows")), list) else {}
    pr, rr = rows(produced), rows(reference)
    closing = {"absent": sorted(map(str, set(rr) - set(pr))), "extra": sorted(map(str, set(pr) - set(rr))), "trigger_diffs": []}
    for k in sorted(set(pr) & set(rr), key=str):
        if sorted(pr[k].get("triggers") or []) != sorted(rr[k].get("triggers") or []) or pr[k].get("precedence") != rr[k].get("precedence"):
            closing["trigger_diffs"].append({"row": list(k), "produced": pr[k].get("triggers"), "ref": rr[k].get("triggers"),
                                             "precedence": [pr[k].get("precedence"), rr[k].get("precedence")]})
    plan = {"produced": [s.get("type") for s in produced.get("plan") or []], "ref": [s.get("type") for s in reference.get("plan") or []]}
    return {"parameters": params, "obligations": obl, "phrases": phrases, "closing_rows": closing, "plan": plan,
            "amendments": {"produced": len(produced.get("amendments") or []), "ref": len(reference.get("amendments") or [])}}


def render(c: dict) -> str:
    p, o, ph, cr = c["parameters"], c["obligations"], c["phrases"], c["closing_rows"]
    lines = [f"parameters: same {len(p['same'])}, different {len(p['different'])}, absent {len(p['absent'])}, extra {len(p['extra'])}",
             f"  absent: {p['absent']}", f"  extra: {p['extra']}", f"  not specified in produced: {p['not_specified_in_produced']}"]
    for path, d in p["different"].items():
        lines.append(f"  ~ {path}: " + " | ".join(d[:4]))
    lines.append(f"obligations: {o['counts']}, matched {o['matched']}, action diffs {len(o['action_diffs'])}")
    for m in o["missed"]:
        lines.append(f"  missed {m['id']}: {m['quote']}")
    for d in o["action_diffs"]:
        lines.append(f"  actions {d['ref']} vs {d['produced']}: only ref {d['only_ref']}, only produced {d['only_produced']}")
    lines.append(f"  extra (produced, no reference obligation on those units): {len(o['extra'])}")
    lines.append(f"phrases: absent {ph['absent']}, extra {ph['extra']}, text differs {len(ph['text_differs'])}")
    lines.append(f"closing rows: absent {cr['absent']}, extra {cr['extra']}, trigger/precedence diffs {len(cr['trigger_diffs'])}")
    for d in cr["trigger_diffs"]:
        lines.append(f"  {d['row']}: produced {d['produced']} vs ref {d['ref']}, precedence {d['precedence']}")
    lines.append(f"plan: produced {c['plan']['produced']} / ref {c['plan']['ref']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("produced")
    ap.add_argument("reference")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    c = compare(json.loads(pathlib.Path(a.produced).read_text()), json.loads(pathlib.Path(a.reference).read_text()))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(c, indent=1, ensure_ascii=False))
    print(render(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
