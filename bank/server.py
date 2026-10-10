"""A local copy of the hackathon's mock bank, with everything configurable.

It answers the seven tool calls the way the organizers' bank does (same fields, same error texts, same
status codes, same ledger), so a phone agent cannot tell the two apart. Unlike theirs it accepts any
customer: any date and time, any products, any identity questions, any tool fault, and a tool API with
other field names.

    python3 bank/server.py --port 8787 --cases kit/build-the-builder/public-test-set.json

Routes, all under /v1:
    POST /<tool>                      the seven tools; the body carries customer_id
    POST /practice/sessions           {"case": "PUB-01"} or {"customer": {...}} -> {"ok": true, "variables": {...}}
    GET  /practice/ledger/<customer_id>
    GET  /health

A custom customer looks like a case of public-test-set.json (see spec/interfaces.md, section 3):
    {"variables": {"first_name", "last_name", "title", "now"}, "identity": {"date_of_birth": "1988-03-14", ...},
     "products": [...], "faults": [{"tool": "create_promise", "fail_first_n": 2}], "profile": {...}}

Faults, one entry per tool: {"tool": name, "fail_first_n": n}        the first n calls answer 500
                            {"tool": name, "fail_on_call": n}        only the n-th call answers 500
                            {"tool": name, "slow_ms": 20000, "on_call": n}   sleep before answering (every call if no on_call)
`profile` overrides DEFAULT_PROFILE for a brief whose tool API has other fields, values or behaviour.
Standard library only.
"""
import argparse, copy, hashlib, json, re, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")

# The canonical request fields of every tool. `fields` in a profile maps each one to its wire name.
CANONICAL_FIELDS = {
    "verify_identity": ["field", "answer"],
    "get_account": [],
    "create_promise": ["product_id", "amount", "date"],
    "add_note": ["product_id", "reason", "text"],
    "schedule_callback": ["date", "time"],
    "transfer_to_agent": ["queue"],
    "close_call": ["outcome", "reason"],
}

DEFAULT_PROFILE = {
    "max_wrong": 3,
    # identity field -> how an answer is compared: "date" (several spoken forms, swap hint), "digits" (non-digits
    # stripped), "text" (case and spaces ignored). Fields not listed are typed from the case's answer.
    "identity_types": {"date_of_birth": "date", "phone_last4": "digits"},
    "note_reasons": ["refused", "hardship", "dispute", "paid", "service_error"],
    "queues": ["restructuring", "general", "support"],
    # outcome -> allowed reasons. [] means the outcome takes no reason; "any" means any non-empty string.
    "outcome_reasons": {
        "promise": [], "paid": [],
        "transferred": ["restructuring", "human", "support"],
        "no_promise": ["refused", "hardship", "dispute", "service_error"],
        "not_verified": ["failed", "declined"],
        "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"],
    },
    # wire names: tool role -> path name, and tool role -> {canonical field -> wire field}
    "customer_id_field": "customer_id",
    "tools": {t: t for t in TOOLS},
    "fields": {t: {f: f for f in fs} for t, fs in CANONICAL_FIELDS.items()},
    # observed-but-undocumented behaviours of the organizers' bank; each can be switched off
    "hint_once": True,                       # the day_month_swapped hint is given once per call, the next swap counts as wrong
    "passed_field_omits_all_verified": True, # a field that already passed answers success without `all_verified`
    "note_product_unchecked": True,          # add_note accepts any or no product_id
    "reason_rejected_on_reasonless": True,   # a reason sent with promise/paid is rejected (off: ignored, stored as null)
}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
ERR_FAULT = {"ok": False, "error": "service unavailable, nothing was recorded"}
ERR_CLOSED = {"ok": False, "error": "the call is already closed"}
ERR_NOT_VERIFIED = {"ok": False, "error": "identity not verified"}


def read_date(text):
    """A spoken or written date as (year, month, day), unchecked, or None when it cannot be read.
    Numbers only are read as day, month, year, except the ISO form year-month-day."""
    s = str(text if text is not None else "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m: return int(m[1]), int(m[2]), int(m[3])
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s)
    if m: return int(m[3]), int(m[2]), int(m[1])
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+),?\s+(\d{4})", s)
    if m and m[2].lower() in MONTHS: return int(m[3]), MONTHS[m[2].lower()], int(m[1])
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m[1].lower() in MONTHS: return int(m[3]), MONTHS[m[1].lower()], int(m[2])
    return None


