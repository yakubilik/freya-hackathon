"""The platform gate: what the platform loop consists of since 2026-10-11 (runs/night/test-plan.md), run with the hidden
benchmark's rule (3 runs per case, a case counts only when all 3 pass), one set after another (a workspace runs one
simulation at a time).

    .venv/bin/python tools/gate.py [--dry-run] [--deploy] [--reps 3] [--sets public-A,public-B,stability,D,I]
                                   [--agent-a ID] [--agent-b ID] [--agent-d ID] [--agent-i ID] [--out-dir runs/gate/<ts>]

Sets: public A (10 cases, the organisers' scorer), public B (3), the stability subset (scenarios/stability-set.json: 20
extended scenarios with styles, 13 on the Brief A agent and 7 on the Brief B agent), synthetic D (30 cases, clean brief,
our mock bank through its tunnel) and synthetic I (30 cases, raw brief). Deploys nothing unless --deploy is given (then
tools/brief_loop.py's deploy_public / deploy_synthetic run first). Agent ids default to brief_loop.PUBLIC for A and B and
to builder/.freya-agents.json (slots synthetic-D, synthetic-I) for D and I.

Runners reused as subprocesses, nothing new talks to the platform: kit/build-the-builder/tools/run_cases.py (public),
tools/run_extended.py --cases --reps (stability), tools/run_synthetic.py --reps (D, I). Output: one line per case (PASS
only with 3/3, else the failing run's reasons), a summary per set, runs/gate/<timestamp>/results.json. The wall-time
estimate printed first is fitted on results/log.jsonl (seconds per simulation against cases per simulation)."""
import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import brief_loop  # noqa: E402  (PY, env(), PUBLIC, deploy_public, deploy_synthetic)

PY = brief_loop.PY if pathlib.Path(brief_loop.PY).exists() else sys.executable
LOG = ROOT / "kit" / "build-the-builder" / "results" / "log.jsonl"
STABILITY = ROOT / "scenarios" / "stability-set.json"
ALL_SETS = ["public-A", "public-B", "stability", "D", "I"]


def fit_seconds():
    """Seconds per simulation = a + b * cases, least squares on log.jsonl; the kit's own figure (3 to 11 minutes for
    ten customers) when the log is short."""
    xs, ys = [], []
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("seconds") and r.get("total") and r.get("runs"):
                xs.append(r["total"])
                ys.append(r["seconds"] / r["runs"])
    if len(xs) < 10 or len(set(xs)) < 2:
        return 150.0, 25.0, len(xs)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b, n


def default_agents():
    ids = {"A": brief_loop.PUBLIC["A"]["agent"], "B": brief_loop.PUBLIC["B"]["agent"], "D": None, "I": None}
    p = ROOT / "builder" / ".freya-agents.json"
    if p.exists():
        state = json.load(open(p))
        for L in ("D", "I"):
            ids[L] = (state.get("synthetic-" + L) or {}).get("agent_id")
    return ids


def plan(sets, reps, agents):
    """One entry per simulation batch: (set, brief, agent, case ids, result file name)."""
    pub = json.load(open(ROOT / "kit" / "build-the-builder" / "public-test-set.json"))
    stab = json.load(open(STABILITY)) if STABILITY.exists() else []
    out = []
    if "public-A" in sets:
        out.append(("public-A", "A", agents["A"], [c["id"] for c in pub if c["brief"] == "A"], "public-A.json"))
    if "public-B" in sets:
        out.append(("public-B", "B", agents["B"], [c["id"] for c in pub if c["brief"] == "B"], "public-B.json"))
    if "stability" in sets:
        for L in ("A", "B"):
            ids = [c["id"] for c in stab if c["brief"] == L]
            if ids:
                out.append(("stability", L, agents[L], ids, "stability-%s.json" % L))
    for L in ("D", "I"):
        if L in sets:
            cases = json.load(open(ROOT / "synthetic" / L / "cases.json"))
            out.append((L, L, agents[L], [c["id"] for c in cases], "synthetic-%s.json" % L))
    return out


def run_batch(entry, reps, out_dir):
    name, L, agent, ids, fname = entry
    log_path = out_dir / (fname.replace(".json", ".log"))
    target = out_dir / fname
    if name.startswith("public"):
        cmd = [PY, "kit/build-the-builder/tools/run_cases.py", agent, "--brief", L, "--only", ",".join(ids), "--reps", str(reps), "--out", str(target)]
        rc = brief_loop.run(cmd, log_path, timeout=3 * 3600)
    elif name == "stability":
        sub = out_dir / ("stability-%s-raw" % L)
        cmd = [PY, "tools/run_extended.py", agent, "--brief", L, "--cases", str(STABILITY), "--chunk", "99", "--reps", str(reps), "--out-dir", str(sub)]
        rc = brief_loop.run(cmd, log_path, timeout=3 * 3600)
        cand = sorted(glob.glob(str(sub / ("%s-*.json" % L))))
        if cand:
            shutil.copy(cand[-1], target)
    else:
        cmd = [PY, "tools/run_synthetic.py", L, "--agent", agent, "--reps", str(reps)]
        t_start = time.time()
        rc = brief_loop.run(cmd, log_path, timeout=4 * 3600)
        src = ROOT / "runs" / "synthetic" / ("%s-all.json" % L)      # where run_synthetic.py writes without --only
        if src.exists() and src.stat().st_mtime >= t_start:
            shutil.copy(src, target)
    if not target.exists():
        return rc, None
    return rc, json.load(open(target))


