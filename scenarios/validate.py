"""Validates scenarios/extended-test-set.json against the briefs and the fixed bank accounts.

    python3 scenarios/validate.py            # exit 0 when everything passes, 1 otherwise

Checks: schema; variables/identity/products identical to the session case; every promise on a
business day, today or later, not after that product's deadline; every amount between the floor
and the full amount; outcome/reason pairs from the Brief A table; callbacks inside the Brief A
window; notes only on Brief B accounts, never with a transfer (B10), one per product, never on a
product with a promise; Brief B closing rule; one promise per product; rule references well
formed; English/ASCII only; 2 to 4 checks per scenario, each lowercase, without a final full stop,
without "must"/"should" and at most 20 words. As a self-test it re-derives the 13 official cases' expected dates
with brief_calendar.py.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brief_calendar as cal  # noqa: E402

ROOT = HERE.parent
PUBLIC = ROOT / "kit" / "build-the-builder" / "public-test-set.json"
EXTENDED = HERE / "extended-test-set.json"

OUTCOME_TABLE = {
    "promise": {None},
    "paid": {None},
    "transferred": {"restructuring", "human", "support"},
    "no_promise": {"refused", "hardship", "dispute", "service_error"},
    "not_verified": {"failed", "declined"},
    "not_reached": {"callback", "no_callback", "wrong_number", "deceased", "unclear"},
}
QUEUE_FOR_REASON = {"restructuring": "restructuring", "human": "general", "support": "support"}
NOTE_REASONS = {"refused", "hardship", "dispute", "paid", "service_error"}
FIELDS = ["id", "brief", "family", "level", "title", "variables", "identity", "products", "script", "expected",
          "checks", "session_case", "rules"]
EXPECTED_FIELDS = {"outcome", "reason", "promises", "notes", "callbacks", "transfers"}
RULE_RE = re.compile(r"^(A([1-9]|[1-3][0-9]|4[0-7])|B([1-9]|1[01])|B-closing)$")
LEVELS = {"easy", "medium", "hard"}

problems = []


def bad(sid, msg):
    problems.append(f"{sid}: {msg}")


CHECK_MAX_WORDS = 20
CHECK_MODAL_RE = re.compile(r"\b(must|should)\b", re.IGNORECASE)


def check_style(sid, check):
    """A check reads like the organizers' own: a statement of what is true of the call, not an instruction."""
    first = next((ch for ch in check if ch.isalpha()), "")
    if first.isupper():
        bad(sid, f"check starts with an uppercase letter: {check!r}")
    if check.rstrip().endswith("."):
        bad(sid, f"check ends with a full stop: {check!r}")
    if CHECK_MODAL_RE.search(check):
        bad(sid, f"check uses 'must' or 'should': {check!r}")
    if len(check.split()) > CHECK_MAX_WORDS:
        bad(sid, f"check is longer than {CHECK_MAX_WORDS} words: {check!r}")


def check_promises(sid, case, exp, now):
    """Promise checks shared by the official and the extended cases."""
    products = case["products"]
    pids = {f"p{i + 1}": p for i, p in enumerate(products)}
    seen = set()
    for pr in exp["promises"]:
        if set(pr) != {"product_id", "amount", "date"}:
            bad(sid, f"promise fields {sorted(pr)}")
            continue
        pid = pr["product_id"]
        if pid not in pids:
            bad(sid, f"promise on unknown product {pid}")
            continue
        if pid in seen:
            bad(sid, f"more than one promise on {pid} (rule 36)")
        seen.add(pid)
        prod = pids[pid]
        if not isinstance(pr["amount"], (int, float)):
            bad(sid, f"amount {pr['amount']!r} is not a number")
        elif not cal.amount_ok(prod, pr["amount"]):
            bad(sid, f"amount {pr['amount']} on {pid} outside floor {cal.floor_of(prod)} .. full {prod['past_due']} (rule 27)")
        try:
            d = cal.parse_date(pr["date"])
        except ValueError:
            bad(sid, f"promise date {pr['date']!r} is not a date")
            continue
        if not cal.is_business_day(d):
            bad(sid, f"promise date {d} is not a business day (rule 19)")
        if d < cal.today(now):
            bad(sid, f"promise date {d} is before today (rule 19)")
        dl = cal.deadline(now, prod["days_late"])
        if d > dl:
            bad(sid, f"promise date {d} on {pid} is after its deadline {dl} (rules 18, 19)")
    return seen


