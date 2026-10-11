"""Call-state engine: `step(state, events, table, now) -> (new_state, outputs)`.

Pure, deterministic, standard library only. Every rule-bound decision of the call is made here from
the rule table (spec/interfaces.md sections 1 and 2): party resolution, identity questions, callback
window, bands and deadlines, offers and persuasion attempts, versioned read-back, bank writes in the
required order, situations, notes and the closing row. Nothing policy-specific is hard-coded: where the
table is silent the engine marks the capability in `outputs["unsupported"]` and takes the safest path
(ask, do not write).

Contract with the emitter
  * `outputs["writes"]` is the complete list of bank writes due *now*, in order. The emitter runs them one
    by one and feeds every result back as a `tool_result` event through `step`; after each result the
    engine recomputes the list from state, so a write is never issued twice unless the table says so
    (`recording.retries`).
  * `outputs["engine_next"]` names the node to route to: a speaking stage (`party`, `callback`,
    `identity`, `negotiate`, `readback`) or a write stage (`verify`, `fetch`, `record`, `transfer`,
    `note`, `close`) or `end` once `close_call` succeeded.
  * `mandatory_lines` are exact sentences (phrases with `exact: true`); `say_next` is content the
    dialogue model must convey in its own words; `readback_text` is the versioned read-back.
"""
import json
import re
from .calendar import (parse_now, parse_date, iso, calendar_from_table, is_business_day,
                       eval_expr, ExprError, EvalError, CalendarError)
from .dates import (resolve_date, resolve_time, resolve_amount_cents, to_cents, cents_to_number, money_text, amount_words,
                    parse_identity_date, parse_digits, parse_year, parse_code, format_date_words, _weekday_mode)

SPEAKING_STAGES = ("party", "callback", "identity", "negotiate", "readback")
DEBUG_RAISE = False   # tests may set this to see the traceback instead of the never-raise fallback
WRITE_STAGES = ("verify", "fetch", "record", "transfer", "note", "close")
# triggers that end the call before verification or after a callback was booked
TERMINAL_TRIGGERS = ("party_unclear_twice", "wrong_number", "deceased", "callback_booked", "callback_refused_twice",
                     "identity_failed", "identity_declined", "dont_want_twice_unverified", "fetch_failed_twice")
EVENT_KINDS = set([
    "party_confirmed", "party_other", "party_wrong_number", "party_deceased", "id_answer", "id_decline",
    "question_back", "callback_offer", "pay_today_yes", "pay_today_no", "date_proposal", "amount_proposal",
    "too_much", "refuse", "accept_offer", "vague_period", "confirm", "deny", "change", "paid", "dispute",
    "plan_request", "human", "hardship", "complaint", "scam_question", "robot_question", "dont_want_to_talk", "other",
    "tool_result"])

# Wording used only when the table carries no phrase for an obligation it does state.
FALLBACK_TEXT = {
    "opening": "Say you are a digital assistant calling from the bank and that the call is recorded.",
    "hardship_open": "Say that is understood; ask whether there is anything the customer would like to arrange today. Propose no amount and no date.",
    "party_question": "Ask whether you are speaking with {title} {last_name}.",
    "robot_answer": "Say that you are the bank's digital assistant.",
    "callback_question": "Ask when {title} {last_name} can be reached.",
    "sorry_loss": "Express condolences.",
    "questions_protect": "Explain once that the security questions protect the account.",
    "use_app_or_branch": "Say the identity could not be verified and the customer should use the mobile app or a branch.",
    "disclosure": "Say you are calling from the collections team about a late payment.",
    "pay_today": "Ask whether the customer can make this payment today.",
    "rest_overdue": "Say that the rest stays overdue.",
    "below_floor": "Say that an amount below the minimum cannot be recorded.",
    "latest_is_deadline": "Say that the latest date you can record is {deadline}.",
    "do_you_confirm": "Ask: do you confirm?",
    # no "text_message" fallback: a confirmation sentence exists only when the table has one (a brief that withdraws it
    # without replacement must hear none, synthetic J-01 2026-10-11)
    "promise_recorded": "Say the promise is recorded.",
    "could_not_record": "Say you could not record the promise because of a technical problem.",
    "change_in_app": "Say a recorded promise cannot be changed in this call; it can be changed in the mobile app.",
    "paid_takes_day": "Say that payments can take one business day to appear.",
    "sympathy": "Say one short sentence of sympathy.",
    "support_offer": "Offer to connect the customer with the customer support team.",
    "can_i_help": "Ask once whether you can help first.",
    "scam_answer": "Say the customer can verify the call by phoning the bank's customer service number.",
    "no_information": "Say you do not have that information.",
    "thanks_goodbye": "Thank the customer and say goodbye.",
    "month_as_word": "Ask the customer to say the date of birth again with the month as a word.",
    "own_deadline_note": "For {product} the latest date that can be recorded is {deadline}, so it is recorded on {deadline}.",
    "request_noted": "Acknowledge that the customer's request has been noted.",
}


# ---------------------------------------------------------------------------------------------
# state


def new_state(call=None):
    """A fresh call state. `call` carries the call variables (title, last_name, first_name, customer_id)."""
    return {
        "rev": 0, "stage": "party", "party": "unknown", "call": dict(call or {}),
        "opened": False, "party_asks": 1, "pending": "party",
        "identity": {"q_index": 0, "wrong": 0, "hinted": False, "partials": {}, "passed": [], "state": "pending",
                     "declines": 0, "retried": 0},
        "callback": {"date": None, "time": None, "invalid": 0},
        "items": [], "current_item": 0, "pay_today_asked": False, "readback_version": 0,
        "global": {"hardship": False, "support_offered": False, "hardship_open": False, "human_asked_once": False, "dont_want": 0,
                   "pending_transfer": None, "transfer_done": None, "transfer_failures": 0, "paid_claim": False,
                   "dispute": False, "turns": 0, "pending_lines": [], "fetch_failures": 0, "close_failures": 0,
                   "resume_pending": None, "triggers": []},
        "commits": [], "close": None, "closed": False, "unsupported": [],
    }


def _copy(x):
    return json.loads(json.dumps(x))


# ---------------------------------------------------------------------------------------------
# table access


def _param(C, path):
    """Value of a parameter or None when absent or not_specified (then recorded as unsupported)."""
    entry = C["params"].get(path)
    if not isinstance(entry, dict) or entry.get("confidence") == "not_specified" or "value" not in entry:
        if path not in C["missing"]:
            C["missing"].append(path)
        return None
    return entry.get("value")


def _has_param(C, path):
    entry = C["params"].get(path)
    return isinstance(entry, dict) and entry.get("confidence") != "not_specified" and "value" in entry


def _unsupported(C, st, what):
    if what not in st["unsupported"]:
        st["unsupported"].append(what)


def _fill(text, fmt):
    for k, v in fmt.items():
        text = text.replace("{" + k + "}", "" if v is None else str(v))
    return text


def _phrase(C, pid):
    return C["phrases"].get(pid)


def _say(C, st, pid):
    """Speak a table phrase: exact ones go to mandatory_lines, content ones to say_next."""
    fmt = dict(st.get("call") or {})
    fmt.update(C.get("fmt") or {})
    ph = _phrase(C, pid)
    if ph is None:
        text = FALLBACK_TEXT.get(pid)
        if text is None:
            return
        C["lines"].append(_fill(text, fmt))
        return
    text = _fill(ph.get("text") or "", fmt)
    if ph.get("exact"):
        if text not in C["mandatory"]:
            C["mandatory"].append(text)
    else:
        if text not in C["lines"]:
            C["lines"].append(text)


def _line(C, text):
    if text and text not in C["lines"]:
        C["lines"].append(text)


def _trigger(C, st, name):
    if name not in st["global"]["triggers"]:
        st["global"]["triggers"].append(name)


# ---------------------------------------------------------------------------------------------
# context


def _context(table, now):
    table = table or {}
    params = table.get("parameters") or {}
    cal, missing_cal = calendar_from_table(table)
    phrases = {}
    for ph in table.get("phrases") or []:
        if isinstance(ph, dict) and ph.get("kind") == "mandatory" and ph.get("id"):
            phrases[ph["id"]] = ph
    try:
        clock = parse_now(now)
    except (ValueError, TypeError, AttributeError):
        clock = None
    C = {"table": table, "params": params, "phrases": phrases, "cal": cal, "now": clock,
         "missing": list(missing_cal), "lines": [], "mandatory": [], "understood": False, "fmt": {},
         "calendar_ok": "calendar.holidays" not in missing_cal and clock is not None}
    C["today"] = clock.date() if clock is not None else None
    if clock is None:
        C["missing"].append("call.now")
    rules = {}
    tn = _param(C, "dates.this_next_rule") if _has_param(C, "dates.this_next_rule") else None
    if isinstance(tn, dict):
        # the reader writes the rule as a small expression ("next_weekday(w)", or "this_weekday(w) if this_weekday(w) >
        # today else next_weekday(w)" for "the first such weekday after today"); the resolver knows the modes
        rules["this"] = _weekday_mode(tn.get("this"), "current_week")
        rules["next"] = _weekday_mode(tn.get("next"), "following_week")
    else:
        rules["this_next_unspecified"] = True
    bw = _param(C, "dates.bare_weekday_rule") if _has_param(C, "dates.bare_weekday_rule") else None
    if isinstance(bw, str):
        rules["bare_weekday"] = bw
    elif isinstance(bw, dict) and bw.get("rule"):
        rules["bare_weekday"] = bw["rule"]
    else:
        rules["bare_weekday_unspecified"] = True
    C["rules"] = rules
    C["notes_mode"] = bool(_has_param(C, "notes.reasons"))
    sits = _param(C, "situations") if _has_param(C, "situations") else None
    C["situations"] = sits if isinstance(sits, dict) else {}
    # flags read from the whole table (obligations, units, phrases). The engine node on the platform carries only the
    # parameters and the mandatory phrases (snippet.engine_table), so the emitter computes them once and embeds them
    # as table["derived"]; offline the full table is at hand and they are computed here (synthetic C-01, 2026-10-11:
    # the amounts-in-words flag was lost on the platform)
    derived = table.get("derived") if isinstance(table.get("derived"), dict) else derive_table_flags(table, C)
    C["currency"] = derived.get("currency") or ""
    C["amount_words"] = bool(derived.get("amount_words"))
    C["hardship_continues"] = bool(derived.get("hardship_continues"))
    C["hardship_when"] = derived.get("hardship_when") if isinstance(derived.get("hardship_when"), dict) else dict()
    return C


def derive_table_flags(table, C=None):
    """The table-wide flags the engine needs at run time, computed from the full table: the currency word, whether
    amounts are spoken in words, whether the call continues after a declined hardship transfer, and the hardship
    obligation's `when`. Embedded by snippet.engine_table as table["derived"]."""
    if C is None:
        C = {"table": table, "params": table.get("parameters") or dict(), "missing": [], "phrases": dict()}
        for ph in table.get("phrases") or []:
            if isinstance(ph, dict) and ph.get("id"):
                C["phrases"][ph["id"]] = ph
        sits = _param(C, "situations") if _has_param(C, "situations") else None
        C["situations"] = sits if isinstance(sits, dict) else {}
    cur_note = _param(C, "amounts.currency") if _has_param(C, "amounts.currency") else None
    currency = _currency_word(cur_note)
    words_text = _amount_words_text(C, cur_note)
    if words_text and not currency:
        currency = _currency_word(words_text)
    hs = C["situations"].get("hardship") if isinstance(C["situations"].get("hardship"), dict) else None
    when = dict()
    for o in table.get("obligations") or []:
        if hs and o.get("id") == hs.get("obligation") and o.get("status") == "effective":
            when = o.get("when") or dict()
    return {"currency": currency, "amount_words": bool(words_text), "hardship_continues": bool(hs) and _hardship_continues(C, hs),
            "hardship_when": when}


def _expr_ctx(C, st, item=None):
    call = st.get("call") or dict()
    ctx = {"now": C["now"], "cal": C["cal"], "rules": C["rules"], "customer": call, "call": call}
    if item is not None:
        ctx["product"] = item.get("product") or {}
        ctx["item"] = item
        ctx["deadline"] = item.get("deadline")
        ctx["floor"] = cents_to_number(item["floor"]) if item.get("floor") is not None else None
    return ctx


def _eval(C, st, text, item=None):
    """Evaluate a table expression; None (and an unsupported mark) when it cannot be evaluated."""
    try:
        return eval_expr(text, _expr_ctx(C, st, item))
    except (ExprError, EvalError, CalendarError, ValueError, TypeError, KeyError):
        _unsupported(C, st, "expression:" + str(text))
        return None


# ---------------------------------------------------------------------------------------------
# items


def _product_label(p):
    t = str(p.get("type") or "product").replace("_", " ")
    if p.get("card_last4"):
        return t + " ending " + str(p.get("card_last4"))
    return t


def _build_items(C, st, products):
    bands = _param(C, "bands") or []
    floor_expr = _param(C, "amounts.floor_expr")
    max_items = _param(C, "multi.max_items") if _has_param(C, "multi.max_items") else None
    items = []
    for n, p in enumerate(products or []):
        if not isinstance(p, dict):
            continue
        pid = p.get("product_id") or ("p%d" % (n + 1))
        item = {"item_id": pid, "type": p.get("type"), "label": _product_label(p), "product": p,
                "past_due": to_cents(p.get("past_due")), "floor": None, "days_late": p.get("days_late"),
                "band": None, "deadline": None, "attempts_allowed": 0, "attempts_used": 0, "offers_made": [],
                "floor_offered": False, "too_much": False, "agreed": None, "readback_version": 0,
                "confirmed_version": 0, "recorded": False, "record_failures": 0, "noted": None, "status": "open",
                "vague_asked": False, "offer": None, "refused": [], "basis": to_cents(p.get("past_due")),
                "proposed_amount": None, "proposed_date": None, "confirmed": False, "own_deadline": False,
                "noted_written": False, "note_failures": 0, "exhausted": False}
        if floor_expr:
            f = _eval(C, st, floor_expr, item)
            item["floor"] = to_cents(f) if f is not None else None
        for b in bands:
            ok = _eval(C, st, b.get("condition", "false"), item)
            if ok:
                item["band"] = b.get("id")
                d = _eval(C, st, b.get("deadline_expr", ""), item)
                item["deadline"] = iso(d) if d is not None else None
                item["attempts_allowed"] = int(b.get("attempts") or 0)
                break
        if item["band"] is None:
            _unsupported(C, st, "bands:no band for days_late " + str(p.get("days_late")))
        if item["floor"] is None:
            _unsupported(C, st, "amounts.floor_expr")
        items.append(item)
    if isinstance(max_items, int) and len(items) > max_items:
        _unsupported(C, st, "multi.max_items exceeded (%d > %d)" % (len(items), max_items))
        items = items[:max_items]
    st["items"] = items
    st["current_item"] = 0


