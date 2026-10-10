"""R1: forward reading of a brief into a rule table (Claude).

Prompt = prompts/r1.md + prompts/engine_contract.md + the segmented documents and units + the parsed API + the
schema. The model writes everything except ``units`` and ``wire_map.tools``, which code inserts from the segmenter
and the API parser (exact by construction, and fewer output tokens). The reply is parsed robustly, normalised,
validated with jsonschema; on validation errors one repair turn asks for correction operations (not a whole new
table), which are applied and re-validated. Items that still fail are pruned and reported.
"""
from __future__ import annotations

import copy
import json
import pathlib

import jsonschema

from . import models
from .api_file import api_summary, tools_for_schema
from .jsonx import NoJSON, OpError, apply_ops, extract_json

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCHEMA_PATH = ROOT / "spec" / "rule_table.schema.json"
STATES = {"pre_verification", "identity", "verified", "third_party", "disclosure", "negotiation", "readback",
          "recording", "closing", "any"}
TOP_KEYS = ("schema_version", "documents", "units", "dispositions", "obligations", "parameters", "amendments",
            "wire_map", "phrases", "examples", "open_questions", "plan")


class ReaderError(Exception):
    """The reading failed; the orchestrator falls back to the kit builder."""


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def prompt_text(name: str) -> str:
    return (HERE / "prompts" / name).read_text()


def schema_units(units: dict) -> dict:
    """Segmenter units restricted to the schema's unit fields."""
    keep = ("text", "doc_id", "offset", "end", "kind", "parent", "table")
    return {uid: {k: u[k] for k in keep if k in u} for uid, u in units.items()}


def units_listing(units: dict) -> str:
    lines = []
    for uid, u in sorted(units.items(), key=lambda kv: (kv[1]["offset"], kv[0])):
        rel = f" parent={u['parent']}" if u.get("parent") else ""
        rel += f" table={u['table']}" if u.get("table") and u.get("table") != uid else ""
        lines.append(f"{uid} [{u['kind']}{rel}] {u['text']}")
    return "\n".join(lines)


def build_prompt(seg: dict, api: dict, schema: dict | None = None) -> str:
    schema = schema or load_schema()
    docs = [{k: d.get(k) for k in ("doc_id", "kind", "title", "issue_date")} | {"units": len(d["evidence_units"]),
             "first_unit": d["evidence_units"][0] if d["evidence_units"] else None} for d in seg["documents"]]
    enums = {}
    for name, t in api["tools"].items():
        for f, e in t["request_fields"].items():
            if "enum" in e:
                enums[f"{name}.{f}"] = e["enum"]
        for f, e in t["response_fields"].items():
            if "enum" in e:
                enums[f"{name}.response.{f}"] = e["enum"]
    return "\n\n".join([
        prompt_text("r1.md"),
        prompt_text("engine_contract.md"),
        "# Input: documents (from the segmenter; you decide each role)\n\n" + json.dumps(docs, indent=1),
        "# Input: units (id [kind relations] exact text)\n\n" + units_listing(seg["units"]),
        "# Input: api (parsed tool API; tool names, fields and enum values are exact wire strings)\n\n" + api_summary(api)
        + "\n\nEnums:\n" + json.dumps(enums, indent=1),
        "# Input: schema\n\n" + json.dumps(schema, separators=(",", ":")),
        "Now return the single JSON object.",
    ])


# ------------------------------------------------------------------------------------------------
# normalisation and validation


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


DISP_KEYS = {"kind", "refs", "reason", "evidence"}
OBL_KEYS = {"id", "units", "quote", "when", "then", "kind", "scope", "exception_of", "precedence", "status", "effective",
            "capability", "notes"}
VALUE_KEYS = {"value", "windows", "type", "quotes", "units", "obligations", "confidence"}
PHRASE_KEYS = {"id", "kind", "text", "exact", "obligation", "when"}
AMEND_KEYS = {"amending_unit", "amended_units", "path", "old", "new", "authority", "issue_date", "effective", "scope", "quotes"}


def _drop_extra(d: dict, allowed: set, where: str) -> list[dict]:
    out = []
    for k in list(d):
        if k not in allowed:
            out.append({"where": where, "key": k, "value": d.pop(k)})
    return out


