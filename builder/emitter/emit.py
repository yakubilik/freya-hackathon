"""Compile a frozen rule table plus the tool API file into a complete Freya workflow (deterministic, offline).

    from builder.emitter import emit
    wf = emit(table, api, variant="final")                       # api: parsed (load_api) or the raw OpenAPI dict

    .venv/bin/python -m builder.emitter.emit fixtures/tables/brief-a.json \
        --api kit/build-the-builder/tools/openapi.json --out /tmp/brief-a.workflow.json [--variant test --bank-url URL]

The CLI also runs the static walk (walk.py) and exits non-zero when it finds anything.

Plan: the engine runs the collections order (party, verify, fetch, disclose, negotiate, readback, record, note,
close). `table["plan"]` is read only when present and only to order the known fragments in the output; an unknown
stage type, a repeated stage, a missing stage the engine always uses, or a broken hard rule is an EmitError.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse

from builder.engine.snippet import pack, render
from builder.emitter import wire
from builder.readers.api_file import parse_api
from . import fragments as F
from .fragments import EmitError

DEFAULT_PLAN = ["party", "verify", "fetch", "disclose", "negotiate", "readback", "record", "note", "close"]
REQUIRED_STAGES = ["party", "verify", "fetch", "negotiate", "readback", "record", "close"]
GATE_TYPES = {"consent", "say", "ask", "prompt_only"}
SAMPLE_CALL_VARS = {"customer_id": "c_test", "first_name": "Dana", "last_name": "Reyes", "title": "Ms",
                    "now": "2026-10-14T11:00"}


class Ctx:
    """Everything the fragments read, derived once from the table and the API file."""

    def __init__(self, table, api, base_url):
        self.table = table
        self.api = api
        self.base_url = base_url
        params = table.get("parameters") or {}
        self.params = params
        self.call_vars = list(self.param("call_variables") or ["customer_id", "first_name", "last_name", "title", "now"])
        self.max_items = int(self.param("multi.max_items") or 3)
        words = [str(w).replace("{customer_own_name}", "their own name") for w in (self.param("party.confirmation_words") or [])]
        self.confirm_words = ", ".join(words) if words else "a clear yes or their own name"
        decline = self.param("identity.decline_rule") or {}
        self.decline_extra = (", or asks what the call is about instead of answering"
                              if isinstance(decline, dict) and decline.get("question_about_call_counts_as_decline") else "")
        rows = self.param("closing.rows")
        if not isinstance(rows, list) or not rows:
            raise EmitError("the table has no closing.rows")
        self.rows = rows
        # the API's own field names for the engine's canonical ones: derived from the API file by type and name (the
        # organisers keep the seven tool names, the fields and allowed values can change), the reader's map on top
        self.field_map = wire.request_field_map(api)
        for tool, m in (table.get("field_map") or {}).items():
            if isinstance(m, dict):
                self.field_map.setdefault(tool, {}).update({k: v for k, v in m.items() if isinstance(v, str)})
        self.cid_field = wire.customer_id_field(api)
        self.resp_map = wire.response_field_map(api)
        situations = self.param("situations") or {}
        self.has_callback = self.param("third_party.callback.window") is not None or any(
            isinstance(s, dict) and isinstance(s.get("callback"), dict) for s in situations.values())
        self.has_transfer = any(isinstance(s, dict) and s.get("transfer_queue") for s in situations.values())
        self.has_notes = self.param("notes.reasons") is not None
        dnc = situations.get("do_not_call") or situations.get("no_contact")
        self.do_not_call = dnc if isinstance(dnc, dict) else None
        self.stages = ["party"] + (["callback"] if self.has_callback else []) + ["identity", "negotiate", "readback"]

    def param(self, path):
        e = self.params.get(path)
        if not isinstance(e, dict) or e.get("confidence") == "not_specified" or "value" not in e:
            return None
        return e["value"]


def resolve_plan(table, ctx):
    """The stage types in output order, after the checks above."""
    plan = table.get("plan")
    if not plan:
        return [t for t in DEFAULT_PLAN if t != "note" or ctx.has_notes]
    if not isinstance(plan, list):
        raise EmitError("table plan is not a list")
    types = []
    for entry in plan:
        t = entry.get("type") if isinstance(entry, dict) else None
        if t in GATE_TYPES:
            F.gate(ctx, entry)
        if t not in DEFAULT_PLAN:
            raise EmitError("plan stage %r has unknown type %r" % (entry.get("id") if isinstance(entry, dict) else entry, t))
        if t in types:
            raise EmitError("plan repeats stage type %r; repeated stages are not built" % t)
        if entry.get("per_item") and t not in ("disclose", "negotiate", "record", "note"):
            raise EmitError("plan stage %r is per_item, which this emitter only supports for item stages" % t)
        types.append(t)
    missing = [t for t in REQUIRED_STAGES if t not in types]
    if missing:
        raise EmitError("plan omits %s, which the engine always runs" % missing)
    if types[0] != "party" or types[-1] != "close":
        raise EmitError("plan must start with party and end with close")
    pos = {t: i for i, t in enumerate(types)}
    for later in ("fetch", "disclose", "record", "note"):
        if later in pos and pos[later] < pos["verify"]:
            raise EmitError("plan puts %s before verify" % later)
    if "disclose" in pos and pos["disclose"] < pos["fetch"]:
        raise EmitError("plan puts disclose before fetch")
    if not (pos["negotiate"] < pos["readback"] < pos["record"]):
        raise EmitError("plan breaks the promise block order negotiate, readback, record")
    if "note" in types and not ctx.has_notes:
        raise EmitError("plan has a note stage but the table has no notes.reasons")
    if ctx.has_notes and "note" not in types:
        raise EmitError("the table defines notes.reasons but the plan has no note stage")
    return types


def base_url_for(api, variant, bank_url):
    server = api.get("server") or ""
    if variant == "test":
        bank_url = bank_url or os.environ.get("OWN_BANK_URL")
        if not bank_url:
            raise EmitError("the test variant needs --bank-url or OWN_BANK_URL")
    elif variant != "final":
        raise EmitError("variant must be final or test")
    url = bank_url or server
    if not url:
        raise EmitError("no bank URL: the tool API file has no server and none was given")
    p = urllib.parse.urlsplit(url)
    if p.path not in ("", "/"):
        return url.rstrip("/")
    sp = urllib.parse.urlsplit(server).path if server else ""
    return "%s://%s%s" % (p.scheme, p.netloc, sp.rstrip("/"))


def emit(table, api, *, variant="final", bank_url=None, model_config=None):
    """The workflow dict (the value of `workflow` in the platform's create body)."""
    if isinstance(api, dict) and "tools" not in api and ("paths" in api or "openapi" in api or "swagger" in api):
        api = parse_api(api)
    base = base_url_for(api, variant, bank_url)
    ctx = Ctx(table, api, base)
    plan = resolve_plan(table, ctx)
    write_tools = ["verify_identity", "get_account", "create_promise"]
    if ctx.has_callback:
        write_tools.append("schedule_callback")
    if ctx.has_transfer:
        write_tools.append("transfer_to_agent")
    if "note" in plan:
        write_tools.append("add_note")
    for t in write_tools + [F.CLOSE_TOOL]:
        if t not in api["tools"]:
            raise EmitError("the tool API file has no %r, which this table needs" % t)
    ctx.write_tools = write_tools
    snippet = pack(render(table))

    frags = {"setup": F.setup(ctx, "party")}
    order = ["setup"]
    for t in plan:
        if t == "party":
            frags["party"] = F.speaking_stage(ctx, "party")
            order.append("party")
            if ctx.has_callback:
                frags["callback"] = F.speaking_stage(ctx, "callback")
                frags["callback_book"] = F.callback_book(ctx)
                order += ["callback", "callback_book"]
        elif t == "verify":
            frags["identity"] = F.speaking_stage(ctx, "identity")
            frags["verify"] = F.identity_verify(ctx)
            order += ["identity", "verify"]
        elif t == "fetch":
            frags["fetch"] = F.account_fetch(ctx)
            order.append("fetch")
        elif t == "disclose":
            continue  # the engine's first negotiate output carries the disclosure (negotiate_say speaks it)
        elif t in ("negotiate", "readback"):
            frags[t] = F.speaking_stage(ctx, t)
            order.append(t)
        elif t == "record":
            frags["record"] = F.record(ctx)
            order.append("record")
            if ctx.has_transfer:
                frags["transfer"] = F.transfer(ctx)
                order.append("transfer")
        elif t == "note":
            frags["note"] = F.note(ctx)
            order.append("note")
        elif t == "close":
            frags["close"] = F.close_rows(ctx)
            frags["end"] = F.end()
            order += ["close", "end"]
    frags["write_result"] = F.write_result(ctx)
    frags["hold"] = F.hold(ctx, "party")
    order += ["write_result", "hold"]

    # engine transitions in priority order: end, close rows, writes, speaking stages, last resort
    routes = list(frags["end"].routes) + list(frags["close"].routes)
    for key in ("verify", "fetch", "record", "transfer", "note", "callback_book"):
        if key in frags:
            routes += frags[key].routes
    for stage in ctx.stages:
        routes += frags[stage].routes
    routes += frags["hold"].routes
    engine = F.engine_node(ctx, snippet, routes)

    nodes = {}
    for key in order:
        nodes.update(frags[key].nodes)
        if key == "setup":
            nodes.update(engine.nodes)
    org = ctx.param("organisation.name") or "the bank"
    label = ctx.param("organisation.assistant_label") or "the digital assistant"
    address = str(ctx.param("call.address_form") or "{title} {last_name}")
    for v in ctx.call_vars:
        address = address.replace("{%s}" % v, "{{%s}}" % v)
    wf = {
        "initial_node": "setup",
        "system_prompt": F.SYSTEM_PROMPT.format(label=("a " + label) if not label.startswith(("a ", "the ")) else label,
                                                org=org, address=address),
        "nodes": nodes,
        "global_nodes": {},
        # a call variable the sample does not know (the API's own name for the customer id: client_ref, account_no) stays
        # empty: on the platform test_variables stand in for missing call variables, and a "test" value here was sent to
        # the bank as the customer id (synthetic brief C, 2026-10-11)
        "test_variables": {v: SAMPLE_CALL_VARS.get(v, "") for v in ctx.call_vars},
    }
    if model_config:
        wf["agent_config"] = model_config
    return wf


def counts(wf):
    nodes = wf["nodes"]
    return {"nodes": len(nodes), "transitions": sum(len(n.get("transitions") or []) for n in nodes.values()),
            "by_type": {t: sum(1 for n in nodes.values() if n.get("node_type") == t)
                        for t in sorted(set(n.get("node_type") for n in nodes.values()))}}


def main(argv=None):
    from .walk import walk
    ap = argparse.ArgumentParser(description="Compile a rule table into a Freya workflow JSON.")
    ap.add_argument("table")
    ap.add_argument("--api", required=True, help="the tool API file (OpenAPI)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--variant", default="final", choices=["final", "test"])
    ap.add_argument("--bank-url", default=None)
    ap.add_argument("--model-config", default=None, help="JSON file with an agent_config object (optional)")
    a = ap.parse_args(argv)
    table = json.loads(pathlib.Path(a.table).read_text())
    raw_api = json.loads(pathlib.Path(a.api).read_text())
    model_config = json.loads(pathlib.Path(a.model_config).read_text()) if a.model_config else None
    try:
        wf = emit(table, parse_api(raw_api), variant=a.variant, bank_url=a.bank_url, model_config=model_config)
    except EmitError as e:
        print("emit error:", e, file=sys.stderr)
        return 2
    pathlib.Path(a.out).write_text(json.dumps(wf, indent=1, ensure_ascii=False))
    c = counts(wf)
    print("wrote %s: %d nodes, %d transitions %s" % (a.out, c["nodes"], c["transitions"], json.dumps(c["by_type"])))
    findings = walk(wf, table, raw_api)
    for f in findings:
        print("walk:", f, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
