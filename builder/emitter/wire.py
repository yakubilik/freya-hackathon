"""Wire names: the tool API's own field names for what the engine knows by canonical names.

The organisers keep the seven tool names but "the fields and the allowed values can change" (kit README, "The final").
The engine speaks canonical names (verify_identity: field, answer; create_promise: product_id, amount, date; responses:
verified, wrong_answers_left, all_verified, hint, products[].type/past_due/days_late/...). This module reads the parsed
API (builder.readers.api_file.parse_api) and derives, by field type and name, (1) the request map canonical -> wire per
tool, (2) the shared request field that carries the customer id, (3) the response map wire -> canonical per tool plus the
list key and item keys of get_account, and (4) which fields are in cents. Standard library only; the response
normaliser is also rendered as code for the write_result node (it runs in the platform's sandbox).
"""
import re

CANONICAL_REQUEST = {"verify_identity": ["field", "answer"], "get_account": [], "create_promise": ["product_id", "amount", "date"],
                     "add_note": ["product_id", "reason", "text"], "schedule_callback": ["date", "time", "reason"],
                     "transfer_to_agent": ["queue"], "close_call": ["outcome", "reason"]}


def _tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def _has(name, *words):
    toks = _tokens(name)
    low = name.lower()
    return any(w in toks or w in low for w in words)


def _pick(fields, used, *tests):
    """The first field (not yet used) satisfying a test; tests in order of preference."""
    for test in tests:
        for name, schema in fields.items():
            if name in used:
                continue
            if test(name, schema or {}):
                used.add(name)
                return name
    return None


def customer_id_field(api):
    """The request field every tool shares: the customer id, whatever it is called (customer_id, client_ref, account_no)."""
    sets = [set(t.get("request_fields") or {}) for t in api["tools"].values() if t.get("request_fields")]
    common = set.intersection(*sets) if sets else set()
    for cand in ("customer_id", "customerId", "customer", "id"):
        if cand in common:
            return cand
    for c in sorted(common):
        if "customer" in c.lower() or c.lower().endswith(("id", "ref", "no", "number")):
            return c
    if len(common) == 1:
        return next(iter(common))
    return "customer_id"


def request_field_map(api):
    """{tool: {canonical: wire}} for the engine's arguments; identity when the names already match."""
    cid = customer_id_field(api)
    is_enum = lambda n, s: bool(s.get("enum"))
    is_num = lambda n, s: s.get("type") in ("number", "integer") or _has(n, "amount", "cents", "sum")
    is_date = lambda n, s: s.get("format") == "date" or _has(n, "date", "day", "by", "when") or "yyyy" in str(s.get("description") or "").lower()
    is_str = lambda n, s: s.get("type", "string") == "string"
    named = lambda *words: (lambda n, s: _has(n, *words))
    out = {}
    for tool, spec in api["tools"].items():
        fields = {k: v for k, v in (spec.get("request_fields") or {}).items() if k != cid}
        used, m = set(), {}
        if tool == "verify_identity":
            m["field"] = _pick(fields, used, is_enum, named("field", "question", "check", "kind", "type", "key"))
            m["answer"] = _pick(fields, used, named("answer", "value", "response", "reply"), is_str)
            if m["field"] is None and len(fields) == 1:
                # one question only, the answer goes into a field named after it ("birth_date"): no question field is sent
                m["answer"] = next(iter(fields))
                m["field"] = ""   # "" = the engine's argument has no wire field and is left out of the request
        elif tool == "create_promise":
            m["product_id"] = _pick(fields, used, named("product", "item", "account", "debt", "loan"), lambda n, s: n.lower().endswith("id"))
            m["amount"] = _pick(fields, used, named("amount", "sum", "value", "cents"), is_num)
            m["date"] = _pick(fields, used, is_date, named("day", "when"))
        elif tool == "add_note":
            m["reason"] = _pick(fields, used, is_enum, named("reason", "flag", "code", "category", "kind"))
            m["product_id"] = _pick(fields, used, named("product", "item", "account", "debt"), lambda n, s: n.lower().endswith("id"))
            m["text"] = _pick(fields, used, named("text", "note", "comment", "detail", "memo", "remark"), is_str)
        elif tool == "schedule_callback":
            m["time"] = _pick(fields, used, named("time", "hour", "slot"))
            m["date"] = _pick(fields, used, is_date, named("day", "when"))
            m["reason"] = _pick(fields, used, named("reason", "purpose", "cause"), is_enum) or ""
        elif tool == "transfer_to_agent":
            m["queue"] = _pick(fields, used, is_enum, named("queue", "team", "department", "target", "destination"), is_str)
        elif tool == "close_call":
            m["outcome"] = _pick(fields, used, named("outcome", "result", "status", "disposition"), is_enum)
            m["reason"] = _pick(fields, used, named("reason", "code", "detail", "cause"), is_str)
        out[tool] = {c: (m[c] if m.get(c) is not None else c) for c in CANONICAL_REQUEST.get(tool, [])}   # "" = no wire field
    return out


def _item_keys(spec, list_key, singleton=False):
    pref = list_key + ("." if singleton else "[].")
    return {k[len(pref):]: v for k, v in (spec.get("response_fields") or {}).items() if k.startswith(pref)}


