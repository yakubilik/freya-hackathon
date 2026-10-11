"""Check every synthetic brief: seven tool names, enum values used by the cases, and re-derived promise dates/amounts."""
import json, os, sys
from collections import Counter
from cal import d, is_bd, fmt
from derive import HOL, deadline, floor, attempt_dates

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEVEN = {"verify_identity", "get_account", "create_problem"} and {"verify_identity", "get_account", "create_promise", "schedule_callback", "transfer_to_agent", "add_note", "close_call"}
PRODUCT_LIST = {"C": "products", "D": "accounts", "E": "products", "F": "product", "G": "products", "H": "products", "I": "products", "J": "debts"}
TYPE_FIELD = {"C": "kind", "D": "product", "E": "type", "F": "type", "G": "type", "H": "type", "I": "type", "J": "kind"}
FULL_FIELD = {"C": "overdue_amount", "D": "arrears", "E": "past_due_cents", "F": "past_due", "G": "arrears", "H": "past_due", "I": "past_due", "J": "amount_due"}
NOTE_FIELD = {"J": "flag"}
OUTCOME_FIELD = {"J": "result"}
ID_MAP = {"F": {"date_of_birth": "birth_date"}}
# close reasons per brief, from the brief text / code list
REASONS = {
    "C": {"pledge": [None], "settled": [None], "handed_over": ["welfare", "arrangements", "human"], "no_pledge": ["refused", "disputed", "system_error", "do_not_call"],
          "unverified": ["failed", "declined", "do_not_call"], "unreachable": ["callback_booked", "no_callback", "wrong_number", "deceased", "no_confirmation"]},
    "D": {"promise": [None], "paid": [None], "transferred": ["vulnerable", "arrangements", "human"], "no_promise": ["refused", "hardship", "dispute", "service_error", "paid", "do_not_call"],
          "not_verified": ["failed", "declined", "do_not_call"], "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"]},
    "E": {"promise": [None], "settled": [None], "callback_booked": ["unavailable", "arrangement", "human_requested"], "no_promise": ["declined", "hardship", "disputed", "error", "do_not_call"],
          "id_failed": ["wrong_answers", "declined"], "no_contact": ["unclear", "no_callback", "wrong_number", "ceased_trading", "do_not_call"]},
    "F": {"promise": [None], "paid": [None], "transferred": ["care", "plans", "human"], "refused": ["no_money", "dispute", "system", "no_contact"],
          "not_verified": ["failed", "declined", "no_contact"], "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"]},
    "G": {"PTP": [None], "PAID": [None], "XFER": ["WELF", "ARR", "HUM", "COMP"], "NOPTP": ["REF", "HARD", "DISP", "ERR", "DNC"],
          "IDFAIL": ["FAIL", "DECL", "DNC"], "NOCON": ["CB", "NOCB", "WRONG", "DEC", "UNCLR"]},
    "H": {"pledge": [None], "paid": [None], "transferred": ["wellbeing", "restructuring", "human"], "no_pledge": ["refused", "hardship", "dispute", "system_error"],
          "unverified": ["failed", "declined"], "unreachable": ["callback", "no_callback", "wrong_number", "deceased", "unclear"]},
    "I": {"promise": [None], "paid": [None], "transferred": ["hardship", "plan", "human"], "no_promise": ["refused", "hardship", "dispute", "service_error", "do_not_call"],
          "not_verified": ["failed", "declined", "do_not_call"], "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"]},
    "J": {"arranged": [None], "paid": [None], "routed": ["customer_care", "arrangements", "human", "complaint"], "no_arrangement": ["refused", "hardship", "disputed", "failed", "do_not_call"],
          "not_verified": ["failed", "declined", "do_not_call"], "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"]},
}
STYLES = {"pieces", "corrects", "talkative", "asks_back", "in_words"}


