"""Tested node fragments of the phone-agent workflow (research/builder-architecture.md section 2.1).

Every function returns a `Fragment`: the nodes it owns (in the platform's exact JSON shape, transitions inside the
nodes), the transitions the engine code node needs to reach it (`routes`), and the tool definitions it uses. Tool
definitions are generated from the parsed tool API file (builder/readers/api_file.py), never typed by hand.

Runtime contract (one call turn):

    conversation node S / S_wait --(any extraction slot set)--> S_observe (code: snapshot + clear, engine_events)
        --> engine (code: engine snippet + emitter epilogue) --(engine_next + flags)--> one of
            S (llm entry: head line, content, tail line); S_say (tts) -> S_wait (silent) is emitted but never
            routed: on the platform a tts code node that passes through to a silent conversation node ends the turn
            at the code node, and the next customer message re-runs the passthrough and hangs the chat (measured
            2026-10-10, version 4)
            w_<tool> (baked api_request) -> write_result (code: tool_result event) -> engine
            close_<outcome>_<reason> (baked close_call, tts goodbye) -> write_result -> engine -> end

The epilogue appended to the engine snippet turns the engine outputs into speech and routing variables:
`say_head_line` (verbatim sentences the engine produced before its first content instruction, spoken word for
word by the model at the start of its message), `say_content` (what the dialogue model must convey in its own
words), `say_tail_line` (verbatim sentences that follow content, spoken word for word by the model), `say_tts`
(always "" now, kept for the S_say route), `close_text`, `speech_buf` (lines produced during writes,
carried to the next speaking node), `write_tool` / `wa_<tool>__<field>` (the first due write, baked into its
node), `last_stage`.
"""
from __future__ import annotations

import json
import re
import urllib.parse


# --------------------------------------------------------------------------------------------------------------
# vocabulary shared with the engine (builder/engine/step.py)

SPEAKING = ("party", "callback", "identity", "negotiate", "readback")
STAGE_NODE = {"party": "greeting", "callback": "callback", "identity": "identity", "negotiate": "negotiate",
              "readback": "readback"}
# the engine's canonical write tools, the engine_next stage that issues each, and the argument keys it sends
WRITE_STAGE = {"verify_identity": "verify", "get_account": "fetch", "create_promise": "record",
               "transfer_to_agent": "transfer", "add_note": "note", "schedule_callback": "callback"}
ENGINE_ARGS = {"verify_identity": ["field", "answer"], "get_account": [], "create_promise": ["product_id", "amount", "date"],
               "add_note": ["product_id", "reason"], "schedule_callback": ["date", "time", "reason"], "transfer_to_agent": ["queue"],
               "close_call": ["outcome", "reason"]}
CLOSE_TOOL = "close_call"
ENGINE_MARKER = "Freya call engine, rendered by builder/engine/snippet.py"

COMMON_KINDS = ["question_back", "robot_question", "scam_question", "human", "hardship", "complaint", "dont_want_to_talk", "other"]
STAGE_KINDS = {
    "party": ["party_confirmed", "party_other", "party_wrong_number", "party_deceased", "callback_offer"] + COMMON_KINDS,
    "callback": ["callback_offer", "party_confirmed", "party_wrong_number", "party_deceased"] + COMMON_KINDS,
    "identity": ["id_answer", "id_decline"] + COMMON_KINDS,
    "negotiate": ["pay_today_yes", "pay_today_no", "date_proposal", "amount_proposal", "too_much", "refuse", "accept_offer",
                  "vague_period", "confirm", "deny", "change", "paid", "dispute", "plan_request"] + COMMON_KINDS,
    "readback": ["confirm", "deny", "change", "date_proposal", "amount_proposal", "accept_offer", "refuse", "paid", "dispute",
                 "plan_request"] + COMMON_KINDS,
}
# extraction fields per stage: reply (event kind), item, amount, date (words), time (words), words (own words)
STAGE_FIELDS = {"party": ["reply", "date", "time", "words"], "callback": ["reply", "date", "time", "words"],
                "identity": ["reply", "words"], "negotiate": ["reply", "item", "amount", "date", "words"],
                "readback": ["reply", "item", "amount", "date", "words"]}

KIND_HELP = {
    "party_confirmed": "the person confirms they are the customer asked for. Only these count: {confirm_words}. "
                       "'Hello?', 'go ahead', 'okay', 'yes?' as a prompt to continue are not confirmations: other",
    "party_other": "the person says they are someone else (a relative, a colleague, anyone who is not the customer)",
    "party_wrong_number": "the person says this number does not belong to the customer",
    "party_deceased": "the person says the customer has died",
    "callback_offer": "the person says when the customer can be reached (day words in date, time words in time)",
    "id_answer": "an answer, complete or partial, to the security question just asked (exact words in words)",
    "id_decline": "refuses to answer the security question{decline_extra}",
    "pay_today_yes": "yes to doing it today",
    "pay_today_no": "no to doing it today",
    "date_proposal": "names a day (their words for the day in date)",
    "amount_proposal": "names an amount they can manage (digits in amount, day words in date if a day is named too); "
                       "asking for a discount or a lower total names no amount and is 'other'",
    "too_much": "says the amount is too much for them",
    "refuse": "refuses the proposal, or gives a non-answer such as 'I will have to see'",
    "accept_offer": "accepts the proposal that was just made",
    "vague_period": "gives only a vague time such as next week, the end of the month, when the salary comes",
    "confirm": "says yes to the read-back or to a yes or no question",
    "deny": "says no to the read-back",
    "change": "changes the amount or the day of something already agreed",
    "paid": "says they paid recently (today, yesterday, this week) and it may not show yet",
    "dispute": "says it is not theirs, they never had the product, or it was closed or paid off in the past",
    "plan_request": "asks to split the amount or to spread it over months (a discount, waiver or lower total is not a plan: 'other')",
    "question_back": "asks a question back (who is calling, why, what it is about)",
    "robot_question": "asks whether you are a robot or an AI",
    "scam_question": "asks whether this is a scam",
    "human": "asks to speak to a person",
    "hardship": "mentions a hardship: illness, a death in the family, job loss",
    "complaint": "says they want to make a complaint or are going to complain, or asks how to complain",
    "dont_want_to_talk": "says they do not want to talk",
    "do_not_call": "asks not to be called again or to stop the calls",
    "other": "anything else, including small talk, greetings and unclear replies",
}
# a kind whose meaning differs in one stage: in the callback stage the person on the line was taken for someone else,
# so a confirmation is them saying they are the customer after all, by name; a plain yes to the callback question is not
KIND_HELP_STAGE = {
    ("callback", "party_confirmed"): "the person now says that they themselves are the customer asked for, by their own "
                                     "name or 'that's me', 'speaking'; a plain yes or okay to the callback question is not this",
}