def jsnum(x):
    """Numbers the way a JavaScript service writes them: a whole float is an integer. Applied recursively."""
    if isinstance(x, bool): return x
    if isinstance(x, float) and x.is_integer(): return int(x)
    if isinstance(x, dict): return {k: jsnum(v) for k, v in x.items()}
    if isinstance(x, list): return [jsnum(v) for v in x]
    return x


def merge_profile(overrides):
    """DEFAULT_PROFILE with `overrides` applied; the nested maps (`fields`, `tools`, `identity_types`) merge per key."""
    profile = copy.deepcopy(DEFAULT_PROFILE)
    for k, v in (overrides or {}).items():
        if k == "fields" and isinstance(v, dict):
            for tool, names in v.items(): profile["fields"].setdefault(tool, {}).update(names or {})
        elif k in ("tools", "identity_types") and isinstance(v, dict): profile[k].update(v)
        else: profile[k] = copy.deepcopy(v)
    return profile


def identity_type(profile, field, answer):
    """The comparison type of one identity field: from the profile, else guessed from the case's answer."""
    t = profile["identity_types"].get(field)
    if t: return t
    s = str(answer)
    if s.isdigit(): return "digits"
    if read_date(s): return "date"
    return "text"


class Bank:
    def __init__(self, cases=()):
        self.lock = threading.Lock()
        self.cases = {c["id"]: c for c in cases}
        self.sessions = {}

    # ---- sessions -------------------------------------------------------------------------------------
    def open_session(self, body, team=""):
        if isinstance(body.get("customer"), dict): spec, case_id = body["customer"], body["customer"].get("id")
        elif body.get("case") in self.cases: spec, case_id = self.cases[body["case"]], body["case"]
        else: return 404, {"ok": False, "error": "unknown case"}
        cid = "c_" + str(uuid.uuid4())[:12]
        products = []
        for i, p in enumerate(copy.deepcopy(spec.get("products") or [])):
            products.append(jsnum({"product_id": p.pop("product_id", f"p{i + 1}"), **p}))
        profile = merge_profile(spec.get("profile"))
        identity = {k: v for k, v in (spec.get("identity") or {}).items()}
        for field, answer in identity.items(): profile["identity_types"][field] = identity_type(profile, field, answer)
        variables = {"customer_id": cid, **(spec.get("variables") or {})}
        faults = []
        for f in spec.get("faults") or []:
            faults.append({"tool": f.get("tool"), "fail_first_n": int(f.get("fail_first_n") or 0),
                           "fail_on_call": int(f.get("fail_on_call") or 0), "on_call": int(f.get("on_call") or 0),
                           "slow_ms": int(f.get("slow_ms") or 0)})
        with self.lock:
            self.sessions[cid] = {"case": case_id, "team": team, "now": variables.get("now"), "identity": identity, "products": products,
                                  "profile": profile, "faults": faults, "tool_calls": {},
                                  "verified": {}, "wrong": 0, "hinted": False, "promises": [], "notes": [], "callbacks": [], "transfers": [],
                                  "outcome": None, "reason": None, "closed": False, "failures": {}, "calls": [], "last_at": 0}
        return 200, {"ok": True, "variables": variables}

    def ledger(self, cid):
        with self.lock:
            s = self.sessions.get(cid)
            if not s: return 404, {"ok": False, "error": "unknown customer_id"}
            keys = ("case", "team", "now", "verified", "wrong", "hinted", "promises", "notes", "callbacks", "transfers", "outcome", "reason", "failures", "calls", "last_at")
            return 200, {"ok": True, **{k: copy.deepcopy(s[k]) for k in keys}}

    # ---- routing of a wire tool name to its role -----------------------------------------------------
    def resolve_tool(self, wire_name, body):
        """(role, session) for a POST /v1/<wire_name>; role is None when no profile serves that name."""
        if wire_name in TOOLS: role = wire_name
        else: role = None
        cid = body.get("customer_id") if isinstance(body, dict) else None
        s = self.sessions.get(cid) if isinstance(cid, str) else None
        # a session opened with renamed tools or a renamed customer id field
        if s is None and isinstance(body, dict):
            for cand in self.sessions.values():
                f = cand["profile"]["customer_id_field"]
                if f != "customer_id" and body.get(f) in self.sessions: s = self.sessions[body[f]]; break
        if s is not None:
            for r, name in s["profile"]["tools"].items():
                if name == wire_name: role = r
        return role, s

    # ---- the seven tools ------------------------------------------------------------------------------
    def call(self, wire_name, body):
        with self.lock:
            role, s = self.resolve_tool(wire_name, body)
            if role is None: return 404, {"ok": False, "error": "not found"}
            if s is None: return 404, {"ok": False, "error": "unknown customer_id"}
            idf = s["profile"]["customer_id_field"]
            args = {k: v for k, v in body.items() if k not in ("customer_id", idf)}
            n = s["tool_calls"][role] = s["tool_calls"].get(role, 0) + 1
            fault = self._fault(s, role, n)
        if fault and fault["slow_ms"]: time.sleep(fault["slow_ms"] / 1000)
        with self.lock:
            s["failures"].setdefault(role, 0)
            if s["closed"]: status, result = 200, dict(ERR_CLOSED)
            elif fault and (fault["fail_first_n"] or fault["fail_on_call"]):
                s["failures"][role] += 1
                status, result = 500, dict(ERR_FAULT)
            else: status, result = 200, getattr(self, "_" + role)(s, self._canonical(s, role, args))
            s["calls"].append({"n": len(s["calls"]) + 1, "tool": role, "args": args, "status": status, "result": result})
            s["last_at"] = int(time.time() * 1000)
            return status, copy.deepcopy(result)

    @staticmethod
    def _fault(s, role, n):
        """The fault entry that applies to the n-th call of `role`, or None."""
        for f in s["faults"]:
            if f["tool"] != role: continue
            if f["fail_first_n"] and n <= f["fail_first_n"]: return f
            if f["fail_on_call"] and n == f["fail_on_call"]: return f
            if f["slow_ms"] and (not f["on_call"] or n == f["on_call"]) and not f["fail_first_n"] and not f["fail_on_call"]: return f
        return None

    @staticmethod
    def _canonical(s, role, args):
        """Request args keyed by canonical field name, read through the profile's wire names."""
        names = s["profile"]["fields"].get(role, {})
        return {canon: args[wire] for canon, wire in names.items() if wire in args}

    @staticmethod
    def _wire(s, role, canon):
        return s["profile"]["fields"].get(role, {}).get(canon, canon)

    def _verified(self, s): return bool(s["identity"]) and all(s["verified"].get(f) for f in s["identity"])

    def _verify_identity(self, s, a):
        p = s["profile"]
        field, answer, left = a.get("field"), a.get("answer"), lambda: max(0, p["max_wrong"] - s["wrong"])
        if field not in s["identity"]: return {"ok": False, "error": self._wire(s, "verify_identity", "field") + " must be " + " or ".join(s["identity"])}
        if left() <= 0: return {"ok": False, "verified": False, "wrong_answers_left": 0, "error": "identity check is over"}
        if s["verified"].get(field):
            r = {"ok": True, "verified": True, "wrong_answers_left": left()}
            if not p["passed_field_omits_all_verified"]: r["all_verified"] = self._verified(s)
            return r
        kind, truth = p["identity_types"].get(field, "text"), s["identity"][field]
        if kind == "date":
            got, want = read_date(answer), read_date(truth)
            if got is None: return {"ok": False, "error": "answer is not a date. Send it as YYYY-MM-DD."}
            right = got == want
            if not right and (got[0], got[2], got[1]) == want and (not s["hinted"] or not p["hint_once"]):
                s["hinted"] = True
                return {"ok": True, "verified": False, "wrong_answers_left": left(), "hint": "day_month_swapped"}
        elif kind == "digits": right = re.sub(r"\D", "", str(answer if answer is not None else "")) == re.sub(r"\D", "", str(truth))
        else: right = re.sub(r"[\s\-]", "", str(answer if answer is not None else "")).lower() == re.sub(r"[\s\-]", "", str(truth)).lower()
        if right:
            s["verified"][field] = True
            return {"ok": True, "verified": True, "wrong_answers_left": left(), "all_verified": self._verified(s)}
        s["wrong"] += 1
        return {"ok": True, "verified": False, "wrong_answers_left": left(), "all_verified": False}

    def _get_account(self, s, a):
        if not self._verified(s): return dict(ERR_NOT_VERIFIED)
        return {"ok": True, "products": copy.deepcopy(s["products"])}

    def _create_promise(self, s, a):
        if not self._verified(s): return dict(ERR_NOT_VERIFIED)
        product = next((p for p in s["products"] if p["product_id"] == a.get("product_id")), None)
        if not product: return {"ok": False, "error": "unknown " + self._wire(s, "create_promise", "product_id")}
        raw = a.get("amount")
        try: amount = float(raw) if not isinstance(raw, bool) else 0
        except (TypeError, ValueError): amount = 0
        if not amount > 0: return {"ok": False, "error": self._wire(s, "create_promise", "amount") + " must be a positive number"}
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a.get("date") or "")): return {"ok": False, "error": self._wire(s, "create_promise", "date") + " must be YYYY-MM-DD"}
        if any(p["product_id"] == product["product_id"] for p in s["promises"]): return {"ok": False, "error": "this product already has a promise"}
        pid = f"pr{len(s['promises']) + 1}"
        s["promises"].append({"promise_id": pid, "product_id": product["product_id"], "type": product.get("type"), "amount": jsnum(amount), "date": a["date"]})
        return {"ok": True, "promise_id": pid}

    def _add_note(self, s, a):
        p = s["profile"]
        if not p["note_product_unchecked"] and not any(x["product_id"] == a.get("product_id") for x in s["products"]):
            return {"ok": False, "error": "unknown " + self._wire(s, "add_note", "product_id")}
        if a.get("reason") not in p["note_reasons"]: return {"ok": False, "error": "unknown " + self._wire(s, "add_note", "reason")}
        s["notes"].append({"product_id": a.get("product_id"), "reason": a["reason"], "text": a.get("text") or ""})
        return {"ok": True}

    def _schedule_callback(self, s, a):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(a.get("date") or "")) or not re.fullmatch(r"\d{2}:\d{2}", str(a.get("time") or "")):
            return {"ok": False, "error": self._wire(s, "schedule_callback", "date") + " must be YYYY-MM-DD and " + self._wire(s, "schedule_callback", "time") + " HH:MM"}
        s["callbacks"].append({"date": a["date"], "time": a["time"]})
        return {"ok": True}

    def _transfer_to_agent(self, s, a):
        if a.get("queue") not in s["profile"]["queues"]: return {"ok": False, "error": "unknown " + self._wire(s, "transfer_to_agent", "queue")}
        s["transfers"].append({"queue": a["queue"]})
        return {"ok": True}

    def _close_call(self, s, a):
        p = s["profile"]
        outcome = a.get("outcome")
        reasons = p["outcome_reasons"].get(outcome) if isinstance(outcome, str) else None
        if reasons is None: return {"ok": False, "error": "unknown " + self._wire(s, "close_call", "outcome")}
        reason = a.get("reason")
        if reasons == "any":
            if not isinstance(reason, str) or not reason: return {"ok": False, "error": "this " + self._wire(s, "close_call", "outcome") + " needs a " + self._wire(s, "close_call", "reason")}
        elif not reasons and not p["reason_rejected_on_reasonless"]: reason = None
        elif (reasons or reason is not None) and reason not in reasons:
            return {"ok": False, "error": "this " + self._wire(s, "close_call", "outcome") + " needs one of these " + self._wire(s, "close_call", "reason") + "s: " + ", ".join(reasons)}
        s["outcome"], s["reason"], s["closed"] = outcome, reason, True
        return {"ok": True}


