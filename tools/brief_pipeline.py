"""Two workers, one platform: the platform worker runs test rounds of every brief back to back; the fix worker triages a
GROUP of briefs as soon as its round is in, fixes generically in a separate git worktree (branch `fixes`), proves the
suite and the cross-brief offline gate, merges into main, and enqueues the group's failures for the next round. One fix
agent at a time; the platform never waits for it. At the end every brief runs once more on the final deployment.

    .venv/bin/python tools/brief_pipeline.py A B C D E F G H I J [--group 3] [--rounds 3]

Public briefs A/B: real slots, the organisers' bank, public cases + extended scenarios (round 1: only the scenarios that
failed on v15). Synthetic briefs: test variant on our tunnelled bank, synthetic/<L>/cases.json; a brief whose table is
not frozen yet (runs/synthetic/build-<L>/read/table.json, produced by runs/night/preread.sh) is retried later.
Log: runs/night/pipeline.log. Accounts: yakupkeskin777 first, bedriyan as fallback, never brynq.
"""
import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brief_loop as BL  # noqa: E402  (deploy_*, cases_*, rows_of, PUBLIC, accounts)

ROOT = BL.ROOT
PY = BL.PY
LOG = ROOT / "runs" / "night" / "pipeline.log"
WT = ROOT / "runs" / "night" / "fixwt"
lock = threading.Lock()


def log(msg):
    line = "%s %s" % (dt.datetime.utcnow().strftime("%H:%M:%SZ"), msg)
    print(line, flush=True)
    with lock, LOG.open("a") as fh:
        fh.write(line + "\n")


