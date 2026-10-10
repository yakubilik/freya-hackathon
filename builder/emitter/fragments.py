"""Tested node fragments of the phone-agent workflow (research/builder-architecture.md section 2.1).

Every function returns a `Fragment`: the nodes it owns (in the platform's exact JSON shape, transitions inside the
nodes), the transitions the engine code node needs to reach it (`routes`), and the tool definitions it uses. Tool
definitions are generated from the parsed tool API file (builder/readers/api_file.py), never typed by hand.

Runtime contract (one call turn):

    conversation node S / S_wait --(any extraction slot set)--> S_observe (code: snapshot + clear, engine_events)
        --> engine (code: engine snippet + emitter epilogue) --(engine_next + flags)--> one of
            S_say (tts of verbatim lines) -> S (llm entry: content) | S_wait (silent)
            w_<tool> (baked api_request) -> write_result (code: tool_result event) -> engine
            close_<outcome>_<reason> (baked close_call, tts goodbye) -> write_result -> engine -> end

The epilogue appended to the engine snippet turns the engine outputs into speech and routing variables:
`say_tts` (verbatim sentences in the order the engine produced them, up to the first content instruction),
`say_content` (what the dialogue model must convey in its own words), `say_tail_line` (verbatim sentences that
follow content, spoken word for word by the model), `close_text`, `speech_buf` (lines produced during writes,
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
               "add_note": ["product_id", "reason"], "schedule_callback": ["date", "time"], "transfer_to_agent": ["queue"],
               "close_call": ["outcome", "reason"]}
CLOSE_TOOL = "close_call"
ENGINE_MARKER = "Freya call engine, rendered by builder/engine/snippet.py"

COMMON_KINDS = ["question_back", "robot_question", "scam_question", "human", "hardship", "dont_want_to_talk", "other"]
STAGE_KINDS = {
    "party": ["party_confirmed", "party_other", "party_wrong_number", "party_deceased", "callback_offer"] + COMMON_KINDS,
    "callback": ["callback_offer", "party_wrong_number", "party_deceased"] + COMMON_KINDS,
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
    "party_confirmed": "the person confirms they are the customer asked for. Only these count: {confirm_words}",
    "party_other": "the person says they are someone else (a relative, a colleague, anyone who is not the customer)",
    "party_wrong_number": "the person says this number does not belong to the customer",
    "party_deceased": "the person says the customer has died",
    "callback_offer": "the person says when the customer can be reached (day words in date, time words in time)",
    "id_answer": "an answer, complete or partial, to the security question just asked (exact words in words)",
    "id_decline": "refuses to answer the security question{decline_extra}",
    "pay_today_yes": "yes to doing it today",
    "pay_today_no": "no to doing it today",
    "date_proposal": "names a day (their words for the day in date)",
    "amount_proposal": "names an amount they can manage (digits in amount, day words in date if a day is named too)",
    "too_much": "says the amount is too much for them",
    "refuse": "refuses the proposal, or gives a non-answer such as 'I will have to see'",
    "accept_offer": "accepts the proposal that was just made",
    "vague_period": "gives only a vague time such as next week, the end of the month, when the salary comes",
    "confirm": "says yes to the read-back or to a yes or no question",
    "deny": "says no to the read-back",
    "change": "changes the amount or the day of something already agreed",
    "paid": "says it is already paid",
    "dispute": "says it is not theirs, they never had the product, or it was closed or paid off in the past",
    "plan_request": "asks to split the amount or to spread it over months",
    "question_back": "asks a question back (who is calling, why, what it is about)",
    "robot_question": "asks whether you are a robot or an AI",
    "scam_question": "asks whether this is a scam",
    "human": "asks to speak to a person",
    "hardship": "mentions a hardship: illness, a death in the family, job loss",
    "dont_want_to_talk": "says they do not want to talk",
    "other": "anything else, including small talk, greetings and unclear replies",
}

ENTRY_PROMPT = ("Say this to the customer now, in one or two short sentences of your own: {{say_content}}\n"
                "{{say_tail_line}}\nDo not add anything else and do not call any tool.")
TAIL_PREFIX = "Finish your message with exactly these words:"
GOODBYE = "Thank you, goodbye."
REPEAT = "Ask the customer to repeat what they said."

STAGE_TASK = {
    "party": ("STEP: find out whether the person on the line is {{title}} {{last_name}}. Nobody is verified yet. "
              "Say nothing about why you are calling or about any account, to anyone. Only the person's own "
              "confirmation counts."),
    "callback": ("STEP: someone other than {{title}} {{last_name}} answered. Do not say why you are calling and ask them "
                 "no security questions. Find out when {{title}} {{last_name}} can be reached: a day and a time."),
    "identity": ("STEP: security questions. The person said they are {{title}} {{last_name}} but is not verified yet. "
                 "Ask only the question in the instruction, one at a time, and never answer it for them. Say nothing "
                 "about why you are calling or about any account until the questions are done."),
    "negotiate": ("STEP: the customer is verified and you are discussing the overdue amount. Propose only the amount and "
                  "the day the instruction gives. Never invent an amount, a day, a reduction or an arrangement, and "
                  "never ask the customer to name an amount."),
    "readback": ("STEP: read-back. The agreed amount and day were read to the customer. Wait for a clear yes; if they "
                 "want to change something, listen. Never say anything is done before the instruction says so."),
}
TASK_TAIL = ("\n\nCurrent instruction: {{what_to_do_next}}\n"
             "Speak only what the instruction asks. No tool call is allowed in this turn.")

SYSTEM_PROMPT = (
    "You are {label} of {org} on an outbound phone call. Speak English. Address the customer as {address}. "
    "Keep every turn to one or two short sentences and ask one question at a time.\n"
    "Rules for every step:\n"
    "- What to say is decided for you in the current step. Never decide amounts, days, outcomes or next steps yourself.\n"
    "- Never claim that something was done in the bank's systems unless your current step says it was.\n"
    "- Never offer a reduction, a waiver, an arrangement or any term your current step does not give you.\n"
    "- If asked something your step does not answer, say you do not have that information.\n"
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
    """Body fields filled from call variables (customer_id): any request field named like a call variable."""
    return {f: "{{%s}}" % f for f in ctx.api["tools"][tool]["request_fields"] if f in ctx.call_vars}


def engine_write_defaults(ctx, tool):
    """Body defaults of an engine-run write: call variables plus one `wa_<tool>__<field>` per engine argument."""
    fields = ctx.api["tools"][tool]["request_fields"]
    out = call_var_defaults(ctx, tool)
    for key in ENGINE_ARGS[tool]:
        wire = ctx.field_map.get(tool, {}).get(key, key)
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
    names += ["say_tts", "say_content", "say_tail_line", "close_text", "write_tool", "write_item", "write_args",
              "wr_json", "wr_body", "engine_events"]
    for tool in ctx.write_tools:
        for key in ENGINE_ARGS[tool]:
            names.append(write_var(tool, ctx.field_map.get(tool, {}).get(key, key)))
    lines = ["vars[%r] = ''" % n for n in names]
    lines += ["vars['speech_buf'] = '[]'", "vars['last_stage'] = %r" % first]
    code = "try:\n" + "\n".join("    " + ln for ln in lines) + "\nexcept Exception:\n    pass\n"
    return Fragment({"setup": code_node("setup", code, [always("engine")])})


def slot_count(ctx, stage):
    if stage in ("negotiate", "readback"):
        return max(3, ctx.max_items + 1)
    return 2


def slot_vars(ctx, stage):
    node = STAGE_NODE[stage]
    return ["%s_%s%d" % (node, f, k) for k in range(1, slot_count(ctx, stage) + 1) for f in STAGE_FIELDS[stage]]


def extraction_schema(ctx, stage):
    kinds = STAGE_KINDS[stage]
    help_lines = []
    for k in kinds:
        text = KIND_HELP[k].format(confirm_words=ctx.confirm_words, decline_extra=ctx.decline_extra)
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
                out.append({"name": name, "type": "string", "enum_values": list(kinds), "description": desc, "min_confidence": 0.5})
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
                out.append({"name": name, "type": "string", "min_confidence": 0.5,
                            "description": ("For %s_reply%d: the customer's exact words for this part of the reply. For an "
                                            "answer to a security question, everything they said as the answer, unchanged." % (node, k))})
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
    return words


try:
    evs = []
    for slot in _SLOTS:
        kind = _ob_val(slot.get('reply'))
        if not kind:
            continue
        if kind not in _KINDS:
            kind = 'other'
        amount = None
        a = _ob_val(slot.get('amount')).replace(',', '')
        if a:
            try:
                amount = float(a)
            except ValueError:
                amount = None
        words = _ob_val(slot.get('words')) or None
        if a and amount is None and not words:
            words = a
        ev = dict(kind=kind, item=_ob_item(_ob_val(slot.get('item'))), amount=amount,
                  date_text=_ob_val(slot.get('date')) or None, time_text=_ob_val(slot.get('time')) or None,
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
    code = (DISPATCH.replace("__KINDS__", py(STAGE_KINDS[stage])).replace("__SLOTS__", py(slots))
            )
    code = code + "".join("vars[%r] = ''\n" % n for n in names)
    name = node + "_observe"
    return Fragment({name: code_node(name, code, [always("engine")])})


def speaking_stage(ctx, stage):
    """S_say (tts of the verbatim lines), S (llm entry with the content) and S_wait (silent), all listening on the
    same extraction schema, plus the stage's dispatcher."""
    node = STAGE_NODE[stage]
    task = STAGE_TASK[stage] + TASK_TAIL
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
    return Fragment({"write_result": code_node("write_result", WRITE_RESULT, [always("engine")])})


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
        o_say, o_line, o_phrase, o_main = g.get('_say'), g.get('_line'), g.get('_phrase'), g.get('_engine_main')
        if o_say and o_line and o_phrase and o_main:
            def w_say(C, st, pid):
                nm = len(C['mandatory'])
                nl = len(C['lines'])
                o_say(C, st, pid)
                known = o_phrase(C, pid) is not None
                for t in C['mandatory'][nm:]:
                    log.append(['v', t, 'm'])
                for t in C['lines'][nl:]:
                    log.append(['v' if known else 'i', t, 'l'])

            def w_line(C, text):
                nl = len(C['lines'])
                o_line(C, text)
                for t in C['lines'][nl:]:
                    log.append(['i', t, 'l'])
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
        return [[x[0], x[1]] for x in log]
    segs = []
    mand = [x for x in str(v.get('mandatory_lines') or '').split('\\n') if x.strip()]
    for m in mand:
        if not m.strip().endswith('?'):
            segs.append(['v', m])
    sn = str(v.get('say_next') or '').strip()
    if sn:
        segs.append(['i', sn])
    for m in mand:
        if m.strip().endswith('?'):
            segs.append(['v', m])
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
    for k in ('write_tool', 'write_item', 'write_args', 'wr_json', 'wr_body', 'say_tts', 'say_content', 'say_tail_line'):
        v[k] = ''
    if nxt == 'end':
        v['speech_buf'] = '[]'
        return
    if nxt == 'close':
        text = ' '.join([s[1] for s in buf + segs if s[0] == 'v'])
        v['close_text'] = text or cfg['goodbye']
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
            if key in args:
                val = args.get(key)
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
        allsegs = buf + [['v', rb]] + segs
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
    if not tts and not content:
        content.append(str(v.get('what_to_do_next') or '') or cfg['repeat'])
    v['say_tts'] = ' '.join(tts)
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
        vars['say_tail_line'] = ''
        vars['say_content'] = EMIT_CFG['repeat']
        vars['write_tool'] = ''
    except Exception:
        pass
'''


def engine_node(ctx, snippet, routes):
    """The single engine code node: snapshot of vars, the engine snippet, the emitter epilogue; routes on engine_next."""
    cfg = {"stages": [s for s in ctx.stages], "first_stage": "party", "goodbye": GOODBYE, "repeat": REPEAT,
           "tail_prefix": TAIL_PREFIX, "close_tool": CLOSE_TOOL, "write_stage": {t: WRITE_STAGE[t] for t in ctx.write_tools},
           "write_vars": {t: {k: write_var(t, ctx.field_map.get(t, {}).get(k, k)) for k in ENGINE_ARGS[t]} for t in ctx.write_tools}}
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
