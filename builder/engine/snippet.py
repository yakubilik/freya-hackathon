"""Render the engine as one self-contained Python source string for a Freya code node.

`render(table)` inlines calendar.py, dates.py, step.py and the rule table (its JSON as a string literal with
every brace written as \\x7b / \\x7d, so the source never contains `{{` or `}}` whatever the table says), then a main block that reads and writes the
workflow variables:

  reads   vars["engine_state"]  (JSON string; may be missing -> a fresh state seeded from the call variables)
          vars["engine_events"] (JSON string, a list of event dicts; may be missing -> [])
          vars["now"]           (the call clock, e.g. "2026-10-14T11:00")
  writes  vars["engine_state"], vars["engine_next"], vars["say_next"], vars["mandatory_lines"] (joined
          with newline), vars["readback_text"], vars["engine_writes"] (JSON string), vars["close_outcome"],
          vars["close_reason"], vars["what_to_do_next"], vars["ask_clarify"] ("true"/"false"),
          vars["engine_unsupported"] (JSON string)

The snippet never raises: the main block is wrapped and on any error writes a fallback
(`engine_next = "clarify"`, a plain `what_to_do_next`, `ask_clarify = "true"`). It uses the standard
library only and runs under `exec(src, {"vars": vars})`.
"""
import ast
import io
import json
import pathlib
import re
import tokenize

_HERE = pathlib.Path(__file__).resolve().parent
_RELATIVE_IMPORT = re.compile(r"^from \.\w+ import \([^)]*\)\n|^from \.\w+ import .*\n", re.MULTILINE)

_MAIN = '''

# ---------------------------------------------------------------------------------------------
# Freya code node entry point

TABLE = json.loads(TABLE_JSON)
_STRING_KEYS = ("engine_next", "say_next", "readback_text", "what_to_do_next", "close_outcome", "close_reason")


def _engine_fallback(v, message):
    for k in _STRING_KEYS:
        if k not in v or not isinstance(v.get(k), str):
            v[k] = ""
    v["engine_next"] = "clarify"
    v["what_to_do_next"] = message
    v["ask_clarify"] = "true"
    v["mandatory_lines"] = v.get("mandatory_lines") if isinstance(v.get("mandatory_lines"), str) else ""
    v["engine_writes"] = "[]"
    if not isinstance(v.get("engine_state"), str) or not v.get("engine_state"):
        v["engine_state"] = json.dumps(new_state())
    if not isinstance(v.get("engine_unsupported"), str):
        v["engine_unsupported"] = "[]"


def _engine_main(v):
    raw_state = v.get("engine_state")
    state = None
    if isinstance(raw_state, str) and raw_state.strip():
        state = json.loads(raw_state)
    elif isinstance(raw_state, dict):
        state = raw_state
    if not isinstance(state, dict) or not state.get("stage"):
        call = dict()
        for k in ("customer_id", "first_name", "last_name", "title", "now"):
            if v.get(k) is not None:
                call[k] = v.get(k)
        state = new_state(call)
    raw_events = v.get("engine_events")
    events = []
    if isinstance(raw_events, str) and raw_events.strip():
        events = json.loads(raw_events)
    elif isinstance(raw_events, list):
        events = raw_events
    if not isinstance(events, list):
        events = []
    now = v.get("now") or state.get("call", dict()).get("now")
    new_st, out = step(state, events, TABLE, now)
    v["engine_state"] = json.dumps(new_st)
    v["engine_next"] = str(out.get("engine_next") or "clarify")
    v["say_next"] = str(out.get("say_next") or "")
    v["mandatory_lines"] = "\\n".join(str(x) for x in (out.get("mandatory_lines") or []))
    v["readback_text"] = str(out.get("readback_text") or "")
    v["engine_writes"] = json.dumps(out.get("writes") or [])
    close = out.get("close") or dict()
    v["close_outcome"] = str(close.get("outcome") or "")
    v["close_reason"] = str(close.get("reason") or "")
    v["what_to_do_next"] = str(out.get("what_to_do_next") or "")
    v["ask_clarify"] = "true" if out.get("ask_clarify") else "false"
    v["engine_unsupported"] = json.dumps(out.get("unsupported") or [])
    v["engine_events"] = ""


try:
    _engine_main(vars)
except Exception as _exc:  # noqa: BLE001 - a code node must never raise
    try:
        _engine_fallback(vars, "The engine could not apply the last reply (" + type(_exc).__name__ + "); ask the customer to repeat.")
    except Exception:  # noqa: BLE001
        pass
'''


# the emitter's epilogue runs in the same namespace and looks engine functions up by name: every name its source
# mentions is kept
_KEEP_SOURCES = (_HERE.parent / "emitter" / "fragments.py",)


