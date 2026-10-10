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
import json
import pathlib
import re

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


def _module_source(name):
    src = (_HERE / (name + ".py")).read_text(encoding="utf-8")
    return _RELATIVE_IMPORT.sub("", src)


def render(table):
    """The self-contained snippet source for `table`. Raises ValueError if the result contains {{ or }}."""
    if not isinstance(table, dict):
        raise ValueError("render needs the rule table as a dict")
    table_json = json.dumps(table, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    literal = repr(table_json).replace("{", "\\x7b").replace("}", "\\x7d")
    parts = [
        '"""Freya call engine, rendered by builder/engine/snippet.py. Standard library only. Do not edit."""\n',
        "import json\nimport re\n",
        "\n# ===== calendar.py =====\n", _module_source("calendar"),
        "\n# ===== dates.py =====\n", _module_source("dates"),
        "\n# ===== step.py =====\n", _module_source("step"),
        "\n# ===== rule table =====\n", "TABLE_JSON = " + literal + "\n",
        _MAIN,
    ]
    src = "".join(parts)
    if "{{" in src or "}}" in src:
        bad = [ln for ln in src.splitlines() if "{{" in ln or "}}" in ln]
        raise ValueError("rendered snippet contains double braces: " + " | ".join(bad[:3]))
    compile(src, "<engine-snippet>", "exec")
    return src
