import json, re, datetime

ONES = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz']
TENS = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan']
DIG = ['sıfır', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz']
MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']


def w3(n):
    h, r = divmod(n, 100)
    t, o = divmod(r, 10)
    s = []
    if h:
        s.append('yüz' if h == 1 else ONES[h] + ' yüz')
    if t:
        s.append(TENS[t])
    if o:
        s.append(ONES[o])
    return ' '.join(s)


def words(n):
    n = int(n)
    if n == 0:
        return 'sıfır'
    parts = []
    for val, name in ((10 ** 9, 'milyar'), (10 ** 6, 'milyon'), (1000, 'bin')):
        q, n = divmod(n, val)
        if q:
            if name == 'bin' and q == 1:
                parts.append('bin')
            else:
                parts.append(w3(q) + ' ' + name)
    if n:
        parts.append(w3(n))
    return ' '.join(parts)


def num(v):
    try:
        if v is None or str(v).strip() == '':
            return None
        return float(str(v).strip())
    except Exception:
        return None


def amount(v, cur):
    x = num(v) or 0.0
    cents = int(round(abs(x) * 100))
    whole, frac = divmod(cents, 100)
    main = {'TL': 'Türk Lirası', 'USD': 'Dolar', 'EUR': 'Euro', 'GBP': 'İngiliz Sterlini'}[cur]
    sub = {'TL': 'kuruş', 'USD': 'sent', 'EUR': 'sent', 'GBP': 'peni'}[cur]
    if cur == 'TL':
        if frac:
            return words(whole) + ' lira ' + words(frac) + ' kuruş'
        return words(whole) + ' Türk Lirası'
    s = words(whole) + ' ' + main
    if frac:
        s += ' ' + words(frac) + ' ' + sub
    return s


def pdate(s):
    try:
        d, m, y = str(s).strip().split('.')
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None


def sdate(s):
    d = pdate(s)
    if not d:
        return str(s or '')
    return '%d %s %d' % (d.day, MONTHS[d.month], d.year)


def digits(s):
    return ' '.join(DIG[int(c)] for c in str(s) if c.isdigit())


def today():
    try:
        return datetime.date.fromisoformat(str(vars.get('now') or '')[:10])
    except Exception:
        return None


def join_tr(items):
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' ve ' + items[-1]


def load_cards():
    raw = vars.get('cards_raw')
    cards = None
    if isinstance(raw, list):
        cards = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            cards = json.loads(raw)
        except Exception:
            try:
                cards = json.loads(raw.replace("'", '"').replace('True', 'true').replace('False', 'false'))
            except Exception:
                cards = None
    if cards is None:
        cards = []
        i = 0
        while True:
            found = False
            c = {}
            for k in ('cardNumber', 'cardNumberLast4', 'productName', 'isMainCard', 'status'):
                for pre in ('load_cards_response.data.data.cards.%d.' % i, 'load_cards_response.data.data.cards[%d].' % i):
                    if pre + k in vars:
                        c[k] = vars.get(pre + k)
                        found = True
            if not found:
                break
            cards.append(c)
            i += 1
    out = []
    for c in cards:
        if isinstance(c, dict):
            out.append(c)
    return out
CUR = ['TL', 'USD', 'EUR', 'GBP']
FIELDS = ['statementPaymentStatus', 'transferAmount', 'statementDebt', 'minPayment', 'remainingDebt', 'remainingMinPayment', 'totalDebt', 'remainAutomaticPaymentAmount']
