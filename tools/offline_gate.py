"""Offline gate: every frozen rule table still compiles with the final emitter and passes the static walk. Seconds, no model,
no platform. Exit code 1 on any failure.

    .venv/bin/python tools/offline_gate.py [--full] [--only A,B,D] [--out-dir runs/gate-offline/<timestamp>]

Tables: fixtures/tables/brief-a.json and brief-b.json (the hand-written public tables, with the kit's openapi.json) and
runs/synthetic/build-<L>/read/table.json for every synthetic brief C..J that has one (with synthetic/<L>/api.json).
Each table goes through `python -m builder.emitter.emit` (emit + static walk; non-zero exit on a walk finding), final
variant. `--full` additionally runs tools/brief_loop.py's offline_gate (builder/build.py --reuse-table --no-deploy:
emit, walk, variant diff and the engine self-test) on the loop's known tables, which takes a few minutes.

The six synthetic briefs that left the platform loop (C, E, F, G, H, J) live only here (runs/night/test-plan.md)."""
import argparse
import datetime as dt
import glob
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
KIT_API = ROOT / "kit" / "build-the-builder" / "tools" / "openapi.json"


def tables(only=None):
    out = {"A": (ROOT / "fixtures" / "tables" / "brief-a.json", KIT_API),
           "B": (ROOT / "fixtures" / "tables" / "brief-b.json", KIT_API)}
    for t in sorted(glob.glob(str(ROOT / "runs" / "synthetic" / "build-*" / "read" / "table.json"))):
        L = pathlib.Path(t).parents[1].name.split("-", 1)[1]
        out[L] = (pathlib.Path(t), ROOT / "synthetic" / L / "api.json")
    if only:
        out = {L: v for L, v in out.items() if L in only}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="also run brief_loop.offline_gate (build.py --reuse-table, with the self-test)")
    ap.add_argument("--only", help="letters, comma separated")
    ap.add_argument("--out-dir")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else ROOT / "runs" / "gate-offline" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    bad = []
    for L, (table, api) in tables(only).items():
        if not table.exists() or not api.exists():
            print("SKIP %s: missing %s" % (L, table if not table.exists() else api))
            results[L] = {"status": "skipped"}
            continue
        wf = out_dir / ("%s.workflow.json" % L)
        t0 = time.time()
        r = subprocess.run([PY, "-m", "builder.emitter.emit", str(table), "--api", str(api), "--out", str(wf), "--variant", "final"],
                           cwd=ROOT, capture_output=True, text=True)
        took = time.time() - t0
        findings = [ln[len("walk: "):] for ln in r.stderr.splitlines() if ln.startswith("walk: ")]
        errors = [ln for ln in r.stderr.splitlines() if ln.startswith("emit error") or "Traceback" in ln]
        ok = r.returncode == 0
        results[L] = {"status": "pass" if ok else "fail", "rc": r.returncode, "seconds": round(took, 1), "table": str(table.relative_to(ROOT)),
                      "walk": findings, "errors": errors, "stdout": r.stdout.strip()[-400:]}
        (out_dir / ("%s.log" % L)).write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
        print("%s %s  %s  (%.1f s)%s" % ("PASS" if ok else "FAIL", L, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", took,
                                        "" if ok else "\n       " + "\n       ".join((findings + errors + r.stderr.strip().splitlines()[-3:])[:6])))
        if not ok:
            bad.append(L)
    if a.full:
        sys.path.insert(0, str(ROOT / "tools"))
        import brief_loop
        tag = "offline-" + out_dir.name
        regressed = brief_loop.offline_gate(tag)
        results["full"] = {"status": "fail" if regressed else "pass", "regressed": regressed, "logs": "runs/loop/gate-%s-*.log" % tag}
        print("%s full (build.py --reuse-table + self-test): %s" % ("FAIL" if regressed else "PASS", ", ".join(regressed) or "all briefs"))
        bad += [L for L in regressed if L not in bad]
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    n = sum(1 for v in results.values() if v.get("status") == "pass")
    print("\n%d / %d tables pass; results in %s" % (n, sum(1 for v in results.values() if v.get("status") != "skipped"), out_dir.relative_to(ROOT)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