def response_field_map(api):
    """Per tool: {"fields": {wire: canonical}, "list": wire name of the product list (get_account), "item": {wire: canonical}
    for the product fields, "cents": [wire fields in cents]}. Only non-identity mappings are listed."""
    out = {}
    for tool, spec in api["tools"].items():
        resp = {k: v for k, v in (spec.get("response_fields") or {}).items() if "[]." not in k}
        used, m = set(), {}
        is_bool = lambda n, s: s.get("type") == "boolean"
        is_int = lambda n, s: s.get("type") in ("integer", "number")
        is_str = lambda n, s: s.get("type", "string") == "string"
        named = lambda *words: (lambda n, s: _has(n, *words))
        both = lambda a, b: (lambda n, s: a(n, s) and b(n, s))
        if tool == "verify_identity":
            m["all_verified"] = _pick(resp, used, both(is_bool, named("all", "complete", "fully", "every")))
            m["verified"] = _pick(resp, used, both(is_bool, named("verified", "correct", "passed", "match", "accepted", "right")))
            m["wrong_answers_left"] = _pick(resp, used, both(is_int, named("left", "remaining", "attempts", "tries")))
            m["wrong_count"] = _pick(resp, used, both(is_int, named("wrong", "failed", "errors", "count", "total", "used")))
            m["hint"] = _pick(resp, used, both(is_str, named("hint", "clue")))
        elif tool == "get_account":
            lst = _pick(resp, used, lambda n, s: s.get("type") == "array")
            singleton = False
            if not lst:
                lst = _pick(resp, used, lambda n, s: s.get("type") == "object" and "." not in n)
                singleton = bool(lst)
            if lst:
                m["products"] = lst
                items = _item_keys(spec, lst, singleton)
                iu, im = set(), {}
                im["product_id"] = _pick(items, iu, named("product_id"), lambda n, s: n.lower().endswith(("id", "ref")))
                im["type"] = _pick(items, iu, named("type", "kind", "category", "product"))
                im["card_last4"] = _pick(items, iu, named("last4", "last_four", "ending", "last_4"))
                im["days_late"] = _pick(items, iu, both(is_int, named("days", "late", "overdue_days", "dpd")))
                im["minimum_payment"] = _pick(items, iu, both(is_int, named("minimum", "min", "floor")))
                im["instalment_amount"] = _pick(items, iu, both(is_int, named("instalment", "installment", "monthly", "repayment")))
                im["past_due"] = _pick(items, iu, both(is_int, named("past_due", "arrears", "overdue", "due", "balance", "outstanding", "amount")))
                item_map = {w: c for c, w in im.items() if w and w != c}
                cents = [w for w in items if "cents" in w.lower()]
                out[tool] = {"fields": {}, "list": lst if lst != "products" else None, "item": item_map, "cents": cents,
                             "singleton": singleton}
                continue
        elif tool in ("create_promise", "schedule_callback", "add_note", "transfer_to_agent", "close_call"):
            key = {"create_promise": "promise_id", "schedule_callback": "callback_id", "add_note": "note_id",
                   "transfer_to_agent": "transfer_id", "close_call": "call_id"}[tool]
            m[key] = _pick(resp, used, both(is_str, lambda n, s: n.lower().endswith(("id", "ref", "reference"))))
        fields = {w: c for c, w in m.items() if w and w != c}
        cents = [w for w in resp if "cents" in w.lower()]
        if fields or cents:
            out[tool] = {"fields": fields, "list": None, "item": {}, "cents": cents}
    return out


NORMALISER = '''
def _wire_norm(tool, data):
    """Canonical names next to the API's own (see builder/emitter/wire.py); values in cents become units."""
    spec = _RESP_MAP.get(tool)
    if not isinstance(data, dict) or not spec:
        return data
    def fix(d, fields, cents):
        d = dict(d)
        for w, c in fields.items():
            if w in d and c not in d:
                value = d[w]
                if w in cents and isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = value / 100.0
                d[c] = value
        return d
    data = fix(data, spec.get('fields') or {}, [c for c in spec.get('cents') or [] if '[]' not in c])
    lst = spec.get('list')
    if lst and lst in data and 'products' not in data:
        data['products'] = data[lst]
    if spec.get('singleton') and isinstance(data.get('products'), dict):
        data['products'] = [data['products']]
    if isinstance(data.get('products'), list) and (spec.get('item') or spec.get('cents')):
        data['products'] = [fix(p, spec.get('item') or {}, spec.get('cents') or []) if isinstance(p, dict) else p for p in data['products']]
    return data
'''


# a required request field the engine never fills (E's schedule_callback asked for a `reason` enum): a fixed, neutral value
_PREFER = {"schedule_callback": ("unavail", "not_reached", "no_answer", "third", "relative", "busy", "callback", "customer"),
           "transfer_to_agent": ("general", "default", "support", "agent"),
           "add_note": ("other", "general", "note", "info"),
           "close_call": ("other", "none", "general"),
           "create_promise": ("call", "phone", "agent", "default"),
           "verify_identity": ("phone", "call")}


def required_default(tool, name, schema):
    """A literal for a required field with no engine source, or None when nothing sensible exists (then the emitter
    raises). Enums: the value whose name fits the tool best, else the first; free strings: a neutral text; booleans: False."""
    enum = schema.get("enum") or []
    if enum:
        low = [str(v).lower() for v in enum]
        for w in _PREFER.get(tool, ()):
            for v, lv in zip(enum, low):
                if w in lv:
                    return v
        return enum[0]
    t = schema.get("type", "string")
    if t == "string":
        return "set by the phone agent during the call"
    if t == "boolean":
        return False
    return None