ENTRY_PROMPT = ("{{say_head_line}}\nConvey all of this content to the customer now: {{say_content}}\n"
                "Directions such as ignore an aside or continue are silent instructions, never customer-facing sentences. "
                "When the content names a security field, ask the customer for it; never supply or guess its value. "
                "Preserve each supplied product's details and requested sentence structure. Use concise sentences; "
                "do not combine separate product statements into a total. Instructions about reporting events or "
                "waiting for a reply are for you, not words to say to the customer.\n"
                "{{say_tail_line}}\nDo not add anything else and do not call any tool.")
HEAD_PREFIX = "Start your message with exactly these words:"
# The close node has no model turn: its tts can only speak sentences. The engine's content lines are instructions for
# a model; these are the ones that can come up at a close, by the engine's phrase id (the table's wording of a non-exact
# phrase varies by brief), as the sentence the tts says instead. Any other instruction is dropped there (the goodbye is
# always said).
CLOSE_SPOKEN = {
    "thanks_goodbye": "Thank you, goodbye.",
    "could_not_record": "I could not record the promise because of a technical problem.",
    "promise_recorded": "The promise is recorded.",
    "text_message": "You will receive a text message confirming the promise.",
    "rest_overdue": "The rest stays overdue.",
    "paid_takes_day": "Payments can take one business day to appear.",
    "change_in_app": "A recorded promise cannot be changed in this call; it can be changed in the mobile app.",
    "sympathy": "I am sorry to hear that.",
    "no_information": "I do not have that information.",
    "use_app_or_branch": "I could not verify your identity, so I cannot go further on this call.",
    "system_unavailable": "I am sorry, the system is unavailable right now.",
    "request_noted": "Your request has been noted.",
}
# content phrases whose table wording is spoken at the close when it is a sentence (the table's own words for where an
# unverified customer should turn, "Please call the number on your statement.", not another brief's app-or-branch
# advice: synthetic G-03/H-02/J-05, 2026-10-11); an instruction-shaped wording ("confirm the promise is in place") keeps
# the generic sentence above
CLOSE_FROM_TABLE = ("use_app_or_branch", "promise_recorded", "text_message", "rest_overdue", "paid_takes_day", "change_in_app",
                    "could_not_record", "no_information", "system_unavailable", "request_noted")
INSTRUCTION_START_RE = re.compile(r"^(say|tell|ask|offer|explain|state|mention|confirm|acknowledge|one (short )?sentence|"
                                  r"the (customer|caller) (is|was) told)\b", re.I)


def _as_sentence(text):
    """A table phrase written for the customer, as a sentence the tts can say: "the customer can visit a branch with
    identification" -> "You can visit a branch with identification."; "call the number on their statement" ->
    "Call the number on your statement."."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip()
    if not t:
        return ""
    t = re.sub(r"^(the customer|the caller|they)\s+(can|should|may|must|will|could)\s+", lambda m: "You " + m.group(2) + " ", t, flags=re.I)
    t = re.sub(r"\btheir\b", "your", t)
    t = re.sub(r"\bthemselves\b", "yourself", t)
    t = re.sub(r"\bthem\b", "you", t)
    t = t[0].upper() + t[1:]
    if t[-1] not in ".!?":
        t += "."
    return t


def close_spoken_for(table):
    """CLOSE_SPOKEN with the table's own sentence wherever it has one for a phrase the close may speak."""
    out = dict(CLOSE_SPOKEN)
    for ph in (table or {}).get("phrases") or []:
        if not isinstance(ph, dict) or ph.get("kind") != "mandatory" or ph.get("exact"):
            continue
        pid, text = ph.get("id"), str(ph.get("text") or "").strip()
        if pid not in CLOSE_FROM_TABLE or not text or "{" in text or INSTRUCTION_START_RE.match(text):
            continue
        sentence = _as_sentence(text)
        if sentence:
            out[pid] = sentence
    return out


TAIL_PREFIX = "Finish your message with exactly these words:"
GOODBYE = "Thank you, goodbye."
REPEAT = "Ask the customer to repeat what they said."

STAGE_TASK = {
    "party": ("STEP: find out whether the person on the line is {{title}} {{last_name}}. Nobody is verified yet. "
              "Say nothing about why you are calling or about any account, to anyone. You may always say who you are "
              "using the organisation and role from your opening when asked; that is not account information. Only the person's own "
              "confirmation counts. If confirmation is still missing, repeat the supplied name question; never "
              "announce account access or ask the person why they called."),
    "callback": ("STEP: someone other than {{title}} {{last_name}} answered. Do not say why you are calling and ask them "
                 "no security questions. If they ask what the call is about, say only that it is a personal matter you can "
                 "discuss with {{title}} {{last_name}} alone: no overview, no hint, no 'limited information'. Deal with "
                 "nobody else about the matter, whatever they offer. Find out when {{title}} {{last_name}} can be reached: a day "
                 "and a time."),
    "identity": ("STEP: security questions. The person said they are {{title}} {{last_name}} but is not verified yet. "
                 "Ask only the question in the instruction, one at a time, and never answer it for them. Say nothing "
                 "about why you are calling or about any account until the questions are done."),
    "negotiate": ("STEP: the customer is verified and you are discussing the overdue amount. Propose only the amount and "
                  "the day the instruction gives. Never invent an amount, a day, a reduction or an arrangement, and "
                  "never ask the customer to name an amount. Never say that you are transferring or connecting the "
                  "customer, or that a payment is being taken or processed: a transfer happens only when the "
                  "instruction says it does, and a question in the instruction is asked, not acted on."),
    "readback": ("STEP: read-back. The agreed amount and day were read to the customer. Wait for a clear yes; if they "
                 "want to change something, listen. Never say anything is done before the instruction says so."),
}
TASK_TAIL = ("\n\nCurrent instruction: {{what_to_do_next}}\n"
             "Ask the question the instruction specifies. A request to ask whether you can help means asking about "
             "your own help, not offering a transfer. If a question remains open, continue with it; do not say goodbye "
             "unless the instruction ends the call.\n"
             "Speak only what the instruction asks. No tool call is allowed in this turn.")

