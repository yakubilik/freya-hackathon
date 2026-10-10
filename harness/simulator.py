"""A deterministic local executor of Freya workflow JSON.

The three model calls of a turn (extraction, routing, dialogue) are replaced by a script, everything else is run
the way the documented engine runs it (kit docs: workflow-format.md, tools-and-code.md): node entry, `{{var}}`
substitution, parameter baking, real HTTP tool calls, pre and post hooks, code nodes, result flattening,
counters, response mapping, deterministic routing, global nodes, end-call terminals and lifecycle tools.

    from harness.simulator import Simulator, rewrite_urls
    record = Simulator(workflow, variables={"customer_id": "c_1"}, script=script).run()

Script (one case):

    {"turns": [
        {"say": "Yes, speaking", "tool_calls": [{"name": "transition_to_identity"}]},
        {"say": "14 March 1988", "tool_calls": [{"name": "verify_identity", "args": {"field": "date_of_birth", "answer": "1988-03-14"}}]},
        {"say": "...", "extract": {"next_action": "done"}, "intents": ["The caller wants to complain"], "loop": false}
     ],
     "enter_lines": {"collect": "What would you like to book?"},     # what an on_enter of type llm says, else "[llm]"
     "end_of_call": {"close_call": {"outcome": "promise"}}}          # model-filled fields of lifecycle tools

The dialogue "model" of a turn does, in order: the listed tool calls (each followed by re-routing), then says the
scripted line. `extract` is checked against the node's extraction_schema (enum_values, validation_pattern).
`intents` lists the matches_intent descriptions that are true for this turn; everything else is false.

The output mirrors the kit's call record (api.md "Get a call"): `messages` with user / assistant rows and
`system` rows whose `message` is a JSON string of one engine event (node_enter, function_call_start,
function_call_complete, route_evaluated, error). The same events are also in `events` as dicts.

CLI:
    .venv/bin/python -m harness.simulator WORKFLOW.json --script SCRIPT.json [--bank http://127.0.0.1:8787 --case PUB-01]
        [--variables '{"customer_id": "c_1"}'] [--skip-initial-code] [--out record.json]
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

PLACEHOLDER = re.compile(r"\{\{\s*([^{}:\s]+)\s*(?::\s*(json))?\s*\}\}")
SAFE_MODULES = ("json", "re", "datetime")
# modules the standard library pulls in behind the safe ones (datetime.strftime imports `time`); never os, sys, socket...
SUPPORT_MODULES = ("time", "math", "_strptime", "calendar", "locale", "_datetime", "copy", "decimal", "string")
DROP = object()  # an engine-run field whose single placeholder did not resolve


# ----------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------
def rewrite_urls(workflow: dict, base: str, origins=None) -> dict:
    """A deep copy of `workflow` in which every tool `url` default points at `base` (scheme://host[:port]),
    keeping the path. With `origins` (a list of "scheme://host" strings) only those origins are rewritten."""
    base = base.rstrip("/")
    wf = copy.deepcopy(workflow)

    def fix(url):
        if not isinstance(url, str) or "://" not in url:
            return url
        p = urllib.parse.urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origins and origin not in origins:
            return url
        return base + p.path + (("?" + p.query) if p.query else "")

    def walk(x):
        if isinstance(x, dict):
            props = x.get("properties")
            if isinstance(props, dict) and isinstance(props.get("url"), dict) and "default" in props["url"]:
                props["url"]["default"] = fix(props["url"]["default"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(wf)
    return wf


def flatten(prefix: str, value, out: dict):
    """Write `value` under `prefix` the way the engine flattens tool results: nested dicts with dots, booleans as
    lowercase strings, lists as JSON strings, scalars as they are."""
    if isinstance(value, dict):
        if not value:
            return
        for k, v in value.items():
            flatten(f"{prefix}.{k}", v, out)
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    elif isinstance(value, list):
        out[prefix] = json.dumps(value)
    else:
        out[prefix] = value


def get_path(obj, path: str):
    """Walk a dot path through dicts (and lists with numeric segments). Returns (found, value)."""
    cur = obj
    for seg in path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return False, None
    return True, cur


def _is_unset(v):
    return v is None or v == ""


def describe_condition(cond) -> str:
    if not isinstance(cond, dict):
        return "?"
    if "logic" in cond:
        joiner = f" {str(cond.get('logic', 'or')).upper()} "
        return "(" + joiner.join(describe_condition(c) for c in cond.get("conditions") or []) + ")"
    op = cond.get("operator")
    if op == "always":
        return "always"
    if op == "matches_intent":
        return f"intent({cond.get('description', '')!r})"
    if op in ("is_set", "is_not_set"):
        return f"{cond.get('variable')} {op}"
    sym = {"equals": "==", "not_equals": "!=", "greater_than": ">", "less_than": "<", "contains": "contains"}.get(op, op)
    return f"{cond.get('variable')} {sym} {cond.get('operand')!r}"


def _has_intent(cond) -> bool:
    if not isinstance(cond, dict):
        return False
    if "logic" in cond:
        return any(_has_intent(c) for c in cond.get("conditions") or [])
    return cond.get("operator") == "matches_intent"


def merge_transitions(transitions):
    """The engine merges transitions of one node with the same target into one whose condition is the OR of the
    originals; an unconditional member makes the merged one unconditional. Tool-call transitions stay apart."""
    out, by_target = [], {}
    for t in transitions or []:
        if not isinstance(t, dict) or not t.get("target_node"):
            continue
        key = t["target_node"]
        if t.get("is_tool_call"):
            out.append(copy.deepcopy(t))
            continue
        if key in by_target:
            m = by_target[key]
            if _is_always(m["condition"]):
                continue
            if _is_always(t.get("condition")):
                m["condition"] = {"operator": "always"}
            else:
                if m["condition"].get("logic") != "or" or m.get("_merged") is not True:
                    m["condition"] = {"logic": "or", "conditions": [m["condition"]]}
                    m["_merged"] = True
                m["condition"]["conditions"].append(copy.deepcopy(t.get("condition") or {"operator": "always"}))
            continue
        c = copy.deepcopy(t)
        c["condition"] = copy.deepcopy(t.get("condition") or {"operator": "always"})
        by_target[key] = c
        out.append(c)
    for t in out:
        t.pop("_merged", None)
    return out


def _is_always(cond) -> bool:
    return isinstance(cond, dict) and cond.get("operator") == "always" and "logic" not in cond


def http_request(url, method, headers, body, timeout_s):
    """One HTTP attempt. Returns (status_code, response_headers, data, error_kind, error_text).
    error_kind is None, "timeout" or "transport"."""
    data = None
    if body is not None and method.upper() not in ("GET", "HEAD"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method.upper(), headers={str(k): str(v) for k, v in (headers or {}).items()})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw, code, hdr = resp.read(), resp.status, dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        raw, code, hdr = e.read(), e.code, dict(e.headers.items())
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return 0, {}, None, "timeout", str(e.reason)
        return 0, {}, None, "transport", str(e.reason)
    except (socket.timeout, TimeoutError) as e:
        return 0, {}, None, "timeout", str(e)
    except OSError as e:
        return 0, {}, None, "transport", str(e)
    try:
        parsed = json.loads(raw.decode() or "null")
    except ValueError:
        parsed = raw.decode(errors="replace")
    return code, hdr, parsed, None, None


class _SandboxImport:
    def __init__(self):
        self.real = __import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".")[0] in SAFE_MODULES or name.split(".")[0] in SUPPORT_MODULES:
            return self.real(name, globals, locals, fromlist, level)
        raise ImportError(f"module {name!r} is not available in the sandbox")


def run_snippet(code: str, names: dict):
    """exec `code` with `names` as globals in a sandbox where only json, re and datetime can be imported."""
    builtins = dict(vars(__builtins__)) if not isinstance(__builtins__, dict) else dict(__builtins__)
    for k in ("open", "exec", "eval", "compile", "input", "exit", "quit", "breakpoint", "help"):
        builtins.pop(k, None)
    builtins["__import__"] = _SandboxImport()
    g = {"__builtins__": builtins, "__name__": "__freya_snippet__"}
    g.update(names)
    exec(compile(code, "<snippet>", "exec"), g)
    return g


# ----------------------------------------------------------------------------------------------------------------
# the simulator
# ----------------------------------------------------------------------------------------------------------------
class Simulator:
    MAX_HOPS = 60  # passthrough chain guard

    def __init__(self, workflow: dict, variables: dict | None = None, script=None, skip_initial_code: bool = False,
                 clock: _dt.datetime | None = None, call_direction: str = "web", http=None):
        self.wf = copy.deepcopy(workflow)
        self.nodes = self.wf.get("nodes") or {}
        self.globals = self.wf.get("global_nodes") or {}
        self.skip_initial_code = skip_initial_code
        self.http = http or http_request
        if isinstance(script, list):
            script = {"turns": script}
        self.script = copy.deepcopy(script or {})
        self.turns = list(self.script.get("turns") or [])
        self.enter_lines = dict(self.script.get("enter_lines") or {})
        self.end_of_call_args = dict(self.script.get("end_of_call") or {})
        self.clock = clock or _dt.datetime.now(_dt.timezone.utc)
        self.call_id = str(uuid.uuid4())
        # the one variable table of the call
        self.table: dict = {}
        for name in list(self.nodes) + list(self.globals):
            self.table[f"{name}.current_turns"] = 0
            self.table[f"{name}.total_turns"] = 0
        self.table.update(self.wf.get("test_variables") or {})
        self.table.update(dict(self.script.get("variables") or {}))
        self.table.update(variables or {})
        self.table["call.call_id"] = self.call_id
        self.table["call.direction"] = call_direction
        utc = self.clock.astimezone(_dt.timezone.utc)
        self.table["system.iso_utc_now"] = utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        self.table["system.todays_date_en_cst"] = (utc - _dt.timedelta(hours=6)).strftime("%d %B %Y %A %H:%M")
        self.table["system.todays_date_en_est"] = (utc - _dt.timedelta(hours=5)).strftime("%d %B %Y %A %H:%M")
        self.table["system.todays_date_tr.iso_8601"] = (utc + _dt.timedelta(hours=3)).strftime("%Y-%m-%d")
        # merged transitions per node, computed at load time
        self.transitions = {n: merge_transitions(nd.get("transitions")) for n, nd in self.nodes.items()}
        self.transitions.update({n: merge_transitions(nd.get("transitions")) for n, nd in self.globals.items()})
        # call state
        self.current: str | None = None
        self.previous: str | None = None  # the node a global node interrupted
        self.entered: set = set()
        self.baked: dict = {}  # node -> tool name -> {tool, baked, model (exposed parameter names)}
        self.ended = False
        self.ended_reason: str | None = None
        self.messages: list = []
        self.events: list = []
        self.transcript: list = []
        self.tool_calls: list = []
        self.warnings: list = []
        self._seq = 0
        self._spoke_this_turn = False
        self._hops = 0

    # ---- record keeping ----------------------------------------------------------------------------------------
    def _stamp(self):
        self._seq += 1
        return self._seq

    def _message(self, role, text, extra=None):
        n = self._stamp()
        m = {"role": role, "message": text, "messageId": f"msg_{n}", "secondsFromStart": round(n * 0.01, 2), "nodeId": self.current}
        if extra:
            m.update(extra)
        self.messages.append(m)
        return m

    def event(self, kind, **data):
        ev = {"event": kind, **data}
        self.events.append(ev)
        self._message("system", json.dumps(ev, default=str))
        return ev

    def warn(self, text, **data):
        self.warnings.append(text)
        self.event("simulator_warning", message=text, **data)

    def say(self, text):
        self.transcript.append({"role": "assistant", "text": text, "node": self.current})
        self._message("assistant", text)
        self._spoke_this_turn = True

    def hear(self, text):
        self.transcript.append({"role": "user", "text": text, "node": self.current})
        self._message("user", text)

    def transcript_text(self):
        return "\n".join(("AGENT: " if t["role"] == "assistant" else "USER: ") + t["text"] for t in self.transcript)

    # ---- variables ----------------------------------------------------------------------------------------------
    def lookup(self, name: str):
        """(found, value) of a variable; a few system names are computed."""
        if name in self.table:
            return True, self.table[name]
        if name == "system.conversation":
            return True, self.transcript_text()
        m = re.fullmatch(r"system\.conversation\.last-(\d+)", name)
        if m:
            n = int(m.group(1))
            lines = self.transcript_text().split("\n")
            return True, "\n".join(lines[-n:])
        if name == "call.duration":
            return True, int(self._seq * 0.01)
        return False, None

    def substitute(self, text, engine: bool = False):
        """`{{var}}` substitution. In prompt mode an unresolved placeholder stays literal. In engine mode a field
        that is exactly one unresolved placeholder is DROPped, a mixed value keeps the literal text, and a field
        that is exactly one resolved placeholder keeps the value's type."""
        if not isinstance(text, str):
            return text
        m = PLACEHOLDER.fullmatch(text.strip()) if engine else None
        if m:
            found, val = self.lookup(m.group(1))
            if not found or val is None:
                return DROP
            return json.dumps(val) if m.group(2) else val

        def repl(mm):
            found, val = self.lookup(mm.group(1))
            if not found or val is None:
                return mm.group(0)
            if mm.group(2):
                return json.dumps(val)
            return val if isinstance(val, str) else json.dumps(val) if isinstance(val, (dict, list)) else str(val)

        return PLACEHOLDER.sub(repl, text)

    # ---- tool parameters ------------------------------------------------------------------------------------------
    def bake(self, tool: dict) -> dict:
        """Resolve the `default`s of a tool against the variable table (the engine does this when the node is
        entered). Returns {"config": {url, method, headers, body}, "model": {field: (path, var)}, "required": [...]}
        where `model` lists the fields the model must fill."""
        params = ((tool.get("function") or {}).get("parameters") or {}).get("properties") or {}
        cfg = {"url": None, "method": "POST", "headers": {}, "body": {}}
        model, required = {}, []

        def take(spec, path, field):
            if not isinstance(spec, dict):
                return
            if "default" in spec:
                val = self.substitute(spec["default"], engine=True)
                if val is DROP:
                    var = PLACEHOLDER.fullmatch(str(spec["default"]).strip()).group(1)
                    model[field] = (path, var)
                else:
                    self._set_cfg(cfg, path, val)
            else:
                model[field] = (path, field)

        for name, spec in params.items():
            if name in ("headers", "body") and isinstance(spec, dict) and isinstance(spec.get("properties"), dict):
                for f, s in spec["properties"].items():
                    take(s, (name, f), f)
                required += [f for f in (spec.get("required") or []) if isinstance(f, str)]
            elif name == "connect_retries":
                continue
            else:
                take(spec, (name,), name)
        if "method" not in cfg or cfg["method"] is None:
            cfg["method"] = "POST"
        return {"config": cfg, "model": model, "required": required}

    @staticmethod
    def _set_cfg(cfg, path, val):
        if len(path) == 1:
            cfg[path[0]] = val
        else:
            cfg.setdefault(path[0], {})[path[1]] = val

    def build_request(self, baked: dict, args: dict | None, tool_name: str, record_args: bool = True):
        """The request of one call: baked config plus the model-filled `args`. Writes `<tool>_args.<field>`."""
        cfg = copy.deepcopy(baked["config"])
        args = dict(args or {})
        by_var = {var: field for field, (_, var) in baked["model"].items()}
        for k, v in args.items():
            field = k if k in baked["model"] else by_var.get(k)
            if field is None:
                if self._field_is_baked(baked, k):
                    self.warn(f"{tool_name}: argument {k!r} ignored, the field is baked from a variable and hidden from the model", tool=tool_name, field=k)
                else:
                    self.warn(f"{tool_name}: argument {k!r} is not a parameter of the tool", tool=tool_name, field=k)
                continue
            path, _ = baked["model"][field]
            self._set_cfg(cfg, path, v)
            if record_args:
                self.table[f"{tool_name}_args.{field}"] = v
        for field in baked["required"]:
            if field in baked["model"] and field not in args and baked["model"][field][1] not in args:
                self.warn(f"{tool_name}: required model field {field!r} was not given by the script", tool=tool_name, field=field)
        return cfg

    @staticmethod
    def _field_is_baked(baked, name):
        cfg = baked["config"]
        return name in cfg or name in (cfg.get("body") or {}) or name in (cfg.get("headers") or {})

    # ---- running tools -------------------------------------------------------------------------------------------
    def run_api_call(self, tool: dict, prefix: str, request: dict, node_mapping=None, apply_mapping=True):
        """One api_call with hooks, retries, envelope, flattening, counters and response_mapping."""
        fn = tool.get("function") or {}
        name = fn.get("name") or prefix
        conf = tool.get("config") or {}
        timeout_ms = conf.get("timeoutMs")
        timeout_s = (float(timeout_ms) / 1000.0) if timeout_ms else 30.0
        retries = int(conf.get("maxRetries") or 0)
        config = {"url": request.get("url"), "method": request.get("method") or "POST", "headers": dict(request.get("headers") or {}), "body": request.get("body")}
        pre = tool.get("pre_process_code")
        if isinstance(pre, str) and pre.strip():
            try:
                run_snippet(pre, {"vars": self.table, "config": config})
            except Exception as e:  # what the platform does when a hook raises is not documented
                self.event("error", message=f"pre_process_code of {name} raised", details=repr(e))
        result = None
        for attempt in range(retries + 1):
            self.event("function_call_start", function=name, args=copy.deepcopy(config), **({"attempt": attempt + 1} if attempt else {}))
            if not config.get("url"):
                result = {"status": "error", "data": None, "message": "URL is required", "status_code": 0, "header": {}}
            else:
                code, hdr, data, kind, err = self.http(config["url"], config.get("method") or "POST", config.get("headers") or {}, config.get("body"), timeout_s)
                if kind == "timeout":
                    result = {"status": "error", "data": None, "message": f"Request timed out after {int(timeout_s * 1000)} ms", "status_code": 0, "header": {}}
                elif kind == "transport":
                    result = {"status": "error", "data": None, "message": f"Request failed: {err}", "status_code": 0, "header": {}}
                elif code >= 400:
                    result = {"status": "error", "data": data, "message": f"HTTP {code}", "status_code": code, "header": hdr}
                else:
                    result = {"status": "success", "data": data, "message": f"Successfully executed {str(config.get('method') or 'POST').upper()} request", "status_code": code, "header": hdr}
            self.tool_calls.append({"function": name, "prefix": prefix, "node": self.current, "request": copy.deepcopy(config), "result": copy.deepcopy(result), "attempt": attempt + 1})
            if result["status"] == "success" or not (result["status_code"] == 0 or result["status_code"] >= 500):
                break
        post = tool.get("post_process_code")
        if isinstance(post, str) and post.strip():
            try:
                run_snippet(post, {"vars": self.table, "result": result})
            except Exception as e:
                self.event("error", message=f"post_process_code of {name} raised", details=repr(e))
        self.event("function_call_complete", function=name, result=copy.deepcopy(result))
        self._record_result(prefix, result)
        mapping = node_mapping if node_mapping is not None else tool.get("response_mapping")
        if apply_mapping:
            self.apply_mapping(mapping, result, prefix)
        return result

    def _record_result(self, prefix: str, result: dict):
        flat = {}
        flatten(f"{prefix}_response", result, flat)
        self.table.update(flat)
        self.table[f"{prefix}_status_code"] = result.get("status_code")
        ok = result.get("status") == "success"
        key = f"{prefix}_success_count" if ok else f"{prefix}_failure_count"
        self.table[key] = int(self.table.get(key) or 0) + 1

    def apply_mapping(self, mapping, result, prefix):
        for m in mapping or []:
            if not isinstance(m, dict) or not m.get("path") or not m.get("variable"):
                continue
            found, val = get_path(result, m["path"])
            if found:
                self.table[m["variable"]] = val
            else:
                self.event("simulator_note", message=f"response_mapping of {prefix}: path {m['path']!r} not found in the result; variable {m['variable']!r} left unchanged")

    def run_code_exec(self, tool: dict, prefix: str, args: dict | None = None):
        params = ((tool.get("function") or {}).get("parameters") or {}).get("properties") or {}
        code = (params.get("code") or {}).get("default")
        if args and "code" in args and not code:
            code = args["code"]
        names = {"vars": self.table}
        for k, v in (args or {}).items():
            if k != "code":
                names[k] = v
                self.table[f"{prefix}_args.{k}"] = v
        self.event("function_call_start", function=(tool.get("function") or {}).get("name") or "code_exec", args={"code": code, **{k: v for k, v in names.items() if k != "vars"}})
        if "{{" in str(code) or "}}" in str(code):
            self.warn(f"{prefix}: the code contains '{{{{' or '}}}}'; the platform may template it and break the snippet", tool=prefix)
        try:
            run_snippet(str(code or ""), names)
            result = {"status": "success", "data": None, "message": "Code executed successfully", "status_code": 200}
        except Exception as e:
            result = {"status": "error", "data": None, "message": f"Code execution failed: {e!r}", "status_code": 500}
            self.event("error", message=f"code_exec in {prefix} raised", details=repr(e))
        self.tool_calls.append({"function": "code_exec", "prefix": prefix, "node": self.current, "request": {"code": code}, "result": copy.deepcopy(result), "attempt": 1})
        self.event("function_call_complete", function=(tool.get("function") or {}).get("name") or "code_exec", result=copy.deepcopy(result))
        self._record_result(prefix, result)
        return result

    def run_pre_action(self, node_name: str, node: dict, action: dict):
        handler = str(((action.get("function") or {}).get("handler")) or "")
        if handler.endswith("code_exec"):
            return self.run_code_exec(action, node_name)
        if handler.endswith("api_call"):
            baked = self.bake(action)
            # an engine-run call: every unresolved single placeholder is dropped from the request
            cfg = baked["config"]
            for field, (path, var) in baked["model"].items():
                self.event("simulator_note", message=f"{node_name}: field {field!r} ({{{{{var}}}}}) unresolved and dropped from the engine-run request")
            return self.run_api_call(action, node_name, cfg, node_mapping=node.get("response_mapping") or [])
        if handler.endswith("end_call"):
            return self.finish((action.get("function") or {}).get("name") or "end_call", action)
        self.event("error", message=f"unsupported handler {handler!r} in pre_actions of {node_name}", details="")
        return None

    def run_lifecycle(self, when: str, node_name: str | None = None):
        tools = list(self.wf.get("tools") or [])
        # Node-level lifecycle tools belong only to the initial/ending node, not prior visits.
        node = self.nodes.get(node_name) or self.globals.get(node_name) or {}
        if (node.get("node_type") or "conversation") == "conversation":
            tools += list(node.get("tools") or [])
        for tool in tools:
            runs_at = ((tool.get("config") or {}).get("alwaysRunsAt")) or []
            if when not in runs_at:
                continue
            fn = tool.get("function") or {}
            name = fn.get("name") or "lifecycle"
            handler = str(fn.get("handler") or "")
            self.event("simulator_note", message=f"lifecycle tool {name} fires at {when}")
            if handler.endswith("api_call"):
                baked = self.bake(tool)
                args = dict(self.end_of_call_args.get(name) or {}) if when == "end_of_call" else {}
                if baked["model"] and not args:
                    self.event("simulator_note", message=f"{name}: unresolved fields {sorted(baked['model'])} would be filled by one model call; no script args given, fields dropped")
                request = self.build_request(baked, args, name)
                self.run_api_call(tool, name, request, apply_mapping=(when == "start_of_call"))
            elif handler.endswith("code_exec"):
                self.run_code_exec(tool, name)

    # ---- conditions and routing --------------------------------------------------------------------------------
    def eval_condition(self, cond, intents, leaf_results=None):
        """(result, record) in the shape of a route_evaluated branch's condition_results."""
        if not isinstance(cond, dict):
            return False, {"operator": None, "result": False}
        if "logic" in cond:
            logic = str(cond.get("logic") or "or").lower()
            subs = [self.eval_condition(c, intents) for c in cond.get("conditions") or []]
            results = [r for r, _ in subs]
            res = all(results) if logic == "and" else any(results)
            if not subs:
                res = False
            return res, {"logic": logic, "result": res, "conditions": [rec for _, rec in subs]}
        op = cond.get("operator")
        var = cond.get("variable")
        operand = cond.get("operand")
        found, val = self.lookup(var) if var else (False, None)
        rec = {"operator": op, "variable": var, "operand": operand, "result": False}
        if op == "always":
            res = True
        elif op == "matches_intent":
            desc = str(cond.get("description") or "").strip()
            res = desc in intents
            rec["description"] = desc
        elif op == "equals":
            res = str(val) == str(operand)
        elif op == "not_equals":
            res = str(val) != str(operand)
        elif op == "greater_than":
            try:
                res = float(val) > float(operand)
            except (TypeError, ValueError):
                res = False
        elif op == "less_than":
            try:
                res = float(val) < float(operand)
            except (TypeError, ValueError):
                res = False
        elif op == "contains":
            res = (not _is_unset(val)) and str(operand).lower() in str(val).lower()
        elif op == "is_set":
            res = found and not _is_unset(val)
        elif op == "is_not_set":
            res = not found or _is_unset(val)
        else:
            self.event("error", message=f"unknown condition operator {op!r}", details=json.dumps(cond))
            res = False
        rec["result"] = res
        if var:
            rec["value"] = val
        return res, rec

    def route(self, trigger: str, intents=(), loop: bool = False):
        """Routing after a user message or a tool result. Returns the target node key, or None."""
        intents = {str(i).strip() for i in (intents or [])}
        node = self.nodes.get(self.current) or self.globals.get(self.current) or {}
        branches, target, reason = [], None, "No transition matched"
        if trigger == "user_message" and node.get("loop_condition") and loop:
            target, reason = self.current, "loop_condition matched"
            branches.append({"target": self.current, "description": "loop_condition", "result": True, "condition_results": {"operator": "loop_condition", "result": True}})
        if target is None:
            trans = [t for t in self.transitions.get(self.current, []) if not t.get("is_tool_call")]
            # deterministic conditions first, then the ones that need the routing model
            ordered = [t for t in trans if not _has_intent(t["condition"])] + [t for t in trans if _has_intent(t["condition"])]
            for t in ordered:
                res, rec = self.eval_condition(t["condition"], intents)
                branches.append({"target": t["target_node"], "description": describe_condition(t["condition"]), "result": res, "condition_results": rec})
                if res:
                    target, reason = t["target_node"], f"transition matched: {t.get('description', '')}"
                    break
        if target is None:
            for gname, g in self.globals.items():
                if g.get("is_tool_call") or self.current in (g.get("excluded_nodes") or []) or gname == self.current:
                    continue
                res, rec = self.eval_condition(g.get("condition") or {"operator": "always"}, intents)
                branches.append({"target": gname, "description": "global: " + describe_condition(g.get("condition")), "result": res, "condition_results": rec})
                if res:
                    target, reason = gname, f"global node matched: {g.get('description', '')}"
                    break
        self.event("route_evaluated", matched=target is not None, from_node=self.current, target=target, reason=reason, trigger=trigger,
                   branches=branches, variable_table=copy.deepcopy(self.table))
        return target

    def route_and_go(self, trigger, intents=(), loop=False):
        target = self.route(trigger, intents, loop)
        if target is not None and target != self.current:
            self.enter(target, reason=f"routing after {trigger}")
        elif target is not None and trigger == "user_message" and loop:
            node = self.nodes.get(target) or self.globals.get(target) or {}
            if node.get("loop_condition"):
                self.event("simulator_note", node=target,
                           message="loop_condition matched; staying without re-running on_enter")
        # A self-transition or a matching loop condition keeps the current node visit.
        return target

    # ---- node entry ------------------------------------------------------------------------------------------------
    def resolve_target(self, name):
        if name == "__previous__":
            return self.previous or self.current
        return name

    def enter(self, name: str, reason: str = "", from_node: str | None = None):
        if self.ended:
            return
        self._hops += 1
        if self._hops > self.MAX_HOPS:
            self.event("error", message="too many node entries without a user turn (passthrough loop?)", details=name)
            self.finish("simulator_loop_guard")
            return
        name = self.resolve_target(name)
        is_global = name in self.globals and name not in self.nodes
        node = self.nodes.get(name) if name in self.nodes else self.globals.get(name)
        prev = self.current if from_node is None else from_node
        if node is None:
            self.event("error", message=f"transition to unknown node {name!r}", details="")
            self.finish("invalid_target")
            return
        if is_global and (self.current not in self.globals):
            self.previous = self.current
        self.current = name
        # Reset this visit's counter on entry; total_turns is call-wide.
        self.table[f"{name}.current_turns"] = 0
        self.event("node_enter", node=name, from_node=prev, reason=reason)
        first = name not in self.entered
        self.entered.add(name)
        ntype = node.get("node_type") or "conversation"
        # entry behaviour
        oe = node.get("on_enter") or {"type": "llm"}
        skip = bool(node.get("on_enter_first_entry_only")) and not first
        if not skip:
            t = oe.get("type", "llm")
            if t == "tts":
                self.say(self.substitute(str(oe.get("text") or "")))
            elif t == "llm":
                if ntype == "conversation":
                    self.say(self.substitute(str(self.enter_lines.get(name) or "[llm]")))
            elif t == "silent":
                pass
            elif t == "audio":
                self.say("[audio]")
        # tools of a conversation node are baked now
        if ntype == "conversation":
            self.baked[name] = {}
            for tool in node.get("tools") or []:
                fn = tool.get("function") or {}
                if fn.get("name"):
                    baked = self.bake(tool)
                    self.baked[name][fn["name"]] = {"tool": tool, "baked": baked, "model": set(baked["model"])}
            if node.get("pre_actions"):
                self.event("simulator_note", message=f"{name}: pre_actions on a conversation node are stripped by the platform; not run")
        # engine-run actions
        if ntype in ("api_request", "code") or (ntype not in ("conversation", "end_call") and node.get("pre_actions")):
            if self.skip_initial_code and ntype == "code" and name == self.wf.get("initial_node") and first:
                self.event("simulator_note", message=f"{name}: initial code node skipped (chat-route emulation)")
            else:
                for action in node.get("pre_actions") or []:
                    if self.ended:
                        return
                    self.run_pre_action(name, node, action)
            if node.get("tools"):
                self.event("simulator_note", message=f"{name}: tools on a non-conversation node are stripped by the platform; ignored")
        if self.ended:
            return
        if ntype == "end_call":
            term = node.get("terminal") or {}
            fn = term.get("function") or {}
            self.finish(fn.get("name") or "end_call", term)
            return
        if node.get("passthrough"):
            target = self.route("passthrough")
            if target is None:
                default = node.get("passthrough_default_transition")
                if default:
                    self.warn(f"{name}: no transition matched on a passthrough node; using passthrough_default_transition {default!r} (the docs say such a node may deadlock on the platform)", node=name)
                    target = default
                else:
                    self.event("error", message=f"passthrough node {name} deadlocked: no transition matched and no passthrough_default_transition", details="")
                    self.finish("deadlock")
                    return
            self.enter(target, reason="passthrough")
        elif ntype in ("api_request", "code"):
            # a non-passthrough action node: routing still runs on the tool results it just produced
            self.route_and_go("tool_result")

    def finish(self, reason: str, terminal: dict | None = None):
        if self.ended:
            return
        node_at_end = self.current
        if terminal:
            props = (((terminal.get("function") or {}).get("parameters") or {}).get("properties")) or {}
            mode = (props.get("message_mode") or {}).get("default", "custom")
            if mode == "custom":
                msg = (props.get("spoken_message") or {}).get("default")
                if msg:
                    self.say(self.substitute(str(msg)))
            elif mode == "llm":
                self.say("[llm farewell]")
        self.ended = True
        self.ended_reason = reason
        self.table["call.call_end_reason"] = reason
        self.event("call_ended", endedReason=reason, node=node_at_end)
        self.run_lifecycle("end_of_call", node_at_end)

    # ---- the dialogue model's tool calls ----------------------------------------------------------------------------
    def call_tool(self, name: str, args: dict | None):
        if self.ended:
            return
        if name.startswith("transition_to_"):
            target = name[len("transition_to_"):]
            own = [t for t in self.transitions.get(self.current, []) if t.get("is_tool_call") and t.get("target_node") == target]
            g = self.globals.get(target)
            if own or (g and g.get("is_tool_call") and self.current not in (g.get("excluded_nodes") or [])):
                self.event("function_call_start", function=name, args=dict(args or {}))
                self.event("function_call_complete", function=name, result={"status": "success", "data": {"transition": target}, "message": f"Transitioning to {target}", "status_code": 200})
                self.enter(target, reason=f"tool call {name}")
            else:
                self.event("error", message=f"The function `{name}` is not currently available.", details=f"node {self.current} has no tool-call transition to {target}")
            return
        entry = (self.baked.get(self.current) or {}).get(name)
        if entry is None:
            self.event("error", message=f"The function `{name}` is not currently available.", details=f"node {self.current} does not list {name}")
            return
        tool, baked = entry["tool"], entry["baked"]
        if ((tool.get("config") or {}).get("alwaysRunsAt")):
            self.event("error", message=f"The function `{name}` is not currently available.", details="lifecycle tools are never shown to the model")
            return
        handler = str(((tool.get("function") or {}).get("handler")) or "")
        if handler.endswith("api_call"):
            request = self.build_request(baked, args, name)
            self.run_api_call(tool, name, request)
            self.route_and_go("tool_result")
        elif handler.endswith("end_call"):
            self.event("function_call_start", function=name, args=dict(args or {}))
            self.event("function_call_complete", function=name, result={"status": "success", "data": None, "message": "Call ended", "status_code": 200})
            self.finish(name, tool)
        elif handler.endswith("code_exec"):
            self.run_code_exec(tool, name, args)
            self.route_and_go("tool_result")
        else:
            self.event("error", message=f"unsupported handler {handler!r} for tool {name}", details="")

    # ---- extraction -----------------------------------------------------------------------------------------------
    def extract(self, values: dict):
        node = self.nodes.get(self.current) or self.globals.get(self.current) or {}
        schema = {s.get("name"): s for s in (node.get("extraction_schema") or []) if isinstance(s, dict)}
        accepted, discarded = {}, {}
        for k, v in (values or {}).items():
            spec = schema.get(k)
            if spec is None:
                discarded[k] = "not in this node's extraction_schema"
                continue
            t = str(spec.get("type") or "string")
            try:
                if t == "integer":
                    v = int(v)
                elif t == "float":
                    v = float(v)
                elif t == "boolean":
                    v = v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")
                else:
                    v = v if isinstance(v, str) else str(v)
            except (TypeError, ValueError):
                discarded[k] = f"not a {t}"
                continue
            if spec.get("enum_values") and str(v) not in [str(e) for e in spec["enum_values"]]:
                discarded[k] = f"not one of enum_values {spec['enum_values']}"
                continue
            pat = spec.get("validation_pattern")
            if pat and not re.search(pat, str(v)):
                discarded[k] = f"does not match validation_pattern {pat!r}"
                continue
            accepted[k] = v
            self.table[k] = v
        self.event("extraction", node=self.current, accepted=accepted, discarded=discarded)
        return accepted

    # ---- turns ----------------------------------------------------------------------------------------------------
    def start(self):
        self.run_lifecycle("start_of_call", self.wf.get("initial_node"))
        self.enter(self.wf.get("initial_node"), reason="initial_node", from_node=None)
        self._hops = 0

    def turn(self, t: dict):
        if self.ended:
            self.warn("script turn after the call ended; ignored")
            return
        self._hops = 0
        self._spoke_this_turn = False
        text = t.get("say")
        if text is None:
            text = ""
        self.hear(str(text))
        self.table[f"{self.current}.current_turns"] = int(self.table.get(f"{self.current}.current_turns") or 0) + 1
        self.table[f"{self.current}.total_turns"] = int(self.table.get(f"{self.current}.total_turns") or 0) + 1
        node = self.nodes.get(self.current) or self.globals.get(self.current) or {}
        if t.get("extract"):
            self.extract(t["extract"])
        cap = node.get("max_node_turns")
        if cap is None:
            cap = 10
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            cap = 10
        moved = False
        if int(self.table.get(f"{self.current}.current_turns") or 0) >= cap:
            mt = node.get("max_turn_transition")
            if mt:
                self.event("simulator_note", message=f"{self.current}: max_node_turns {cap} reached, moving to {mt}")
                self.enter(mt, reason="max_node_turns reached")
                moved = True
            else:
                self.warn(f"{self.current}: max_node_turns {cap} reached without max_turn_transition; the engine records the overrun and continues", node=self.current)
        if not self.ended and not moved:
            self.route_and_go("user_message", t.get("intents") or [], bool(t.get("loop")))
        for tc in t.get("tool_calls") or []:
            if self.ended:
                break
            if isinstance(tc, str):
                tc = {"name": tc}
            self.call_tool(str(tc.get("name") or ""), tc.get("args") or {})
        if self.ended:
            return
        cur = self.nodes.get(self.current) or self.globals.get(self.current) or {}
        if (cur.get("node_type") or "conversation") == "conversation" and not self._spoke_this_turn:
            self.say(self.substitute(str(t.get("agent") if t.get("agent") is not None else "[llm]")))
        elif t.get("agent") is not None and self._spoke_this_turn:
            self.event("simulator_note", message="scripted agent line skipped: a fixed entry line was spoken in this turn")

    def run(self) -> dict:
        self.start()
        for t in self.turns:
            if self.ended:
                break
            self.turn(t)
        return self.record()

    def record(self) -> dict:
        return {
            "id": self.call_id,
            "endedReason": self.ended_reason,
            "ended_reason": self.ended_reason,
            "ended": self.ended,
            "current_node": self.current,
            "transcript": list(self.transcript),
            "transcript_text": self.transcript_text(),
            "messages": list(self.messages),
            "events": list(self.events),
            "variables": copy.deepcopy(self.table),
            "tool_calls": list(self.tool_calls),
            "warnings": list(self.warnings),
        }


# ----------------------------------------------------------------------------------------------------------------
# convenience
# ----------------------------------------------------------------------------------------------------------------
def open_bank_session(bank: str, case=None, customer=None, team_key: str = "local"):
    body = {"case": case} if case else {"customer": customer}
    req = urllib.request.Request(bank.rstrip("/") + "/v1/practice/sessions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-team-key": team_key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def bank_ledger(bank: str, customer_id: str):
    with urllib.request.urlopen(bank.rstrip("/") + "/v1/practice/ledger/" + customer_id, timeout=20) as r:
        return json.load(r)


def run_case(workflow: dict, script, bank: str, case=None, customer=None, variables=None, skip_initial_code=False, team_key="local"):
    """Open a bank session, point the workflow at the bank, run the script, return (record, ledger, session)."""
    session = open_bank_session(bank, case=case, customer=customer, team_key=team_key)
    if not session.get("ok"):
        raise RuntimeError(f"bank session failed: {session}")
    vars_ = dict(session.get("variables") or {})
    vars_.update(variables or {})
    sim = Simulator(rewrite_urls(workflow, bank), variables=vars_, script=script, skip_initial_code=skip_initial_code)
    record = sim.run()
    ledger = bank_ledger(bank, vars_["customer_id"])
    return record, ledger, session


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a Freya workflow JSON locally on a scripted conversation.")
    ap.add_argument("workflow", help="workflow JSON file (the value of `workflow`, or a {name, workflow} wrapper)")
    ap.add_argument("--script", required=True, help="script JSON file: {turns: [...], enter_lines: {}, end_of_call: {}}")
    ap.add_argument("--bank", help="base URL of a local bank; opens a practice session and rewrites tool urls to it")
    ap.add_argument("--case", help="bank case id, for example PUB-01 (needs --bank)")
    ap.add_argument("--variables", help="JSON object of call variables (win over test_variables)")
    ap.add_argument("--skip-initial-code", action="store_true", help="emulate the chat route: the initial code node does not run")
    ap.add_argument("--out", help="write the call record (JSON) to this file")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    wf = json.load(open(a.workflow))
    if "workflow" in wf and "nodes" not in wf:
        wf = wf["workflow"]
    script = json.load(open(a.script))
    variables = json.loads(a.variables) if a.variables else {}
    ledger = None
    if a.bank:
        record, ledger, _ = run_case(wf, script, a.bank, case=a.case, variables=variables, skip_initial_code=a.skip_initial_code)
    else:
        record = Simulator(wf, variables=variables, script=script, skip_initial_code=a.skip_initial_code).run()
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"record": record, "ledger": ledger}, f, indent=1, default=str)
    if not a.quiet:
        for t in record["transcript"]:
            print(("AGENT" if t["role"] == "assistant" else "USER ") + f" [{t['node']}]: {t['text']}")
        print("tool calls:", " > ".join(f"{c['function']}({c['result'].get('status')})" for c in record["tool_calls"]) or "(none)")
        print("ended:", record["ended"], "reason:", record["ended_reason"], "node:", record["current_node"])
        for w in record["warnings"]:
            print("warning:", w)
        if ledger is not None:
            print("ledger:", json.dumps({k: ledger.get(k) for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers")}))
            print("bank calls:", " > ".join(c["tool"] for c in ledger.get("calls", [])))
    return 0 if record["ended"] else 1


if __name__ == "__main__":
    sys.exit(main())