def report_batch(name, data, reps):
    """One line per case; a case passes only with reps/reps. Returns the case rows for results.json."""
    rows = []
    if not data:
        print("  (no result file: the run failed or timed out, see the .log)")
        return rows
    by_rep = data.get("all_rows") or [data.get("rows") or []]
    for f in data.get("final") or []:
        cid = f["id"]
        reasons = []
        for k, rep in enumerate(by_rep, 1):
            r = next((x for x in rep if x["id"] == cid), None)
            if r and not r["pass"]:
                reasons.append("run %d: %s" % (k, " | ".join(r["failed"])[:300]))
        ok = f.get("pass") and f.get("passes", 0) >= reps
        print("  %s %-8s %d/%d  %s%s" % ("PASS" if ok else "FAIL", cid, f.get("passes", 0), f.get("runs", reps), f.get("family", ""),
                                        "" if ok else "\n         " + "\n         ".join(reasons[:1] or ["no run row"])))
        rows.append({"id": cid, "family": f.get("family"), "passes": f.get("passes"), "runs": f.get("runs"), "pass": bool(ok), "reasons": reasons})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list what would run and the time estimate, run nothing")
    ap.add_argument("--deploy", action="store_true", help="deploy A, B (public slots) and D, I (test variant) first, via brief_loop")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--sets", default=",".join(ALL_SETS))
    ap.add_argument("--agent-a"); ap.add_argument("--agent-b"); ap.add_argument("--agent-d"); ap.add_argument("--agent-i")
    ap.add_argument("--out-dir")
    a = ap.parse_args()
    sets = [s for s in a.sets.split(",") if s]
    bad_sets = [s for s in sets if s not in ALL_SETS]
    if bad_sets:
        raise SystemExit("unknown set(s) %s; choose from %s" % (bad_sets, ALL_SETS))
    agents = default_agents()
    for L, v in (("A", a.agent_a), ("B", a.agent_b), ("D", a.agent_d), ("I", a.agent_i)):
        if v:
            agents[L] = v
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else ROOT / "runs" / "gate" / stamp
    batches = plan(sets, a.reps, agents)
    base, per, n = fit_seconds()
    est = {}
    print("Platform gate %s: %d runs per case, a case counts only with %d/%d." % (stamp, a.reps, a.reps, a.reps))
    print("Wall-time estimate (fit on %d logged simulations: %.0f s + %.0f s per case, one simulation per run, sets in sequence):" % (n, base, per))
    total = 0.0
    for name, L, agent, ids, fname in batches:
        sec = a.reps * (base + per * len(ids))
        est[fname] = round(sec)
        total += sec
        print("  %-10s brief %s  agent %s  %2d cases x %d runs  ~%3.0f min" % (name, L, (agent or "MISSING")[:8], len(ids), a.reps, sec / 60))
    print("  total ~%.0f min (%.1f h); busy platform periods have run 2 to 3 times slower than the fit." % (total / 60, total / 3600))
    missing = [name for name, L, agent, ids, fname in batches if not agent]
    if missing:
        print("No agent id for %s: pass --agent-<letter> or run with --deploy." % ", ".join(missing))
    if a.dry_run:
        print("dry run: nothing started.")
        return 0
    if missing:
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"started": stamp, "reps": a.reps, "agents": agents, "estimate_seconds": est, "sets": {}}
    if a.deploy:
        for name, L in (("public-A", "A"), ("public-B", "B"), ("D", "D"), ("I", "I")):
            if name in sets:
                if L in brief_loop.PUBLIC:
                    ok = brief_loop.deploy_public(L)
                else:
                    table = ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json"
                    ok = brief_loop.deploy_synthetic(L, table) if table.exists() else False
                results.setdefault("deploy", {})[L] = ok
                if not ok:
                    print("deploy of %s FAILED, its set is skipped" % L)
                    sets = [s for s in sets if s != name]
        batches = plan(sets, a.reps, agents)
    t0 = time.time()
    for entry in batches:
        name, L, agent, ids, fname = entry
        print("\n== %s (brief %s, %d cases, agent %s) started %s" % (name, L, len(ids), agent, dt.datetime.now().strftime("%H:%M:%S")), flush=True)
        t1 = time.time()
        rc, data = run_batch(entry, a.reps, out_dir)
        rows = report_batch(name, data, a.reps)
        passed = sum(r["pass"] for r in rows)
        took = time.time() - t1
        print("  -- %s: %d / %d pass with %d/%d; %.0f min (estimate %.0f min); rc %s" % (name, passed, len(ids), a.reps, a.reps, took / 60, est[fname] / 60, rc))
        results["sets"].setdefault(name, []).append({"brief": L, "agent": agent, "file": fname, "rc": rc, "passed": passed, "total": len(ids),
                                                     "seconds": round(took), "cases": rows})
        (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    print("\n== summary (%.0f min)" % ((time.time() - t0) / 60))
    for name, parts in results["sets"].items():
        print("  %-10s %d / %d" % (name, sum(p["passed"] for p in parts), sum(p["total"] for p in parts)))
    results["seconds"] = round(time.time() - t0)
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    print("results: %s" % (out_dir / "results.json").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
