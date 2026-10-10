"""Unit tests of the engine rules the simulator emulates (kit docs workflow-format.md and tools-and-code.md)."""
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.simulator import DROP, Simulator, flatten, merge_transitions, run_snippet  # noqa: E402


# ---------------------------------------------------------------------------------------------------------------
# a capture HTTP server: records every request, answers per path
# ---------------------------------------------------------------------------------------------------------------
class Capture:
    def __init__(self):
        self.requests = []
        self.responses = {}  # path -> (status, json) or list of them (consumed in order)
        self.sleep = {}      # path -> seconds

    def answer(self, path):
        r = self.responses.get(path, (200, {"ok": True}))
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return r


@pytest.fixture(scope="module")
def capture():
    cap = Capture()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode()
            cap.requests.append({"path": self.path, "method": self.command, "headers": dict(self.headers.items()), "body": body})
            if self.path in cap.sleep:
                time.sleep(cap.sleep[self.path])
            status, payload = cap.answer(self.path)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Trace", "abc")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = _handle
        do_GET = _handle

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cap.base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield cap
    srv.shutdown()


# ---------------------------------------------------------------------------------------------------------------
# workflow building blocks
# ---------------------------------------------------------------------------------------------------------------
def api_tool(name, url, body_fields=None, headers=None, config=None, mapping=None, pre=None, post=None, required=None, method="POST"):
    props = {"url": {"type": "string", "default": url}, "method": {"type": "string", "default": method},
             "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}, **(headers or {})}},
             "body": {"type": "object", "properties": body_fields or {}, "required": required or []}}
    t = {"type": "function", "config": config or {"timeoutMs": 2000, "maxRetries": 0},
         "function": {"name": name, "handler": "__function__:api_call", "description": "x", "parameters": {"type": "object", "properties": props}}}
    if mapping is not None:
        t["response_mapping"] = mapping
    if pre:
        t["pre_process_code"] = pre
    if post:
        t["post_process_code"] = post
    return t


