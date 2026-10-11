"""Policy variants exercised without a network or a deployed agent: situation entries the public briefs do not use
(a callback instead of a transfer, a hardship entry with no offer), from the synthetic briefs of 2026-10-11 (fix round DEF)."""
import copy
import json
from pathlib import Path

import pytest

from bank.adapters import profile_from_openapi
from bank.server import Bank
from builder.emitter.emit import emit
from builder.readers.api_file import parse_api
from builder.engine.dates import parse_identity_date
from builder.engine.step import new_state, step

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / 'fixtures/tables/brief-b.json').read_text())
API = json.loads((ROOT / 'kit/build-the-builder/tools/openapi.json').read_text())
NOW = '2026-10-14T11:00'


def event(kind, **fields):
    return dict(kind=kind, **fields)


def ready(table, count=2):
    st = new_state()
    st['identity']['state'] = 'verified'
    st['stage'], st['pending'] = 'fetch', 'fetch'
    return step(st, [event('tool_result', tool='get_account', result='ok', data={
        'ok': True, 'products': [dict(product_id='p%d' % (i + 1), type='credit_card',
                                     past_due=360, minimum_payment=90, days_late=5)
                                  for i in range(count)]})], table, NOW)[0]


@pytest.mark.parametrize('text,rule,want', [
    ('nine oh two seventy-six', 'day_month_year', '1976-02-09'),
    ('five, twelve, ninety-one.', 'day_month_year', '1991-12-05'),
    ('two nine seventy six', 'month_day_year', '1976-02-09'),
    ('twenty four oh six eighty two', 'day_month_year', '1982-06-24'),
])
def test_spoken_numeric_birth_dates(text, rule, want):
    assert parse_identity_date(text, rule)['value'] == want


@pytest.mark.parametrize('kind', ['plan_request', 'human'])
def test_situation_callback_uses_configured_date_reason_and_close(kind):
    """Synthetic E: human and plan_request carry `callback: {reason, date_expr, time}` and a close row, no queue."""
    table = copy.deepcopy(TABLE)
    s = table['parameters']['situations']['value'][kind]
    s.update(transfer_queue=None, ask_first_once=False,
             callback={'date_expr': 'business_days_after(today, 2)', 'time': '14:30', 'reason': 'review'},
             close=['follow_up', 'review'])
    table['parameters']['closing.rows']['value'].append({
        'outcome': 'follow_up', 'reason': 'review', 'triggers': ['callback_booked'], 'precedence': 1})
    st = ready(table)
    st, _ = step(st, [event('amount_proposal', item='p1', amount=180, date_text='today')], table, NOW)
    st, out = step(st, [event(kind)], table, NOW)
    assert out['writes'][0]['tool'] == 'schedule_callback'
    assert out['writes'][0]['args'] == {'date': '2026-10-16', 'time': '14:30', 'reason': 'review'}
    assert not any(i['agreed'] for i in st['items'])
    st, out = step(st, [event('tool_result', tool='schedule_callback', result='ok')], table, NOW)
    assert out['writes'] == [dict(tool='close_call', args={'outcome': 'follow_up', 'reason': 'review'},
                                  item_id=None, intent_key='close:follow_up:review')]


@pytest.mark.parametrize('result,recorded,want', [
    ('ok', True, {'outcome': 'promise'}),
    ('failed', False, {'outcome': 'not_reached', 'reason': 'no_callback'}),
])
def test_callback_preserves_recorded_promise_precedence_and_failure_path(result, recorded, want):
    table = copy.deepcopy(TABLE)
    table['parameters']['situations']['value']['human'].update(
        transfer_queue=None, ask_first_once=False,
        callback={'date_expr': 'next_business_day(today)', 'time': '14:30', 'reason': 'review'},
        close=['not_reached', 'callback'])
    st = ready(table, 1)
    if recorded:
        st['items'][0].update(recorded=True, status='recorded')
    st, out = step(st, [event('human')], table, NOW)
    assert out['writes'][0]['tool'] == 'schedule_callback'
    st, out = step(st, [event('tool_result', tool='schedule_callback', result=result)], table, NOW)
    if result == 'failed':
        assert out['writes'][0]['tool'] == 'schedule_callback'
        st, out = step(st, [event('tool_result', tool='schedule_callback', result=result)], table, NOW)
    assert out['writes'][0]['tool'] == 'close_call'
    assert out['writes'][0]['args'] == want


