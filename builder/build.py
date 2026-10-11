"""The builder: one brief and its tool API file in, one phone agent on Freya out.

    python3 builder/build.py <brief.md> <tools.json> [--out-dir runs/<run_id>] [--slot NAME] [--skip-tests]
                             [--reuse-table PATH] [--base BRIEF.md] [--no-deploy] [--no-platform-test]
    python3 builder/build.py <case_folder> <mock_url> 2>&1 | tee traces/final.log     (the final's form)

The final's form: the case folder holds BRIEF.md, README.md, the documents and a service contract; the second argument
is the base URL of our mock of the bank. The contract (a .json/.yaml/.yml OpenAPI document anywhere in the folder) is
copied with its server on the mock, so every tool of the final variant calls the mock and nothing else. Without a
machine-readable contract (a prose contract: services, paths and shapes in text and tables) there is nothing for the
reader and the emitter: the run goes straight to the floor (trigger T0) with the whole budget. BRIEF.md, README.md and then the other text documents
(file-name order, subfolders included) are joined into <case_folder>.joined.md; images and binaries are only listed.

Stages, under one 30-minute budget with reservations (Schedule below):
  1. read     builder.readers.read_brief -> frozen rule table (or --reuse-table). Failure -> T1 floor.
  2. emit     both variants (final on the tool API's server, test on OWN_BANK_URL or a placeholder for the diff
              check), static walk, variant diff limited to endpoint strings. Emitter failure twice -> T2 floor.
              An unsupported obligation on every customer's path -> T4 floor.
  3. selftest exec the engine snippet incl. the error path; the public cases through the local simulator and an
              in-process mock bank when the brief is a public one (by hash), else the table's own examples.
  4. deploy   dry run, save into the slot (state file builder/.freya-agents.json, updated in place on reruns of
              the same slot), read back and compare, export to submission/<brief_slug>.workflow.json.
  5. platform one public case on the official scorer when time remains and the brief is public.
  6. manifest runs/<run_id>/manifest.json, written even on failure.

Why a case folder can go straight to the floor (written 2026-10-11, after the final case opened). The kit and the
challenge page promised hidden briefs as one Markdown file each with its own OpenAPI tool file, the seven practice tool
names unchanged, debt collection, calls in English; the reader, the engine and the emitter were built to that
promise. The final arrived in another form (one case folder of documents, a prose service contract, other services,
another domain, another language), and this builder stopped with "no machine-readable contract" and made no agent.
The changes made after the case opened only adapt the input path: a folder without a machine-readable contract goes to
the floor (T0); the floor reads the case folder instead of the kit's practice files; it keeps the builder's two model
families (a second-family review of the saved workflow, then a Claude fix session, as the reader's R1/R4 did); it
tests its own agent with simulations, as the kit's example builder did. Reader, engine and emitter are unchanged, and
nothing from any case (no rule, value, name, path or sentence) is written into the builder.

The floor, run as a subprocess: for a case folder our own runner (builder/floor/runner.py with its skill, which reads
every document of the folder and builds the tools on the mock; its session log is runs/<run_id>/floor-session.jsonl),
else the kit's example builder (kit/build-the-builder/examples/agent_builder.py).
Trace: runs/<run_id>/trace.log (plain text, every line also on stdout, paths repo-relative) and trace.jsonl. Keys come from the environment or from .env in the
repository root (KEY=VALUE lines); they are never written to the trace.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
KIT = ROOT / "kit" / "build-the-builder"
STATE_FILE = ROOT / "builder" / ".freya-agents.json"
SUBMISSION = ROOT / "submission"
EXPORT_DIR = SUBMISSION                        # test-variant deploys export next to it, not into the deliverables
PUBLIC_BRIEFS = {"A": KIT / "briefs" / "brief-a.md", "B": KIT / "briefs" / "brief-b.md"}
# a public brief that builds on another one; the reader gets the base as an earlier document of the same source
PUBLIC_BASES = {"B": ["A"]}
TEST_PLACEHOLDER_BANK = "http://127.0.0.1:9"
# T4: obligation states every customer passes through on a normal call
EVERY_PATH_STATES = {"any", "pre_verification", "closing"}
EVERY_PATH_STAGES = {"party", "close"}

TOTAL_S = 1800
# measured 2026-10-10 on the public briefs: R1 took 511 s (A) and 626 s (B), adjudication 150 to 175 s; Brief B ended
# its reading 4 s before a 780 s cap. 1020 s leaves the deploy (180), the export reserve (180) and a platform test
# (at least 360) inside the 1800 s run.
READ_MAX_S = 1020
EMIT_DEPLOY_S = 180
EXPORT_RESERVE_S = 180
# measured 2026-10-10: "Code and data for code_exec total N bytes, over the 131072-byte limit a sandboxed process
# can receive"; N is the JSON-encoded code plus the variables. Keep room for a growing engine_state.
CODE_EXEC_LIMIT = 131072
CODE_EXEC_MAX = 122000
FLOOR_MIN_S = 600          # the kit floor is not started with less than this left
PLATFORM_TEST_MIN_S = 360  # one public case on the official scorer takes about 3 to 5 minutes


# --------------------------------------------------------------------------------------------------------------
# environment


def read_dotenv(path) -> dict:
    """KEY=VALUE lines; blank lines and # comments skipped; optional `export ` and matching quotes stripped."""
    out = {}
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        out[key] = val
    return out


def load_env(path=ROOT / ".env"):
    """Set the variables of `path` that the environment does not already have. Returns the key names set."""
    vals = read_dotenv(path)
    set_ = [k for k in vals if k not in os.environ]
    for k in set_:
        os.environ[k] = vals[k]
    return set_



