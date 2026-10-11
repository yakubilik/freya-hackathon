"""Turkish customer words reach the English resolvers rewritten (builder/engine/dates.py tr_to_en, 2026-10-11)."""
from builder.engine.dates import resolve_date, resolve_amount_cents, resolve_time, parse_identity_date, parse_digits, parse_year, tr_to_en

NOW = "2026-10-11T10:00:00"


def d(text, rules=None):
    return resolve_date(text, NOW, rules or {})


def test_turkish_dates():
    assert d("27 Ekim")["date"] == "2026-10-27"
    assert d("yirmi yedi ekim")["date"] == "2026-10-27"
    assert d("ayın 27'sinde")["date"] == "2026-10-27"
    assert d("27'si")["date"] == "2026-10-27"
    assert d("yirmi yedisinde")["date"] == "2026-10-27"
    assert d("Ekim'in yirmi yedisi")["date"] == "2026-10-27"
    assert d("15 Kasım 2026 Pazar")["date"] == "2026-11-15"
    assert d("on beş kasım")["date"] == "2026-11-15"
    assert d("27.10.2026")["date"] == "2026-10-27"
    assert d("önümüzdeki cuma")["date"] == "2026-10-16"
    assert d("cuma günü")["date"] == "2026-10-16"
    assert d("yarın")["date"] == "2026-10-12"
    assert d("öbür gün")["date"] == "2026-10-13"
    assert d("bugün")["date"] == "2026-10-11"
    assert d("iki hafta sonra")["date"] == "2026-10-25"
    assert d("3 gün sonra")["date"] == "2026-10-14"
    assert d("ay sonunda")["kind"] == "vague"
    assert d("maaşımı alınca")["kind"] == "vague"
    assert d("haftaya")["kind"] == "vague"
    assert resolve_date("yirmi altı pazartesi", "2026-10-14T11:00:00")["date"] == "2026-10-26"
    assert resolve_date("pazartesi 26", "2026-10-14T11:00:00")["date"] == "2026-10-26"
    assert resolve_date("pazartesi 26 ekim", "2026-10-14T11:00:00")["date"] == "2026-10-26"


def test_turkish_corrections():
    assert d("21'i, pardon, 20'si")["date"] == "2026-10-20"
    assert d("yirmi bir ekim yani yirmi")["date"] == "2026-10-20"
    assert resolve_amount_cents("iki yüz, pardon, iki yüz elli") == 25000


def test_turkish_amounts():
    assert resolve_amount_cents("altı yüz otuz yedi lira elli kuruş") == 63750
    assert resolve_amount_cents("637,50 TL") == 63750
    assert resolve_amount_cents("1.250 lira") == 125000
    assert resolve_amount_cents("1.250,00 TL") == 125000
    assert resolve_amount_cents("bin iki yüz elli lira") == 125000
    assert resolve_amount_cents("altı yüz otuz yedi buçuk") == 63750
    assert resolve_amount_cents("dört yüz yirmi") == 42000
    assert resolve_amount_cents("yüz elli lira") == 15000
    assert resolve_amount_cents("altı otuz yedi elli") == 63750
    assert resolve_amount_cents("yüzde yirmi") is None


def test_turkish_times():
    assert resolve_time("saat on bir") == "11:00"
    assert resolve_time("on bir buçukta") == "11:30"
    assert resolve_time("11'de") == "11:00"
    assert resolve_time("öğleden sonra üçte") == "15:00"
    assert resolve_time("sabah onda") == "10:00"
    assert resolve_time("akşam yedi buçukta") == "19:30"
    assert resolve_time("öğlen") == "12:00"


def test_turkish_identity():
    assert parse_identity_date("on dört mart bin dokuz yüz seksen sekiz")["value"] == "1988-03-14"
    assert parse_identity_date("14 Mart 1988")["value"] == "1988-03-14"
    assert parse_digits("dört dört yedi bir", 4)["value"] == "4471"
    assert parse_year("bin dokuz yüz seksen sekiz")["value"] == "1988"


def test_english_untouched():
    for t in ("next Friday", "the 27th", "two hundred on the twentieth, sorry, the twenty-first", "half past two", "on the 21st", "4471"):
        assert tr_to_en(t, "date") == t
    assert d("next friday")["date"] == "2026-10-16"
    assert resolve_amount_cents("two hundred on the twentieth, sorry, the twenty-first") == 20000
    assert resolve_time("half past two") == "14:30"