def _item_by_id(st, pid):
    for i, it in enumerate(st["items"]):
        if it["item_id"] == pid:
            return i, it
    return None, None


def _open_items(st):
    return [it for it in st["items"] if it["status"] == "open"]


def _agreed_items(st):
    return [it for it in st["items"] if it["status"] == "agreed"]


def _current(st):
    if not st["items"]:
        return None
    idx = st.get("current_item") or 0
    if 0 <= idx < len(st["items"]) and st["items"][idx]["status"] == "open":
        return st["items"][idx]
    for i, it in enumerate(st["items"]):
        if it["status"] == "open":
            st["current_item"] = i
            return it
    return None


def _target_items(st, ev):
    """The items an item-scoped event applies to: the named item, else all open items."""
    pid = ev.get("item")
    if pid:
        _, it = _item_by_id(st, pid)
        return [it] if it is not None else []
    return _open_items(st)


# ---------------------------------------------------------------------------------------------
# money and dates


def _amount_of(ev):
    if ev.get("amount") is not None:
        try:
            return to_cents(ev.get("amount"))
        except (TypeError, ValueError):
            return None
    for key in ("span", "text"):
        if ev.get(key):
            c = resolve_amount_cents(ev.get(key))
            if c is not None:
                return c
    return None


def _date_of(C, st, ev):
    """resolve_date on the event's date text; None when the event carries no date text."""
    text = ev.get("date_text") or ev.get("span") or ev.get("text")
    if not text or C["now"] is None:
        return None
    return resolve_date(text, C["now"], C["rules"])


def _check_amount(item, cents):
    if item["floor"] is None or item["past_due"] is None:
        return "unknown"
    if cents < item["floor"]:
        return "below"
    if cents > item["past_due"]:
        return "above"
    return "ok"


def _check_date(C, st, item, d):
    """Rules 19, 20, 23 as table parameters: returns (verdict, date)."""
    d = parse_date(d)
    if C["today"] is None:
        _unsupported(C, st, "call.now")
        return "unknown", iso(d)
    if d < C["today"]:
        return "past", iso(d)
    if not C["calendar_ok"]:
        _unsupported(C, st, "calendar.holidays")
        return "unknown", iso(d)
    if item.get("deadline") is None:
        _unsupported(C, st, "bands.deadline")
        return "unknown", iso(d)
    dl = parse_date(item["deadline"])
    if d > dl:
        return "after_deadline", iso(dl)
    if not is_business_day(d, C["cal"]):
        rule = _param(C, "dates.non_business_rule") if _has_param(C, "dates.non_business_rule") else None
        nb = None
        if rule:
            ctx = _expr_ctx(C, st, item)
            ctx["date"] = d
            try:
                nb = eval_expr(rule, ctx)
            except (ExprError, EvalError, CalendarError, ValueError, TypeError):
                nb = None
        if nb is None:
            _unsupported(C, st, "dates.non_business_rule")
            return "unknown", iso(d)
        nb = parse_date(nb)
        if nb > dl:
            return "after_deadline", iso(dl)
        return "non_business", iso(nb)
    return "ok", iso(d)


CURRENCY_BASES = ("pound", "euro", "dollar", "franc", "krona", "krone", "zloty", "forint", "koruna", "lira", "rupee", "peso",
                  "real", "dirham", "riyal", "shekel", "ringgit", "rupiah", "naira", "shilling", "cedi")
CURRENCY_PLAIN = ("yen", "yuan", "won", "rand", "baht", "lei", "kronor", "kroner", "reais")


def _currency_word(value):
    """The word for the brief's currency from its amounts.currency note ("<currency> sterling, spoken in words" -> the
    currency word)."""
    if not isinstance(value, str) or not value.strip():
        return ""
    low = value.lower()
    for base in CURRENCY_BASES:
        if re.search(r"\b" + base + r"s?\b", low):
            return base + "s"
    for w in CURRENCY_PLAIN:
        if re.search(r"\b" + w + r"\b", low):
            return w
    m = re.match(r"\s*([A-Za-z]+)", value)
    return m.group(1).lower() if m else ""


AMOUNT_WORDS_RE = re.compile(r"\b(amounts?|currency|euros?|pounds?|dollars?|sterling)\b(?:(?!product)[^.;]){0,60}\b(in|into) words", re.I)


def _amount_words_text(C, cur_note):
    """The table text that asks for amounts in words (synthetic C, D, F, G, H, J 2026-10-11), or ''."""
    if isinstance(cur_note, str) and AMOUNT_WORDS_RE.search(cur_note):
        return cur_note
    for o in (C.get("table") or {}).get("obligations") or []:
        for step in o.get("then") or []:
            for v in (step.values() if isinstance(step, dict) else []):
                txt = v.get("content") if isinstance(v, dict) else v
                if isinstance(txt, str) and AMOUNT_WORDS_RE.search(txt):
                    return txt
    for ph in (C.get("phrases") or {}).values():
        txt = " ".join(str(ph.get(k) or "") for k in ("text", "when", "id"))
        if "amount" in txt.lower() and AMOUNT_WORDS_RE.search(txt):
            return txt
    return ""


def _money(cents, C=None):
    """An amount for the model's lines, with the brief's currency word when the table names one (the model said
    a currency of its own when none was given, synthetic G-01 2026-10-11); in words when the brief wants amounts
    spoken in words (synthetic C-01: "1240 euros" was said as digits)."""
    if cents is None:
        return "?"
    cur = (C or {}).get("currency") if isinstance(C, dict) else ""
    if isinstance(C, dict) and C.get("amount_words"):
        return amount_words(cents, cur)
    text = money_text(cents)
    return text + " " + cur if cur else text


def _date_words(d):
    try:
        return format_date_words(d)
    except (ValueError, TypeError):
        return str(d)


# ---------------------------------------------------------------------------------------------
# negotiation primitives


def _amount_in_play(item):
    if item.get("offer"):
        return item["offer"]["amount"]
    if item.get("proposed_amount") is not None:
        return item["proposed_amount"]
    return item.get("basis") if item.get("basis") is not None else item.get("past_due")


def _date_in_play(C, st, item):
    """The date under discussion for the item: the pending offer's, a kept one, or today while pay-today is open."""
    if item.get("offer") and item["offer"].get("date"):
        return item["offer"]["date"]
    if item.get("proposed_date"):
        return item["proposed_date"]
    if (st.get("pending") == "pay_today" or C.get("pay_today_pending")) and C["today"] is not None:
        return iso(C["today"])
    return None


def _set_current(st, item):
    i, _ = _item_by_id(st, item["item_id"])
    if i is not None:
        st["current_item"] = i


def _offer(C, st, item, amount, d, kind):
    item["offer"] = {"amount": amount, "date": d, "kind": kind}
    item["offers_made"].append({"amount": cents_to_number(amount) if amount is not None else None, "date": d, "kind": kind})
    item["status"] = "open"
    _set_current(st, item)
    st["pending"] = "offer"
    # an offer made while applying this reply has not been heard yet: the same reply's "yes" or "today" cannot accept it
    # (platform EXT-068/153, 2026-10-11: "I can pay 100 today" became the floor agreed for today in one step)
    C.setdefault("offered_now", []).append(item["item_id"])
    C["understood"] = True


def _offered_now(C, item):
    return item["item_id"] in (C.get("offered_now") or [])


def _agree(C, st, item, amount, d, own_deadline=False):
    item["agreed"] = {"amount": cents_to_number(amount), "date": d}
    item["agreed_cents"] = amount
    item["offer"] = None
    item["proposed_amount"] = None
    item["proposed_date"] = None
    item["own_deadline"] = bool(own_deadline)
    item["status"] = "agreed"
    item["readback_version"] += 1
    st["pending"] = None
    st["global"]["readback_rounds"] = 0      # a new version is read back afresh
    C["agreed_calls"] = C.get("agreed_calls", 0) + 1
    C["understood"] = True


# the closing-row trigger that goes with each canonical note reason (the row's reason is often the note code too)
NOTE_TRIGGER = {"refused": "attempts_exhausted", "hardship": "hardship_support_declined", "dispute": "dispute",
                "paid": "paid_claim", "service_error": "record_failed_twice", "do_not_call": "dont_want_twice_verified"}
# a dispute said in the customer's words -> the token a brief's finer note reason tends to carry
DISPUTE_WORDS = (
    (re.compile(r"\b(closed|settled|cleared|paid (it |that |this |them )?off|finished paying)\b"), ("closed", "settled")),
    (re.compile(r"\b(not (my|mine|our|his|hers)|isn'?t mine|is not mine|never (had|took|opened|signed|applied)|don'?t have|"
                r"do not have|not me|fraud|identity theft)\b"), ("mine", "theirs", "fraud", "unknown", "owner")),
    (re.compile(r"\b(wrong|incorrect|too (much|high)|mistake|error|overcharg\w*|charges?|figure|balance|amount)\b"),
     ("wrong", "amount", "incorrect", "balance", "figure")),
)


def _wire_reason(C, st, canonical, text=None):
    """The table's value for a note reason the engine knows by its canonical name ("hardship" -> the code list's own
    abbreviation; synthetic G-06/H-05, 2026-10-11): the value itself when listed; a finer reason chosen by the
    customer's words (a dispute as not theirs, closed long ago or a wrong amount); the situation's note; the closing
    row of the same trigger; a listed name that abbreviates the canonical one. The canonical name when the table lists
    no reasons or nothing fits (then marked unsupported)."""
    reasons = _param(C, "notes.reasons") if _has_param(C, "notes.reasons") else None
    if not isinstance(reasons, list) or not reasons:
        return canonical
    reasons = [str(r) for r in reasons if isinstance(r, str) and r]
    if canonical == "dispute" and text:
        low = str(text).lower().replace("\u2019", "'")
        for rx, toks in DISPUTE_WORDS:
            if rx.search(low):
                hits = [r for r in reasons if any(tok in r.lower() for tok in toks)]
                if hits:
                    return hits[0]
    if canonical in reasons:
        return canonical
    s = _sit(C, canonical) or {}
    multi = s.get("multi") if isinstance(s.get("multi"), dict) else {}
    for v in (s.get("note"), multi.get("note")):
        if isinstance(v, str) and v in reasons:
            return v
    dc = s.get("decline_close")
    if isinstance(dc, list) and len(dc) > 1 and isinstance(dc[1], str) and dc[1] in reasons:
        return dc[1]
    trig = NOTE_TRIGGER.get(canonical)
    rows = _param(C, "closing.rows") if _has_param(C, "closing.rows") else None
    for row in rows if isinstance(rows, list) else []:
        if trig and isinstance(row, dict) and trig in (row.get("triggers") or []) and isinstance(row.get("reason"), str) \
                and row["reason"] in reasons:
            return row["reason"]
    toks = [t for t in canonical.lower().split("_") if t]
    initials = "".join(t[0] for t in toks)
    cands = []
    for r in reasons:
        rl = r.lower()
        if rl == initials or canonical.lower().startswith(rl) or rl.startswith(canonical.lower()) \
                or any((t.startswith(rl) or rl.startswith(t)) for t in toks if len(t) > 2 and len(rl) > 2):
            cands.append(r)
    if len(cands) == 1:
        return cands[0]
    _unsupported(C, st, "notes.reasons:no value for " + canonical)
    return canonical


def _note_item(C, st, item, reason, text=None):
    item["status"] = "noted"
    wire = _wire_reason(C, st, reason, text) if C["notes_mode"] else reason
    item["noted"] = {"reason": wire, "canonical": reason, "text": None}
    item["offer"] = None
    item["agreed"] = None
    st["pending"] = None
    C["understood"] = True


def _exhaust(C, st, item):
    """Attempts used up (or none allowed): the item is refused; after a hardship, where no attempt may be made, a product
    without a promise is a hardship note, not a refusal."""
    item["exhausted"] = True
    item["offer"] = None
    hardship = bool(st["global"]["hardship"]) and _sit(C, "hardship") is not None
    _note_item(C, st, item, "hardship" if hardship else "refused")
    if not C["notes_mode"]:
        _trigger(C, st, "hardship_support_declined" if hardship else "attempts_exhausted")


def _attempt(C, st, item):
    """Make the next persuasion attempt for the item, or exhaust it."""
    if st["global"]["hardship"]:
        _exhaust(C, st, item)
        return
    attempts = _param(C, "attempts") or []
    n = item["attempts_used"] + 1
    if n > item["attempts_allowed"]:
        _exhaust(C, st, item)
        return
    rule = None
    for a in attempts:
        if int(a.get("n") or 0) == n and (a.get("band") in (None, "any", item.get("band"))):
            rule = a
            break
    if rule is None:
        _exhaust(C, st, item)
        return
    item["attempts_used"] = n
    amount = _amount_rule(C, st, item, rule.get("amount_rule"))
    d = _eval(C, st, rule.get("date_expr"), item)
    if amount is None or d is None:
        _unsupported(C, st, "attempts[%d]" % n)
        _exhaust(C, st, item)
        return
    d = iso(d)
    if [cents_to_number(amount), d] in item["refused"]:
        _attempt(C, st, item)
        return
    _offer(C, st, item, amount, d, "attempt")


def _amount_rule(C, st, item, rule):
    if rule in (None, "", "same"):
        return _amount_in_play(item)
    if rule == "floor":
        return item.get("floor")
    v = _eval(C, st, rule, item)
    return to_cents(v) if v is not None else None


def _refuse(C, st, item):
    """A flat refusal or non-answer on the item: the pending offer is refused and the next attempt follows."""
    C["understood"] = True
    if item.get("offer"):
        item["refused"].append([cents_to_number(item["offer"]["amount"]), item["offer"]["date"]])
        item["offer"] = None
    _attempt(C, st, item)


def _today_event(C):
    """A resolved-date dict for today, or None when the call has no clock."""
    if C["today"] is None:
        return None
    return {"kind": "exact", "date": iso(C["today"]), "how": "today"}