def normalise(table: dict, seg: dict, api: dict) -> dict:
    """Insert code-owned parts and coerce the common harmless deviations. Never invents policy content."""
    t = {k: v for k, v in table.items() if k in TOP_KEYS or k == "run_metadata"}
    extra = {k: v for k, v in table.items() if k not in t}
    t["schema_version"] = "1.0"
    t["units"] = schema_units(seg["units"])
    wm = t.get("wire_map") if isinstance(t.get("wire_map"), dict) else {}
    t["wire_map"] = {"tools": tools_for_schema(api), "concepts": wm.get("concepts") or {}, "enums": wm.get("enums") or {}}
    for k in ("documents", "obligations", "phrases", "plan", "amendments", "examples", "open_questions"):
        t[k] = _as_list(t.get(k))
    for k in ("dispositions", "parameters"):
        if not isinstance(t.get(k), dict):
            t[k] = {}
    # documents: keep the segmenter's ids and evidence; take the model's role/title/issue_date
    model_docs = {d.get("doc_id"): d for d in t["documents"] if isinstance(d, dict)}
    docs = []
    for d in seg["documents"]:
        md = model_docs.get(d["doc_id"], {})
        role = md.get("role") if md.get("role") in ("authoritative", "amends", "informational", "superseded") else "authoritative"
        docs.append({"doc_id": d["doc_id"], "kind": md.get("kind") or d["kind"], "title": md.get("title") or d.get("title") or "",
                     "issue_date": md.get("issue_date", d.get("issue_date")), "role": role,
                     "evidence_units": [u for u in _as_list(md.get("evidence_units")) if u in seg["units"]] or d["evidence_units"][:1]})
    t["documents"] = docs
    # markup units need no reading
    for uid, u in seg["units"].items():
        if uid not in t["dispositions"] and u["kind"] == "other":
            t["dispositions"][uid] = {"kind": "informational", "reason": "markup"}
    dropped = []
    for uid, d in list(t["dispositions"].items()):
        if isinstance(d, str):
            t["dispositions"][uid] = d = {"kind": d}
        if isinstance(d, dict):
            if "refs" in d:
                d["refs"] = [str(r) for r in _as_list(d["refs"])]
            dropped += _drop_extra(d, DISP_KEYS, f"dispositions.{uid}")
    for o in t["obligations"]:
        if not isinstance(o, dict):
            continue
        o["units"] = [str(u) for u in _as_list(o.get("units"))]
        w = o.get("when") if isinstance(o.get("when"), dict) else {}
        if w.get("state") not in STATES:
            note = f"state {w.get('state')!r} not in the vocabulary; read as 'any'"
            o["notes"] = (o.get("notes", "") + "; " + note).strip("; ")
            w["state"] = "any"
        w["guards"] = [str(g) for g in _as_list(w.get("guards"))]
        o["when"] = w
        o["then"] = [a for a in _as_list(o.get("then")) if isinstance(a, dict)]
        o["precedence"] = [str(p) for p in _as_list(o.get("precedence"))]
        o.setdefault("scope", "call")
        o.setdefault("status", "effective")
        o.setdefault("quote", "")
        extra_o = {k: o.pop(k) for k in list(o) if k not in OBL_KEYS}
        if extra_o:
            o["notes"] = (str(o.get("notes", "")) + "; " + json.dumps(extra_o)).strip("; ")
    for path, e in list(t["parameters"].items()):
        if not isinstance(e, dict):
            t["parameters"][path] = {"value": e, "type": type(e).__name__, "confidence": "derived"}
            continue
        if "confidence" not in e:
            e["confidence"] = "quoted" if "value" in e or "windows" in e else "not_specified"
        if "type" not in e:
            e["type"] = "list" if isinstance(e.get("value"), list) else type(e.get("value")).__name__
        for k in ("quotes", "units", "obligations"):
            if k in e:
                e[k] = [str(x) for x in _as_list(e[k])]
        dropped += _drop_extra(e, VALUE_KEYS, f"parameters.{path}")
    for ph in t["phrases"]:
        if isinstance(ph, dict):
            ph.setdefault("exact", False)
            ph["obligation"] = str(ph.get("obligation") or "")
            dropped += _drop_extra(ph, PHRASE_KEYS, f"phrases.{ph.get('id')}")
    for a in t["amendments"]:
        if isinstance(a, dict):
            a["amended_units"] = [str(u) for u in _as_list(a.get("amended_units"))]
            dropped += _drop_extra(a, AMEND_KEYS, "amendments")
    if extra or dropped:
        rm = t.setdefault("run_metadata", {})
        rm["r1_extra_keys"] = sorted(extra)
        rm["r1_dropped"] = dropped
    return t


def validation_errors(table: dict, schema: dict | None = None) -> list[dict]:
    schema = schema or load_schema()
    v = jsonschema.Draft202012Validator(schema)
    out = []
    for e in sorted(v.iter_errors(table), key=lambda e: list(e.absolute_path)):
        out.append({"path": list(e.absolute_path), "message": e.message[:300]})
    return out


