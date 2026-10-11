"""The 26 recorded sequences of the organizers' bank, replayed over HTTP against our bank started in-process."""
import json, pathlib, sys

import pytest
from data_paths import data_path

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bank import replay  # noqa: E402

SEQUENCES = json.load(open(data_path("research/bank-recorded-behaviour.json")))


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