def _apply_date(C, st, item, amount, resolved, common=False):
    """A date the customer named for the item (resolved by resolve_date) with the amount in play."""
    C["understood"] = True
    _set_current(st, item)
    if resolved is None and C["today"] is None:
        _unsupported(C, st, "call.now")
        item["proposed_amount"] = amount
        st["pending"] = "which_date"
        return
    if resolved is None or resolved.get("kind") == "none":
        _vague(C, st, item, amount)
        return
    if resolved.get("kind") == "vague":
        _vague(C, st, item, amount)
        return
    if resolved.get("how") == "bare_weekday" and C["rules"].get("bare_weekday_unspecified"):
        _unsupported(C, st, "dates.bare_weekday_rule")
        item["proposed_amount"] = amount
        st["pending"] = "which_date"
        return
    if resolved.get("how") in ("this_weekday", "next_weekday") and C["rules"].get("this_next_unspecified"):
        _unsupported(C, st, "dates.this_next_rule")
        item["proposed_amount"] = amount
        st["pending"] = "which_date"
        return
    verdict, d = _check_date(C, st, item, resolved["date"])
    if verdict == "past":
        item["proposed_amount"] = amount
        st["pending"] = "past_date"
        return
    if verdict == "unknown":
        item["proposed_amount"] = amount
        st["pending"] = "which_date"
        return
    if verdict == "after_deadline":
        if common and _has_param(C, "multi.common_date_rule"):
            _agree(C, st, item, amount, d, own_deadline=True)
            return
        rule = _param(C, "dates.after_deadline_rule") if _has_param(C, "dates.after_deadline_rule") else None
        if rule is None:
            _unsupported(C, st, "dates.after_deadline_rule")
            item["proposed_amount"] = amount
            st["pending"] = "which_date"
            return
        dd = _eval(C, st, rule, item)
        dd = iso(dd) if dd is not None else d
        C["fmt"]["deadline"] = _date_words(dd)
        _say(C, st, "latest_is_deadline")
        _offer(C, st, item, amount, dd, "deadline")
        return
    if verdict == "non_business":
        _offer(C, st, item, amount, d, "next_business")
        return
    _agree(C, st, item, amount, d)


def _vague(C, st, item, amount):
    rule = _param(C, "dates.vague_rule") if _has_param(C, "dates.vague_rule") else None
    if rule is None:
        _unsupported(C, st, "dates.vague_rule")
        st["pending"] = "which_date"
        return
    if rule.get("ask_once", True) and not item["vague_asked"]:
        item["vague_asked"] = True
        item["proposed_amount"] = amount
        _set_current(st, item)
        st["pending"] = "exact_day"
        return
    then = rule.get("then")
    d = _eval(C, st, then, item) if then else None
    if d is None:
        _unsupported(C, st, "dates.vague_rule.then")
        st["pending"] = "which_date"
        return
    _offer(C, st, item, amount, iso(d), "deadline")


def _floor_offer(C, st, item, d, after_too_much, below_cents=None):
    """Offer the floor once (rules 26 and 27); a second time counts as not accepting it."""
    if item["floor"] is None:
        _unsupported(C, st, "amounts.floor_expr")
        st["pending"] = "which_amount"
        return
    if item["floor_offered"]:
        _refuse(C, st, item)
        return
    item["floor_offered"] = True
    if after_too_much:
        _say(C, st, "rest_overdue")
    else:
        if below_cents is not None:
            # the customer's own figure is named: "it cannot be recorded" left the model guessing what "it" was
            # (platform EXT-068/102/153, 2026-10-11)
            _line(C, "Say that %s cannot be recorded because it is below the minimum." % _money(below_cents, C))
        ph = _phrase(C, "below_floor")
        if below_cents is None or (ph is not None and ph.get("exact")):
            _say(C, st, "below_floor")
    _offer(C, st, item, item["floor"], d, "floor")




def _handle_amount(C, st, item, ev, cents, resolved_date):
    C["understood"] = True
    _set_current(st, item)
    verdict = _check_amount(item, cents)
    date_in_play = resolved_date["date"] if (resolved_date and resolved_date.get("kind") == "exact") else None
    if verdict == "below":
        d = None
        if date_in_play is not None:
            v, dd = _check_date(C, st, item, date_in_play)
            if v in ("ok", "non_business"):
                d = dd
            elif v == "after_deadline":
                # the customer's own day is after the deadline too: the minimum goes on the deadline, which is named
                # (synthetic G-06, 2026-10-11: a low figure for next Tuesday -> the minimum on the Friday deadline, not today)
                rule = _param(C, "dates.after_deadline_rule") if _has_param(C, "dates.after_deadline_rule") else None
                dl = _eval(C, st, rule, item) if rule else None
                d = iso(dl) if dl is not None else dd
                C["fmt"]["deadline"] = _date_words(d)
                _say(C, st, "latest_is_deadline")
        _floor_offer(C, st, item, d or _date_in_play(C, st, item), after_too_much=False, below_cents=cents)
        return
    if verdict == "above":
        _unsupported(C, st, "amounts.range_rule:above_full")
        _line(C, "The past-due amount is " + _money(item["past_due"], C) + "; only the full past-due amount can be recorded at most.")
        _offer(C, st, item, item["past_due"], date_in_play or _date_in_play(C, st, item), "full")
        return
    if verdict == "unknown":
        _unsupported(C, st, "amounts.range_rule")
        st["pending"] = "which_amount"
        return
    item["basis"] = cents
    item["offer"] = None
    if resolved_date is not None:
        _apply_date(C, st, item, cents, resolved_date)
        return
    d = _date_in_play(C, st, item)
    if d:
        _apply_date(C, st, item, cents, {"kind": "exact", "date": d, "how": "in_play"})
        return
    item["proposed_amount"] = cents
    st["pending"] = "which_date"


def _accept(C, st, item, ev):
    C["understood"] = True
    resolved = _date_of(C, st, ev) if (ev.get("date_text") or ev.get("span")) else None
    cents = _amount_of(ev) if ev.get("amount") is not None else None
    if item.get("offer"):
        off = item["offer"]
        amount = cents if cents is not None else off["amount"]
        if resolved is not None and resolved.get("kind") != "none":
            item["offer"] = None
            _apply_date(C, st, item, amount, resolved)
            return
        if off.get("date") == "today":
            off["date"] = iso(C["today"])
        if off.get("date"):
            _agree(C, st, item, amount, off["date"])
            return
        item["offer"] = None
        item["proposed_amount"] = amount
        _set_current(st, item)
        st["pending"] = "which_date"
        return
    if st.get("pending") in ("which_date", "exact_day", "past_date") and resolved is not None:
        _apply_date(C, st, item, _amount_in_play(item), resolved)
        return
    if st.get("pending") == "pay_today":
        _apply_date(C, st, item, _amount_in_play(item), _today_event(C))
        return
    C["understood"] = False


# ---------------------------------------------------------------------------------------------
# situations


def _sit(C, key):
    s = C["situations"].get(key)
    return s if isinstance(s, dict) else None




def _handle_hardship(C, st, ev, bundle):
    s = _sit(C, "hardship")
    if s is None:
        _unsupported(C, st, "situations.hardship")
        return
    C["understood"] = True
    if not st["global"]["hardship"]:
        _say(C, st, "sympathy")
    st["global"]["hardship"] = True
    # "offer": "none" or an explicit null means the transfer follows at once, without asking (synthetic H-06, 2026-10-11)
    no_offer = s.get("offer") == "none" or ("offer" in s and s.get("offer") in (None, "", False))
    if no_offer and s.get("transfer_queue"):
        when = C.get("hardship_when") or dict()
        if st["identity"]["state"] == "verified" or (when.get("state") == "any" and not when.get("guards")
                                                    and not when.get("stage_id")):
            _request_transfer(C, st, s["transfer_queue"], "hardship")
        return
    if st["identity"]["state"] != "verified":
        return
    if s.get("transfer_queue") and not st["global"]["support_offered"]:
        st["global"]["support_offered"] = True
        st["global"]["resume_pending"] = st.get("pending")
        _say(C, st, "support_offer")
        _line(C, OFFER_IS_A_QUESTION)
        st["pending"] = "support_offer"
        C["question_now"] = "support_offer"


# the model announced the transfer instead of asking (platform EXT-081/093/094, 2026-10-11): the yes/no offers are questions
OFFER_IS_A_QUESTION = ("Put this as a question and wait for the answer; do not say that you are transferring or connecting "
                       "the customer, nothing happens until they answer.")


def _support_answer(C, st, accepted):
    s = _sit(C, "hardship") or {}
    C["understood"] = True
    st["pending"] = st["global"].get("resume_pending") or st.get("pending")
    if accepted:
        _request_transfer(C, st, s.get("transfer_queue"), "hardship")
        return
    # declined: no persuasion; items still open after this bundle are noted as hardship (see _advance),
    # a date or amount named in the same reply is still recorded
    st["global"]["hardship_declined"] = True
    if C.get("hardship_continues") and _open_items(st):
        # "Declined: continue without persuasion; a date or amount the customer still names is recorded" (synthetic
        # D, G, I, J): the call stays open for one more reply instead of closing on the decline (G-06, J-05 2026-10-11);
        # brief A says "If they decline, close as no_promise / hardship" and keeps closing at once
        st["global"]["hardship_open"] = True
        st["pending"] = "hardship_open"
        C["question_now"] = "hardship_open"
        _say(C, st, "hardship_open")


HARDSHIP_CONTINUES_RE = re.compile(r"declin\w*\W{0,3}(the call )?continues?\b|\bcontinues? without persuasion", re.I)


def _hardship_continues(C, s):
    """True when the brief says the call goes on after a declined hardship transfer ("Declined: continue without
    persuasion; a date or amount the customer still names is recorded", synthetic D, G, I, J). Brief A says "If they
    decline, close as no_promise / hardship": False. Read from the brief's own sentences (the table's units) and the
    hardship obligation."""
    texts = [str((s or {}).get("decline_rule") or (s or {}).get("declined") or "")]
    units = C["table"].get("units") or {}
    for u in (units.values() if isinstance(units, dict) else units):
        texts.append(str(u.get("text") or "") if isinstance(u, dict) else str(u))
    for o in C["table"].get("obligations") or []:
        if o.get("id") == (s or {}).get("obligation"):
            texts.append(str(o.get("quote") or ""))
    return any(HARDSHIP_CONTINUES_RE.search(t) for t in texts if t)


def _handle_human(C, st, ev):
    s = _sit(C, "human")
    if s is None:
        _unsupported(C, st, "situations.human")
        return
    C["understood"] = True
    if s.get("ask_first_once") and not st["global"]["human_asked_once"]:
        st["global"]["human_asked_once"] = True
        st["global"]["resume_pending"] = st.get("pending")
        _say(C, st, "can_i_help")
        _line(C, OFFER_IS_A_QUESTION)
        st["pending"] = "can_i_help"
        C["question_now"] = "can_i_help"
        return
    _request_transfer(C, st, s.get("transfer_queue"), "human")


def _request_transfer(C, st, queue, reason):
    if not queue:
        _unsupported(C, st, "situations." + reason + ".transfer_queue")
        return
    """A transfer is due. Whether agreed-but-unrecorded promises are recorded first comes from the situation
    entry (`voluntary_promise: record`), otherwise from `transfer.unrecorded_rule` (drop)."""
    g = st["global"]
    g["pending_transfer"] = queue
    g["transfer_reason"] = reason
    st["pending"] = None
    rule = (_sit(C, reason) or {}).get("voluntary_promise")
    if rule is None:
        rule = _param(C, "transfer.unrecorded_rule") if _has_param(C, "transfer.unrecorded_rule") else None
    keep = rule == "record"
    g["transfer_keeps_promises"] = keep
    if keep:
        return
    if rule is None:
        _unsupported(C, st, "transfer.unrecorded_rule")
    for it in _agreed_items(st):
        it["agreed"] = None
        it["status"] = "skipped"
    for it in _open_items(st):
        it["status"] = "skipped"


def _handle_plan_request(C, st, ev):
    s = _sit(C, "plan_request")
    if s is None:
        _unsupported(C, st, "situations.plan_request")
        return
    C["understood"] = True
    _request_transfer(C, st, s.get("transfer_queue"), "plan_request")


def _handle_paid_or_dispute(C, st, key, ev, exclude=()):
    s = _sit(C, key)
    if s is None:
        _unsupported(C, st, "situations." + key)
        return
    C["understood"] = True
    if key == "paid":
        _say(C, st, "paid_takes_day")
    multi = s.get("multi") if isinstance(s.get("multi"), dict) else None
    targets = _target_items(st, ev)
    if not targets and ev.get("item"):
        _, it = _item_by_id(st, ev.get("item"))
        targets = [it] if it is not None else []
    if not ev.get("item") and exclude:
        # no product named, but the same reply proposes a payment for other products: those are not the ones disputed
        # or paid ("I closed that card years ago; I can pay the loan on the 28th", synthetic H-05 2026-10-11)
        rest = [it for it in targets if it["item_id"] not in exclude]
        if rest:
            targets = rest
    if multi and multi.get("continue"):
        for it in targets:
            if it["status"] in ("open", "agreed"):
                _note_item(C, st, it, key, text=ev.get("text"))
        return
    if key == "dispute":
        # a dispute that ends the call: the disputed product gets the note; the others are not negotiated and get none
        for it in targets:
            if not it["recorded"] and it["status"] != "noted":
                _note_item(C, st, it, key, text=ev.get("text"))
        for it in st["items"]:
            if it["status"] in ("open", "agreed") and not it["recorded"]:
                it["agreed"] = None
                it["status"] = "skipped"
    else:
        # call-level claim: every item without a recorded promise is noted and the call closes
        for it in st["items"]:
            if not it["recorded"] and it["status"] != "noted":
                _note_item(C, st, it, key)
    st["global"]["paid_claim" if key == "paid" else "dispute"] = True
    _trigger(C, st, "paid_claim" if key == "paid" else "dispute")


def _handle_complaint(C, st):
    """A complaint, said or asked about: the table's situation entry names the queue; collection stops and the transfer
    follows, before or after verification. Without an entry the engine has no rule and the reply counts as an aside."""
    s = _sit(C, "complaint")
    if s is None:
        _unsupported(C, st, "situations.complaint")
        return False
    C["understood"] = True
    _request_transfer(C, st, s.get("transfer_queue"), "complaint")
    return bool(st["global"]["pending_transfer"])


# a farewell: only in a reply that does nothing else (a goodbye next to an answer is politeness, not the end)
GOODBYE_RE = re.compile(r"\b(good ?bye|bye( bye)?|that'?s all|that is all|that will be all|that'?ll be all|"
                        r"i (have|need|got) to go( now)?|gotta go|end (the|this) call|talk to you later|"
                        r"have a (good|nice) (day|one|evening))\b")
IDLE_TURNS_MAX = 3   # replies in a row that answer nothing end the conversation


