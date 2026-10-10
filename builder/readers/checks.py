"""Step 2: mechanical checks on R1's table (pure code, seconds).

``run_checks(table, api) -> findings``; a finding is
``{"id", "check", "severity": "fatal"|"item", "path", "message", "units": [...]}``.
``fatal`` means the table is unusable downstream (the emitter or engine would refuse it); ``item`` findings go to
adjudication. Examples get ``status`` verified|mismatch|unevaluated in ``example_results``.
"""
from __future__ import annotations

import re

import importlib
from builder.engine.calendar import CalendarError, EvalError, ExprError, calendar_from_table, eval_expr, parse_expr
from builder.engine.dates import resolve_date

from .r1 import validation_errors
from .segment import _soft, quote_in_units

ENGINE_TRIGGERS = {"promise_recorded", "paid_claim", "all_items_noted_paid", "attempts_exhausted", "dont_want_twice_verified",
                   "dont_want_twice_unverified", "hardship_support_declined", "dispute", "record_failed_twice",
                   "identity_failed", "identity_declined", "callback_booked", "callback_refused_twice", "wrong_number",
                   "deceased", "party_unclear_twice", "fetch_failed_twice"}
ENGINE_TRIGGER_PREFIXES = ("transfer_done:", "first_non_paid_note:")
PLAN_TYPES = {"party", "verify", "consent", "say", "ask", "fetch", "disclose", "negotiate", "readback", "record", "note",
              "close", "prompt_only"}
EXPR_KEYS = {"condition", "deadline_expr", "date_expr", "days_expr", "floor_expr", "amount_rule", "then"}
EXPR_PARAMS = {"amounts.floor_expr", "dates.non_business_rule", "dates.after_deadline_rule"}
AMOUNT_WORDS = {"floor", "same", ""}
CLOSE_TOOL, TRANSFER_TOOL, NOTE_TOOL, VERIFY_TOOL = "close_call", "transfer_to_agent", "add_note", "verify_identity"
REF_RE = re.compile(r"^[a-z_]+(\.[a-z_\[\]]+)+$")


def _placeholder(v):
    """A call-time value rather than a wire literal: {{var}} or a dotted reference such as close.outcome."""
    return isinstance(v, str) and ("{{" in v or "{" in v or bool(REF_RE.match(v)))


class _F:
    def __init__(self):
        self.items = []

    def add(self, check, severity, path, message, units=None):
        self.items.append({"id": f"M-{len(self.items) + 1}", "check": check, "severity": severity, "path": path,
                           "message": message, "units": list(units or [])})


def _req_enum(api_tools, tool, field):
    t = api_tools.get(tool) or {}
    return (t.get("request_fields") or {}).get(field, {}).get("enum")


def _param(table, path):
    e = (table.get("parameters") or {}).get(path)
    if not isinstance(e, dict) or e.get("confidence") == "not_specified" or "value" not in e:
        return None
    return e["value"]


def _actions(table):
    for o in table.get("obligations") or []:
        for i, a in enumerate(o.get("then") or []):
            if isinstance(a, dict) and len(a) == 1:
                k = next(iter(a))
                yield o, i, k, a[k]


# ------------------------------------------------------------------------------------------------


