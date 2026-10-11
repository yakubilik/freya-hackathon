"""Keep the platform moving: one simulation runs at a time per workspace, and a simulation whose calls stop progressing
blocks everything (seen 2026-10-11 all day: runs orphaned by API flaps stayed "running" for 40+ minutes).
Every 60 s: list the simulations; for the running one count its finished calls (iteration runs with an outcome or a
callId). If that count has not changed for --stale-min minutes, cancel it. Every status change and every API up/down
flip is written to stdout (runs/night/platform.log) so people and agents can see what the platform is doing.
    .venv/bin/python tools/sim_watchdog.py [--stale-min 12] [--once]
"""
import argparse
import datetime as dt
import pathlib
import socket
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import build  # noqa: E402


def now():
    return dt.datetime.now().strftime("%H:%M:%S")


def progress(fr, sim_id):
    """(finished calls, total runs) of the simulation's first iteration; None when unreadable."""
    its = fr.api("GET", f"/api/v2/simulations/{sim_id}/iterations")
    its = its.get("iterations") or its.get("items") or its
    if not its:
        return None
    it = fr.get_iteration(sim_id, its[0]["id"])
    runs = it.get("runs") or []
    # a call that ended but whose judge verdict is still "analyzing"/"running" is not finished: only terminal outcomes count
    done = sum(1 for r in runs if (r.get("outcome") or "") in ("pass", "fail", "inconclusive", "error") or r.get("status") in ("completed", "failed"))
    return done, len(runs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-min", type=float, default=12)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    build.load_env()
    fr = build.import_freya()
    socket.setdefaulttimeout(60)
    api_up = None
    seen = {}      # sim id -> (last progress tuple, time it last changed, last status printed)
    while True:
        try:
            r = fr.api("GET", "/api/v2/simulations", workspaceId=fr.workspace_id(), limit=5)
            if api_up is not True:
                print(f"{now()} API up", flush=True); api_up = True
            sims = r.get("simulations") or r.get("items") or r
            for s in sims:
                sid, st = s["id"], s.get("status")
                rec = seen.get(sid)
                if rec is None or rec[2] != st:
                    print(f"{now()} sim {sid[:8]} {st} ({s.get('name')}, created {str(s.get('createdAt',''))[11:19]}Z)", flush=True)
                    seen[sid] = [None, time.time(), st]
                if st != "running":
                    continue
                try:
                    p = progress(fr, sid)
                except Exception as e:  # noqa: BLE001
                    print(f"{now()} sim {sid[:8]} progress unreadable: {str(e)[:80]}", flush=True); continue
                rec = seen[sid]
                if p != rec[0]:
                    if rec[0] is not None:
                        print(f"{now()} sim {sid[:8]} progress {p[0]}/{p[1]} calls", flush=True)
                    rec[0], rec[1] = p, time.time()
                idle = (time.time() - rec[1]) / 60
                if idle > a.stale_min:
                    res = fr.api("POST", f"/api/v2/simulations/{sid}/cancel", {})
                    print(f"{now()} CANCELLED {sid[:8]} ({s.get('name')}): no new finished call for {idle:.0f} min at {p}: {res}", flush=True)
                    rec[1] = time.time()
        except Exception as e:  # noqa: BLE001
            if api_up is not False:
                print(f"{now()} API down: {type(e).__name__}: {str(e)[:100]}", flush=True); api_up = False
        if a.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