NEGATED_GOODBYE_RE = re.compile(r"\b(not|don'?t|do not|never|no need to|without)\b[^.!?]{0,24}?\b(hang|goodbye|bye|go)\b")


def _goodbye_like(text):
    if not text:
        return False
    low = str(text).lower().replace("\u2019", "'")
    return bool(GOODBYE_RE.search(low)) and not NEGATED_GOODBYE_RE.search(low)


def _end_signal(C, st, cust):
    """True when the customer is ending the conversation: a goodbye in a reply that answers nothing, or several such
    replies in a row (an answer the extractor lost would otherwise leave the model saying goodbye for ever)."""
    g = st["global"]
    if not cust:
        return False
    idle = all(e["kind"] == "other" for e in cust)
    g["idle_turns"] = g.get("idle_turns", 0) + 1 if idle else 0
    passive = all(e["kind"] in ("other", "dont_want_to_talk") for e in cust)
    if passive and any(_goodbye_like(e.get("text") or e.get("span")) for e in cust):
        return True
    return idle and st["stage"] != "party" and g["idle_turns"] >= IDLE_TURNS_MAX


def _end_conversation(C, st):
    """Close with the row the table gives for a customer who ends the conversation at this point of the call."""
    C["understood"] = True
    st["global"]["ended_by_customer"] = True
    if st["stage"] == "party":
        _trigger(C, st, "party_unclear_twice")
        return
    if st["stage"] == "callback":
        _trigger(C, st, "callback_refused_twice")
        return
    s = _sit(C, "dont_want_to_talk")
    if s is not None:
        st["global"]["dont_want"] = max(st["global"]["dont_want"], int(s.get("count") or 2)) - 1
        _handle_dont_want(C, st, None)
        return
    verified = st["identity"]["state"] == "verified"
    for it in _open_items(st) + _agreed_items(st):
        it["agreed"] = None
        it["status"] = "open"
        _exhaust(C, st, it)
    if not verified:
        _trigger(C, st, "identity_declined")


def _handle_dont_want(C, st, ev):
    s = _sit(C, "dont_want_to_talk")
    if s is None:
        _unsupported(C, st, "situations.dont_want_to_talk")
        return
    C["understood"] = True
    st["global"]["dont_want"] += 1
    limit = int(s.get("count") or 2)
    verified = st["identity"]["state"] == "verified"
    if st["global"]["dont_want"] >= limit:
        # The situation may use a more specific note reason than a payment refusal.
        reasons = _param(C, "notes.reasons") if _has_param(C, "notes.reasons") else []
        close = s.get("close_verified") or []
        reason = s.get("note") or (close[1] if len(close) > 1 and close[1] in (reasons or []) else "refused")
        for it in _open_items(st) + _agreed_items(st):
            _note_item(C, st, it, reason)
        _trigger(C, st, "dont_want_twice_verified" if verified else "dont_want_twice_unverified")
        st["global"]["dont_want_closed"] = True
        return
    # below the limit the call goes on: the model said "Have a nice day" and the customer took it as the end (EXT-097)
    _line(C, "Acknowledge that briefly and continue with the current question; do not say goodbye and do not end the call.")
    if verified and st["stage"] == "negotiate":
        it = _current(st)
        if it is not None:
            _refuse(C, st, it)


# ---------------------------------------------------------------------------------------------
# stages: party and callback


def _party_events(C, st, evs):
    kinds = [e["kind"] for e in evs]
    if "party_confirmed" in kinds:
        st["party"] = "customer"
        st["stage"] = "identity"
        st["pending"] = "identity"
        C["understood"] = True
        return
    if "party_other" in kinds or ("callback_offer" in kinds and st["party"] == "unknown"):
        st["party"] = "third_party"
        st["stage"] = "callback"
        st["pending"] = "callback"
        C["understood"] = True
        cb = [e for e in evs if e["kind"] == "callback_offer"]
        if cb:
            _callback_events(C, st, cb)
        return
    asked = False
    for e in evs:
        k = e["kind"]
        if k in ("question_back", "other", "robot_question", "scam_question", "id_answer", "pay_today_yes", "confirm"):
            asked = True
    if not asked and not evs:
        return
    # not a confirmation: ask once more, then the table's row
    C["understood"] = True
    max_asks = _param(C, "party.max_asks")
    if max_asks is None:
        _unsupported(C, st, "party.max_asks")
        st["pending"] = "party"
        return
    if st["party_asks"] < int(max_asks):
        st["party_asks"] += 1
        st["pending"] = "party"
    else:
        _trigger(C, st, "party_unclear_twice")


def _callback_window(C, st):
    w = _param(C, "third_party.callback.window")
    if not isinstance(w, dict):
        _unsupported(C, st, "third_party.callback.window")
        return None
    days = []
    for expr in w.get("days_expr") or []:
        d = _eval(C, st, expr)
        if d is not None:
            days.append(iso(d))
    return {"days": days, "start": w.get("start"), "end": w.get("end"), "inclusive": w.get("inclusive", True),
            "later_than_now": (w.get("later_than") == "now")}


def _callback_events(C, st, evs):
    cb = st["callback"]
    for e in evs:
        C["understood"] = True
        dtext = e.get("date_text")
        ttext = e.get("time_text")
        if not dtext and not ttext and e.get("text"):
            dtext = e.get("text")
            ttext = e.get("text")
        if dtext and C["now"] is not None:
            r = resolve_date(dtext, C["now"], C["rules"])
            if r.get("kind") == "exact":
                cb["date"] = r["date"]
            elif r.get("kind") == "vague" or e.get("date_text") or (cb["date"] is None and resolve_time(dtext) is None):
                cb["date"] = "vague"
        if ttext:
            # Day and time are separate extraction slots; the day can carry the daypart.
            daypart = re.search(r"\b(tonight|morning|afternoon|evening|night)\b", str(dtext or ""), re.I)
            t = resolve_time(ttext + (" " + daypart.group(0) if daypart else ""))
            if t:
                cb["time"] = t
    win = _callback_window(C, st)
    if win is None:
        st["pending"] = "callback"
        return
    date_bad = cb["date"] is not None and (cb["date"] == "vague" or cb["date"] not in win["days"])
    time_bad = False
    if cb["time"] is not None and win["start"] and win["end"]:
        t = cb["time"]
        if win["inclusive"]:
            time_bad = not (win["start"] <= t <= win["end"])
        else:
            time_bad = not (win["start"] < t < win["end"])
    complete = cb["date"] not in (None, "vague") and cb["time"] is not None
    late_enough = True
    if complete and win["later_than_now"]:
        try:
            late_enough = C["now"] is not None and parse_now(cb["date"] + "T" + cb["time"]) > C["now"]
        except ValueError:
            late_enough = False
    if date_bad or time_bad or (complete and not late_enough):
        cb["invalid"] += 1
        cb["date"], cb["time"] = None, None
        max_invalid = _param(C, "third_party.callback.max_invalid")
        if max_invalid is None:
            _unsupported(C, st, "third_party.callback.max_invalid")
            st["pending"] = "callback_retry"
            return
        if cb["invalid"] >= int(max_invalid):
            # the last refused offer is still answered before the goodbye (synthetic I-04, 2026-10-11)
            _line(C, "Say that this time is outside the window as well, so no callback can be booked.")
            _trigger(C, st, "callback_refused_twice")
            return
        st["pending"] = "callback_retry"
        return
    if not complete:
        st["pending"] = "callback_time" if cb["date"] else "callback_date"
        return
    st["pending"] = "callback_book"


# ---------------------------------------------------------------------------------------------
# stages: identity


def _questions(C, st):
    qs = _param(C, "identity.questions")
    if not isinstance(qs, list) or not qs:
        _unsupported(C, st, "identity.questions")
        return []
    return sorted(qs, key=lambda q: int(q.get("order") or 0))


def _parse_answer(q, text):
    typ = str(q.get("type") or "text")
    if typ == "date":
        rule = "month_day_year" if "month, then day" in str(q.get("parse_rule") or "") else "day_month_year"
        r = parse_identity_date(text, rule)
        return r["status"], r["value"]
    if typ.startswith("digits"):
        n = int(typ.split(":")[1]) if ":" in typ else None   # no length given: see parse_digits
        r = parse_digits(text, n)
        return r["status"], r["value"]
    if typ == "year":
        r = parse_year(text)
        return r["status"], r["value"]
    if _code_question(q):
        r = parse_code(text)
        return r["status"], r["value"]
    s = _normalise_text_answer(text, str(q.get("parse_rule") or ""))
    if s.isdigit() and len(s) <= 3:
        # "four two seven" for a company number said in two pieces (synthetic E, the kit's "pieces" style): the first
        # piece; the engine asks for the rest and joins (the identity partials)
        return "partial", s
    return ("complete", s) if s else ("none", None)


CODE_QUESTION_RE = re.compile(r"post ?code|\bzip\b|\bcode\b|reference|\bnumber\b|digits|upper ?case|without spaces|no spaces", re.I)


def _code_question(q):
    """A free-text security question whose answer is an alphanumeric code (a postcode, a reference number): spoken
    digits and letters are joined, spaces and punctuation dropped, upper case (synthetic H-02/H-04/J-05, 2026-10-11)."""
    blob = " ".join(str(q.get(k) or "") for k in ("id", "text", "parse_rule", "type", "wire_field"))
    return bool(CODE_QUESTION_RE.search(blob))


_DIGIT_WORDS = {"zero": "0", "oh": "0", "o": "0", "nought": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _normalise_text_answer(text, rule):
    """A text answer (postcode, reference, name) as the bank wants it: spoken digits become digits ("seven zero three
    zero" -> 7030, "double four" -> 44), a code said in groups loses its spaces when the rule says so or when it looks
    like a code (short alphanumeric groups), case follows the rule ("upper case" / "lower case"). Platform synthetic
    briefs C and H (2026-10-11): the postcode said in words was sent as words and counted as a wrong answer."""
    s = str(text or "").strip().rstrip(".,;!?")
    if not s:
        return ""
    toks = [t for t in re.split(r"[\s\-]+", s) if t]
    out, i = [], 0
    while i < len(toks):
        t, low = toks[i], toks[i].lower().strip(".,")
        if low in ("double", "triple") and i + 1 < len(toks) and toks[i + 1].lower() in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[toks[i + 1].lower()] * (2 if low == "double" else 3))
            i += 2
            continue
        out.append(_DIGIT_WORDS.get(low, t))
        i += 1
    low_rule = rule.lower()
    code_like = len(out) >= 2 and all(re.fullmatch(r"[A-Za-z0-9]{1,4}", x) for x in out) and any(ch.isdigit() for ch in "".join(out))
    joined = "".join(out) if ("no space" in low_rule or "without space" in low_rule or code_like) else " ".join(out)
    if "upper" in low_rule:
        joined = joined.upper()
    elif "lower" in low_rule:
        joined = joined.lower()
    elif code_like:
        joined = joined.upper()
    return joined


def _tiny_piece(text):
    """One digit or one number word ("one", "seven", "42"): the tail of a number said in pieces, nothing else."""
    toks = re.sub(r"[^\w\s-]", " ", str(text or "").lower()).replace("-", " ").split()
    return len(toks) == 1 and (toks[0].isdigit() and len(toks[0]) <= 2 or toks[0] in _DIGIT_WORDS)


def _identity_events(C, st, evs):
    ident = st["identity"]
    qs = _questions(C, st)
    if not qs:
        st["pending"] = "identity"
        return
    if ident["q_index"] >= len(qs):
        return
    q = qs[ident["q_index"]]
    qid = q.get("id")
    for e in evs:
        k = e["kind"]
        if k == "id_answer":
            C["understood"] = True
            text = e.get("text") or e.get("span") or ""
            status, value = _parse_answer(q, text)
            lw = ident.get("last_wrong") or dict()
            if lw.get("qid") == qid and lw.get("text") and _tiny_piece(text):
                # "nineteen seventy" was sent, judged wrong, and the customer adds "one": the pieces customer's second
                # half (synthetic H-04, 2026-10-11); the two are read together before anything else
                s2, v2 = _parse_answer(q, str(lw["text"]) + " " + text)
                if s2 == "complete" and v2 != lw.get("value"):
                    status, value = s2, v2
            if status != "complete":
                prev = ident["partials"].get(qid)
                if prev:
                    s2, v2 = _parse_answer(q, prev + " " + text)
                    if s2 == "complete":
                        status, value = s2, v2
                    elif s2 == "partial":
                        ident["partials"][qid] = prev + " " + text
                    elif status == "partial":
                        ident["partials"][qid] = text
                elif status == "partial":
                    ident["partials"][qid] = text
            if status == "complete":
                ident["partials"].pop(qid, None)
                ident["answer"] = {"qid": qid, "field": q.get("wire_field") or qid, "value": value,
                                   "text": (str(lw["text"]) + " " + text) if (lw.get("qid") == qid and lw.get("text") and _tiny_piece(text)) else text}
                ident["last_wrong"] = None
                st["pending"] = "verify"
            else:
                st["pending"] = "identity_rest" if ident["partials"].get(qid) else "identity_again"
        elif k == "id_decline":
            C["understood"] = True
            rule = _param(C, "identity.decline_rule")
            if not isinstance(rule, dict):
                _unsupported(C, st, "identity.decline_rule")
                st["pending"] = "identity"
                continue
            ident["declines"] += 1
            if ident["declines"] >= int(rule.get("max_declines") or 2):
                ident["state"] = "declined"
                _trigger(C, st, "identity_declined")
            else:
                st["identity"]["protect_said"] = True
                _say(C, st, "questions_protect")
                st["pending"] = "identity"