def code_tool(code):
    return {"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
            "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 1000}}}}}


def always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def var_cond(target, variable, operator, operand=None, description="cond"):
    c = {"variable": variable, "operator": operator}
    if operand is not None:
        c["operand"] = operand
    return {"target_node": target, "description": description, "condition": {"logic": "or", "conditions": [c]}}


def intent(target, description):
    return {"target_node": target, "description": description, "condition": {"operator": "matches_intent", "description": description}}


def conv(name, transitions=(), tools=(), **extra):
    n = {"name": name, "node_type": "conversation", "task_message": "x", "on_enter": {"type": "silent"}, "transitions": list(transitions), "tools": list(tools)}
    n.update(extra)
    return n


def action_node(name, actions, nxt, node_type="api_request", mapping=None, **extra):
    n = {"name": name, "node_type": node_type, "passthrough": True, "passthrough_default_transition": nxt, "on_enter": {"type": "silent"},
         "pre_actions": list(actions), "transitions": [always(nxt)]}
    if mapping is not None:
        n["response_mapping"] = mapping
    n.update(extra)
    return n


def end_node(name, fn_name, mode="none", spoken=None):
    props = {"message_mode": {"type": "string", "default": mode}}
    if spoken:
        props["spoken_message"] = {"type": "string", "default": spoken}
    return {"name": name, "node_type": "end_call", "on_enter": {"type": "silent"}, "transitions": [],
            "terminal": {"type": "function", "function": {"name": fn_name, "handler": "__function__:end_call", "parameters": {"type": "object", "properties": props}}}}


def wf(initial, nodes, **extra):
    w = {"initial_node": initial, "nodes": {n["name"]: n for n in nodes}, "global_nodes": {}, "test_variables": {}}
    w.update(extra)
    return w


def T(name, **args):
    return {"name": name, "args": args}


# ---------------------------------------------------------------------------------------------------------------
# substitution and baking
# ---------------------------------------------------------------------------------------------------------------
def test_substitution_forms():
    sim = Simulator(wf("a", [conv("a")]), variables={"name": "Dana", "amount": 12.5, "items": ["x"], "when": "2026-10-14T11:00"})
    assert sim.substitute("Hi {{name}}, {{amount}} on {{when}}") == "Hi Dana, 12.5 on 2026-10-14T11:00"  # dates are not reformatted
    assert sim.substitute("{{items:json}}") == '["x"]'
    assert sim.substitute("Hi {{nobody}}") == "Hi {{nobody}}"  # a prompt keeps the literal placeholder
    assert sim.substitute("{{nobody}}", engine=True) is DROP  # exactly one unresolved placeholder: the field is dropped
    assert sim.substitute("Status: {{nobody}}", engine=True) == "Status: {{nobody}}"  # mixed: the literal stays
    assert sim.substitute("{{amount}}", engine=True) == 12.5  # a whole-field placeholder keeps the value's type
    assert sim.substitute("{{system.conversation.last-1}}") == ""


def test_baking_hides_resolved_defaults_and_exposes_unresolved_ones(capture):
    tool = api_tool("verify", capture.base + "/verify", {"customer_id": {"type": "string", "default": "{{customer_id}}"},
                                                         "answer": {"type": "string", "default": "{{answer}}"},
                                                         "free": {"type": "string"}}, required=["answer"])
    sim = Simulator(wf("a", [conv("a", tools=[tool])]), variables={"customer_id": "c_1"})
    sim.start()
    baked = sim.baked["a"]["verify"]["baked"]
    assert baked["config"]["body"] == {"customer_id": "c_1"} and baked["config"]["url"].endswith("/verify")
    assert set(baked["model"]) == {"answer", "free"}  # model-filled: unresolved default and no default
    sim.turn({"say": "x", "tool_calls": [T("verify", answer="1988-03-14", customer_id="hacker")]})
    sent = capture.requests[-1]
    assert sent["body"] == {"customer_id": "c_1", "answer": "1988-03-14"}  # the baked value wins; the model's extra arg is ignored
    assert sent["headers"]["Content-Type"] == "application/json"
    v = sim.table
    assert v["verify_args.answer"] == "1988-03-14" and "verify_args.customer_id" not in v  # only model args are stored
    assert any("baked" in w for w in sim.warnings)


def test_baking_happens_at_node_entry(capture):
    tool = api_tool("t", capture.base + "/t", {"product_id": {"type": "string", "default": "{{product_id}}"}})
    sim = Simulator(wf("a", [conv("a", tools=[tool])]))
    sim.start()
    assert "product_id" in sim.baked["a"]["t"]["model"]
    sim.table["product_id"] = "p9"  # set after entry: still model-filled in this node visit
    sim.turn({"say": "x", "tool_calls": [T("t", product_id="p1")]})
    assert capture.requests[-1]["body"] == {"product_id": "p1"}


def test_engine_run_call_drops_single_unresolved_placeholder_keeps_mixed(capture):
    act = api_tool("push", capture.base + "/push", {"a": {"type": "string", "default": "{{missing}}"},
                                                    "b": {"type": "string", "default": "Status: {{missing}}"},
                                                    "c": {"type": "string", "default": "{{obj:json}}"},
                                                    "d": {"type": "string", "default": "{{empty}}"}},
                   headers={"X-Key": {"type": "string", "default": "{{api_key}}"}})
    sim = Simulator(wf("n", [action_node("n", [act], "e"), end_node("e", "done")]), variables={"obj": {"k": [1, 2]}, "empty": ""})
    sim.run()
    sent = capture.requests[-1]
    assert sent["body"] == {"b": "Status: {{missing}}", "c": '{"k": [1, 2]}', "d": ""}
    assert "X-Key" not in sent["headers"]
    assert sim.ended_reason == "done"


# ---------------------------------------------------------------------------------------------------------------
# results: flattening, counters, mapping, envelope
# ---------------------------------------------------------------------------------------------------------------
def test_flatten_rules():
    out = {}
    flatten("t_response", {"status": "success", "data": {"ok": True, "nested": {"n": 2, "f": False}, "items": [{"a": 1}], "none": None, "s": "x"}, "status_code": 200, "header": {"X": "1"}}, out)
    assert out == {"t_response.status": "success", "t_response.data.ok": "true", "t_response.data.nested.n": 2, "t_response.data.nested.f": "false",
                   "t_response.data.items": '[{"a": 1}]', "t_response.data.none": None, "t_response.data.s": "x", "t_response.status_code": 200, "t_response.header.X": "1"}


def test_tool_result_envelope_flattened_keys_counters_and_mapping(capture):
    capture.responses["/look"] = (200, {"ok": True, "verified": False, "attempts_left": 3, "products": [{"product_id": "p1"}], "meta": {"tier": "gold"}})
    tool = api_tool("look", capture.base + "/look", {}, mapping=[{"path": "data.products", "variable": "products"}, {"path": "data.meta.tier", "variable": "tier"},
                                                              {"path": "ok", "variable": "bare_ok"}])  # a path without data. is not confirmed and does not resolve
    sim = Simulator(wf("a", [conv("a", tools=[tool])]))
    sim.start()
    sim.turn({"say": "x", "tool_calls": [T("look"), T("look")]})
    v = sim.table
    assert v["look_response.status"] == "success" and v["look_response.status_code"] == 200 and v["look_status_code"] == 200
    assert v["look_response.data.ok"] == "true" and v["look_response.data.verified"] == "false"  # booleans as lowercase strings
    assert v["look_response.data.attempts_left"] == 3
    assert v["look_response.data.meta.tier"] == "gold"  # nested dicts flattened with dots
    assert json.loads(v["look_response.data.products"]) == [{"product_id": "p1"}]  # lists as JSON strings
    assert v["look_response.header.X-Trace"] == "abc" and v["look_response.message"] == "Successfully executed POST request"
    assert v["look_success_count"] == 2 and "look_failure_count" not in v
    assert v["products"] == [{"product_id": "p1"}] and v["tier"] == "gold"  # mapped values keep their type
    assert "bare_ok" not in v
    evs = [e for e in sim.events if e["event"] == "function_call_complete"]
    assert evs[-1]["result"]["header"]["X-Trace"] == "abc" and set(evs[-1]["result"]) == {"status", "data", "message", "status_code", "header"}
    starts = [e for e in sim.events if e["event"] == "function_call_start"]
    assert set(starts[-1]["args"]) == {"url", "method", "headers", "body"}


def test_pre_actions_node_uses_node_id_prefix_and_node_level_mapping(capture):
    capture.responses["/acc"] = (200, {"ok": True, "balance": 42})
    act = api_tool("get_account", capture.base + "/acc", {"customer_id": {"type": "string", "default": "{{customer_id}}"}},
                   mapping=[{"path": "data.balance", "variable": "ignored_nested"}])  # a mapping inside a pre_actions entry is ignored
    node = action_node("fetch", [act], "e", mapping=[{"path": "data.balance", "variable": "balance"}])
    sim = Simulator(wf("fetch", [node, end_node("e", "done")]), variables={"customer_id": "c_7"})
    sim.run()
    v = sim.table
    assert capture.requests[-1]["body"] == {"customer_id": "c_7"}
    assert v["balance"] == 42 and "ignored_nested" not in v
    assert v["fetch_success_count"] == 1 and v["fetch_status_code"] == 200 and v["fetch_response.data.ok"] == "true"
    assert "get_account_success_count" not in v


def test_http_error_counts_as_failure_and_retries(capture):
    capture.responses["/flaky"] = [(500, {"ok": False, "error": "down"}), (500, {"ok": False, "error": "down"}), (200, {"ok": True})]
    before = len(capture.requests)
    act = api_tool("w", capture.base + "/flaky", {}, config={"timeoutMs": 2000, "maxRetries": 2})
    sim = Simulator(wf("n", [action_node("n", [act], "e"), end_node("e", "done")]))
    sim.run()
    assert len(capture.requests) - before == 3  # 1 + 2 retries, the last one succeeded
    assert sim.table["n_success_count"] == 1 and "n_failure_count" not in sim.table
    capture.responses["/flaky"] = [(500, {"ok": False, "error": "down"})]
    sim = Simulator(wf("n", [action_node("n", [api_tool("w", capture.base + "/flaky", {})], "e"), end_node("e", "done")]))
    sim.run()
    assert sim.table["n_failure_count"] == 1 and sim.table["n_response.status"] == "error" and sim.table["n_status_code"] == 500
    assert sim.table["n_response.data.error"] == "down"  # the error body is still flattened


def test_timeout_gives_status_error_and_status_code_zero(capture):
    capture.sleep["/slow"] = 0.6
    act = api_tool("slow", capture.base + "/slow", {}, config={"timeoutMs": 200, "maxRetries": 1})
    node = action_node("n", [act], "ok")
    node["transitions"] = [var_cond("bad", "n_failure_count", "greater_than", 0), always("ok")]
    sim = Simulator(wf("n", [node, end_node("ok", "ok"), end_node("bad", "bad")]))
    t0 = time.time()
    sim.run()
    assert time.time() - t0 < 1.5
    r = [e for e in sim.events if e["event"] == "function_call_complete"][-1]["result"]
    assert r["status"] == "error" and r["status_code"] == 0 and "timed out" in r["message"] and r["data"] is None
    assert sim.table["n_failure_count"] == 1 and sim.table["n_status_code"] == 0
    assert len([e for e in sim.events if e["event"] == "function_call_start"]) == 2  # one retry
    assert sim.ended_reason == "bad"


# ---------------------------------------------------------------------------------------------------------------
# hooks and code
# ---------------------------------------------------------------------------------------------------------------
def test_pre_hook_sees_config_and_vars_post_hook_sees_result(capture):
    capture.responses["/h"] = (200, {"ok": True, "verified": True})
    pre = "vars['seen_url'] = config['url']\nconfig['body']['answer'] = str(config['body'].get('answer') or '').strip().upper()\nconfig['body']['extra'] = vars.get('customer_id')\nconfig['headers']['X-Pre'] = 'yes'\n"
    post = "result.pop('header', None)\nd = result['data']\nd['what_to_do_next'] = 'Ask the next question.' if d.get('verified') else 'Ask again.'\nvars['from_post'] = 'set'\n"
    tool = api_tool("h", capture.base + "/h", {"answer": {"type": "string", "default": "{{answer}}"}}, pre=pre, post=post,
                    mapping=[{"path": "data.what_to_do_next", "variable": "next_step"}])
    later = api_tool("h2", capture.base + "/h", {}, pre="vars['later_saw'] = vars.get('from_post')\n")
    sim = Simulator(wf("a", [conv("a", tools=[tool, later])]), variables={"customer_id": "c_1"})
    sim.start()
    sim.turn({"say": "x", "tool_calls": [T("h", answer=" abc "), T("h2")]})
    sent = capture.requests[-2]
    assert sent["body"] == {"answer": "ABC", "extra": "c_1"} and sent["headers"]["X-Pre"] == "yes"
    v = sim.table
    assert v["seen_url"].endswith("/h")
    assert v["next_step"] == "Ask the next question."  # mapping runs after the post-hook
    assert "h_response.header.X-Trace" not in v  # flattening sees the hook's result (header popped)
    assert v["h_response.data.what_to_do_next"] == "Ask the next question."
    assert v["from_post"] == "set" and v["later_saw"] == "set"  # a later pre-hook reads what a post-hook wrote
    complete = [e for e in sim.events if e["event"] == "function_call_complete" and e["function"] == "h"][0]
    assert "header" not in complete["result"] and complete["result"]["data"]["what_to_do_next"]


def test_pre_hook_string_body_is_sent_raw(capture):
    tool = api_tool("raw", capture.base + "/raw", {"a": {"type": "string", "default": "1"}}, pre="config['body'] = 'k=v'\nconfig['headers']['Content-Type'] = 'text/plain'\n")
    sim = Simulator(wf("n", [action_node("n", [tool], "e"), end_node("e", "done")]))
    sim.run()
    assert capture.requests[-1]["body"] == "k=v" and capture.requests[-1]["headers"]["Content-Type"] == "text/plain"


def test_hook_exception_is_recorded_and_the_call_still_runs(capture):
    tool = api_tool("boom", capture.base + "/boom", {}, pre="raise ValueError('x')", post="result['data']['touched'] = 1")
    sim = Simulator(wf("n", [action_node("n", [tool], "e"), end_node("e", "done")]))
    sim.run()
    errs = [e for e in sim.events if e["event"] == "error"]
    assert errs and "pre_process_code" in errs[0]["message"]
    assert sim.table["n_response.data.touched"] == 1 and sim.ended_reason == "done"


def test_code_node_writes_vars_and_automatic_keys_named_after_the_node():
    code = "import datetime\nimport json\nimport re\ntry:\n    d = datetime.date.fromisoformat(str(vars.get('now'))[:10])\n    vars['tomorrow'] = (d + datetime.timedelta(days=1)).isoformat()\n    vars['state'] = 'known'\n    vars['n'] = int(vars.get('n') or 0) + 1\nexcept Exception:\n    vars['state'] = 'unknown'\n"
    node = action_node("setup", [code_tool(code)], "e", node_type="code")
    sim = Simulator(wf("setup", [node, end_node("e", "done")]), variables={"now": "2026-10-14T11:00", "n": 1})
    sim.run()
    v = sim.table
    assert v["tomorrow"] == "2026-10-15" and v["state"] == "known" and v["n"] == 2
    assert v["setup_response.status"] == "success" and v["setup_response.data"] is None and v["setup_response.message"] == "Code executed successfully"
    assert v["setup_response.status_code"] == 200 and v["setup_status_code"] == 200 and v["setup_success_count"] == 1
    assert "code_exec_success_count" not in v


def test_sandbox_allows_only_json_re_datetime():
    g = run_snippet("import json, re, datetime\nx = json.dumps(re.sub('a', 'b', 'a')) + datetime.date(2026, 1, 1).strftime('%d')", {})
    assert g["x"] == '"b"01'
    with pytest.raises(ImportError):
        run_snippet("import os", {})
    with pytest.raises(ImportError):
        run_snippet("import subprocess", {})
    with pytest.raises(NameError):
        run_snippet("open('/etc/passwd')", {})


def test_code_node_exception_is_an_error_and_a_failure():
    node = action_node("calc", [code_tool("vars['a'] = 1\nraise RuntimeError('bad')")], "e", node_type="code")
    sim = Simulator(wf("calc", [node, end_node("e", "done")]))
    sim.run()
    assert sim.table["calc_failure_count"] == 1 and sim.table["calc_response.status"] == "error"
    assert any(e["event"] == "error" and "code_exec" in e["message"] for e in sim.events)
    assert sim.table["a"] == 1  # writes before the raise stay (the engine writes every key the snippet assigned)
    assert sim.ended_reason == "done"


def test_skip_initial_code_emulates_the_chat_route():
    node = action_node("setup", [code_tool("vars['ran'] = 'yes'")], "a", node_type="code")
    sim = Simulator(wf("setup", [node, conv("a")]), skip_initial_code=True)
    sim.start()
    assert "ran" not in sim.table and sim.current == "a"
    sim2 = Simulator(wf("setup", [node, conv("a")]))
    sim2.start()
    assert sim2.table["ran"] == "yes"


# ---------------------------------------------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------------------------------------------
def test_operators():
    sim = Simulator(wf("a", [conv("a")]), variables={"flag": True, "s": "Shipped", "n": "2", "e": "", "z": 0})
    ev = lambda **c: sim.eval_condition(c, set())[0]
    assert ev(variable="flag", operator="equals", operand="True") and not ev(variable="flag", operator="equals", operand="true")  # str(value) == str(operand)
    assert ev(variable="flag", operator="not_equals", operand="true")
    assert ev(variable="n", operator="greater_than", operand=1) and ev(variable="n", operator="less_than", operand="3.5")
    assert not ev(variable="s", operator="greater_than", operand=1)  # not a number: false, no error
    assert ev(variable="s", operator="contains", operand="SHIP")  # case-insensitive substring
    assert ev(variable="s", operator="is_set") and ev(variable="z", operator="is_set")
    assert not ev(variable="e", operator="is_set") and ev(variable="e", operator="is_not_set")
    assert ev(variable="nope", operator="is_not_set") and not ev(variable="nope", operator="is_set")
    assert ev(operator="always")
    assert not ev(operator="matches_intent", description="x")
    assert sim.eval_condition({"operator": "matches_intent", "description": "x"}, {"x"})[0]
    nested = {"logic": "or", "conditions": [{"logic": "and", "conditions": [{"variable": "s", "operator": "equals", "operand": "Shipped"}, {"variable": "n", "operator": "greater_than", "operand": 5}]},
                                            {"variable": "z", "operator": "equals", "operand": "0"}]}
    res, rec = sim.eval_condition(nested, set())
    assert res and rec["logic"] == "or" and rec["conditions"][0]["result"] is False and rec["conditions"][1]["result"] is True


def test_routing_order_loop_then_transitions_in_order_then_globals():
    a = conv("a", transitions=[intent("b", "wants b"), var_cond("c", "x", "equals", "1"), intent("d", "wants d")], loop_condition="not done", loop_prompt="again")
    g = {"g": {"name": "g", "node_type": "conversation", "description": "interrupt", "on_enter": {"type": "tts", "text": "interrupted"},
               "condition": {"operator": "matches_intent", "description": "off topic"}, "excluded_nodes": ["c"],
               "passthrough": True, "passthrough_default_transition": "__previous__", "transitions": [always("__previous__")]}}
    w = wf("a", [a, conv("b"), conv("c", transitions=[intent("b", "wants b")]), conv("d")], global_nodes=g)
    # 1. loop_condition wins over everything
    sim = Simulator(w, variables={"x": "1"})
    sim.start()
    sim.turn({"say": "x", "loop": True, "intents": ["wants b"]})
    assert sim.current == "a" and sim.events[-2]["event"] == "route_evaluated" and "loop_condition" in sim.events[-2]["reason"]
    # 2. deterministic conditions are evaluated before intent ones, even when listed later
    sim = Simulator(w, variables={"x": "1"})
    sim.start()
    sim.turn({"say": "x", "intents": ["wants b"]})
    assert sim.current == "c"
    # 3. intents in list order
    sim = Simulator(w)
    sim.start()
    sim.turn({"say": "x", "intents": ["wants d", "wants b"]})
    assert sim.current == "b"
    # 4. globals only after the node's transitions found nothing; __previous__ returns
    sim = Simulator(w)
    sim.start()
    sim.turn({"say": "x", "intents": ["off topic"]})
    entered = [e["node"] for e in sim.events if e["event"] == "node_enter"]
    assert entered == ["a", "g", "a"] and "interrupted" in sim.transcript_text() and sim.current == "a"
    # 5. excluded_nodes: the global does not fire from c
    sim = Simulator(w, variables={"x": "1"})
    sim.start()
    sim.turn({"say": "x"})
    assert sim.current == "c"
    sim.turn({"say": "x", "intents": ["off topic"]})
    assert sim.current == "c" and [e["node"] for e in sim.events if e["event"] == "node_enter"] == ["a", "c"]
    # 6. nothing matched: stay, no fallback
    sim = Simulator(w)
    sim.start()
    sim.turn({"say": "x"})
    assert sim.current == "a" and [e for e in sim.events if e["event"] == "route_evaluated"][-1]["matched"] is False


def test_route_evaluated_event_shape():
    a = conv("a", transitions=[var_cond("b", "x", "equals", "1")])
    sim = Simulator(wf("a", [a, conv("b")]), variables={"x": "0"})
    sim.start()
    sim.turn({"say": "hi"})
    ev = [e for e in sim.events if e["event"] == "route_evaluated"][-1]
    assert ev["from_node"] == "a" and ev["matched"] is False and ev["target"] is None
    assert ev["branches"][0]["target"] == "b" and ev["branches"][0]["result"] is False
    assert ev["branches"][0]["condition_results"]["conditions"][0] == {"operator": "equals", "variable": "x", "operand": "1", "result": False, "value": "0"}
    assert ev["variable_table"]["x"] == "0" and ev["variable_table"]["a.current_turns"] == 1
    msg = [m for m in sim.messages if m["role"] == "system"][-1]
    assert json.loads(msg["message"])["event"] == "route_evaluated"


def test_same_target_transitions_are_merged():
    ts = [var_cond("b", "x", "equals", "1"), intent("c", "c please"), var_cond("b", "y", "equals", "1"), always("d"), always("d")]
    merged = merge_transitions(ts)
    assert [t["target_node"] for t in merged] == ["b", "c", "d"]
    assert merged[0]["condition"]["logic"] == "or" and len(merged[0]["condition"]["conditions"]) == 2
    assert merged[2]["condition"] == {"operator": "always"}
    merged2 = merge_transitions([var_cond("b", "x", "equals", "1"), always("b")])
    assert merged2[0]["condition"] == {"operator": "always"}  # an unconditional member makes the merged one unconditional
    tool_calls = merge_transitions([{"target_node": "b", "is_tool_call": True, "condition": {"operator": "matches_intent", "description": "x"}}, var_cond("b", "x", "equals", "1")])
    assert len(tool_calls) == 2  # tool-call transitions are not merged with router ones
    sim = Simulator(wf("a", [conv("a", transitions=ts), conv("b"), conv("c"), conv("d")]), variables={"y": "1"})
    sim.start()
    sim.turn({"say": "x"})
    assert sim.current == "b"
    assert len([e for e in sim.events if e["event"] == "route_evaluated"][-1]["branches"]) == 1  # merged b matched first


def test_routing_runs_again_after_a_tool_result_in_the_same_turn(capture):
    capture.responses["/ok"] = (200, {"ok": True, "verified": True})
    tool = api_tool("check", capture.base + "/ok", {}, mapping=[{"path": "data.verified", "variable": "passed"}])
    a = conv("a", tools=[tool], transitions=[var_cond("b", "check_response.data.verified", "equals", "true"), var_cond("b", "passed", "equals", "True")])
    sim = Simulator(wf("a", [a, conv("b", on_enter={"type": "tts", "text": "Welcome to b"})]))
    sim.start()
    sim.turn({"say": "x", "tool_calls": [T("check")], "agent": "not spoken: b's fixed line took the turn"})
    assert sim.current == "b"
    routes = [e for e in sim.events if e["event"] == "route_evaluated"]
    assert [r["trigger"] for r in routes] == ["user_message", "tool_result"] and routes[-1]["matched"]
    assert sim.transcript[-1]["text"] == "Welcome to b"
    assert sim.table["passed"] is True  # the mapped raw value keeps its type; the flattened key is the string "true"


def test_is_tool_call_transition_and_unavailable_tools():
    a = conv("a", transitions=[{"target_node": "b", "description": "go", "is_tool_call": True, "condition": {"operator": "matches_intent", "description": "go"}}])
    sim = Simulator(wf("a", [a, conv("b", on_enter={"type": "tts", "text": "in b"}), conv("c")]))
    sim.start()
    sim.turn({"say": "x", "intents": ["go"]})
    assert sim.current == "a"  # the router does not evaluate tool-call transitions
    sim.turn({"say": "x", "tool_calls": [T("transition_to_c"), T("verify_identity"), T("transition_to_b")]})
    errs = [e["message"] for e in sim.events if e["event"] == "error"]
    assert errs == ["The function `transition_to_c` is not currently available.", "The function `verify_identity` is not currently available."]
    assert sim.current == "b" and sim.transcript[-1]["text"] == "in b"


def test_global_node_as_tool_call_and_previous():
    g = {"help": {"name": "help", "node_type": "conversation", "is_tool_call": True, "condition": {"operator": "matches_intent", "description": "help"},
                  "on_enter": {"type": "tts", "text": "help text"}, "passthrough": True, "passthrough_default_transition": "__previous__", "transitions": [always("__previous__")]}}
    sim = Simulator(wf("a", [conv("a"), conv("b")], global_nodes=g))
    sim.start()
    sim.turn({"say": "x", "intents": ["help"]})
    assert sim.current == "a" and "help text" not in sim.transcript_text()  # a tool-call global is not checked per turn
    sim.turn({"say": "x", "tool_calls": [T("transition_to_help")]})
    assert [e["node"] for e in sim.events if e["event"] == "node_enter"] == ["a", "help", "a"]


def test_max_node_turns_moves_to_max_turn_transition():
    a = conv("a", max_node_turns=2, max_turn_transition="give_up")
    sim = Simulator(wf("a", [a, end_node("give_up", "no_booking", mode="custom", spoken="No booking, {{first_name}}. Goodbye.")]), variables={"first_name": "Dana"})
    sim.start()
    sim.turn({"say": "one"})
    assert sim.current == "a" and not sim.ended
    sim.turn({"say": "two"})
    assert sim.ended and sim.ended_reason == "no_booking" and sim.transcript[-1]["text"] == "No booking, Dana. Goodbye."
    assert sim.table["a.current_turns"] == 2 and sim.table["a.total_turns"] == 2
    # without max_turn_transition the cap changes nothing
    sim = Simulator(wf("a", [conv("a", max_node_turns=1)]))
    sim.start()
    sim.turn({"say": "one"})
    sim.turn({"say": "two"})
    assert sim.current == "a" and any("max_node_turns" in w for w in sim.warnings)


def test_turn_counters_reset_on_entry_and_total_persists():
    a = conv("a", transitions=[var_cond("b", "x", "equals", "1")])
    b = conv("b", transitions=[always("a")])
    sim = Simulator(wf("a", [a, b]), variables={"x": "1"})
    sim.start()
    sim.turn({"say": "1"})  # a -> b
    sim.turn({"say": "2"})  # b -> a
    sim.turn({"say": "3"})  # a -> b
    assert sim.table["a.current_turns"] == 0 and sim.table["a.total_turns"] == 2 and sim.table["b.total_turns"] == 1


# ---------------------------------------------------------------------------------------------------------------
# extraction, entry behaviour, variables, end of call
# ---------------------------------------------------------------------------------------------------------------
def test_extraction_honours_enum_and_pattern_and_routes_same_turn():
    schema = [{"name": "order_number", "type": "string", "validation_pattern": "^[0-9]{8}$"},
              {"name": "next_action", "type": "string", "enum_values": ["cancel", "done"]},
              {"name": "days", "type": "integer"}]
    a = conv("a", extraction_schema=schema, transitions=[var_cond("done", "next_action", "equals", "done")])
    sim = Simulator(wf("a", [a, conv("done")]))
    sim.start()
    sim.turn({"say": "x", "extract": {"order_number": "123", "next_action": "cancel_it", "days": "abc", "other": "y"}})
    assert not any(k in sim.table for k in ("order_number", "next_action", "days", "other"))
    ev = [e for e in sim.events if e["event"] == "extraction"][-1]
    assert set(ev["discarded"]) == {"order_number", "next_action", "days", "other"}
    sim.turn({"say": "x", "extract": {"order_number": "12345678", "next_action": "done", "days": "3"}})
    assert sim.table["order_number"] == "12345678" and sim.table["days"] == 3
    assert sim.current == "done"  # the extracted value is available to the same node's transitions in the same turn


def test_on_enter_tts_llm_silent_and_first_entry_only():
    a = conv("a", on_enter={"type": "tts", "text": "Hello {{title}} {{last_name}}, {{unknown}}"}, on_enter_first_entry_only=True, transitions=[always("b")])
    b = conv("b", on_enter={"type": "llm"}, transitions=[always("a")])
    sim = Simulator(wf("a", [a, b]), variables={"title": "Mr", "last_name": "Reyes"}, script={"enter_lines": {"b": "What next?"}})
    sim.start()
    assert sim.transcript[-1]["text"] == "Hello Mr Reyes, {{unknown}}"  # the placeholder is said aloud
    sim.turn({"say": "x"})
    assert sim.current == "b" and sim.transcript[-1]["text"] == "What next?"
    sim.turn({"say": "y", "agent": "line"})
    assert sim.current == "a" and sim.transcript[-1]["text"] == "line"  # no repeated greeting; the model took the turn
    sim2 = Simulator(wf("s", [conv("s")]))
    sim2.start()
    assert sim2.transcript == []  # silent


def test_passthrough_chain_and_default_transition():
    n1 = action_node("n1", [code_tool("vars['k'] = 'v'")], "n2", node_type="code")
    n2 = action_node("n2", [], "c", node_type="api_request")
    n2["transitions"] = [var_cond("x", "nope", "is_set")]  # nothing matches: the default is used, with a warning
    sim = Simulator(wf("n1", [n1, n2, conv("c", on_enter={"type": "tts", "text": "k={{k}}"})]))
    sim.start()
    assert [e["node"] for e in sim.events if e["event"] == "node_enter"] == ["n1", "n2", "c"]
    assert sim.transcript[-1]["text"] == "k=v" and any("passthrough_default_transition" in w for w in sim.warnings)
    n2["passthrough_default_transition"] = ""
    sim = Simulator(wf("n1", [n1, n2, conv("c")]))
    sim.start()
    assert sim.ended and sim.ended_reason == "deadlock"


def test_variables_precedence_and_system_variables():
    w = wf("a", [conv("a")], test_variables={"customer_id": "c_test", "first_name": "Dana", "now": "2026-03-11T10:00"})
    sim = Simulator(w, variables={"customer_id": "c_real"})
    assert sim.table["customer_id"] == "c_real" and sim.table["first_name"] == "Dana" and sim.table["now"] == "2026-03-11T10:00"
    assert sim.table["call.direction"] == "web" and sim.table["call.call_id"] and sim.table["system.iso_utc_now"].endswith("Z")
    assert sim.table["a.current_turns"] == 0 and sim.table["a.total_turns"] == 0


def test_end_call_node_reason_and_lifecycle_tools_after_the_end(capture):
    capture.responses["/res"] = (200, {"ok": True})
    life = api_tool("push_result", capture.base + "/res", {"reason": {"type": "string", "default": "{{outcome}}"}, "fixed": {"type": "string", "default": "{{first_name}}"}, "gone": {"type": "string", "default": "{{missing}}"}},
                    config={"timeoutMs": 2000, "maxRetries": 0, "alwaysRunsAt": ["end_of_call"]}, mapping=[{"path": "data.ok", "variable": "not_mapped_at_end"}])
    start = api_tool("warm", capture.base + "/warm", {}, config={"alwaysRunsAt": ["start_of_call"]}, mapping=[{"path": "data.ok", "variable": "warmed"}])
    idle = api_tool("never", capture.base + "/never", {})  # a workflow-level tool without alwaysRunsAt never runs
    a = conv("a", transitions=[always("bye")], tools=[life])
    sim = Simulator(wf("a", [a, end_node("bye", "closing_end", mode="custom", spoken="Bye {{first_name}}.")], tools=[life, start, idle]),
                    variables={"first_name": "Dana"}, script={"turns": [{"say": "x", "tool_calls": [T("push_result")]}], "end_of_call": {"push_result": {"outcome": "promise"}}})
    rec = sim.run()
    assert rec["ended_reason"] == "closing_end" and rec["transcript"][-1]["text"] == "Bye Dana."
    order = [e["function"] for e in rec["events"] if e["event"] == "function_call_start"]
    assert order == ["warm", "push_result", "push_result"]  # start_of_call first, the end_of_call tool once from the workflow and once from the node the call ended in... see below
    ends = [c for c in rec["tool_calls"] if c["function"] == "push_result"]
    assert all(c["request"]["body"] == {"reason": "promise", "fixed": "Dana"} for c in ends)  # model-filled from the script, unresolved dropped
    assert sim.table["warmed"] is True and "not_mapped_at_end" not in sim.table
    ended_at = [e for e in rec["events"] if e["event"] == "call_ended"][0]
    assert rec["events"].index(ended_at) < rec["events"].index([e for e in rec["events"] if e["event"] == "function_call_start" and e["function"] == "push_result"][0])
    assert any(e["event"] == "error" and "push_result" in e["message"] for e in rec["events"])  # the model cannot call a lifecycle tool
    assert not any(c["function"] == "never" for c in rec["tool_calls"])


def test_end_call_tool_in_tools_ends_with_the_tool_name():
    end_tool = {"type": "function", "function": {"name": "hang_up", "handler": "__function__:end_call", "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}
    sim = Simulator(wf("a", [conv("a", tools=[end_tool])]))
    sim.run()
    sim.turn({"say": "bye", "tool_calls": [T("hang_up")]})
    assert sim.ended and sim.ended_reason == "hang_up"
    sim.turn({"say": "still there?"})
    assert sum(1 for t in sim.transcript if t["role"] == "user") == 1 and any("after the call ended" in w for w in sim.warnings)


def test_record_shape():
    rec = Simulator(wf("a", [conv("a", transitions=[always("e")]), end_node("e", "done")]), script=[{"say": "hi"}]).run()
    assert set(rec) >= {"id", "endedReason", "ended_reason", "transcript", "transcript_text", "messages", "events", "variables", "tool_calls", "warnings"}
    assert rec["transcript"] == [{"role": "user", "text": "hi", "node": "a"}]
    assert all(m["role"] in ("user", "assistant", "system") for m in rec["messages"])
    assert all(isinstance(json.loads(m["message"]), dict) for m in rec["messages"] if m["role"] == "system")
