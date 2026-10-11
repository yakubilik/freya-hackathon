#!/usr/bin/env python3
"""Walk every entry of data/test-customers.json and check the mock returns exactly that HTTP status and body.

usage: python3 check.py <base-url> [--data path/to/test-customers.json]

Requests follow the service contract (2026-10-01): POST <base>/voice/v1/<service>, body {"data": {...}, "call": {...}}.
Card services are asked with the cardNumber exactly as cards.list gives it, and again with the cards.balance mask
("5400********1234"); customerNo and newStatementWeek alternate between string and number. Then the "not in the
file" answers (contract §4/§6) are checked by HTTP status and code. Exit code 0 only if everything matches.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BY_CARD = {"cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change"}
BY_WEEK = {"statement.week.decide", "statement.week.change"}
CALL = {"ani": "905000000000", "lang": "tr"}


def post(base, service, data, timeout=60):
    url = base.rstrip("/") + "/voice/v1/" + service
    # Cloudflare's edge answers 403 to the default "Python-urllib" User-Agent before the Worker runs.
    headers = {"content-type": "application/json", "accept": "application/json",
               "authorization": "Bearer test", "user-agent": "freya-statement-mock-check/1.0"}
    req = urllib.request.Request(url, data=json.dumps({"data": data, "call": CALL}).encode(), method="POST", headers=headers)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw.decode("utf-8", "replace")
    return status, body, time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test-customers.json"))
    a = ap.parse_args()
    customers = json.load(open(a.data, encoding="utf-8"))["customers"]

    cases = []  # (label, service, data, want_status, want_body, min_delay)
    for i, c in enumerate(customers):
        no = c["customerNo"]
        no_wire = int(no) if i % 2 else no
        for svc, node in c["services"].items():
            if svc not in BY_CARD:
                data = {"customerNo": no_wire}
                if svc == "cards.list":
                    data["aiFlow"] = "CardOps"
                elif svc == "contact.email.get":
                    data["intAddressInfoType"] = "E"
                elif svc == "statement.pdf.send":
                    data.update(cardNumber="540000******0000", currencyType="TL", statementDate="05.10.2026",
                                emailAddress="x@freyabank.example")
                cases.append((f"{no} {svc}", svc, data, node["http"], node["response"], node.get("delaySeconds", 0)))
                continue
            for card, cnode in node.items():
                for form in (card, card[:4] + "*" * 8 + card[-4:]):
                    items = cnode.items() if svc in BY_WEEK else [(None, cnode)]
                    for j, (week, e) in enumerate(items):
                        data = {"cardNumber": form}
                        if week is not None:
                            data.update(newStatementWeek=int(week) if j % 2 else week, statementDay=5)
                        label = f"{no} {svc} {form} {week or ''}".strip()
                        cases.append((label, svc, data, e["http"], e["response"], e.get("delaySeconds", 0)))

    # not in the file: (label, service, data, status, code)
    one = customers[0]
    card0 = next(iter(one["services"]["statement.week.get"]))
    cur_week = str(one["services"]["statement.week.get"][card0]["response"]["data"]["statementWeek"])
    no_pdf = next(c["customerNo"] for c in customers if "statement.pdf.send" not in c["services"])
    neg = [
        ("unknown customer cards.list", "cards.list", {"customerNo": "99999999"}, 404, "FB_IVR_CHANNEL_102"),
        ("unknown card cards.balance", "cards.balance", {"cardNumber": "540000******0000"}, 404, "FB_IVR_CHANNEL_120"),
        ("unknown card week.get", "statement.week.get", {"cardNumber": "540000******0000"}, 404, "FB_IVR_CHANNEL_121"),
        ("current week decide", "statement.week.decide", {"cardNumber": card0, "newStatementWeek": cur_week}, 400, "INVALID_ARGUMENTS_ERROR"),
        ("unknown card change", "statement.week.change", {"cardNumber": "540000******0000", "newStatementWeek": 2}, 400, "INVALID_ARGUMENTS_ERROR"),
        ("unknown customer email", "contact.email.get", {"customerNo": "99999999", "intAddressInfoType": "E"}, 400, "INVALID_ARGUMENTS_ERROR"),
        ("no pdf entry", "statement.pdf.send", {"customerNo": no_pdf}, 404, "FB_IVR_CHANNEL_107"),
        ("empty card", "cards.balance", {"cardNumber": ""}, 400, "INVALID_ARGUMENTS_ERROR"),
        ("empty customer", "cards.list", {}, 400, "INVALID_ARGUMENTS_ERROR"),
        ("bare last four", "cards.balance", {"cardNumber": card0[-4:]}, 404, "FB_IVR_CHANNEL_120"),
    ]

    def run(case):
        label, svc, data, want_s, want_b, delay = case
        s, b, dt = post(a.base, svc, data)
        if s != want_s or b != want_b:
            return f"MISMATCH {label}: got {s} {json.dumps(b, ensure_ascii=False)[:200]}"
        if delay and dt < delay:
            return f"NO DELAY {label}: answered in {dt:.1f}s, want >= {delay}s"
        return None

    def run_neg(case):
        label, svc, data, want_s, want_code = case
        s, b, _ = post(a.base, svc, data)
        r = b.get("result", {}) if isinstance(b, dict) else {}
        if s != want_s or r.get("code") != want_code or r.get("returnCode") != want_code or "data" in b:
            return f"ERROR CASE {label}: got {s} {json.dumps(b, ensure_ascii=False)[:200]}"
        return None

    with ThreadPoolExecutor(16) as ex:
        fails = [r for r in list(ex.map(run, cases)) + list(ex.map(run_neg, neg)) if r]
    for x in fails:
        print(x)
    total = len(cases) + len(neg)
    entries = sum(1 for c in cases if c[2].get("cardNumber", "")[4:6] != "**")
    print(f"{total - len(fails)}/{total} match ({entries} pack entries, {len(cases) - entries} again with the "
          f"cards.balance mask, {len(neg)} not-in-file cases)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