def check_quotes(table, f):
    units = table.get("units") or {}
    for o in table.get("obligations") or []:
        bad = [u for u in o.get("units") or [] if u not in units]
        if bad:
            f.add("unit_exists", "item", f"obligations/{o.get('id')}", f"cites unknown units {bad}", o.get("units"))
        if not o.get("quote"):
            f.add("quote", "item", f"obligations/{o.get('id')}", "empty quote", o.get("units"))
        elif quote_in_units(o["quote"], o.get("units") or [], units) is None:
            f.add("quote", "item", f"obligations/{o.get('id')}", f"quote not in cited units: {o['quote'][:120]!r}", o.get("units"))
    for path, e in (table.get("parameters") or {}).items():
        cited = [u for u in e.get("units") or [] if u in units]
        for u in e.get("units") or []:
            if u not in units:
                f.add("unit_exists", "item", f"parameters/{path}", f"cites unknown unit {u}")
        for q in e.get("quotes") or []:
            if e.get("confidence") == "derived":
                continue  # a derived entry explains its computation in quotes
            ok = quote_in_units(q, cited, units) if cited else _quote_anywhere(q, units)
            if not ok:
                f.add("quote", "item", f"parameters/{path}", f"quote not in cited units: {q[:120]!r}", cited)
    for i, a in enumerate(table.get("amendments") or []):
        cited = [a.get("amending_unit")] + list(a.get("amended_units") or [])
        for q in a.get("quotes") or []:
            if not quote_in_units(q, [u for u in cited if u in units], units):
                f.add("quote", "item", f"amendments/{i}", f"quote not in amending or amended units: {q[:120]!r}", cited)
    for ph in table.get("phrases") or []:
        if ph.get("exact") and ph.get("kind") == "mandatory" and not _phrase_in_brief(ph.get("text") or "", units):
            f.add("phrase_source", "item", f"phrases/{ph.get('id')}", f"exact phrase not found in the brief: {ph.get('text')!r}")


def _quote_anywhere(q, units):
    sq = _soft(q)
    return bool(sq) and any(sq in _soft(u["text"]) for u in units.values())


def _phrase_in_brief(text, units):
    pat = re.escape(_soft(text))
    pat = re.sub(r"\\\{[a-z_]+\\\}", r".{1,40}", pat)  # placeholders match whatever the brief wrote there
    pat = pat.replace(r"\{", "{").replace(r"\}", "}")
    return any(re.search(pat, _soft(u["text"])) for u in units.values())


def check_dispositions(table, f):
    units = table.get("units") or {}
    disp = table.get("dispositions") or {}
    oids = {o.get("id") for o in table.get("obligations") or []}
    for uid in units:
        if uid not in disp:
            f.add("disposition", "item", f"dispositions/{uid}", "unit has no disposition", [uid])
    for uid, d in disp.items():
        if uid not in units:
            f.add("disposition", "item", f"dispositions/{uid}", "disposition for an unknown unit")
            continue
        refs = d.get("refs") or []
        missing = [r for r in refs if r not in oids]
        if missing:
            f.add("disposition", "item", f"dispositions/{uid}", f"refs unknown obligations {missing}", [uid])
        if d.get("kind") == "obligation" and not refs:
            f.add("disposition", "item", f"dispositions/{uid}", "obligation unit without obligation refs", [uid])
        if d.get("kind") == "superseded" and not d.get("evidence"):
            f.add("disposition", "item", f"dispositions/{uid}", "superseded without evidence unit", [uid])
    for o in table.get("obligations") or []:
        for ref in [o.get("exception_of")] + [p.split()[-1] for p in o.get("precedence") or [] if p]:
            if ref and ref.startswith("O-") and ref not in oids:
                f.add("reference", "item", f"obligations/{o.get('id')}", f"refers to unknown obligation {ref}", o.get("units"))
    seen = set()
    for o in table.get("obligations") or []:
        if o.get("id") in seen:
            f.add("reference", "item", f"obligations/{o.get('id')}", "duplicate obligation id", o.get("units"))
        seen.add(o.get("id"))


