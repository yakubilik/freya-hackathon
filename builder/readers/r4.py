"""R4: blind source audit (second model family) from the raw brief and the raw tool API file only.

The auditor never sees the segmentation or R1's table. Its JSON Lines reply is parsed line by line (a truncated
reply loses only the tail: cases before inventory before items); code maps every quote to unit ids afterwards.
"""
from __future__ import annotations

import pathlib

from . import models
from .jsonx import parse_jsonl
from .segment import locate_quote

HERE = pathlib.Path(__file__).resolve().parent


def build_prompt(brief_text: str, api_text: str) -> str:
    return "\n\n".join([
        (HERE / "prompts" / "r4.md").read_text(),
        "# The brief (raw Markdown, verbatim)\n\n<<<BRIEF\n" + brief_text + "\nBRIEF>>>",
        "# The tool API file (verbatim)\n\n<<<API\n" + api_text + "\nAPI>>>",
        "Now write the JSON Lines.",
    ])


def _map(q, units):
    if not isinstance(q, str) or not q.strip() or q.strip().lower() in ("null", "none"):
        return None
    return locate_quote(q, units)


def parse_reply(text: str, units: dict) -> dict:
    """{items, inventory, cases, unparsed, counts}; each item gets ``units`` and ``match`` from its quote."""
    objs, bad = parse_jsonl(text)
    items, inventory, cases, other = [], [], [], []
    for o in objs:
        kind = str(o.get("kind") or "").lower()
        if kind == "item" or (not kind and "category" in o):
            loc = _map(o.get("quote"), units) or {"units": [], "method": "none"}
            o["units"], o["match"] = loc["units"], loc["method"]
            for key in ("exception_of_quote", "precedence_over_quote"):
                l2 = _map(o.get(key), units)
                if l2:
                    o[key.replace("_quote", "_units")] = l2["units"]
            for s in o.get("steps") or []:
                if isinstance(s, dict):
                    l3 = _map(s.get("quote"), units)
                    s["units"] = l3["units"] if l3 else []
            items.append(o)
        elif kind == "inventory":
            loc = _map(o.get("quote"), units) or {"units": [], "method": "none"}
            o["units"], o["match"] = loc["units"], loc["method"]
            inventory.append(o)
        elif kind == "case":
            cases.append(o)
        else:
            other.append(o)
    for i, it in enumerate(items):
        it.setdefault("id", f"R4-{i + 1}")
    unmatched = [it["id"] for it in items if not it["units"]]
    return {"items": items, "inventory": inventory, "cases": cases, "other": other, "unparsed": bad,
            "counts": {"items": len(items), "inventory": len(inventory), "cases": len(cases), "unparsed": len(bad),
                       "unmatched_quotes": len(unmatched)},
            "unmatched": unmatched}


def read_r4(brief_text: str, api_text: str, units: dict, *, deadline=None, timeout_s: float = 480,
            raw_sink=None) -> tuple[dict, list[dict]]:
    """Run the blind audit. Returns (audit, usages). Raises models.ModelCallError when every backend fails."""
    text, usage = models.r4_text(build_prompt(brief_text, api_text), deadline=deadline, timeout_s=timeout_s, purpose="r4")
    if raw_sink:
        raw_sink(text)
    audit = parse_reply(text, units)
    audit["assurance"] = usage.get("assurance", "two model families")
    audit["backend"] = usage.get("backend")
    return audit, [usage]


def main(argv=None):
    """Standalone audit: .venv/bin/python -m builder.readers.r4 BRIEF.md API.json --out DIR [--base BASE.md]"""
    import argparse
    import json
    import time

    from .segment import segment

    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("api")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", action="append", default=[])
    ap.add_argument("--timeout", type=float, default=1200)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    source = "\n\n---\n\n".join([pathlib.Path(p).read_text() for p in a.base] + [pathlib.Path(a.brief).read_text()])
    t0 = time.monotonic()
    audit, usages = read_r4(source, pathlib.Path(a.api).read_text(), segment(source)["units"], timeout_s=a.timeout,
                            raw_sink=(out / "r4.raw.txt").write_text)
    (out / "r4.json").write_text(json.dumps(audit, indent=1))
    print(json.dumps({"seconds": round(time.monotonic() - t0, 1), "counts": audit["counts"], "usage": usages}, indent=1))


if __name__ == "__main__":
    main()
