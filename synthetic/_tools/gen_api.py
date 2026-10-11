"""Generate the eight api.json files. Same shape as the public openapi.json: POST per tool, JSON body, 200 + 500.

Every file keeps exactly the seven public tool names (verify_identity, get_account, create_promise, schedule_callback,
transfer_to_agent, add_note, close_call). Only field names, allowed values and response shapes vary.
"""
import json, os

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEVEN = ["verify_identity", "get_account", "create_promise", "schedule_callback", "transfer_to_agent", "add_note", "close_call"]
FAIL = "The service failed. Nothing was recorded. The call may be repeated."
OKDESC = "`ok` is false when the action was not carried out."


def prop(t, **kw):
    p = {"type": t}
    p.update(kw)
    return p


def tool(name, summary, props, required, resp_props):
    r = {"ok": prop("boolean"), "error": prop("string")}
    r.update(resp_props)
    return (name, {
        "post": {
            "summary": summary,
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "properties": props, "required": required}}}},
            "responses": {
                "200": {"description": OKDESC, "content": {"application/json": {"schema": {
                    "type": "object", "properties": r}}}},
                "500": {"description": FAIL},
            },
        }
    })


def product_schema(fields):
    return {"type": "array", "items": {"type": "object", "properties": fields}}


def write(letter, title, desc, server, tools):
    names = [n for n, _ in tools]
    assert sorted(names) == sorted(SEVEN), (letter, names)
    doc = {
        "openapi": "3.0.3",
        "info": {"title": title, "version": "1.0", "description": desc},
        "servers": [{"url": server}],
        "components": {},
        "paths": {f"/{n}": body for n, body in tools},
    }
    path = os.path.join(ROOT, letter, "api.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1)
    print("wrote", path, len(tools), "tools")


CLOSE_REASON = "Required for every outcome except {}. See the brief."

# ---------------------------------------------------------------- C: Halvard Credit Union
ID = "client_ref"
write("C", "Halvard Credit Union call tools",
      "Mock of Halvard Credit Union's systems for the reminder call. Every call is written to the ledger the scorer reads. The service does not enforce the brief: it records a pledge on a closing day or past the deadline without complaint. The client_ref in the body is the secret of one call.",
      "https://halvard-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Two wrong answers on the same question end the check.",
         {ID: prop("string"), "question": prop("string", enum=["postcode", "birth_year"]),
          "answer": prop("string", description="postcode: upper case letters and digits, no spaces (AB123CD). birth_year: four digits. An unreadable value is rejected with ok=false and is not counted as a wrong answer.")},
         [ID, "question", "answer"],
         {"correct": prop("boolean"), "wrong_left_on_question": prop("integer"), "all_passed": prop("boolean")}),
    tool("get_account", "The overdue product. Refused until both questions are passed.",
         {ID: prop("string")}, [ID],
         {"products": product_schema({"product_id": prop("string"), "kind": prop("string", enum=["card", "loan", "overdraft"]),
                                      "card_last4": prop("string", description="cards only"), "overdue_amount": prop("number"),
                                      "days_overdue": prop("integer")})}),
    tool("create_promise", "Record a payment pledge. One per product.",
         {ID: prop("string"), "product_id": prop("string"), "amount": prop("number"), "pay_date": prop("string", format="date")},
         [ID, "product_id", "amount", "pay_date"], {"pledge_id": prop("string")}),
    tool("schedule_callback", "Book a callback for the next business day.",
         {ID: prop("string"), "callback_date": prop("string", format="date"), "callback_time": prop("string", description="HH:MM")},
         [ID, "callback_date", "callback_time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["welfare", "arrangements", "agents"])}, [ID, "queue"], {}),
    tool("add_note", "Record a member request that is not a pledge. Brief C uses it only for do-not-call requests.",
         {ID: prop("string"), "reason": prop("string", enum=["do_not_call"]), "text": prop("string")},
         [ID, "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["pledge", "settled", "handed_over", "no_pledge", "unverified", "unreachable"]),
          "reason": prop("string", description=CLOSE_REASON.format("pledge and settled"))},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- D: Marlowe & Finch
ID = "customer_id"
write("D", "Marlowe & Finch Bank arrears call tools",
      "Mock of Marlowe & Finch Bank's systems. Every call is written to the ledger the scorer reads. The service does not enforce the brief: it records a promise on a closing day or past the deadline without complaint.",
      "https://marlowe-finch-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Three wrong answers in total end the check.",
         {ID: prop("string"), "question": prop("string", enum=["date_of_birth", "postcode", "phone_last4"]),
          "answer": prop("string", description="date_of_birth as YYYY-MM-DD; postcode in upper case without spaces; phone_last4 four digits. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "question", "answer"],
         {"passed": prop("boolean"), "wrong_total": prop("integer"), "all_passed": prop("boolean"), "hint": prop("string", enum=["day_month_swapped"])}),
    tool("get_account", "The accounts in arrears, one to three. Refused until all three questions are passed.",
         {ID: prop("string")}, [ID],
         {"accounts": product_schema({"product_id": prop("string"), "product": prop("string", enum=["credit_card", "personal_loan", "overdraft"]),
                                      "card_last4": prop("string", description="credit cards only"), "arrears": prop("number"),
                                      "days_in_arrears": prop("integer"), "minimum_due": prop("number")})}),
    tool("create_promise", "Record a payment promise. One per account.",
         {ID: prop("string"), "product_id": prop("string"), "promise_amount": prop("number"), "promise_date": prop("string", format="date")},
         [ID, "product_id", "promise_amount", "promise_date"], {"promise_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["vulnerable_customers", "arrangements", "general"])}, [ID, "queue"], {}),
    tool("add_note", "Record why an account ended without a promise. A dispute note ends the collections part of the call.",
         {ID: prop("string"), "product_id": prop("string"), "reason": prop("string", enum=["refused", "hardship", "paid", "service_error", "dispute"]), "text": prop("string")},
         [ID, "product_id", "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["promise", "paid", "transferred", "no_promise", "not_verified", "not_reached"]),
          "reason": prop("string", description=CLOSE_REASON.format("promise and paid"))},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- E: Northgate Savings (business)
write("E", "Northgate Savings business collections tools",
      "Mock of Northgate Savings' systems. Every call is written to the ledger the scorer reads. Amounts are integers in cents. The service does not enforce the brief.",
      "https://northgate-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Two wrong answers in total end the check.",
         {ID: prop("string"), "field": prop("string", enum=["company_number", "founded_year"]),
          "answer": prop("string", description="company_number: digits only, as registered. founded_year: four digits. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "field", "answer"],
         {"verified": prop("boolean"), "wrong_answers_left": prop("integer"), "all_verified": prop("boolean")}),
    tool("get_account", "The past-due products, one to three. Refused until both questions are passed.",
         {ID: prop("string")}, [ID],
         {"products": product_schema({"product_id": prop("string"), "type": prop("string", enum=["business_card", "term_loan", "line_of_credit"]),
                                      "card_last4": prop("string", description="business cards only"),
                                      "past_due_cents": prop("integer", description="past-due balance in cents"), "days_late": prop("integer")})}),
    tool("create_promise", "Record a payment promise. One per product. Amount in cents.",
         {ID: prop("string"), "product_id": prop("string"), "amount_cents": prop("integer"), "pay_date": prop("string", format="date")},
         [ID, "product_id", "amount_cents", "pay_date"], {"promise_id": prop("string")}),
    tool("schedule_callback", "Ask the collections team to call back. The reason says why.",
         {ID: prop("string"), "callback_date": prop("string", format="date"), "callback_time": prop("string", description="HH:MM"),
          "reason": prop("string", enum=["unavailable", "human_requested", "arrangement"])},
         [ID, "callback_date", "callback_time", "reason"], {}),
    tool("transfer_to_agent", "Hand the call to a person on the daytime desk. Not available on the evening line; see the brief.",
         {ID: prop("string"), "queue": prop("string", enum=["daytime_desk"])}, [ID, "queue"], {}),
    tool("add_note", "Record why a product ended without a promise.",
         {ID: prop("string"), "product_id": prop("string"), "reason": prop("string", enum=["declined", "hardship", "disputed", "settled", "error"]), "text": prop("string")},
         [ID, "product_id", "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["promise", "settled", "callback_booked", "no_promise", "id_failed", "no_contact"]),
          "reason": prop("string", description=CLOSE_REASON.format("promise and settled"))},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- F: Cresta Bank
ID = "client_ref"
write("F", "Cresta Bank collections tools",
      "Mock of Cresta Bank's systems. Every call is written to the ledger the scorer reads. The service does not enforce the brief.",
      "https://cresta-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check the date of birth. The third wrong answer ends the check.",
         {ID: prop("string"), "birth_date": prop("string", format="date", description="YYYY-MM-DD. Callers say dates in words, the agent converts. An unreadable value is rejected with ok=false and is not counted.")},
         [ID, "birth_date"], {"matched": prop("boolean"), "tries_left": prop("integer")}),
    tool("get_account", "The one late product. Refused until the date of birth is matched.",
         {ID: prop("string")}, [ID],
         {"product": {"type": "object", "properties": {"product_id": prop("string"), "type": prop("string", enum=["card", "consumer_loan", "auto_loan"]),
                                                       "card_last4": prop("string", description="cards only"), "past_due": prop("number"),
                                                       "days_late": prop("integer"), "monthly_instalment": prop("number")}}}),
    tool("create_promise", "Record a payment promise.",
         {ID: prop("string"), "product_id": prop("string"), "amount": prop("number"), "pay_date": prop("string", format="date")},
         [ID, "product_id", "amount", "pay_date"], {"promise_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["care", "plans", "people"])}, [ID, "queue"], {}),
    tool("add_note", "Write a note on the customer. Cresta uses it only for a do-not-call wish. No product on the note.",
         {ID: prop("string"), "reason": prop("string", enum=["no_contact"]), "text": prop("string")}, [ID, "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["promise", "paid", "transferred", "refused", "not_verified", "not_reached"]),
          "reason": prop("string", description=CLOSE_REASON.format("promise and paid"))},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- G: Ashworth Mutual
ID = "customer_ref"
write("G", "Ashworth Mutual arrears tools",
      "Mock of Ashworth Mutual's systems. Every call is written to the ledger the scorer reads. The service does not enforce the policy. Codes as in the code list.",
      "https://ashworth-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer.",
         {ID: prop("string"), "field": prop("string", enum=["date_of_birth", "phone_last4"]),
          "answer": prop("string", description="date_of_birth as YYYY-MM-DD; phone_last4 four digits. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "field", "answer"],
         {"verified": prop("boolean"), "wrong_on_this_field": prop("integer"), "all_verified": prop("boolean"), "hint": prop("string", enum=["day_month_swapped"])}),
    tool("get_account", "The products in arrears, one to three.",
         {ID: prop("string")}, [ID],
         {"products": product_schema({"product_id": prop("string"), "type": prop("string", enum=["CC", "PL", "HP"]),
                                      "card_last4": prop("string", description="CC only"), "arrears": prop("number"),
                                      "days_in_arrears": prop("integer")})}),
    tool("create_promise", "Record a promise to pay. One per product.",
         {ID: prop("string"), "product_id": prop("string"), "amount": prop("number"), "date": prop("string", format="date")},
         [ID, "product_id", "amount", "date"], {"promise_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["financial_support", "complaints", "arrangements", "agent"])}, [ID, "queue"], {}),
    tool("add_note", "Record why a product ended without a promise. Reason codes from the code list.",
         {ID: prop("string"), "product_id": prop("string"), "reason": prop("string", enum=["REF", "HARD", "DISP", "PAID", "ERR", "DNC"]), "text": prop("string")},
         [ID, "product_id", "reason"], {}),
    tool("close_call", "End the call. Always the last tool call. Codes from the code list.",
         {ID: prop("string"), "outcome": prop("string", enum=["PTP", "PAID", "XFER", "NOPTP", "IDFAIL", "NOCON"]),
          "reason": prop("string", description="Required for every outcome except PTP and PAID. See the code list.")},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- H: Portmann Bank
ID = "client_ref"
write("H", "Portmann Bank collections tools",
      "Mock of Portmann Bank's systems. Every call is written to the ledger the scorer reads. The service does not enforce the policy.",
      "https://portmann-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Two wrong answers in total end the check.",
         {ID: prop("string"), "question": prop("string", enum=["postcode", "birth_year"]),
          "answer": prop("string", description="postcode: upper case, no spaces. birth_year: four digits. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "question", "answer"],
         {"correct": prop("boolean"), "wrong_total": prop("integer"), "all_passed": prop("boolean")}),
    tool("get_account", "The late products, one to three. Refused until both questions are passed.",
         {ID: prop("string")}, [ID],
         {"products": product_schema({"product_id": prop("string"), "type": prop("string", enum=["credit_card", "personal_loan", "car_loan"]),
                                      "card_last4": prop("string", description="credit cards only"), "past_due": prop("number"),
                                      "days_late": prop("integer"), "floor": prop("number", description="the smallest amount Portmann accepts on this product")})}),
    tool("create_promise", "Record a payment pledge. One per product.",
         {ID: prop("string"), "product_id": prop("string"), "amount": prop("number"), "pay_date": prop("string", format="date")},
         [ID, "product_id", "amount", "pay_date"], {"pledge_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["wellbeing", "restructuring", "front_desk"])}, [ID, "queue"], {}),
    tool("add_note", "Record why a product ended without a pledge. A dispute reason (not_mine, already_closed, amount_wrong) ends the collections part of the call.",
         {ID: prop("string"), "product_id": prop("string"),
          "reason": prop("string", enum=["not_mine", "already_closed", "amount_wrong", "refused", "hardship", "paid", "failed"]), "text": prop("string")},
         [ID, "product_id", "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["pledge", "paid", "transferred", "no_pledge", "unverified", "unreachable"]),
          "reason": prop("string", description="Required for every outcome except pledge and paid. See the code list.")},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- I: Tamsin Finance
ID = "customer_id"
AMT = prop("string", pattern=r"^[0-9]+\.[0-9]{2}$", description="dollars with exactly two decimals, as a string, e.g. \"125.00\"")
write("I", "Tamsin Finance payments-team tools",
      "Mock of Tamsin Finance's systems. Every call is written to the ledger the scorer reads. Amounts are strings with two decimals. The service does not enforce the policy.",
      "https://tamsin-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Two wrong answers on the same question end the check.",
         {ID: prop("string"), "field": prop("string", enum=["date_of_birth", "postcode", "phone_last4"]),
          "answer": prop("string", description="date_of_birth as YYYY-MM-DD; postcode upper case without spaces; phone_last4 four digits. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "field", "answer"],
         {"verified": prop("boolean"), "wrong_on_this_field": prop("integer"), "all_verified": prop("boolean"), "hint": prop("string", enum=["day_month_swapped"])}),
    tool("get_account", "The past-due products, one to three.",
         {ID: prop("string")}, [ID],
         {"products": product_schema({"product_id": prop("string"), "type": prop("string", enum=["store_card", "instalment_loan", "auto_loan"]),
                                      "card_last4": prop("string", description="store cards only"),
                                      "past_due": dict(AMT), "days_late": prop("integer"), "min_due": dict(AMT)})}),
    tool("create_promise", "Record a payment promise. One per product. Amount as a two-decimal string.",
         {ID: prop("string"), "product_id": prop("string"), "amount": dict(AMT), "date": prop("string", format="date")},
         [ID, "product_id", "amount", "date"], {"promise_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["payments_team", "hardship_team"])}, [ID, "queue"], {}),
    tool("add_note", "Record why a product ended without a promise.",
         {ID: prop("string"), "product_id": prop("string"), "reason": prop("string", enum=["refused", "hardship", "dispute", "paid", "service_error", "do_not_call"]), "text": prop("string")},
         [ID, "product_id", "reason"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "outcome": prop("string", enum=["promise", "paid", "transferred", "no_promise", "not_verified", "not_reached"]),
          "reason": prop("string", description="Required for every outcome except promise and paid. See the code list.")},
         [ID, "outcome"], {}),
])

# ---------------------------------------------------------------- J: Kestrel Bank
ID = "account_no"
write("J", "Kestrel Bank collections tools",
      "Mock of Kestrel Bank's systems. Every call is written to the ledger the scorer reads. The service does not enforce the policy.",
      "https://kestrel-mock.example.workers.dev/v1", [
    tool("verify_identity", "Check one security answer. Three wrong answers in total end the check.",
         {ID: prop("string"), "check": prop("string", enum=["date_of_birth", "postcode"]),
          "value": prop("string", description="date_of_birth as YYYY-MM-DD; postcode upper case without spaces. An unreadable value is rejected with ok=false and not counted.")},
         [ID, "check", "value"],
         {"passed": prop("boolean"), "wrong_total": prop("integer"), "all_passed": prop("boolean"), "hint": prop("string", enum=["day_month_swapped"])}),
    tool("get_account", "The overdue products, one to three. Refused until both checks are passed.",
         {ID: prop("string")}, [ID],
         {"debts": product_schema({"product_id": prop("string"), "kind": prop("string", enum=["card", "loan", "mortgage_arrears"]),
                                   "card_last4": prop("string", description="cards only"), "amount_due": prop("number"),
                                   "days_overdue": prop("integer"), "minimum": prop("number")})}),
    tool("create_promise", "Record a payment arrangement. One per product.",
         {ID: prop("string"), "product_id": prop("string"), "amount": prop("number"), "pay_by": prop("string", format="date")},
         [ID, "product_id", "amount", "pay_by"], {"arrangement_id": prop("string")}),
    tool("schedule_callback", "Book a callback.",
         {ID: prop("string"), "date": prop("string", format="date"), "time": prop("string", description="HH:MM")}, [ID, "date", "time"], {}),
    tool("transfer_to_agent", "Hand the call to a person.",
         {ID: prop("string"), "queue": prop("string", enum=["customer_care", "arrangements", "complaints", "agent"])}, [ID, "queue"], {}),
    tool("add_note", "Flag why a product ended without an arrangement.",
         {ID: prop("string"), "product_id": prop("string"), "flag": prop("string", enum=["refused", "hardship", "disputed", "paid", "failed", "do_not_call"]), "text": prop("string")},
         [ID, "product_id", "flag"], {}),
    tool("close_call", "End the call. Always the last tool call.",
         {ID: prop("string"), "result": prop("string", enum=["arranged", "paid", "routed", "no_arrangement", "not_verified", "not_reached"]),
          "detail": prop("string", description="Required for every result except arranged and paid. See the code list.")},
         [ID, "result"], {}),
])