SYSTEM_PROMPT = (
    "You are {label} of {org} on an outbound phone call. Speak English. Address the customer as {address}. "
    "Use concise sentences, preserving all content and sentence structure required by the current step, "
    "and ask one question at a time.\n"
    "Rules for every step:\n"
    "- What to say is decided for you in the current step. Never decide amounts, days, outcomes or next steps yourself.\n"
    "- Never claim that something was done in the bank's systems unless your current step says it was. You cannot take "
    "money or process anything: never say money was taken or processed, never ask for banking details. The bank only "
    "records when the customer will pay.\n"
    "- Never offer a reduction, a waiver, an arrangement or any term your current step does not give you.\n"
    "- If asked something your step does not answer, say you do not have that information.\n"
    "- Say amounts exactly as the step gives them; never add a currency the step does not name.\n"
    "- No tool call is allowed. Never end a turn with nothing.")


class EmitError(ValueError):
    """A table or tool API file the emitter cannot compile. Never silently worked around."""


# --------------------------------------------------------------------------------------------------------------
# fragment container


class Fragment:
    def __init__(self, nodes=None, routes=None, tools=None):
        self.nodes = dict(nodes or {})
        self.routes = list(routes or [])   # transitions of the engine node into this fragment, in priority order
        self.tools = list(tools or [])     # tool definitions used (for the report)


def always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def leaf(var, op, operand=None):
    c = {"variable": var, "operator": op}
    if operand is not None:
        c["operand"] = operand
    return c


def when_all(target, description, leaves):
    """A variable transition: AND of `leaves` nested in the top-level OR group (workflow-format.md)."""
    group = leaves[0] if len(leaves) == 1 else {"logic": "and", "conditions": list(leaves)}
    return {"target_node": target, "description": description, "condition": {"logic": "or", "conditions": [group]}}


def when_any(target, description, groups):
    """OR of AND groups."""
    conds = [g[0] if len(g) == 1 else {"logic": "and", "conditions": list(g)} for g in groups]
    return {"target_node": target, "description": description, "condition": {"logic": "or", "conditions": conds}}


def filled(var):
    """`var` holds a fresh value: set and not the cleared "" (robust to both is_set semantics)."""
    return [leaf(var, "is_set"), leaf(var, "not_equals", "")]


def code_action(code):
    if "{{" in code or "}}" in code:
        raise EmitError("code node source contains '{{' or '}}'")
    compile(code, "<fragment>", "exec")
    return {"type": "function",
            "function": {"name": "code_exec", "handler": "__function__:code_exec",
                         "parameters": {"type": "object", "properties": {
                             "code": {"type": "string", "default": code},
                             "timeout_ms": {"type": "number", "default": 20000}}}}}


def code_node(name, code, transitions, on_enter=None):
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": transitions[-1]["target_node"],
            "on_enter": on_enter or {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [code_action(code)], "transitions": transitions}


def py(value):
    """A Python expression for a baked constant: hex-encoded JSON, so no brace sequence can appear and no module
    beyond json is needed (json, re and datetime are the only modules verified in the platform sandbox)."""
    return "json.loads(bytes.fromhex(" + repr(json.dumps(value, sort_keys=True).encode().hex()) + ").decode('utf-8'))"


# The engine snippet decodes its table with `base64`, which is not among the modules verified in the sandbox
# (json, re, datetime). The engine node replaces that import with this pure-Python stand-in.
BASE64_SHIM = '''class base64:
    """Stand-in for the base64 module (decode only), inserted by builder/emitter/fragments.py."""
    @staticmethod
    def b64decode(s):
        if isinstance(s, (bytes, bytearray)):
            s = bytes(s).decode('ascii')
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        rev = dict((c, i) for i, c in enumerate(alphabet))
        out = bytearray()
        bits, n = 0, 0
        for ch in s:
            if ch == '=':
                break
            if ch not in rev:
                continue
            bits = ((bits << 6) | rev[ch]) & 0xFFFFFF
            n += 6
            if n >= 8:
                n -= 8
                out.append((bits >> n) & 0xFF)
        return bytes(out)
'''


# --------------------------------------------------------------------------------------------------------------
# tools from the API file

RESULT_HOOK = '''try:
    import json
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        ok = None
        if isinstance(d, dict) and 'ok' in d:
            ok = d.get('ok')
            if isinstance(ok, str):
                ok = ok.strip().lower() == 'true'
        if result.get('status') == 'success' and ok is True:
            cls = 'ok'
        elif ok is not None:
            cls = 'failed'
        else:
            cls = 'unknown'
        body = d if isinstance(d, dict) else dict()
        rec = json.dumps(dict(result=cls, data=body))
        vars['wr_json'] = rec
        if isinstance(d, dict):
            d['engine_result'] = rec
        else:
            result['data'] = dict(engine_result=rec)
except Exception:
    pass
'''


def tool_url(ctx, tool):
    return ctx.base_url.rstrip("/") + ctx.api["tools"][tool]["path"]


def api_tool(ctx, tool, body_defaults, description):
    """One `api_call` tool function for `tool`, its body leaves taken from the API request schema.
    `body_defaults` maps API field -> default (a literal or one placeholder). Required API fields without a default
    are a loud error; fields that are not top-level leaves of the request schema are refused."""
    spec = ctx.api["tools"].get(tool)
    if spec is None:
        raise EmitError("the tool API file has no tool %r" % tool)
    fields = spec["request_fields"]
    props = {}
    for f, default in body_defaults.items():
        if f not in fields or "." in f or "[]" in f:
            raise EmitError("%s: body field %r is not in the API request schema" % (tool, f))
        e = fields[f]
        lf = {"type": e.get("type") or "string", "default": default}
        if e.get("enum"):
            lf["enum"] = list(e["enum"])
            if not PLACEHOLDER.fullmatch(str(default)) and default not in e["enum"]:
                raise EmitError("%s.%s: %r is not in the API enum %r" % (tool, f, default, e["enum"]))
        if e.get("description"):
            lf["description"] = e["description"]
        props[f] = lf
    missing = [f for f, e in fields.items() if e.get("required") and "." not in f and f not in props]
    for f in list(missing):
        from builder.emitter.wire import required_default
        val = required_default(tool, f, fields[f])
        if val is not None:
            lf = {"type": fields[f].get("type") or "string", "default": val}
            if fields[f].get("enum"):
                lf["enum"] = list(fields[f]["enum"])
            if fields[f].get("description"):
                lf["description"] = fields[f]["description"]
            props[f] = lf
            missing.remove(f)
    if missing:
        raise EmitError("%s: required API fields without a source: %s" % (tool, missing))
    return {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
            "function": {"name": tool, "handler": "__function__:api_call", "description": description,
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": tool_url(ctx, tool)},
                             "method": {"type": "string", "default": spec["method"]},
                             "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                             "body": {"type": "object", "properties": props, "required": [f for f in props if fields[f].get("required")]}}}},
            "post_process_code": RESULT_HOOK}


PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w.\-]*)\s*\}\}")


