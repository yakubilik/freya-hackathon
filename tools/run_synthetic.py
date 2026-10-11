"""Run a synthetic brief's cases (synthetic/<L>/cases.json) on the platform against OUR mock bank through its tunnel.

    .venv/bin/python tools/run_synthetic.py <L> [--agent <agent_id>] [--only C-01,C-02] [--reps 1] [--style pieces]

The agent must have been deployed as the TEST variant with its tools on the tunnel URL:
    OWN_BANK_URL=$(cat bank/.url) .venv/bin/python builder/build.py synthetic/<L>/brief.md synthetic/<L>/api.json \\
        --slot synthetic-<L> --deploy-variant test --no-platform-test      (a raw-material brief: pass the directory)
Then this script opens one bank session per case with the case as the customer (any identity questions, any `now`,
faults) and the brief's API shape as the bank profile (bank/adapters.profile_from_openapi), runs the kit's scorer with
FREYA_BANK_HOST pointed at the tunnel, and scores the ledger as usual. Needs the .env exported.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "kit" / "build-the-builder"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

URL = (ROOT / "bank" / ".url").read_text().strip() if (ROOT / "bank" / ".url").exists() else ""
os.environ.setdefault("FREYA_BANK_HOST", URL)
os.environ.setdefault("FREYA_BANK_TEAM_KEY", "synthetic-team-key-0123456789")
import run_cases  # noqa: E402
import score  # noqa: E402
from bank.adapters import profile_from_openapi  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("letter")
    ap.add_argument("--agent")
    ap.add_argument("--only")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--style")
    a = ap.parse_args()
    d = ROOT / "synthetic" / a.letter
    cases = json.load(open(d / "cases.json"))
    profile = profile_from_openapi(json.load(open(d / "api.json")))
    by_id = {c["id"]: c for c in cases}
    agent = a.agent
    if not agent:
        state = json.load(open(ROOT / "builder" / ".freya-agents.json"))
        agent = state["synthetic-" + a.letter]["agent_id"]
    real_http = score.http

    def http(path, body=None):
        if path == "/v1/practice/sessions" and body and body.get("case") in by_id:
            c = dict(by_id[body["case"]])
            c["profile"] = profile
            body = {"customer": c}
        return real_http(path, body)

    run_cases.http = http
    score.http = http
    out = ROOT / "runs" / "synthetic" / ("%s-%s.json" % (a.letter, a.only.replace(",", "_") if a.only else "all"))
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = ["run_cases.py", agent, "--brief", a.letter, "--cases", str(d / "cases.json"), "--reps", str(a.reps), "--out", str(out)]
    if a.only:
        argv += ["--only", a.only]
    if a.style:
        argv += ["--style", a.style]
    sys.argv = argv
    print("bank", os.environ["FREYA_BANK_HOST"], "| agent", agent, "| cases", len(cases), flush=True)
    run_cases.main()


if __name__ == "__main__":
    main()