def schema(api, tool):
    p = api["paths"]["/" + tool]["post"]
    req = p["requestBody"]["content"]["application/json"]["schema"]["properties"]
    resp = p["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    return req, resp


def num(x):
    return float(x)


def main():
    problems = 0
    style_count = Counter()
    nows = []
    for b in "CDEFGHIJ":
        api = json.load(open(os.path.join(ROOT, b, "api.json")))
        cases = json.load(open(os.path.join(ROOT, b, "cases.json")))
        names = {p.strip("/") for p in api["paths"]}
        if names != SEVEN:
            print(b, "TOOL NAMES WRONG", names); problems += 1
        vreq, _ = schema(api, "verify_identity")
        _, gresp = schema(api, "get_account")
        creq, _ = schema(api, "create_promise")
        nreq, _ = schema(api, "add_note")
        treq, _ = schema(api, "transfer_to_agent")
        xreq, _ = schema(api, "close_call")
        plist = gresp[PRODUCT_LIST[b]]
        pprops = plist["items"]["properties"] if plist["type"] == "array" else plist["properties"]
        type_enum = set(pprops[TYPE_FIELD[b]]["enum"])
        qfield = [k for k in vreq if k not in ("client_ref", "customer_id", "customer_ref", "account_no", "answer", "value", "birth_date")]
        q_enum = set(vreq[qfield[0]]["enum"]) if qfield else {"birth_date"}
        note_enum = set(nreq[NOTE_FIELD.get(b, "reason")]["enum"])
        queue_enum = set(treq["queue"]["enum"])
        out_enum = set(xreq[OUTCOME_FIELD.get(b, "outcome")]["enum"])
        local_styles = 0
        print(f"== {b}: {len(cases)} cases")
        for c in cases:
            cid = c["id"]
            today = d(c["variables"]["now"])
            nows.append((b, c["variables"]["now"], fmt(today)))
            h = HOL[b]
            # identity keys
            for k in c["identity"]:
                kk = ID_MAP.get(b, {}).get(k, k)
                if kk not in q_enum:
                    print(cid, "identity key not in api", k); problems += 1
            # products
            for i, p in enumerate(c["products"], 1):
                if p[TYPE_FIELD[b]] not in type_enum:
                    print(cid, "product type not in api", p[TYPE_FIELD[b]]); problems += 1
                extra = set(p) - set(pprops)
                if extra:
                    print(cid, "product fields not in api", extra); problems += 1
            e = c["expected"]
            if e["outcome"] not in out_enum:
                print(cid, "outcome not in api", e["outcome"]); problems += 1
            if e["reason"] not in REASONS[b].get(e["outcome"], []):
                print(cid, "reason not in brief table", e["outcome"], e["reason"]); problems += 1
            for n in e["notes"]:
                if n["reason"] not in note_enum:
                    print(cid, "note reason not in api", n["reason"]); problems += 1
            for t in e["transfers"]:
                if t["queue"] not in queue_enum:
                    print(cid, "queue not in api", t["queue"]); problems += 1
            # promises
            for pr in e["promises"]:
                idx = int(pr["product_id"][1:]) - 1
                p = c["products"][idx]
                dl = deadline(b, today, p)
                fl = floor(b, p)
                full = num(p[FULL_FIELD[b]])
                pd = d(pr["date"])
                amt = num(pr["amount"])
                tag = []
                if not is_bd(pd, h): tag.append("NOT BUSINESS DAY")
                if pd < today: tag.append("BEFORE TODAY")
                if pd > dl: tag.append("AFTER DEADLINE")
                if amt < num(fl) - 1e-9 or amt > full + 1e-9: tag.append("AMOUNT OUT OF RANGE")
                kind = "full" if abs(amt - full) < 1e-9 else "floor" if abs(amt - num(fl)) < 1e-9 else "own"
                if tag: problems += 1
                print(f"  {cid} {pr['product_id']} {fmt(pd)} amount {pr['amount']} ({kind}) | deadline {fmt(dl)} floor {fl} full {full} attempts {[fmt(x) for x in attempt_dates(b, today, dl)]} {' '.join(tag)}")
            for cb in e["callbacks"]:
                cd = d(cb["date"])
                print(f"  {cid} callback {fmt(cd)} {cb['time']} ({'bd' if is_bd(cd, h) else 'NOT bd'}; now {fmt(today)} {c['variables']['now'][11:]})")
            if not e["promises"] and not e["callbacks"]:
                print(f"  {cid} {e['outcome']}/{e['reason']} notes {[n['reason'] for n in e['notes']]} transfers {[t['queue'] for t in e['transfers']]}")
            if c.get("style"):
                if c["style"] not in STYLES:
                    print(cid, "bad style", c["style"]); problems += 1
                style_count[c["style"]] += 1
                local_styles += 1
            if not c["checks"]:
                print(cid, "no checks"); problems += 1
        if local_styles < 2:
            print(b, "fewer than two styled cases"); problems += 1
    print("styles", dict(style_count))
    print("nows:")
    for b, n, f in nows:
        print("  ", b, n, f[:3])
    print("PROBLEMS", problems)
    return problems


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