def write_var(tool, field):
    return "wa_%s__%s" % (tool, field)


def call_var_defaults(ctx, tool):
    """Body fields filled from call variables: any request field named like a call variable, and the API's customer id
    field (client_ref, account_no, ...) from the customer_id call variable."""
    fields = ctx.api["tools"][tool]["request_fields"]
    out = {f: "{{%s}}" % f for f in fields if f in ctx.call_vars}
    cid = getattr(ctx, "cid_field", "customer_id")
    if cid in fields and cid not in out and "customer_id" in ctx.call_vars:
        out[cid] = "{{customer_id}}"
    return out


def engine_write_defaults(ctx, tool):
    """Body defaults of an engine-run write: call variables plus one `wa_<tool>__<field>` per engine argument."""
    fields = ctx.api["tools"][tool]["request_fields"]
    out = call_var_defaults(ctx, tool)
    for key in ENGINE_ARGS[tool]:
        wire = ctx.field_map.get(tool, {}).get(key, key)
        if wire == "":
            continue   # this API has no such field (one-question verify_identity without a question field)
        if wire not in fields:
            raise EmitError("%s: the engine sends %r but the API request schema has no field %r" % (tool, key, wire))
        out[wire] = "{{%s}}" % write_var(tool, wire)
    return out


# --------------------------------------------------------------------------------------------------------------
# fragments

def setup(ctx, first):
    """Silent initial code node: every observation slot, speech and write variable starts as "" (idempotent)."""
    names = []
    for stage in ctx.stages:
        names += slot_vars(ctx, stage)
    names += ["say_tts", "say_head_line", "say_content", "say_tail_line", "close_text", "write_tool", "write_item", "write_args",
              "wr_json", "wr_body", "engine_events"]
    for tool in ctx.write_tools:
        for key in ENGINE_ARGS[tool]:
            wire = ctx.field_map.get(tool, {}).get(key, key)
            if wire:
                names.append(write_var(tool, wire))
    lines = ["vars[%r] = ''" % n for n in names]
    lines += ["vars['speech_buf'] = '[]'", "vars['last_stage'] = %r" % first]
    cid = getattr(ctx, "cid_field", "customer_id")
    if cid != "customer_id":
        # the API calls the customer id client_ref / account_no / ...: whichever name the call variables carry, both are set
        # whichever name the call variables bring, both carry the real id; a sample value ("test", "c_test") never wins
        lines += ["_ids = [x for x in (vars.get('customer_id'), vars.get(%r)) if x and str(x) not in ('test', 'c_test')]" % cid,
                  "vars['customer_id'] = _ids[0] if _ids else (vars.get('customer_id') or vars.get(%r) or '')" % cid,
                  "vars[%r] = vars['customer_id']" % cid]
    code = "try:\n" + "\n".join("    " + ln for ln in lines) + "\nexcept Exception:\n    pass\n"
    return Fragment({"setup": code_node("setup", code, [always("engine")])})


def slot_count(ctx, stage):
    if stage in ("negotiate", "readback"):
        return max(3, ctx.max_items + 1)
    return 2


def slot_vars(ctx, stage):
    node = STAGE_NODE[stage]
    return ["%s_%s%d" % (node, f, k) for k in range(1, slot_count(ctx, stage) + 1) for f in STAGE_FIELDS[stage]] + [node + "_raw"]


def stage_kinds(ctx, stage):
    """The event kinds a stage extracts: STAGE_KINDS plus `do_not_call` when the table has such a situation (the
    engine ends the call on the first request with the entry's note and close pair)."""
    kinds = list(STAGE_KINDS[stage])
    if getattr(ctx, "do_not_call", None):
        kinds.insert(kinds.index("other"), "do_not_call")
    return kinds


def extraction_schema(ctx, stage):
    kinds = stage_kinds(ctx, stage)
    help_lines = []
    for k in kinds:
        text = KIND_HELP_STAGE.get((stage, k), KIND_HELP[k]).format(confirm_words=ctx.confirm_words, decline_extra=ctx.decline_extra)
        help_lines.append("%s: %s" % (k, text))
    node = STAGE_NODE[stage]
    out = []
    for k in range(1, slot_count(ctx, stage) + 1):
        first = k == 1
        for f in STAGE_FIELDS[stage]:
            name = "%s_%s%d" % (node, f, k)
            if f == "reply":
                desc = ("What the customer's last message does. One of:\n" + "\n".join(help_lines)) if first else \
                       ("Only when the same last message also does another thing, not already in %s_reply%d: one more value "
                        "from the same list. Empty otherwise." % (node, k - 1))
                # "" is in the enum so the dispatcher's clearing write (vars[name] = '') passes the platform's schema
                # validation; the transitions test `not_equals ""`, so a cleared slot never fires a route.
                out.append({"name": name, "type": "string", "enum_values": list(kinds) + [""], "description": desc, "min_confidence": 0.5})
            elif f == "item":
                out.append({"name": name, "type": "string", "min_confidence": 0.5,
                            "description": "For %s_reply%d: the customer's words for the one product it is about (for example "
                                           "'the card', 'the car loan'). Empty when it is about everything." % (node, k)})
            elif f == "amount":
                out.append({"name": name, "type": "string", "min_confidence": 0.5,
                            "description": "For %s_reply%d: the amount the customer names, in digits (for example 400 or "
                                           "125.99). Empty when no amount is named." % (node, k)})
            elif f == "date":
                out.append({"name": name, "type": "string", "min_confidence": 0.5,
                            "description": "For %s_reply%d: the customer's own words for the day, unchanged (for example "
                                           "'next Friday', 'the 16th', 'tomorrow'). Do not convert. Empty if none." % (node, k)})
            elif f == "time":
                out.append({"name": name, "type": "string", "min_confidence": 0.5,
                            "description": "For %s_reply%d: the customer's own words for the time, unchanged (for example "
                                           "'around eleven'). Empty if none." % (node, k)})
            elif f == "words":
                # no confidence floor: an answer with its words left out costs a whole turn (the engine must ask again),
                # and the platform's extractor sometimes left them out for a two-part message (EXT-027, 2026-10-10)
                out.append({"name": name, "type": "string", "min_confidence": 0.0,
                            "description": ("For %s_reply%d: the customer's exact words for this part of the reply. For an "
                                            "answer to a security question, everything they said as the answer, unchanged; "
                                            "never leave it empty when the reply is an answer." % (node, k))})
    # the whole message, as a second chance when the extractor leaves a slot's words empty (seen on the platform for
    # "8864. How much do I owe?": reply filled, words empty, the answer never reached the bank)
    out.append({"name": node + "_raw", "type": "string", "min_confidence": 0.0,
                "description": "The customer's entire last message, word for word, unchanged."})
    return out