def _verify_result(C, st, ev):
    ident = st["identity"]
    qs = _questions(C, st)
    data = ev.get("data") or {}
    result = ev.get("result") or ("ok" if data.get("ok") else "failed")
    ans = ident.get("answer") or {}
    qid = ans.get("qid")
    max_wrong = _param(C, "identity.max_wrong")
    if result != "ok" and not isinstance(data.get("verified"), bool) and _has_param(C, "tools.retries"):
        retries = _param(C, "tools.retries")
        if isinstance(retries, int) and not isinstance(retries, bool) and retries >= 0:
            # A service failure is not a wrong customer answer. Retry the same request within the table's budget.
            ident["service_failures"] = ident.get("service_failures", 0) + 1
            if ident["service_failures"] <= retries:
                ident["retried"] += 1
                st["pending"] = "verify"
            else:
                ident["answer"] = None
                ident["state"] = "failed"
                _say(C, st, "system_unavailable")
                _trigger(C, st, "identity_failed")
            return
    ident["service_failures"] = 0
    if result == "unknown":
        ident["unreadable"] = ident.get("unreadable", 0) + 1
        if ident["unreadable"] >= UNREADABLE_MAX:
            _unsupported(C, st, "verify_identity gave no verdict %d times: no rule" % UNREADABLE_MAX)
            ident["answer"] = None
            ident["state"] = "failed"
            _say(C, st, "system_unavailable")
            _trigger(C, st, "identity_failed")
            return
        if ident["retried"] < 1:
            ident["retried"] += 1
            st["pending"] = "verify"
        else:
            ident["answer"] = None
            st["pending"] = "identity_again"
        return
    ident["retried"] = 0
    if data.get("verified") is True:
        if qid and qid not in ident["passed"]:
            ident["passed"].append(qid)
        ident["answer"] = None
        ident["q_index"] += 1
        if ident["q_index"] >= len(qs) or data.get("all_verified") is True:
            ident["state"] = "verified"
            st["stage"] = "fetch"
            st["pending"] = "fetch"
        else:
            st["pending"] = "identity"
        return
    left = data.get("wrong_answers_left")
    if not isinstance(left, int) or isinstance(left, bool):
        left = None
    err = str(data.get("error") or "").lower()
    over = data.get("ok") is False and bool(re.search(r"\bover\b|exhausted|too many attempts|no (more |further )?attempts", err))
    if left is not None and left <= 0 and data.get("verified") is not True:
        over = True
    bank_wrong = (max_wrong - left) if (left is not None and isinstance(max_wrong, int)) else 0
    wc = data.get("wrong_count")   # an API that counts wrong answers so far instead of answers left (wire normaliser)
    if isinstance(wc, int) and not isinstance(wc, bool):
        bank_wrong = max(bank_wrong, wc)
        if isinstance(max_wrong, int) and wc >= max_wrong and data.get("verified") is not True:
            over = True
    if over:
        # the bank says the check is over (no answers left): final, whatever else the answer carries
        ident["answer"] = None
        ident["state"] = "failed"
        _say(C, st, "use_app_or_branch")
        _trigger(C, st, "identity_failed")
        return
    hint_rule = _param(C, "identity.hint_rule") if _has_param(C, "identity.hint_rule") else None
    if data.get("hint") and isinstance(hint_rule, dict) and data.get("hint") == hint_rule.get("hint"):
        ident["hinted"] = True
        ident["answer"] = None
        if not hint_rule.get("counts_as_wrong", False):
            ident["wrong"] = max(ident["wrong"], bank_wrong)    # the hint itself is exempt, the bank's count stays
            _say(C, st, "month_as_word")
            st["pending"] = "identity_hint"
            return
    if data.get("ok") is False and data.get("verified") is None:
        # the service could not read the answer: ask the same question again, no wrong answer counted; a service that
        # never gives a verdict must not keep the call in the question for ever (160 turns on synthetic C, 2026-10-11)
        ident["answer"] = None
        ident["unreadable"] = ident.get("unreadable", 0) + 1
        if ident["unreadable"] >= UNREADABLE_MAX:
            _unsupported(C, st, "verify_identity gave no verdict %d times: no rule" % UNREADABLE_MAX)
            ident["state"] = "failed"
            _say(C, st, "use_app_or_branch")
            _trigger(C, st, "identity_failed")
            return
        st["pending"] = "identity_again"
        return
    hint_counts = isinstance(hint_rule, dict) and bool(hint_rule.get("counts_as_wrong", False))
    if data.get("verified") is False and ans.get("text"):
        ident["last_wrong"] = {"qid": qid, "text": ans.get("text"), "value": ans.get("value")}
    if data.get("verified") is False and (not data.get("hint") or hint_counts):
        # the engine keeps its own count of wrong answers and takes the stricter of the two counters: a bank whose
        # counter does not move (or counts per question) must not let a fourth wrong answer through, and a bank that
        # says no answers are left ends the check even when the engine counted fewer (platform EXT-027/028, 2026-10-10)
        ident["wrong"] += 1
    ident["wrong"] = max(ident["wrong"], bank_wrong)
    ident["answer"] = None
    if isinstance(max_wrong, int) and ident["wrong"] >= max_wrong:
        ident["state"] = "failed"
        _say(C, st, "use_app_or_branch")
        _trigger(C, st, "identity_failed")
        return
    if max_wrong is None:
        _unsupported(C, st, "identity.max_wrong")
    st["pending"] = "identity_again"


# ---------------------------------------------------------------------------------------------
# stages: negotiation and read-back


READBACK_ROUNDS_MAX = 3   # read-backs of the same version without a clear yes before the promise counts as refused
READBACK_TOTAL_MAX = 6    # read-backs in the whole call, whatever the versions
UNREADABLE_MAX = 3        # verify_identity answers without a verdict (ok false, no verified) before the check is given up


def _agreed_snapshot(st):
    """What is agreed per item, for the read-back restatement check."""
    return [(it["item_id"], it["status"], it.get("agreed_cents"), (it.get("agreed") or {}).get("date")) for it in st["items"]]


def _negotiate_events(C, st, evs):
    """Item-scoped events after verification. Proposals beat refusals in the same bundle."""
    at_readback = st.get("pending") in ("readback", "readback_deny")
    if at_readback:
        # "yes, that is fine" extracted as accept_offer at the read-back (no new day, no new amount) is the confirmation
        for e in evs:
            if e["kind"] == "accept_offer" and e.get("amount") is None:
                r = _date_of(C, st, e)
                if r is not None and r.get("kind") != "none":
                    e["kind"] = "change"            # "fine, but make it Friday"
                    e["date_text"] = e.get("date_text") or e.get("span") or e.get("text")
                    continue
                cents = _amount_in_words(e)
                if cents is not None:
                    e["kind"] = "change"            # "yes but only two hundred"
                    e["amount"] = cents_to_number(cents)
                else:
                    e["kind"] = "confirm"
        before = _agreed_snapshot(st)
        C["agreed_calls"] = 0
        st["global"]["unreached"] = 0
        n_lines, n_mand = len(C["lines"]), len(C["mandatory"])
        saved = _copy(st)
    _negotiate_bundle(C, st, evs)
    if not at_readback or st.get("pending") == "record":
        return
    kinds = set(e["kind"] for e in evs)
    restating = kinds & set(["change", "date_proposal", "amount_proposal", "pay_today_yes", "accept_offer"])
    known = all(not e.get("item") or _item_by_id(st, e.get("item"))[1] is not None for e in evs)
    # an event that reached no item (an amount with no product named at a joint read-back) is not a restatement
    if restating and known and C.get("agreed_calls") and not st["global"].get("unreached") \
            and not (kinds & set(["deny", "refuse", "vague_period", "too_much"])) and _agreed_snapshot(st) == before \
            and st.get("pending") in ("readback", "readback_deny", None) and _agreed_items(st):
        # the customer repeated the agreed day and amount in other words ("I can pay the full amount today" at the
        # read-back of the full amount for today): that is the yes, not a change to read back again (a platform call
        # read the same promise back for 30 turns, EXT-023, 2026-10-10)
        st.clear()
        st.update(saved)
        del C["lines"][n_lines:]
        del C["mandatory"][n_mand:]
        _confirm_readback(C, st)
        return
    g = st["global"]
    still = st.get("pending") in ("readback", "readback_deny", None, "which_amount", "which_date")
    same_version = g.get("readback_rounds", 0) >= READBACK_ROUNDS_MAX and still
    too_many = g.get("readback_total", 0) >= READBACK_TOTAL_MAX and still
    if (same_version or too_many) and _agreed_items(st) and not _open_items(st):
        # three read-backs of one version (or six in the call) and still no clear yes: nothing can be recorded
        for it in _agreed_items(st):
            it["agreed"] = None
            it["status"] = "open"
            _exhaust(C, st, it)


def _amount_in_words(e):
    """An amount said in the words of an event that has no amount field; nothing when the words name a day."""
    text = e.get("span") or e.get("text")
    if not text or re.search(r"\b\d+(st|nd|rd|th)\b", str(text).lower()):
        return None
    return resolve_amount_cents(text)


def _share_bundle_date(C, st, group, common_date, key, accepted=False):
    """An amount named in the same reply as a day ("I can pay 200 today", "200 on Friday, yes to your proposal") takes
    that day, whatever the order the extractor filed the two parts in; otherwise the amount would be agreed for the day
    in play and the day would find nothing open (platform EXT-064, 2026-10-10). Returns the day said in words, the only
    one that carries over to the other products of the reply; the day implied by accepting an offer stays with the
    product that has that offer."""
    date_src = common_date
    for e in group:
        if e["kind"] == "pay_today_yes":
            date_src = "today"
        elif e["kind"] in ("date_proposal", "change", "accept_offer") and e.get("date_text") and e.get("amount") is None:
            date_src = e.get("date_text")
    implied = None
    if date_src is None and (any(e["kind"] == "accept_offer" for e in group) or (key is not None and accepted)):
        if key is not None:
            _, it = _item_by_id(st, key)
            offers = [it] if it is not None and it.get("offer") else []
        else:
            offers = [it for it in _open_items(st) if it.get("offer")]
        dates = set(it["offer"].get("date") for it in offers if it["offer"].get("date"))
        if len(dates) == 1:
            implied = dates.pop()
    use = date_src or implied
    if use:
        for e in group:
            if e["kind"] in ("amount_proposal", "change") and _amount_of(e) is not None and not e.get("date_text"):
                own = _date_of(C, st, e)
                if own is None or own.get("kind") == "none":
                    e["date_text"] = use
            elif e["kind"] == "accept_offer" and date_src is not None and not e.get("date_text") and e.get("amount") is None:
                # "yes to the smaller amount, on the 11th": the acceptance takes the day said with it, else the offer's
                # day would be agreed and the day said would find nothing open (synthetic J-02, 2026-10-11)
                e["date_text"] = date_src
    return date_src


CARRIER_KINDS = ("amount_proposal", "date_proposal", "change", "accept_offer", "vague_period")
# replies whose slot the extractor sometimes fills with the values of the proposal said in the same breath
VALUE_DONORS = ("pay_today_no", "pay_today_yes", "refuse", "deny", "too_much", "confirm", "other")


def _tidy_bundle(C, st, evs):
    """Extractor tolerance before the item split. On the platform the amount, the day and the product of one reply are
    filed under whichever slot came first ("No, I can pay 637.50 on Monday 19 October" -> pay_today_no with amount
    637.5 and the day; amount_proposal and date_proposal with nothing; EXT-065/072/102/154, B-109/116/122, 2026-10-11):
      1. a proposal event without its value takes amount, day, words and product from such a reply, which then goes;
      2. a refusal that still carries an amount is the proposal of that amount (an amount is never a refusal);
      3. a day proposal that carries an amount is an amount proposal; an amount proposal with no readable amount is
         dropped (asking "how much" is never allowed), or, alone, the customer saying the amount is too much."""
    used = set()
    for e in evs:
        if e["kind"] not in CARRIER_KINDS:
            continue
        for d in evs:
            if d is e or d["kind"] not in VALUE_DONORS:
                continue
            if e.get("item") and d.get("item") and e["item"] != d["item"]:
                continue  # a misplaced value can be recovered only within the same product's reply
            took = False
            if e.get("amount") is None and d.get("amount") is not None:
                e["amount"], took = d.get("amount"), True
            if not e.get("date_text") and d.get("date_text") and e["kind"] != "vague_period":
                e["date_text"], took = d.get("date_text"), True
            if not e.get("text") and d.get("text") and e.get("amount") is None:
                e["text"], took = d.get("text"), True
            if took:
                if not e.get("item") and d.get("item"):
                    e["item"] = d.get("item")
                used.add(id(d))
                e["_donor"] = id(d)
                break
    for e in evs:
        if e["kind"] in ("pay_today_no", "pay_today_yes", "refuse", "deny") and e.get("amount") is not None and id(e) not in used:
            e["kind"] = "amount_proposal"
        if e["kind"] == "date_proposal" and e.get("amount") is not None:
            e["kind"] = "amount_proposal"
    drop = set()
    for e in evs:
        if id(e) in used or e["kind"] != "amount_proposal" or _amount_of(e) is not None:
            continue
        # an amount proposal with no readable amount: the words it took back to their own reply ("No, not that date, a
        # smaller amount on the 23rd" is the refusal), else alone it is "too much", else nothing (never ask how much)
        if e.get("_donor") in used:
            used.discard(e["_donor"])
            drop.add(id(e))
        elif all(x is e or x["kind"] == "other" or id(x) in used or id(x) in drop for x in evs):
            e["kind"] = "too_much"
        else:
            drop.add(id(e))
    out, seen = [], []
    for e in evs:
        e.pop("_donor", None)
        if id(e) in used or id(e) in drop:
            continue
        key = (e["kind"], e.get("item"), e.get("amount"), e.get("date_text"))
        if e["kind"] in CARRIER_KINDS and key in seen:
            continue
        seen.append(key)
        out.append(e)
    evs[:] = out


