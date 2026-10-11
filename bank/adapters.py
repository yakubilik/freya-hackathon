"""Build a bank `profile` from a tool API file, so the bank serves a brief whose tools have other names or fields.

    from bank.adapters import profile_from_openapi
    profile = profile_from_openapi(json.load(open("tools/openapi.json")))
    # then: POST /v1/practice/sessions {"customer": {..., "profile": profile}}

What is read from the OpenAPI document:
    - which path plays which role (verify_identity, get_account, ...), by the shape of its request body
    - the wire name of every request field of every role (`fields`), and of the customer id (`customer_id_field`)
    - the identity field names and their comparison type (`identity_types`), from the `field` enum
    - the note reason enum (`note_reasons`), the queue enum (`queues`), the outcome enum
    - which outcomes take no reason, from the reason's description ("except promise and paid") or a reason enum
The allowed reasons per outcome are not in the API file; pass `outcome_reasons` to set them (the brief's table),
otherwise every outcome not named as reasonless accepts any non-empty reason ("any").
Standard library only.
"""
import copy, re

from bank.server import CANONICAL_FIELDS, DEFAULT_PROFILE, TOOLS

ROLE_HINTS = {  # words in a path name that point at a role, used after the shape test
    "verify_identity": ("verify", "identity", "security", "check"),
    "get_account": ("account", "product", "balance", "policy", "detail"),
    "create_promise": ("promise", "payment", "arrangement", "pledge"),
    "add_note": ("note", "remark", "comment"),
    "schedule_callback": ("callback", "schedule", "call_back"),
    "transfer_to_agent": ("transfer", "handoff", "escalate", "agent"),
    "close_call": ("close", "end", "finish", "wrap"),
}


def _request_props(op):
    body = (((op or {}).get("requestBody") or {}).get("content") or {}).get("application/json") or {}
    schema = body.get("schema") or {}
    return dict(schema.get("properties") or {}), list(schema.get("required") or [])


def _post_ops(doc):
    for path, item in (doc.get("paths") or {}).items():
        op = (item or {}).get("post")
        if op is None: continue
        name = path.strip("/").split("/")[-1]
        props, required = _request_props(op)
        yield name, op, props, required


def _customer_id_field(ops):
    """The request field every tool shares: the customer id."""
    names = [set(props) for _, _, props, _ in ops if props]
    common = set.intersection(*names) if names else set()
    for cand in ("customer_id", "customerId", "customer", "id"):
        if cand in common: return cand
    for c in sorted(common):
        if "customer" in c.lower() or c.lower().endswith("id"): return c
    if len(common) == 1:
        return next(iter(common))   # the one field every tool shares is the customer id, whatever it is called (client_ref, account_no)
    return "customer_id"


def _role_of(name, props, idf):
    """The role a tool plays, from the shape of its request body, then from words in its name."""
    others = {k: v for k, v in props.items() if k != idf}
    enums = {k: v.get("enum") for k, v in others.items() if v.get("enum")}
    kinds = {k: (v.get("type"), v.get("format"), (v.get("description") or "").lower()) for k, v in others.items()}
    lname = name.lower()
    if name in TOOLS:
        return name
    if not others: return "get_account"
    if any(w in lname for w in ROLE_HINTS["verify_identity"]) and len(others) >= 2: return "verify_identity"
    if any(w in lname for w in ROLE_HINTS["close_call"]) and ("outcome" in others or enums): return "close_call"
    if any(w in lname for w in ROLE_HINTS["schedule_callback"]) and "time" in " ".join(others): return "schedule_callback"
    if any(w in lname for w in ROLE_HINTS["transfer_to_agent"]) and len(others) == 1: return "transfer_to_agent"
    if any(w in lname for w in ROLE_HINTS["add_note"]) and enums: return "add_note"
    if any(w in lname for w in ROLE_HINTS["create_promise"]) and any(t == "number" or "amount" in k.lower() for k, (t, _, _) in kinds.items()): return "create_promise"
    # shape only
    if any(t == "number" or "amount" in k.lower() for k, (t, _, _) in kinds.items()): return "create_promise"
    if "outcome" in others: return "close_call"
    if any("time" in k.lower() for k in others) and any(f == "date" or "date" in k.lower() for k, (_, f, _) in kinds.items()): return "schedule_callback"
    if len(others) == 1 and enums: return "transfer_to_agent"
    if len(others) == 2 and enums and any("answer" in k.lower() for k in others): return "verify_identity"
    if enums and "text" in " ".join(others): return "add_note"
    if enums: return "verify_identity" if len(others) == 2 else "add_note"
    return None


def _pick(props, used, *tests):
    """The first property name (not yet used) that satisfies a test, tests tried in order."""
    for test in tests:
        for k, v in props.items():
            if k in used: continue
            if test(k.lower(), v): used.add(k); return k
    return None