def check_wire(table, api, f):
    tools = (api or {}).get("tools") or (table.get("wire_map") or {}).get("tools") or {}
    rows = _param(table, "closing.rows") or []
    pairs = {(r.get("outcome"), r.get("reason")) for r in rows if isinstance(r, dict)}
    for o, i, k, v in _actions(table):
        p = f"obligations/{o.get('id')}/then/{i}"
        if k == "tool":
            name = (v or {}).get("name")
            if name not in tools:
                f.add("wire", "item", p, f"unknown tool {name!r}", o.get("units"))
                continue
            req = tools[name].get("request_fields") or {}
            for arg, val in ((v or {}).get("args") or {}).items():
                if arg not in req:
                    f.add("wire", "item", p, f"{name} has no request field {arg!r}", o.get("units"))
                elif "enum" in req[arg] and isinstance(val, str) and not _placeholder(val) and val not in req[arg]["enum"]:
                    f.add("wire", "item", p, f"{name}.{arg}={val!r} not in enum {req[arg]['enum']}", o.get("units"))
        elif k == "close":
            outcome, reason = (v or {}).get("outcome"), (v or {}).get("reason")
            if _placeholder(outcome) or _placeholder(reason):
                continue
            enum = _req_enum(tools, CLOSE_TOOL, "outcome")
            if enum and outcome not in enum:
                f.add("wire", "item", p, f"close outcome {outcome!r} not in enum {enum}", o.get("units"))
            renum = _req_enum(tools, CLOSE_TOOL, "reason")
            if renum and reason is not None and reason not in renum:
                f.add("wire", "item", p, f"close reason {reason!r} not in enum {renum}", o.get("units"))
            if rows and (outcome, reason) not in pairs:
                f.add("closing", "item", p, f"close {outcome}/{reason} has no closing row", o.get("units"))
        elif k == "transfer":
            enum = _req_enum(tools, TRANSFER_TOOL, "queue")
            q = (v or {}).get("queue")
            if enum and q not in enum:
                f.add("wire", "item", p, f"queue {q!r} not in enum {enum}", o.get("units"))
        elif k == "note":
            enum = _req_enum(tools, NOTE_TOOL, "reason")
            r = (v or {}).get("reason")
            if enum and r is not None and not _placeholder(r) and r not in enum:
                f.add("wire", "item", p, f"note reason {r!r} not in enum {enum}", o.get("units"))
    # identity fields
    fenum = _req_enum(tools, VERIFY_TOOL, "field")
    for q in _param(table, "identity.questions") or []:
        if isinstance(q, dict) and fenum and q.get("wire_field") not in fenum:
            f.add("wire", "item", "parameters/identity.questions", f"wire_field {q.get('wire_field')!r} not in enum {fenum}")
    # situations and closing rows
    oenum, renum = _req_enum(tools, CLOSE_TOOL, "outcome"), _req_enum(tools, CLOSE_TOOL, "reason")
    for r in rows:
        if not isinstance(r, dict):
            continue
        if oenum and r.get("outcome") not in oenum:
            f.add("wire", "item", "parameters/closing.rows", f"row outcome {r.get('outcome')!r} not in enum {oenum}", r.get("units"))
        if renum and r.get("reason") is not None and r.get("reason") not in renum:
            f.add("wire", "item", "parameters/closing.rows", f"row reason {r.get('reason')!r} not in enum {renum}", r.get("units"))
    qenum = _req_enum(tools, TRANSFER_TOOL, "queue")
    for key, s in (_param(table, "situations") or {}).items():
        if isinstance(s, dict) and qenum and s.get("transfer_queue") and s["transfer_queue"] not in qenum:
            f.add("wire", "item", f"parameters/situations.{key}", f"queue {s['transfer_queue']!r} not in enum {qenum}")
    nenum = _req_enum(tools, NOTE_TOOL, "reason")
    for r in _param(table, "notes.reasons") or []:
        if nenum and r not in nenum:
            f.add("wire", "item", "parameters/notes.reasons", f"note reason {r!r} not in enum {nenum}")
    # wire_map.enums keys and coverage of every API request enum value
    enums = (table.get("wire_map") or {}).get("enums") or {}
    api_vals = set()
    for tname, t in tools.items():
        for fld, e in (t.get("request_fields") or {}).items():
            for val in e.get("enum") or []:
                api_vals.add(f"{tname}.{fld}.{val}")
    for key in enums:
        parts = key.split(".")
        if len(parts) >= 3 and parts[0] in tools and ".".join(parts[:2]) in {f"{t}.{x}" for t in tools for x in tools[t].get("request_fields") or {}}:
            if key not in api_vals and (tools[parts[0]]["request_fields"][parts[1]].get("enum")):
                f.add("wire", "item", f"wire_map/enums/{key}", "enum key not an API enum value")
    for key in sorted(api_vals - set(enums)):
        f.add("wire", "item", f"wire_map/enums/{key}", "API enum value has no obligations and no unused reason")
    for c, e in ((table.get("wire_map") or {}).get("concepts") or {}).items():
        if isinstance(e, dict) and e.get("tool") and e["tool"] not in tools:
            f.add("wire", "item", f"wire_map/concepts/{c}", f"unknown tool {e['tool']!r}")