def _module_source(name):
    src = (_HERE / (name + ".py")).read_text(encoding="utf-8")
    return _RELATIVE_IMPORT.sub("", src)


def minify(src):
    """The same program in fewer bytes: docstrings, comments and blank lines removed, one space per indent level.
    Text inside multi-line strings is left as it is. (The platform caps a code node's code plus data at 128 KiB.)"""
    lines = src.splitlines(keepends=True)
    drop = {}
    for node in ast.walk(ast.parse(src)):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str) and not lines[body[0].lineno - 1][:body[0].col_offset].strip():
            d = body[0]
            drop[d.lineno] = (d.end_lineno, len(body) == 1, d.col_offset)
    kept, i = [], 1
    while i <= len(lines):
        if i in drop:
            end, only, col = drop[i]
            if only:
                kept.append(" " * col + "pass\n")
            i = end + 1
            continue
        kept.append(lines[i - 1])
        i += 1
    src = "".join(kept)
    lines = src.splitlines(keepends=True)
    protected, comments = set(), {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comments[tok.start[0]] = tok.start[1]
        elif tok.start[0] < tok.end[0] and tok.type not in (tokenize.NL, tokenize.NEWLINE):
            protected.update(range(tok.start[0] + 1, tok.end[0] + 1))
    out = []
    for n, line in enumerate(lines, 1):
        if n in protected:
            out.append(line)
            continue
        if n in comments:
            line = line[:comments[n]]
        line = line.rstrip()
        if not line.strip():
            continue
        body = line.lstrip(" ")
        out.append(" " * ((len(line) - len(body)) // 4) + body + "\n")
    return "".join(out)


def shorten(src, keep=""):
    """Rename the private top-level names of `src` (``_name``, not dunder, not mentioned in `keep` or in a string
    literal) to short ones, and write plain one-line string literals with single quotes (a double quote costs a
    backslash once the code travels as JSON)."""
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    tree = ast.parse(src)
    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
    strings = " ".join(t.string for t in toks if t.type == tokenize.STRING)
    names = {t.string for t in toks if t.type == tokenize.NAME}
    cands = sorted(n for n in defined if n.startswith("_") and not n.startswith("__") and len(n) > 3
                   and not re.search(r"\b%s\b" % re.escape(n), keep) and n not in strings)
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    short, k = {}, 0
    for n in sorted(cands, key=lambda n: -sum(1 for t in toks if t.string == n)):
        while True:
            x, j = "", k
            while True:
                x = alphabet[j % 26] + x
                j = j // 26 - 1
                if j < 0:
                    break
            k += 1
            new = "_" + x
            if new not in names:
                break
        short[n] = new
    lines = src.splitlines(keepends=True)
    edits = {}
    prev = None
    for t in toks:
        if t.type == tokenize.NAME and t.string in short and not (prev is not None and prev.string == "."):
            edits.setdefault(t.start[0], []).append((t.start[1], t.end[1], short[t.string]))
        elif t.type == tokenize.STRING and t.start[0] == t.end[0]:
            m = re.match(r"([A-Za-z]*)\"(.*)\"$", t.string, re.S)
            if m and not m.group(2).startswith('""') and "'" not in m.group(2) and '\\"' not in m.group(2):
                edits.setdefault(t.start[0], []).append((t.start[1], t.end[1], m.group(1) + "'" + m.group(2) + "'"))
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            prev = t
    for row, es in edits.items():
        line = lines[row - 1]
        for a, b, rep in sorted(es, reverse=True):
            line = line[:a] + rep + line[b:]
        lines[row - 1] = line
    return "".join(lines)


def shorten_locals(src):
    """Rename the local variables and parameters of every top-level function (and method) to short names that
    appear nowhere in `src`. A name is left alone when it is bound at module level, is a builtin, is ever used as
    a keyword argument, or is bound by something other than a plain name (except ... as, import, def, class)."""
    import builtins
    tree = ast.parse(src)
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    used = {t.string for t in toks if t.type == tokenize.NAME} | set(dir(builtins))
    module_names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        for sub in ast.walk(node) if isinstance(node, (ast.Assign, ast.AugAssign, ast.For, ast.With, ast.Import, ast.ImportFrom, ast.Try)) else ():
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                module_names.add(sub.id)
            elif isinstance(sub, ast.alias):
                module_names.add((sub.asname or sub.name).split(".")[0])
    keywords = {k.arg for k in ast.walk(tree) if isinstance(k, ast.keyword) and k.arg}
    funcs = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs.append(node)
        elif isinstance(node, ast.ClassDef):
            funcs += [n for n in node.body if isinstance(n, ast.FunctionDef)]

    def pool():
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        for n in range(1, 4):
            for i in range(len(alphabet) ** n):
                x, j = "", i
                for _ in range(n):
                    x = alphabet[j % 26] + x
                    j //= 26
                if x not in used and not __import__("keyword").iskeyword(x):
                    yield x

    edits = {}
    for fn in funcs:
        bound, bad = {}, set(keywords) | module_names | set(dir(builtins)) | {"self", "vars"}
        for sub in ast.walk(fn):
            if isinstance(sub, ast.arg):
                bound[sub.arg] = bound.get(sub.arg, 0) + 1
            elif isinstance(sub, ast.Name):
                bound[sub.id] = bound.get(sub.id, 0) + (1 if isinstance(sub.ctx, (ast.Store, ast.Del)) else 0) or bound.get(sub.id, 0)
            elif isinstance(sub, ast.ExceptHandler) and sub.name:
                bad.add(sub.name)
            elif isinstance(sub, (ast.FunctionDef, ast.ClassDef, ast.Lambda)) and sub is not fn:
                if not isinstance(sub, ast.Lambda):
                    bad.add(sub.name)
            elif isinstance(sub, (ast.Global, ast.Nonlocal)):
                bad.update(sub.names)
            elif isinstance(sub, ast.alias):
                bad.add((sub.asname or sub.name).split(".")[0])
        stores = {s.id for s in ast.walk(fn) if isinstance(s, ast.Name) and isinstance(s.ctx, (ast.Store, ast.Del))}
        stores |= {a.arg for a in ast.walk(fn) if isinstance(a, ast.arg)}
        local = sorted(n for n in stores if n not in bad and len(n) > 1)
        freq = {n: 0 for n in local}
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Name) and sub.id in freq:
                freq[sub.id] += 1
            elif isinstance(sub, ast.arg) and sub.arg in freq:
                freq[sub.arg] += 1
        names = pool()
        new = {}
        for n in sorted(local, key=lambda n: -freq[n] * len(n)):
            cand = next(names)
            if len(cand) < len(n):
                new[n] = cand
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Name) and sub.id in new:
                edits.setdefault(sub.lineno, []).append((sub.col_offset, sub.end_col_offset, new[sub.id]))
            elif isinstance(sub, ast.arg) and sub.arg in new:
                edits.setdefault(sub.lineno, []).append((sub.col_offset, sub.col_offset + len(sub.arg.encode()), new[sub.arg]))
    lines = src.splitlines(keepends=True)
    for row, es in edits.items():
        b = lines[row - 1].encode()
        for a, e, rep in sorted(set(es), reverse=True):
            b = b[:a] + rep.encode() + b[e:]
        lines[row - 1] = b.decode()
    out = "".join(lines)
    compile(out, "<engine-snippet>", "exec")
    return out


def engine_table(table):
    """The part of the rule table the engine reads (step._context, _param, _say, calendar_from_table): parameter
    values, with not_specified entries left out (the engine treats absent and not_specified alike), and the
    mandatory phrases' id, kind, text and exact flag."""
    params = {}
    for k, e in (table.get("parameters") or {}).items():
        if isinstance(e, dict) and "value" in e and e.get("confidence") != "not_specified":
            params[k] = {"value": e["value"]}
    phrases = [{f: ph[f] for f in ("id", "kind", "text", "exact") if f in ph} for ph in table.get("phrases") or []
               if isinstance(ph, dict) and ph.get("kind") == "mandatory" and ph.get("id")]
    return {"parameters": params, "phrases": phrases}


def render(table):
    """The self-contained snippet source for `table`. Raises ValueError if the result contains {{ or }}."""
    if not isinstance(table, dict):
        raise ValueError("render needs the rule table as a dict")
    table_json = json.dumps(engine_table(table), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    # only a brace followed by the same brace is escaped: that is all it takes to never write {{ or }}
    literal = re.sub(r"\}(?=\})", r"\\x7d", re.sub(r"\{(?=\{)", r"\\x7b", repr(table_json)))
    parts = [
        '"""Freya call engine, rendered by builder/engine/snippet.py. Standard library only. Do not edit."""\n',
        "import json\nimport re\n",
        shorten(shorten_locals("".join(minify(_module_source(m)) for m in ("calendar", "dates", "step"))), keep=_MAIN + " step new_state " + "".join(p.read_text(encoding="utf-8") for p in _KEEP_SOURCES if p.exists())),
        "\n# ===== rule table =====\n", "TABLE_JSON = " + literal + "\n",
        _MAIN,
    ]
    src = "".join(parts)
    if "{{" in src or "}}" in src:
        bad = [ln for ln in src.splitlines() if "{{" in ln or "}}" in ln]
        raise ValueError("rendered snippet contains double braces: " + " | ".join(bad[:3]))
    compile(src, "<engine-snippet>", "exec")
    return src
