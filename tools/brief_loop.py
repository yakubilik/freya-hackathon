"""One brief at a time, until it is clean: deploy, run every test case of the brief on the platform, triage and fix
generically (an agent on this session's account), redeploy, rerun the failures; then the next brief.

    .venv/bin/python tools/brief_loop.py A B C D ... [--rounds 4]

A and B are the public briefs: frozen tables, the real slots, the organisers' practice bank, cases = the public set plus
our extended scenarios of that brief (scenarios/extended-test-set.json). Letters C.. are synthetic briefs: frozen table
(or a brynq read ONLY when runs/night/brynq.ok exists), the test variant on our tunnelled bank, synthetic/<L>/cases.json.
Platform runs retry; tools/sim_watchdog.py (separate) cancels hung simulations. Log: runs/night/loop.log.
"""
import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
LOG = ROOT / "runs" / "night" / "loop.log"
# Claude accounts for model work, in Yakup's order: yakupkeskin777 first, then bedriyan; never yakup@brynq.com
# (claude-ea4eb4: pay-as-you-go overage, see memory brynq-limit-guard)
YAKUP = str(pathlib.Path.home() / ".divan" / "accounts" / "claude-759b47")
BEDRIYAN = str(pathlib.Path.home() / ".remote-ai-chat" / "accounts" / "claude-37a8a4")
PUBLIC = {"A": {"slot": "20261010-192020-brief-a-final", "agent": "320bf1fa-ac9c-4776-86ca-65c267b917d9",
                "brief": "kit/build-the-builder/briefs/brief-a.md", "table": "runs/readers-smoke-a/adjudicated/table.json"},
          "B": {"slot": "brief-b-final", "agent": "5ff61b01-bfc9-4def-80df-fb75c6302f59",
                "brief": "kit/build-the-builder/briefs/brief-b.md", "table": "runs/readers-smoke-b/table.json"}}
API = "kit/build-the-builder/tools/openapi.json"