def check_amendments(table, f):
    units = table.get("units") or {}
    oq = " ".join(str(q.get("topic", "")) + " " + str(q.get("rule", "")) for q in table.get("open_questions") or [])
    for i, a in enumerate(table.get("amendments") or []):
        p = f"amendments/{i}"
        cited = [a.get("amending_unit")] + list(a.get("amended_units") or [])
        for u in cited:
            if u not in units:
                f.add("amendment", "item", p, f"unknown unit {u!r}", cited)
        eff = a.get("effective")
        if a.get("authority") == "explicit_effective_date" and not (isinstance(eff, dict) and eff.get("from")):
            f.add("amendment", "item", p, "effective-date amendment without effective.from", cited)
        if isinstance(eff, dict) and eff and not eff.get("anchor"):
            f.add("amendment", "item", p, "effective window without anchor", cited)
        if a.get("authority") == "inferred" and a.get("path") not in oq and a.get("amending_unit") not in oq:
            f.add("amendment", "item", p, "inferred amendment missing from open_questions", cited)
    for o in table.get("obligations") or []:
        eff = o.get("effective")
        if isinstance(eff, dict) and eff and not eff.get("anchor"):
            f.add("amendment", "item", f"obligations/{o.get('id')}", "effective window without anchor", o.get("units"))