DISPATCH = '''import json
_KINDS = __KINDS__
_SLOTS = __SLOTS__


def _ob_val(name):
    if not name:
        return ''
    x = vars.get(name)
    if x is None:
        return ''
    s = str(x).strip()
    if s.lower() in ('none', 'null', 'nan'):
        return ''
    return s


def _ob_item(words):
    """A product id from the customer's words for a product, matched against the engine's items."""
    if not words:
        return None
    try:
        st = json.loads(vars.get('engine_state') or '')
        items = st.get('items') or []
    except Exception:
        items = []
    low = words.lower()
    best, best_score, tie = None, 0, False
    for it in items:
        pid = str(it.get('item_id') or '')
        if pid and pid.lower() == low:
            return pid
        p = it.get('product') or dict()
        score = 0
        last4 = str(p.get('card_last4') or '')
        if last4 and last4 in low:
            score += 10
        for tok in str(p.get('type') or '').lower().split('_'):
            if tok and tok in low:
                score += 1
        if score > best_score:
            best, best_score, tie = pid, score, False
        elif score == best_score and score > 0:
            tie = True
    if best is not None and not tie:
        return best
    # no product matched ("the full amount", "it"): no item, so the engine applies the event to the current or to all
    # open items. Handing the words through as an item id made the engine drop the event (platform EXT-006, 2026-10-10).
    return None


_FIELDS = ('words', 'amount', 'date', 'time', 'item')
_RAW = __RAW__

try:
    vals = [dict((f, _ob_val(s.get(f))) for f in _FIELDS) for s in _SLOTS]
    kinds = [_ob_val(s.get('reply')) for s in _SLOTS]
    n = len(_SLOTS)
    # two products in one reply (seen on the platform 2026-10-11, B EXT-124/127): the extractor filled a value slot per
    # product but the reply slots positionally, so one reply slot carries the words of another reply while the slot with
    # its own words has no reply. A reply slot whose words duplicate another reply slot's words gets the orphan's values;
    # an orphan whose words duplicate a reply slot's words is a second product of that reply.
    extra = []
    for j in range(n):
        if kinds[j] or not any(vals[j][f] for f in _FIELDS):
            continue
        wj = vals[j]['words']
        if not wj:
            continue
        if any(kinds[i] and vals[i]['words'] == wj for i in range(n)):
            continue
        twins = [i for i in range(n) if kinds[i] and vals[i]['words'] and
                 any(k != i and kinds[k] and vals[k]['words'] == vals[i]['words'] for k in range(n))]
        if twins:
            k = twins[-1]
            vals[k], vals[j] = vals[j], vals[k]
    for j in range(n):
        if kinds[j] or not vals[j]['words']:
            continue
        for i in range(n):
            if kinds[i] and vals[i]['words'] == vals[j]['words'] and any(vals[j][f] != vals[i][f] for f in ('item', 'amount', 'date')):
                extra.append((kinds[i], dict(vals[j])))
                vals[j] = dict((f, '') for f in _FIELDS)
                break
    # the extractor sometimes files the value of the one reply under another slot (seen on the platform 2026-10-10:
    # identity_reply1 = id_answer with identity_words2 = 4471): a slot with a reply and no value adopts the value of
    # a slot without a reply
    for f in _FIELDS:
        for i in range(n):
            if kinds[i] and not vals[i][f]:
                for j in range(n):
                    if not kinds[j] and vals[j][f]:
                        vals[i][f], vals[j][f] = vals[j][f], ''
                        break
    # a security answer whose words were filed under the aside said with it (identity_reply1 = id_answer without words,
    # identity_reply2 = other with words "four seven one one"; synthetic G-02/H-06, 2026-10-11): the answer takes those
    # words, else the whole message. The parser and the bank decide whether they hold the answer; without words the
    # question is asked again and a talkative customer never repeats the digits.
    for i in range(n):
        if kinds[i] == 'id_answer' and not vals[i]['words']:
            for j in range(n):
                if j != i and kinds[j] in ('other', 'question_back', 'robot_question', 'scam_question') and vals[j]['words']:
                    vals[i]['words'] = vals[j]['words']
                    break
            if not vals[i]['words']:
                vals[i]['words'] = _ob_val(_RAW)
    evs = []
    for kind, v in [(kinds[i], vals[i]) for i in range(n)] + extra:
        if not kind:
            continue
        if kind not in _KINDS:
            kind = 'other'
        amount = None
        # digits only: the extractor has written a full-width comma in front of an amount (platform 2026-10-11)
        a = ''.join(ch for ch in v['amount'] if ch.isdigit() or ch in '.,-').replace(',', '')
        if a:
            try:
                amount = float(a)
            except ValueError:
                amount = None
        words = v['words'] or None
        if words is None and sum(1 for x in kinds if x) == 1 and not extra and not v['amount'] and not v['date'] and not v['time']:
            words = _ob_val(_RAW) or None   # the one reply of the turn with nothing attached: its words are the whole message
        if a and amount is None and not words:
            words = a
        ev = dict(kind=kind, item=_ob_item(v['item']), amount=amount,
                  date_text=v['date'] or None, time_text=v['time'] or None,
                  text=words, span=None, qid=None)
        evs.append(ev)
    vars['engine_events'] = json.dumps(evs)
except Exception:
    vars['engine_events'] = json.dumps([dict(kind='other')])
'''