def log(msg):
    line = "%s %s" % (dt.datetime.utcnow().strftime("%H:%M:%SZ"), msg)
    print(line, flush=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def env(extra=None):
    e = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            e.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if (ROOT / "bank" / ".url").exists():
        e["OWN_BANK_URL"] = (ROOT / "bank" / ".url").read_text().strip()
    e.update(extra or {})
    return e


def run(cmd, log_path, extra_env=None, timeout=None):
    with open(log_path, "a") as fh:
        try:
            return subprocess.run(cmd, cwd=ROOT, env=env(extra_env), stdout=fh, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            fh.write("\n[timeout after %s s]\n" % timeout)
            return 124


def rows_of(paths):
    rows = []
    for p in paths:
        try:
            rows += json.load(open(p))["rows"]
        except Exception:  # noqa: BLE001
            pass
    return rows


# ---- public briefs

def deploy_public(L):
    c = PUBLIC[L]
    lp = ROOT / "runs" / "night" / ("deploy-%s.log" % L)
    run([PY, "builder/build.py", c["brief"], API, "--reuse-table", c["table"], "--slot", c["slot"], "--no-platform-test",
         "--out-dir", "runs/night/deploy-%s" % L], lp, timeout=900)
    ok = "published version" in lp.read_text()[-3000:]
    log("%s: deploy %s" % (L, "ok" if ok else "FAILED (runs/night/deploy-%s.log)" % L))
    return ok


def cases_public(L, rnd, only_ids=None):
    """Public cases plus extended scenarios of brief L; only_ids limits to a rerun of failures. Returns result paths."""
    c = PUBLIC[L]
    out_dir = ROOT / "runs" / "loop" / ("%s-round%d" % (L, rnd))
    out_dir.mkdir(parents=True, exist_ok=True)
    pub = [x["id"] for x in json.load(open(ROOT / "kit/build-the-builder/public-test-set.json")) if x["brief"] == L]
    ext = [x["id"] for x in json.load(open(ROOT / "scenarios/extended-test-set.json")) if x["brief"] == L]
    if only_ids is not None:
        pub = [i for i in pub if i in only_ids]
        ext = [i for i in ext if i in only_ids]
    paths = []
    if pub:
        p = out_dir / "public.json"
        for attempt in range(3):
            run([PY, "kit/build-the-builder/tools/run_cases.py", c["agent"], "--brief", L, "--only", ",".join(pub), "--out", str(p)], out_dir / "public.log", timeout=2400)
            if p.exists():
                break
            time.sleep(60)
        paths.append(p)
    for n in range(0, len(ext), 15):
        chunk = ext[n:n + 15]
        p = out_dir / ("ext-%02d.json" % (n // 15 + 1))
        for attempt in range(3):
            run([PY, "tools/run_extended.py", c["agent"], "--brief", L, "--only", ",".join(chunk), "--out-dir", str(out_dir), "--chunk", "99"], out_dir / "ext.log", timeout=2400)
            cand = sorted(glob.glob(str(out_dir / ("%s-*.json" % L))))
            if cand:
                os.replace(cand[-1], p)
                break
            time.sleep(60)
        paths.append(p)
    return [p for p in paths if p.exists()]


# ---- synthetic briefs

def source_of(L):
    d = ROOT / "synthetic" / L
    return str(d / "brief.md") if (d / "brief.md").exists() else str(d)


def table_synthetic(L):
    t = ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json"
    if t.exists():
        return t
    for acct in (YAKUP, BEDRIYAN):
        log("%s: reading the brief (R1 + adjudication on %s, R4 on codex)" % (L, acct.rsplit("/", 1)[-1]))
        run([PY, "builder/build.py", source_of(L), "synthetic/%s/api.json" % L, "--no-deploy", "--out-dir", "runs/synthetic/build-%s" % L],
            ROOT / "runs" / "synthetic" / ("build-%s.log" % L), {"CLAUDE_CONFIG_DIR": acct}, timeout=2400)
        if t.exists():
            return t
    log("%s: reading failed on both accounts, skipped" % L)
    return None


def deploy_synthetic(L, table):
    lp = ROOT / "runs" / "synthetic" / ("deploy-%s.log" % L)
    run([PY, "builder/build.py", source_of(L), "synthetic/%s/api.json" % L, "--reuse-table", str(table), "--slot", "synthetic-%s" % L,
         "--deploy-variant", "test", "--no-platform-test", "--out-dir", "runs/synthetic/deploy-%s" % L], lp, timeout=900)
    txt = lp.read_text()[-3000:]
    ok = "published version" in txt or "created on Freya" in txt
    log("%s: deploy %s" % (L, "ok" if ok else "FAILED (runs/synthetic/deploy-%s.log)" % L))
    return ok


def cases_synthetic(L, rnd, only_ids=None):
    out_dir = ROOT / "runs" / "loop" / ("%s-round%d" % (L, rnd))
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [PY, "tools/run_synthetic.py", L]
    if only_ids is not None:
        cmd += ["--only", ",".join(only_ids)]
    for attempt in range(3):
        run(cmd, out_dir / "cases.log", timeout=3600)
        cand = sorted(glob.glob(str(ROOT / "runs" / "synthetic" / ("%s-*.json" % L))), key=os.path.getmtime)
        if cand:
            p = out_dir / "cases.json"
            os.replace(cand[-1], p)
            return [p]
        time.sleep(60)
    return []


# ---- cross-brief regression gate (offline, seconds): every brief with a frozen table must still emit and pass its
# local self-tests after a fix round, so a fix for one brief cannot silently break another

def known_tables():
    out = {L: (PUBLIC[L]["brief"], API, PUBLIC[L]["table"]) for L in PUBLIC}
    for d in sorted(glob.glob(str(ROOT / "runs" / "synthetic" / "build-*" / "read" / "table.json"))):
        L = pathlib.Path(d).parents[1].name.split("-", 1)[1]
        out[L] = (source_of(L), "synthetic/%s/api.json" % L, str(pathlib.Path(d).relative_to(ROOT)))
    return out


def offline_gate(tag):
    bad = []
    for L, (brief, api, table) in known_tables().items():
        lp = ROOT / "runs" / "loop" / ("gate-%s-%s.log" % (tag, L))
        lp.parent.mkdir(parents=True, exist_ok=True)
        if lp.exists():
            lp.unlink()
        run([PY, "builder/build.py", brief, api, "--reuse-table", table, "--no-deploy", "--out-dir", "runs/loop/gate-%s-%s" % (tag, L)], lp, timeout=600)
        txt = lp.read_text() if lp.exists() else ""
        if "end emit: ok" not in txt or "end selftest: ok" not in txt or "] test     [tier 0] FAIL" in txt:
            bad.append(L)
    log("gate %s: %s" % (tag, "all briefs still emit and self-test" if not bad else "REGRESSION in %s" % ",".join(bad)))
    return bad


# ---- triage

def triage(group, rnd, paths_by_L):
    tag = "".join(group)
    manifest = ROOT / "runs" / "loop" / ("group-%s-round%d" % (tag, rnd)) / "RESULTS.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with manifest.open("w") as fh:
        fh.write("# Briefs %s, round %d\n\n" % (", ".join(group), rnd))
        for L, paths in paths_by_L.items():
            rows = rows_of(paths)
            kind = "public (kit/build-the-builder/briefs/brief-%s.md, kit/build-the-builder/tools/openapi.json; cases: public-test-set.json + scenarios/extended-test-set.json)" % L.lower() if L in PUBLIC else "synthetic (synthetic/%s/: brief files, api.json, cases.json, README.md; table runs/synthetic/build-%s/read/table.json; bank = our mock bank through the tunnel)" % (L, L)
            fh.write("## Brief %s: %s\nResult files: %s\nFailed cases:\n" % (L, kind, ", ".join(str(p) for p in paths)))
            for r in rows:
                if not r["pass"]:
                    total += 1
                    fh.write("- %s (call %s): %s\n" % (r["id"], r.get("call_id"), " | ".join(r["failed"])[:600]))
            if L in PUBLIC:
                # Yakup: nothing tested so far may go to waste. The earlier run of every extended scenario on v15 (before the
                # night's fixes) with its call ids: compare, and read those transcripts too when a case still fails or
                # passes by luck now.
                earlier = rows_of(sorted(glob.glob(str(ROOT / "runs" / "extended" / ("%s-*.json" % L)))))
                fh.write("\nEarlier run on version 15 (2026-10-10 night, before the fixes), failures for comparison:\n")
                for r in earlier:
                    if not r["pass"]:
                        fh.write("- %s (call %s): %s\n" % (r["id"], r.get("call_id"), " | ".join(r["failed"])[:300]))
            fh.write("\n")
    prompt = (ROOT / "runs" / "night" / "agent-loop-triage.md").read_text()
    prompt = prompt.replace("__L__", ", ".join(group)).replace("__KIND__", "see the results file").replace("__RESULTS__", str(manifest)).replace("__N__", str(rnd))
    log("group %s round %d: triage agent starts on %d failures" % (tag, rnd, total))
    rc = 1
    for acct in (YAKUP, BEDRIYAN):
        lp = ROOT / "runs" / "night" / ("agent-triage-%s-round%d.log" % (tag, rnd))
        rc = run(["claude", "-p", prompt, "--model", "claude-fable-5-1", "--dangerously-skip-permissions", "--output-format", "text"],
                 lp, {"CLAUDE_CONFIG_DIR": acct}, timeout=5400)
        tail = lp.read_text()[-2000:].lower() if lp.exists() else ""
        if rc == 0 and "usage limit" not in tail and "rate limit" not in tail:
            break
        log("group %s round %d: triage on %s failed (rc %s), trying the next account" % (tag, rnd, acct.rsplit("/", 1)[-1], rc))
    res = subprocess.run([PY, "-m", "pytest", "-q", "tests/", "-k", "not simulator_rules"], cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
    last = res[-1] if res else "?"
    log("group %s round %d: triage done (rc %s); suite: %s" % (tag, rnd, rc, last))
    if "failed" in last:
        return False
    bad = offline_gate("%s-round%d" % (tag, rnd))
    if bad:
        with manifest.open("a") as fh:
            fh.write("\nREGRESSION after round %d fixes: briefs %s no longer emit or self-test offline (runs/loop/gate-*).\n" % (rnd, ",".join(bad)))
        return False
    return True


def read_missing_tables(group):
    """Synthetic briefs without a frozen table are read in parallel (one builder process each, yakupkeskin777 account)."""
    import threading
    missing = [L for L in group if L not in PUBLIC and not (ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json").exists()]
    if not missing:
        return
    log("reading %s in parallel" % ",".join(missing))
    ths = [threading.Thread(target=table_synthetic, args=(L,)) for L in missing]
    for t in ths:
        t.start()
    for t in ths:
        t.join()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("letters", nargs="+")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--group", type=int, default=3)
    a = ap.parse_args()
    letters = a.letters
    groups = [letters[i:i + a.group] for i in range(0, len(letters), a.group)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-2] += groups.pop()
    for group in groups:
        tag = "".join(group)
        log("== group %s" % tag)
        read_missing_tables(group)
        tables = {}
        for L in group:
            t = None if L in PUBLIC else (ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json")
            if L not in PUBLIC and not t.exists():
                log("%s: no table, dropped from the group" % L)
                continue
            tables[L] = t
        only = {L: None for L in tables}
        for rnd in range(1, a.rounds + 1):
            paths_by_L, failed_by_L = {}, {}
            for L in list(tables):
                ok = deploy_public(L) if L in PUBLIC else deploy_synthetic(L, tables[L])
                if not ok:
                    continue
                paths = cases_public(L, rnd, only[L]) if L in PUBLIC else cases_synthetic(L, rnd, only[L])
                rows = rows_of(paths)
                if not rows:
                    log("%s round %d: no results after retries" % (L, rnd))
                    continue
                failed = [r["id"] for r in rows if not r["pass"]]
                log("%s round %d: %d / %d passed; failed: %s" % (L, rnd, len(rows) - len(failed), len(rows), ",".join(failed) or "-"))
                paths_by_L[L] = paths
                failed_by_L[L] = failed
            if not any(failed_by_L.values()):
                log("group %s: CLEAN after %d round(s)" % (tag, rnd))
                break
            if rnd == a.rounds:
                log("group %s: still failing after %d rounds: %s" % (tag, rnd, json.dumps(failed_by_L)))
                break
            if not triage(group, rnd, {L: p for L, p in paths_by_L.items()}):
                log("group %s: triage left the suite red or a regression; no redeploy, moving on" % tag)
                break
            subprocess.run(["git", "add", "-A", "builder", "tests", "bank"], cwd=ROOT)
            subprocess.run(["git", "commit", "-q", "-m", "Generic fixes from briefs %s round %d (triage agent; runs/night/triage-%s-round%d.md)\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" % (", ".join(group), rnd, tag, rnd)], cwd=ROOT)
            only = {L: (failed_by_L.get(L) or None) for L in tables}
    # closing run (Yakup: "en sonunda da hepsini çalıştırırız"): every case of every brief once more, on what is deployed
    # at the end, so the final fixes are proven against everything, not only against the brief they came from
    log("== final run over every brief")
    final = {}
    for L in letters:
        if L not in PUBLIC and not (ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json").exists():
            continue
        paths = cases_public(L, 99, None) if L in PUBLIC else cases_synthetic(L, 99, None)
        rows = rows_of(paths)
        final[L] = (sum(r["pass"] for r in rows), len(rows), [r["id"] for r in rows if not r["pass"]])
        log("%s final: %d / %d; failed: %s" % (L, final[L][0], final[L][1], ",".join(final[L][2]) or "-"))
    (ROOT / "runs" / "loop" / "FINAL.json").write_text(json.dumps(final, indent=1))
    log("== loop done")


if __name__ == "__main__":
    main()
