"""Read one brief into a frozen, hashed rule table (oracle-design Steps 0 to 3).

    .venv/bin/python -m builder.readers.read_brief BRIEF.md API.json --out runs/<id>/ [--base BASE.md] [--skip-r4]

Step 0 segments the brief and parses the API file; Step 1 runs R1 (Claude) and R4 (second family, blind) in
parallel threads under one outer Deadline; Step 2 runs the mechanical checks; Step 3 adjudicates and applies one
correction cycle; then the table is frozen and hashed. ``--base`` prepends a brief this one builds on (Brief B
on Brief A) as earlier documents of the same source.

Outputs in ``out_dir``: table.json, r1.raw.txt, r4.raw.txt, checks.json, adjudication.json, trace.jsonl.
Degradation: R4 missing or late -> assurance "source audit incomplete"; adjudication out of time -> "not
adjudicated"; R1 failing twice -> ReaderError (the orchestrator falls back to the kit builder).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import models
from .adjudicate import adjudicate, freeze
from .api_file import parse_api
from .checks import run_checks
from .r1 import ReaderError, read_r1
from .r4 import read_r4
from .segment import lossless, segment

R4_SHARE = 0.67          # R4 must be back by two thirds of the reading budget (8:00 of 12:00)
ADJ_MIN_S = 60           # below this, adjudication is skipped
ADJ_MAX_S = 300


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Trace:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.lock = threading.Lock()
        self.calls: list[dict] = []
        path.write_text("")

    def add(self, usage: dict):
        line = {"model": usage.get("model"), "purpose": usage.get("purpose"), "tokens": usage.get("tokens"),
                "seconds": usage.get("seconds"), "backend": usage.get("backend")}
        detail = usage.get("detail") if isinstance(usage.get("detail"), dict) else {}
        # cost and the token breakdown, when the backend reports them (the Claude SDK does): the rules ask for a
        # trace of every model call, and the cost of a build is part of what we measure
        for k in ("cost_usd", "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            if detail.get(k) is not None:
                line[k] = detail[k]
        with self.lock:
            self.calls.append(line)
            with self.path.open("a") as fh:
                fh.write(json.dumps(line) + "\n")


def _write(path: pathlib.Path, obj):
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False, default=str))


def read(brief_path, api_path, *, out_dir, deadline_s: float = 720, skip_r4: bool = False, base_paths=()) -> dict:
    t0 = time.monotonic()
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deadline = models.Deadline(deadline_s)
    r4_deadline = models.Deadline(deadline_s * R4_SHARE)
    trace = Trace(out / "trace.jsonl")
    timings: dict[str, float] = {}

    # Step 0
    brief_text = pathlib.Path(brief_path).read_text()
    source = "\n\n---\n\n".join([pathlib.Path(p).read_text() for p in base_paths] + [brief_text])
    api_text = pathlib.Path(api_path).read_text()
    api = parse_api(json.loads(api_text))
    seg = segment(source)
    if not lossless(source, seg["units"]):
        raise ReaderError("segmentation is not lossless")
    timings["segment"] = round(time.monotonic() - t0, 2)

    # Step 1: R1 and R4 in parallel
    r1_raw, r4_raw = out / "r1.raw.txt", out / "r4.raw.txt"
    r1_raw.write_text("")
    r4_raw.write_text("")

    def run_r1():
        s = time.monotonic()
        try:
            return read_r1(seg, api, deadline=deadline, timeout_s=max(60.0, deadline.remaining() - 90),
                           raw_sink=r1_raw.write_text)
        finally:
            timings["r1"] = round(time.monotonic() - s, 1)

    def run_r4():
        s = time.monotonic()
        try:
            # its own deadline: a late R4 (or its Claude fallback) must not run on after the reading is done
            return read_r4(source, api_text, seg["units"], deadline=r4_deadline, timeout_s=deadline_s * R4_SHARE,
                           raw_sink=r4_raw.write_text)
        finally:
            timings["r4"] = round(time.monotonic() - s, 1)

    audit, r4_error = None, None
    ex = ThreadPoolExecutor(max_workers=2)
    try:
        f1 = ex.submit(run_r1)
        f4 = None if skip_r4 else ex.submit(run_r4)
        try:
            table, r1_usages, r1_info = f1.result()
        except ReaderError:
            raise
        except models.ModelCallError as e:
            raise ReaderError(f"R1 failed: {e}") from e
        for u in r1_usages:
            trace.add(u)
        if f4 is not None:
            try:
                audit, r4_usages = f4.result(timeout=max(1.0, deadline_s * R4_SHARE - (time.monotonic() - t0) + 5))
                for u in r4_usages:
                    trace.add(u)
            except Exception as e:  # noqa: BLE001 - any R4 failure degrades, never stops the build
                r4_error = f"{type(e).__name__}: {e}"
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if audit is not None:
        assurance = "single model family" if audit.get("assurance") == "single model family" else "two model families"
    else:
        assurance = "source audit incomplete"

    # Step 2
    s = time.monotonic()
    checks = run_checks(table, api)
    timings["checks"] = round(time.monotonic() - s, 2)
    fatal = [f for f in checks["findings"] if f["severity"] == "fatal"]

    # Step 3
    adjudication = {"skipped": None}
    if deadline.remaining() >= ADJ_MIN_S and (audit is not None or checks["counts"]["item"]):
        s = time.monotonic()
        try:
            table, adjudication = adjudicate(table, api, audit, checks["findings"], deadline=deadline,
                                             timeout_s=min(ADJ_MAX_S, deadline.remaining() - 10))
            for u in adjudication.get("usages", []):
                trace.add(u)
        except models.ModelCallError as e:
            adjudication = {"skipped": f"adjudicator failed: {e}"}
        timings["adjudicate"] = round(time.monotonic() - s, 1)
    else:
        adjudication = {"skipped": "no time left" if deadline.remaining() < ADJ_MIN_S else "nothing to adjudicate"}
    if adjudication.get("skipped") and assurance != "source audit incomplete":
        assurance += ", not adjudicated"
    checks_after = run_checks(table, api) if adjudication.get("summary", {}).get("applied") else checks

    run_metadata = {
        "models": sorted({c["model"] for c in trace.calls if c.get("model")}),
        "timings": timings, "usage": trace.calls,
        "tokens": sum(int(c.get("tokens") or 0) for c in trace.calls),
        "assurance": assurance, "r4_error": r4_error,
        "r4_counts": (audit or {}).get("counts"),
        "r1": {k: v for k, v in r1_info.items() if k not in ("battery",)},
        "findings": {"before": checks["counts"], "after": checks_after["counts"],
                     "fatal": [f["message"] for f in [x for x in checks_after["findings"] if x["severity"] == "fatal"]]},
        "examples": checks_after["example_results"],
        "adjudication": adjudication.get("summary") or {"skipped": adjudication.get("skipped")},
        "hashes": {"brief": _sha(source), "tools": _sha(api_text)},
        "brief_path": str(brief_path), "api_path": str(api_path), "base_paths": [str(p) for p in base_paths],
    }
    timings["total"] = round(time.monotonic() - t0, 1)
    frozen = freeze(table, run_metadata)

    _write(out / "checks.json", {"before": checks, "after": checks_after, "fatal_before": fatal})
    _write(out / "adjudication.json", {k: v for k, v in adjudication.items() if k != "usages"} | {"r4": audit})
    _write(out / "table.json", frozen)
    if r1_info.get("battery"):
        _write(out / "r1.battery.json", r1_info["battery"])
    return frozen


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read a brief into a frozen rule table.")
    ap.add_argument("brief")
    ap.add_argument("api")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", action="append", default=[], help="a brief this one builds on (repeatable)")
    ap.add_argument("--deadline", type=float, default=720)
    ap.add_argument("--skip-r4", action="store_true")
    a = ap.parse_args(argv)
    try:
        t = read(a.brief, a.api, out_dir=a.out, deadline_s=a.deadline, skip_r4=a.skip_r4, base_paths=a.base)
    except ReaderError as e:
        print(f"ReaderError: {e}", file=sys.stderr)
        return 2
    rm = t["run_metadata"]
    print(json.dumps({"table_hash": rm["table_hash"], "assurance": rm["assurance"], "timings": rm["timings"],
                      "tokens": rm["tokens"], "obligations": len(t["obligations"]), "parameters": len(t["parameters"]),
                      "findings": rm["findings"], "adjudication": rm["adjudication"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
