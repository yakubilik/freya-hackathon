import json,urllib.request
wf=json.load(open('out/workflow.json'))
M='https://freya-statement-mock.yakuupkeskin.workers.dev/voice/v1/'
def post(p,b):
    r=urllib.request.Request(M+p,data=json.dumps(b).encode(),headers={'Content-Type':'application/json','User-Agent':'curl/8'})
    try: return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e: return json.load(e)
def run(node,v):
    code=wf['nodes'][node]['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    exec(code,{'vars':v})
def get(d,path):
    for k in path.split('.'):
        if not isinstance(d,dict) or k not in d: return None
        d=d[k]
    return d
for cust in ['95004361','96158684','92460108','96125950','97526380']:
    v={'customerNumber':cust,'now':'2026-10-12T10:30:00+03:00'}
    env={'data':post('cards.list',{'customerNo':cust})}
    for m in wf['nodes']['load_cards']['response_mapping']:
        x=get(env,m['path'])
        if x is not None: v[m['variable']]=x
    run('prep_cards',v)
    if v['card_state']=='multi':
        v['card_hint']='Yıldız Premium'; run('resolve_card',v)
    run('clear_balance',v)
    env={'data':post('cards.balance',{'cardNumber':v['sel_card_number']})}
    for m in wf['nodes']['get_balance']['response_mapping']:
        x=get(env,m['path'])
        if x is not None: v[m['variable']]=str(x)
    env={'data':post('contact.email.get',{'customerNo':cust,'intAddressInfoType':'E'})}
    for m in wf['nodes']['get_email']['response_mapping']:
        x=get(env,m['path'])
        if x is not None: v[m['variable']]=str(x)
    run('build_reading',v)
    print(cust, v.get('code_error'), v.get('reading_text'),'\n')
