"""Cancel a platform simulation that hangs: status "running" and no update for STALE_MIN minutes blocks the workspace
(one simulation at a time; seen 2026-10-11, a run whose client died stayed "running" for an hour).
    .venv/bin/python tools/sim_watchdog.py [--stale-min 12] [--once]
"""
import argparse
import datetime as dt
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import build  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-min", type=float, default=12)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    build.load_env()
    fr = build.import_freya()
    while True:
        try:
            r = fr.api("GET", "/api/v2/simulations", workspaceId=fr.workspace_id(), limit=5)
            for s in (r.get("simulations") or r.get("items") or r):
                if s.get("status") != "running":
                    continue
                upd = s.get("updatedAt") or s.get("createdAt")
                t = dt.datetime.fromisoformat(upd.replace("Z", "+00:00"))
                age = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60
                if age > a.stale_min:
                    res = fr.api("POST", "/api/v2/simulations/%s/cancel" % s["id"], {})
                    print("%s cancelled %s (%s, idle %.0f min): %s" % (dt.datetime.utcnow().strftime("%H:%M:%SZ"), s["id"][:8], s.get("name"), age, res), flush=True)
        except Exception as e:  # noqa: BLE001
            print("watchdog error: %s: %s" % (type(e).__name__, str(e)[:120]), flush=True)
        if a.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