def _expr_strings(x, path):
    """(path, expression) pairs under a parameter value."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k in EXPR_KEYS:
                for j, s in enumerate(v if isinstance(v, list) else [v]):
                    if isinstance(s, str):
                        yield f"{path}.{k}" + (f"[{j}]" if isinstance(v, list) else ""), s, k
            else:
                yield from _expr_strings(v, f"{path}.{k}")
    elif isinstance(x, list):
        for j, v in enumerate(x):
            yield from _expr_strings(v, f"{path}[{j}]")


def check_expressions(table, api, f):
    exprs = []
    for path, e in (table.get("parameters") or {}).items():
        if not isinstance(e, dict) or "value" not in e:
            continue
        v = e["value"]
        if isinstance(v, str) and (path in EXPR_PARAMS or e.get("type") == "expr"):
            exprs.append((path, v, "expr"))
        if path == "dates.this_next_rule":
            continue  # pseudo-calls with a free `w`, read by the engine as text
        exprs.extend(_expr_strings(v, path))
    for o, i, k, v in _actions(table):
        if k == "offer":
            for key in ("date_expr", "amount_rule"):
                if isinstance((v or {}).get(key), str):
                    exprs.append((f"obligations/{o.get('id')}/then/{i}.{key}", v[key], key))
    product_fields = set()
    for t in ((api or {}).get("tools") or {}).values():
        for fld in t.get("response_fields") or {}:
            if "[]" in fld:
                product_fields.add(fld.split(".")[-1])
    for path, s, key in exprs:
        if key == "amount_rule" and s.strip() in AMOUNT_WORDS:
            continue
        if key == "then" and not path.startswith("dates."):
            continue
        try:
            parse_expr(s)
        except ExprError as e:
            f.add("expression", "item", path, f"unparseable expression {s!r}: {e}")
            continue
        if product_fields:
            for m in re.finditer(r"\bproduct\.([A-Za-z_][A-Za-z0-9_]*)", s):
                if m.group(1) not in product_fields:
                    sev = "item"
                    f.add("expression", sev, path, f"product.{m.group(1)} is not a field of the lookup tool's response")


def check_closing(table, f):
    rows = _param(table, "closing.rows")
    if not isinstance(rows, list) or not rows:
        f.add("closing", "fatal", "parameters/closing.rows", "no closing rows")
        return
    oids = {o.get("id") for o in table.get("obligations") or []}
    for j, r in enumerate(rows):
        p = f"parameters/closing.rows[{j}]"
        trig = r.get("triggers") or []
        if not trig:
            f.add("closing", "item", p, f"row {r.get('outcome')}/{r.get('reason')} has no trigger", r.get("units"))
        for t in trig:
            if t not in ENGINE_TRIGGERS and not str(t).startswith(ENGINE_TRIGGER_PREFIXES):
                f.add("closing", "item", p, f"trigger {t!r} is not an engine trigger", r.get("units"))
        obs = r.get("obligations") or []
        if not obs:
            f.add("closing", "item", p, f"row {r.get('outcome')}/{r.get('reason')} has no trigger obligation", r.get("units"))
        for oid in obs:
            if oid not in oids:
                f.add("closing", "item", p, f"row cites unknown obligation {oid}", r.get("units"))


def check_plan(table, f):
    plan = table.get("plan") or []
    if not plan:
        return  # the emitter uses the default order
    types = [s.get("type") for s in plan]
    for s in plan:
        if s.get("type") not in PLAN_TYPES:
            f.add("plan", "fatal", f"plan/{s.get('id')}", f"unknown stage type {s.get('type')!r}")
    if types[0] != "party":
        f.add("plan", "fatal", "plan", "the first stage is not party")
    if types[-1] != "close":
        f.add("plan", "fatal", "plan", "close_call is not last: the last stage is not close")
    if "verify" in types:
        v = types.index("verify")
        for later in ("fetch", "disclose", "record", "note"):
            if later in types and types.index(later) < v:
                f.add("plan", "fatal", "plan", f"{later} before the first verify")
    for t in set(types):
        if types.count(t) > 1:
            f.add("plan", "item", "plan", f"stage type {t} repeated")
    oids = {o.get("id") for o in table.get("obligations") or []}
    for s in plan:
        for oid in s.get("obligations") or []:
            if oid not in oids:
                f.add("plan", "item", f"plan/{s.get('id')}", f"unknown obligation {oid}")
    # close_call is the last tool call inside every obligation's actions
    for o in table.get("obligations") or []:
        tools_in = [(a.get("tool") or {}).get("name") for a in o.get("then") or [] if isinstance(a, dict) and "tool" in a]
        if CLOSE_TOOL in tools_in and tools_in[-1] != CLOSE_TOOL:
            f.add("plan", "item", f"obligations/{o.get('id')}", "a tool call follows close_call")


def check_emitter(table, api, f):
    """The workflow generator's own plan and closing-row preconditions (it raises EmitError on these)."""
    try:
        from builder.emitter.emit import Ctx, resolve_plan
        from builder.emitter.fragments import EmitError
    except ImportError:  # pragma: no cover - emitter lane absent
        return
    try:
        resolve_plan(table, Ctx(table, api or {"tools": {}}, "https://example.invalid"))
    except EmitError as e:
        f.add("emitter", "item", "plan", f"the workflow generator refuses the table: {e}")
    except Exception as e:  # noqa: BLE001 - a generator crash is reported, not raised
        f.add("emitter", "item", "plan", f"the workflow generator crashed on the table: {type(e).__name__}: {e}")


def check_basics(table, f):
    if not table.get("obligations"):
        f.add("schema", "fatal", "obligations", "no obligations")
    for e in validation_errors(table):
        f.add("schema", "fatal", "/".join(map(str, e["path"])), e["message"])
    if not _param(table, "identity.questions"):
        f.add("identity", "item", "parameters/identity.questions", "no identity questions")


# ------------------------------------------------------------------------------------------------
# examples


def _same(a, b):
    return str(a)[:10] == str(b)[:10] if a is not None and b is not None else a == b