def check_case(sc, official):
    sid = sc.get("id", "<no id>")
    # ---- schema
    extra = [k for k in sc if k not in FIELDS + ["faults", "style"]]
    missing = [k for k in FIELDS if k not in sc]
    if extra or missing:
        bad(sid, f"fields: extra {extra}, missing {missing}")
    if not re.fullmatch(r"EXT-\d{3}", sid):
        bad(sid, "id must look like EXT-001")
    session = sc.get("session_case")
    if session not in official:
        bad(sid, f"session_case {session!r} is not an official case")
        return
    case = official[session]
    if sc.get("brief") != case["brief"]:
        bad(sid, f"brief {sc.get('brief')!r} but session {session} is Brief {case['brief']}")
    for k in ("variables", "identity", "products"):
        if sc.get(k) != case[k]:
            bad(sid, f"{k} differs from {session}")
    if "faults" in case:
        if sc.get("faults") != case["faults"]:
            bad(sid, f"faults must be inherited unchanged from {session}")
    elif "faults" in sc:
        bad(sid, f"faults present but {session} has none")
    if sc.get("level") not in LEVELS:
        bad(sid, f"level {sc.get('level')!r}")
    for k in ("family", "title", "script"):
        if not isinstance(sc.get(k), str) or not sc[k].strip():
            bad(sid, f"{k} must be a non-empty string")
    checks = sc.get("checks")
    if not isinstance(checks, list) or not 2 <= len(checks) <= 4 or not all(isinstance(c, str) and c.strip() for c in checks):
        bad(sid, "checks must be 2 to 4 non-empty strings")
    else:
        for c in checks:
            check_style(sid, c)
    rules = sc.get("rules")
    if not isinstance(rules, list) or not rules or not all(isinstance(r, str) and RULE_RE.match(r) for r in rules):
        bad(sid, f"rules must be a non-empty list of A1..A47 / B1..B11 / B-closing, got {rules}")
    elif case["brief"] == "A" and any(r.startswith("B") for r in rules):
        bad(sid, "Brief A account references a Brief B rule")
    if len(set(rules or [])) != len(rules or []):
        bad(sid, "duplicate rule references")
    # ---- English / ASCII only
    text = json.dumps(sc, ensure_ascii=False)
    if any(ord(ch) > 127 for ch in text):
        bad(sid, "non-ASCII characters found; everything must be English")
    exp = sc.get("expected")
    if not isinstance(exp, dict) or set(exp) != EXPECTED_FIELDS:
        bad(sid, f"expected must have exactly {sorted(EXPECTED_FIELDS)}")
        return
    now = case["variables"]["now"]
    outcome, reason = exp["outcome"], exp["reason"]
    # ---- outcome table
    if outcome not in OUTCOME_TABLE:
        bad(sid, f"unknown outcome {outcome!r}")
        return
    if reason not in OUTCOME_TABLE[outcome]:
        bad(sid, f"reason {reason!r} is not allowed with outcome {outcome} (rule 46 table)")
    # ---- promises
    promised = check_promises(sid, case, exp, now)
    if outcome == "promise" and not promised:
        bad(sid, "outcome promise with no promise")
    if outcome in ("paid", "no_promise", "not_verified", "not_reached") and promised:
        bad(sid, f"outcome {outcome} cannot have promises")
    # ---- transfers
    transfers = exp["transfers"]
    if outcome == "transferred":
        if len(transfers) != 1 or transfers[0].get("queue") != QUEUE_FOR_REASON.get(reason):
            bad(sid, f"transferred / {reason} needs exactly one transfer with queue {QUEUE_FOR_REASON.get(reason)}, got {transfers}")
    elif transfers:
        bad(sid, f"transfers present with outcome {outcome}")
    # ---- callbacks
    callbacks = exp["callbacks"]
    if outcome == "not_reached" and reason == "callback":
        if len(callbacks) != 1:
            bad(sid, "not_reached / callback needs exactly one callback")
        for cb in callbacks:
            if set(cb) != {"date", "time"}:
                bad(sid, f"callback fields {sorted(cb)}")
            elif not re.fullmatch(r"\d{2}:\d{2}", cb["time"]) or not cal.callback_ok(now, cb["date"], cb["time"]):
                bad(sid, f"callback {cb} is outside the window (today or next business day, 10:00-19:00, later than now; rule 6)")
    elif callbacks:
        bad(sid, f"callbacks present with outcome {outcome} / {reason}")
    # ---- who is on the line
    if outcome == "not_reached" and reason != "unclear" and sc.get("family") != "Third party":
        bad(sid, "a not_reached case other than 'unclear' must have family 'Third party' (run_cases.py builds the persona from it)")
    if sc.get("family") == "Third party" and outcome != "not_reached":
        bad(sid, "family 'Third party' must end as not_reached")
    # ---- notes
    notes = exp["notes"]
    n_products = len(case["products"])
    pids = [f"p{i + 1}" for i in range(n_products)]
    if case["brief"] == "A" and notes:
        bad(sid, "Brief A never uses add_note")
    if notes and transfers:
        bad(sid, "notes together with a transfer (Brief B rule 10)")
    noted = {}
    for n in notes:
        if set(n) != {"product_id", "reason"}:
            bad(sid, f"note fields {sorted(n)}")
            continue
        if n["product_id"] not in pids:
            bad(sid, f"note on unknown product {n['product_id']}")
        if n["reason"] not in NOTE_REASONS:
            bad(sid, f"note reason {n['reason']!r}")
        if n["product_id"] in noted:
            bad(sid, f"two notes on {n['product_id']}")
        if n["product_id"] in promised:
            bad(sid, f"note and promise on the same product {n['product_id']}")
        noted[n["product_id"]] = n["reason"]
    if case["brief"] == "B":
        if outcome in ("promise", "paid", "no_promise"):
            for pid in pids:
                if pid not in promised and pid not in noted:
                    bad(sid, f"{pid} has neither a promise nor a note (Brief B rule 8)")
        if outcome in ("not_verified", "not_reached", "transferred") and notes:
            bad(sid, f"notes with outcome {outcome}")
        if outcome == "paid" and (set(noted.values()) != {"paid"} or len(noted) != n_products):
            bad(sid, "outcome paid needs every product noted 'paid' (Brief B closing)")
        if outcome == "no_promise":
            first = next((noted[p] for p in pids if noted.get(p) != "paid"), None)
            if first != reason:
                bad(sid, f"no_promise reason {reason!r} but the first non-paid note in order is {first!r} (Brief B closing)")
    # ---- script sanity: every date named in expected should be a date the script can produce
    if outcome == "promise" and "confirm" not in sc["script"].lower():
        bad(sid, "a promise scenario should say that the customer confirms at the read-back")