def prune_invalid(table: dict, errors: list[dict]) -> tuple[dict, list[dict]]:
    """Drop the array items or map entries that still fail validation. Returns (table, pruned)."""
    t = copy.deepcopy(table)
    targets = set()
    for e in errors:
        p = e["path"]
        if len(p) >= 2 and p[0] in ("obligations", "phrases", "plan", "amendments", "examples", "open_questions", "documents"):
            targets.add((p[0], p[1]))
        elif len(p) >= 2 and p[0] in ("dispositions", "parameters"):
            targets.add((p[0], p[1]))
        elif len(p) >= 3 and p[0] == "wire_map" and p[1] in ("concepts", "enums"):
            targets.add(("wire_map." + p[1], p[2]))
    pruned = []
    for coll, key in sorted(targets, key=lambda x: (x[0], str(x[1])), reverse=True):
        if coll.startswith("wire_map."):
            d = t["wire_map"][coll.split(".")[1]]
            pruned.append({"where": coll, "key": key, "item": d.pop(key, None)})
        elif isinstance(t.get(coll), list):
            pruned.append({"where": coll, "key": key, "item": t[coll][int(key)]})
            del t[coll][int(key)]
        elif isinstance(t.get(coll), dict):
            pruned.append({"where": coll, "key": key, "item": t[coll].pop(key, None)})
    return t, pruned


REPAIR_TEMPLATE = """You wrote the rule table below for a bank brief. It fails JSON Schema validation with the errors listed.
Fix only what the errors name; keep every quote verbatim and every wire string exact; do not change anything else.

Return exactly one JSON object and nothing else:
{{"ops": [ ... ]}}
Operations (paths are lists of keys and list indices from the table root):
  {{"op": "set", "path": ["obligations", 12, "then", 0], "value": {{...}}}}
  {{"op": "delete", "path": ["obligations", 12, "when", "foo"]}}
  {{"op": "set_parameter", "path": "identity.max_wrong", "entry": {{...value entry...}}}}
  {{"op": "replace_obligation", "id": "O-...", "obligation": {{...}}}}

# Errors
{errors}

# Schema
{schema}

# Table (units and wire_map.tools omitted)
{table}
"""


def _slim(table: dict) -> dict:
    t = {k: v for k, v in table.items() if k not in ("units", "run_metadata")}
    t["wire_map"] = {k: v for k, v in (table.get("wire_map") or {}).items() if k != "tools"}
    return t


def repair(table: dict, errors: list[dict], *, deadline=None, timeout_s: float = 240) -> tuple[dict, dict, str]:
    """One repair turn. Returns (table, usage, raw reply)."""
    prompt = REPAIR_TEMPLATE.format(errors=json.dumps(errors[:80], indent=1),
                                    schema=json.dumps(load_schema(), separators=(",", ":")),
                                    table=json.dumps(_slim(table), separators=(",", ":")))
    text, usage = models.claude_text(prompt, deadline=deadline, timeout_s=timeout_s, purpose="r1_repair", effort="medium")
    ops = extract_json(text, require_key="ops").get("ops") or []
    fixed, _ = apply_ops(table, ops)
    return fixed, usage, text


def read_r1(seg: dict, api: dict, *, deadline=None, timeout_s: float = 540, raw_sink=None) -> tuple[dict, list[dict], dict]:
    """Run R1. Returns (table, usages, info). Raises ReaderError when no table comes back twice."""
    schema = load_schema()
    prompt = build_prompt(seg, api, schema)
    usages, raws, errors_seen = [], [], []
    reply = None
    for attempt in (1, 2):
        try:
            text, usage = models.claude_text(prompt, deadline=deadline, timeout_s=timeout_s, purpose="r1")
            usages.append(usage)
            raws.append(text)
            if raw_sink:
                raw_sink("\n\n".join(raws))
            reply = extract_json(text, require_key="table")
            break
        except models.DeadlineExceeded as e:
            errors_seen.append(str(e))
            break
        except (models.ModelCallError, NoJSON) as e:
            errors_seen.append(f"attempt {attempt}: {e}")
    if reply is None:
        raise ReaderError("R1 produced no table: " + "; ".join(errors_seen))
    info = {"attempts": len(raws), "call_errors": errors_seen, "battery": reply.get("question_battery"),
            "reader_notes": reply.get("reader_notes")}
    table = normalise(reply["table"] if isinstance(reply.get("table"), dict) else {}, seg, api)
    errors = validation_errors(table, schema)
    info["schema_errors_initial"] = len(errors)
    if errors:
        try:
            fixed, usage, text = repair(table, errors, deadline=deadline)
            usages.append(usage)
            raws.append("=== repair ===\n" + text)
            if raw_sink:
                raw_sink("\n\n".join(raws))
            fixed = normalise(fixed, seg, api)
            errors = validation_errors(fixed, schema)
            table = fixed
        except (models.ModelCallError, NoJSON, OpError) as e:
            info["repair_error"] = str(e)
        if errors:
            table, pruned = prune_invalid(table, errors)
            info["pruned"] = pruned
            errors = validation_errors(table, schema)
    info["schema_errors_final"] = errors
    if errors:
        raise ReaderError(f"R1 table still invalid after repair and pruning: {errors[:3]}")
    return table, usages, info