def _negotiate_bundle(C, st, evs):
    C["pay_today_pending"] = st.get("pending") == "pay_today"
    if C["pay_today_pending"] and st["items"]:
        st["pay_today_asked"] = True
    _tidy_bundle(C, st, evs)
    by_item = {}
    order = []
    proposal_items = set()
    for e in evs:
        key = e.get("item") or None
        if key not in by_item:
            by_item[key] = []
            order.append(key)
        by_item[key].append(e)
        if e["kind"] in ("date_proposal", "amount_proposal", "accept_offer", "pay_today_yes", "change", "vague_period"):
            proposal_items.add(key)
    common_date = _share_bundle_date(C, st, by_item[None], None, None) if None in by_item else None
    accepted = any(e["kind"] == "accept_offer" for e in by_item.get(None, []))
    for key in order:
        if key is not None:
            _share_bundle_date(C, st, by_item[key], common_date, key, accepted)
    # events for all items first (so a common date is applied before per-item ones)
    for key in order:
        group = by_item[key]
        # a date or an amount is never a refusal: a refusal in the same bundle for that item is dropped
        has_proposal = key in proposal_items or None in proposal_items or (key is None and bool(proposal_items))
        # "No, the full amount is too much": the no belongs to the too-much, which gets the minimum offered once; it is
        # not a flat refusal that uses a persuasion attempt (synthetic J-02, 2026-10-11)
        has_too_much = any(e["kind"] == "too_much" for e in group)
        for e in group:
            k = e["kind"]
            if k in ("refuse", "deny", "other") and st.get("pending") == "exact_day" and not e.get("date_text") and e.get("amount") is None:
                # "I do not know exactly" after the one question for the exact day: still no day, so the vague rule's
                # second step (propose the deadline), not a refusal with a persuasion offer (platform EXT-053, 2026-10-10)
                k = "vague_period"
            if k == "amount_proposal" or (k == "change" and e.get("amount") is not None):
                for it in _targets_for(st, e, current_only=True):
                    cents = _amount_of(e)
                    if cents is None:
                        st["pending"] = "which_amount"
                        C["understood"] = True
                        continue
                    _prepare_change(it)
                    _handle_amount(C, st, it, e, cents, _date_of(C, st, e) if (e.get("date_text") or e.get("span")) else None)
            elif k == "date_proposal" or (k == "change" and e.get("amount") is None):
                targets = [it for it in _targets_for(st, e, current_only=False) if not _offered_now(C, it)]
                common = e.get("item") is None and len(targets) > 1
                resolved = _date_of(C, st, e)
                if resolved is None:
                    if targets:
                        st["pending"] = "which_date"
                    C["understood"] = True
                    continue
                for it in targets:
                    _prepare_change(it)
                    _apply_date(C, st, it, _amount_in_play(it), resolved, common=common)
            elif k == "pay_today_yes":
                for it in _targets_for(st, e, current_only=False):
                    if _offered_now(C, it):
                        continue
                    _apply_date(C, st, it, _amount_in_play(it), _today_event(C))
            elif k == "accept_offer":
                targets = [it for it in _targets_for(st, e, current_only=False) if it.get("offer") and not _offered_now(C, it)]
                if not targets:
                    cur = _current(st)
                    targets = [cur] if cur is not None and not _offered_now(C, cur) else []
                for it in targets:
                    _accept(C, st, it, e)
            elif k == "vague_period":
                for it in _targets_for(st, e, current_only=False):
                    _vague(C, st, it, _amount_in_play(it))
            elif k == "too_much":
                if has_proposal:
                    for it in _targets_for(st, e, current_only=True):
                        it["too_much"] = True
                    continue
                for it in _targets_for(st, e, current_only=True):
                    it["too_much"] = True
                    d = None
                    if e.get("date_text"):
                        r = _date_of(C, st, e)       # "a smaller amount on the 23rd": the floor goes on that day
                        if r is not None and r.get("kind") == "exact" and _check_date(C, st, it, r["date"])[0] == "ok":
                            d = r["date"]
                    _floor_offer(C, st, it, d or _date_in_play(C, st, it), after_too_much=True)
            elif k in ("refuse", "pay_today_no", "deny"):
                if has_proposal or has_too_much:
                    C["understood"] = True
                    continue
                if st.get("pending") == "readback" and k == "deny":
                    C["understood"] = True
                    st["pending"] = "readback_deny"
                    continue
                for it in _targets_for(st, e, current_only=True):
                    if it["status"] == "agreed":
                        it["refused"].append([it["agreed"]["amount"], it["agreed"]["date"]])
                        it["agreed"] = None
                        it["status"] = "open"
                    _refuse(C, st, it)
            elif k == "confirm":
                if st.get("pending") in ("readback", "readback_deny") and not has_proposal:
                    _confirm_readback(C, st)
                else:
                    cur = _current(st)
                    if cur is not None and _offered_now(C, cur):
                        C["understood"] = True
                    elif cur is not None and cur.get("offer"):
                        _accept(C, st, cur, e)
                    elif C["pay_today_pending"] and cur is not None:
                        _apply_date(C, st, cur, _amount_in_play(cur), _today_event(C))


def _targets_for(st, e, current_only):
    out = _targets_of(st, e, current_only)
    if not out:
        st["global"]["unreached"] = st["global"].get("unreached", 0) + 1
    return out


def _targets_of(st, e, current_only):
    if e.get("item"):
        _, it = _item_by_id(st, e.get("item"))
        if it is None:
            return []
        if it["status"] in ("open", "agreed"):
            return [it]
        return []
    if current_only:
        cur = _current(st)
        if cur is None:
            ag = _agreed_items(st)
            return [ag[0]] if len(ag) == 1 else []
        return [cur]
    opens = _open_items(st)
    if opens:
        return opens
    return _agreed_items(st) if st.get("pending") in ("readback", "readback_deny") else []


def _prepare_change(it):
    """An agreed item that the customer changes goes back to open with its old values as the basis."""
    if it["status"] == "agreed" and it.get("agreed"):
        it["proposed_amount"] = it.get("agreed_cents")
        it["proposed_date"] = it["agreed"]["date"]
        it["basis"] = it.get("agreed_cents")
        it["agreed"] = None
        it["status"] = "open"


def _confirm_readback(C, st):
    C["understood"] = True
    st["global"]["readback_rounds"] = 0
    for it in _agreed_items(st):
        it["confirmed"] = True
        it["confirmed_version"] = it["readback_version"]
    st["pending"] = "record"


def _to_record(st):
    return [it for it in st["items"] if it["confirmed"] and not it["recorded"] and it["status"] != "noted" and it.get("agreed")]


def _advance(C, st):
    """After the bundle: pick the next open item, the read-back, the writes, or the closing path."""
    g = st["global"]
    pending = st.get("pending")
    cur = _current(st)
    if pending in ("support_offer", "can_i_help", "hardship_open"):
        return
    if g.get("hardship_declined"):
        # no persuasion after a declined support offer: whatever is still open (a vague day, an unanswered attempt) is
        # noted as hardship; a day agreed in the same reply is still read back and recorded, and the minimum or the
        # deadline offered in answer to the customer's own figure or day stays on the table (it is a reply to what they
        # named, not persuasion; synthetic G-06, 2026-10-11)
        for it in _open_items(st):
            if it.get("offer") and it["offer"].get("kind") != "attempt":
                continue
            _note_item(C, st, it, "hardship")
            if not C["notes_mode"]:
                _trigger(C, st, "hardship_support_declined")
        cur = _current(st)
        pending = st.get("pending")
        if cur is not None and cur.get("offer") and pending not in ("readback", "readback_deny", "record"):
            st["pending"] = pending = "offer"
    if pending == "readback_deny" and _agreed_items(st):
        return
    if pending in ("past_date", "which_date", "which_amount", "exact_day") and cur is not None:
        # a question about an item that is no longer open (noted, agreed in the same reply) must not be asked
        return
    if pending == "offer" and cur is not None and cur.get("offer"):
        return
    if _to_record(st):
        st["stage"] = "record"
        st["pending"] = "record"
        return
    if g["pending_transfer"] and not g["transfer_done"]:
        # no negotiation continues once a transfer is due; a promise agreed in the same reply is read back
        # and recorded first only when the situation entry says so
        for it in _open_items(st):
            it["status"] = "skipped"
        if _agreed_items(st):
            st["stage"] = "readback"
            st["pending"] = "readback"
            return
        st["stage"] = "transfer"
        st["pending"] = "transfer"
        return
    if g.get("dont_want_closed") or st["identity"]["state"] in ("failed", "declined"):
        st["stage"] = "close"
        st["pending"] = "close"
        return
    if cur is not None:
        st["stage"] = "negotiate"
        if cur.get("offer"):
            st["pending"] = "offer"
        elif not st["pay_today_asked"]:
            st["pending"] = "pay_today"
        elif cur.get("proposed_amount") is not None:
            st["pending"] = "which_date"
        elif cur["attempts_used"] == 0 and _has_param(C, "multi.pay_today_once") and _param(C, "multi.pay_today_once") and len(st["items"]) > 1:
            # Brief B rule 4: the next product starts at attempt 1 without a second pay-today question
            _attempt(C, st, cur)
            if cur.get("offer"):
                st["pending"] = "offer"
            else:
                _advance(C, st)
        else:
            st["pending"] = "offer_any"
        return
    if _agreed_items(st):
        st["stage"] = "readback"
        st["pending"] = "readback"
        return
    st["stage"] = "close"
    st["pending"] = "close"


# ---------------------------------------------------------------------------------------------
# tool results


def _result_class(ev):
    r = ev.get("result")
    if r in ("ok", "failed", "unknown"):
        return r
    data = ev.get("data")
    if isinstance(data, dict) and "ok" in data:
        return "ok" if data.get("ok") else "failed"
    return "unknown"


def _apply_tool_result(C, st, ev):
    tool = ev.get("tool")
    res = _result_class(ev)
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    st["commits"].append({"tool": tool, "args": ev.get("args") or {}, "result": res, "item_id": ev.get("item")})
    g = st["global"]
    if tool == "verify_identity":
        ev2 = dict(ev)
        ev2["result"] = res
        _verify_result(C, st, ev2)
        return
    if tool == "get_account":
        if res == "ok" and isinstance(data.get("products"), list):
            _build_items(C, st, data["products"])
            st["stage"] = "negotiate"
            st["pending"] = "pay_today"
            C["disclose"] = True
            return
        g["fetch_failures"] += 1
        if g["fetch_failures"] <= 1:
            st["pending"] = "fetch"
        else:
            _unsupported(C, st, "get_account failed twice: no rule")
            _trigger(C, st, "fetch_failed_twice")
            st["stage"] = "close"
            st["pending"] = "close"
        return
    if tool == "create_promise":
        it = None
        if ev.get("item"):
            _, it = _item_by_id(st, ev.get("item"))
        if it is None:
            for cand in st["items"]:
                if cand["confirmed"] and not cand["recorded"] and cand["status"] != "noted":
                    it = cand
                    break
        if it is None:
            return
        if res == "ok":
            it["recorded"] = True
            it["status"] = "recorded"
            _say(C, st, "promise_recorded")
            _say(C, st, "text_message")
            return
        it["record_failures"] += 1
        retries = _param(C, "recording.retries")
        if retries is None:
            _unsupported(C, st, "recording.retries")
            retries = 0
        if it["record_failures"] <= int(retries):
            return
        # failed for good
        se = _sit(C, "service_error")
        if se and se.get("note") and C["notes_mode"]:
            it["confirmed"] = False
            _note_item(C, st, it, "service_error")
            _say(C, st, "could_not_record")
        else:
            it["confirmed"] = False
            _note_item(C, st, it, "service_error")
            _say(C, st, "could_not_record")
            _trigger(C, st, "record_failed_twice")
        return
    if tool == "transfer_to_agent":
        if res == "ok":
            g["transfer_done"] = g["pending_transfer"] or (ev.get("args") or {}).get("queue")
            st["pending"] = "close"
            return
        g["transfer_failures"] += 1
        if g["transfer_failures"] >= 2:
            _unsupported(C, st, "transfer failed twice: no rule")
            g["transfer_done"] = g["pending_transfer"]
            st["pending"] = "close"
        return
    if tool == "add_note":
        it = None
        if ev.get("item"):
            _, it = _item_by_id(st, ev.get("item"))
        if it is None:
            for cand in st["items"]:
                if cand["noted"] and not cand["noted_written"]:
                    it = cand
                    break
        if it is None:
            return
        if res == "ok":
            it["noted_written"] = True
        else:
            it["note_failures"] += 1
            if it["note_failures"] >= 2:
                _unsupported(C, st, "add_note failed twice: no rule")
                it["noted_written"] = True
        return
    if tool == "close_call":
        if res == "ok" or (res == "failed" and "closed" in str(data.get("error") or "")):
            st["closed"] = True
            st["stage"] = "end"
            st["pending"] = None
            return
        g["close_failures"] += 1
        if g["close_failures"] >= 2:
            _unsupported(C, st, "close_call failed twice: no rule")
            st["closed"] = True
            st["stage"] = "end"
            st["pending"] = None
        return
    if tool == "schedule_callback":
        if res == "ok":
            st["callback"]["booked"] = True
            _trigger(C, st, "callback_booked")
            st["pending"] = "close"
        else:
            st["callback"]["book_failures"] = st["callback"].get("book_failures", 0) + 1
            if st["callback"]["book_failures"] >= 2:
                # nothing was booked: the call ends with the row for a callback that could not be arranged, instead of
                # asking for another time and letting the model announce a booking (synthetic C-02, 2026-10-11)
                _unsupported(C, st, "schedule_callback failed twice: no rule")
                st["callback"]["date"], st["callback"]["time"] = None, None
                _trigger(C, st, "callback_refused_twice")
                st["pending"] = "close"


# ---------------------------------------------------------------------------------------------
# closing


def _close_row(C, st):
    rows = _param(C, "closing.rows")
    if not isinstance(rows, list) or not rows:
        _unsupported(C, st, "closing.rows")
        return None
    g = st["global"]
    active = []
    if g["transfer_done"]:
        active.append("transfer_done:" + str(g["transfer_done"]))
    if any(it["recorded"] for it in st["items"]):
        active.append("promise_recorded")
    if C["notes_mode"] and not any(it["recorded"] for it in st["items"]):
        notes = [(it["noted"]["reason"], it["noted"].get("canonical") or it["noted"]["reason"]) for it in st["items"] if it["noted"]]
        if notes and all(c == "paid" for _, c in notes):
            active.append("all_items_noted_paid")
        else:
            for r, c in notes:
                if c != "paid":
                    active.append("first_non_paid_note:" + str(r))
                    break
    active.extend(g["triggers"])
    best = None
    for idx, row in enumerate(rows):
        trig = row.get("triggers") or []
        hits = [active.index(t) for t in trig if t in active]
        if not hits:
            continue
        key = (int(row.get("precedence") or 99), min(hits), idx)
        if best is None or key < best[0]:
            best = (key, row)
    if best is None:
        return None
    return best[1]


# ---------------------------------------------------------------------------------------------
# rendering of the pending question and the writes


def _readback_text(C, st):
    parts = []
    for it in st["items"]:
        if it["status"] != "agreed" or not it.get("agreed"):
            continue
        parts.append("%s: %s on %s." % (it["label"], _money(it.get("agreed_cents"), C), _date_words(it["agreed"]["date"])))
        if it.get("own_deadline"):
            ph = _phrase(C, "own_deadline_note")
            text = ph.get("text") if ph else FALLBACK_TEXT["own_deadline_note"]
            parts.append(_fill(text, {"product": it["label"], "deadline": _date_words(it["deadline"])}))
    return " ".join(parts)


def _offer_text(C, st, it):
    off = it.get("offer") or {}
    d = off.get("date")
    dtext = _date_words(d) if d and d != "today" else ("today" if d == "today" else "a day you name")
    return "Propose %s of %s on %s for the %s." % (
        "the minimum amount" if off.get("kind") == "floor" else "a payment", _money(off.get("amount"), C), dtext, it["label"])