def self_test(official):
    """Re-derive the 13 official cases' expected dates with the calendar module."""
    now = "2026-10-14T11:00"
    want = {
        "PUB-01": [cal.today(now)],
        "PUB-04": [cal.resolve_named_day(now, "2026-11-06", 14)[0]],
        "PUB-06": [cal.this_weekday(now, "friday")],
        "PUB-07": [cal.resolve_named_day(now, "2026-10-26", 5)[0]],
        "PUB-10": [cal.this_weekday(now, "friday")],
        "PUB-11": [cal.this_weekday(now, "friday")] * 3,
        "PUB-12": [cal.tomorrow(now)],
        "PUB-13": [cal.resolve_named_day(now, "2026-10-30", 4)[0], cal.resolve_named_day(now, "2026-10-30", 20)[0]],
    }
    for pid, dates in want.items():
        got = [cal.parse_date(p["date"]) for p in official[pid]["expected"]["promises"]]
        if got != dates:
            bad("self-test " + pid, f"calendar derives {dates}, official file says {got}")
    if cal.resolve_named_day(now, "2026-11-06", 14) != (cal.deadline(now, 14), "deadline"):
        bad("self-test PUB-04", "6 November should resolve to the late-band deadline")
    if cal.resolve_named_day(now, "2026-10-26", 5) != (cal.parse_date("2026-10-27"), "next_business"):
        bad("self-test PUB-07", "26 October should resolve to the next business day, 27 October")
    if cal.resolve_named_day(now, "2026-10-30", 4)[1] != "accepted" or cal.resolve_named_day(now, "2026-10-30", 20)[1] != "deadline":
        bad("self-test PUB-13", "30 October should be accepted for the card and moved to the deadline for the loan")
    cb = official["PUB-02"]["expected"]["callbacks"][0]
    if cal.parse_date(cb["date"]) != cal.next_business_day(cal.today(now)) or not cal.callback_ok(now, cb["date"], cb["time"]):
        bad("self-test PUB-02", f"callback {cb} does not match the calendar")
    if cal.deadline(now, 14) != cal.parse_date("2026-10-23") or cal.deadline(now, 5) != cal.parse_date("2026-11-02"):
        bad("self-test", "deadlines do not match the brief's worked examples (23 October late, 2 November early)")
    if cal.band(7) != "early" or cal.band(8) != "late" or cal.attempt1_date(now) != cal.parse_date("2026-10-16"):
        bad("self-test", "band boundary or attempt 1 date wrong")
    # the official cases must pass the same promise checks as the extended ones
    for pid, c in official.items():
        check_promises("official " + pid, c, c["expected"], now)
        if c["expected"]["reason"] not in OUTCOME_TABLE[c["expected"]["outcome"]]:
            bad("official " + pid, "outcome/reason pair not in the table")


