"""Engine shapes the public briefs do not use, found by the static audit of 2026-10-11 (runs/night/engine-assessment.static.md,
"Not covered"): a per-question wrong-answer limit, a do-not-call request, month-first customer dates, coded product types.
Table-driven: every test adds the field to a copy of a public table; without the field the behaviour is the one of main."""
import copy
import json
from pathlib import Path

import pytest

from builder.engine.step import new_state, step

ROOT = Path(__file__).resolve().parents[1]
TABLE_A = json.loads((ROOT / 'fixtures/tables/brief-a.json').read_text())
TABLE_B = json.loads((ROOT / 'fixtures/tables/brief-b.json').read_text())
NOW = '2026-10-14T11:00'


def event(kind, **fields):
    return dict(kind=kind, **fields)


def verify_result(st, table, data):
    ev = {'kind': 'tool_result', 'tool': 'verify_identity', 'result': 'ok' if data.get('ok') else 'failed', 'data': data, 'args': {}}
    return step(st, [ev], table, NOW)


def at_identity(table):
    st, _ = step({}, [], table, NOW)
    st, _ = step(st, [event('party_confirmed')], table, NOW)
    return st


def answer(st, table, text):
    st, out = step(st, [event('id_answer', text=text)], table, NOW)
    assert [w['tool'] for w in out['writes']] == ['verify_identity']
    return st


# 1. per-question wrong-answer limit


def per_question_table(limit=2, total=None):
    table = copy.deepcopy(TABLE_A)
    p = table['parameters']
    p['identity.max_wrong_per_question'] = {'value': limit, 'type': 'integer', 'confidence': 'quoted'}
    if total is None:
        p['identity.max_wrong'] = {'type': 'integer', 'confidence': 'not_specified'}
    else:
        p['identity.max_wrong']['value'] = total
    return table


def test_one_wrong_answer_on_each_question_does_not_end_a_per_question_check():
    """Synthetic C rule 13: a wrong postcode and a wrong year are one wrong each; the check continues."""
    table = per_question_table(2)
    st = answer(at_identity(table), table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'pending' and st['identity']['wrong_by_q'] == {'date_of_birth': 1}
    st = answer(st, table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': True})
    assert st['identity']['q_index'] == 1
    st = answer(st, table, '4471')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'pending' and st['identity']['wrong'] == 2
    assert st['identity']['wrong_by_q'] == {'date_of_birth': 1, 'phone_last4': 1}
    assert 'identity.max_wrong' not in out['unsupported']


def test_two_wrong_answers_on_the_same_question_end_a_per_question_check():
    table = per_question_table(2)
    st = answer(at_identity(table), table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    st = answer(st, table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'failed' and out['close'] == {'outcome': 'not_verified', 'reason': 'failed'}
    assert [w['tool'] for w in out['writes']] == ['close_call']


def test_bank_per_question_counter_is_taken_as_the_stricter_count():
    """The bank's answers-left field counts on the question (synthetic C wrong_left_on_question): one left of two means
    one wrong on this question even when the engine saw none, and zero left ends the check."""
    table = per_question_table(2)
    st = answer(at_identity(table), table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False, 'wrong_answers_left': 1})
    assert st['identity']['wrong_by_q'] == {'date_of_birth': 1} and st['identity']['state'] == 'pending'
    st = answer(st, table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False, 'wrong_answers_left': 0})
    assert st['identity']['state'] == 'failed'


def test_total_limit_still_ends_the_check_when_both_limits_are_given():
    table = per_question_table(2, total=2)
    st = answer(at_identity(table), table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    st = answer(st, table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': True})
    st = answer(st, table, '4471')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'failed' and st['identity']['wrong'] == 2


def test_question_entry_limit_wins_over_the_table_wide_one():
    table = per_question_table(3)
    table['parameters']['identity.questions']['value'][0]['max_wrong'] = 1
    st = answer(at_identity(table), table, '12 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'failed'


def test_swap_hint_is_not_a_wrong_answer_on_the_question_either():
    table = per_question_table(2)
    st = answer(at_identity(table), table, '21 July 1991')
    st, out = verify_result(st, table, {'ok': True, 'verified': False, 'hint': 'day_month_swapped'})
    assert st['identity'].get('wrong_by_q', {}) == {} and st['identity']['hinted'] is True


def test_without_a_per_question_limit_the_total_counts_as_before():
    st = answer(at_identity(TABLE_A), TABLE_A, '12 July 1991')
    for n in (1, 2):
        st, out = verify_result(st, TABLE_A, {'ok': True, 'verified': False})
        assert st['identity']['wrong'] == n and 'wrong_by_q' not in st['identity']
        st = answer(st, TABLE_A, '12 July 1991')
    st, out = verify_result(st, TABLE_A, {'ok': True, 'verified': False})
    assert st['identity']['state'] == 'failed'
