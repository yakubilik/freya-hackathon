"""One chat turn against the saved workflow, no simulation:
    python3 chat.py --vars '{"name": "value"}' 'first thing the caller says'
    python3 chat.py --call <call_id> 'next thing the caller says'
    python3 chat.py --end <call_id>"""
import argparse, json, sys
sys.path.insert(0, "kit")
import freya
ap = argparse.ArgumentParser()
ap.add_argument("message", nargs="?")
ap.add_argument("--vars", default="{}")
ap.add_argument("--call")
ap.add_argument("--end")
a = ap.parse_args()
run = json.load(open("run.json"))
if a.end:
    print(json.dumps(freya.api("POST", "/api/v2/chat/end", {"callId": a.end}))[:2000]); sys.exit()
state = json.load(open(run["state_file"])).get(run["slot"])
if not state:
    sys.exit("nothing saved yet: run save.py first")
body = {"workflowId": state["workflow_id"], "message": a.message or ""}
if a.call:
    body["callId"] = a.call
else:
    body["customerVariables"] = json.loads(a.vars)
r = freya.api("POST", "/api/v2/chat/message", body)
print(json.dumps({"callId": r.get("callId"), "response": r.get("response")}, ensure_ascii=False))