def observe(ctx, stage):
    """The one observation dispatcher of a stage: snapshot every slot, build engine_events, clear every slot."""
    node = STAGE_NODE[stage]
    slots = []
    for k in range(1, slot_count(ctx, stage) + 1):
        slots.append({f: "%s_%s%d" % (node, f, k) for f in STAGE_FIELDS[stage]})
    names = slot_vars(ctx, stage)
    code = (DISPATCH.replace("__KINDS__", py(stage_kinds(ctx, stage))).replace("__SLOTS__", py(slots))
            .replace("__RAW__", py(node + "_raw")))
    code = code + "".join("vars[%r] = ''\n" % n for n in names)
    name = node + "_observe"
    return Fragment({name: code_node(name, code, [always("engine")])})


def speech_rules(ctx):
    """Unconditional call-wide communication requirements supplied by the reader."""
    lines = []
    for obligation in ctx.table.get("obligations") or []:
        when = obligation.get("when") or {}
        if (obligation.get("status") != "effective" or obligation.get("kind") != "communication"
                or obligation.get("scope") != "call" or when.get("state") != "any"
                or when.get("guards") or when.get("event") or when.get("stage_id")):
            continue
        for action in obligation.get("then") or []:
            say = action.get("say")
            if isinstance(say, dict) and isinstance(say.get("content"), str):
                lines.append(say["content"])
            if isinstance(action.get("forbid"), str):
                lines.append("Do not: " + action["forbid"])
    if not lines:
        return ""
    text = "\nCall-wide speech requirements (apply to the supplied content; do not recite these instructions):\n" + "\n".join(lines)
    for name in ctx.call_vars:
        text = re.sub(r"(?<!\{)\{" + re.escape(name) + r"\}(?!\})", lambda m: "{" + m[0] + "}", text)
    return text


def speaking_stage(ctx, stage):
    """S_say (tts of the verbatim lines), S (llm entry with the content) and S_wait (silent), all listening on the
    same extraction schema, plus the stage's dispatcher."""
    node = STAGE_NODE[stage]
    task = STAGE_TASK[stage] + speech_rules(ctx) + TASK_TAIL
    trigger = when_any(node + "_observe", "The customer replied", [filled("%s_reply%d" % (node, k))
                                                                   for k in range(1, slot_count(ctx, stage) + 1)])
    schema = extraction_schema(ctx, stage)

    def conv(name, on_enter):
        return {"name": name, "node_type": "conversation", "on_enter": on_enter, "task_message": task,
                "extraction_schema": schema, "tools": [], "transitions": [trigger]}

    nodes = {
        node + "_say": code_node(node + "_say", "vars['spoken_stage'] = %r\n" % stage,
                                 [when_all(node, "There is content for the model to convey", filled("say_content")),
                                  always(node + "_wait")],
                                 on_enter={"type": "tts", "text": "{{say_tts}}"}),
        node: conv(node, {"type": "llm", "prompt": ENTRY_PROMPT}),
        node + "_wait": conv(node + "_wait", {"type": "silent"}),
    }
    frag = observe(ctx, stage)
    nodes.update(frag.nodes)
    routes = [when_all(node + "_say", "Engine: %s, verbatim lines first" % stage,
                       [leaf("engine_next", "equals", stage)] + filled("say_tts")),
              when_all(node, "Engine: %s" % stage, [leaf("engine_next", "equals", stage)]),
              when_all(node, "Engine could not apply the reply during %s" % stage,
                       [leaf("engine_next", "equals", "clarify"), leaf("last_stage", "equals", stage)])]
    return Fragment(nodes, routes)


def write_node(ctx, tool, description):
    """A baked engine-run write: arguments from the engine, result back through write_result."""
    name = "w_" + tool
    fn = api_tool(ctx, tool, engine_write_defaults(ctx, tool), description)
    node = {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "write_result",
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "suppress_tool_results": True,
            "pre_actions": [fn], "response_mapping": RESULT_MAPPING, "transitions": [always("write_result")]}
    route = when_all(name, "Engine: write %s" % tool,
                     [leaf("engine_next", "equals", WRITE_STAGE[tool]), leaf("write_tool", "equals", tool)])
    return Fragment({name: node}, [route], [fn])


RESULT_MAPPING = [{"path": "data.engine_result", "variable": "wr_json"}, {"path": "data", "variable": "wr_body"}]


def identity_verify(ctx):
    return write_node(ctx, "verify_identity", "Check one security answer chosen by the engine.")


def account_fetch(ctx):
    return write_node(ctx, "get_account", "The customer's late products, after verification.")


def record(ctx):
    return write_node(ctx, "create_promise", "Record the confirmed promise of one product.")


def transfer(ctx):
    return write_node(ctx, "transfer_to_agent", "Hand the call to the queue chosen by the engine.")


def note(ctx):
    return write_node(ctx, "add_note", "Note why a product ended without a promise.")


def callback_book(ctx):
    return write_node(ctx, "schedule_callback", "Book the callback the engine validated.")


WRITE_RESULT = '''import json
try:
    tool = str(vars.get('write_tool') or '')
    args = dict()
    try:
        args = json.loads(vars.get('write_args') or '{}')
    except Exception:
        args = dict()
    rec = vars.get('wr_json')
    res, data = 'unknown', dict()
    if isinstance(rec, str) and rec.strip():
        r = json.loads(rec)
        res = str(r.get('result') or 'unknown')
        data = r.get('data') if isinstance(r.get('data'), dict) else dict()
    else:
        body = vars.get('wr_body')
        if isinstance(body, str) and body.strip():
            try:
                body = json.loads(body)
            except Exception:
                body = None
        if isinstance(body, dict):
            data = body
            ok = body.get('ok')
            if ok is True or str(ok).lower() == 'true':
                res = 'ok'
            elif 'ok' in body:
                res = 'failed'
    ev = dict(kind='tool_result', tool=tool, item=(str(vars.get('write_item') or '') or None), result=res, data=data, args=args)
    vars['engine_events'] = json.dumps([ev])
except Exception:
    vars['engine_events'] = json.dumps([dict(kind='tool_result', tool=str(vars.get('write_tool') or ''), result='unknown', data=dict())])
vars['wr_json'] = ''
vars['wr_body'] = ''
'''


