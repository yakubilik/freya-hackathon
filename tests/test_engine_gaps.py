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


# 2. do-not-call request


def ready(table, count=2):
    st = new_state()
    st['identity']['state'] = 'verified'
    st['stage'], st['pending'] = 'fetch', 'fetch'
    return step(st, [event('tool_result', tool='get_account', result='ok', data={
        'ok': True, 'products': [dict(product_id='p%d' % (i + 1), type='credit_card', past_due=360, minimum_payment=90, days_late=5)
                                 for i in range(count)]})], table, NOW)[0]


def dnc_table(**entry):
    """Table B plus a do-not-call situation in the shape of synthetic C (note, two close pairs)."""
    table = copy.deepcopy(TABLE_B)
    s = {'obligation': 'O-x', 'note': 'do_not_call', 'close_verified': ['no_promise', 'do_not_call'],
         'close_unverified': ['not_verified', 'do_not_call']}
    s.update(entry)
    table['parameters']['situations']['value']['do_not_call'] = s
    table['parameters']['notes.reasons']['value'].append('do_not_call')
    return table


def tool_ok(tool, **data):
    return event('tool_result', tool=tool, result='ok', data=dict(ok=True, **data))


def test_do_not_call_notes_every_open_item_and_closes_with_the_entry_pair():
    table = dnc_table()
    st = ready(table)
    st, out = step(st, [event('do_not_call', text='Stop calling me.')], table, NOW)
    assert [it['noted']['reason'] for it in st['items']] == ['do_not_call', 'do_not_call']
    assert out['writes'][0]['tool'] == 'add_note' and out['writes'][0]['args'] == {'product_id': 'p1', 'reason': 'do_not_call'}
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert out['writes'][0]['args'] == {'product_id': 'p2', 'reason': 'do_not_call'}
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert out['writes'] == [dict(tool='close_call', args={'outcome': 'no_promise', 'reason': 'do_not_call'}, item_id=None,
                                  intent_key='close:no_promise:do_not_call')]
    assert 'noted' in out['say_next'].lower()


def test_do_not_call_before_verification_writes_one_note_without_a_product():
    table = dnc_table()
    st = at_identity(table)
    st, out = step(st, [event('do_not_call', text='Do not call me again.')], table, NOW)
    assert out['writes'] == [dict(tool='add_note', args={'product_id': None, 'reason': 'do_not_call'}, item_id=None,
                                  intent_key='note:call:do_not_call:0')]
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert out['writes'][0]['args'] == {'outcome': 'not_verified', 'reason': 'do_not_call'}
    assert st['identity']['state'] == 'pending' and 'noted' in out['say_next'].lower()


def test_do_not_call_note_failing_twice_still_closes_without_claiming_a_note():
    table = dnc_table()
    st = at_identity(table)
    st, out = step(st, [event('do_not_call')], table, NOW)
    for n in (1, 2):
        st, out = step(st, [event('tool_result', tool='add_note', result='failed', data={'ok': False})], table, NOW)
    assert out['writes'][0]['tool'] == 'close_call' and 'noted' not in out['say_next'].lower()


def test_do_not_call_beats_a_hardship_and_a_transfer_in_the_same_reply():
    """Synthetic F: only the do-not-call wish is stronger than the hardship hand-over; no transfer, the note and the close."""
    table = dnc_table()
    st = ready(table, 1)
    st, out = step(st, [event('hardship', text='I lost my job'), event('human'), event('do_not_call')], table, NOW)
    assert [w['tool'] for w in out['writes']] == ['add_note'] and st['global']['pending_transfer'] is None
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert [w['tool'] for w in out['writes']] == ['close_call'] and out['writes'][0]['args']['outcome'] == 'no_promise'


@pytest.mark.parametrize('after,want', [
    (['promise', None], {'outcome': 'promise'}),
    (None, {'outcome': 'promise'}),
])
def test_do_not_call_after_a_recorded_promise_keeps_the_promise(after, want):
    """The promise stays; the entry's after_promise_close names the row, else the closing rows decide (B: promise wins)."""
    table = dnc_table(**({'after_promise_close': after} if after else {}))
    st = ready(table, 1)
    st['items'][0].update(recorded=True, status='recorded', confirmed=True)
    st['stage'] = 'record'
    st, out = step(st, [event('do_not_call')], table, NOW)
    assert out['writes'][0]['args'] == {'product_id': None, 'reason': 'do_not_call'}     # the wish is still noted
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert out['writes'][0]['tool'] == 'close_call' and out['writes'][0]['args'] == want
    assert st['items'][0]['recorded'] and not st['items'][0]['noted']


def test_do_not_call_uses_the_table_row_when_the_pair_is_listed():
    table = dnc_table()
    table['parameters']['closing.rows']['value'].append(
        {'outcome': 'no_promise', 'reason': 'do_not_call', 'triggers': ['do_not_call'], 'precedence': 1, 'line': 'close_dnc'})
    table['phrases'].append({'id': 'close_dnc', 'kind': 'mandatory', 'text': 'We will not call you again.', 'exact': True})
    st = ready(table, 1)
    st, out = step(st, [event('do_not_call')], table, NOW)
    st, out = step(st, [tool_ok('add_note')], table, NOW)
    assert out['writes'][0]['args'] == {'outcome': 'no_promise', 'reason': 'do_not_call'}
    assert 'We will not call you again.' in out['mandatory_lines']


def test_do_not_call_without_a_table_entry_is_the_ordinary_refusal_to_talk():
    """No such row: the first request is handled as dont_want_to_talk (the call goes on until its count)."""
    st = ready(TABLE_B)
    st, out = step(st, [event('do_not_call', text='Stop calling me.')], TABLE_B, NOW)
    assert st['global']['dont_want'] == 1 and not st['closed'] and out['writes'] == []
    assert out['engine_next'] == 'negotiate' and not any(it['noted'] for it in st['items'])


def test_do_not_call_kind_is_extracted_only_when_the_table_has_the_situation():
    from builder.emitter.emit import emit
    from builder.readers.api_file import parse_api
    api = parse_api(json.loads((ROOT / 'kit/build-the-builder/tools/openapi.json').read_text()))

    def kinds(wf, node):
        return [f for f in wf['nodes'][node]['extraction_schema'] if f['name'] == node + '_reply1'][0]['enum_values']

    plain = emit(TABLE_B, api)
    assert 'do_not_call' not in kinds(plain, 'negotiate')
    wf = emit(dnc_table(), api)
    for node in ('greeting', 'identity', 'negotiate', 'readback'):
        ks = kinds(wf, node)
        assert 'do_not_call' in ks and ks.index('do_not_call') == ks.index('other') - 1
    code = wf['nodes']['negotiate_observe']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    assert 'do_not_call' in bytes.fromhex(code.split("bytes.fromhex('")[1].split("'")[0]).decode()