def make_handler(bank):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _body(self):
            try: raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            except (ValueError, TypeError): raw = b""
            try: body = json.loads(raw or b"{}")
            except (ValueError, TypeError): body = {}
            return body if isinstance(body, dict) else {}

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/v1/health": return self._send(200, {"ok": True, "sessions": len(bank.sessions)})
            if path.startswith("/v1/practice/ledger/"): return self._send(*bank.ledger(path.rsplit("/", 1)[1]))
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path, body = self.path.split("?")[0].rstrip("/"), self._body()
            if path == "/v1/practice/sessions":
                key = self.headers.get("x-team-key") or ""
                return self._send(*bank.open_session(body, hashlib.sha256(key.encode()).hexdigest()[:24] if key else ""))
            if path.startswith("/v1/") and "/" not in path[4:]: return self._send(*bank.call(path[4:], body))
            self._send(404, {"ok": False, "error": "not found"})

        def log_message(self, *args): pass
    return Handler


def serve(port=8787, case_files=(), host="127.0.0.1"):
    cases = [c for f in case_files for c in json.load(open(f))]
    server = ThreadingHTTPServer((host, port), make_handler(Bank(cases)))
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8787); ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--cases", action="append", default=[], help="a case file such as public-test-set.json; may be given more than once")
    a = ap.parse_args()
    srv = serve(a.port, a.cases, a.host)
    print(f"bank listening on http://{a.host}:{a.port}/v1 with {len(a.cases)} case file(s)", flush=True)
    srv.serve_forever()