def write_result(ctx):
    """The write_result code node: the API's answer, with the engine's canonical response names added next to the
    API's own (builder/emitter/wire.py), as one tool_result event."""
    from builder.emitter.wire import NORMALISER
    resp_map = getattr(ctx, "resp_map", None) or {}
    literal = repr(resp_map).replace("{{", "{ {").replace("}}", "} }")   # a Python literal (json's null/true would not run)
    code = ("_RESP_MAP = " + literal + "\n" + NORMALISER + "\n"
            + WRITE_RESULT.replace("    ev = dict(kind='tool_result'", "    data = _wire_norm(tool, data)\n    ev = dict(kind='tool_result'", 1))
    return Fragment({"write_result": code_node("write_result", code, [always("engine")])})


def close_rows(ctx):
    """close_prep is the engine epilogue (close_text, close_outcome, close_reason); one close node per outcome row,
    the reason field absent (not empty) when the row has none; a no-row fallback; the silent end node."""
    nodes, routes, tools = {}, [], []
    seen = set()
    for row in ctx.rows:
        outcome, reason = row.get("outcome"), row.get("reason")
        key = (outcome, reason)
        if key in seen:
            continue
        seen.add(key)
        name = "close_%s_%s" % (outcome, reason or "none")
        defaults = call_var_defaults(ctx, CLOSE_TOOL)
        out_f = ctx.field_map.get(CLOSE_TOOL, {}).get("outcome", "outcome")
        rea_f = ctx.field_map.get(CLOSE_TOOL, {}).get("reason", "reason")
        defaults[out_f] = outcome
        if reason is not None:
            defaults[rea_f] = reason
        fn = api_tool(ctx, CLOSE_TOOL, defaults, "Close the call as %s%s." % (outcome, (" / " + reason) if reason else ""))
        tools.append(fn)
        nodes[name] = {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "write_result",
                       "on_enter": {"type": "tts", "text": "{{close_text}}"}, "on_enter_first_entry_only": True,
                       "disable_inactivity_monitor": True, "suppress_tool_results": True, "pre_actions": [fn],
                       "response_mapping": RESULT_MAPPING, "transitions": [always("write_result")]}
        routes.append(when_all(name, "Engine: close as %s / %s" % (outcome, reason or "no reason"),
                               [leaf("engine_next", "equals", "close"), leaf("close_outcome", "equals", outcome),
                                leaf("close_reason", "equals", reason or "")]))
    nodes["close_unmatched"] = code_node("close_unmatched", "vars['spoken_stage'] = 'close_unmatched'\n", [always("end")],
                                         on_enter={"type": "tts", "text": "{{close_text}}"})
    routes.append(when_all("close_unmatched", "Engine: close without a matching row", [leaf("engine_next", "equals", "close")]))
    return Fragment(nodes, routes, tools)


