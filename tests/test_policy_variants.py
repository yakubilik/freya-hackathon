"""Policy variants exercised without a network or a deployed agent."""
import copy
import json
from pathlib import Path

import pytest

from bank.adapters import profile_from_openapi
from bank.server import Bank
from builder.emitter.emit import emit
from builder.emitter.wire import NORMALISER, response_field_map
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


def test_call_ending_product_note_does_not_note_other_products():
    table = copy.deepcopy(TABLE)
    table['parameters']['situations']['value']['dispute'] = {
        'obligation': 'targeted-note', 'close': ['no_promise', 'dispute']}
    table['obligations'].append(dict(id='targeted-note', status='effective', scope='product',
                                    then=[{'note': {'reason': 'dispute'}}]))
    st = ready(table)
    st['items'][1]['noted'] = {'reason': 'paid'}
    st['items'][1]['status'] = 'noted'
    st, out = step(st, [event('dispute', item='p1')], table, NOW)
    assert [(w['tool'], w['args']) for w in out['writes']] == [
        ('add_note', {'product_id': 'p1', 'reason': 'dispute'})]
    st, out = step(st, [event('tool_result', tool='add_note', item='p1', result='ok')], table, NOW)
    assert out['writes'][0]['tool'] == 'close_call'
    assert not st['items'][1]['noted']


@pytest.mark.parametrize('kind', ['plan_request', 'human'])
def test_situation_callback_uses_configured_date_reason_and_close(kind):
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
    table = copy.deepcopy(TABLE)
    s = table['parameters']['situations']['value']['hardship']
    s.update(offer=None, transfer_queue=None, note='hardship', say='Give the assistance contact from the policy.')
    st = ready(table)
    st, _ = step(st, [event('amount_proposal', item='p1', amount=180, date_text='today')], table, NOW)
    st, out = step(st, [event('hardship'), event('human')], table, NOW)
    assert out['engine_next'] == 'readback'
    assert st['items'][0]['agreed']['amount'] == 180
    assert st['items'][1]['noted']['reason'] == 'hardship'
    assert s['say'] in out['say_next']


def code(wf, node):
    return wf['nodes'][node]['pre_actions'][0]['function']['parameters']['properties']['code']['default']


def test_close_speech_uses_table_content_instead_of_phrase_id_default():
    table = copy.deepcopy(TABLE)
    ph = next(p for p in table['phrases'] if p['id'] == 'use_app_or_branch')
    ph.update(text='Tell the customer to contact the verification desk.', exact=False)
    for row in table['parameters']['closing.rows']['value']:
        if 'identity_failed' in row.get('triggers', []):
            row['line'] = ph['id']
    wf = emit(table, API)
    st = new_state()
    st['identity']['state'] = 'failed'
    st['global']['triggers'] = ['identity_failed']
    st['stage'], st['pending'] = 'close', 'close'
    variables = {'now': NOW, 'engine_state': json.dumps(st), 'engine_events': '[]'}
    exec(code(wf, 'engine'), {'vars': variables})
    assert ph['text'] in variables['close_content']
    assert 'mobile app' not in variables['close_content']
    node = wf['nodes']['close_not_verified_failed']
    assert node['on_enter']['type'] == 'llm'
    assert '{{close_content}}' in node['on_enter']['prompt']
    assert node['on_enter_first_entry_only']


def test_single_object_response_is_normalised_into_products():
    api = {'tools': {'get_account': {'response_fields': {
        'facility': {'type': 'object'}, 'facility.account_ref': {'type': 'string'},
        'facility.category': {'type': 'string'}, 'facility.overdue_cents': {'type': 'integer'},
        'facility.days_overdue': {'type': 'integer'}}}}}
    ns = {'_RESP_MAP': response_field_map(api)}
    exec(NORMALISER, ns)
    got = ns['_wire_norm']('get_account', {'ok': True, 'facility': {
        'account_ref': 'x', 'category': 'card', 'overdue_cents': 12345, 'days_overdue': 8}})
    assert got['products'][0]['product_id'] == 'x'
    assert got['products'][0]['past_due'] == 123.45
    assert got['products'][0]['overdue_cents'] == 12345
    assert got['products'][0]['days_late'] == 8


def test_callback_reason_reaches_emitted_tool_body():
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
    wf = emit(table, api)
    variables = {'now': NOW, 'engine_state': json.dumps(ready(table)),
                 'engine_events': json.dumps([event('human')])}
    exec(code(wf, 'engine'), {'vars': variables})
    assert variables['wa_schedule_callback__purpose'] == 'review'
    body = wf['nodes']['w_schedule_callback']['pre_actions'][0]['function']['parameters']['properties']['body']['properties']
    assert body['purpose']['default'] == '{{wa_schedule_callback__purpose}}'


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
