"""Run the extended scenario set (scenarios/extended-test-set.json) on a deployed agent through the kit's scorer.

    .venv/bin/python tools/run_extended.py <agent_id> --brief A [--chunk 15] [--only EXT-001,EXT-002] [--list]

Each scenario plays on the practice-bank account of its `session_case` (the bank knows only the 13 official
accounts), so the session request is rewritten from the scenario id to that account. Scenarios run in chunks, one
simulation per chunk, results in runs/extended/<brief>-<n>.json; a chunk that already has a result file is skipped.
Needs the .env exported (FREYA_API_KEY, FREYA_BANK_TEAM_KEY).
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "kit" / "build-the-builder"
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
import run_cases  # noqa: E402
import score  # noqa: E402

CASES = ROOT / "scenarios" / "extended-test-set.json"
OUT = ROOT / "runs" / "extended"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_id")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--chunk", type=int, default=15)
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    cases = json.load(open(CASES))
    by_id = {c["id"]: c for c in cases}
    real_http = score.http

    def http(path, body=None):
        if path == "/v1/practice/sessions" and body and body.get("case") in by_id:
            body = {"case": by_id[body["case"]].get("session_case", body["case"])}
        return real_http(path, body)

    run_cases.http = http
    ids = [c["id"] for c in cases if c["brief"] == a.brief and (not a.only or c["id"] in a.only.split(","))]
    chunks = [ids[i:i + a.chunk] for i in range(0, len(ids), a.chunk)]
    OUT.mkdir(parents=True, exist_ok=True)
    for n, chunk in enumerate(chunks, 1):
        out = OUT / ("%s-%02d.json" % (a.brief, n))
        if a.list:
            print(out.name, ",".join(chunk))
            continue
        if out.exists():
            print("skip", out.name, "(done)", flush=True)
            continue
        print("== chunk %d of %d: %s" % (n, len(chunks), ",".join(chunk)), flush=True)
        sys.argv = ["run_cases.py", a.agent_id, "--brief", a.brief, "--cases", str(CASES), "--only", ",".join(chunk), "--out", str(out)]
        try:
            run_cases.main()
        except Exception as e:  # noqa: BLE001 - one bad chunk must not stop the night
            print("chunk %d failed: %s: %s" % (n, type(e).__name__, str(e)[:300]), flush=True)


if __name__ == "__main__":
    main()
