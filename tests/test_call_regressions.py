"""Pure engine and emitted-node regressions; no network or dialogue model required."""
import copy
import json
from pathlib import Path

import pytest

from builder.engine.dates import resolve_date
from builder.engine.step import new_state, step
from builder.emitter.emit import emit
from builder.readers.api_file import load_api

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / 'fixtures/tables/brief-b.json').read_text())
API = load_api(ROOT / 'kit/build-the-builder/tools/openapi.json')
NOW = '2026-10-14T11:00'


def account(table, amount=276.30):
    state = new_state()
    state['stage'] = 'fetch'
    state['pending'] = 'fetch'
    state['identity']['state'] = 'verified'
    return step(state, [{'kind': 'tool_result', 'tool': 'get_account', 'result': 'ok',
                         'data': {'ok': True, 'products': [
                             {'product_id': 'p1', 'type': 'credit_card', 'card_last4': '1234',
                              'past_due': amount, 'days_late': 8}]}}], table, NOW)[0]


def engine_code(table, api=API):
    wf = emit(table, api)
    return wf['nodes']['engine']['pre_actions'][0]['function']['parameters']['properties']['code']['default']


@pytest.mark.parametrize('field,typ,amount,expected', [
    ('amount', 'string', 276.30, '276.30'),
    ('pledge_sum', 'string', 72, '72.00'),
    ('amount', 'number', 276.30, 276.30),
    ('amount_cents', 'integer', 276.30, 27630),
    ('amount_cents', 'string', 276.30, '27630'),
])
def test_emitted_promise_amount_preserves_api_type(field, typ, amount, expected):
    api = copy.deepcopy(API)
    fields = api['tools']['create_promise']['request_fields']
    spec = fields.pop('amount')
    spec['type'] = typ
    fields[field] = spec
    state = account(TABLE, amount)
    state, out = step(state, [{'kind': 'pay_today_yes'}], TABLE, NOW)
    assert out['engine_next'] == 'readback'
    values = {'now': NOW, 'engine_state': json.dumps(state),
              'engine_events': json.dumps([{'kind': 'confirm'}])}
    exec(engine_code(TABLE, api), {'vars': values})
    value = values['wa_create_promise__' + field]
    assert value == expected and type(value) is type(expected)


def contact_table(reason='contact_blocked'):
    table = copy.deepcopy(TABLE)
    table['parameters']['notes.reasons']['value'].append(reason)
    sit = table['parameters']['situations']['value']['dont_want_to_talk']
    sit['count'] = 1
    sit['close_verified'] = ['no_promise', reason]
    table['parameters']['closing.rows']['value'].insert(0, {
        'outcome': 'no_promise', 'reason': reason, 'precedence': 1,
        'triggers': ['dont_want_twice_verified'], 'line': None})
    return table


@pytest.mark.parametrize('reason', ['quiet_requested', 'contact_blocked'])
def test_contact_note_reason_comes_from_table(reason):
    table = contact_table(reason)
    state, out = step(account(table), [{'kind': 'dont_want_to_talk'}], table, NOW)
    assert out['writes'][0]['args']['reason'] == reason
    assert 'has been noted' not in out['say_next']


@pytest.mark.parametrize('failures', [0, 1, 2])
@pytest.mark.parametrize('exact', [False, True])
def test_contact_acknowledgement_requires_successful_note(failures, exact):
    table = contact_table()
    table['parameters']['closing.rows']['value'][0]['line'] = 'contact_ack'
    table['phrases'].append({'id': 'contact_ack', 'kind': 'mandatory', 'exact': exact,
                            'text': 'Your request has been noted.' if exact else 'Say the request was noted.'})
    state, out = step(account(table), [{'kind': 'dont_want_to_talk'}], table, NOW)
    code = engine_code(table)
    values = {'now': NOW, 'engine_state': json.dumps(state)}
    for attempt in range(min(failures + 1, 2)):
        ok = attempt >= failures
        values['engine_events'] = json.dumps([{'kind': 'tool_result', 'tool': 'add_note',
            'item': 'p1', 'result': 'ok' if ok else 'failed', 'data': {'ok': ok}}])
        exec(code, {'vars': values})
    assert values['engine_next'] == 'close'
    assert ('has been noted' in values['close_text']) == (failures < 2)


