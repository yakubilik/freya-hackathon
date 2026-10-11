"""builder/build.py offline: the scheduler, the dotenv reader, the variant diff, the T4 check, the manifest on
failure, the T1/T2 fallback selection (monkeypatched, nothing reaches the platform or a model) and the trace format.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder import build  # noqa: E402
from builder.emitter.emit import emit  # noqa: E402
from builder.readers.api_file import load_api  # noqa: E402

KIT = ROOT / "kit" / "build-the-builder"
BRIEF_A = KIT / "briefs" / "brief-a.md"
API_PATH = KIT / "tools" / "openapi.json"
TABLE_A_PATH = ROOT / "fixtures" / "tables" / "brief-a.json"
TABLE_A = json.loads(TABLE_A_PATH.read_text())


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------------------------------------
# scheduler


def test_schedule_reservations_and_caps():
    c = Clock()
    s = build.Schedule(1800, clock=c)
    assert s.budget("read") == build.READ_MAX_S                       # capped at 17 minutes
    c.t = 1500                                                        # 300 s left
    assert s.budget("read") == 0                                      # 360 s are reserved after the reading
    assert s.budget("deploy") == pytest.approx(180)
    assert s.budget("platform") == pytest.approx(300 - build.EXPORT_RESERVE_S)
    c.t = 2000
    assert s.remaining() == 0 and s.budget("floor") == 0


def test_schedule_deadline_counts_down_on_the_same_clock():
    c = Clock()
    s = build.Schedule(1800, clock=c)
    c.t = 100
    d = s.deadline("selftest")
    assert d.seconds == 300
    c.t = 250
    assert d.remaining() == pytest.approx(150) and not d.expired()
    c.t = 500
    assert d.expired()


# ---------------------------------------------------------------------------------------------
# dotenv


def test_dotenv_reader(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("# comment\n\nFOO_A=plain\nexport FOO_B=\"quoted value\"\nFOO_C='single'\nFOO_D=x # trailing\n"
                 "not a line\n1BAD=no\nFOO_E=a=b\n")
    vals = build.read_dotenv(p)
    assert vals == {"FOO_A": "plain", "FOO_B": "quoted value", "FOO_C": "single", "FOO_D": "x", "FOO_E": "a=b"}
    monkeypatch.setenv("FOO_A", "from-env")
    monkeypatch.delenv("FOO_B", raising=False)
    set_ = build.load_env(p)
    assert "FOO_A" not in set_ and build.os.environ["FOO_A"] == "from-env"   # the environment wins
    assert build.os.environ["FOO_B"] == "quoted value"
    for k in ("FOO_B", "FOO_C", "FOO_D", "FOO_E"):
        monkeypatch.delenv(k, raising=False)
    assert build.read_dotenv(tmp_path / "missing") == {}


# ---------------------------------------------------------------------------------------------
# variant diff and endpoint check


def test_variants_differ_only_at_endpoints():
    api = load_api(API_PATH)
    final = emit(TABLE_A, api, variant="final")
    test = emit(TABLE_A, api, variant="test", bank_url="http://127.0.0.1:9")
    from builder.emitter.emit import base_url_for
    fb, tb = base_url_for(api, "final", None), base_url_for(api, "test", "http://127.0.0.1:9")
    endpoint, other = build.variant_diff(final, test, fb, tb)
    assert endpoint and not other
    test["nodes"]["setup"]["planted"] = 1                             # anything else is reported
    _, other = build.variant_diff(final, test, fb, tb)
    assert [p for p, _, _ in other] == ["/nodes/setup/planted"]
    assert build.endpoint_check(final, fb) == "clean"
    assert build.endpoint_check(test, fb).startswith("foreign urls: http://127.0.0.1:9")


def test_diff_paths_reports_stripped_and_added():
    rep = build._strip_report({"a": 1, "b": {"c": [1, 2]}}, {"b": {"c": [1, 3]}, "d": 0})
    assert rep == {"stripped": ["/a"], "changed": ["/b/c/1"], "added": ["/d"]}


def test_t4_only_for_every_path_obligations():
    t = {"plan": [{"type": "party", "obligations": ["O1"]}, {"type": "negotiate", "per_item": True, "obligations": ["O2"]}],
         "obligations": [{"id": "O1", "capability": "unsupported", "when": {"state": "third_party"}},
                         {"id": "O2", "capability": "unsupported", "when": {"state": "negotiation"}},
                         {"id": "O3", "capability": "unsupported", "when": {"state": "any"}},
                         {"id": "O4", "capability": "structural", "when": {"state": "any"}}]}
    assert build.t4_check(t) == [("O1", "stage party"), ("O3", "state any")]
    assert build.t4_check(TABLE_A) == []


def test_public_brief_detection(tmp_path):
    assert build.public_brief(BRIEF_A.read_text()) == "A"
    assert build.public_brief(BRIEF_A.read_text() + "\n") is None
    assert build.slug("briefs/Hidden 1.md") == "hidden-1"


# ---------------------------------------------------------------------------------------------
# whole runs, offline


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """No .env, no platform, no models: every run stays on this machine."""
    monkeypatch.setattr(build, "load_env", lambda *a, **k: [])
    monkeypatch.setattr(build, "source_commit", lambda: "0" * 40)
    floors = []

    def fake_floor(a, schedule, trace, manifest, ft, *rest):
        floors.append(ft.trigger)
        manifest["trigger"] = {"id": ft.trigger, "reason": ft.reason}
        manifest["fallback"] = "kit"
        manifest["status"] = "ok (floor)"

    monkeypatch.setattr(build, "run_floor", fake_floor)
    return tmp_path, floors


def _argv(tmp_path, *extra):
    return [str(BRIEF_A), str(API_PATH), "--out-dir", str(tmp_path / "run"), "--no-deploy", *extra]


def test_offline_run_with_reused_table(offline):
    tmp, floors = offline
    m = build.run(_argv(tmp, "--reuse-table", str(TABLE_A_PATH)))
    assert m["status"] == "built offline (no deploy)" and not floors
    assert m["results"]["FAIL"] == 0 and m["results"]["PASS"] >= 14          # 4 snippet checks + 10 public cases
    assert m["variant_diff"]["other"] == [] and m["tiers_run"] == ["0"]
    assert json.loads((tmp / "run" / "manifest.json").read_text())["table_hash"] == m["table_hash"]


def test_trace_format(offline):
    tmp, _ = offline
    build.run(_argv(tmp, "--reuse-table", str(TABLE_A_PATH), "--skip-tests"))
    log = (tmp / "run" / "trace.log").read_text().splitlines()
    rows = [json.loads(x) for x in (tmp / "run" / "trace.jsonl").read_text().splitlines()]
    assert len(log) == len(rows) and " info " in log[0] and "builder start" in log[0]
    assert all({"at", "t", "kind"} <= set(r) for r in rows)
    assert any(r["kind"] == "stage" and r.get("stage") == "emit" and r.get("status") == "ok" for r in rows)
    assert "builder end" in log[-2] and "created on Freya" in log[-1]
    tr = build.Trace(tmp / "t2", echo=False)
    tr.model_call("claude-opus-5-5", "r1: read the brief", 1234, 5.0)
    tr.test("0", "case", "PASS", "fine")
    lines = (tmp / "t2" / "trace.log").read_text().splitlines()
    assert "model=claude-opus-5-5 purpose=r1: read the brief tokens=1234 seconds=5.0" in lines[0]
    assert "[tier 0] PASS case | fine" in lines[1]


def test_t1_reader_error_selects_the_floor(offline, monkeypatch):
    tmp, floors = offline
    from builder.readers import read_brief
    from builder.readers.r1 import ReaderError
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise ReaderError("R1 output fails the schema")

    monkeypatch.setattr(read_brief, "read", boom)
    m = build.run(_argv(tmp))
    assert floors == ["T1"] and len(calls) == 2                       # two attempts, then the floor
    assert m["trigger"]["id"] == "T1" and m["fallback"] == "kit"
    assert json.loads((tmp / "run" / "manifest.json").read_text())["trigger"]["id"] == "T1"


def test_t2_emitter_failure_selects_the_floor(offline, monkeypatch):
    tmp, floors = offline
    import builder.emitter.emit as E

    def bad_emit(*a, **k):
        raise E.EmitError("the table has no closing.rows")

    monkeypatch.setattr(E, "emit", bad_emit)
    m = build.run(_argv(tmp, "--reuse-table", str(TABLE_A_PATH)))
    assert floors == ["T2"] and "closing.rows" in m["trigger"]["reason"]


def test_t2_on_static_walk_findings(offline, monkeypatch):
    tmp, floors = offline
    import builder.emitter.walk as W
    monkeypatch.setattr(W, "walk", lambda *a, **k: ["node x: target y does not exist"])
    build.run(_argv(tmp, "--reuse-table", str(TABLE_A_PATH)))
    assert floors == ["T2"]


def test_t4_selects_the_floor(offline, tmp_path):
    tmp, floors = offline
    t = json.loads(TABLE_A_PATH.read_text())
    t["obligations"].append({"id": "O-x", "capability": "unsupported", "status": "effective", "when": {"state": "any"}})
    p = tmp_path / "t4.json"
    p.write_text(json.dumps(t))
    build.run(_argv(tmp, "--reuse-table", str(p)))
    assert floors == ["T4"]


def test_manifest_written_on_failure(offline, monkeypatch):
    tmp, _ = offline

    def crash(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(build, "stage_emit", crash)
    m = build.run(_argv(tmp, "--reuse-table", str(TABLE_A_PATH)))
    saved = json.loads((tmp / "run" / "manifest.json").read_text())
    assert m["status"] == saved["status"] == "failed"
    assert saved["errors"] == ["RuntimeError: unexpected"] and saved["finished"] and saved["brief_hash"]
    assert "run failed" in (tmp / "run" / "trace.log").read_text()


def test_floor_not_admitted_without_time(monkeypatch, tmp_path):
    monkeypatch.setattr(build, "load_env", lambda *a, **k: [])
    c = Clock()
    s = build.Schedule(1800, clock=c)
    c.t = 1500
    a = build.parse_args([str(BRIEF_A), str(API_PATH)])
    tr = build.Trace(tmp_path, s, echo=False)
    m = {"errors": []}
    build.run_floor(a, s, tr, m, build.FloorTrigger("T1", "x"), BRIEF_A, API_PATH, "brief-a")
    assert m["status"] == "no agent" and m["trigger"]["id"] == "T1"


def test_retry_on_transient_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(build.time, "sleep", lambda s: None)
    tr = build.Trace(tmp_path, echo=False)
    n = []

    def flaky():
        n.append(1)
        if len(n) < 3:
            raise RuntimeError("PUT /api/v2/workflow/x -> 503: busy")
        return "ok"

    assert build.with_retry(flaky, build.Deadline(600), tr, "save") == "ok" and len(n) == 3
    with pytest.raises(RuntimeError):
        build.with_retry(lambda: (_ for _ in ()).throw(RuntimeError("POST /x -> 400: bad")), build.Deadline(600), tr, "save")


@pytest.mark.parametrize("table_name", ["brief-a.json", "brief-b.json"])
def test_engine_code_fits_the_code_exec_limit(table_name):
    """The platform rejects a code_exec whose code and data exceed 131072 bytes (measured 2026-10-10)."""
    t = json.loads((ROOT / "fixtures" / "tables" / table_name).read_text())
    wf = emit(t, load_api(API_PATH))
    sizes = build.code_sizes(wf)
    assert max(sizes.values()) <= build.CODE_EXEC_MAX, sizes



def test_slug_of_a_generic_brief_name_takes_the_directory():
    """Two hidden briefs both called brief.md would export to the same submission/brief.workflow.json (synthetic C..F did
    on 2026-10-11): the directory name goes in front."""
    from builder.build import slug
    assert slug("kit/build-the-builder/briefs/brief-a.md") == "brief-a"
    assert slug("synthetic/C/brief.md") == "c-brief"
    assert slug("/tmp/Hidden Brief 2/README.md") == "hidden-brief-2-readme"
    assert slug("hidden/g.joined.md") == "g-joined"


# ---------------------------------------------------------------------------------------------
# the final's form: <case_folder> <mock_url>

MOCK = "https://our-mock.example.workers.dev"


def _case(tmp_path, contract_name="contract/service.json", contract=True):
    d = tmp_path / "case"
    (d / "sub").mkdir(parents=True)
    (d / "BRIEF.md").write_text("# Brief\nread me first\n")
    (d / "README.md").write_text("# Readme\nwhat each document is\n")
    (d / "analysis.md").write_text("# Analysis\n")
    (d / "customers.json").write_text(json.dumps([{"name": "x", "dob": "1990-01-01"}]))
    (d / "qa.csv").write_text("q,a\nwhy,because\n")
    (d / "sub" / "announcement.txt").write_text("an announcement\n")
    (d / "flow.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (d / ".DS_Store").write_bytes(b"\x00\x01")
    if contract:
        c = d / contract_name
        c.parent.mkdir(parents=True, exist_ok=True)
        c.write_text(API_PATH.read_text())
    return d


def test_is_url():
    assert build.is_url(MOCK) and build.is_url("http://127.0.0.1:8787/v1")
    assert not build.is_url(str(API_PATH)) and not build.is_url("tools.json")


def test_case_folder_reading_order(tmp_path):
    d = _case(tmp_path)
    contract = d / "contract" / "service.json"
    out, used, skipped = build.join_case_dir(d, exclude=[contract])
    # data files (customers, tables) feed the mock and the tests, not the reader
    assert used == ["BRIEF.md", "README.md", "analysis.md", "sub/announcement.txt"]
    assert skipped == ["customers.json", "flow.png", "qa.csv"]
    text = out.read_text()
    assert text.index("read me first") < text.index("what each document is") < text.index("an announcement")
    assert "freya-bank-mock" not in text and "\n\n---\n\n" in text


def test_contract_detection(tmp_path):
    d = _case(tmp_path)
    p, doc, notes = build.find_contract(build.case_files(d))
    assert p == d / "contract" / "service.json" and "paths" in doc and not notes   # customers.json is not a contract
    (d / "contract" / "service.json").unlink()
    assert build.find_contract(build.case_files(d))[0] is None


def test_contract_detection_yaml(tmp_path):
    y = tmp_path / "api.yaml"
    y.write_text("openapi: 3.0.3\nservers:\n  - url: https://bank.example/v1\npaths:\n  /verify_identity:\n"
                 "    post:\n      operationId: verify_identity\n      responses: {'200': {description: ok}}\n")
    try:
        build.load_structured(y)
    except ValueError as e:
        pytest.skip("no YAML parser here: %s" % e)
    p, doc, _ = build.find_contract([y])
    assert p == y and doc["servers"][0]["url"] == "https://bank.example/v1"


def test_mock_url_selects_the_mock_base(offline):
    tmp, floors = offline
    d = _case(tmp)
    m = build.run([str(d), MOCK, "--out-dir", str(tmp / "run"), "--no-deploy", "--skip-tests",
                   "--reuse-table", str(TABLE_A_PATH)])
    assert m["status"] == "built offline (no deploy)" and not floors
    assert m["bank_url"] == MOCK + "/v1"                                # the contract's server path on the mock origin
    assert m["mock_url"] == MOCK and m["contract_path"].endswith("case/contract/service.json")
    assert m["brief_documents"][:2] == ["BRIEF.md", "README.md"] and m["skipped_documents"] == ["customers.json", "flow.png", "qa.csv"]
    copy = json.loads((tmp / "case.contract.json").read_text())
    assert copy["servers"] == [{"url": MOCK + "/v1"}]
    log = (tmp / "run" / "trace.log").read_text()
    saved = (tmp / "run" / "manifest.json").read_text()
    assert "tools go to the mock %s/v1" % MOCK in log and "not read (image, binary or data file): customers.json, flow.png, qa.csv" in log
    for text in (log, saved):
        assert str(ROOT) not in text and str(pathlib.Path.home()) not in text


def test_mock_url_without_contract_fails_loudly(offline):
    tmp, floors = offline
    d = _case(tmp, contract=False)
    m = build.run([str(d), MOCK, "--out-dir", str(tmp / "run"), "--no-deploy", "--reuse-table", str(TABLE_A_PATH)])
    assert m["status"] == "failed" and not floors
    assert "no machine-readable service contract" in m["errors"][0]
    assert "no machine-readable service contract" in (tmp / "run" / "trace.log").read_text()


def test_trace_scrubs_keys_and_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOME_API_KEY", "sk-very-secret-value")
    tr = build.Trace(tmp_path / "t")
    tr.info("key sk-very-secret-value at %s" % (build.ROOT / "builder" / "build.py"))
    out = capsys.readouterr().out
    assert "sk-very-secret-value" not in out and "*** at builder/build.py" in out
    assert "sk-very-secret-value" not in (tmp_path / "t" / "trace.jsonl").read_text()