STYLES = {"pieces", "corrects", "talkative", "asks_back", "in_words"}


def main():
    official = {c["id"]: c for c in json.load(open(PUBLIC))}
    self_test(official)
    if len(sys.argv) == 3 and sys.argv[1] == "--file":
        # a subset file (scenarios/stability-set.json): the per-case checks, no rule-coverage requirement
        data = json.load(open(sys.argv[2]))
        for sc in data:
            check_case(sc, official)
            if sc.get("style") not in STYLES:
                bad(sc.get("id"), f"style must be one of {sorted(STYLES)}")
        if problems:
            print(f"FAILED: {len(problems)} problem(s)")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        print(f"OK: {len(data)} scenarios in {sys.argv[2]}, styles " + ", ".join(f"{st} {sum(1 for sc in data if sc.get('style') == st)}" for st in sorted(STYLES)))
        sys.exit(0)
    data = json.load(open(EXTENDED))
    if not isinstance(data, list) or not data:
        print("extended-test-set.json must be a non-empty list")
        sys.exit(1)
    ids = [sc.get("id") for sc in data]
    nums = [int(i[4:]) if re.fullmatch(r"EXT-\d{3}", str(i)) else -1 for i in ids]
    if nums != sorted(set(nums)) or -1 in nums:
        bad("file", "ids must be EXT-### , unique and increasing (slots of scenarios removed after a review stay empty)")
    for sc in data:
        check_case(sc, official)
    # every rule exercised at least twice, on different accounts where possible
    by_rule = {}
    for sc in data:
        for r in sc.get("rules", []):
            by_rule.setdefault(r, set()).add(sc["session_case"])
    all_rules = [f"A{i}" for i in range(1, 48)] + [f"B{i}" for i in range(1, 12)]
    untestable = {"B11"}  # create_promise never fails twice on the fixed bank (PUB-10 fails once, and is a Brief A account)
    for r in all_rules:
        n = sum(1 for sc in data if r in sc.get("rules", []))
        if n < 2 and r not in untestable:
            bad("coverage", f"rule {r} is exercised by {n} scenario(s), need at least 2")
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    fams = {}
    for sc in data:
        fams[sc["family"]] = fams.get(sc["family"], 0) + 1
    print(f"OK: {len(data)} scenarios, self-test on {len(official)} official cases passed")
    for f, n in sorted(fams.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {n:3d}  {f}")
    sys.exit(0)


if __name__ == "__main__":
    main()