def _field_map(role, props, idf):
    """{canonical field -> wire field} for one role."""
    others = {k: v for k, v in props.items() if k != idf}
    used, m = set(), {}
    is_enum = lambda k, v: bool(v.get("enum"))
    named = lambda *words: (lambda k, v: any(w in k for w in words))
    is_num = lambda k, v: v.get("type") in ("number", "integer")
    is_date = lambda k, v: v.get("format") == "date" or "date" in k or "yyyy" in (v.get("description") or "").lower()
    is_str = lambda k, v: v.get("type", "string") == "string"
    if role == "verify_identity":
        m["field"] = _pick(others, used, is_enum, named("field", "question", "kind", "type"))
        m["answer"] = _pick(others, used, named("answer", "value", "response"), is_str)
        if len(others) == 1 and m["field"] is None:
            return {"field": "", "answer": next(iter(others))}
    elif role == "create_promise":
        m["product_id"] = _pick(others, used, named("product", "item", "account", "policy"), lambda k, v: k.endswith("id"))
        m["amount"] = _pick(others, used, named("amount", "sum", "value"), is_num)
        m["date"] = _pick(others, used, is_date, named("day", "when"))
    elif role == "add_note":
        m["reason"] = _pick(others, used, is_enum, named("reason", "code", "category"))
        m["product_id"] = _pick(others, used, named("product", "item", "account", "policy"), lambda k, v: k.endswith("id"))
        m["text"] = _pick(others, used, named("text", "note", "comment", "detail", "memo"), is_str)
    elif role == "schedule_callback":
        m["time"] = _pick(others, used, named("time", "hour", "slot"))
        m["date"] = _pick(others, used, is_date, named("day", "when"))
    elif role == "transfer_to_agent":
        m["queue"] = _pick(others, used, is_enum, named("queue", "team", "department", "target"), is_str)
    elif role == "close_call":
        m["outcome"] = _pick(others, used, named("outcome", "result", "status", "disposition"), is_enum)
        m["reason"] = _pick(others, used, named("reason", "code", "detail"), is_str)
    canonical = CANONICAL_FIELDS[role]
    return {c: (m.get(c) or c) for c in canonical}


def _identity_type(name, desc):
    n, d = name.lower(), (desc or "").lower()
    if "year" in n: return "digits"
    if "date" in n or "birth" in n or "dob" in n or "yyyy-mm-dd" in d: return "date"
    if "letter" in d or "alphanum" in d: return "text"
    if "digit" in n or "last4" in n or "phone" in n or "pin" in n or "digits" in d: return "digits"
    return "text"


def _reasonless_outcomes(reason_prop, outcomes):
    """Outcomes named in the reason's description as not needing one: "except promise and paid"."""
    desc = (reason_prop or {}).get("description") or ""
    m = re.search(r"except\s+(.+?)(?:\.|$)", desc, re.I)
    if not m: return []
    words = re.split(r"[,\s]+|\band\b|\bor\b", m[1])
    return [o for o in outcomes if o in words]


def profile_from_openapi(doc, outcome_reasons=None, overrides=None):
    """A bank profile for the tool API in `doc` (a parsed OpenAPI document). See the module docstring."""
    ops = list(_post_ops(doc))
    idf = _customer_id_field(ops)
    profile = {"customer_id_field": idf, "tools": {}, "fields": {}, "identity_types": {}}
    roles = {}
    for name, op, props, required in ops:
        role = _role_of(name, props, idf)
        if role is None or role in roles: continue
        roles[role] = (name, props, required)
    for role in TOOLS:
        if role not in roles: continue
        name, props, required = roles[role]
        profile["tools"][role] = name
        fmap = _field_map(role, props, idf)
        profile["fields"][role] = fmap
        if role == "verify_identity":
            field_prop = props.get(fmap["field"]) or {}
            answer_desc = (props.get(fmap["answer"]) or {}).get("description") or ""
            for f in field_prop.get("enum") or []:
                # the answer description often says per field how it is sent ("For date_of_birth: the date as YYYY-MM-DD")
                m = re.search(re.escape(f) + r"[^.]*?[:]\s*([^.]*)", answer_desc)
                profile["identity_types"][f] = _identity_type(f, m[1] if m else "")
            profile["identity_fields"] = list(field_prop.get("enum") or [])
        elif role == "add_note":
            enum = (props.get(fmap["reason"]) or {}).get("enum")
            if enum: profile["note_reasons"] = list(enum)
        elif role == "transfer_to_agent":
            enum = (props.get(fmap["queue"]) or {}).get("enum")
            if enum: profile["queues"] = list(enum)
        elif role == "close_call":
            outcomes = list((props.get(fmap["outcome"]) or {}).get("enum") or [])
            reason_prop = props.get(fmap["reason"]) or {}
            reason_enum = reason_prop.get("enum")
            table = copy.deepcopy(outcome_reasons) if outcome_reasons else {}
            if outcomes:
                reasonless = _reasonless_outcomes(reason_prop, outcomes)
                for o in outcomes:
                    if o in table: continue
                    table[o] = [] if o in reasonless else (list(reason_enum) if reason_enum else "any")
                profile["outcome_reasons"] = table
            elif table: profile["outcome_reasons"] = table
    for k, v in (overrides or {}).items(): profile[k] = v
    return profile


def describe(profile):
    """One line per tool: wire name and field map, for a quick look."""
    lines = []
    for role in TOOLS:
        name = profile.get("tools", {}).get(role, role)
        fm = profile.get("fields", {}).get(role, {})
        renamed = {c: w for c, w in fm.items() if c != w}
        lines.append(f"{role:<18} -> /{name}" + (f"  fields {renamed}" if renamed else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    import json, sys
    p = profile_from_openapi(json.load(open(sys.argv[1])))
    print(describe(p)); print(json.dumps({k: v for k, v in p.items() if k not in ("tools", "fields")}, indent=1))