def table_ok(L):
    return L in BL.PUBLIC or (ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json").exists()


def ensure_worktree():
    if not (WT / ".git").exists():
        subprocess.run(["git", "worktree", "add", "-q", "-B", "fixes", str(WT), "HEAD"], cwd=ROOT, check=True)
    for name in (".venv", ".env"):
        if not (WT / name).exists():
            os.symlink(ROOT / name, WT / name)
    subprocess.run(["git", "checkout", "-q", "fixes"], cwd=WT)
    subprocess.run(["git", "reset", "-q", "--hard", "main"], cwd=WT)


def platform_worker(jobs, results, state):
    """jobs: (L, rnd, only_ids) in order; results: (L, rnd, paths)."""
    while True:
        job = jobs.get()
        if job is None:
            break
        L, rnd, only = job
        if not table_ok(L):
            if state["reads_done"]:
                log("%s: no table even after the reads, dropped" % L)
                results.put((L, rnd, []))
                continue
            jobs.put(job)
            time.sleep(60)
            continue
        with state["deploy_lock"]:
            ok = BL.deploy_public(L) if L in BL.PUBLIC else BL.deploy_synthetic(L, ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json")
        if not ok:
            results.put((L, rnd, []))
            continue
        paths = BL.cases_public(L, rnd, only) if L in BL.PUBLIC else BL.cases_synthetic(L, rnd, only)
        rows = BL.rows_of(paths)
        failed = [r["id"] for r in rows if not r["pass"]]
        log("%s round %d: %d / %d passed; failed: %s" % (L, rnd, len(rows) - len(failed), len(rows), ",".join(failed) or "-"))
        results.put((L, rnd, paths))


def fix_group(group, rnd, paths_by_L):
    """Triage + fix in the worktree; True when merged into main."""
    tag = "".join(group)
    ensure_worktree()
    manifest = ROOT / "runs" / "loop" / ("group-%s-round%d" % (tag, rnd)) / "RESULTS.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with manifest.open("w") as fh:
        fh.write("# Briefs %s, round %d\n\nWork in the git worktree %s (branch fixes); the main checkout is deployed and must not be edited.\n\n" % (", ".join(group), rnd, WT))
        for L, paths in paths_by_L.items():
            rows = BL.rows_of(paths)
            kind = ("public (kit/build-the-builder/briefs/brief-%s.md, kit/build-the-builder/tools/openapi.json; cases: public-test-set.json + scenarios/extended-test-set.json)" % L.lower()
                    if L in BL.PUBLIC else "synthetic (synthetic/%s/: brief files, api.json, cases.json, README.md; table runs/synthetic/build-%s/read/table.json; bank = our mock bank through the tunnel)" % (L, L))
            fh.write("## Brief %s: %s\nResult files: %s\nFailed cases:\n" % (L, kind, ", ".join(str(p) for p in paths)))
            for r in rows:
                if not r["pass"]:
                    total += 1
                    fh.write("- %s (call %s): %s\n" % (r["id"], r.get("call_id"), " | ".join(r["failed"])[:600]))
            if L in BL.PUBLIC and rnd == 1:
                earlier = BL.rows_of(sorted(glob.glob(str(ROOT / "runs" / "extended" / ("%s-*.json" % L)))))
                fh.write("\nEarlier run on version 15 (before the night's fixes), failures for comparison:\n")
                for r in earlier:
                    if not r["pass"]:
                        fh.write("- %s (call %s): %s\n" % (r["id"], r.get("call_id"), " | ".join(r["failed"])[:300]))
            fh.write("\n")
    if total == 0:
        return True
    prompt = (ROOT / "runs" / "night" / "agent-loop-triage.md").read_text()
    prompt = prompt.replace("__L__", ", ".join(group)).replace("__KIND__", "see the results file").replace("__RESULTS__", str(manifest)).replace("__N__", str(rnd))
    prompt = prompt.replace(str(ROOT), str(WT)) + ("\n\nIMPORTANT: your working copy is the git worktree %s on branch `fixes` (cwd). Edit and run tests THERE only (`%s/.venv/bin/python -m pytest -q tests/`). Result files, transcripts and tables under %s/runs/ are read-only inputs. Commit your changes in the worktree when done (git add builder tests bank; git commit)." % (WT, WT, ROOT))
    log("group %s round %d: fix agent starts on %d failures" % (tag, rnd, total))
    # Yakup's order: yakupkeskin777 (Claude), then codex gpt-6-astra, bedriyan (Claude) last; never brynq
    runners = [("claude yakupkeskin777", ["claude", "-p", prompt, "--model", "claude-fable-5-1", "--dangerously-skip-permissions", "--output-format", "text"], {"CLAUDE_CONFIG_DIR": BL.YAKUP}),
               ("codex gpt-6-astra", ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-m", "gpt-6-astra", "-c", "model_reasoning_effort=high", prompt], {}),
               ("claude bedriyan", ["claude", "-p", prompt, "--model", "claude-fable-5-1", "--dangerously-skip-permissions", "--output-format", "text"], {"CLAUDE_CONFIG_DIR": BL.BEDRIYAN})]
    for name, cmd, extra in runners:
        lp = ROOT / "runs" / "night" / ("agent-fix-%s-round%d.log" % (tag, rnd))
        with open(lp, "a") as fh:
            fh.write("\n===== %s =====\n" % name)
            try:
                rc = subprocess.run(cmd, cwd=WT, env=BL.env(extra), stdout=fh, stderr=subprocess.STDOUT, timeout=5400).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        tail = lp.read_text()[-2000:].lower()
        changed = subprocess.run(["git", "status", "--porcelain", "builder", "tests", "bank"], cwd=WT, capture_output=True, text=True).stdout.strip()
        if rc == 0 and "usage limit" not in tail and "rate limit" not in tail and (changed or "no fix" in tail):
            log("group %s round %d: fix agent (%s) finished" % (tag, rnd, name))
            break
        log("group %s round %d: fix agent (%s) gave nothing usable (rc %s, changes: %s); next runner" % (tag, rnd, name, rc, "yes" if changed else "no"))
    subprocess.run(["git", "add", "-A", "builder", "tests", "bank"], cwd=WT)
    subprocess.run(["git", "commit", "-q", "-m", "Generic fixes from briefs %s round %d (fix agent; runs/night/triage-%s-round%d.md)\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" % (", ".join(group), rnd, tag, rnd)], cwd=WT)
    res = subprocess.run([str(WT / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "tests/", "-k", "not simulator_rules"], cwd=WT, capture_output=True, text=True).stdout.strip().splitlines()
    last = res[-1] if res else "?"
    log("group %s round %d: fix agent done; suite in worktree: %s" % (tag, rnd, last))
    if "failed" in last:
        log("group %s round %d: suite red, fixes stay on branch `fixes`, not merged" % (tag, rnd))
        return False
    # cross-brief offline gate in the worktree
    bad = []
    for L, (brief, api, table) in BL.known_tables().items():
        lp = ROOT / "runs" / "loop" / ("gate-%s-round%d-%s.log" % (tag, rnd, L))
        with open(lp, "w") as fh:
            subprocess.run([str(WT / ".venv" / "bin" / "python"), "builder/build.py", str(ROOT / brief) if not brief.startswith("/") else brief, str(ROOT / api) if not api.startswith("/") else api,
                            "--reuse-table", str(ROOT / table) if not str(table).startswith("/") else str(table), "--no-deploy", "--out-dir", str(ROOT / "runs" / "loop" / ("gate-%s-round%d-%s" % (tag, rnd, L)))],
                           cwd=WT, env=BL.env(), stdout=fh, stderr=subprocess.STDOUT, timeout=600)
        txt = lp.read_text()
        if "end emit: ok" not in txt or "end selftest: ok" not in txt or "] test     [tier 0] FAIL" in txt:
            bad.append(L)
    if bad:
        log("group %s round %d: REGRESSION in %s after the fixes; not merged (branch fixes keeps them)" % (tag, rnd, ",".join(bad)))
        with manifest.open("a") as fh:
            fh.write("\nREGRESSION after round %d fixes: %s\n" % (rnd, ",".join(bad)))
        return False
    r = subprocess.run(["git", "merge", "-q", "--ff-only", "fixes"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        log("group %s round %d: merge into main failed: %s" % (tag, rnd, r.stderr.strip()[:200]))
        return False
    log("group %s round %d: fixes merged into main (%s)" % (tag, rnd, subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("letters", nargs="+")
    ap.add_argument("--group", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    letters = a.letters
    groups = [letters[i:i + a.group] for i in range(0, len(letters), a.group)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-2] += groups.pop()
    jobs, results = queue.Queue(), queue.Queue()
    state = {"reads_done": False, "deploy_lock": threading.Lock()}
    for L in letters:
        jobs.put((L, 1, None))
    worker = threading.Thread(target=platform_worker, args=(jobs, results, state), daemon=True)
    worker.start()

    def reads_watch():
        while subprocess.run(["pgrep", "-f", "runs/night/preread.sh"], capture_output=True).returncode == 0:
            time.sleep(60)
        state["reads_done"] = True
    threading.Thread(target=reads_watch, daemon=True).start()

    pending = {}            # (L, rnd) -> paths
    group_round = {tuple(g): 1 for g in groups}
    group_done = {tuple(g): False for g in groups}
    expected = {tuple(g): set(g) for g in groups}
    while not all(group_done.values()):
        L, rnd, paths = results.get()
        pending[(L, rnd)] = paths
        for g in groups:
            gt = tuple(g)
            r = group_round[gt]
            if group_done[gt] or not all((x, r) in pending for x in expected[gt]):
                continue
            paths_by_L = {x: pending[(x, r)] for x in expected[gt] if pending[(x, r)]}
            failed_by_L = {x: [row["id"] for row in BL.rows_of(p) if not row["pass"]] for x, p in paths_by_L.items()}
            if not any(failed_by_L.values()):
                log("group %s: CLEAN after round %d" % ("".join(g), r))
                group_done[gt] = True
                continue
            if r >= a.rounds:
                log("group %s: still failing after %d rounds: %s" % ("".join(g), r, json.dumps(failed_by_L)))
                group_done[gt] = True
                continue
            merged = fix_group(g, r, paths_by_L)
            if not merged:
                log("group %s: no merge after round %d; the group stops here (fixes on branch `fixes` for a human)" % ("".join(g), r))
                group_done[gt] = True
                continue
            group_round[gt] = r + 1
            expected[gt] = {x for x in g if failed_by_L.get(x)}
            for x in g:
                if failed_by_L.get(x):
                    jobs.put((x, r + 1, failed_by_L[x]))
    log("== all groups done; final run over every brief")
    final = {}
    for L in letters:
        if not table_ok(L):
            continue
        with state["deploy_lock"]:
            ok = BL.deploy_public(L) if L in BL.PUBLIC else BL.deploy_synthetic(L, ROOT / "runs" / "synthetic" / ("build-%s" % L) / "read" / "table.json")
        paths = BL.cases_public(L, 99, None) if L in BL.PUBLIC else BL.cases_synthetic(L, 99, None)
        rows = BL.rows_of(paths)
        final[L] = (sum(r["pass"] for r in rows), len(rows), [r["id"] for r in rows if not r["pass"]])
        log("%s final: %d / %d; failed: %s" % (L, final[L][0], final[L][1], ",".join(final[L][2]) or "-"))
    (ROOT / "runs" / "loop" / "FINAL.json").write_text(json.dumps(final, indent=1))
    jobs.put(None)
    log("== pipeline done")


if __name__ == "__main__":
    main()