def _render(C, st, out):
    """Fill say_next, mandatory_lines, readback_text, writes, close and engine_next from the state."""
    g = st["global"]
    pending = st.get("pending")
    stage = st["stage"]
    writes = []
    call = st.get("call") or {}
    fmt = dict(call)
    if st["closed"]:
        out["engine_next"] = "end"
        out["what_to_do_next"] = "The call is closed. Say nothing more."
        return
    if stage == "readback" and not _readback_text(C, st):
        st["stage"] = stage = "negotiate"
    # a chosen closing row wins over everything else (the situation already decided the call)
    row = None
    if g["pending_transfer"] and not g["transfer_done"] and stage == "transfer":
        writes.append({"tool": "transfer_to_agent", "args": {"queue": g["pending_transfer"]}, "item_id": None,
                       "intent_key": "transfer:" + str(g["pending_transfer"])})
        _say(C, st, "close_transferred")
        out["engine_next"] = "transfer"
        out["what_to_do_next"] = "Transfer the call to the %s queue, then close." % g["pending_transfer"]
    elif stage == "party":
        if not st["opened"]:
            _say(C, st, "opening")
            opening = _phrase(C, "opening") or {}
            content = _param(C, "opening.sentence_content") if _has_param(C, "opening.sentence_content") else None
            if not opening.get("exact") and re.search(r"\b(first|one|single) sentence\b", " ".join(str(x or "") for x in (opening.get("text"), content)), re.I):
                # "all in the first sentence" (synthetic J-01, 2026-10-11: the recording notice was moved to a second sentence)
                _line(C, "Put the bank's name, what you are and that the call is recorded in one single sentence.")
            if opening.get("exact") and isinstance(content, str) and content.strip() != str(opening.get("text") or "").strip():
                _line(C, "After the supplied exact opening, convey any remaining introduction content from these "
                      "requirements without repeating that opening: " + content)
            st["opened"] = True
        _say(C, st, "party_question")
        if st["party_asks"] > 1:
            # the model asked for an account number on the second ask (synthetic H-01, 2026-10-11)
            _line(C, _fill("Ask once more, in one short sentence, whether you are speaking with {title} {last_name}; ask for "
                           "nothing else and name no account or security detail.", fmt))
        out["engine_next"] = "party"
        out["what_to_do_next"] = "Ask whether you are speaking with the customer; only yes, that's me, speaking or their own name confirms."
    elif stage == "callback" and pending in ("callback", "callback_retry", "callback_time", "callback_date"):
        if pending == "callback":
            _say(C, st, "callback_question")
            out["what_to_do_next"] = "Say nothing about the reason for the call; ask when the customer can be reached."
        elif pending == "callback_retry":
            _line(C, "That time is outside the window; ask once for another day or time.")
            out["what_to_do_next"] = "Ask once for another time inside the callback window."
        elif pending == "callback_time":
            _line(C, "Ask at what time on that day the customer can be reached.")
            out["what_to_do_next"] = "Ask for the time of the callback."
        else:
            _line(C, "Ask on which day the customer can be reached at that time.")
            out["what_to_do_next"] = "Ask for the day of the callback."
        out["engine_next"] = "callback"
    elif stage == "callback" and pending == "callback_book":
        cb = st["callback"]
        writes.append({"tool": "schedule_callback", "args": {"date": cb["date"], "time": cb["time"]}, "item_id": None,
                       "intent_key": "callback:%s:%s" % (cb["date"], cb["time"])})
        out["engine_next"] = "callback"
        out["what_to_do_next"] = "Schedule the callback, then close."
    elif stage == "identity" and st["identity"]["state"] == "pending":
        qs = _questions(C, st)
        ident = st["identity"]
        q = qs[ident["q_index"]] if ident["q_index"] < len(qs) else None
        if pending == "verify" and ident.get("answer"):
            a = ident["answer"]
            writes.append({"tool": "verify_identity", "args": {"field": a["field"], "answer": a["value"]}, "item_id": None,
                           "intent_key": "verify:%s:%d" % (a["qid"], ident["wrong"] + len(ident["passed"]) + ident["retried"])})
            out["engine_next"] = "verify"
            out["what_to_do_next"] = "Verify the answer with the bank before saying anything else."
        elif q is not None:
            qid = q.get("id")
            if pending == "identity_hint":
                _say(C, st, "month_as_word")
            elif pending == "identity_rest":
                _line(C, "Ask for the rest of the answer to: " + str(q.get("text") or qid))
            elif pending == "identity_again":
                _line(C, "Ask the same question again: " + str(q.get("text") or qid))
            else:
                ph = _phrase(C, "ask_" + str(qid))
                if ph is not None:
                    _say(C, st, "ask_" + str(qid))
                else:
                    _line(C, str(q.get("text") or ("Ask the security question " + str(qid))))
            out["engine_next"] = "identity"
            out["what_to_do_next"] = "Ask security question %d of %d (%s) and report the answer." % (ident["q_index"] + 1, len(qs), qid)
        else:
            out["engine_next"] = "identity"
            out["ask_clarify"] = True
    elif stage == "fetch":
        writes.append({"tool": "get_account", "args": {}, "item_id": None, "intent_key": "fetch"})
        out["engine_next"] = "fetch"
        out["what_to_do_next"] = "Fetch the account before stating anything."
    elif pending in ("support_offer", "can_i_help"):
        if C.get("question_now") != pending:
            _say(C, st, pending)       # the reply did not answer the question: ask it again, after any answer given
            _line(C, OFFER_IS_A_QUESTION)
        out["engine_next"] = stage if stage in SPEAKING_STAGES else "negotiate"
        out["what_to_do_next"] = "Ask the yes-or-no question again and report accept or decline."
    elif pending == "hardship_open":
        if C.get("question_now") != pending:
            _say(C, st, "hardship_open")
        out["engine_next"] = stage if stage in SPEAKING_STAGES else "negotiate"
        out["what_to_do_next"] = "Wait for the customer; report any amount or day they name, or that they do not."
    elif stage == "negotiate":
        if C.get("disclose"):
            _say(C, st, "disclosure")
            for it in st["items"]:
                _line(C, "%s: %s past due, %s days late." % (it["label"], _money(it["past_due"], C), it.get("days_late")))
            if len(st["items"]) > 1:
                # the model folded three products into one sentence with an invented total (platform B EXT-035, 2026-10-11)
                _line(C, "One sentence per product, each with its own amount and its own days late; do not add the amounts up.")
        cur = _current(st)
        if pending == "pay_today":
            _say(C, st, "pay_today")
            out["what_to_do_next"] = "Ask whether the customer can pay today; never ask how much they can pay."
        elif pending == "offer" and cur is not None and cur.get("offer"):
            for it in st["items"]:
                if it["status"] == "open" and it.get("offer"):
                    _line(C, _offer_text(C, st, it))
            out["what_to_do_next"] = "Make exactly this proposal and report accept, refuse, or a counter-proposal."
        elif pending == "exact_day" and cur is not None:
            _line(C, "Ask once for the exact day of the payment for the %s." % cur["label"])
            out["what_to_do_next"] = "Ask for the exact day."
        elif pending == "past_date" and cur is not None:
            _line(C, "That day has already passed; ask for a date from today on for the %s." % cur["label"])
            out["what_to_do_next"] = "Ask for a date from today on."
        elif pending == "which_date" and cur is not None:
            _line(C, "Ask on which exact day the customer will pay %s for the %s." % (_money(_amount_in_play(cur), C), cur["label"]))
            out["what_to_do_next"] = "Ask for the exact payment date."
        elif pending == "which_amount" and cur is not None:
            _line(C, "Ask the customer to repeat the amount for the %s." % cur["label"])
            out["what_to_do_next"] = "Ask the customer to repeat the amount."
            out["ask_clarify"] = True
        elif cur is not None:
            _line(C, "Ask about the %s: %s past due; the customer should name a payment date." % (cur["label"], _money(cur["past_due"], C)))
            out["what_to_do_next"] = "Continue with the %s." % cur["label"]
        else:
            _line(C, "Ask the customer to repeat what they said.")
            out["what_to_do_next"] = "Ask the customer to repeat what they said."
            out["ask_clarify"] = True
        out["engine_next"] = "negotiate"
    elif stage == "readback":
        out["readback_text"] = _readback_text(C, st)
        g["readback_rounds"] = g.get("readback_rounds", 0) + 1
        g["readback_total"] = g.get("readback_total", 0) + 1
        _say(C, st, "do_you_confirm")
        out["engine_next"] = "readback"
        out["what_to_do_next"] = "Read the promise back exactly and ask for confirmation; report confirm, change or deny."
        if pending == "readback_deny":
            _line(C, "Ask what should change: the amount or the date.")
        st["pending"] = "readback"
    elif stage == "record":
        for it in st["items"]:
            if it["confirmed"] and not it["recorded"] and it["status"] != "noted" and it.get("agreed"):
                writes.append({"tool": "create_promise",
                               "args": {"product_id": it["item_id"], "amount": it["agreed"]["amount"], "date": it["agreed"]["date"]},
                               "item_id": it["item_id"], "intent_key": "promise:%s:%d" % (it["item_id"], it["record_failures"])})
        out["engine_next"] = "record"
        out["what_to_do_next"] = "Record the promise; say it is recorded only after the bank confirms."
    elif stage in ("close", "note"):
        if C["notes_mode"] and not g["transfer_done"] and not g["pending_transfer"]:
            for it in st["items"]:
                if it["noted"] and not it["noted_written"] and not it["recorded"]:
                    writes.append({"tool": "add_note", "args": {"product_id": it["item_id"], "reason": it["noted"]["reason"]},
                                   "item_id": it["item_id"], "intent_key": "note:%s:%s" % (it["item_id"], it["noted"]["reason"])})
        if writes:
            st["stage"] = "note"
            out["engine_next"] = "note"
            out["what_to_do_next"] = "Add the notes, then close."
        else:
            row = _close_row(C, st)
            st["stage"] = "close"
            if row is None:
                _unsupported(C, st, "closing.rows:no row matches")
                out["engine_next"] = "close"
                out["ask_clarify"] = True
                out["what_to_do_next"] = "No closing row matches; say goodbye and end the call."
            else:
                st["close"] = {"outcome": row.get("outcome"), "reason": row.get("reason")}
                args = {"outcome": row.get("outcome")}
                if row.get("reason") is not None:
                    args["reason"] = row.get("reason")
                writes.append({"tool": "close_call", "args": args, "item_id": None,
                               "intent_key": "close:%s:%s" % (row.get("outcome"), row.get("reason"))})
                notes = [it for it in st["items"] if it["noted"]]
                contact_close = g.get("dont_want_closed") and bool(notes)
                notes_ok = all(it["noted_written"] and it["note_failures"] < 2 for it in notes)
                # A contact-request closing phrase may acknowledge the notes. Never speak it after a failed write.
                if row.get("line") and (not contact_close or notes_ok):
                    _say(C, st, row["line"])
                phrase = _phrase(C, row.get("line")) if row.get("line") else None
                if contact_close and notes_ok and not (phrase and phrase.get("exact")):
                    _say(C, st, "request_noted")
                _say(C, st, "thanks_goodbye")
                out["engine_next"] = "close"
                out["what_to_do_next"] = "Thank the customer and say goodbye, then close the call as %s / %s." % (row.get("outcome"), row.get("reason"))
    else:
        out["engine_next"] = stage if stage in SPEAKING_STAGES else "negotiate"
        out["ask_clarify"] = True
        out["what_to_do_next"] = "Ask the customer to repeat."
    out["writes"] = writes
    out["close"] = st.get("close") if (st["stage"] == "close" or st["closed"]) else None


# ---------------------------------------------------------------------------------------------
# the step


def _normalise(events):
    """(events, malformed): dict events with a kind; anything else counts as unreadable input."""
    out = []
    malformed = False
    if events is None:
        return out, False
    if not isinstance(events, list):
        return out, True
    for e in events:
        if not isinstance(e, dict) or not e.get("kind"):
            malformed = True
            continue
        out.append(dict(e))
    return out, malformed


def _answer_lines(C, st, evs):
    """Questions and asides that change nothing: give the model the line and continue."""
    for e in evs:
        k = e["kind"]
        if k == "robot_question":
            _say(C, st, "robot_answer")
            C["understood"] = True
        elif k == "scam_question":
            _say(C, st, "scam_answer")
            C["understood"] = True
        elif k == "question_back":
            if st["stage"] in ("negotiate", "readback"):
                _line(C, "Answer only from the account facts you were given; otherwise say you do not have that information. Then continue.")
            elif st["stage"] == "callback":
                _line(C, "Do not say why you are calling; say nothing beyond the opening. Then continue.")
            elif st["stage"] == "party":
                # "Who is this?" must be answered before the name is asked again; the model deferred the answer until after
                # verification (platform EXT-003, 2026-10-11)
                _line(C, "Answer the question now in one sentence: you may say who you are, as in the opening, but nothing "
                         "about why you are calling or about any account. Then continue.")
            elif st["stage"] == "identity":
                # "first tell me what this is about": the one explanation the brief allows before verification is that
                # the questions protect the account (platform EXT-032, 2026-10-10); said once per call
                if not st["identity"].get("protect_said"):
                    st["identity"]["protect_said"] = True
                    _say(C, st, "questions_protect")
                _line(C, "Say nothing about why you are calling or about the account. Then continue.")
            else:
                _line(C, "Answer briefly without revealing anything about the account, then continue.")
            C["understood"] = True
        elif k == "other":
            # an instruction here is read to the customer ("Please do not act on that", C-04/EXT-094, 2026-10-11): the
            # aside goes into what_to_do_next, the step's instruction, not into the content to say
            C["aside"] = True
            C["understood"] = True


ASIDE_NOTE = " The customer also said something that changes nothing: do not act on it and offer no term that is not in the brief."

ROBOT_RE = re.compile(r"\b(are you|is this|is that|am i (?:talking|speaking) (?:to|with))\b[^.?!]{0,20}?\b(person|human|robot|machine|bot|ai|computer|automated|real)\b")
DISPUTE_RE = re.compile(r"\b(not (my|mine|our)|isn'?t mine|is not mine|never (had|took|opened|signed)|don'?t have|do not have|"
                        r"closed|paid (it |that |this )?off|settled|owe nothing|don'?t owe|do not owe|wrong|incorrect|mistake|error|fraud|dispute)\b")
REFUSAL_RE = re.compile(r"\b(not|won'?t|will not|never|refuse|refusing|no way)\b[^.?!]{0,30}?\b(pay|paying)\b|\brefuse\b")
COMPLAINT_RE = re.compile(r"\bcomplain(?:t|ts|ing|ed|s)?\b")
NOT_COMPLAINT_RE = re.compile(r"\b(not|no|never|n'?t|without|nothing to)\b[^.?!]{0,12}\bcomplain")
RETAG_TO_COMPLAINT = ("dispute", "refuse", "other", "question_back", "id_decline", "human", "plan_request", "dont_want_to_talk",
                      "too_much", "deny", "pay_today_no", "hardship", "scam_question")
