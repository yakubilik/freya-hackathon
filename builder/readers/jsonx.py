"""Robust JSON extraction from model replies, and the correction operations shared by R1 repair and adjudication.

``extract_json`` accepts a bare object, a fenced block, prose around it, trailing text and smart quotes outside
strings; it returns the largest JSON object found (optionally the first one that has a required key).
``parse_jsonl`` parses JSON Lines one line at a time so a truncated or malformed line costs only that line.
``apply_ops`` applies a list of correction operations to a table in place.
"""
from __future__ import annotations

import copy
import json
import re

FENCE_RE = re.compile(r"```(?:json|jsonl|JSON)?\s*\n(.*?)```", re.S)


class NoJSON(ValueError):
    pass


def _candidates(text: str):
    """Decoded objects found in text: fenced blocks first, then every '{' that starts a valid object."""
    dec = json.JSONDecoder(strict=False)
    found = []
    for m in FENCE_RE.finditer(text):
        body = m.group(1).strip()
        try:
            found.append(json.loads(body, strict=False))
        except json.JSONDecodeError:
            pass
    i = text.find("{")
    while i >= 0:
        try:
            obj, end = dec.raw_decode(text, i)
            found.append(obj)
            i = text.find("{", end)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    return found


def extract_json(text: str, require_key: str | None = None) -> dict:
    """The largest JSON object in a model reply (the one with ``require_key`` if given). Raises NoJSON."""
    if not isinstance(text, str) or not text.strip():
        raise NoJSON("empty reply")
    s = text.strip()
    try:
        obj = json.loads(s, strict=False)
        if isinstance(obj, dict) and (require_key is None or require_key in obj):
            return obj
    except json.JSONDecodeError:
        pass
    objs = [o for o in _candidates(s) if isinstance(o, dict)]
    if require_key is not None:
        keyed = [o for o in objs if require_key in o]
        if keyed:
            objs = keyed
        else:
            # a nested object may carry the key
            raise NoJSON(f"no JSON object with key {require_key!r}")
    if not objs:
        raise NoJSON("no JSON object in reply")
    return max(objs, key=lambda o: len(json.dumps(o)))


def parse_jsonl(text: str) -> tuple[list[dict], list[str]]:
    """(objects, unparsed lines). Tolerates fences, blank lines, trailing commas, array wrappers and several
    objects on one line."""
    objs, bad = [], []
    dec = json.JSONDecoder(strict=False)
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or line in ("[", "]"):
            continue
        line = line.rstrip(",")
        if line.startswith("[") and not line.startswith("[{"):
            bad.append(raw)
            continue
        line = line.lstrip("[").rstrip("]") if line.startswith("[{") else line
        try:
            o = json.loads(line, strict=False)
            if isinstance(o, dict):
                objs.append(o)
            elif isinstance(o, list):
                objs.extend(x for x in o if isinstance(x, dict))
            continue
        except json.JSONDecodeError:
            pass
        i, got = line.find("{"), False
        while i >= 0:
            try:
                o, end = dec.raw_decode(line, i)
                if isinstance(o, dict):
                    objs.append(o)
                    got = True
                i = line.find("{", end)
            except json.JSONDecodeError:
                break
        if not got:
            bad.append(raw)
    return objs, bad


# ------------------------------------------------------------------------------------------------
# correction operations


class OpError(ValueError):
    pass


def _walk(root, path):
    cur = root
    for k in path[:-1]:
        if isinstance(cur, list):
            cur = cur[int(k)]
        elif isinstance(cur, dict):
            if k not in cur:
                cur[k] = {}
            cur = cur[k]
        else:
            raise OpError(f"cannot descend into {type(cur).__name__} at {k!r}")
    return cur


def _find_obligation(table, oid):
    for i, o in enumerate(table.get("obligations") or []):
        if o.get("id") == oid:
            return i
    return None