def test_hardship_without_offer_transfers_without_recording_voluntary_proposal():
    """`offer: null` with a queue: the transfer follows at once; `voluntary_promise: drop` leaves the same-turn proposal."""
    table = copy.deepcopy(TABLE)
    s = table['parameters']['situations']['value']['hardship']
    s.update(offer=None, transfer_queue='assistance', voluntary_promise='drop')
    st, out = step(ready(table), [event('hardship'), event('human'),
                                event('amount_proposal', item='p1', amount=180, date_text='today')], table, NOW)
    assert out['writes'][0]['tool'] == 'transfer_to_agent'
    assert out['writes'][0]['args'] == {'queue': 'assistance'}
    assert not any(i['agreed'] for i in st['items'])
    assert 'support_offer' != st['pending']


def test_informational_hardship_keeps_existing_agreement_and_notes_only_open_items():
    """Synthetic E: hardship has no offer and no queue, only a line (sympathy, the support line) and a note."""
    table = copy.deepcopy(TABLE)
    s = table['parameters']['situations']['value']['hardship']
    s.update(offer=None, transfer_queue=None, note='hardship', say='Give the assistance contact from the policy.')
    st = ready(table)
    st, _ = step(st, [event('amount_proposal', item='p1', amount=180, date_text='today')], table, NOW)
    st, out = step(st, [event('hardship')], table, NOW)
    assert out['engine_next'] == 'readback'
    assert st['items'][0]['agreed']['amount'] == 180
    assert st['items'][1]['noted']['reason'] == 'hardship'
    assert s['say'] in out['say_next']


def code(wf, node):
    return wf['nodes'][node]['pre_actions'][0]['function']['parameters']['properties']['code']['default']


def test_callback_reason_reaches_emitted_tool_body():
    """An API with a required callback purpose enum: the body takes the engine's variable, the engine sets it from the entry."""
    api = copy.deepcopy(API)
    op = api['paths']['/schedule_callback']['post']
    schema = op['requestBody']['content']['application/json']['schema']
    schema['properties']['purpose'] = {'type': 'string', 'enum': ['unavailable', 'review']}
    schema['required'].append('purpose')
    table = copy.deepcopy(TABLE)
    table['parameters']['situations']['value']['human'].update(
        transfer_queue=None, ask_first_once=False,
        callback={'date_expr': 'next_business_day(today)', 'time': '14:30', 'reason': 'review'},
        close=['not_reached', 'callback'])
    wf = emit(table, parse_api(api))
    variables = {'now': NOW, 'engine_state': json.dumps(ready(table)),
                 'engine_events': json.dumps([event('human')])}
    exec(code(wf, 'engine'), {'vars': variables})
    assert variables['wa_schedule_callback__purpose'] == 'review'
    body = wf['nodes']['w_schedule_callback']['pre_actions'][0]['function']['parameters']['properties']['body']['properties']
    assert body['purpose']['default'] == '{{wa_schedule_callback__purpose}}'


def test_third_party_callback_takes_the_api_neutral_reason():
    """Brief A's third-party callback sets no reason; a required purpose enum gets the API's neutral value, not ''."""
    api = copy.deepcopy(API)
    schema = api['paths']['/schedule_callback']['post']['requestBody']['content']['application/json']['schema']
    schema['properties']['purpose'] = {'type': 'string', 'enum': ['unavailable', 'review']}
    schema['required'].append('purpose')
    table = json.loads((ROOT / 'fixtures/tables/brief-a.json').read_text())
    wf = emit(table, parse_api(api))
    st = new_state()
    st['callback'].update(date='2026-10-15', time='11:00')
    st['stage'], st['pending'] = 'callback', 'callback_book'
    variables = {'now': NOW, 'engine_state': json.dumps(st), 'engine_events': '[]'}
    exec(code(wf, 'engine'), {'vars': variables})
    assert variables['wa_schedule_callback__purpose'] == 'unavailable'


def test_bank_accepts_single_question_api_without_question_selector():
    api = copy.deepcopy(API)
    op = api['paths']['/verify_identity']['post']
    op['requestBody']['content']['application/json']['schema'] = {
        'type': 'object', 'properties': {'customer_id': {'type': 'string'},
                                      'security_date': {'type': 'string', 'format': 'date'}},
        'required': ['customer_id', 'security_date']}
    profile = profile_from_openapi(api)
    bank = Bank([])
    status, session = bank.open_session({'customer': {'id': 'one-question', 'profile': profile,
                                                    'identity': {'registered_date': '1976-02-09'}}})
    assert status == 200
    status, result = bank.call('verify_identity', {'customer_id': session['variables']['customer_id'],
                                                 'security_date': '1976-02-09'})
    assert status == 200 and result['verified'] and result['all_verified']