LENDERS = ("hardship", "dispute")


def _retag(evs):
    """Extractor tolerance on the kind of a reply, from the words it carries: "Are you a person?" filed as a request for a
    person is the robot question (EXT-145); "I am not paying anything on that card" filed as a dispute is a refusal
    (B EXT-119), a dispute names the debt as wrong or not theirs."""
    for e in evs:
        low = str(e.get("text") or e.get("span") or "").lower().replace("’", "'")
        if not low:
            continue
        if e["kind"] == "human" and ROBOT_RE.search(low):
            e["kind"] = "robot_question"
        elif e["kind"] in RETAG_TO_COMPLAINT and COMPLAINT_RE.search(low) and not NOT_COMPLAINT_RE.search(low):
            e["kind"] = "complaint"        # "I want to make a formal complaint" filed as a dispute (synthetic G-05/J-03)
        elif e["kind"] == "dispute" and not DISPUTE_RE.search(low) and REFUSAL_RE.search(low):
            e["kind"] = "refuse"


def _lend_values(evs):
    """The amount, day and product of a proposal said in the same breath as a hardship, a dispute or a payment claim are
    sometimes filed under that reply ("my wife passed away ... I can only do 200 for the loan next Tuesday": hardship
    with amount 200, date next Tuesday, item p1; the proposal slots empty; synthetic G-06/H-05, 2026-10-11).
    A proposal event without values takes them; after a hardship, which never carries a figure of its own, a proposal
    event is added when the extractor made none. A dispute lends only a day (an amount on a dispute is the disputed
    figure) and only to a proposal event the extractor did make; a payment claim lends nothing (its day is when they
    paid). Returns the products the reply proposes for."""
    for d in evs:
        if d["kind"] not in LENDERS or (d.get("amount") is None and not d.get("date_text")):
            continue
        if d["kind"] == "dispute" and not d.get("date_text"):
            continue
        carrier = None
        for e in evs:
            if e["kind"] in CARRIER_KINDS and e.get("amount") is None and not e.get("date_text") \
                    and (not e.get("item") or not d.get("item") or e["item"] == d["item"]):
                carrier = e
                break
        if carrier is None:
            if d["kind"] != "hardship":
                continue
            carrier = {"kind": "amount_proposal" if d.get("amount") is not None else "date_proposal", "item": None,
                       "amount": None, "date_text": None, "time_text": None, "text": None, "span": None, "qid": None}
            evs.append(carrier)
        carrier["amount"] = d.get("amount")
        carrier["date_text"] = d.get("date_text")
        carrier["item"] = carrier.get("item") or d.get("item")
        if not carrier.get("text"):
            carrier["text"] = d.get("text")
        d["amount"], d["date_text"] = None, None
        if d["kind"] != "hardship":
            d["item"] = None      # the product named went with the proposal; the claim's own product is unknown
    return set(e["item"] for e in evs if e["kind"] in CARRIER_KINDS and e.get("item"))


def _step(state, events, table, now):
    st = _copy(state) if isinstance(state, dict) and state.get("stage") else new_state((state or {}).get("call") if isinstance(state, dict) else None)
    C = _context(table, now)
    st["rev"] = int(st.get("rev") or 0) + 1
    out = {"engine_next": st["stage"], "say_next": "", "mandatory_lines": [], "readback_text": "", "writes": [],
           "close": None, "what_to_do_next": "", "ask_clarify": False, "unsupported": []}
    evs, malformed = _normalise(events)
    tool_evs = [e for e in evs if e["kind"] == "tool_result"]
    cust = [e for e in evs if e["kind"] != "tool_result"]
    unknown = [e for e in cust if e["kind"] not in EVENT_KINDS]
    cust = [e for e in cust if e["kind"] in EVENT_KINDS]
    _retag(cust)
    proposed_for = _lend_values(cust)
    for e in tool_evs:
        _apply_tool_result(C, st, e)
    if cust:
        st["global"]["turns"] += 1
    g = st["global"]
    verified = st["identity"]["state"] == "verified"
    if cust and not st["closed"]:
        kinds = set(e["kind"] for e in cust)
        # pre-verification terminations
        if not verified and "party_deceased" in kinds and _sit(C, "deceased") is not None:
            _say(C, st, "sorry_loss")
            _trigger(C, st, "deceased")
            C["understood"] = True
            st["stage"] = "close"
            st["pending"] = "close"
        elif not verified and "party_wrong_number" in kinds and _sit(C, "wrong_number") is not None:
            _trigger(C, st, "wrong_number")
            C["understood"] = True
            st["stage"] = "close"
            st["pending"] = "close"
        else:
            # the farewell is judged on the whole reply, before the answer to a pending yes/no question is taken out
            farewell = _end_signal(C, st, cust)
            declined_support = False
            # answers to a pending yes/no offer (support, can-I-help)
            if st.get("pending") == "support_offer":
                # "Yes, please transfer me to them" is extracted as human: that is the yes to the offer of a person, not a
                # new request that gets the can-I-help question (platform EXT-081, 2026-10-11)
                yes = kinds & set(["accept_offer", "confirm", "pay_today_yes", "human"])
                no = kinds & set(["refuse", "deny", "pay_today_no", "dont_want_to_talk", "date_proposal", "amount_proposal", "vague_period", "other"])
                if yes:
                    _support_answer(C, st, True)
                    cust = [e for e in cust if e["kind"] not in ("accept_offer", "confirm", "human")]
                elif no:
                    _support_answer(C, st, False)
                    declined_support = True
                    # the decline closes the hardship path; a plan request in the same breath ("no transfer, but can I get
                    # a discount?") must not turn into the transfer they just declined (platform PUB-05, 2026-10-10)
                    # "I do not want to be transferred" is the answer to the offer, not a wish to end the conversation
                    cust = [e for e in cust if e["kind"] not in ("refuse", "deny", "pay_today_no", "other", "plan_request", "too_much", "dont_want_to_talk")
                            and not (e["kind"] == "amount_proposal" and e.get("amount") is None)
                            and not (e["kind"] == "date_proposal" and not e.get("date_text"))]
            elif st.get("pending") == "hardship_open":
                # the reply to the open line after a declined transfer: a figure or a day is handled as the customer's own
                # proposal (no persuasion follows); anything else ends the hardship path and the items are noted
                g["hardship_open"] = False
                st["pending"] = g.get("resume_pending") or "pay_today"
                C["understood"] = True
                if not (kinds & set(CARRIER_KINDS)) and not (kinds & set(["hardship", "human", "plan_request", "paid", "dispute", "complaint", "question_back", "robot_question", "scam_question"])):
                    cust = [e for e in cust if e["kind"] not in ("refuse", "deny", "pay_today_no", "other", "too_much", "dont_want_to_talk", "accept_offer", "confirm", "vague_period")]
                    farewell = False
            elif st.get("pending") == "can_i_help":
                if "human" in kinds:
                    pass
                else:
                    st["pending"] = g.get("resume_pending") or st.get("pending")
                    C["understood"] = True
                    cust = [e for e in cust if e["kind"] not in ("accept_offer", "confirm", "other", "refuse", "deny")]
            kinds = set(e["kind"] for e in cust)
            if farewell and st["stage"] in SPEAKING_STAGES and not declined_support:
                _end_conversation(C, st)
                cust = [e for e in cust if e["kind"] not in ("other", "dont_want_to_talk")]
                kinds = set(e["kind"] for e in cust)
            if "complaint" in kinds:
                if _handle_complaint(C, st):
                    # a complaint stops collection: nothing else in the reply is acted on (G mail, J amendment 5/8)
                    cust = [e for e in cust if e["kind"] in ("question_back", "robot_question", "scam_question")]
                else:
                    for e in cust:
                        if e["kind"] == "complaint":
                            e["kind"] = "other"
                kinds = set(e["kind"] for e in cust)
            if "hardship" in kinds:
                _handle_hardship(C, st, None, cust)
                # "I lost my job and cannot pay anything" is the hardship, not a refusal to negotiate: the same turn's
                # no / too much / plan request do not note the item as refused or start a transfer (platform PUB-05)
                cust = [e for e in cust if e["kind"] not in ("plan_request", "pay_today_no", "refuse", "too_much", "dont_want_to_talk")
                        and not (e["kind"] == "amount_proposal" and e.get("amount") is None)
                        and not (e["kind"] == "date_proposal" and not e.get("date_text"))]
                kinds = set(e["kind"] for e in cust)
            if "human" in kinds:
                _handle_human(C, st, None)
            elif "plan_request" in kinds and verified:
                _handle_plan_request(C, st, None)
            elif "plan_request" in kinds:
                _line(C, "Say that can be looked at once the security questions are done; continue.")
                C["understood"] = True
            if "dont_want_to_talk" in kinds:
                _handle_dont_want(C, st, None)
            _answer_lines(C, st, cust)
            if (not g["pending_transfer"] or g.get("transfer_keeps_promises")) and not g.get("dont_want_closed"):
                if verified and st["stage"] in ("negotiate", "readback"):
                    for e in cust:
                        if e["kind"] == "paid":
                            _handle_paid_or_dispute(C, st, "paid", e, exclude=proposed_for)
                        elif e["kind"] == "dispute":
                            _handle_paid_or_dispute(C, st, "dispute", e, exclude=proposed_for)
                    if not g["paid_claim"] and not g["dispute"]:
                        if st.get("pending") == "exact_day" and not (kinds & (set(CARRIER_KINDS) | set(["refuse", "deny", "too_much", "pay_today_no", "pay_today_yes", "confirm"]))):
                            # "I do not know exactly" after the one question for the exact day, extracted as other: still
                            # no day, the vague rule's second step follows (synthetic C-03, 2026-10-11)
                            for e in cust:
                                if e["kind"] == "other" and not e.get("date_text") and e.get("amount") is None:
                                    e["kind"] = "vague_period"
                        _negotiate_events(C, st, [e for e in cust if e["kind"] not in ("paid", "dispute", "hardship", "complaint", "human", "plan_request", "dont_want_to_talk", "robot_question", "scam_question", "question_back", "other")])
                elif st["stage"] == "party":
                    _party_events(C, st, [e for e in cust if e["kind"] not in ("human", "hardship", "dont_want_to_talk")])
                elif st["stage"] == "callback":
                    if "party_confirmed" in kinds and "callback_offer" not in kinds:
                        # the customer comes to the phone after all ("Fine, yes, this is Victor Ionescu" after a first
                        # answer taken as someone else, platform EXT-138, 2026-10-11): the security questions follow
                        st["party"] = "customer"
                        st["stage"] = "identity"
                        st["pending"] = "identity"
                        C["understood"] = True
                    else:
                        _callback_events(C, st, [e for e in cust if e["kind"] == "callback_offer"])
                elif st["stage"] == "identity":
                    _identity_events(C, st, [e for e in cust if e["kind"] in ("id_answer", "id_decline")])
                elif verified and st["stage"] in ("record", "end", "close", "note", "transfer"):
                    for e in cust:
                        if e["kind"] in ("change", "deny", "refuse") and any(it["recorded"] for it in st["items"]):
                            _say(C, st, "change_in_app")
                            C["understood"] = True
    if (unknown or malformed) and not C["understood"]:
        out["ask_clarify"] = True
    if not st["closed"] and any(t in TERMINAL_TRIGGERS for t in g["triggers"]):
        st["stage"] = "close"
        st["pending"] = "close"
    if st["identity"]["state"] == "verified" and st["stage"] in ("negotiate", "readback", "record", "transfer", "note", "close") and not st["closed"]:
        if st.get("pending") not in ("support_offer", "can_i_help", "close"):
            _advance(C, st)
    elif g["pending_transfer"] and not g["transfer_done"] and not st["closed"]:
        st["stage"] = "transfer"
        st["pending"] = "transfer"
    if C.get("question_now") and not st["closed"] and st["stage"] not in ("transfer", "close", "note"):
        # a yes/no question asked in this bundle stays pending even when a proposal in the same bundle made progress
        if st.get("pending") != C["question_now"]:
            g["resume_pending"] = st.get("pending")
            st["pending"] = C["question_now"]
    if st.get("pending") == "close" and st["stage"] not in ("close", "note"):
        st["stage"] = "close"
    _render(C, st, out)
    if out["engine_next"] in SPEAKING_STAGES and not out["writes"] and not C["lines"] and not C["mandatory"] and not out.get("readback_text"):
        # never silent: with nothing from the engine the dialogue model invents the rest of the call (a platform run
        # said "I have processed the payment", 2026-10-10); the pending question is the content. Not on a turn that
        # issues a write: "Schedule the callback, then close" was buffered and read out as a booking (C-02, 2026-10-11)
        if not out.get("what_to_do_next"):
            out["what_to_do_next"] = "Ask the customer to repeat what they said."
            out["ask_clarify"] = True
        _line(C, out["what_to_do_next"])
    if C.get("aside") and out["engine_next"] in SPEAKING_STAGES and not st["closed"]:
        out["what_to_do_next"] = (out.get("what_to_do_next") or "").rstrip() + ASIDE_NOTE
    out["mandatory_lines"] = list(C["mandatory"])
    out["say_next"] = " ".join(C["lines"])
    if cust and not C["understood"] and not tool_evs:
        out["ask_clarify"] = True
        if not out["what_to_do_next"]:
            out["what_to_do_next"] = "Ask the customer to repeat or clarify."
    for m in C["missing"]:
        # every parameter the engine needed and the table did not give (absent or not_specified) is reported
        if m not in st["unsupported"]:
            st["unsupported"].append(m)
    out["unsupported"] = list(st["unsupported"])
    return st, out


def step(state, events, table, now):
    """Apply one observation bundle. Returns (new_state, outputs). Pure; never raises."""
    try:
        return _step(state, events, table, now)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise"
        if DEBUG_RAISE:
            raise
        st = _copy(state) if isinstance(state, dict) and state.get("stage") else new_state()
        stage = st.get("stage") or "party"
        out = {"engine_next": stage if stage in SPEAKING_STAGES else "clarify",
               "say_next": "Ask the customer to repeat what they said.",
               "mandatory_lines": [], "readback_text": "", "writes": [], "close": None,
               "what_to_do_next": "Ask the customer to repeat; the engine could not apply the last reply.",
               "ask_clarify": True, "unsupported": list(st.get("unsupported") or []) + ["engine_error:" + type(exc).__name__]}
        return st, out
