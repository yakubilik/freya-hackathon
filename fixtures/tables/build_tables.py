"""Hand-written rule tables for Brief A and Brief A+B.

Run:  .venv/bin/python fixtures/tables/build_tables.py
Writes fixtures/tables/brief-a.json and fixtures/tables/brief-b.json.

Everything that is policy content below was written by hand from the two briefs. The script only
segments the brief files into numbered units (lossless, with character offsets), verifies that
every quote is contained in the unit it cites, and serialises the table in the frozen schema
(spec/rule_table.schema.json). No model is involved.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
BRIEF_A = ROOT / "kit/build-the-builder/briefs/brief-a.md"
BRIEF_B = ROOT / "kit/build-the-builder/briefs/brief-b.md"
OPENAPI = ROOT / "kit/build-the-builder/tools/openapi.json"
OUT = ROOT / "fixtures/tables"

SENT_SPLIT = re.compile(r'(?<=[.?!])\s+(?=[A-Z"`(])')


# ----------------------------------------------------------------------------------------------
# Lossless segmentation
# ----------------------------------------------------------------------------------------------
def segment(doc_id, prefix, text):
    """Number every heading, numbered rule, sub-bullet, table row and paragraph of a brief file.

    Rules become `<prefix>.r<N>` (kind item) with sentence children `<prefix>.r<N>.s<k>`.
    Sub-bullets of a rule become `<prefix>.r<N>.b<k>`. Table rows become `<prefix>.t<k>.r<j>`
    with the header folded into the text. Headings `<prefix>.h<k>`, other paragraphs `<prefix>.p<k>`.
    """
    units = {}
    pos = 0
    heading_n = table_n = para_n = 0
    current_rule = None
    current_heading = None
    header_cells = None
    in_table = False
    lines = text.split("\n")
    for line in lines:
        start = text.index(line, pos) if line else pos
        end = start + len(line)
        pos = end + 1
        stripped = line.strip()
        if not stripped:
            in_table = False
            header_cells = None
            continue
        m_head = re.match(r"^(#+)\s+(.*)$", stripped)
        m_rule = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        m_bullet = re.match(r"^\s+-\s+(.*)$", line)
        if m_head:
            heading_n += 1
            uid = f"{prefix}.h{heading_n}"
            units[uid] = {"text": m_head.group(2), "doc_id": doc_id, "offset": start, "end": end,
                          "kind": "heading", "parent": None, "table": None}
            current_heading = uid
            current_rule = None
        elif m_rule:
            n = int(m_rule.group(1))
            uid = f"{prefix}.r{n}"
            body = m_rule.group(2)
            units[uid] = {"text": body, "doc_id": doc_id, "offset": start + line.index(body),
                          "end": end, "kind": "item", "parent": current_heading, "table": None}
            current_rule = uid
            sentences = [s for s in SENT_SPLIT.split(body) if s.strip()]
            if len(sentences) > 1:
                off = units[uid]["offset"]
                for k, s in enumerate(sentences, 1):
                    so = text.index(s, off)
                    units[f"{uid}.s{k}"] = {"text": s, "doc_id": doc_id, "offset": so, "end": so + len(s),
                                            "kind": "sentence", "parent": uid, "table": None}
                    off = so + len(s)
        elif m_bullet and current_rule:
            k = 1 + sum(1 for u in units if u.startswith(current_rule + ".b"))
            uid = f"{current_rule}.b{k}"
            body = m_bullet.group(1)
            units[uid] = {"text": body, "doc_id": doc_id, "offset": start + line.index(body), "end": end,
                          "kind": "item", "parent": current_rule, "table": None}
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_table:
                in_table = True
                table_n += 1
                header_cells = cells
                tid = f"{prefix}.t{table_n}"
                units[tid] = {"text": " | ".join(cells), "doc_id": doc_id, "offset": start, "end": end,
                              "kind": "heading", "parent": current_rule or current_heading, "table": tid}
                continue
            tid = f"{prefix}.t{table_n}"
            j = sum(1 for u in units if u.startswith(tid + ".r"))
            uid = f"{tid}.r{j + 1}"
            folded = "; ".join(f"{h}: {c}" for h, c in zip(header_cells, cells))
            units[uid] = {"text": folded, "doc_id": doc_id, "offset": start, "end": end, "kind": "row",
                          "parent": tid, "table": tid}
        else:
            para_n += 1
            uid = f"{prefix}.p{para_n}"
            units[uid] = {"text": stripped, "doc_id": doc_id, "offset": start, "end": end, "kind": "sentence",
                          "parent": current_heading, "table": None}
            current_rule = None
    return units


# ----------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------
def ob(oid, units, quote, state, then, kind="state", guards=None, event=None, scope="call",
       exception_of=None, precedence=None, status="effective", capability="structural", notes=None,
       stage_id=None):
    o = {"id": oid, "units": units, "quote": quote,
         "when": {"state": state, "guards": guards or [], "event": event, "stage_id": stage_id},
         "then": then, "kind": kind, "scope": scope, "exception_of": exception_of,
         "precedence": precedence or [], "status": status, "effective": None, "capability": capability}
    if notes:
        o["notes"] = notes
    return o


def val(value, typ, quotes, units, obligations=None, confidence="quoted"):
    return {"value": value, "type": typ, "quotes": quotes, "units": units, "obligations": obligations or [],
            "confidence": confidence}


def not_specified(typ, reason_units=None):
    return {"type": typ, "quotes": [], "units": reason_units or [], "obligations": [], "confidence": "not_specified"}


def phrase(pid, kind, text, exact, obligation, when):
    return {"id": pid, "kind": kind, "text": text, "exact": exact, "obligation": obligation, "when": when}


def wire_map_from_openapi(api):
    tools = {}
    for path, item in api["paths"].items():
        name = path.strip("/")
        post = item["post"]
        req = post["requestBody"]["content"]["application/json"]["schema"]
        resp = post["responses"]["200"]["content"]["application/json"]["schema"]
        rf = {}
        for fname, fs in req["properties"].items():
            entry = {"type": fs.get("type", "string"), "required": fname in req.get("required", [])}
            if "enum" in fs:
                entry["enum"] = list(fs["enum"])
            if "description" in fs:
                entry["description"] = fs["description"]
            if "format" in fs:
                entry["format"] = fs["format"]
            rf[fname] = entry
        rsp = {}
        for fname, fs in resp["properties"].items():
            entry = {"type": fs.get("type", "string")}
            if "enum" in fs:
                entry["enum"] = list(fs["enum"])
            if fs.get("type") == "array":
                entry["items"] = {k: {"type": v.get("type", "string"), **({"enum": v["enum"]} if "enum" in v else {})}
                                  for k, v in fs["items"]["properties"].items()}
            rsp[fname] = entry
        tools[name] = {"path": path, "method": "POST", "request_fields": rf, "response_fields": rsp,
                       "summary": post.get("summary", "")}
    return tools


# ----------------------------------------------------------------------------------------------
# Brief A content
# ----------------------------------------------------------------------------------------------
HOLIDAYS = ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"]

CLOSE_ROWS_A = [
    {"outcome": "promise", "reason": None, "triggers": ["promise_recorded"], "precedence": 2,
     "units": ["a.t3.r1"], "obligations": ["O-a.r46.row.promise"], "line": "close_promise"},
    {"outcome": "paid", "reason": None, "triggers": ["paid_claim"], "precedence": 3,
     "units": ["a.t3.r2"], "obligations": ["O-a.r39"], "line": "close_paid"},
    {"outcome": "transferred", "reason": "restructuring", "triggers": ["transfer_done:restructuring"], "precedence": 1,
     "units": ["a.t3.r3"], "obligations": ["O-a.r41"], "line": "close_transferred"},
    {"outcome": "transferred", "reason": "human", "triggers": ["transfer_done:general"], "precedence": 1,
     "units": ["a.t3.r3"], "obligations": ["O-a.r42"], "line": "close_transferred"},
    {"outcome": "transferred", "reason": "support", "triggers": ["transfer_done:support"], "precedence": 1,
     "units": ["a.t3.r3"], "obligations": ["O-a.r32"], "line": "close_transferred"},
    {"outcome": "no_promise", "reason": "refused", "triggers": ["attempts_exhausted", "dont_want_twice_verified"],
     "precedence": 4, "units": ["a.t3.r4"], "obligations": ["O-a.r31", "O-a.r45"], "line": "close_no_promise"},
    {"outcome": "no_promise", "reason": "hardship", "triggers": ["hardship_support_declined"], "precedence": 4,
     "units": ["a.t3.r4"], "obligations": ["O-a.r32"], "line": "close_no_promise"},
    {"outcome": "no_promise", "reason": "dispute", "triggers": ["dispute"], "precedence": 4,
     "units": ["a.t3.r4"], "obligations": ["O-a.r40"], "line": "close_no_promise"},
    {"outcome": "no_promise", "reason": "service_error", "triggers": ["record_failed_twice"], "precedence": 4,
     "units": ["a.t3.r4"], "obligations": ["O-a.r37"], "line": "close_service_error"},
    {"outcome": "not_verified", "reason": "failed", "triggers": ["identity_failed"], "precedence": 5,
     "units": ["a.t3.r5"], "obligations": ["O-a.r14"], "line": "close_not_verified_failed"},
    {"outcome": "not_verified", "reason": "declined", "triggers": ["identity_declined", "dont_want_twice_unverified"],
     "precedence": 5, "units": ["a.t3.r5"], "obligations": ["O-a.r15", "O-a.r45"], "line": "close_not_verified_declined"},
    {"outcome": "not_reached", "reason": "callback", "triggers": ["callback_booked"], "precedence": 6,
     "units": ["a.t3.r6"], "obligations": ["O-a.r6"], "line": "close_callback"},
    {"outcome": "not_reached", "reason": "no_callback", "triggers": ["callback_refused_twice"], "precedence": 6,
     "units": ["a.t3.r6"], "obligations": ["O-a.r7"], "line": "close_no_callback"},
    {"outcome": "not_reached", "reason": "wrong_number", "triggers": ["wrong_number"], "precedence": 6,
     "units": ["a.t3.r6"], "obligations": ["O-a.r8"], "line": "close_wrong_number"},
    {"outcome": "not_reached", "reason": "deceased", "triggers": ["deceased"], "precedence": 6,
     "units": ["a.t3.r6"], "obligations": ["O-a.r9"], "line": "close_deceased"},
    {"outcome": "not_reached", "reason": "unclear", "triggers": ["party_unclear_twice"], "precedence": 6,
     "units": ["a.t3.r6"], "obligations": ["O-a.r3"], "line": "close_unclear"},
]


def obligations_a():
    O = []
    # --- 3. Opening and who is on the line
    O.append(ob("O-a.r1.1", ["a.r1.s1"], "First sentence: say you are a digital assistant calling from Freya Bank, and that the call is recorded.",
                "pre_verification", [{"say": {"content": "opening: a digital assistant calling from Freya Bank; the call is recorded"}}],
                kind="communication", stage_id="party"))
    O.append(ob("O-a.r1.2", ["a.r1.s2", "a.r1.s3"], 'Do not say "collections", "debt", "payment" or the product before identity is verified. This applies to everyone, including relatives.',
                "any", [{"forbid": "the words collections, debt, payment, and the product name"}],
                kind="prohibition", guards=["identity.state != 'verified'"]))
    O.append(ob("O-a.r2", ["a.r2"], 'Ask "Am I speaking with {title} {last_name}?".',
                "pre_verification", [{"ask": {"question_id": "party", "content": "Am I speaking with {title} {last_name}?"}}],
                kind="communication", stage_id="party"))
    O.append(ob("O-a.r3.def", ["a.r3.s1", "a.r3.s2"], 'Only "yes", "that\'s me", "speaking" or the customer\'s own name counts as confirmation. "Hello", "go ahead" and "who is this" do not.',
                "pre_verification", [{"other": "confirmation vocabulary; see parameters party.confirmation_words"}], kind="definition", stage_id="party"))
    O.append(ob("O-a.r3", ["a.r3.s3", "a.r3.s4"], "Ask once more. If it is still unclear after the second ask, close as `not_reached` / `unclear`.",
                "pre_verification", [{"count": {"counter": "party_asks", "max": 2}}, {"close": {"outcome": "not_reached", "reason": "unclear"}}],
                event="other", stage_id="party"))
    O.append(ob("O-a.r3.q", ["a.r3.s5", "a.r3.s6"], "Answer a question from the customer first (rules 4 and 43). The ask that follows is the second ask.",
                "pre_verification", [{"other": "answer the question first; the party ask that follows counts as the second ask"}],
                kind="ordering", event="question_back", stage_id="party"))
    O.append(ob("O-a.r4", ["a.r4"], "If the customer asks whether you are a robot or an AI, say that you are Freya Bank's digital assistant and continue.",
                "any", [{"say": {"content": "you are Freya Bank's digital assistant"}}, {"other": "continue where you were"}],
                kind="communication", event="robot_question"))
    # --- 4. Someone else answers
    O.append(ob("O-a.r5", ["a.r5"], "Do not say why you are calling. Say nothing beyond the opening sentence of rule 1. Ask when the customer can be reached.",
                "third_party", [{"forbid": "the reason for the call; anything beyond the opening sentence"}, {"ask": {"question_id": "callback", "content": "when the customer can be reached"}}],
                kind="communication", event="party_other", stage_id="party"))
    O.append(ob("O-a.r6", ["a.r6"], "A callback is for today or the next business day, from 10:00 to 19:00, both included, and later than `now`. Call `schedule_callback` with the date and the time, then close as `not_reached` / `callback`.",
                "third_party", [{"tool": {"name": "schedule_callback", "args": {"date": "callback.date", "time": "callback.time"}}}, {"close": {"outcome": "not_reached", "reason": "callback"}}],
                event="callback_offer", guards=["callback.in_window"], stage_id="party"))
    O.append(ob("O-a.r7", ["a.r7"], "If the person offers a day or a time outside that window, ask once for another time. If that is also outside it, do not schedule. Close as `not_reached` / `no_callback`.",
                "third_party", [{"count": {"counter": "callback.invalid", "max": 2}}, {"ask": {"question_id": "callback", "content": "another time inside the window"}}, {"close": {"outcome": "not_reached", "reason": "no_callback"}}],
                event="callback_offer", guards=["not callback.in_window"], stage_id="party"))
    O.append(ob("O-a.r8", ["a.r8"], "If the person says the number does not belong to the customer, close as `not_reached` / `wrong_number`.",
                "pre_verification", [{"close": {"outcome": "not_reached", "reason": "wrong_number"}}], event="party_wrong_number", stage_id="party"))
    O.append(ob("O-a.r9", ["a.r9"], 'If the person says the customer has died, say "I am sorry for your loss.", ask nothing else, and close as `not_reached` / `deceased`.',
                "pre_verification", [{"say": {"exact": "I am sorry for your loss."}}, {"stop": True}, {"close": {"outcome": "not_reached", "reason": "deceased"}}],
                event="party_deceased", stage_id="party"))
    O.append(ob("O-a.r10", ["a.r10"], "A relative may not answer the security questions and may not be told anything about the account, even if they offer to pay.",
                "third_party", [{"forbid": "security questions to a relative; any account information to a relative; a payment from a relative"}],
                kind="prohibition", stage_id="party"))
    # --- 5. Identity
    O.append(ob("O-a.r11", ["a.r11"], "Ask two security questions, one at a time: first the date of birth, then the last four digits of the phone number on file. Call `verify_identity` with the answer. Send a date of birth as `YYYY-MM-DD`, whatever way the customer said it. The service rejects anything it cannot read as a date. Read a date given only as numbers as day, then month, then year.",
                "identity", [{"ask": {"question_id": "date_of_birth"}}, {"ask": {"question_id": "phone_last4"}}, {"tool": {"name": "verify_identity", "args": {"field": "identity.question.wire_field", "answer": "identity.answer_formatted"}}}],
                kind="ordering", event="id_answer", stage_id="verify"))
    O.append(ob("O-a.r12", ["a.r12"], "A wrong answer may be asked again. Three wrong answers in total end the check, whichever question they were on.",
                "identity", [{"count": {"counter": "identity.wrong", "max": 3}}, {"ask": {"question_id": "same"}}], event="tool_result", stage_id="verify"))
    O.append(ob("O-a.r13", ["a.r13"], 'If the customer gives day and month the other way round, `verify_identity` returns `hint: "day_month_swapped"`. Ask them to say the month as a word. That retry does not count as a wrong answer.',
                "identity", [{"ask": {"question_id": "same", "content": "say the month as a word"}}], event="tool_result",
                guards=["tool_result.data.hint == 'day_month_swapped'"], exception_of="O-a.r12", stage_id="verify"))
    O.append(ob("O-a.r14", ["a.r14"], "After three wrong answers, do not state the debt. Tell the customer to use the mobile app or a branch. Close as `not_verified` / `failed`.",
                "identity", [{"forbid": "stating the debt"}, {"say": {"content": "use the mobile app or a branch"}}, {"close": {"outcome": "not_verified", "reason": "failed"}}],
                event="tool_result", guards=["identity.wrong >= 3"], stage_id="verify"))
    O.append(ob("O-a.r15", ["a.r15"], "If the customer does not want to answer, explain once that the questions protect their account. If they still decline, close as `not_verified` / `declined`. Asking what the call is about instead of answering counts as declining. A second refusal or a second such question closes the call.",
                "identity", [{"count": {"counter": "identity.declines", "max": 2}}, {"say": {"content": "the questions protect their account"}}, {"close": {"outcome": "not_verified", "reason": "declined"}}],
                event="id_decline", stage_id="verify", notes="asking what the call is about instead of answering is reported as id_decline; another question back (why do you need that) is answered and the question asked again, not counted"))
    # --- 6. Stating the debt
    O.append(ob("O-a.r16", ["a.r16"], "After both questions pass, call `get_account`.",
                "verified", [{"tool": {"name": "get_account", "args": {}}}], kind="ordering", stage_id="fetch"))
    O.append(ob("O-a.r17", ["a.r17"], 'Say that you are calling from the collections team about a late payment. Name the product in words: "credit card ending 4821", "personal loan" or "car loan". State the past-due amount and how many days late it is.',
                "disclosure", [{"say": {"content": "calling from the collections team about a late payment; the product in words; the past-due amount; the days late"}}],
                kind="communication", scope="product", stage_id="disclose"))
    # --- 7. Dates
    O.append(ob("O-a.r18", ["a.r18", "a.t2.r1", "a.t2.r2"], "The **deadline** depends on how late the customer is.",
                "negotiation", [{"other": "band, deadline and attempts per parameters bands[]"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r19", ["a.r19"], "A promise date must be today or later, a business day, and not after the deadline.",
                "negotiation", [{"other": "validate: today <= date <= deadline and business_day(date)"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r20", ["a.r20"], "If the customer names a weekend day or a holiday that is not after the deadline, offer the next business day. If the named day is after the deadline, rule 23 applies.",
                "negotiation", [{"offer": {"amount_rule": "same", "date_expr": "next_business_day(date)"}}], event="date_proposal",
                guards=["not business_day(date)", "date <= deadline"], scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r21", ["a.r21"], 'If the customer gives a vague period ("next week", "end of the month", "when my salary comes"), ask once for the exact day. If they still give none, propose the deadline.',
                "negotiation", [{"count": {"counter": "item.vague_asked", "max": 1}}, {"ask": {"question_id": "exact_day"}}, {"offer": {"amount_rule": "same", "date_expr": "deadline"}}],
                event="vague_period", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r22", ["a.r22"], '"Next <weekday>" means that weekday in the following calendar week. "This <weekday>" means the one in the current week.',
                "negotiation", [{"other": "this_weekday(w) / next_weekday(w) per parameters dates.this_next_rule"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r23", ["a.r23"], "If the customer asks for a date after the deadline, say the latest date you can record is the deadline and offer it. If the customer refuses the deadline, treat it as a flat refusal (rule 30).",
                "negotiation", [{"say": {"content": "the latest date you can record is the deadline"}}, {"offer": {"amount_rule": "same", "date_expr": "deadline"}}],
                event="date_proposal", guards=["date > deadline"], scope="product", stage_id="negotiate", notes="refusal of the deadline offer -> refuse -> O-a.r30"))
    # --- 8. Amounts
    O.append(ob("O-a.r24", ["a.r24"], 'Ask for the full past-due amount first. Never ask "how much can you pay?". The agent proposes every amount.',
                "negotiation", [{"offer": {"amount_rule": "product.past_due", "date_expr": "today"}}, {"forbid": 'asking "how much can you pay?" or any question that lets the customer name the amount'}],
                kind="communication", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r25", ["a.r25"], "The **floor** is `minimum_payment` for a credit card and `instalment_amount` for a personal loan or a car loan.",
                "negotiation", [{"other": "floor per parameters amounts.floor_expr"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r26", ["a.r26"], "If the customer says the full amount is too much, offer the floor, once. Say that the rest stays overdue. If the customer refuses the floor, treat it as a flat refusal (rule 30). Attempt 2 may name the floor again, on the deadline.",
                "negotiation", [{"offer": {"amount_rule": "floor", "date_expr": "same", "once": True}}, {"say": {"content": "the rest stays overdue"}}],
                event="too_much", scope="product", stage_id="negotiate", notes="refusal of the floor -> refuse -> O-a.r30; attempt 2 may repeat the floor on the deadline"))
    O.append(ob("O-a.r27", ["a.r27"], "If the customer proposes an amount from the floor up to the full amount, both included, accept it. Below the floor, say it cannot be recorded and offer the floor once. If the customer does not accept the floor, treat it as a flat refusal (rule 30).",
                "negotiation", [{"other": "floor <= amount <= past_due: accept"}, {"say": {"content": "an amount below the floor cannot be recorded"}}, {"offer": {"amount_rule": "floor", "date_expr": "same", "once": True}}],
                event="amount_proposal", scope="product", stage_id="negotiate"))
    # --- 9. Getting the promise
    O.append(ob("O-a.r28", ["a.r28"], 'First ask: "Can you make this payment today?".',
                "negotiation", [{"ask": {"question_id": "pay_today", "content": "Can you make this payment today?"}}], kind="communication", stage_id="negotiate"))
    O.append(ob("O-a.r29", ["a.r29"], "A date or an amount the customer proposes is never a refusal. Handle it with sections 7 and 8.",
                "negotiation", [{"other": "date_proposal / amount_proposal never consume an attempt"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r30", ["a.r30.s1", "a.r30.s2", "a.r30.s3"], "A flat refusal or a non-answer uses one persuasion attempt. A no to paying today with no date and no amount is a flat refusal. Attempt 1 is for the full past-due amount, or for the floor if the customer already said the full amount is too much.",
                "negotiation", [{"count": {"counter": "item.attempts_used", "max": 2}}, {"offer": {"amount_rule": "floor if item.too_much else product.past_due", "date_expr": "attempts[n].date_expr"}}],
                event="refuse", scope="product", stage_id="negotiate", notes="pay_today_no with no date and no amount is a refuse event"))
    O.append(ob("O-a.r30.a1", ["a.r30.b1"], "Attempt 1: propose the last business day of this week. If today is that day, propose the last business day of next week.",
                "negotiation", [{"offer": {"amount_rule": "floor if item.too_much else product.past_due", "date_expr": "last_business_day_of_next_week(today) if last_business_day_of_week(today) == today else last_business_day_of_week(today)"}}],
                event="refuse", guards=["item.attempts_used == 0"], scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r30.a2", ["a.r30.b2"], "Attempt 2, late band only: propose the floor amount on the deadline.",
                "negotiation", [{"offer": {"amount_rule": "floor", "date_expr": "deadline"}}],
                event="refuse", guards=["item.attempts_used == 1", "item.band == 'late'"], scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r31", ["a.r31"], "When the attempts are used up, stop. Do not repeat an offer the customer already refused. Close as `no_promise` / `refused`.",
                "negotiation", [{"stop": True}, {"forbid": "repeating an offer the customer already refused"}, {"close": {"outcome": "no_promise", "reason": "refused"}}],
                event="refuse", guards=["item.attempts_used >= item.attempts_allowed"], scope="product", stage_id="negotiate"))
    O.append(ob("O-a.r32", ["a.r32"], "If the customer mentions illness, a death in the family or job loss, say one short sentence of sympathy and make no persuasion attempt. Offer to connect them with the customer support team. If they accept, call `transfer_to_agent` with queue `support` and close as `transferred` / `support`. If they decline, close as `no_promise` / `hardship`. This rule comes before rules 30 and 41. If the customer still names a date or an amount themselves, record the promise under sections 7 and 8.",
                "verified", [{"say": {"content": "one short sentence of sympathy"}}, {"forbid": "any persuasion attempt"}, {"ask": {"question_id": "support_offer", "content": "offer to connect them with the customer support team"}}, {"transfer": {"queue": "support"}}, {"close": {"outcome": "transferred", "reason": "support"}}, {"close": {"outcome": "no_promise", "reason": "hardship"}}, {"other": "a date or amount the customer names themselves is still recorded"}],
                event="hardship", precedence=["before O-a.r30", "before O-a.r41"], stage_id="negotiate"))
    O.append(ob("O-a.r33", ["a.r33"], "Never offer a discount, a waiver, an instalment plan or any term that is not in this brief.",
                "any", [{"forbid": "a discount, a waiver, an instalment plan or any term not in the brief"}], kind="prohibition"))
    # --- 10. Confirming and recording
    O.append(ob("O-a.r34", ["a.r34"], 'Read the product, the amount and the date back and ask "Do you confirm?". Call `create_promise` only after a clear yes.',
                "readback", [{"say": {"content": "read back the product, the amount and the date"}}, {"ask": {"question_id": "confirm", "content": "Do you confirm?"}}, {"tool": {"name": "create_promise", "args": {"product_id": "item.item_id", "amount": "item.agreed.amount", "date": "item.agreed.date"}}}],
                kind="ordering", event="confirm", scope="product", stage_id="readback"))
    O.append(ob("O-a.r35", ["a.r35"], "If the customer changes the date or the amount at this step, check the new value against sections 7 and 8 and read it back again.",
                "readback", [{"other": "re-validate the changed value; read back again (new version)"}], event="change", scope="product", stage_id="readback"))
    O.append(ob("O-a.r36", ["a.r36"], "One promise per product. A recorded promise cannot be changed or cancelled in the same call. If the customer asks, say they can change it in the mobile app.",
                "recording", [{"forbid": "a second promise on the same product; changing or cancelling a recorded promise"}, {"say": {"content": "they can change it in the mobile app"}}],
                event="change", guards=["item.recorded"], scope="product", stage_id="record"))
    O.append(ob("O-a.r37", ["a.r37"], "Say the promise is recorded only after `create_promise` returns `ok: true`. If it fails, try once more. If it fails again, say you could not record it and close as `no_promise` / `service_error`.",
                "recording", [{"forbid": "saying the promise is recorded before ok true"}, {"count": {"counter": "item.record_failures", "max": 2}}, {"say": {"content": "you could not record it"}}, {"close": {"outcome": "no_promise", "reason": "service_error"}}],
                event="tool_result", scope="product", stage_id="record"))
    O.append(ob("O-a.r38", ["a.r38"], 'After a recorded promise, say this sentence: "You will receive a text message confirming this promise."',
                "recording", [{"say": {"exact": "You will receive a text message confirming this promise."}}], kind="communication", event="tool_result",
                guards=["tool_result.result == 'ok'"], scope="product", stage_id="record"))
    # --- 11. Other things customers say
    O.append(ob("O-a.r39", ["a.r39"], '"I already paid": say that payments can take one business day to appear, take no promise, and close as `paid`.',
                "verified", [{"say": {"content": "payments can take one business day to appear"}}, {"forbid": "taking a promise"}, {"close": {"outcome": "paid", "reason": None}}],
                event="paid", stage_id="negotiate"))
    O.append(ob("O-a.r40", ["a.r40"], '"This debt is not mine" or "I never had this product": do not argue and do not take a promise. Close as `no_promise` / `dispute`. A claim that the product was closed or paid off in the past is a dispute. Rule 39 covers only a payment of this past-due amount.',
                "verified", [{"forbid": "arguing; taking a promise"}, {"close": {"outcome": "no_promise", "reason": "dispute"}}], event="dispute", stage_id="negotiate"))
    O.append(ob("O-a.r41", ["a.r41"], "A request for a new payment plan or lower instalments: do not describe a plan. Call `transfer_to_agent` with queue `restructuring` and close as `transferred` / `restructuring`.",
                "verified", [{"forbid": "describing a plan"}, {"transfer": {"queue": "restructuring"}}, {"close": {"outcome": "transferred", "reason": "restructuring"}}], event="plan_request", stage_id="negotiate"))
    O.append(ob("O-a.r42", ["a.r42"], "A request for a human: ask once whether you can help first. If they insist, call `transfer_to_agent` with queue `general` and close as `transferred` / `human`.",
                "any", [{"count": {"counter": "global.human_asked_once", "max": 1}}, {"ask": {"question_id": "can_i_help", "content": "ask once whether you can help first"}}, {"transfer": {"queue": "general"}}, {"close": {"outcome": "transferred", "reason": "human"}}], event="human"))
    O.append(ob("O-a.r43", ["a.r43"], '"Is this a scam?": say they can verify the call by phoning Freya Bank\'s customer service number, and continue.',
                "any", [{"say": {"content": "they can verify the call by phoning Freya Bank's customer service number"}}, {"other": "continue where you were"}], kind="communication", event="scam_question"))
    O.append(ob("O-a.r44", ["a.r44"], "A question you cannot answer from the tools: say you do not have that information. Do not invent figures, dates or reasons.",
                "any", [{"say": {"content": "you do not have that information"}}, {"forbid": "inventing figures, dates or reasons"}], kind="communication", event="other"))
    O.append(ob("O-a.r45", ["a.r45"], "If the customer says twice that they do not want to talk, close as `no_promise` / `refused`. Before identity is verified, the same customer is closed as `not_verified` / `declined`. Rule 42 applies before and after verification.",
                "any", [{"count": {"counter": "global.dont_want", "max": 2}}, {"close": {"outcome": "no_promise", "reason": "refused"}}, {"close": {"outcome": "not_verified", "reason": "declined"}}],
                event="dont_want_to_talk", notes="verified -> no_promise/refused; not verified -> not_verified/declined"))
    # --- 12. Closing
    O.append(ob("O-a.r46", ["a.r46.s1", "a.r46.s2"], "Every call ends with exactly one `close_call`, with an outcome and, where the table lists one, a reason. It is the last tool call.",
                "closing", [{"tool": {"name": "close_call", "args": {"outcome": "close.outcome", "reason": "close.reason"}}}, {"stop": True}], kind="ordering", stage_id="close"))
    O.append(ob("O-a.r46.row.promise", ["a.t3.r1"], "Outcome: `promise`; Reason: none; When: at least one promise was recorded",
                "closing", [{"close": {"outcome": "promise", "reason": None}}], guards=["any(item.recorded)"], stage_id="close"))
    O.append(ob("O-a.r46.transfer", ["a.p6"], "If a transfer follows a recorded promise, close as `transferred` with that transfer's reason.",
                "closing", [{"close": {"outcome": "transferred", "reason": "transfer.reason"}}], guards=["transfer.done"], precedence=["before O-a.r46.row.promise"], stage_id="close"))
    O.append(ob("O-a.r46.no_note", ["a.p7"], "Brief A never uses `add_note`.",
                "any", [{"forbid": "add_note"}], kind="prohibition", stage_id="close"))
    O.append(ob("O-a.r47", ["a.r47"], "Thank the customer and say goodbye before `close_call`.",
                "closing", [{"say": {"content": "thank the customer and say goodbye"}}], kind="communication", precedence=["before O-a.r46"], stage_id="close"))
    return O


def parameters_a():
    P = {}
    P["organisation.name"] = val("Freya Bank", "string", ["a digital assistant calling from Freya Bank"], ["a.r1.s1"], ["O-a.r1.1"])
    P["organisation.assistant_label"] = val("digital assistant", "string", ["say you are a digital assistant calling from Freya Bank"], ["a.r1.s1"], ["O-a.r1.1"])
    P["organisation.team"] = val("collections team", "string", ["calling from the collections team about a late payment"], ["a.r17"], ["O-a.r17"])
    P["party.confirmation_words"] = val(["yes", "that's me", "speaking", "{customer_own_name}"], "list[string]",
                                        ['Only "yes", "that\'s me", "speaking" or the customer\'s own name counts as confirmation.'], ["a.r3.s1"], ["O-a.r3.def"])
    P["party.non_confirmation_words"] = val(["hello", "go ahead", "who is this"], "list[string]", ['"Hello", "go ahead" and "who is this" do not.'], ["a.r3.s2"], ["O-a.r3.def"])
    P["party.max_asks"] = val(2, "integer", ["Ask once more. If it is still unclear after the second ask, close as `not_reached` / `unclear`."], ["a.r3.s3", "a.r3.s4"], ["O-a.r3"])
    P["third_party.callback.window"] = val({"days_expr": ["today", "next_business_day(today)"], "start": "10:00", "end": "19:00", "inclusive": True, "later_than": "now"},
                                           "window", ["A callback is for today or the next business day, from 10:00 to 19:00, both included, and later than `now`."], ["a.r6"], ["O-a.r6"])
    P["third_party.callback.max_invalid"] = val(2, "integer", ["ask once for another time. If that is also outside it, do not schedule."], ["a.r7"], ["O-a.r7"])
    P["identity.questions"] = val([
        {"id": "date_of_birth", "wire_field": "date_of_birth", "type": "date", "order": 1,
         "text": "What is your date of birth?",
         "parse_rule": "send as YYYY-MM-DD whatever way the customer said it; numbers only are read day, month, year"},
        {"id": "phone_last4", "wire_field": "phone_last4", "type": "digits:4", "order": 2,
         "text": "What are the last four digits of the phone number on file?",
         "parse_rule": "four digits"}],
        "list[question]", ["Ask two security questions, one at a time: first the date of birth, then the last four digits of the phone number on file.",
                           "Send a date of birth as `YYYY-MM-DD`, whatever way the customer said it.", "Read a date given only as numbers as day, then month, then year."],
        ["a.r11"], ["O-a.r11"])
    P["identity.max_wrong"] = val(3, "integer", ["Three wrong answers in total end the check, whichever question they were on."], ["a.r12"], ["O-a.r12"])
    P["identity.hint_rule"] = val({"hint": "day_month_swapped", "ask": "say the month as a word", "counts_as_wrong": False},
                                  "hint_rule", ['`verify_identity` returns `hint: "day_month_swapped"`. Ask them to say the month as a word. That retry does not count as a wrong answer.'], ["a.r13"], ["O-a.r13"])
    P["identity.decline_rule"] = val({"explain_once": "the questions protect their account", "max_declines": 2, "question_about_call_counts_as_decline": True},
                                     "decline_rule", ["explain once that the questions protect their account. If they still decline, close as `not_verified` / `declined`. Asking what the call is about instead of answering counts as declining. A second refusal or a second such question closes the call."], ["a.r15"], ["O-a.r15"])
    P["identity.failed_message"] = val("use the mobile app or a branch", "content", ["Tell the customer to use the mobile app or a branch."], ["a.r14"], ["O-a.r14"])
    P["calendar.holidays"] = val(HOLIDAYS, "list[date]", ["except Freya Bank holidays: 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01."], ["a.p5"])
    P["calendar.business_days"] = val("Monday to Friday", "string", ["Business days are Monday to Friday"], ["a.p5"])
    P["bands"] = val([
        {"id": "early", "condition": "1 <= product.days_late <= 7", "deadline_expr": "business_days_after(today, 12)", "attempts": 1},
        {"id": "late", "condition": "8 <= product.days_late <= 45", "deadline_expr": "business_days_after(today, 7)", "attempts": 2}],
        "list[band]", ["1 to 7 | early | the 12th business day after today | 1", "8 to 45 | late | the 7th business day after today | 2"], ["a.t2.r1", "a.t2.r2"], ["O-a.r18"])
    P["dates.valid_rule"] = val("today <= date <= deadline and business_day(date)", "expr", ["A promise date must be today or later, a business day, and not after the deadline."], ["a.r19"], ["O-a.r19"])
    P["dates.non_business_rule"] = val("next_business_day(date)", "expr", ["offer the next business day"], ["a.r20"], ["O-a.r20"])
    P["dates.after_deadline_rule"] = val("deadline", "expr", ["say the latest date you can record is the deadline and offer it"], ["a.r23"], ["O-a.r23"])
    P["dates.vague_rule"] = val({"ask_once": True, "then": "deadline", "examples": ["next week", "end of the month", "when my salary comes"]}, "vague_rule",
                                ["ask once for the exact day. If they still give none, propose the deadline."], ["a.r21"], ["O-a.r21"])
    P["dates.this_next_rule"] = val({"this": "this_weekday(w)", "next": "next_weekday(w)"}, "weekday_rule",
                                    ['"Next <weekday>" means that weekday in the following calendar week. "This <weekday>" means the one in the current week.'], ["a.r22"], ["O-a.r22"])
    P["dates.bare_weekday_rule"] = not_specified("weekday_rule", ["a.r22"])
    P["amounts.floor_expr"] = val("product.minimum_payment if product.type == 'credit_card' else product.instalment_amount", "expr",
                                  ["The **floor** is `minimum_payment` for a credit card and `instalment_amount` for a personal loan or a car loan."], ["a.r25"], ["O-a.r25"])
    P["amounts.range_rule"] = val({"min": "floor", "max": "product.past_due", "inclusive": True, "below_floor": "say it cannot be recorded; offer the floor once"}, "range_rule",
                                  ["from the floor up to the full amount, both included, accept it. Below the floor, say it cannot be recorded and offer the floor once."], ["a.r27"], ["O-a.r27"])
    P["amounts.too_much_rule"] = val({"offer": "floor", "once": True, "say": "the rest stays overdue"}, "rule",
                                     ["offer the floor, once. Say that the rest stays overdue."], ["a.r26"], ["O-a.r26"])
    P["attempts"] = val([
        {"n": 1, "amount_rule": "floor if item.too_much else product.past_due",
         "date_expr": "last_business_day_of_next_week(today) if last_business_day_of_week(today) == today else last_business_day_of_week(today)", "band": "any"},
        {"n": 2, "amount_rule": "floor", "date_expr": "deadline", "band": "late"}],
        "list[attempt]", ["Attempt 1: propose the last business day of this week. If today is that day, propose the last business day of next week.",
                          "Attempt 2, late band only: propose the floor amount on the deadline."], ["a.r30.b1", "a.r30.b2"], ["O-a.r30.a1", "O-a.r30.a2"])
    P["situations"] = val({
        "hardship": {"obligation": "O-a.r32", "triggers": ["illness", "a death in the family", "job loss"], "say": "one short sentence of sympathy", "offer": "customer support team", "transfer_queue": "support", "accept_close": ["transferred", "support"], "decline_close": ["no_promise", "hardship"], "persuasion": "none", "voluntary_promise": "record"},
        "paid": {"obligation": "O-a.r39", "say": "payments can take one business day to appear", "promise": "none", "close": ["paid", None]},
        "dispute": {"obligation": "O-a.r40", "includes": ["debt is not mine", "never had this product", "product closed or paid off in the past"], "promise": "none", "argue": "never", "close": ["no_promise", "dispute"]},
        "plan_request": {"obligation": "O-a.r41", "describe_plan": "never", "transfer_queue": "restructuring", "close": ["transferred", "restructuring"]},
        "human": {"obligation": "O-a.r42", "ask_first_once": True, "transfer_queue": "general", "close": ["transferred", "human"], "applies": "before and after verification"},
        "scam": {"obligation": "O-a.r43", "say": "they can verify the call by phoning Freya Bank's customer service number", "then": "continue"},
        "robot": {"obligation": "O-a.r4", "say": "you are Freya Bank's digital assistant", "then": "continue"},
        "deceased": {"obligation": "O-a.r9", "say_exact": "I am sorry for your loss.", "ask": "nothing else", "close": ["not_reached", "deceased"]},
        "wrong_number": {"obligation": "O-a.r8", "close": ["not_reached", "wrong_number"]},
        "dont_want_to_talk": {"obligation": "O-a.r45", "count": 2, "close_verified": ["no_promise", "refused"], "close_unverified": ["not_verified", "declined"]},
        "unknown_question": {"obligation": "O-a.r44", "say": "you do not have that information"}},
        "situations", ["see the cited units"], ["a.r32", "a.r39", "a.r40", "a.r41", "a.r42", "a.r43", "a.r4", "a.r9", "a.r8", "a.r45", "a.r44"],
        ["O-a.r32", "O-a.r39", "O-a.r40", "O-a.r41", "O-a.r42", "O-a.r43", "O-a.r4", "O-a.r9", "O-a.r8", "O-a.r45", "O-a.r44"])
    P["recording.retries"] = val(1, "integer", ["If it fails, try once more. If it fails again, say you could not record it"], ["a.r37"], ["O-a.r37"])
    P["recording.confirm_rule"] = val("a clear yes to the read-back", "content", ["Call `create_promise` only after a clear yes."], ["a.r34"], ["O-a.r34"])
    P["multi.max_items"] = val(1, "integer", ["Freya Bank calls customers who are 1 to 45 days late on one product."], ["a.p3"], [])
    P["multi.order"] = val("get_account", "string", ["one product"], ["a.p3"], [], confidence="derived")
    P["closing.rows"] = val(CLOSE_ROWS_A, "list[row]", ["see the closing table"], ["a.t3.r1", "a.t3.r2", "a.t3.r3", "a.t3.r4", "a.t3.r5", "a.t3.r6", "a.p6"],
                            ["O-a.r46", "O-a.r46.row.promise", "O-a.r46.transfer"])
    P["closing.precedence_rule"] = val("transferred before promise before paid before no_promise; not_verified and not_reached only before verification",
                                       "content", ["If a transfer follows a recorded promise, close as `transferred` with that transfer's reason."], ["a.p6"], ["O-a.r46.transfer"], confidence="derived")
    P["call_variables"] = val(["customer_id", "first_name", "last_name", "title", "now"], "list[string]",
                              ["Every call starts with these."], ["a.t1.r1", "a.t1.r2", "a.t1.r3", "a.t1.r4"])
    P["call.address_form"] = val("{title} {last_name}", "template", ["Address the customer as title plus last name."], ["a.t1.r3"])
    P["call.clock"] = val("now", "string", ["All date rules use this, never the real clock."], ["a.t1.r4"])
    return P


def phrases_a():
    return [
        phrase("opening", "mandatory", "Hello, this is a digital assistant calling from Freya Bank. This call is recorded.", False, "O-a.r1.1", "first sentence of the call"),
        phrase("party_question", "mandatory", "Am I speaking with {title} {last_name}?", True, "O-a.r2", "after the opening; again on the second ask"),
        phrase("robot_answer", "mandatory", "I am Freya Bank's digital assistant.", False, "O-a.r4", "customer asks whether you are a robot or an AI"),
        phrase("callback_question", "mandatory", "When can {title} {last_name} be reached?", False, "O-a.r5", "someone else answers"),
        phrase("sorry_loss", "mandatory", "I am sorry for your loss.", True, "O-a.r9", "the person says the customer has died"),
        phrase("ask_date_of_birth", "mandatory", "Before I continue, I need to ask you two security questions. What is your date of birth?", False, "O-a.r11", "first identity question"),
        phrase("ask_phone_last4", "mandatory", "Thank you. What are the last four digits of the phone number on file?", False, "O-a.r11", "second identity question"),
        phrase("month_as_word", "mandatory", "Could you say your date of birth again, with the month as a word?", False, "O-a.r13", "verify_identity returned hint day_month_swapped"),
        phrase("questions_protect", "mandatory", "These questions protect your account. I can explain the reason for the call once they are done.", False, "O-a.r15", "first decline during identity"),
        phrase("use_app_or_branch", "mandatory", "I could not verify your identity, so I cannot continue with this call. Please use the mobile app or visit a branch.", False, "O-a.r14", "third wrong answer"),
        phrase("disclosure", "mandatory", "I am calling from the collections team about a late payment.", False, "O-a.r17", "right after verification, before any question"),
        phrase("pay_today", "mandatory", "Can you make this payment today?", True, "O-a.r28", "first question after the disclosure"),
        phrase("rest_overdue", "mandatory", "The rest stays overdue.", False, "O-a.r26", "the floor is offered after too much"),
        phrase("below_floor", "mandatory", "An amount below the minimum cannot be recorded.", False, "O-a.r27", "amount below the floor"),
        phrase("latest_is_deadline", "mandatory", "The latest date I can record is {deadline}.", False, "O-a.r23", "date after the deadline"),
        phrase("do_you_confirm", "mandatory", "Do you confirm?", True, "O-a.r34", "after the read-back"),
        phrase("text_message", "mandatory", "You will receive a text message confirming this promise.", True, "O-a.r38", "after create_promise returned ok true"),
        phrase("promise_recorded", "mandatory", "Your promise is recorded.", False, "O-a.r37", "only after create_promise returned ok true"),
        phrase("could_not_record", "mandatory", "I am sorry, I could not record your promise because of a technical problem.", False, "O-a.r37", "create_promise failed twice"),
        phrase("change_in_app", "mandatory", "A recorded promise cannot be changed in this call. You can change it in the mobile app.", False, "O-a.r36", "customer asks to change or cancel a recorded promise"),
        phrase("paid_takes_day", "mandatory", "Payments can take one business day to appear.", False, "O-a.r39", "customer says they already paid"),
        phrase("sympathy", "mandatory", "I am sorry to hear that.", False, "O-a.r32", "illness, a death in the family or job loss"),
        phrase("support_offer", "mandatory", "Would you like me to connect you with our customer support team?", False, "O-a.r32", "after the sympathy sentence"),
        phrase("can_i_help", "mandatory", "Is there something I can help you with first?", False, "O-a.r42", "customer asks for a human, first time"),
        phrase("scam_answer", "mandatory", "You can verify this call by phoning Freya Bank's customer service number.", False, "O-a.r43", "customer asks whether this is a scam"),
        phrase("no_information", "mandatory", "I do not have that information.", False, "O-a.r44", "a question the tools cannot answer"),
        phrase("thanks_goodbye", "mandatory", "Thank you, goodbye.", False, "O-a.r47", "before close_call"),
        phrase("close_promise", "mandatory", "Thank you for your time.", False, "O-a.r47", "closing line for outcome promise"),
        phrase("close_paid", "mandatory", "Thank you for letting me know.", False, "O-a.r39", "closing line for outcome paid"),
        phrase("close_transferred", "mandatory", "I am transferring you to a colleague now.", False, "O-a.r42", "closing line for outcome transferred"),
        phrase("close_no_promise", "mandatory", "I understand.", False, "O-a.r31", "closing line for outcome no_promise"),
        phrase("close_service_error", "mandatory", "I am sorry, I could not record your promise because of a technical problem.", False, "O-a.r37", "closing line for no_promise / service_error"),
        phrase("close_not_verified_failed", "mandatory", "I could not verify your identity, so I cannot continue with this call. Please use the mobile app or visit a branch.", False, "O-a.r14", "closing line for not_verified / failed"),
        phrase("close_not_verified_declined", "mandatory", "I understand. I cannot continue without the security questions.", False, "O-a.r15", "closing line for not_verified / declined"),
        phrase("close_callback", "mandatory", "Thank you, we will call back at that time.", False, "O-a.r6", "closing line for not_reached / callback"),
        phrase("close_no_callback", "mandatory", "I understand, I will not schedule a callback.", False, "O-a.r7", "closing line for not_reached / no_callback"),
        phrase("close_wrong_number", "mandatory", "I apologise for the inconvenience.", False, "O-a.r8", "closing line for not_reached / wrong_number"),
        phrase("close_deceased", "mandatory", "I am sorry for your loss.", True, "O-a.r9", "closing line for not_reached / deceased"),
        phrase("close_unclear", "mandatory", "I am sorry, I could not confirm who I am speaking with.", False, "O-a.r3", "closing line for not_reached / unclear"),
        phrase("forbid_pre_verification_words", "forbidden", "collections; debt; payment; the product name", True, "O-a.r1.2", "before identity is verified, to everyone including relatives"),
        phrase("forbid_reason_third_party", "forbidden", "why you are calling", False, "O-a.r5", "someone else answers"),
        phrase("forbid_how_much", "forbidden", "how much can you pay?", True, "O-a.r24", "always"),
        phrase("forbid_terms", "forbidden", "a discount, a waiver, an instalment plan or any term that is not in this brief", False, "O-a.r33", "always"),
        phrase("forbid_recorded_claim", "forbidden", "recorded", True, "O-a.r37", "before create_promise returned ok true"),
        phrase("forbid_repeat_refused", "forbidden", "an offer the customer already refused", False, "O-a.r31", "negotiation"),
        phrase("forbid_invent", "forbidden", "invented figures, dates or reasons", False, "O-a.r44", "always"),
    ]


def examples_a():
    return [
        {"unit": "a.r22", "input": {"now": "2026-10-16T11:00", "text": "next Friday"}, "expected": "2026-10-23"},
        {"unit": "a.r11", "input": {"text": "3/4/1985"}, "expected": "1985-04-03"},
        {"unit": "a.r30.b1", "input": {"now": "2026-10-14T11:00"}, "expected": "2026-10-16"},
        {"unit": "a.r30.b1", "input": {"now": "2026-10-16T11:00"}, "expected": "2026-10-23"},
        {"unit": "a.t2.r1", "input": {"now": "2026-10-14T11:00", "days_late": 6}, "expected": {"band": "early", "deadline": "2026-11-02", "attempts": 1}},
        {"unit": "a.t2.r2", "input": {"now": "2026-10-14T11:00", "days_late": 14}, "expected": {"band": "late", "deadline": "2026-10-23", "attempts": 2}},
        {"unit": "a.r6", "input": {"now": "2026-10-14T11:00", "date": "2026-10-14", "time": "10:30"}, "expected": False},
        {"unit": "a.r6", "input": {"now": "2026-10-14T11:00", "date": "2026-10-15", "time": "19:00"}, "expected": True},
    ]


def open_questions_a():
    return [
        {"topic": "bare weekday", "readings": ["the next such day from today", "this week's day per rule 22"],
         "taken": "the next such day strictly after today", "rule": "a.r22 is silent on a weekday said without this/next"},
        {"topic": "closing precedence", "readings": ["table order", "transferred > promise > paid > no_promise"],
         "taken": "transferred first (a.p9), then promise, then paid, then no_promise; not_verified and not_reached only before verification",
         "rule": "a.p6 and a.t3.r1"},
        {"topic": "turn cap", "readings": ["no rule"], "taken": "say goodbye and end the call without close_call; our scorer counts it as FAIL", "rule": "none in the brief"},
        {"topic": "date in the past", "readings": ["treat as invalid, ask again", "treat as flat refusal"],
         "taken": "say it cannot be recorded and ask for a date from today; no attempt used", "rule": "a.r19 (today or later), a.r29 (a date is never a refusal)"},
        {"topic": "hardship before verification", "readings": ["rule 32 applies any time", "rule 32 applies after verification only"],
         "taken": "sympathy sentence any time; the support offer and the hardship close only after verification; before it the identity check continues",
         "rule": "a.r32 sits in section 9 (getting the promise)"},
        {"topic": "pay-today yes", "readings": ["record at once", "read back first"],
         "taken": "a yes to paying today is an agreed promise for the full amount today and goes to the read-back", "rule": "a.r34 applies to every promise"},
    ]


def plan_a():
    return [
        {"id": "party", "type": "party", "params": {}, "obligations": ["O-a.r1.1", "O-a.r2", "O-a.r3", "O-a.r3.q", "O-a.r5", "O-a.r6", "O-a.r7", "O-a.r8", "O-a.r9", "O-a.r10"], "units": ["a.r1", "a.r2", "a.r3"], "per_item": False, "gates": []},
        {"id": "verify", "type": "verify", "params": {"questions": "identity.questions"}, "obligations": ["O-a.r11", "O-a.r12", "O-a.r13", "O-a.r14", "O-a.r15"], "units": ["a.r11"], "per_item": False, "gates": ["fetch", "disclose", "negotiate", "readback", "record"]},
        {"id": "fetch", "type": "fetch", "params": {"tool": "get_account"}, "obligations": ["O-a.r16"], "units": ["a.r16"], "per_item": False, "gates": []},
        {"id": "disclose", "type": "disclose", "params": {}, "obligations": ["O-a.r17"], "units": ["a.r17"], "per_item": True, "gates": []},
        {"id": "negotiate", "type": "negotiate", "params": {}, "obligations": ["O-a.r18", "O-a.r19", "O-a.r20", "O-a.r21", "O-a.r22", "O-a.r23", "O-a.r24", "O-a.r25", "O-a.r26", "O-a.r27", "O-a.r28", "O-a.r29", "O-a.r30", "O-a.r30.a1", "O-a.r30.a2", "O-a.r31", "O-a.r32"], "units": ["a.r28", "a.r30"], "per_item": True, "gates": []},
        {"id": "readback", "type": "readback", "params": {}, "obligations": ["O-a.r34", "O-a.r35"], "units": ["a.r34"], "per_item": False, "gates": []},
        {"id": "record", "type": "record", "params": {"tool": "create_promise", "retries": "recording.retries"}, "obligations": ["O-a.r36", "O-a.r37", "O-a.r38"], "units": ["a.r37"], "per_item": True, "gates": []},
        {"id": "close", "type": "close", "params": {"tool": "close_call", "rows": "closing.rows"}, "obligations": ["O-a.r46", "O-a.r46.row.promise", "O-a.r46.transfer", "O-a.r47"], "units": ["a.r46", "a.r47"], "per_item": False, "gates": []},
    ]


def wire_concepts_a():
    return {
        "identity.date_of_birth": {"tool": "verify_identity", "field": "field", "wire": "date_of_birth", "units": ["a.r11"]},
        "identity.phone_last4": {"tool": "verify_identity", "field": "field", "wire": "phone_last4", "units": ["a.r11"]},
        "identity.answer": {"tool": "verify_identity", "field": "answer", "wire": "answer", "units": ["a.r11"]},
        "identity.hint.day_month_swapped": {"tool": "verify_identity", "field": "hint", "wire": "day_month_swapped", "units": ["a.r13"]},
        "identity.verified": {"tool": "verify_identity", "field": "verified", "wire": "verified", "units": ["a.r12"]},
        "identity.all_verified": {"tool": "verify_identity", "field": "all_verified", "wire": "all_verified", "units": ["a.r16"]},
        "identity.wrong_answers_left": {"tool": "verify_identity", "field": "wrong_answers_left", "wire": "wrong_answers_left", "units": ["a.r12"]},
        "product.list": {"tool": "get_account", "field": "products", "wire": "products", "units": ["a.r16"]},
        "product.id": {"tool": "get_account", "field": "products[].product_id", "wire": "product_id", "units": ["a.r34"]},
        "product.type": {"tool": "get_account", "field": "products[].type", "wire": "type", "units": ["a.r17"]},
        "product.card_last4": {"tool": "get_account", "field": "products[].card_last4", "wire": "card_last4", "units": ["a.r17"]},
        "product.past_due": {"tool": "get_account", "field": "products[].past_due", "wire": "past_due", "units": ["a.r17"]},
        "product.days_late": {"tool": "get_account", "field": "products[].days_late", "wire": "days_late", "units": ["a.r17", "a.r18"]},
        "product.minimum_payment": {"tool": "get_account", "field": "products[].minimum_payment", "wire": "minimum_payment", "units": ["a.r25"]},
        "product.instalment_amount": {"tool": "get_account", "field": "products[].instalment_amount", "wire": "instalment_amount", "units": ["a.r25"]},
        "promise.product_id": {"tool": "create_promise", "field": "product_id", "wire": "product_id", "units": ["a.r34"]},
        "promise.amount": {"tool": "create_promise", "field": "amount", "wire": "amount", "units": ["a.r34"]},
        "promise.date": {"tool": "create_promise", "field": "date", "wire": "date", "units": ["a.r34"]},
        "promise.ok": {"tool": "create_promise", "field": "ok", "wire": "ok", "units": ["a.r37"]},
        "callback.date": {"tool": "schedule_callback", "field": "date", "wire": "date", "units": ["a.r6"]},
        "callback.time": {"tool": "schedule_callback", "field": "time", "wire": "time", "units": ["a.r6"]},
        "transfer.queue": {"tool": "transfer_to_agent", "field": "queue", "wire": "queue", "units": ["a.r41", "a.r42", "a.r32"]},
        "close.outcome": {"tool": "close_call", "field": "outcome", "wire": "outcome", "units": ["a.r46"]},
        "close.reason": {"tool": "close_call", "field": "reason", "wire": "reason", "units": ["a.r46"]},
    }


def wire_enums_a():
    e = {
        "verify_identity.field.date_of_birth": {"obligations": ["O-a.r11"]},
        "verify_identity.field.phone_last4": {"obligations": ["O-a.r11"]},
        "verify_identity.hint.day_month_swapped": {"obligations": ["O-a.r13"]},
        "get_account.products.type.credit_card": {"obligations": ["O-a.r17", "O-a.r25"]},
        "get_account.products.type.personal_loan": {"obligations": ["O-a.r17", "O-a.r25"]},
        "get_account.products.type.car_loan": {"obligations": ["O-a.r17", "O-a.r25"]},
        "transfer_to_agent.queue.restructuring": {"obligations": ["O-a.r41"]},
        "transfer_to_agent.queue.general": {"obligations": ["O-a.r42"]},
        "transfer_to_agent.queue.support": {"obligations": ["O-a.r32"]},
        "close_call.outcome.promise": {"obligations": ["O-a.r46.row.promise"]},
        "close_call.outcome.paid": {"obligations": ["O-a.r39"]},
        "close_call.outcome.transferred": {"obligations": ["O-a.r41", "O-a.r42", "O-a.r32", "O-a.r46.transfer"]},
        "close_call.outcome.no_promise": {"obligations": ["O-a.r31", "O-a.r45", "O-a.r32", "O-a.r40", "O-a.r37"]},
        "close_call.outcome.not_verified": {"obligations": ["O-a.r14", "O-a.r15", "O-a.r45"]},
        "close_call.outcome.not_reached": {"obligations": ["O-a.r6", "O-a.r7", "O-a.r8", "O-a.r9", "O-a.r3"]},
        "add_note.reason.refused": {"unused": "Brief A never uses add_note (a.p10)"},
        "add_note.reason.hardship": {"unused": "Brief A never uses add_note (a.p10)"},
        "add_note.reason.dispute": {"unused": "Brief A never uses add_note (a.p10)"},
        "add_note.reason.paid": {"unused": "Brief A never uses add_note (a.p10)"},
        "add_note.reason.service_error": {"unused": "Brief A never uses add_note (a.p10)"},
    }
    return e


# ----------------------------------------------------------------------------------------------
# Brief B additions
# ----------------------------------------------------------------------------------------------
def obligations_b():
    O = []
    O.append(ob("O-b.r1", ["b.r1"], "`get_account` returns one to three products. Each has its own `past_due`, `days_late` and floor.",
                "verified", [{"other": "items = get_account products, up to three, each with its own past_due, days_late and floor"}], kind="definition", stage_id="fetch"))
    O.append(ob("O-b.r2", ["b.r2"], "State every late product, one sentence each, before asking for anything.",
                "disclosure", [{"say": {"content": "one sentence per late product: product in words, past-due amount, days late"}}], kind="ordering", scope="product", stage_id="disclose",
                precedence=["before O-b.r4"]))
    O.append(ob("O-b.r3", ["b.r3"], "The band and the deadline are per product, from that product's `days_late`. Two products of the same customer can have different deadlines.",
                "negotiation", [{"other": "band and deadline evaluated per item"}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-b.r4", ["b.r4"], "First ask whether the customer can pay all of them today. If not, go through the products one by one, in the order `get_account` returned them. Do not ask about today again for each product. Start each product at attempt 1 of Brief A rule 30.",
                "negotiation", [{"ask": {"question_id": "pay_today", "content": "Can you pay all of them today?"}}, {"other": "then one product at a time in get_account order; pay-today asked once per call; attempts start at 1 per product"}],
                kind="ordering", stage_id="negotiate", notes="replaces the per-product form of O-a.r28"))
    O.append(ob("O-b.r5", ["b.r5"], "Persuasion attempts are counted per product.",
                "negotiation", [{"count": {"counter": "item.attempts_used", "max": 2}}], kind="definition", scope="product", stage_id="negotiate"))
    O.append(ob("O-b.r6", ["b.r6"], "If the customer names one date for everything and it is after one product's deadline, record that product on its own deadline and say so in the read-back. The other products keep the date the customer named.",
                "negotiation", [{"other": "a date for all items: items whose deadline is earlier are recorded on their own deadline; the read-back says so"}],
                event="date_proposal", guards=["event.item is None", "date > item.deadline"], scope="product", stage_id="negotiate", exception_of="O-a.r23"))
    O.append(ob("O-b.r7", ["b.r7"], "Read all promises back together and ask for one confirmation. Then call `create_promise` once per product.",
                "readback", [{"say": {"content": "read all promises back together"}}, {"ask": {"question_id": "confirm", "content": "Do you confirm?"}}, {"tool": {"name": "create_promise", "args": {"product_id": "item.item_id", "amount": "item.agreed.amount", "date": "item.agreed.date"}}}],
                kind="ordering", event="confirm", stage_id="readback", notes="replaces the per-product read-back of O-a.r34"))
    O.append(ob("O-b.r8", ["b.r8"], "The customer may promise some products and refuse others. For each product without a promise call `add_note` with that `product_id` and a reason: `refused`, `hardship`, `dispute`, `paid` or `service_error`. This also applies when no product gets a promise.",
                "closing", [{"note": {"reason": "item.noted.reason", "text": "item.noted.text"}}, {"tool": {"name": "add_note", "args": {"product_id": "item.item_id", "reason": "item.noted.reason"}}}],
                scope="product", stage_id="note", guards=["not item.recorded", "not transfer.done"]))
    O.append(ob("O-b.r9", ["b.r9"], "A dispute or an \"already paid\" claim on one product does not end the call. Note it and continue with the others.",
                "negotiation", [{"note": {"reason": "dispute or paid"}}, {"other": "continue with the other items"}], scope="product", stage_id="negotiate",
                exception_of="O-a.r40", notes="also an exception of O-a.r39"))
    O.append(ob("O-b.r10", ["b.r10"], "A restructuring request still transfers the call (Brief A rule 41). Promises recorded before the request stay. Promises agreed but not yet recorded are not recorded. Close as `transferred` / `restructuring`. On any transfer (restructuring, support, human) add no notes at all, before or after it.",
                "verified", [{"transfer": {"queue": "restructuring"}}, {"defer": "agreed-but-unrecorded promises are dropped"}, {"forbid": "add_note before or after any transfer"}, {"close": {"outcome": "transferred", "reason": "restructuring"}}],
                event="plan_request", stage_id="negotiate", precedence=["before O-b.r8"]))
    O.append(ob("O-b.r11", ["b.r11"], "If one `create_promise` fails twice, keep the promises that were recorded and call `add_note` with reason `service_error` for the failed product.",
                "recording", [{"note": {"reason": "service_error"}}, {"other": "keep the recorded promises; the call continues"}], event="tool_result", scope="product", stage_id="record",
                exception_of="O-a.r37"))
    O.append(ob("O-b.close.paid", ["b.p3.s2"], "With no promise recorded: if every product is noted `paid`, close as `paid`.",
                "closing", [{"close": {"outcome": "paid", "reason": None}}], guards=["not any(item.recorded)", "all(item.noted.reason == 'paid')"], stage_id="close"))
    O.append(ob("O-b.close.first_note", ["b.p3.s3"], "Otherwise close as `no_promise` with the reason of the first product, in `get_account` order, whose note is not `paid`.",
                "closing", [{"close": {"outcome": "no_promise", "reason": "first item in order whose noted.reason != 'paid'"}}], guards=["not any(item.recorded)", "not all(item.noted.reason == 'paid')"], stage_id="close"))
    O.append(ob("O-b.close.promise", ["b.p3.s4"], "With several products, `promise` wins whenever at least one promise was recorded, except rule 10 above.",
                "closing", [{"close": {"outcome": "promise", "reason": None}}], guards=["any(item.recorded)", "not transfer.done"], stage_id="close", precedence=["after O-b.r10"]))
    return O


CLOSE_ROWS_B_EXTRA_TRIGGERS = {
    ("paid", None): ["all_items_noted_paid"],
    ("no_promise", "refused"): ["first_non_paid_note:refused"],
    ("no_promise", "hardship"): ["first_non_paid_note:hardship"],
    ("no_promise", "dispute"): ["first_non_paid_note:dispute"],
    ("no_promise", "service_error"): ["first_non_paid_note:service_error"],
}


def build_b(table_a):
    """Brief B = Brief A plus the B document; A obligations that B replaces are marked superseded."""
    text_b = BRIEF_B.read_text()
    units_b = segment("brief-b", "b", text_b)
    # sentence split of the closing paragraph of B so the three closing sentences can be cited
    p3 = next(u for u in units_b if units_b[u]["text"].startswith("The outcome table of Brief A applies."))
    body = units_b[p3]["text"]
    off = units_b[p3]["offset"]
    for k, s in enumerate(SENT_SPLIT.split(body), 1):
        so = text_b.index(s, off)
        units_b[f"{p3}.s{k}"] = {"text": s, "doc_id": "brief-b", "offset": so, "end": so + len(s), "kind": "sentence", "parent": p3, "table": None}
        off = so + len(s)
    assert p3 == "b.p3", p3
    t = json.loads(json.dumps(table_a))
    t["documents"].append({"doc_id": "brief-b", "kind": "brief", "title": "Brief B: Freya Bank, up to three products", "issue_date": None,
                           "role": "amends", "evidence_units": ["b.p2"]})
    t["units"].update(units_b)
    obs_b = obligations_b()
    superseded = {"O-a.r46.no_note": "O-b.r8", "O-a.r28": "O-b.r4", "O-a.r34": "O-b.r7"}
    for o in t["obligations"]:
        if o["id"] in superseded:
            o["status"] = "superseded"
            o["notes"] = (o.get("notes", "") + " superseded by " + superseded[o["id"]]).strip()
    t["obligations"].extend(obs_b)
    t["amendments"] = [
        {"amending_unit": "b.p2", "amended_units": ["a.p7"], "path": "obligations.O-a.r46.no_note", "old": "Brief A never uses add_note", "new": "add_note per product without a promise (O-b.r8)",
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "document", "quotes": ["Every rule of Brief A applies unless a rule below replaces it."]},
        {"amending_unit": "b.r4", "amended_units": ["a.r28"], "path": "obligations.O-a.r28", "old": "Can you make this payment today?", "new": "First ask whether the customer can pay all of them today.",
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "clause", "quotes": ["First ask whether the customer can pay all of them today."]},
        {"amending_unit": "b.r7", "amended_units": ["a.r34"], "path": "obligations.O-a.r34", "old": "read back per product and confirm", "new": "read all promises back together, one confirmation, then create_promise once per product",
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "clause", "quotes": ["Read all promises back together and ask for one confirmation."]},
        {"amending_unit": "b.r1", "amended_units": ["a.p3"], "path": "parameters.multi.max_items", "old": 1, "new": 3,
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "document", "quotes": ["`get_account` returns one to three products."]},
        {"amending_unit": "b.r9", "amended_units": ["a.r39", "a.r40"], "path": "parameters.situations.paid,dispute", "old": "close the call", "new": "note the item and continue with the others",
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "clause", "quotes": ["A dispute or an \"already paid\" claim on one product does not end the call. Note it and continue with the others."]},
        {"amending_unit": "b.r11", "amended_units": ["a.r37"], "path": "parameters.situations.service_error", "old": "close as no_promise / service_error", "new": "note service_error on the failed product; keep the recorded promises",
         "authority": "stated_supersession", "issue_date": None, "effective": None, "scope": "clause", "quotes": ["keep the promises that were recorded and call `add_note` with reason `service_error` for the failed product."]},
    ]
    P = t["parameters"]
    P["multi.max_items"] = val(3, "integer", ["`get_account` returns one to three products."], ["b.r1"], ["O-b.r1"])
    P["multi.order"] = val("get_account", "string", ["in the order `get_account` returned them"], ["b.r4"], ["O-b.r4"])
    P["multi.pay_today_once"] = val(True, "boolean", ["Do not ask about today again for each product."], ["b.r4"], ["O-b.r4"])
    P["multi.readback"] = val("together", "string", ["Read all promises back together and ask for one confirmation."], ["b.r7"], ["O-b.r7"])
    P["multi.common_date_rule"] = val("item.deadline if date > item.deadline else date", "expr",
                                      ["record that product on its own deadline and say so in the read-back. The other products keep the date the customer named."], ["b.r6"], ["O-b.r6"])
    P["notes.reasons"] = val(["refused", "hardship", "dispute", "paid", "service_error"], "list[string]",
                             ["a reason: `refused`, `hardship`, `dispute`, `paid` or `service_error`"], ["b.r8"], ["O-b.r8"])
    P["notes.on_transfer"] = val("none", "string", ["On any transfer (restructuring, support, human) add no notes at all, before or after it."], ["b.r10"], ["O-b.r10"])
    P["transfer.unrecorded_rule"] = val("drop", "string", ["Promises agreed but not yet recorded are not recorded."], ["b.r10"], ["O-b.r10"])
    sit = P["situations"]["value"]
    sit["paid"]["multi"] = {"note": "paid", "continue": True, "obligation": "O-b.r9"}
    sit["dispute"]["multi"] = {"note": "dispute", "continue": True, "obligation": "O-b.r9"}
    sit["service_error"] = {"obligation": "O-b.r11", "note": "service_error", "continue": True}
    P["situations"]["units"] += ["b.r9", "b.r11"]
    P["situations"]["obligations"] += ["O-b.r9", "O-b.r11"]
    rows = json.loads(json.dumps(CLOSE_ROWS_A))
    for r in rows:
        extra = CLOSE_ROWS_B_EXTRA_TRIGGERS.get((r["outcome"], r["reason"]))
        if extra:
            r["triggers"] = r["triggers"] + extra
            r["units"] = r["units"] + ["b.p3"]
        if r["outcome"] == "paid":
            r["obligations"].append("O-b.close.paid")
        if r["outcome"] == "no_promise":
            r["obligations"].append("O-b.close.first_note")
        if r["outcome"] == "promise":
            r["obligations"].append("O-b.close.promise")
    P["closing.rows"] = val(rows, "list[row]", ["The outcome table of Brief A applies."], P["closing.rows"]["units"] + ["b.p3"],
                            P["closing.rows"]["obligations"] + ["O-b.close.paid", "O-b.close.first_note", "O-b.close.promise"])
    P["closing.precedence_rule"] = val("transferred before promise (b.r10, b.p3.s4); with no promise: paid only if every note is paid, else no_promise with the first non-paid note",
                                       "content", ["With several products, `promise` wins whenever at least one promise was recorded, except rule 10 above."], ["b.p3"],
                                       ["O-b.close.paid", "O-b.close.first_note", "O-b.close.promise"])
    t["wire_map"]["concepts"].update({
        "note.product_id": {"tool": "add_note", "field": "product_id", "wire": "product_id", "units": ["b.r8"]},
        "note.reason": {"tool": "add_note", "field": "reason", "wire": "reason", "units": ["b.r8"]},
        "note.text": {"tool": "add_note", "field": "text", "wire": "text", "units": ["b.r8"]},
    })
    for reason in ["refused", "hardship", "dispute", "paid", "service_error"]:
        t["wire_map"]["enums"]["add_note.reason." + reason] = {"obligations": ["O-b.r8"] + (["O-b.r11"] if reason == "service_error" else []) + (["O-b.r9"] if reason in ("paid", "dispute") else [])}
    t["phrases"] = [p for p in t["phrases"] if p["id"] != "pay_today"] + [
        phrase("pay_today", "mandatory", "Can you pay all of them today?", False, "O-b.r4", "first question after the disclosure of every product"),
        phrase("own_deadline_note", "mandatory", "For {product} the latest date I can record is {deadline}, so that one is recorded on {deadline}.", False, "O-b.r6", "read-back when a common date is after one product's deadline"),
    ]
    t["examples"] = t["examples"] + [
        {"unit": "b.r6", "input": {"now": "2026-10-14T11:00", "date": "2026-10-28", "items": [{"days_late": 6}, {"days_late": 14}]},
         "expected": [{"date": "2026-10-28"}, {"date": "2026-10-23", "said_in_readback": True}]},
        {"unit": "b.p3", "input": {"notes": ["paid", "paid"], "recorded": []}, "expected": {"outcome": "paid", "reason": None}},
        {"unit": "b.p3", "input": {"notes": ["paid", "refused"], "recorded": []}, "expected": {"outcome": "no_promise", "reason": "refused"}},
    ]
    t["open_questions"] = t["open_questions"] + [
        {"topic": "note text", "readings": ["text is optional and omitted", "text carries the customer's words"],
         "taken": "text omitted unless the engine has a short quote; an empty text is never sent", "rule": "b.r8 names product_id and reason only"},
        {"topic": "hardship with several products", "readings": ["hardship ends the whole call", "hardship is noted per product"],
         "taken": "hardship is global: sympathy once, support offered once; if declined, every open product is noted hardship and the call closes no_promise / hardship (or the first non-paid note)", "rule": "b.r8 lists hardship as a note reason; a.r32 is a call-level rule"},
    ]
    plan = json.loads(json.dumps(plan_a()))
    for st in plan:
        if st["id"] == "fetch":
            st["obligations"].append("O-b.r1")
        if st["id"] == "disclose":
            st["obligations"].append("O-b.r2")
        if st["id"] == "negotiate":
            st["obligations"] += ["O-b.r3", "O-b.r4", "O-b.r5", "O-b.r6", "O-b.r9", "O-b.r10"]
        if st["id"] == "readback":
            st["obligations"] = [o for o in st["obligations"] if o != "O-a.r34"] + ["O-b.r7", "O-a.r35"]
            st["obligations"] = list(dict.fromkeys(st["obligations"]))
        if st["id"] == "record":
            st["obligations"].append("O-b.r11")
            st["per_item"] = True
        if st["id"] == "close":
            st["obligations"] += ["O-b.close.paid", "O-b.close.first_note", "O-b.close.promise"]
    close_i = next(i for i, st in enumerate(plan) if st["id"] == "close")
    plan.insert(close_i, {"id": "note", "type": "note", "params": {"tool": "add_note", "reasons": "notes.reasons"}, "obligations": ["O-b.r8", "O-b.r11", "O-b.r9"],
                          "units": ["b.r8"], "per_item": True, "gates": []})
    t["plan"] = plan
    return t


# ----------------------------------------------------------------------------------------------
# Assembly and checks
# ----------------------------------------------------------------------------------------------
def dispositions(units, obligations, parameters):
    cited = {}
    for o in obligations:
        for u in o["units"]:
            cited.setdefault(u, []).append(o["id"])
    param_units = set()
    for p in parameters.values():
        for u in p.get("units", []):
            param_units.add(u)
    d = {}
    for uid, u in units.items():
        if uid in cited:
            d[uid] = {"kind": "obligation", "refs": cited[uid]}
        elif uid in param_units:
            d[uid] = {"kind": "definition", "refs": [], "reason": "value carried in parameters"}
        elif u["kind"] == "heading":
            d[uid] = {"kind": "informational", "refs": [], "reason": "heading"}
        elif u["kind"] == "row" and u["table"] in ("a.t1",):
            d[uid] = {"kind": "definition", "refs": [], "reason": "call variable"}
        else:
            # a parent rule whose sentences carry the obligations, or an intro paragraph
            children = [c for c in cited if c.startswith(uid + ".")]
            if children:
                refs = sorted({r for c in children for r in cited[c]})
                d[uid] = {"kind": "obligation", "refs": refs, "reason": "cited through its sentences"}
            elif u["parent"] and u["parent"] in cited:
                d[uid] = {"kind": "obligation", "refs": cited[u["parent"]], "reason": "sentence of a cited rule"}
            else:
                d[uid] = {"kind": "informational", "refs": [], "reason": "no obligation: context or example text"}
    return d


def check_quotes(table):
    units = table["units"]
    for o in table["obligations"]:
        for u in o["units"]:
            assert u in units, (o["id"], u)
        joined = " ".join(units[u]["text"] for u in o["units"])
        assert o["quote"] in joined, (o["id"], o["quote"][:60], joined[:120])
    for pid, p in table["parameters"].items():
        for u in p.get("units", []):
            assert u in units, (pid, u)
    for ph in table["phrases"]:
        assert any(o["id"] == ph["obligation"] for o in table["obligations"]), ph["id"]
        if ph["exact"] and ph["kind"] == "mandatory":
            ob_ = next(o for o in table["obligations"] if o["id"] == ph["obligation"])
            joined = " ".join(units[u]["text"] for u in ob_["units"])
            assert ph["text"] in joined, (ph["id"], ph["text"])
    for st in table["plan"]:
        for oid in st["obligations"]:
            assert any(o["id"] == oid for o in table["obligations"]), (st["id"], oid)
        for u in st["units"]:
            assert u in units, (st["id"], u)


def build_a():
    text_a = BRIEF_A.read_text()
    units = segment("brief-a", "a", text_a)
    api = json.loads(OPENAPI.read_text())
    obligations = obligations_a()
    parameters = parameters_a()
    table = {
        "schema_version": "1.0",
        "documents": [{"doc_id": "brief-a", "kind": "brief", "title": "Brief A: Freya Bank, early-stage collections, one product",
                       "issue_date": None, "role": "authoritative", "evidence_units": ["a.h1"]},
                      {"doc_id": "openapi", "kind": "tool_api", "title": api["info"]["title"], "issue_date": None,
                       "role": "informational", "evidence_units": []}],
        "units": units,
        "dispositions": dispositions(units, obligations, parameters),
        "obligations": obligations,
        "parameters": parameters,
        "amendments": [],
        "wire_map": {"tools": wire_map_from_openapi(api), "concepts": wire_concepts_a(), "enums": wire_enums_a(),
                     "server": api["servers"][0]["url"]},
        "phrases": phrases_a(),
        "examples": examples_a(),
        "open_questions": open_questions_a(),
        "plan": plan_a(),
    }
    # the schema forbids extra keys on wire_map; keep the server under tools metadata instead
    server = table["wire_map"].pop("server")
    table["wire_map"]["tools"]["_server"] = {"path": server, "method": "BASE"}
    return table


def main():
    a = build_a()
    check_quotes(a)
    b = build_b(a)
    b["dispositions"] = dispositions(b["units"], b["obligations"], b["parameters"])
    check_quotes(b)
    (OUT / "brief-a.json").write_text(json.dumps(a, indent=1, ensure_ascii=False, sort_keys=False) + "\n")
    (OUT / "brief-b.json").write_text(json.dumps(b, indent=1, ensure_ascii=False, sort_keys=False) + "\n")
    print("units a", len(a["units"]), "obligations a", len(a["obligations"]), "params a", len(a["parameters"]))
    print("units b", len(b["units"]), "obligations b", len(b["obligations"]), "params b", len(b["parameters"]))


if __name__ == "__main__":
    main()
