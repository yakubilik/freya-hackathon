"""Parse a tool API file into the ``wire_map.tools`` shape of the rule table schema.

Accepts OpenAPI 3 (the kit's ``tools/openapi.json``), Swagger 2, and a plain ``{"tools": [...]}`` list.
Field names and enum values are taken exactly as the file has them (a hidden API file may rename
fields or enums; the brief's tables are the authority only where the API leaves a field free).

Output::

    {"server": "https://.../v1",
     "tools": {tool_name: {"path", "method", "summary",
                           "request_fields": {name: {"type", "enum"?, "format"?, "required", "description"?}},
                           "response_fields": {dotted.path: {"type", "enum"?, "description"?}}}}}
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

HTTP_METHODS = ("post", "get", "put", "patch", "delete")


def _resolve(node: Any, root: dict, depth: int = 0) -> Any:
    if depth > 20 or not isinstance(node, dict):
        return node
    if "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        if ref.startswith("#/"):
            cur: Any = root
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return {}
            merged = dict(_resolve(cur, root, depth + 1))
            merged.update({k: v for k, v in node.items() if k != "$ref"})
            return merged
        return {}
    return node


def _merge_all_of(schema: dict, root: dict) -> dict:
    schema = _resolve(schema, root)
    if not isinstance(schema, dict):
        return {}
    if "allOf" in schema:
        merged: dict = {"type": "object", "properties": {}, "required": []}
        for part in schema["allOf"]:
            part = _merge_all_of(part, root)
            merged["properties"].update(part.get("properties", {}))
            merged["required"] += part.get("required", [])
        rest = {k: v for k, v in schema.items() if k != "allOf"}
        merged["properties"].update(rest.get("properties", {}))
        merged["required"] += rest.get("required", [])
        return merged
    return schema


def _enum_of(schema: dict) -> list | None:
    if "enum" in schema and isinstance(schema["enum"], list):
        return list(schema["enum"])
    for key in ("oneOf", "anyOf"):
        if key in schema and all(isinstance(o, dict) and "const" in o for o in schema[key]):
            return [o["const"] for o in schema[key]]
    if "const" in schema:
        return [schema["const"]]
    if "x-enum" in schema and isinstance(schema["x-enum"], list):
        return list(schema["x-enum"])
    return None


def _field_entry(schema: dict, root: dict, required: bool | None = None) -> dict:
    schema = _merge_all_of(schema, root)
    entry: dict = {"type": schema.get("type") or ("object" if "properties" in schema else "string")}
    enum = _enum_of(schema)
    if enum is not None:
        entry["enum"] = enum
    if "format" in schema:
        entry["format"] = schema["format"]
    if "description" in schema:
        entry["description"] = schema["description"]
    if required is not None:
        entry["required"] = required
    if entry["type"] == "array" and isinstance(schema.get("items"), dict):
        items = _merge_all_of(schema["items"], root)
        entry["items"] = items.get("type", "object")
    return entry


def _flatten(schema: dict, root: dict, prefix: str, out: dict, depth: int = 0) -> None:
    schema = _merge_all_of(schema, root)
    if depth > 6 or not isinstance(schema, dict):
        return
    props = schema.get("properties") or {}
    req = set(schema.get("required") or [])
    for name, sub in props.items():
        sub = _merge_all_of(sub, root)
        path = f"{prefix}{name}"
        out[path] = _field_entry(sub, root, required=(name in req) if prefix == "" else None)
        if sub.get("type") == "object" or "properties" in sub:
            _flatten(sub, root, path + ".", out, depth + 1)
        elif sub.get("type") == "array" and isinstance(sub.get("items"), dict):
            items = _merge_all_of(sub["items"], root)
            if items.get("type") == "object" or "properties" in items:
                _flatten(items, root, path + "[].", out, depth + 1)


def _request_schema(op: dict, root: dict) -> dict:
    body = _resolve(op.get("requestBody") or {}, root)
    content = body.get("content") or {}
    for mime in ("application/json", *content.keys()):
        if mime in content and isinstance(content[mime], dict) and "schema" in content[mime]:
            return _merge_all_of(content[mime]["schema"], root)
    # Swagger 2 body parameter, or OpenAPI parameters as a flat object.
    props, req = {}, []
    for p in op.get("parameters") or []:
        p = _resolve(p, root)
        if p.get("in") == "body" and "schema" in p:
            return _merge_all_of(p["schema"], root)
        if "name" in p:
            props[p["name"]] = p.get("schema") or {k: v for k, v in p.items() if k in ("type", "enum", "format", "description")}
            if p.get("required"):
                req.append(p["name"])
    for alt in ("input_schema", "parameters_schema", "inputSchema", "input"):
        if isinstance(op.get(alt), dict) and ("properties" in op[alt] or "type" in op[alt]):
            return _merge_all_of(op[alt], root)
    return {"type": "object", "properties": props, "required": req}


def _response_schema(op: dict, root: dict) -> dict:
    responses = op.get("responses") or {}
    for code in ("200", "201", "default", *responses.keys()):
        r = _resolve(responses.get(code) or {}, root)
        if not r:
            continue
        content = r.get("content") or {}
        for mime in ("application/json", *content.keys()):
            if mime in content and isinstance(content[mime], dict) and "schema" in content[mime]:
                return _merge_all_of(content[mime]["schema"], root)
        if "schema" in r:  # Swagger 2
            return _merge_all_of(r["schema"], root)
    for alt in ("output_schema", "outputSchema", "output", "returns", "response"):
        if isinstance(op.get(alt), dict):
            return _merge_all_of(op[alt], root)
    return {}


def _tool_name(path: str, op: dict, used: set) -> str:
    name = op.get("operationId") or op.get("name")
    if not name:
        parts = [p for p in path.strip("/").split("/") if p and not re.fullmatch(r"v\d+", p) and "{" not in p]
        name = parts[-1] if parts else path.strip("/") or "root"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    base, k = name, 2
    while name in used:
        name = f"{base}_{k}"
        k += 1
    used.add(name)
    return name


def parse_api(doc: dict) -> dict:
    """Parse a loaded API document. Never raises on shape surprises; unknown shapes give empty tools."""
    tools: dict = {}
    server = ""
    servers = doc.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        server = servers[0].get("url", "") or ""
    elif "host" in doc:  # Swagger 2
        scheme = (doc.get("schemes") or ["https"])[0]
        server = f"{scheme}://{doc['host']}{doc.get('basePath', '')}"
    elif isinstance(doc.get("server"), str):
        server = doc["server"]
    elif isinstance(doc.get("base_url"), str):
        server = doc["base_url"]
    used: set = set()
    paths = doc.get("paths")
    if isinstance(paths, dict):
        for path, item in paths.items():
            item = _resolve(item, doc)
            if not isinstance(item, dict):
                continue
            for method in HTTP_METHODS:
                if method not in item or not isinstance(item[method], dict):
                    continue
                op = item[method]
                name = _tool_name(path, op, used)
                req_fields: dict = {}
                _flatten(_request_schema(op, doc), doc, "", req_fields)
                resp_fields: dict = {}
                _flatten(_response_schema(op, doc), doc, "", resp_fields)
                tools[name] = {"path": path, "method": method.upper(), "summary": op.get("summary") or op.get("description") or "",
                               "request_fields": req_fields, "response_fields": resp_fields}
    elif isinstance(doc.get("tools"), list):  # plain tool list
        for t in doc["tools"]:
            if not isinstance(t, dict):
                continue
            name = _tool_name(t.get("path") or t.get("url") or t.get("name") or "tool", t, used)
            req_fields, resp_fields = {}, {}
            _flatten(_request_schema(t, doc), doc, "", req_fields)
            _flatten(_response_schema(t, doc), doc, "", resp_fields)
            tools[name] = {"path": t.get("path") or t.get("url") or f"/{name}", "method": str(t.get("method", "POST")).upper(),
                           "summary": t.get("summary") or t.get("description") or "", "request_fields": req_fields, "response_fields": resp_fields}
    return {"server": server, "tools": tools}


def load_api(path: str | pathlib.Path) -> dict:
    return parse_api(json.loads(pathlib.Path(path).read_text()))


def request_enums(api: dict) -> dict:
    """``{"tool.field": [values]}`` for every request field that has an enum."""
    out = {}
    for name, t in api["tools"].items():
        for f, e in t["request_fields"].items():
            if "enum" in e:
                out[f"{name}.{f}"] = e["enum"]
    return out


def response_leaf_fields(api: dict, tool: str | None = None) -> set:
    """Leaf field names in response schemas (``days_late`` for ``products[].days_late``)."""
    out = set()
    for name, t in api["tools"].items():
        if tool and name != tool:
            continue
        for f in t["response_fields"]:
            out.add(f.split(".")[-1])
    return out


def tools_for_schema(api: dict) -> dict:
    """The ``wire_map.tools`` value: path, method, request_fields, response_fields only."""
    return {n: {"path": t["path"], "method": t["method"], "request_fields": t["request_fields"], "response_fields": t["response_fields"]}
            for n, t in api["tools"].items()}


def api_summary(api: dict) -> str:
    """Compact human-readable summary for a prompt."""
    lines = [f"server: {api['server'] or 'NOT SPECIFIED'}"]
    for name, t in api["tools"].items():
        lines.append(f"- {name}: {t['method']} {t['path']} - {t['summary']}")
        for f, e in t["request_fields"].items():
            extra = f" enum={e['enum']}" if "enum" in e else ""
            extra += f" format={e['format']}" if "format" in e else ""
            extra += " required" if e.get("required") else ""
            extra += f" ({e['description']})" if e.get("description") else ""
            lines.append(f"    request {f}: {e['type']}{extra}")
        for f, e in t["response_fields"].items():
            extra = f" enum={e['enum']}" if "enum" in e else ""
            extra += f" ({e['description']})" if e.get("description") else ""
            lines.append(f"    response {f}: {e['type']}{extra}")
    return "\n".join(lines)