def claude_ready():
    """None when the reader can call Claude (ANTHROPIC_API_KEY set, or the claude CLI the SDK bundles is logged in),
    else the reason. The reader runs through claude_agent_sdk, so a run without credentials would fail minutes in."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None
    cli = None
    try:
        import claude_agent_sdk  # noqa: F401
        cand = pathlib.Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / "claude"
        cli = str(cand) if cand.exists() else shutil.which("claude")
    except Exception:  # noqa: BLE001
        cli = shutil.which("claude")
    if not cli:
        return "claude_agent_sdk (or a claude CLI) is not installed"
    try:
        out = subprocess.run([cli, "auth", "status"], capture_output=True, text=True, timeout=30)
        info = json.loads(out.stdout[out.stdout.find("{"):]) if "{" in out.stdout else {}
    except Exception as e:  # noqa: BLE001
        return "claude auth status could not be read (%s)" % str(e)[:80]
    return None if info.get("loggedIn") else "the claude CLI is not logged in"


# --------------------------------------------------------------------------------------------------------------
# deadline scheduler


class Deadline:
    """Same interface as builder.readers.models.Deadline: remaining(), expired(), elapsed()."""

    def __init__(self, seconds, clock=time.monotonic):
        self.seconds = max(0.0, float(seconds))
        self.clock = clock
        self.t0 = clock()

    def remaining(self):
        return max(0.0, self.seconds - (self.clock() - self.t0))

    def expired(self):
        return self.remaining() <= 0

    def elapsed(self):
        return self.clock() - self.t0


class Schedule:
    """One hard budget from the start of the run. Each stage gets min(its cap, what is left after the
    reservations of the stages that must still run)."""

    RESERVE_AFTER = {"read": EMIT_DEPLOY_S + EXPORT_RESERVE_S, "emit": EMIT_DEPLOY_S, "selftest": EMIT_DEPLOY_S,
                     "deploy": EXPORT_RESERVE_S // 2, "floor": EXPORT_RESERVE_S, "platform": EXPORT_RESERVE_S}
    CAPS = {"read": READ_MAX_S, "emit": 60, "selftest": 300, "deploy": EMIT_DEPLOY_S}

    def __init__(self, total=TOTAL_S, clock=time.monotonic):
        self.total = float(total)
        self.clock = clock
        self.t0 = clock()

    def elapsed(self):
        return self.clock() - self.t0

    def remaining(self):
        return max(0.0, self.total - self.elapsed())

    def budget(self, stage):
        left = self.remaining() - self.RESERVE_AFTER.get(stage, 0)
        cap = self.CAPS.get(stage)
        return max(0.0, min(cap, left) if cap is not None else left)

    def deadline(self, stage):
        return Deadline(self.budget(stage), clock=self.clock)


# --------------------------------------------------------------------------------------------------------------
# trace


def _now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD", re.I)


def rel(p):
    """A path as the trace and the manifest show it: relative to the repository root, never absolute."""
    if p is None:
        return None
    try:
        return os.path.relpath(str(p), str(ROOT))
    except ValueError:
        return pathlib.Path(p).name


def scrub(text):
    """No absolute paths and no key values in anything the builder writes or prints."""
    s = str(text)
    for k, v in os.environ.items():
        if v and len(v) >= 8 and SECRET_NAME.search(k):
            s = s.replace(v, "***")
    s = s.replace(str(ROOT) + os.sep, "").replace(str(ROOT), ".")
    return s.replace(str(pathlib.Path.home()), "~")


class Trace:
    """trace.log (one human-readable line per event) and trace.jsonl (the same events as JSON)."""

    def __init__(self, out_dir, schedule=None, echo=True):
        self.dir = pathlib.Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = self.dir / "trace.log"
        self.jsonl = self.dir / "trace.jsonl"
        self.schedule = schedule
        self.echo = echo
        self.log.write_text("")
        self.jsonl.write_text("")
        self.model_calls = []
        self.tests = []
        self.stages = {}

    def _t(self):
        return round(self.schedule.elapsed(), 1) if self.schedule else None

    def write(self, kind, text, **data):
        rec = {"at": _now_iso(), "t": self._t(), "kind": kind, **data}
        line = scrub("%s [%7s s] %-8s %s" % (rec["at"], rec["t"], kind, text))
        with self.log.open("a") as fh:
            fh.write(line + "\n")
        with self.jsonl.open("a") as fh:
            fh.write(scrub(json.dumps(rec, default=str, ensure_ascii=False)) + "\n")
        if self.echo:
            print(line, flush=True)

    def echo_output(self, name, text):
        """A subprocess's output (kept in its own file in the run directory) also goes to stdout, which the organisers
        keep as the trace."""
        if self.echo and text.strip():
            print(scrub("\n".join("  %s | %s" % (name, ln) for ln in text.rstrip().splitlines())), flush=True)

    def info(self, text, **data):
        self.write("info", text, **data)

    def error(self, text, **data):
        self.write("error", text, **data)

    def model_call(self, model, purpose, tokens, seconds, **extra):
        self.model_calls.append({"model": model, "purpose": purpose, "tokens": tokens, "seconds": seconds})
        self.write("model", "model=%s purpose=%s tokens=%s seconds=%s" % (model, purpose, tokens, seconds),
                   model=model, purpose=purpose, tokens=tokens, seconds=seconds, **extra)

    def test(self, tier, name, result, detail=""):
        self.tests.append({"tier": tier, "name": name, "result": result, "detail": detail})
        self.write("test", "[tier %s] %-4s %s | %s" % (tier, result, name, str(detail)[:300]),
                   tier=tier, name=name, result=result, detail=detail)

    def stage_start(self, name, budget):
        self.stages[name] = {"start": self._t(), "budget_s": round(budget, 1)}
        self.write("stage", "start %s (budget %.0f s)" % (name, budget), stage=name, budget_s=round(budget, 1))

    def stage_end(self, name, status="ok"):
        st = self.stages.setdefault(name, {"start": self._t()})
        st["end"] = self._t()
        st["seconds"] = round((st["end"] or 0) - (st["start"] or 0), 1)
        st["status"] = status
        self.write("stage", "end %s: %s in %.1f s" % (name, status, st["seconds"]), stage=name, status=status,
                   seconds=st["seconds"])


# --------------------------------------------------------------------------------------------------------------
# helpers


def sha256_text(s):
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def sha256_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def canonical_hash(obj):
    return sha256_text(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


GENERIC_STEMS = ("brief", "readme", "index", "main", "doc", "document")


def slug(path):
    """File stem as a slug; a generic stem ("brief.md" inside a directory) takes the directory's name in front so two
    hidden briefs that are both called brief.md do not export to the same submission/brief.workflow.json."""
    p = pathlib.Path(path)
    s = re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-")
    if s in GENERIC_STEMS or not s:
        parent = re.sub(r"[^a-z0-9]+", "-", p.resolve().parent.name.lower()).strip("-")
        if parent and parent not in GENERIC_STEMS:
            s = parent + "-" + (s or "brief")
    return s or "brief"


def public_brief(brief_text):
    """'A' or 'B' when the brief is byte-identical to a public brief of the kit, else None."""
    h = sha256_text(brief_text)
    for letter, p in PUBLIC_BRIEFS.items():
        if p.exists() and sha256_file(p) == h:
            return letter
    return None


def source_commit():
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def diff_paths(a, b, path=""):
    """Every leaf path where a and b differ: [(path, a_value, b_value)]; a missing side is the string <absent>."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = "%s/%s" % (path, k)
            if k not in a:
                out.append((p, "<absent>", b[k]))
            elif k not in b:
                out.append((p, a[k], "<absent>"))
            else:
                out += diff_paths(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            p = "%s/%d" % (path, i)
            if i >= len(a):
                out.append((p, "<absent>", b[i]))
            elif i >= len(b):
                out.append((p, a[i], "<absent>"))
            else:
                out += diff_paths(a[i], b[i], p)
    elif a != b:
        out.append((path, a, b))
    return out


def variant_diff(final_wf, test_wf, final_base, test_base):
    """(endpoint_diffs, other_diffs): the two variants may differ only in strings where the final base URL is
    replaced by the test base URL."""
    endpoint, other = [], []
    for p, a, b in diff_paths(final_wf, test_wf):
        if isinstance(a, str) and isinstance(b, str) and final_base in a and a.replace(final_base, test_base) == b:
            endpoint.append(p)
        else:
            other.append((p, a, b))
    return endpoint, other


def urls_in(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            urls_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            urls_in(v, out)
    elif isinstance(obj, str):
        out += re.findall(r"https?://[^\s\"'{}]+", obj)
    return out


def endpoint_check(stored_wf, official_base):
    """'clean' when every URL in the workflow starts with the official base URL, else the offending URLs."""
    bad = sorted({u for u in urls_in(stored_wf) if not u.startswith(official_base)})
    return "clean" if not bad else "foreign urls: " + ", ".join(bad[:10])


def code_sizes(wf):
    """{node: JSON-encoded size of the largest code its code_exec actions send}."""
    out = {}
    for name, n in (wf.get("nodes") or {}).items():
        for fn in n.get("pre_actions") or []:
            code = (((fn.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("code", {}).get("default")
            if isinstance(code, str):
                out[name] = max(out.get(name, 0), len(json.dumps(code)))
        if isinstance(n.get("code"), str):
            out[name] = max(out.get(name, 0), len(json.dumps(n["code"])))
    return out


def t4_check(table):
    """Unsupported obligations on every customer's path: [(obligation id, why)]. An obligation is on every path
    when its state is one every call passes through, or it belongs to a non-per-item plan stage of a type every
    call runs."""
    stage_of = {}
    for st in table.get("plan") or []:
        if isinstance(st, dict):
            for oid in st.get("obligations") or []:
                stage_of[oid] = st
    hits = []
    for o in table.get("obligations") or []:
        if o.get("capability") != "unsupported" or o.get("status", "effective") != "effective":
            continue
        state = (o.get("when") or {}).get("state")
        st = stage_of.get(o.get("id"))
        if state in EVERY_PATH_STATES:
            hits.append((o.get("id"), "state %s" % state))
        elif st and st.get("type") in EVERY_PATH_STAGES and not st.get("per_item"):
            hits.append((o.get("id"), "stage %s" % st.get("type")))
    return hits


def import_freya():
    if str(KIT) not in sys.path:
        sys.path.insert(0, str(KIT))
    import freya  # noqa: PLC0415 - reads the keys from the environment at import
    return freya


TRANSIENT = re.compile(r"-> (502|503|504|429):|timed out|Connection reset|Remote end closed|temporarily|SSL|URLError|EOF occurred", re.I)


def with_retry(fn, deadline, trace, what, *args, **kwargs):
    """Call fn; retry on 502/503/504/429 and transport errors with backoff while the deadline allows."""
    delay, attempt = 2.0, 0
    while True:
        attempt += 1
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            msg = "%s: %s" % (type(e).__name__, str(e)[:400])
            if not (TRANSIENT.search(msg) or isinstance(e, (TimeoutError, ConnectionError))) or deadline.remaining() < delay + 5:
                raise
            trace.info("%s failed (attempt %d, %s); retrying in %.0f s" % (what, attempt, msg[:160], delay))
            time.sleep(delay)
            delay = min(delay * 2, 30)


# --------------------------------------------------------------------------------------------------------------
# the run


class FloorTrigger(Exception):
    def __init__(self, trigger, reason):
        super().__init__("%s: %s" % (trigger, reason))
        self.trigger, self.reason = trigger, reason


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Build a Freya phone agent from a brief.")
    ap.add_argument("brief", help="a brief file, a directory of brief documents, or the final's case folder")
    ap.add_argument("tools", help="the tool API file, or an http(s) URL: the base of our mock bank (the final's form)")
    ap.add_argument("--out-dir")
    ap.add_argument("--slot")
    ap.add_argument("--skip-tests", action="store_true", help="no local and no platform self-tests")
    ap.add_argument("--reuse-table", help="a frozen table.json from an earlier reading; skips the reading")
    ap.add_argument("--base", action="append", default=[], help="a brief this one builds on (repeatable)")
    ap.add_argument("--no-deploy", action="store_true", help="stop after the local self-tests (offline run)")
    ap.add_argument("--no-platform-test", action="store_true")
    ap.add_argument("--deploy-variant", choices=("final", "test"), default="final",
                    help="deploy the test variant (tools on OWN_BANK_URL, our mock bank) instead of the final one; for our own tests only")
    ap.add_argument("--budget", type=float, default=TOTAL_S, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


BRIEF_FILE_ORDER = ("mail", "letter", "email", "policy", "procedure", "memo", "circular", "notice", "codes", "code")


def join_brief_dir(d):
    """A brief handed over as a directory of documents (the organisers' raw-material form: a mail, a policy extract, a
    memo that changes it, a code list) is joined into one markdown file, documents separated by a rule, in reading
    order: mail, policy, memo, codes, then any other file by name. The reader segments on headings, rules and mail or
    memo markers and keeps every document's own date. Written next to the directory as <name>.joined.md."""
    files = sorted(p for p in d.iterdir() if p.suffix.lower() in (".md", ".txt") and not p.name.lower().startswith(("readme", "review")))

    def rank(p):
        low = p.stem.lower()
        for i, w in enumerate(BRIEF_FILE_ORDER):
            if w in low:
                return (i, low)
        return (len(BRIEF_FILE_ORDER), low)

    files.sort(key=rank)
    if not files:
        raise SystemExit("brief directory %s has no .md or .txt files" % d)
    text = "\n\n---\n\n".join(p.read_text(encoding="utf-8").strip() + "\n" for p in files)
    out = d.parent / (d.name + ".joined.md")
    out.write_text(text, encoding="utf-8")
    return out


# ---- the final's case folder: BRIEF.md, README.md, documents, a service contract; the second argument a mock URL

NOT_TEXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".ico", ".svg", ".pdf", ".zip",
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".key", ".pages", ".numbers"}
DATA_SUFFIXES = {".json", ".yaml", ".yml", ".csv", ".tsv", ".sqlite", ".db"}
CONTRACT_SUFFIXES = (".json", ".yaml", ".yml")


def is_url(s):
    return bool(re.match(r"^https?://[^\s/]+", str(s or "").strip(), re.I))


def is_case_dir(d):
    return any(p.stem.lower() == "brief" for p in case_files(d))


def case_files(d):
    """Every file under the folder, recursively, in relative-path order; hidden files and zip debris left out."""
    d = pathlib.Path(d)
    out = []
    for p in sorted(d.rglob("*"), key=lambda q: str(q.relative_to(d)).lower()):
        parts = p.relative_to(d).parts
        if p.is_file() and not any(x.startswith(".") or x == "__MACOSX" for x in parts):
            out.append(p)
    return out


def load_structured(p):
    """A .json, .yaml or .yml file as data. YAML through PyYAML, else Ruby's YAML (macOS ships it); ValueError when
    neither is there or the file does not parse."""
    p = pathlib.Path(p)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError("not valid JSON: %s" % e)
    try:
        import yaml  # noqa: PLC0415
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError("not valid YAML: %s" % str(e)[:200])
    except ImportError:
        pass
    try:
        r = subprocess.run(["ruby", "-ryaml", "-rjson", "-rdate", "-e",
                            "puts JSON.generate(YAML.safe_load(STDIN.read, permitted_classes: [Date, Time, Symbol], aliases: true))"],
                           input=text, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError("YAML file but no YAML parser: PyYAML is not installed and ruby is not usable (%s)" % e)
    if r.returncode != 0:
        raise ValueError("YAML not parsed (PyYAML not installed; ruby says: %s)" % r.stderr.strip()[-200:])
    return json.loads(r.stdout)


def looks_like_contract(doc):
    return isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc or isinstance(doc.get("paths"), dict))


def find_contract(files):
    """(path, doc, notes): the machine-readable service contract among the files, an OpenAPI/Swagger document (JSON or
    YAML, `openapi`, `swagger` or `paths` at the top). With several, the one with most operations, then the first by
    name. (None, None, notes) when there is none; notes say why candidate files were passed over."""
    from builder.readers.api_file import parse_api

    found, notes = [], []
    for p in files:
        if p.suffix.lower() not in CONTRACT_SUFFIXES:
            continue
        try:
            doc = load_structured(p)
        except (ValueError, UnicodeDecodeError) as e:
            notes.append("%s: %s" % (p.name, e))
            continue
        if not looks_like_contract(doc):
            continue
        try:
            n = len(parse_api(doc)["tools"])
        except Exception as e:  # noqa: BLE001
            notes.append("%s: looks like OpenAPI but does not parse: %s" % (p.name, str(e)[:200]))
            continue
        if n:
            found.append((-n, len(found), p, doc))
        else:
            notes.append("%s: OpenAPI without operations" % p.name)
    if not found:
        return None, None, notes
    _, _, p, doc = min(found, key=lambda x: (x[0], x[1]))
    return p, doc, notes


def join_case_dir(d, exclude=(), out=None):
    """The case folder's text documents joined into one markdown file the reader takes like any brief: BRIEF.md first,
    README.md second, then every other text document (.md, .txt, ...) by relative path, subfolders
    included; the service contract (`exclude`), data files (.json, .csv, .yaml: customers, tables) and images and binaries are skipped. Returns (joined path,
    included relative paths, skipped relative paths)."""
    d = pathlib.Path(d)
    exclude = {pathlib.Path(x).resolve() for x in exclude if x}

    def rank(p):
        parts = p.relative_to(d).parts
        cls = {"brief": 0, "readme": 1}.get(p.stem.lower(), 2) if p.suffix.lower() in (".md", ".txt", "") else 2
        return (cls, len(parts) if cls < 2 else 0, "/".join(parts).lower())

    texts, used, skipped = [], [], []
    for p in sorted(case_files(d), key=rank):
        r = str(p.relative_to(d))
        if p.resolve() in exclude:
            continue
        if p.suffix.lower() in NOT_TEXT:
            skipped.append(r)
            continue
        # a data file (the test customers, a second contract, a table) is for the mock and the tests, not brief text:
        # the reader's budget is for the documents (2026-10-11, the final's zip carries test customers next to the brief)
        if p.suffix.lower() in DATA_SUFFIXES:
            skipped.append(r)
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped.append(r)
            continue
        if "\x00" in t:
            skipped.append(r)
            continue
        if t.strip():
            texts.append(t.strip() + "\n")
            used.append(r)
    if not texts:
        raise ValueError("case folder %s has no text documents" % rel(d))
    out = pathlib.Path(out) if out else d.parent / (d.name + ".joined.md")
    out.write_text("\n\n---\n\n".join(texts), encoding="utf-8")
    return out, used, skipped


def prepare_case(trace, manifest, case_dir, tools_path, mock_url, joined):
    """The brief and the tool API file for the reader, from a case folder. With a mock URL the folder's service
    contract is located and copied with its server on the mock (the official run: every tool calls the mock, nothing
    else), so the reader, the emitter's final variant, the export and the floor all see the mock as the bank."""
    from builder.emitter.emit import base_url_for
    from builder.readers.api_file import parse_api

    files = case_files(case_dir)
    trace.info("case folder %s: %d file(s): %s" % (rel(case_dir), len(files), ", ".join(str(p.relative_to(case_dir)) for p in files)))
    contract = tools_path
    if mock_url:
        contract, doc, notes = find_contract(files)
        for n in notes:
            trace.info("contract candidate passed over: %s" % n)
        if contract is None:
            # a prose contract: the reader and the emitter need an OpenAPI document, the floor reads the folder itself
            manifest["mock_url"] = mock_url
            brief_path, used, skipped = join_case_dir(case_dir, out=joined)
            manifest["brief_documents"], manifest["skipped_documents"] = used, skipped
            manifest["brief_path"], manifest["tools_path"] = rel(brief_path), None
            manifest["brief_hash"] = sha256_file(brief_path)
            trace.info("documents in the case folder: %s%s" % (
                ", ".join(used), "; not joined (the floor reads them itself): " + ", ".join(skipped) if skipped else ""))
            raise FloorTrigger("T0", "no machine-readable contract (no .json/.yaml/.yml OpenAPI document with "
                                     "openapi/swagger/paths at the top%s); the reading is skipped, the floor reads the "
                                     "case folder and its contract itself" % ("; " + " | ".join(notes) if notes else ""))
        api0 = parse_api(doc)
        mock_base = base_url_for(api0, "final", mock_url)
        trace.info("service contract: %s, %d operation(s) (%s); its server %s; tools go to the mock %s" % (
            contract.relative_to(case_dir), len(api0["tools"]), ", ".join(sorted(api0["tools"])), api0["server"] or "none",
            mock_base))
        manifest["contract_path"] = rel(contract)
        manifest["mock_url"] = mock_url
        doc = dict(doc)
        doc["servers"] = [{"url": mock_base}]
        tools_path = joined.parent / (case_dir.name + ".contract.json")
        tools_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    brief_path, used, skipped = join_case_dir(case_dir, exclude=[contract], out=joined)
    trace.info("brief material, in reading order: %s" % ", ".join(used))
    if skipped:
        trace.info("not read (image, binary or data file): %s" % ", ".join(skipped))
    manifest["brief_documents"], manifest["skipped_documents"] = used, skipped
    manifest["brief_path"], manifest["tools_path"] = rel(brief_path), rel(tools_path)
    return brief_path, tools_path


def run(argv=None, schedule=None):
    a = parse_args(argv)
    schedule = schedule or Schedule(a.budget)
    started = _now_iso()
    brief_path = pathlib.Path(a.brief).resolve()
    mock_url = a.tools.strip() if is_url(a.tools) else None
    tools_path = None if mock_url else pathlib.Path(a.tools).resolve()
    global EXPORT_DIR
    EXPORT_DIR = ROOT / "submission-test" if getattr(a, "deploy_variant", "final") == "test" else SUBMISSION
    case_dir = None
    if mock_url and brief_path.is_file():
        case_dir = brief_path.parent          # BRIEF.md handed over instead of its folder: the case is the folder
    elif brief_path.is_dir() and (mock_url or is_case_dir(brief_path)):
        case_dir = brief_path
    elif brief_path.is_dir():
        brief_path = join_brief_dir(brief_path)
    if case_dir is not None:
        brief_path = case_dir.parent / (case_dir.name + ".joined.md")
    bslug = slug(brief_path)
    run_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + bslug
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else ROOT / "runs" / run_id
    if a.out_dir:
        run_id = out_dir.name
    trace = Trace(out_dir, schedule)
    env_set = load_env()
    manifest = {
        "run_id": run_id, "brief_path": rel(brief_path), "tools_path": rel(tools_path),
        "case_dir": rel(case_dir), "mock_url": mock_url, "contract_path": None,
        "brief_hash": None, "tools_hash": None, "table_hash": "none", "plan_hash": "none",
        "source_commit": source_commit(), "variant": "final", "slot": None, "workflow_id": None, "agent_id": None,
        "version": None, "export_path": None, "export_hash": None, "bank_url": None, "endpoint_check": None,
        "variant_diff": None, "model_config": None, "tiers_run": [], "fallback": None, "trigger": None,
        "results": {"PASS": 0, "FAIL": 0, "INVALID": 0, "UNKNOWN": 0}, "status": "running", "errors": [],
        "stages": trace.stages, "model_calls": trace.model_calls, "tests": trace.tests,
        "started": started, "finished": None,
    }
    # a real run needs the Freya keys from the start: a run without them must not go on and look like a build
    if not a.no_deploy:
        missing = [k for k in ("FREYA_API_KEY", "FREYA_WORKSPACE_ID") if not os.environ.get(k)]
        if missing:
            trace.error("missing environment: %s. Put them in .env (see README, Setup); only --no-deploy runs without them." % ", ".join(missing))
            trace.info("builder end: status not started (missing keys)")
            manifest["status"] = "not started: missing " + ", ".join(missing)
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
            return manifest
    if not a.reuse_table:
        why = claude_ready()
        if why:
            trace.error("Claude credentials needed for the reader: %s. Run `claude login` (a Claude subscription) or put ANTHROPIC_API_KEY in .env. "
                        "OPENAI_API_KEY or a logged-in codex CLI is optional (the blind audit degrades without it)." % why)
            trace.info("builder end: status not started (no Claude credentials)")
            manifest["status"] = "not started: no Claude credentials"
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
            return manifest
    trace.info("builder start: run %s, %s %s, %s %s, commit %s" % (
        run_id, "case folder" if case_dir else "brief", rel(case_dir or brief_path),
        "mock bank" if mock_url else "tools", mock_url or rel(tools_path), manifest["source_commit"]))
    trace.info("environment: %d keys loaded from .env (names only: %s)" % (len(env_set), ", ".join(sorted(env_set))))
    try:
        if case_dir is not None:
            try:
                brief_path, tools_path = prepare_case(trace, manifest, case_dir, tools_path, mock_url, brief_path)
            except FloorTrigger as ft:
                run_floor(a, schedule, trace, manifest, ft, brief_path, None, bslug, case_dir, mock_url)
                return manifest
        _pipeline(a, schedule, trace, manifest, brief_path, tools_path, bslug, run_id, out_dir, case_dir, mock_url)
    except Exception as e:  # noqa: BLE001 - the manifest is written whatever happens
        manifest["status"] = "failed"
        manifest["errors"].append("%s: %s" % (type(e).__name__, e))
        trace.error("run failed: %s: %s" % (type(e).__name__, e), tb=traceback.format_exc()[-2000:])
    finally:
        for t in trace.tests:
            manifest["results"][t["result"] if t["result"] in manifest["results"] else "UNKNOWN"] += 1
        manifest["finished"] = _now_iso()
        manifest["elapsed_s"] = round(schedule.elapsed(), 1)
        (out_dir / "manifest.json").write_text(scrub(json.dumps(manifest, indent=1, default=str)))
        trace.info("builder end: status %s, %.1f s, results %s, manifest %s" % (
            manifest["status"], schedule.elapsed(), manifest["results"], rel(out_dir / "manifest.json")))
        trace.info("created on Freya: workflow %s, agent %s, slot %s, version %s, export %s" % (
            manifest["workflow_id"], manifest["agent_id"], manifest["slot"], manifest["version"], manifest["export_path"]))
    return manifest


def _pipeline(a, schedule, trace, manifest, brief_path, tools_path, bslug, run_id, out_dir, case_dir=None, mock_url=None):
    from builder.readers.api_file import parse_api

    brief_text = brief_path.read_text()
    tools_text = tools_path.read_text()
    manifest["brief_hash"] = sha256_text(brief_text)
    manifest["tools_hash"] = sha256_text(tools_text)
    raw_api = json.loads(tools_text)
    api = parse_api(raw_api)
    public = public_brief(brief_text)
    trace.info("brief %s (sha256 %s), %s; tools: %d (%s)" % (
        brief_path.name, manifest["brief_hash"][:12], "public brief %s" % public if public else "not a public brief",
        len(api["tools"]), ", ".join(sorted(api["tools"]))))

    table = None
    try:
        table = stage_read(a, schedule, trace, manifest, brief_path, tools_path, public, out_dir)
        wf, counts_ = stage_emit(a, schedule, trace, manifest, table, api, raw_api)
    except FloorTrigger as ft:
        return run_floor(a, schedule, trace, manifest, ft, brief_path, tools_path, bslug, case_dir, mock_url)

    if not a.skip_tests:
        stage_selftest(schedule, trace, manifest, table, api, public)
    if a.no_deploy:
        manifest["status"] = "built offline (no deploy)"
        return
    # one slot per brief and variant: a rerun updates the same workflow in place, a test deploy never touches the final
    slot = a.slot or "%s-%s" % (bslug, getattr(a, "deploy_variant", "final"))
    stage_deploy(schedule, trace, manifest, wf, counts_, slot, bslug, api)
    if not a.skip_tests and not a.no_platform_test:
        stage_platform(schedule, trace, manifest, public)
    manifest["status"] = "ok"


# ---- 1. read


def stage_read(a, schedule, trace, manifest, brief_path, tools_path, public, out_dir):
    from builder.readers import read_brief
    from builder.readers.r1 import ReaderError

    dl = schedule.deadline("read")
    trace.stage_start("read", dl.seconds)
    if a.reuse_table:
        table = json.loads(pathlib.Path(a.reuse_table).read_text())
        rm = table.get("run_metadata") or {}
        trace.info("reusing frozen table %s (table hash %s, assurance %s); no model calls in this run" % (
            rel(pathlib.Path(a.reuse_table).resolve()), rm.get("table_hash"), rm.get("assurance")))
        _note_table(trace, manifest, table)
        trace.stage_end("read", "reused")
        return table
    bases = [str(pathlib.Path(b).resolve()) for b in a.base]
    if not bases and public in PUBLIC_BASES:
        bases = [str(PUBLIC_BRIEFS[x]) for x in PUBLIC_BASES[public]]
    if bases:
        trace.info("base documents for the reading: %s" % ", ".join(rel(b) for b in bases))
    read_dir = out_dir / "read"
    errors = []
    for attempt in (1, 2):
        budget = dl.remaining()
        if attempt == 2 and budget < 300:
            trace.info("no second reading attempt: %.0f s left of the reading budget" % budget)
            break
        trace.info("reading attempt %d, deadline %.0f s" % (attempt, budget))
        try:
            table = read_brief.read(str(brief_path), str(tools_path), out_dir=read_dir, deadline_s=budget,
                                    base_paths=bases)
        except (ReaderError, Exception) as e:  # noqa: BLE001
            errors.append("%s: %s" % (type(e).__name__, str(e)[:300]))
            trace.error("reading attempt %d failed: %s" % (attempt, errors[-1]))
            _trace_reader_calls(trace, read_dir / "trace.jsonl")
            continue
        _trace_reader_calls(trace, None, table)
        _note_table(trace, manifest, table)
        trace.stage_end("read", "ok")
        return table
    trace.stage_end("read", "failed")
    raise FloorTrigger("T1", "no frozen table after %d attempt(s): %s" % (len(errors), " | ".join(errors)))


def _trace_reader_calls(trace, jsonl_path=None, table=None):
    seen = set()
    rows = []
    if table is not None:
        rm = table.get("run_metadata") or {}
        rows = list(rm.get("usage") or []) + list(rm.get("adjudication_usage") or [])
    elif jsonl_path and pathlib.Path(jsonl_path).exists():
        rows = [json.loads(ln) for ln in pathlib.Path(jsonl_path).read_text().splitlines() if ln.strip()]
    for u in rows:
        key = json.dumps(u, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        trace.model_call(u.get("model"), u.get("purpose"), u.get("tokens"), u.get("seconds"), backend=u.get("backend"))


def _note_table(trace, manifest, table):
    rm = table.get("run_metadata") or {}
    manifest["table_hash"] = rm.get("table_hash") or canonical_hash({k: v for k, v in table.items() if k != "run_metadata"})
    manifest["plan_hash"] = canonical_hash(table["plan"]) if table.get("plan") else "none"
    manifest["assurance"] = rm.get("assurance")
    trace.info("table: hash %s, %d obligations, %d parameters, plan %s, assurance %s, reader timings %s" % (
        manifest["table_hash"][:12], len(table.get("obligations") or []), len(table.get("parameters") or {}),
        [s.get("type") for s in table.get("plan") or []], rm.get("assurance"), rm.get("timings")))


# ---- 2. emit


def stage_emit(a, schedule, trace, manifest, table, api, raw_api):
    from builder.emitter.emit import base_url_for, counts, emit
    from builder.emitter.walk import walk

    dl = schedule.deadline("emit")
    trace.stage_start("emit", dl.seconds)
    final_base = base_url_for(api, "final", None)
    manifest["bank_url"] = final_base
    wf, last = None, None
    for attempt in (1, 2):
        try:
            wf = emit(table, api, variant="final")
            findings = walk(wf, table, raw_api)
            big = {k: v for k, v in code_sizes(wf).items() if v > CODE_EXEC_MAX}
            if big:
                findings = list(findings) + ["code node %s sends %d bytes of code, over %d (platform limit %d with the variables)"
                                             % (k, v, CODE_EXEC_MAX, CODE_EXEC_LIMIT) for k, v in big.items()]
            if findings:
                raise ValueError("static walk: %d finding(s): %s" % (len(findings), " | ".join(map(str, findings[:5]))))
            break
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:400])
            trace.error("emit attempt %d failed: %s" % (attempt, last))
            wf = None
    if wf is None:
        trace.stage_end("emit", "failed")
        raise FloorTrigger("T2", last)
    c = counts(wf)
    size = len(json.dumps(wf))
    engine_code = max((len(json.dumps(n)) for n in wf["nodes"].values()), default=0)
    tools = sorted({fn["function"]["name"] for n in wf["nodes"].values()
                    for fn in (n.get("pre_actions") or []) + (n.get("functions") or []) + (n.get("tools") or [])
                    if isinstance(fn, dict) and isinstance(fn.get("function"), dict) and fn["function"].get("name")})
    trace.info("emitted final variant on %s: %d nodes, %d transitions, %s, %d tool definitions, %.0f KB (largest node %.0f KB); static walk clean"
               % (final_base, c["nodes"], c["transitions"], c["by_type"], len(tools), size / 1024, engine_code / 1024))
    sizes = code_sizes(wf)
    manifest["counts"] = {**c, "tools": len(tools), "tool_names": tools, "bytes": size, "largest_code_json": max(sizes.values(), default=0)}
    trace.info("largest code node: %s, %d bytes as JSON (limit %d with the variables)" % (
        max(sizes, key=sizes.get) if sizes else None, max(sizes.values(), default=0), CODE_EXEC_LIMIT))

    test_base_in = os.environ.get("OWN_BANK_URL") or TEST_PLACEHOLDER_BANK
    test_wf = emit(table, api, variant="test", bank_url=test_base_in)
    test_base = base_url_for(api, "test", test_base_in)
    if getattr(a, "deploy_variant", "final") == "test":
        trace.info("deploy variant: test (tools on %s); the final variant was built and walked as usual" % test_base)
    endpoint, other = variant_diff(wf, test_wf, final_base, test_base)
    manifest["variant_diff"] = {"endpoint_locations": len(endpoint), "other": [p for p, _, _ in other][:20],
                                "test_bank": "OWN_BANK_URL" if os.environ.get("OWN_BANK_URL") else "placeholder"}
    if other:
        trace.error("variants differ outside endpoint strings at %d location(s): %s" % (
            len(other), ", ".join(p for p, _, _ in other[:10])))
        manifest["errors"].append("variant diff outside endpoints")
    else:
        trace.info("variant diff: final and test differ only at %d endpoint location(s): %s" % (
            len(endpoint), ", ".join(endpoint[:3]) + (" ..." if len(endpoint) > 3 else "")))
    hits = t4_check(table)
    unsupported = [o.get("id") for o in table.get("obligations") or [] if o.get("capability") == "unsupported"]
    trace.info("capability: %d unsupported obligation(s) %s; on every customer's path: %s" % (
        len(unsupported), unsupported[:10], hits or "none"))
    if hits:
        trace.stage_end("emit", "T4")
        raise FloorTrigger("T4", "unsupported on every path: %s" % hits)
    trace.stage_end("emit", "ok")
    if getattr(a, "deploy_variant", "final") == "test":
        return test_wf, counts(test_wf)
    return wf, c


# ---- 3. local self-tests


def stage_selftest(schedule, trace, manifest, table, api, public):
    from builder import selftest

    dl = schedule.deadline("selftest")
    trace.stage_start("selftest", dl.seconds)
    manifest["tiers_run"].append("0")
    for r in selftest.snippet_check(table):
        trace.test("0", r["name"], r["result"], r["detail"])
    if public:
        trace.info("public brief %s: running its public cases through the local simulator on an in-process mock bank" % public)
        for r in selftest.public_cases(table, api, public):
            trace.test("0", "local %s" % r["name"], r["result"], r["detail"])
    else:
        rows = selftest.witness_cases(table)
        if rows:
            for r in rows:
                trace.test("0", r["name"], r["result"], r["detail"])
        else:
            trace.info("not a public brief and the table has no witness examples: no case-level local test")
    trace.stage_end("selftest", "ok" if dl.remaining() > 0 else "over budget")


# ---- 4. deploy


def _strip_report(sent, stored):
    """Paths present in what we sent and absent or changed in what the platform stored."""
    out = {"stripped": [], "changed": [], "added": []}
    for p, a, b in diff_paths(sent, stored):
        if b == "<absent>":
            out["stripped"].append(p)
        elif a == "<absent>":
            out["added"].append(p)
        else:
            out["changed"].append(p)
    return out


def stage_deploy(schedule, trace, manifest, wf, counts_, slot, bslug, api):
    freya = import_freya()
    dl = schedule.deadline("deploy")
    trace.stage_start("deploy", dl.seconds)
    manifest["slot"] = slot
    manifest["model_config"] = dict(freya.AGENT_LLM)
    try:
        with_retry(freya.validate_workflow, dl, trace, "dry run", slot, wf)
        trace.info("dry run accepted")
    except Exception as e:  # noqa: BLE001
        trace.error("dry run rejected: %s" % str(e)[:800])
        manifest["errors"].append("dry run rejected")
        trace.stage_end("deploy", "dry run rejected")
        raise
    state_before = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    existed = slot in state_before
    res = with_retry(freya.save_workflow, dl, trace, "save", slot, wf, state_file=str(STATE_FILE))
    manifest["workflow_id"], manifest["agent_id"] = res["workflow_id"], res["agent_id"]
    if existed:
        manifest["version"] = res.get("version")
        trace.info("updated workflow %s in place (slot %s), published version %s" % (res["workflow_id"], slot, res.get("version")))
    else:
        # a fresh create: set the event's model and publish, the same way the kit's update does
        manifest["version"] = with_retry(freya.update_workflow, dl, trace, "publish", res["workflow_id"], wf)
        trace.info("created workflow %s (agent %s) in slot %s, published version %s" % (
            res["workflow_id"], res["agent_id"], slot, manifest["version"]))
    stored = with_retry(freya.api, dl, trace, "read back", "GET", "/api/v2/workflow/%s" % res["workflow_id"],
                        workspaceId=freya.workspace_id())["workflow"]
    stored_wf = stored.get("workflow") or {}
    rep = _strip_report(wf, stored_wf)
    manifest["readback"] = {k: (len(v), v[:15]) for k, v in rep.items()}
    trace.info("read back: %d node(s) stored of %d sent; %d path(s) stripped, %d changed, %d added by the platform" % (
        len(stored_wf.get("nodes") or {}), counts_["nodes"], len(rep["stripped"]), len(rep["changed"]), len(rep["added"])))
    for kind in ("stripped", "changed"):
        if rep[kind]:
            trace.info("read back %s: %s" % (kind, ", ".join(rep[kind][:15]) + (" ..." if len(rep[kind]) > 15 else "")))
    llm = ((stored_wf.get("agent_config") or {}).get("llmConfig") or {})
    trace.info("stored agent model: %s/%s" % (llm.get("provider"), llm.get("model")))
    manifest["endpoint_check"] = endpoint_check(stored_wf, manifest["bank_url"])
    trace.info("endpoint check on the stored workflow: %s" % manifest["endpoint_check"])
    _export(freya, trace, manifest, res["workflow_id"], bslug, dl)
    trace.stage_end("deploy", "ok")


def _export(freya, trace, manifest, workflow_id, bslug, dl):
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / ("%s.workflow.json" % bslug)
    with_retry(freya.export_workflow, dl, trace, "export", workflow_id, str(path))
    manifest["export_path"] = str(path.relative_to(ROOT))
    manifest["export_hash"] = sha256_file(path)
    trace.info("exported %s (sha256 %s)" % (manifest["export_path"], manifest["export_hash"][:16]))


# ---- 5. platform self-test


def stage_platform(schedule, trace, manifest, public):
    budget = schedule.budget("platform")
    if not public:
        trace.info("platform self-test skipped: no practice cases exist for this brief")
        return
    if budget < PLATFORM_TEST_MIN_S:
        trace.info("platform self-test skipped: %.0f s left after the export reserve, %d needed" % (budget, PLATFORM_TEST_MIN_S))
        return
    case = "PUB-01" if public == "A" else "PUB-11"
    trace.stage_start("platform", budget)
    manifest["tiers_run"].append("platform")
    cmd = [sys.executable, str(KIT / "tools" / "run_cases.py"), manifest["agent_id"], "--brief", public, "--only", case]
    trace.info("official scorer, one case, one rep: run_cases.py <agent> --brief %s --only %s (timeout %.0f s)" % (public, case, budget))
    try:
        p = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True, timeout=budget, env=dict(os.environ))
        out = p.stdout + p.stderr
        (trace.dir / "platform-test.log").write_text(out)
        trace.echo_output("platform", out)
        line = next((ln for ln in out.splitlines() if ln.startswith(("PASS ", "FAIL "))), None)
        reasons = [ln.strip() for ln in out.splitlines() if ln.startswith("       -")]
        sim = re.search(r"Last simulation (\S+)", out)
        if line:
            trace.test("platform", case, line.split()[0], line + (" | " + " | ".join(reasons) if reasons else "")
                       + (" | simulation %s" % sim.group(1).rstrip(",") if sim else ""))
        else:
            trace.test("platform", case, "UNKNOWN", "no verdict line; exit %s; %s" % (p.returncode, out[-300:]))
        trace.stage_end("platform", "ok")
    except subprocess.TimeoutExpired:
        trace.test("platform", case, "UNKNOWN", "timed out after %.0f s (the simulation may still run on the platform)" % budget)
        trace.stage_end("platform", "timeout")


# ---- floor


def run_floor(a, schedule, trace, manifest, ft, brief_path, tools_path, bslug, case_dir=None, mock_url=None):
    """The floor after a trigger. A case folder with a mock URL gets our own runner (builder/floor/runner.py: it reads
    the whole folder, contract and drawings included, and checks its tools on the mock, no practice cases); a brief with
    a tool API file gets the kit's example builder. Either way the workflow it saved is exported."""
    manifest["trigger"] = {"id": ft.trigger, "reason": ft.reason}
    trace.error("fallback trigger %s: %s" % (ft.trigger, ft.reason))
    case_floor = case_dir is not None and mock_url is not None
    kind = "case" if case_floor else "kit"
    budget = schedule.budget("floor")
    if budget < FLOOR_MIN_S:
        trace.error("floor not admitted: %.0f s left after the export reserve, %d needed; no agent from this run" % (budget, FLOOR_MIN_S))
        manifest["status"] = "no agent"
        return
    if a.no_deploy:
        trace.info("floor not run: --no-deploy (it would be the %s floor with %.0f s)" % (kind, budget))
        manifest["status"] = "no agent (offline)"
        manifest["fallback"] = "%s (not run)" % kind
        return
    manifest["fallback"] = kind
    model = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")
    trace.stage_start("floor", budget)
    if case_floor:
        slot = a.slot or "%s-floor" % bslug
        state_file, key = STATE_FILE, slot
        session_log = trace.dir / "floor-session.jsonl"
        cmd = [sys.executable, str(ROOT / "builder" / "floor" / "runner.py"), str(case_dir), mock_url,
               "--run-dir", str(trace.dir), "--slot", slot, "--state-file", str(STATE_FILE), "--budget", "%.0f" % budget]
        cwd, purpose = ROOT, "case floor: read the case folder, build the agent with its tools on the mock, check and save it"
        trace.info("running our case-folder floor builder/floor/runner.py (model %s, timeout %.0f s, slot %s, mock %s); "
                   "session log %s" % (model, budget, slot, mock_url, rel(session_log)))
    else:
        state_file, key = KIT / ".freya-agents.json", brief_path.stem
        session_log = None
        cmd = [sys.executable, str(KIT / "examples" / "agent_builder.py"), str(brief_path), str(tools_path)]
        cwd, purpose = KIT, "kit floor: build, test and fix a phone agent"
        trace.info("running the kit's example builder as the floor (model %s, timeout %.0f s)" % (model, budget))
    before = (json.loads(state_file.read_text()) if state_file.exists() else {}).get(key)
    t0 = time.monotonic()
    try:
        # the runner cuts its own session before the budget; the extra seconds are for it to write its last lines
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=budget + (20 if case_floor else 0),
                           env=dict(os.environ))
        (trace.dir / "floor.log").write_text(p.stdout + p.stderr)
        trace.echo_output("floor", p.stdout + p.stderr)
        done = re.search(r"done: (\d+) turns, (\d+) s, \$([\d.]+)", p.stdout)
        trace.model_call(model, purpose, None, round(time.monotonic() - t0, 1),
                         detail=done.group(0) if done else "exit %s" % p.returncode)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        (trace.dir / "floor.log").write_text(out)
        trace.echo_output("floor", out)
        trace.model_call(model, purpose, None, round(time.monotonic() - t0, 1), detail="timed out")
        trace.error("floor timed out after %.0f s; exporting what it saved, if anything" % budget)
    if session_log is not None:
        trace.info("floor session log (every message of the coding agent): %s%s" % (
            rel(session_log), "" if session_log.exists() else " (not written)"))
        _trace_floor_steps(trace, trace.dir / "floor-steps.json")
        _trace_floor_sims(trace, trace.dir / "floor-sims.jsonl")
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    entry = state.get(key)
    if not entry:
        trace.stage_end("floor", "no workflow saved")
        manifest["status"] = "no agent"
        return
    if entry == before:
        # an earlier run's agent is not this run's: submitting it with this trace would not match
        trace.error("the floor saved nothing in this run; slot %s still holds an earlier version (%s), not exported" % (
            key, entry.get("version")))
        trace.stage_end("floor", "no workflow saved")
        manifest["status"] = "no agent"
        return
    manifest["slot"] = key if case_floor else "kit:" + key
    manifest["workflow_id"], manifest["agent_id"] = entry["workflow_id"], entry["agent_id"]
    manifest["version"] = entry.get("version")
    freya = import_freya()
    _export(freya, trace, manifest, entry["workflow_id"], bslug, Deadline(max(60.0, schedule.remaining())))
    trace.stage_end("floor", "ok")
    manifest["status"] = "ok (floor)"


def _trace_floor_steps(trace, steps_path):
    """The case floor's review and fix steps (builder/floor/runner.py writes them): every model call with its model,
    purpose, seconds and outcome; a skipped or failed step says why and that the first saved workflow stands."""
    try:
        steps = json.loads(steps_path.read_text()) if steps_path.exists() else []
    except (OSError, ValueError):
        steps = []
    for st in steps:
        if st.get("name") == "first":
            continue                                   # traced above as the floor's own model call
        outcome = st.get("outcome", "")
        if outcome.startswith("skipped"):
            trace.info("%s: %s; the first saved workflow stands" % (st.get("purpose"), outcome))
            continue
        trace.model_call(st.get("model"), st.get("purpose"), st.get("tokens"), st.get("seconds"),
                         detail=outcome, backend=st.get("backend"))
        if st.get("review"):
            trace.info("floor review (second model family, %s): %s" % (st.get("backend"), rel(trace.dir / st["review"])))
        if st.get("log"):
            trace.info("floor fix session log: %s" % rel(trace.dir / st["log"]))
        if outcome.startswith("failed"):
            trace.error("%s %s; the first saved workflow stands" % (st.get("name"), outcome))


def _trace_floor_sims(trace, sims_path):
    """The simulations the case floor ran on its own saved phone agent (builder/floor/runner.py's sim.py writes one line
    each): a test line per simulation with how many callers it ran, passed/total, the simulation id and seconds."""
    lines = sims_path.read_text().splitlines() if sims_path.exists() else []
    if not lines:
        trace.info("floor simulations: none ran on the saved phone agent")
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        total, passed = r.get("callers") or 0, r.get("passed") or 0
        status = str(r.get("status"))
        result = "PASS" if total and passed == total and status == "completed" else "FAIL"
        detail = "%d / %d passed, simulation %s, status %s, %s s" % (passed, total, r.get("simulation_id"), status,
                                                                     r.get("seconds"))
        if r.get("failed"):
            detail += "; failed: %s" % ", ".join(map(str, r["failed"]))
        trace.test("0", "floor simulation %s of the saved phone agent (%d simulated callers)" % (r.get("n"), total),
                   result, detail)


def main(argv=None):
    m = run(argv)
    return 0 if m["status"].startswith("ok") or m["status"].startswith("built") else 1


def _use_repo_venv():
    """`python3 builder/build.py` with a system Python: re-run under the repository's .venv when there is one."""
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.exists() and pathlib.Path(sys.prefix).resolve() != (ROOT / ".venv").resolve() and not os.environ.get("BUILD_NO_REEXEC"):
        os.environ["BUILD_NO_REEXEC"] = "1"
        os.execv(str(venv), [str(venv), str(pathlib.Path(__file__).resolve())] + sys.argv[1:])


if __name__ == "__main__":
    _use_repo_venv()
    sys.exit(main())