def apply_op(table: dict, op: dict) -> str:
    """Apply one operation in place; returns a short description. Raises OpError."""
    if not isinstance(op, dict) or "op" not in op:
        raise OpError("operation without 'op'")
    kind = op["op"]
    if kind in ("set", "delete"):
        path = op.get("path")
        if isinstance(path, str):
            path = [path]
        if not isinstance(path, list) or not path:
            raise OpError("set/delete needs a non-empty path list")
        if path[0] in ("units", "run_metadata"):
            raise OpError(f"{path[0]} cannot be corrected")
        parent = _walk(table, path)
        last = path[-1]
        if kind == "set":
            if isinstance(parent, list):
                idx = int(last)
                if idx == len(parent):
                    parent.append(op.get("value"))
                else:
                    parent[idx] = op.get("value")
            else:
                parent[last] = op.get("value")
        else:
            if isinstance(parent, list):
                del parent[int(last)]
            elif last in parent:
                del parent[last]
        return f"{kind} {'/'.join(map(str, path))}"
    if kind == "add_obligation":
        ob = op.get("obligation") or {}
        if not ob.get("id"):
            raise OpError("add_obligation without id")
        if _find_obligation(table, ob["id"]) is not None:
            raise OpError(f"obligation {ob['id']} exists")
        table.setdefault("obligations", []).append(ob)
        return f"add {ob['id']}"
    if kind == "replace_obligation":
        i = _find_obligation(table, op.get("id"))
        if i is None:
            raise OpError(f"no obligation {op.get('id')}")
        table["obligations"][i] = op.get("obligation") or {}
        return f"replace {op.get('id')}"
    if kind == "remove_obligation":
        i = _find_obligation(table, op.get("id"))
        if i is None:
            raise OpError(f"no obligation {op.get('id')}")
        del table["obligations"][i]
        return f"remove {op.get('id')}"
    if kind == "set_disposition":
        unit = op.get("unit")
        if unit not in (table.get("units") or {}):
            raise OpError(f"no unit {unit}")
        table.setdefault("dispositions", {})[unit] = op.get("disposition") or {}
        return f"disposition {unit}"
    if kind == "set_parameter":
        path = op.get("path")
        if not isinstance(path, str):
            raise OpError("set_parameter needs a dotted path string")
        table.setdefault("parameters", {})[path] = op.get("entry") or {}
        return f"parameter {path}"
    if kind == "add_amendment":
        table.setdefault("amendments", []).append(op.get("amendment") or {})
        return "add amendment"
    if kind == "add_phrase":
        ph = op.get("phrase") or {}
        phrases = table.setdefault("phrases", [])
        phrases[:] = [p for p in phrases if p.get("id") != ph.get("id")]
        phrases.append(ph)
        return f"phrase {ph.get('id')}"
    if kind == "set_plan":
        table["plan"] = op.get("plan") or []
        return "plan"
    if kind == "set_document_role":
        for d in table.get("documents") or []:
            if d.get("doc_id") == op.get("doc_id"):
                d["role"] = op.get("role")
                return f"role {op.get('doc_id')}"
        raise OpError(f"no document {op.get('doc_id')}")
    raise OpError(f"unknown op {kind!r}")


def op_paths(op: dict) -> list[str]:
    """The table locations an operation touches (for conflict detection between corrections)."""
    k = op.get("op")
    if k in ("set", "delete"):
        p = op.get("path")
        p = [p] if isinstance(p, str) else (p or [])
        return ["/".join(map(str, p[:3]))]
    if k in ("add_obligation", "replace_obligation", "remove_obligation"):
        return ["obligation:" + str(op.get("id") or (op.get("obligation") or {}).get("id"))]
    if k == "set_disposition":
        return ["disposition:" + str(op.get("unit"))]
    if k == "set_parameter":
        return ["parameters/" + str(op.get("path"))]
    if k == "add_phrase":
        return ["phrase:" + str((op.get("phrase") or {}).get("id"))]
    if k == "set_plan":
        return ["plan"]
    if k == "set_document_role":
        return ["document:" + str(op.get("doc_id"))]
    return [k or "?"]


def apply_ops(table: dict, ops: list[dict]) -> tuple[dict, list[str]]:
    """Apply ops to a deep copy; all or nothing. Returns (new table, descriptions). Raises OpError."""
    t = copy.deepcopy(table)
    done = []
    for op in ops or []:
        try:
            done.append(apply_op(t, op))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise OpError(f"{op.get('op') if isinstance(op, dict) else op}: {e}") from e
    return t, done
