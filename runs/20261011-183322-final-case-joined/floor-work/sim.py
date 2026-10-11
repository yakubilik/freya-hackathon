"""One simulation of the saved agent with the simulated callers you wrote:
    python3 sim.py callers.json
callers.json is a list of {"name", "prompt", "variables": {...}, "success_criteria"}. Callers are kept on the platform by
name (the same name and text reuses the same one). Prints per caller pass/fail, the judge's reason, every tool request
with its body and result, and how the call ended; the raw result goes to out/sim-<n>.json."""
import hashlib, json, os, sys, time
sys.path.insert(0, "kit")
import freya
SIM_S = 240        # what one simulation may take
SAVE_S = 60        # what a save after it needs
run = json.load(open("run.json"))
left = lambda: run["deadline_epoch"] - time.time()
callers = json.load(open(sys.argv[1]))
state = json.load(open(run["state_file"])).get(run["slot"]) if os.path.exists(run["state_file"]) else None
if not state:
    sys.exit("nothing saved yet: run save.py first")
done = [f for f in os.listdir("out") if f.startswith("sim-") and f.endswith(".started")]
n = len(done) + 1
if n > run.get("sims_max", 3):
    sys.exit("no more simulations in this run (%d done)" % len(done))
if left() < SIM_S + SAVE_S:
    sys.exit("%.0f s left: not enough for a simulation (%d) and a save (%d)" % (left(), SIM_S, SAVE_S))
open("out/sim-%d.started" % n, "w").close()       # a failed simulation counts too
store_path = "out/callers.json"
store = json.load(open(store_path)) if os.path.exists(store_path) else {}
spec = {c["name"]: {"name": c["name"], "prompt": c["prompt"], "successCriteria": c["success_criteria"], "tags": ["floor"]}
        for c in callers}
key = {k: hashlib.sha1(json.dumps(v, sort_keys=True).encode()).hexdigest()[:10] for k, v in spec.items()}
new = [k for k in spec if store.get(k, {}).get("key") != key[k]]
if new:
    made = freya.create_personas([spec[k] for k in new])["personas"]
    store.update({k: {"id": p["id"], "key": key[k]} for k, p in zip(new, made)})
    json.dump(store, open(store_path, "w"), indent=1)
ids = {c["name"]: store[c["name"]]["id"] for c in callers}
t0 = time.time()
row = {"n": n, "callers": len(callers), "passed": 0, "simulation_id": None, "status": None, "seconds": 0, "failed": []}
def record():
    row["seconds"] = round(time.time() - t0, 1)
    if run.get("sims_log"):
        with open(run["sims_log"], "a") as f:
            f.write(json.dumps(row) + "\n")
try:
    sim = freya.api("POST", "/api/v2/simulations", {
        "agentId": state["agent_id"], "name": "floor sim %d %s" % (n, time.strftime("%H:%M:%S")), "mode": "chat",
        "selectedPersonaIds": list(ids.values()),
        "customerVariablesMap": {ids[c["name"]]: c.get("variables", {}) for c in callers},
        "maxConcurrentCalls": max(1, len(callers)), "runsPerPersona": 1, "maxCallDurationSeconds": 180,
        "assistantLlmOverride": freya.AGENT_LLM, "routingLlmOverride": freya.AGENT_LLM,
        "extractionLlmOverride": freya.AGENT_LLM, "personaLlmOverride": freya.SIM_LLM, "analysisLlmOverride": freya.SIM_LLM})
    sim_id = row["simulation_id"] = (sim.get("simulation") or sim)["id"]
    stop = time.time() + min(SIM_S, left() - SAVE_S)
    status = None
    while time.time() < stop:
        time.sleep(10)
        try:
            s = freya.api("GET", "/api/v2/simulations/%s" % sim_id); status = (s.get("simulation") or s).get("status")
        except Exception as e:
            print("poll failed (%s), retrying" % str(e)[:80], flush=True); continue
        if status in ("completed", "failed", "paused", "cancelled"):
            break
    row["status"] = status if status in ("completed", "failed", "paused", "cancelled") else "not finished in time (%s)" % status
    its = freya.api("GET", "/api/v2/simulations/%s/iterations" % sim_id)
    its = its.get("iterations") or its.get("items") or its
    runs = freya.get_iteration(sim_id, its[0]["id"])["runs"] if its else []
except Exception as e:
    row["status"] = "error: %s" % str(e)[:300]; record()
    sys.exit("simulation failed: %s" % str(e)[:300])
by_persona = {r.get("personaId"): r for r in runs}
out = {"simulation_id": sim_id, "status": row["status"], "callers": []}
for c in callers:
    r = by_persona.get(ids[c["name"]], {})
    one = {"name": c["name"], "outcome": r.get("outcome"), "reason": r.get("reason"), "tools": [], "ended": None}
    if r.get("callId"):
        try:
            call = freya.get_call(r["callId"])
            one["ended"] = call.get("endedReason"); one["transcript"] = call.get("transcript")
            for m in call.get("messages", []):
                if m.get("role") != "system":
                    continue
                try:
                    ev = json.loads(m.get("message") or "{}")
                except ValueError:
                    continue
                if ev.get("event") == "function_call_start":
                    a = ev.get("args") or {}
                    one["tools"].append({"function": ev.get("function"), "url": a.get("url"), "method": a.get("method"),
                                         "body": a.get("body")})
                elif ev.get("event") == "function_call_complete" and one["tools"]:
                    one["tools"][-1]["result"] = ev.get("result")
                elif ev.get("event") == "error":
                    one["tools"].append({"error": ev.get("message"), "details": ev.get("details")})
        except Exception as e:
            one["ended"] = "call unreadable: %s" % str(e)[:200]
    out["callers"].append(one)
    ok = one["outcome"] == "pass"
    row["passed"] += ok
    if not ok:
        row["failed"].append(c["name"])
    print("%s %s | ended: %s\n  judge: %s" % ("PASS" if ok else "FAIL", c["name"], one["ended"], " ".join(str(one["reason"]).split())[:600]))
    for t in one["tools"]:
        print("  tool %s" % json.dumps(t, ensure_ascii=False)[:1500])
json.dump(out, open("out/sim-%d.json" % n, "w"), indent=1, ensure_ascii=False)
record()
print("simulation %d: %d / %d passed, %s, %s, %.0f s; raw result out/sim-%d.json" % (
    n, row["passed"], len(callers), sim_id, row["status"], row["seconds"], n))