def test_unknown_verification_responses_cannot_loop_forever():
    state, _ = step(new_state(), [{'kind': 'party_confirmed'}], TABLE, NOW)
    state, out = step(state, [{'kind': 'id_answer', 'text': '9 July 1984'}], TABLE, NOW)
    for _ in range(10):
        state, out = step(state, [{'kind': 'tool_result', 'tool': 'verify_identity',
                                  'result': 'unknown', 'data': {}}], TABLE, NOW)
        if out['engine_next'] == 'close':
            break
        if out['engine_next'] != 'verify':
            state, out = step(state, [{'kind': 'id_answer', 'text': '9 July 1984'}], TABLE, NOW)
    assert out['engine_next'] == 'close'
    assert state['identity']['wrong'] == 0
    assert any('no verdict' in item for item in out['unsupported'])


def test_tonight_callback_keeps_daypart_from_date_slot():
    assert resolve_date('tonight', NOW)['date'] == '2026-10-14'
    state, _ = step(new_state(), [{'kind': 'party_other'}], TABLE, NOW)
    state, out = step(state, [{'kind': 'callback_offer', 'date_text': 'tonight',
                              'time_text': 'nine'}], TABLE, NOW)
    assert not out['writes'] and state['callback']['invalid'] == 1
    state, out = step(state, [{'kind': 'callback_offer', 'date_text': 'tomorrow',
                              'time_text': 'eleven'}], TABLE, NOW)
    assert out['writes'][0]['args'] == {'date': '2026-10-15', 'time': '11:00'}


def test_unreadable_callback_dates_use_table_invalid_offer_limit():
    state, _ = step(new_state(), [{'kind': 'party_other'}], TABLE, NOW)
    for _ in range(TABLE['parameters']['third_party.callback.max_invalid']['value']):
        state, out = step(state, [{'kind': 'callback_offer', 'date_text': 'when they get back',
                                  'time_text': 'eleven'}], TABLE, NOW)
    assert out['writes'][0]['tool'] == 'close_call'
    assert out['writes'][0]['args']['reason'] == 'no_callback'


def test_time_only_callback_still_asks_for_day():
    state, _ = step(new_state(), [{'kind': 'party_other'}], TABLE, NOW)
    state, out = step(state, [{'kind': 'callback_offer', 'text': 'eleven'}], TABLE, NOW)
    assert state['pending'] == 'callback_date'
    assert state['callback']['invalid'] == 0
    state, out = step(state, [{'kind': 'callback_offer', 'date_text': 'tomorrow'}], TABLE, NOW)
    assert out['writes'][0]['args'] == {'date': '2026-10-15', 'time': '11:00'}


def test_speech_prompts_ask_security_fields_and_repeat_unconfirmed_name():
    wf = emit(TABLE, API)
    identity = wf['nodes']['identity']['on_enter']['prompt']
    assert 'never supply or guess its value' in identity
    assert 'silent instructions, never customer-facing sentences' in identity
    greeting = wf['nodes']['greeting']['task_message']
    assert 'repeat the supplied name question' in greeting
    assert 'never announce account access' in greeting


def test_exact_opening_preserves_additional_table_content_once():
    table = copy.deepcopy(TABLE)
    opening = next(p for p in table['phrases'] if p['id'] == 'opening')
    opening.update(exact=True, text='Welcome to this call.')
    requirements = 'Start with the welcome sentence, then identify Example Cooperative and your assistant role.'
    table['parameters']['opening.sentence_content'] = {'value': requirements, 'confidence': 'quoted'}
    values = {'now': NOW, 'engine_events': '[]'}
    code = engine_code(table)
    exec(code, {'vars': values})
    assert opening['text'] in values['say_head_line']
    assert requirements in values['say_content']
    values['engine_events'] = json.dumps([{'kind': 'other', 'text': 'hello?'}])
    exec(code, {'vars': values})
    assert requirements not in values['say_content']
