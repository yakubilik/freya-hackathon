"""Static validator of a Freya workflow dict. Returns a list of findings (empty = clean).

    .venv/bin/python -m builder.emitter.walk WF.json [--table TABLE.json] [--api openapi.json]

Checks: start node and every transition target exist; passthrough nodes end with `always`; every `{{var}}` read
outside code is written somewhere or seeded; every extraction variable has exactly one dispatcher that clears it;
every api_call matches a path and method of the tool API file and sends only fields of its request schema, with
literal enum values inside the enum; no forbidden phrase (exact ones, in the scope the table gives) in any
prompt-like text; no `{{`/`}}` in code; every node reachable from the start reaches an end_call node; every
engine_next value the engine can emit is routed explicitly from every node running the engine; one close node per
closing row with the reason field absent when the row has none; no boolean operands; mapping paths start with
`data`.

What it cannot check: whether the platform behaves as documented (speech on re-entry, hook execution, mapping of
objects), whether the extraction model fills the slots, whether the prompts are followed, non-literal forbidden
content (a forbidden phrase given as a description), and runtime values of variables.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.parse

from builder.engine.snippet import unpack
from builder.readers.api_file import parse_api
from .fragments import ENGINE_MARKER, STAGE_NODE, CLOSE_TOOL

PLACEHOLDER = re.compile(r"\{\{\s*([^{}:\s]+)\s*(?::\s*json)?\s*\}\}")
WRITE_RE = re.compile(r"\b(?:vars|v)\[\s*['\"]([A-Za-z_][\w.]*)['\"]\s*\]\s*=(?!=)")
AUTO_RE = re.compile(r"^(system\.|call\.|extractor\.|date\.|time\.)|(\.current_turns|\.total_turns|_success_count|_failure_count|_status_code)$|_response\.|_args\.")
PRE_VERIFICATION_NODES = ("greeting", "callback", "identity")
THIRD_PARTY_NODES = ("greeting", "callback")
NEGOTIATION_NODES = ("negotiate", "readback")


def _texts(node):
    """(field, text) pairs of everything a model or the caller reads in a node, code excluded."""
    out = []
    for k in ("task_message", "role_message", "loop_prompt", "routing_prompt", "loop_condition", "description"):
        if isinstance(node.get(k), str):
            out.append((k, node[k]))
    oe = node.get("on_enter") or {}
    for k in ("text", "prompt"):
        if isinstance(oe.get(k), str):
            out.append(("on_enter." + k, oe[k]))
    for e in node.get("extraction_schema") or []:
        if isinstance(e, dict):
            out.append(("extraction." + str(e.get("name")), str(e.get("description") or "")))
    for t in node.get("transitions") or []:
        out.append(("transition.description", str(t.get("description") or "")))
        _cond_texts(t.get("condition"), out)
    for fn in _functions(node):
        out.append(("tool.description", str((fn.get("function") or {}).get("description") or "")))
    term = ((node.get("terminal") or {}).get("function") or {}).get("parameters", {}).get("properties", {})
    for k in ("spoken_message", "llm_prompt"):
        if isinstance(term.get(k), dict) and isinstance(term[k].get("default"), str):
            out.append(("terminal." + k, term[k]["default"]))
    return out


def _cond_texts(cond, out):
    if not isinstance(cond, dict):
        return
    if cond.get("operator") == "matches_intent":
        out.append(("intent", str(cond.get("description") or "")))
    for c in cond.get("conditions") or []:
        _cond_texts(c, out)


def _functions(node):
    return [f for f in list(node.get("tools") or []) + list(node.get("pre_actions") or []) if isinstance(f, dict)]


def _codes(node):
    """(where, source) of every Python snippet in a node."""
    out = []
    for fn in _functions(node):
        props = ((fn.get("function") or {}).get("parameters") or {}).get("properties") or {}
        if isinstance(props.get("code"), dict) and isinstance(props["code"].get("default"), str):
            out.append(("code", unpack(props["code"]["default"])))   # the engine node ships packed
        for hook in ("pre_process_code", "post_process_code"):
            if isinstance(fn.get(hook), str) and fn[hook].strip():
                out.append((hook, fn[hook]))
    return out


def _leaves(cond):
    if not isinstance(cond, dict):
        return []
    if "conditions" in cond:
        out = []
        for c in cond.get("conditions") or []:
            out += _leaves(c)
        return out
    return [cond]


def _has_always(cond):
    return isinstance(cond, dict) and cond.get("operator") == "always" and "conditions" not in cond


def _strings(x, out):
    if isinstance(x, str):
        out.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            _strings(v, out)
    elif isinstance(x, list):
        for v in x:
            _strings(v, out)
    return out


def _param(table, path):
    e = ((table or {}).get("parameters") or {}).get(path)
    if not isinstance(e, dict) or e.get("confidence") == "not_specified" or "value" not in e:
        return None
    return e["value"]


def emittable(table):
    """engine_next values the engine can emit for `table` (all of them without a table)."""
    vals = {"party", "identity", "negotiate", "readback", "verify", "fetch", "record", "close", "end", "clarify",
            "callback", "transfer", "note"}
    if table is None:
        return vals
    if _param(table, "third_party.callback.window") is None:
        vals.discard("callback")
    sits = _param(table, "situations") or {}
    if not any(isinstance(s, dict) and s.get("transfer_queue") for s in sits.values()):
        vals.discard("transfer")
    if _param(table, "notes.reasons") is None:
        vals.discard("note")
    return vals


def _scope_nodes(when, nodes):
    w = str(when or "").lower()
    names = list(nodes)
    ours = any(ENGINE_MARKER in src for n in nodes.values() for _, src in _codes(n))
    if not ours:  # not our emitter's naming: every scope is the whole workflow
        return names, True
    def pick(prefixes):
        return [n for n in names if any(n == p or n.startswith(p + "_") for p in prefixes)]
    if "verified" in w and "before" in w:
        return pick(PRE_VERIFICATION_NODES), True
    if "someone else" in w or "third" in w:
        return pick(THIRD_PARTY_NODES), False
    if w.startswith("negotiation"):
        return pick(NEGOTIATION_NODES), False
    return names, True


def _forbidden_items(phrase):
    """The literal strings an exact forbidden phrase stands for; descriptions ('the product name') are skipped."""
    if not phrase.get("exact"):
        return []
    items = [x.strip() for x in str(phrase.get("text") or "").split(";")]
    return [x for x in items if x and not re.match(r"^(the|a|an|any)\s", x, re.I)]


def walk(wf, table=None, api=None):
    findings = []
    nodes = wf.get("nodes") or {}
    glob = wf.get("global_nodes") or {}
    allnodes = dict(nodes)
    allnodes.update(glob)
    start = wf.get("initial_node")
    if start not in nodes:
        findings.append("start node %r does not exist" % start)

    # ---- targets, passthrough, conditions, mappings
    for name, n in allnodes.items():
        for t in n.get("transitions") or []:
            tgt = t.get("target_node")
            if tgt not in allnodes and not (tgt == "__previous__" and name in glob):
                findings.append("%s: transition to unknown node %r" % (name, tgt))
            for lf in _leaves(t.get("condition")):
                if isinstance(lf.get("operand"), bool):
                    findings.append("%s: condition on %s compares a boolean operand" % (name, lf.get("variable")))
        if n.get("passthrough"):
            d = n.get("passthrough_default_transition")
            if d and d not in allnodes:
                findings.append("%s: passthrough_default_transition %r does not exist" % (name, d))
            trs = n.get("transitions") or []
            if not trs or not _has_always(trs[-1].get("condition")):
                findings.append("%s: passthrough node does not end with an always transition" % name)
        maps = list(n.get("response_mapping") or [])
        for fn in _functions(n):
            maps += list(fn.get("response_mapping") or [])
        for m in maps:
            p = str(m.get("path") or "")
            if p != "data" and not p.startswith("data."):
                findings.append("%s: mapping path %r does not start with data." % (name, p))
        if n.get("node_type") == "end_call" and n.get("transitions"):
            findings.append("%s: end_call node has transitions" % name)

    # ---- code: no braces
    for name, n in allnodes.items():
        for where, src in _codes(n):
            if "{{" in src or "}}" in src:
                findings.append("%s: %s contains '{{' or '}}'" % (name, where))

    # ---- variables read versus written
    written = set((wf.get("test_variables") or {}).keys())
    written |= set(_param(table, "call_variables") or [])
    for n in allnodes.values():
        for e in n.get("extraction_schema") or []:
            written.add(e.get("name"))
        for m in list(n.get("response_mapping") or []) + [m for fn in _functions(n) for m in (fn.get("response_mapping") or [])]:
            written.add(m.get("variable"))
        for _, src in _codes(n):
            written |= set(WRITE_RE.findall(src))
    for name, n in allnodes.items():
        texts = [t for _, t in _texts(n)]
        for fn in _functions(n):
            props = ((fn.get("function") or {}).get("parameters") or {}).get("properties") or {}
            texts += _strings({k: v for k, v in props.items() if k != "code"}, [])
        for text in texts:
            for var in PLACEHOLDER.findall(text):
                if var not in written and not AUTO_RE.search(var):
                    findings.append("%s: reads {{%s}}, which nothing writes or seeds" % (name, var))
    sp = wf.get("system_prompt") or ""
    for var in PLACEHOLDER.findall(sp):
        if var not in written and not AUTO_RE.search(var):
            findings.append("system_prompt: reads {{%s}}, which nothing writes or seeds" % var)

    # ---- extraction dispatchers
    for name, n in allnodes.items():
        names = [e.get("name") for e in n.get("extraction_schema") or [] if isinstance(e, dict)]
        if not names:
            continue
        targets = set()
        for t in n.get("transitions") or []:
            if any(lf.get("variable") in names for lf in _leaves(t.get("condition"))):
                targets.add(t.get("target_node"))
        if len(targets) != 1:
            findings.append("%s: extraction routes to %d dispatchers (%s), want exactly one" % (name, len(targets), sorted(targets)))
            continue
        disp = allnodes.get(next(iter(targets))) or {}
        if disp.get("node_type") != "code":
            findings.append("%s: dispatcher %s is not a code node" % (name, next(iter(targets))))
            continue
        src = "\n".join(s for _, s in _codes(disp))
        for var in names:
            if not re.search(r"vars\[\s*['\"]%s['\"]\s*\]\s*=\s*(''|\"\")" % re.escape(var), src):
                findings.append("%s: dispatcher %s does not clear %s" % (name, next(iter(targets)), var))

    # ---- api calls against the tool API file
    if api is not None:
        parsed = api if "tools" in api and "server" in api else parse_api(api)
        by_path = {t["path"]: (tn, t) for tn, t in parsed["tools"].items()}
        for name, n in allnodes.items():
            fns = _functions(n) + ([] if name != start else [])
            for fn in fns:
                f = fn.get("function") or {}
                if not str(f.get("handler") or "").endswith("api_call"):
                    continue
                props = (f.get("parameters") or {}).get("properties") or {}
                url = str((props.get("url") or {}).get("default") or "")
                path = urllib.parse.urlsplit(url).path
                match = [p for p in by_path if path.endswith(p)]
                if not match:
                    findings.append("%s: %s calls %s, which is not a path of the tool API file" % (name, f.get("name"), url))
                    continue
                tn, spec = by_path[max(match, key=len)]
                method = str((props.get("method") or {}).get("default") or "POST").upper()
                if method != spec["method"]:
                    findings.append("%s: %s uses %s, the API says %s" % (name, f.get("name"), method, spec["method"]))
                body = ((props.get("body") or {}).get("properties")) or {}
                for field, leafspec in body.items():
                    if field not in spec["request_fields"]:
                        findings.append("%s: %s sends field %r, not in the %s request schema" % (name, f.get("name"), field, tn))
                        continue
                    enum = spec["request_fields"][field].get("enum")
                    d = leafspec.get("default") if isinstance(leafspec, dict) else None
                    if enum and isinstance(d, str) and not PLACEHOLDER.fullmatch(d.strip()) and d not in enum:
                        findings.append("%s: %s.%s = %r is not in the API enum" % (name, f.get("name"), field, d))
                for field, e in spec["request_fields"].items():
                    if e.get("required") and "." not in field and field not in body:
                        findings.append("%s: %s omits required field %r" % (name, f.get("name"), field))

    # ---- forbidden phrases
    if table is not None:
        for ph in table.get("phrases") or []:
            if ph.get("kind") != "forbidden":
                continue
            scope, with_system = _scope_nodes(ph.get("when"), allnodes)
            for item in _forbidden_items(ph):
                pat = re.compile(r"(?<![\w])" + re.escape(item) + r"(?![\w])", re.I)
                places = [(nm, fld, txt) for nm in scope for fld, txt in _texts(allnodes[nm])]
                if with_system:
                    places.append(("system_prompt", "", sp))
                for nm, fld, txt in places:
                    if pat.search(txt):
                        findings.append("%s %s: forbidden phrase %r (%s)" % (nm, fld, item, ph.get("id")))

    # ---- every reachable node reaches an end_call node
    edges = {nm: set() for nm in allnodes}
    for nm, n in allnodes.items():
        for t in n.get("transitions") or []:
            if t.get("target_node") in allnodes:
                edges[nm].add(t["target_node"])
        if n.get("max_turn_transition") in allnodes:
            edges[nm].add(n["max_turn_transition"])
    reach, todo = set(), [start] if start in allnodes else []
    while todo:
        x = todo.pop()
        if x in reach:
            continue
        reach.add(x)
        todo += list(edges[x])
    ends = {nm for nm, n in allnodes.items() if n.get("node_type") == "end_call"}
    good, changed = set(ends), True
    while changed:
        changed = False
        for nm in allnodes:
            if nm not in good and edges[nm] & good:
                good.add(nm)
                changed = True
    for nm in sorted(reach - good):
        findings.append("%s: no path to an end_call node" % nm)
    if not ends:
        findings.append("the workflow has no end_call node")

    # ---- engine routing coverage
    for nm, n in allnodes.items():
        if not any(ENGINE_MARKER in src for _, src in _codes(n)):
            continue
        routed = set()
        for t in n.get("transitions") or []:
            for lf in _leaves(t.get("condition")):
                if lf.get("variable") == "engine_next" and lf.get("operator") == "equals":
                    routed.add(str(lf.get("operand")))
        for val in sorted(emittable(table) - routed):
            findings.append("%s: engine_next %r has no explicit transition" % (nm, val))

    # ---- one close node per closing row, reason absent when the row has none
    if table is not None:
        # the API may call the close fields otherwise (result / detail): read the wire names like the emitter does
        out_f, rea_f = "outcome", "reason"
        if api:
            try:
                from builder.emitter.wire import request_field_map
                parsed = api if "tools" in api else parse_api(api)
                m = request_field_map(parsed).get(CLOSE_TOOL, {})
                out_f, rea_f = m.get("outcome") or "outcome", m.get("reason") or "reason"
            except Exception:  # noqa: BLE001 - the canonical names are the fallback
                pass
        closes = []
        for nm, n in allnodes.items():
            for fn in _functions(n):
                f = fn.get("function") or {}
                url = str((((f.get("parameters") or {}).get("properties") or {}).get("url") or {}).get("default") or "")
                if f.get("name") == CLOSE_TOOL or url.rstrip("/").endswith("/" + CLOSE_TOOL):
                    body = (((f.get("parameters") or {}).get("properties") or {}).get("body") or {}).get("properties") or {}
                    closes.append((nm, (body.get(out_f) or {}).get("default"), body.get(rea_f)))
        for row in _param(table, "closing.rows") or []:
            o, r = row.get("outcome"), row.get("reason")
            hit = [c for c in closes if c[1] == o and ((r is None and c[2] is None) or (r is not None and isinstance(c[2], dict) and c[2].get("default") == r))]
            if not hit:
                findings.append("closing row %s / %s has no close node with exactly that body" % (o, r))
        for nm, o, r in closes:
            if isinstance(r, dict) and r.get("default") in ("", None):
                findings.append("%s: close_call sends an empty reason" % nm)
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Static walk of a Freya workflow JSON.")
    ap.add_argument("workflow")
    ap.add_argument("--table")
    ap.add_argument("--api")
    a = ap.parse_args(argv)
    wf = json.loads(pathlib.Path(a.workflow).read_text())
    if "workflow" in wf and "nodes" not in wf:
        wf = wf["workflow"]
    table = json.loads(pathlib.Path(a.table).read_text()) if a.table else None
    api = json.loads(pathlib.Path(a.api).read_text()) if a.api else None
    findings = walk(wf, table, api)
    for f in findings:
        print(f)
    print("%d finding(s)" % len(findings), file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
