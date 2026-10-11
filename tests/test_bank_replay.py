"""The 26 recorded sequences of the organizers' bank, replayed over HTTP against our bank started in-process."""
import json, pathlib, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bank import replay  # noqa: E402

SEQUENCES = json.load(open(replay.DEFAULT_RECORDING))


@pytest.fixture(scope="module")
def base_url():
    srv, base = replay.start_server()
    yield base
    srv.shutdown()


@pytest.mark.parametrize("seq", SEQUENCES, ids=[s.get("title", f"#{i}") for i, s in enumerate(SEQUENCES)])
def test_recorded_sequence(base_url, seq):
    bad = replay.replay_sequence(base_url, seq)
    assert not bad, "\n".join(bad)


def test_all_26_present():
    assert len(SEQUENCES) == 26


def test_one_question_verify_without_a_question_field():
    """Synthetic F (2026-10-11): the API's verify_identity has no question field, the answer travels as `birth_date`;
    the bank answered 'field must be date_of_birth' to every call and the agent closed not_verified / failed."""
    import json, pathlib, sys
    root = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from bank import replay
    from bank.adapters import profile_from_openapi
    srv, base = replay.start_server()
    try:
        prof = profile_from_openapi(json.load(open(root / "synthetic" / "F" / "api.json")))
        case = dict(next(c for c in json.load(open(root / "synthetic" / "F" / "cases.json")) if c["id"] == "F-02"))
        case["profile"] = prof
        status, s = replay.http(base, "/v1/practice/sessions", {"customer": case})
        assert status == 200 and s["ok"], s
        cid = s["variables"]["customer_id"]
        status, wrong = replay.http(base, "/v1/verify_identity", {"client_ref": cid, "birth_date": "1979-07-03"})
        assert wrong["ok"] is True and wrong["verified"] is False, wrong
        status, right = replay.http(base, "/v1/verify_identity", {"client_ref": cid, "birth_date": "1979-07-02"})
        assert right["ok"] is True and right["verified"] is True and right["all_verified"] is True, right
    finally:
        srv.shutdown()
