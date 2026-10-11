"""The customer's language: an English table emits exactly as before, a Turkish table gets the Turkish instruction line,
Turkish close sentences and a Turkish goodbye, with the model's instructions still in English."""
import copy
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder.emitter import fragments as F  # noqa: E402
from builder.emitter.emit import emit  # noqa: E402
from builder.emitter.walk import walk  # noqa: E402
from builder.readers.api_file import load_api  # noqa: E402

TABLE_A = json.load(open(ROOT / "fixtures" / "tables" / "brief-a.json"))
API_PATH = ROOT / "kit" / "build-the-builder" / "tools" / "openapi.json"
API = load_api(API_PATH)
API_RAW = json.load(open(API_PATH))


def baked(wf):
    """The workflow's JSON plus every hex-baked constant decoded (py() hides the engine's EMIT_CFG that way)."""
    s = json.dumps(wf, ensure_ascii=False)
    return s + "".join(bytes.fromhex(h).decode("utf-8") for h in re.findall(r"bytes\.fromhex\('([0-9a-f]+)'\)", s))

TURKISH = ["Merhaba, ben Freya Bankası'nın dijital asistanıyım. Bu görüşme kayıt altına alınmaktadır.",
           "Sayın {title} {last_name} ile mi görüşüyorum?",
           "Güvenlik için lütfen doğum tarihinizi söyler misiniz?",
           "Ödemeyi hangi gün yapabilirsiniz?",
           "Taahhüdünüzü onaylayan bir kısa mesaj alacaksınız.",
           "Teşekkür ederim, iyi günler."]


def turkish_table():
    """Brief A with its customer-facing phrases in Turkish (the brief's own text stays English: the phrases decide)."""
    t = copy.deepcopy(TABLE_A)
    for i, ph in enumerate(t["phrases"]):
        if ph.get("kind") == "mandatory":
            # a phrase the close may speak gets its Turkish close sentence (the table's own sentence wins at the close)
            ph["text"] = F.CLOSE_SPOKEN_TR.get(ph.get("id")) or TURKISH[i % len(TURKISH)]
    return t


def test_english_fixture_is_en():
    assert F.detect_language(TABLE_A) == "en"
    assert F.detect_language({}) == "en"


def test_turkish_name_in_english_brief_stays_en():
    t = copy.deepcopy(TABLE_A)
    t["phrases"][1]["text"] = "Am I speaking with Ayşe Çelik?"
    t["parameters"]["organisation.name"]["value"] = "Şişli Bankası"
    assert F.detect_language(t) == "en"


def test_turkish_phrases_are_tr():
    assert F.detect_language(turkish_table()) == "tr"


def test_turkish_brief_text_is_tr_even_with_english_phrases():
    t = copy.deepcopy(TABLE_A)
    for u in t["units"].values():
        u["text"] = "Müşteri ödeme için bir tarih söylerse taahhüt kaydedilir ve görüşme kapatılır."
    for ob in t["obligations"]:
        if isinstance(ob, dict) and isinstance(ob.get("text"), str):
            ob["text"] = "Müşteriye tutar ve gün söylenir, lütfen başka bir şey teklif edilmez."
    assert F.detect_language(t) == "tr"


def test_english_workflow_unchanged():
    wf = emit(TABLE_A, API)
    assert walk(wf, TABLE_A, API_RAW) == []
    s = baked(wf)
    assert "Speak English." in wf["system_prompt"]
    assert F.TURKISH_LINE not in s and "Turkish" not in s
    assert "Teşekkür" not in s
    assert F.CLOSE_SPOKEN["thanks_goodbye"] in s


def test_turkish_workflow():
    table = turkish_table()
    wf = emit(table, API)
    assert walk(wf, table, API_RAW) == []
    s = json.dumps(wf, ensure_ascii=False)
    assert "Speak Turkish." in wf["system_prompt"] and F.TURKISH_LINE in wf["system_prompt"]
    assert "Speak English." not in wf["system_prompt"]
    entry = [n["on_enter"]["prompt"] for n in wf["nodes"].values() if n.get("on_enter", {}).get("type") == "llm"]
    assert entry and all("in Turkish (polite 'siz' form" in p for p in entry if "Convey all of this content" in p)
    # the baked close sentences and goodbye are Turkish, none of the English ones with a Turkish variant survive
    code = json.dumps(wf["nodes"]["engine"], ensure_ascii=False)
    chunks = [bytes.fromhex(h).decode("utf-8") for h in re.findall(r"bytes\.fromhex\('([0-9a-f]+)'\)", code)]
    cfg = [json.loads(c) for c in chunks if c.startswith("{") and "close_spoken" in c]
    assert cfg, "the engine's EMIT_CFG was not found in the baked code"
    cfg = cfg[0]
    text = baked(wf)
    assert cfg["goodbye"] == F.GOODBYE_TR
    assert cfg["close_spoken"]["thanks_goodbye"] == "Teşekkür ederim, iyi günler."
    assert cfg["close_spoken"]["promise_recorded"] == "Ödeme taahhüdünüz kaydedildi."
    assert cfg["close_spoken"]["sympathy"] == "Bunu duyduğuma üzüldüm."
    for key, english in F.CLOSE_SPOKEN.items():
        assert cfg["close_spoken"][key] != english, key
        assert english not in text, key
    assert "'yi günler'" in text and "if 'goodbye' not in text.lower():" not in text
    # instructions stay English: the stage task and the kind help are untouched
    assert any("STEP: security questions" in n.get("task_message", "") for n in wf["nodes"].values())


def test_close_spoken_for_keeps_table_sentence_in_turkish():
    t = turkish_table()
    t["phrases"].append({"id": "promise_recorded", "kind": "mandatory", "exact": False, "text": "Taahhüdünüz sisteme kaydedilmiştir."})
    out = F.close_spoken_for(t, "tr")
    assert out["promise_recorded"] == "Taahhüdünüz sisteme kaydedilmiştir."
    assert out["thanks_goodbye"] == F.GOODBYE_TR