def end():
    node = {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "transitions": [], "terminal": {"type": "function", "function": {
                "name": "call_closed", "handler": "__function__:end_call",
                "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}
    return Fragment({"end": node}, [when_all("end", "Engine: the call is closed", [leaf("engine_next", "equals", "end")])])


def hold(ctx, first):
    """Last-resort target of the engine node (never expected): ask to repeat, then hand the next reply to the engine."""
    node = {"name": "hold", "node_type": "conversation", "on_enter": {"type": "llm", "prompt": REPEAT},
            "task_message": "Ask the customer to repeat what they said. No tool call is allowed in this turn.",
            "tools": [], "transitions": [always("engine")]}
    return Fragment({"hold": node}, [always("hold")])


EPILOGUE = '''

# ===== emitter epilogue (builder/emitter/fragments.py): speech plan and routing flags =====
EMIT_CFG = __CFG__


def _emit_segments(pre, v):
    """The engine's sentences in the order it produced them: ['v', text] verbatim, ['i', text] content to convey.
    Re-runs the same pure step with _say/_line observed; falls back to statements, content, questions."""
    g = globals()
    log = []
    ok = False
    try:
        o_say, o_line, o_main = g.get('_say'), g.get('_line'), g.get('_engine_main')
        if o_say and o_line and o_main:
            def w_say(C, st, pid):
                nm = len(C['mandatory'])
                nl = len(C['lines'])
                o_say(C, st, pid)
                for t in C['mandatory'][nm:]:
                    log.append(['v', t, 'm', pid])
                for t in C['lines'][nl:]:
                    log.append(['i', t, 'l', pid])   # a non-exact table phrase is an instruction, not a sentence

            def w_line(C, text):
                nl = len(C['lines'])
                o_line(C, text)
                for t in C['lines'][nl:]:
                    log.append(['i', t, 'l', ''])
            g['_say'] = w_say
            g['_line'] = w_line
            try:
                o_main(dict(pre))
            finally:
                g['_say'] = o_say
                g['_line'] = o_line
            lines = ' '.join([x[1] for x in log if x[2] == 'l'])
            mand = '\\n'.join([x[1] for x in log if x[2] == 'm'])
            ok = lines == str(v.get('say_next') or '') and mand == str(v.get('mandatory_lines') or '')
    except Exception:
        ok = False
    v['speech_source'] = 'engine' if ok else 'fallback'
    if ok:
        return [[x[0], x[1], x[3]] for x in log]   # kind, text, phrase id ('' for a free line)
    segs = []
    mand = [x for x in str(v.get('mandatory_lines') or '').split('\\n') if x.strip()]
    for m in mand:
        if not m.strip().endswith('?'):
            segs.append(['v', m, ''])
    sn = str(v.get('say_next') or '').strip()
    if sn:
        segs.append(['i', sn, ''])
    for m in mand:
        if m.strip().endswith('?'):
            segs.append(['v', m, ''])
    return segs


def _emit_json(v, key, default):
    try:
        x = json.loads(v.get(key) or '')
    except Exception:
        return default
    return x if isinstance(x, type(default)) else default


def _emit_route(v, pre):
    cfg = EMIT_CFG
    nxt = str(v.get('engine_next') or '')
    writes = _emit_json(v, 'engine_writes', [])
    buf = _emit_json(v, 'speech_buf', [])
    segs = _emit_segments(pre, v)
    for k in ('write_tool', 'write_item', 'write_args', 'wr_json', 'wr_body', 'say_tts', 'say_head_line', 'say_content', 'say_tail_line'):
        v[k] = ''
    if nxt == 'end':
        v['speech_buf'] = '[]'
        return
    if nxt == 'close':
        # no model turn before the close node: its tts speaks the verbatim lines (exact phrases, read-backs) and, for a
        # content line, the sentence EMIT_CFG['close_spoken'] gives for its phrase id; other instructions are not
        # spoken (measured 2026-10-10: the tts read "Thank the customer and say goodbye" to the customer). One goodbye.
        parts = []
        for s in buf + segs:
            t = s[1] if s[0] == 'v' else cfg['close_spoken'].get(s[2] if len(s) > 2 else '', '')
            if t and t not in parts:
                parts.append(t)
        text = ' '.join(parts)
        if 'goodbye' not in text.lower():
            text = (text + ' ' + cfg['goodbye']).strip()
        v['close_text'] = text
        v['speech_buf'] = '[]'
        v['write_tool'] = cfg['close_tool']
        w = writes[0] if writes and isinstance(writes[0], dict) else dict()
        v['write_args'] = json.dumps(w.get('args') if isinstance(w.get('args'), dict) else dict())
        return
    w = writes[0] if writes and isinstance(writes[0], dict) else None
    if w is not None and str(w.get('tool') or '') in cfg['write_vars']:
        tool = str(w.get('tool'))
        args = w.get('args') if isinstance(w.get('args'), dict) else dict()
        for key in cfg['write_vars'][tool]:
            if tool == 'schedule_callback' and key == 'reason' and key not in args:
                # a required callback reason the engine did not set (a third-party callback has none): the API's neutral value
                v[cfg['write_vars'][tool][key]] = cfg.get('callback_reason_default') or ''
            if key in args:
                val = args.get(key)
                if val is not None and 'cents' in cfg['write_vars'][tool][key].split('__')[-1].lower() and isinstance(val, (int, float)) and not isinstance(val, bool):
                    val = int(round(float(val) * 100))   # the API wants cents (amount_cents): the engine works in units
                if val is not None and cfg['write_types'].get(tool, {}).get(key) == 'string':
                    units = 'cents' not in cfg['write_vars'][tool][key].split('__')[-1].lower()
                    val = ('%.2f' % val) if key == 'amount' and units and isinstance(val, (int, float)) else str(val)
                v[cfg['write_vars'][tool][key]] = '' if val is None else val
        v['write_tool'] = tool
        v['write_item'] = str(w.get('item_id') or '')
        v['write_args'] = json.dumps(args)
        v['engine_next'] = cfg['write_stage'][tool]
        v['speech_buf'] = json.dumps(buf + segs)
        return
    stage = nxt
    if stage not in cfg['stages']:
        stage = str(v.get('last_stage') or '')
        if stage not in cfg['stages']:
            stage = cfg['first_stage']
        v['engine_next'] = 'clarify'
    allsegs = buf + segs
    rb = str(v.get('readback_text') or '').strip()
    if nxt == 'readback' and rb:
        allsegs = buf + [['v', rb, '']] + segs
    # a sentence produced once per write ("You will receive a text message ...", twice after two promises) is said once
    uniq = []
    for s in allsegs:
        if not any(u[0] == s[0] and u[1] == s[1] for u in uniq):
            uniq.append(s)
    allsegs = uniq
    tts, content, tail = [], [], []
    seen_i = False
    for s in allsegs:
        if s[0] == 'i':
            seen_i = True
            content.append(s[1])
        elif seen_i:
            tail.append(s[1])
        else:
            tts.append(s[1])
    if not content:
        content.append(str(v.get('what_to_do_next') or '') or cfg['repeat'])
    # every verbatim line goes through the dialogue model (head or tail line), never as tts of the S_say code node:
    # on the platform that node ends the turn and the next customer message re-runs its passthrough (2026-10-10)
    v['say_tts'] = ''
    v['say_head_line'] = (cfg['head_prefix'] + ' "' + ' '.join(tts) + '"') if tts else ''
    v['say_content'] = ' '.join(content)
    v['say_tail_line'] = (cfg['tail_prefix'] + ' "' + ' '.join(tail) + '"') if tail else ''
    v['last_stage'] = stage
    v['speech_buf'] = '[]'


try:
    _emit_route(vars, _EMIT_PRE)
except Exception:
    try:
        vars['engine_next'] = 'clarify'
        vars['say_tts'] = ''
        vars['say_head_line'] = ''
        vars['say_tail_line'] = ''
        vars['say_content'] = EMIT_CFG['repeat']
        vars['write_tool'] = ''
    except Exception:
        pass
'''


def engine_node(ctx, snippet, routes):
    """The single engine code node: snapshot of vars, the engine snippet, the emitter epilogue; routes on engine_next."""
    cfg = {"stages": [s for s in ctx.stages], "first_stage": "party", "goodbye": GOODBYE, "repeat": REPEAT,
           "head_prefix": HEAD_PREFIX, "tail_prefix": TAIL_PREFIX, "close_spoken": close_spoken_for(ctx.table), "close_tool": CLOSE_TOOL, "write_stage": {t: WRITE_STAGE[t] for t in ctx.write_tools},
           "write_vars": {t: {k: write_var(t, ctx.field_map.get(t, {}).get(k, k)) for k in ENGINE_ARGS[t] if ctx.field_map.get(t, {}).get(k, k)} for t in ctx.write_tools}}
    cfg["write_types"] = {t: {k: (ctx.api["tools"][t].get("request_fields", {}).get(
        ctx.field_map.get(t, {}).get(k, k), {}) or {}).get("type") for k in ENGINE_ARGS[t]}
        for t in ctx.write_tools}
    from builder.emitter.wire import required_default
    reason_field = ctx.field_map.get("schedule_callback", {}).get("reason")
    reason_schema = ctx.api["tools"].get("schedule_callback", {}).get("request_fields", {}).get(reason_field, {}) if reason_field else {}
    cfg["callback_reason_default"] = required_default("schedule_callback", reason_field, reason_schema) if reason_schema else None
    prologue = "_EMIT_PRE = dict(vars)\n"
    if "import base64\n" in snippet:
        snippet = snippet.replace("import base64\n", BASE64_SHIM, 1)
    code = prologue + snippet + EPILOGUE.replace("__CFG__", py(cfg))
    if ENGINE_MARKER not in code:
        raise EmitError("the engine snippet lacks its marker line")
    return Fragment({"engine": code_node("engine", code, list(routes))})


def gate(ctx, plan_entry):
    """Gate fragments (consent, ask, say, prompt_only at the four entrances) are not built in this increment."""
    raise EmitError("plan stage %r of type %r needs a gate fragment, which this emitter does not build"
                    % (plan_entry.get("id"), plan_entry.get("type")))


def origin_and_path(url):
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc), p.path