def evaluate_example(table, ex):
    """(status, detail): verified | mismatch | unevaluated."""
    inp, exp = ex.get("input"), ex.get("expected")
    if not isinstance(inp, dict):
        return "unevaluated", "input is not an object"
    now = inp.get("now")
    cal, _ = calendar_from_table(table)
    try:
        C = importlib.import_module("builder.engine.step")._context(table, now or "2026-01-01T00:00")
    except Exception as e:  # pragma: no cover - defensive
        return "unevaluated", f"engine context: {e}"
    ctx = {"now": C["now"], "cal": cal, "rules": C["rules"], "product": dict(inp.get("product") or {}),
           "customer": {}, "call": {}}
    for k, v in inp.items():
        if k not in ("now", "text", "expr", "product"):
            ctx["product"].setdefault(k, v)
    try:
        if isinstance(inp.get("expr"), str):
            got = eval_expr(inp["expr"], ctx)
            return ("verified" if _same(got, exp) else "mismatch"), f"{inp['expr']} -> {got}"
        if isinstance(inp.get("text"), str) and now:
            r = resolve_date(inp["text"], now, C["rules"])
            if r.get("kind") != "exact":
                if isinstance(exp, str) and re.match(r"\d{4}-\d{2}-\d{2}", exp):
                    return "unevaluated", f"resolve_date gives {r.get('kind')} for {inp['text']!r}"
                return "unevaluated", "not a date example"
            if isinstance(exp, str) and re.match(r"\d{4}-\d{2}-\d{2}", exp):
                return ("verified" if r["date"] == exp else "mismatch"), f"{inp['text']!r} -> {r['date']}"
            return "unevaluated", "expected is not a date"
        if isinstance(exp, dict) and ("band" in exp or "deadline" in exp) and ctx["product"] and now:
            for b in _param(table, "bands") or []:
                if eval_expr(b.get("condition", "false"), ctx):
                    got = {"band": b.get("id"), "deadline": str(eval_expr(b.get("deadline_expr", ""), ctx)),
                           "attempts": b.get("attempts")}
                    bad = [k for k in exp if k in got and not _same(got[k], exp[k])]
                    return ("mismatch" if bad else "verified"), f"{got}"
            return "mismatch", "no band matches"
        if isinstance(exp, str) and re.match(r"\d{4}-\d{2}-\d{2}$", exp) and now:
            # a date example: any expression of a parameter citing the example's unit must give it
            cands = []
            for path, e in (table.get("parameters") or {}).items():
                if ex.get("unit") in (e.get("units") or []) and "value" in e:
                    cands += [s for _, s, k in _expr_strings(e["value"], path) if k in ("date_expr", "deadline_expr")]
            got = []
            for s in cands:
                try:
                    got.append(str(eval_expr(s, ctx)))
                except (ExprError, EvalError, CalendarError, ValueError, TypeError):
                    continue
            if not got:
                return "unevaluated", "no evaluable expression cites the unit"
            return ("verified" if exp in got else "mismatch"), f"candidates gave {got}"
    except (ExprError, EvalError, CalendarError, ValueError, TypeError, KeyError) as e:
        return "unevaluated", f"{type(e).__name__}: {e}"
    return "unevaluated", "shape not evaluable"


def check_examples(table, f):
    results = []
    for j, ex in enumerate(table.get("examples") or []):
        status, detail = evaluate_example(table, ex)
        results.append({"index": j, "unit": ex.get("unit"), "status": status, "detail": detail})
        if status == "mismatch":
            f.add("example", "item", f"examples/{j}", f"worked example disagrees with the table: {detail}", [ex.get("unit")])
    return results


def run_checks(table: dict, api: dict | None = None) -> dict:
    """All Step 2 checks. Returns {findings, example_results, counts}."""
    f = _F()
    check_basics(table, f)
    check_quotes(table, f)
    check_dispositions(table, f)
    check_wire(table, api, f)
    check_amendments(table, f)
    check_expressions(table, api, f)
    check_closing(table, f)
    check_plan(table, f)
    check_emitter(table, api, f)
    examples = check_examples(table, f)
    counts = {"fatal": sum(1 for x in f.items if x["severity"] == "fatal"),
              "item": sum(1 for x in f.items if x["severity"] == "item")}
    for x in f.items:
        counts[x["check"]] = counts.get(x["check"], 0) + 1
    return {"findings": f.items, "example_results": examples, "counts": counts}
