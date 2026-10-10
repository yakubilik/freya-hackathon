"""Replay the recorded behaviour of the organizers' bank against a bank server over HTTP.

    python3 -m bank.replay [--url http://127.0.0.1:8787] [--recording research/bank-recorded-behaviour.json]
                           [--cases kit/build-the-builder/public-test-set.json]

Without --url a server is started in-process on a free port. Every recorded sequence is sent step by step:
open a session for the sequence's case, substitute the customer_id, send each step, compare status and result
JSON exactly, then compare the ledger (team, last_at and customer ids ignored). Exit code 1 when anything differs.
"""
import argparse, json, os, pathlib, sys, threading, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bank import server as bank_server  # noqa: E402

DEFAULT_RECORDING = ROOT / "research" / "bank-recorded-behaviour.json"
DEFAULT_CASES = ROOT / "kit" / "build-the-builder" / "public-test-set.json"
TEAM_KEY = "replay-team-key-0123456789"
LEDGER_IGNORED = ("team", "last_at")


def http(base, path, body=None, raw=None, team_key=TEAM_KEY, timeout=30):
    """(status, json) for one request. `raw` sends bytes as they are; `body` None with raw None sends a GET."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json", "x-team-key": team_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def start_server(cases_path=DEFAULT_CASES, host="127.0.0.1"):
    """A bank serving `cases_path` on a free port, in a daemon thread. Returns (server, base_url)."""
    srv = bank_server.serve(0, [str(cases_path)], host)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://{host}:{srv.server_address[1]}"


def replay_sequence(base, seq, team_key=TEAM_KEY):
    """Mismatches of one recorded sequence against the bank at `base`: a list of strings, empty when identical."""
    bad = []
    if "steps" not in seq:                                     # a single request with no session
        tool, body = seq["tool"], seq.get("body")
        if body is None: raw = b"not json" if "json" in seq.get("title", "") else b""
        else: raw = None
        status, result = http(base, "/v1/" + tool, body if raw is None else None, raw=raw, team_key=team_key)
        if (status, result) != (seq["status"], seq["result"]): bad.append(f"{tool}: got {status} {json.dumps(result)}, recorded {seq['status']} {json.dumps(seq['result'])}")
        return bad
    status, session = http(base, "/v1/practice/sessions", {"case": seq["case"]}, team_key=team_key)
    if status != 200 or not session.get("ok"): return [f"session: {status} {json.dumps(session)}"]
    want_vars = {k: v for k, v in seq["session"]["variables"].items() if k != "customer_id"}
    got_vars = {k: v for k, v in session["variables"].items() if k != "customer_id"}
    if got_vars != want_vars: bad.append(f"session variables: got {json.dumps(got_vars)}, recorded {json.dumps(want_vars)}")
    cid = session["variables"]["customer_id"]
    for i, step in enumerate(seq["steps"], 1):
        body = {"customer_id": cid, **step["body"]}
        status, result = http(base, "/v1/" + step["tool"], body, team_key=team_key)
        if (status, result) != (step["status"], step["result"]):
            bad.append(f"step {i} {step['tool']} {json.dumps(step['body'])}: got {status} {json.dumps(result)}, recorded {step['status']} {json.dumps(step['result'])}")
    status, ledger = http(base, "/v1/practice/ledger/" + cid, team_key=team_key)
    if status != 200: bad.append(f"ledger: {status} {json.dumps(ledger)}"); return bad
    want = seq["ledger"]
    if list(ledger.keys()) != list(want.keys()): bad.append(f"ledger keys: got {list(ledger.keys())}, recorded {list(want.keys())}")
    for k in want:
        if k in LEDGER_IGNORED: continue
        if ledger.get(k) != want[k]: bad.append(f"ledger.{k}: got {json.dumps(ledger.get(k))}, recorded {json.dumps(want[k])}")
    return bad


def replay_all(base, recording=DEFAULT_RECORDING, team_key=TEAM_KEY):
    """{title: [mismatches]} for every sequence of the recording."""
    return {seq.get("title", f"#{i}"): replay_sequence(base, seq, team_key) for i, seq in enumerate(json.load(open(recording)))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", help="a running bank; without it a server is started in-process")
    ap.add_argument("--recording", default=str(DEFAULT_RECORDING)); ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--team-key", default=os.environ.get("FREYA_BANK_TEAM_KEY") or TEAM_KEY)
    a = ap.parse_args()
    srv, base = (None, a.url.rstrip("/")) if a.url else start_server(a.cases)
    results = replay_all(base, a.recording, a.team_key)
    failed = 0
    for title, bad in results.items():
        print(("FAIL" if bad else "PASS"), title)
        for b in bad: print("     -", b)
        failed += bool(bad)
    print(f"\n{len(results) - failed} / {len(results)} recorded sequences reproduced")
    if srv: srv.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__": main()
