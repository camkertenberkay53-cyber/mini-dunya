"""Faz-63 — Gemini senaryo JSON uyumluluğu: API seviyesinde yapılandırılmış çıktı (responseJsonSchema) ve şema
doğrulamasından önce çalışan deterministik normalize_senaryo(). Çevrimdışı; ağ ve Gemini YOK (taşıyıcı sahte)."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

from motor.orkestrasyon.gemini import GeminiLLMProvider
from motor.uretim import sozlesme

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_63", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
ARA = json.loads((PILOT / "arastirma.json").read_text())


def _shorts(ids=True, **ek):
    cs = [{"metin": "İki Türk ordusu, tek kazanan.", "kartlar": ["C2"], "niyet": {"tur": "3d", "aciklama": "ordular"}},
          {"metin": "Zafer Osmanlıların oldu.", "kartlar": ["C5"], "niyet": {"tur": "3d", "aciklama": "zafer"}}]
    if ids:
        for i, c in enumerate(cs, 1):
            c["id"] = f"S{i}"
    return {"surum": 1, "konu": "otlukbeli-1473-oto", "format": "shorts", "baslik": "Otlukbeli", "kanca": "S1",
            "final": "S2", "ana_fikir": "Toplar savaşın kaderini belirledi.", "cumleler": cs, **ek}


# ================================================================== normalize_senaryo

def test_tek_anahtarli_senaryo_sarmalayicisi_acilir():
    s = _shorts()
    n = ou.normalize_senaryo({"senaryo": copy.deepcopy(s)})
    assert n == s and sozlesme.senaryo_denetle(n, ARA) == []


def test_ic_ice_tek_anahtarli_sarmalayici_da_acilir():
    s = _shorts()
    assert ou.normalize_senaryo({"senaryo": {"senaryo": copy.deepcopy(s)}}) == s


@pytest.mark.parametrize("girdi", [
    {"senaryo": _shorts(), "surum": 1},                       # yanında başka kök anahtar
    {"senaryo": _shorts(), "not": "x"},
    {"senaryo": "metin"},                                      # değer dict değil
    {"senaryo": [_shorts()]},
])
def test_cok_anahtarli_ya_da_dict_olmayan_sarmalayici_acilmaz(girdi):
    n = ou.normalize_senaryo(copy.deepcopy(girdi))
    assert set(n) == set(girdi) and n["senaryo"] == girdi["senaryo"]
    if isinstance(girdi["senaryo"], dict) and len(girdi) > 1:
        assert any("'senaryo'" in h and "unexpected" in h for h in sozlesme.senaryo_denetle(n, ARA))   # açık hata


def test_eksik_idler_mevcutlarla_cakismadan_sirali_tamamlanir():
    cs = [{"metin": "a"}, {"id": "S2", "metin": "b"}, {"metin": "c"}, {"id": "S4", "metin": "d"}, {"metin": "e"},
          {"id": None, "metin": "f"}]
    n = ou.normalize_senaryo({"cumleler": cs})
    assert [c["id"] for c in n["cumleler"]] == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert len({c["id"] for c in n["cumleler"]}) == 6


def test_mevcut_idler_asla_degismez_bicimi_ne_olursa_olsun():
    cs = [{"id": "S9", "metin": "a"}, {"id": "x7", "metin": "b"}, {"metin": "c"}, {"id": "S1", "metin": "d"}]
    n = ou.normalize_senaryo({"cumleler": cs})
    assert [c["id"] for c in n["cumleler"]] == ["S9", "x7", "S2", "S1"]          # S1 dolu → ilk boş S2
    assert any("x7" in h for h in sozlesme.sema_hatalari("senaryo", dict(_shorts(), cumleler=[
        dict(c, kartlar=["C1"], niyet={"tur": "3d", "aciklama": "a"}) for c in n["cumleler"]])))   # şema yine yakalar


def test_eksik_idli_gercek_shorts_senaryosu_sema_dogrulamasindan_gecer():
    ham = {"senaryo": _shorts(ids=False)}
    assert any("'senaryo' was unexpected" in h for h in sozlesme.senaryo_denetle(ham, ARA))   # sorunun kendisi
    eksik = _shorts(ids=False)
    assert any("'id' is a required property" in h for h in sozlesme.senaryo_denetle(eksik, ARA))
    assert sozlesme.senaryo_denetle(ou.normalize_senaryo(ham), ARA) == []


@pytest.mark.parametrize("girdi", [
    {"senaryo": _shorts(ids=False)}, {"senaryo": {"senaryo": _shorts(ids=False)}}, _shorts(), _shorts(ids=False),
    {"cumleler": [{"metin": "a"}, {"id": "S1", "metin": "b"}]}, {"senaryo": _shorts(), "x": 1},
    {"cumleler": [{"id": "S1"}]}, [1, 2], "metin", None, {},
])
def test_idempotent(girdi):
    bir = ou.normalize_senaryo(copy.deepcopy(girdi))
    assert ou.normalize_senaryo(copy.deepcopy(bir)) == bir


def test_bilinmeyen_alanlar_silinmez_girdi_degismez():
    g = {"senaryo": dict(_shorts(ids=False), gemini_notu="x", cumleler=[
        {"metin": "a", "kartlar": ["C1"], "niyet": {"tur": "3d"}, "ozel": {"k": 1}}])}
    kopya = copy.deepcopy(g)
    n = ou.normalize_senaryo(g)
    assert g == kopya                                                              # girdi yerinde değişmez
    assert n["gemini_notu"] == "x" and n["cumleler"][0]["ozel"] == {"k": 1} and n["cumleler"][0]["id"] == "S1"


@pytest.mark.parametrize("bozuk, beklenen", [
    ("metin", "is not of type 'object'"),
    ({"kartlar": ["C1"], "niyet": {"tur": "3d"}}, "'metin' is a required property"),
    ({"metin": "", "kartlar": ["C1"], "niyet": {"tur": "3d"}}, "is too short"),
    ({"metin": 5, "kartlar": ["C1"], "niyet": {"tur": "3d"}}, "is not of type 'string'"),
])
def test_bozuk_ogeler_onarilmaz_dogrulayici_acik_hata_verir(bozuk, beklenen):
    s = _shorts(ids=False)
    s["cumleler"].append(bozuk)
    n = ou.normalize_senaryo({"senaryo": s})
    assert all("id" not in c for c in n["cumleler"] if isinstance(c, dict))     # hiçbir ID uydurulmadı
    h = sozlesme.senaryo_denetle(n, ARA)
    assert any(beklenen in x for x in h), h


@pytest.mark.parametrize("girdi", [[_shorts()], "metin", None, 3])
def test_dict_olmayan_veri_aynen_doner(girdi):
    assert ou.normalize_senaryo(girdi) == girdi


# ================================================================== API şemaları

DESTEKLENMEYEN = {"$ref", "$defs", "$schema", "pattern", "minLength", "maxLength", "const", "oneOf", "default"}


def _anahtarlar(s, yol=""):
    if isinstance(s, dict):
        for k, v in s.items():
            if k == "properties":
                for ad, x in v.items():
                    yield from _anahtarlar(x, f"{yol}.{ad}")
            else:
                yield k, yol
                yield from _anahtarlar(v, f"{yol}/{k}")
    elif isinstance(s, list):
        for x in s:
            yield from _anahtarlar(x, yol)


@pytest.mark.parametrize("ad", ["shorts", "taslak", "bolum"])
def test_api_semalari_yalniz_desteklenen_anahtarlar(ad):
    s = {"shorts": ou.shorts_api_semasi(), "taslak": ou.TASLAK_API_SEMASI, "bolum": ou.BOLUM_API_SEMASI}[ad]
    kotu = [(k, y) for k, y in _anahtarlar(s) if k in DESTEKLENMEYEN]
    assert kotu == [] and set(k for k, _ in _anahtarlar(s)) <= ou.API_SEMA_ANAHTARLARI
    assert s["additionalProperties"] is False


def test_shorts_api_semasi_yerel_semadan_turetilir_ve_yerel_semaya_dokunmaz():
    yerel = copy.deepcopy(sozlesme.sema("senaryo"))
    s = ou.shorts_api_semasi()
    assert sozlesme.sema("senaryo") == yerel                                        # korunan şema değişmedi
    assert s["required"] == yerel["required"] and "senaryo" not in s["properties"]
    item = s["properties"]["cumleler"]["items"]
    assert "id" in item["required"] and item["additionalProperties"] is False
    assert s["properties"]["surum"] == {"enum": [1]}                                # const → enum
    assert item["properties"]["niyet"]["properties"]["tur"]["enum"] == ["3d", "harita", "bilgi_karti", "gorsel25d"]
    pilot = json.loads((PILOT / "senaryo.json").read_text())
    jsonschema.validate(pilot, s)                                                   # geçerli senaryo API şemasına uyar
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"senaryo": pilot}, s)                                  # sarmalayıcıyı API şeması dışlar
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(pilot, cumleler=[{k: v for k, v in c.items() if k != "id"} for c in pilot["cumleler"]]), s)


def test_bolum_ve_taslak_api_semalari_gecerli_yaniti_kabul_eder():
    jsonschema.validate({"cumleler": [{"metin": "a", "kartlar": ["C1"], "olgusal": True,
                                       "niyet": {"tur": "gorsel25d", "gorsel_id": "g", "aciklama": "x", "hareket": "pan_sol"}}]},
                        ou.BOLUM_API_SEMASI)
    jsonschema.validate({"baslik": "b", "bolumler": [{"baslik": "x", "roller": ["kanca"], "ozet": "o", "kartlar": [],
                                                      "hedef_sn": 150}]}, ou.TASLAK_API_SEMASI)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"cumleler": [{"metin": "a", "kartlar": [], "olgusal": True, "niyet": {"tur": "bilgi_karti"}}]},
                            ou.BOLUM_API_SEMASI)


# ================================================================== API payload (sahte taşıyıcı)

class Tasiyici:
    def __init__(self, yanitlar):
        self.yanitlar, self.govdeler = list(yanitlar), []

    def __call__(self, url, govde, basliklar, zaman):
        self.govdeler.append(json.loads(govde))
        return self.yanitlar.pop(0)


def _ok(metin='{"a": 1}'):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


def _saglayici(t):
    return GeminiLLMProvider(modeller=("gemini-m",), tasiyici=t, anahtar="test-anahtari", uyku=lambda s: None,
                             beklemeler_503=(0, 0), beklemeler_503_yedek=(0,))


def test_payloadda_response_json_schema_gonderilir():
    t = Tasiyici([_ok()])
    sema = ou.shorts_api_semasi()
    assert _saglayici(t).tamamla("istem", "senaryo", {"yanit_semasi": sema}) == '{"a": 1}'
    cfg = t.govdeler[0]["generationConfig"]
    assert cfg["responseJsonSchema"] == sema and cfg["responseMimeType"] == "application/json"
    assert "responseSchema" not in cfg                                              # ikisi birlikte gönderilmez
    assert t.govdeler[0]["contents"][0]["parts"][0]["text"] == "istem"              # istem (JSON talimatı) korunur


def test_sema_verilmezse_payload_eskisi_gibi():
    t = Tasiyici([_ok()])
    _saglayici(t).tamamla("istem", "arastirma", {})
    assert "responseJsonSchema" not in t.govdeler[0]["generationConfig"]


def test_sema_400_ile_reddedilirse_tek_semasiz_tekrar_ve_rapor():
    t = Tasiyici([(400, '{"error": {"message": "Invalid JSON payload: response_json_schema unsupported"}}'), _ok(), _ok()])
    g = _saglayici(t)
    sema = {"type": "object"}
    g.tamamla("i", "senaryo", {"yanit_semasi": sema})
    assert "responseJsonSchema" in t.govdeler[0]["generationConfig"]
    assert "responseJsonSchema" not in t.govdeler[1]["generationConfig"]
    assert g.sema_dusurulen == [{"etiket": "senaryo", "model": "gemini-m"}]
    g.tamamla("i", "senaryo", {"yanit_semasi": sema})                               # aynı modelde sonraki istek de şemasız
    assert "responseJsonSchema" not in t.govdeler[2]["generationConfig"] and len(t.govdeler) == 3


def test_semayla_ilgisiz_400_sema_dusurmez():
    t = Tasiyici([(400, '{"error": {"message": "API key not valid"}}')])
    g = _saglayici(t)
    with pytest.raises(Exception):
        g.tamamla("i", "senaryo", {"yanit_semasi": {"type": "object"}})
    assert g.sema_dusurulen == [] and len(t.govdeler) == 1


# ================================================================== otonom akış: şema bağlama + normalizasyon

class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.cagrilar, self.cagri_sayisi = list(yanitlar), [], 0

    def tamamla(self, istem, adim, baglam):
        self.cagrilar.append((adim, baglam))
        self.cagri_sayisi += 1
        y = self.yanitlar.pop(0)
        return y if isinstance(y, str) else json.dumps(y, ensure_ascii=False)


def test_shorts_senaryo_cagrisina_sema_baglanir_ve_sarmalayici_eksik_id_gecer(monkeypatch):
    """Gerçek koşudaki iki hata birlikte: {"senaryo": {...}} sarmalayıcısı + id'siz cümleler → ilk denemede geçer."""
    monkeypatch.setattr(ou, "senaryo_denetle", lambda s, ara, *a, **k: sozlesme.senaryo_denetle(s, ara))
    ham = {"senaryo": {k: v for k, v in _shorts(ids=False).items() if k not in ("surum", "konu", "format")}}
    s = Sahte([ham])
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    sen, gecmis = ou.senaryo_uret(s, k, ARA, [])
    assert s.cagri_sayisi == 1 and gecmis[0]["hatalar"] == []
    assert [c["id"] for c in sen["cumleler"]] == ["S1", "S2"] and "senaryo" not in sen
    assert sen["konu"] == k["kimlik"] and sen["surum"] == 1 and sen["format"] == "shorts"
    adim, baglam = s.cagrilar[0]
    assert adim == "senaryo" and baglam["yanit_semasi"] == ou.shorts_api_semasi()


def test_cok_anahtarli_sarmalayici_uc_denemede_acik_hata(monkeypatch):
    monkeypatch.setattr(ou, "senaryo_denetle", lambda s, ara, *a, **k: sozlesme.senaryo_denetle(s, ara))
    s = Sahte([{"senaryo": _shorts(), "aciklama": "x"}] * 3)
    with pytest.raises(ou.UretimHatasi) as e:
        ou.senaryo_uret(s, ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), ARA, [])
    assert "'senaryo' were unexpected" in str(e.value) and s.cagri_sayisi == 3


def test_uzun_taslak_ve_bolum_cagrilarina_sema_baglanir_sarmalayici_acilir():
    taslak = {"senaryo": {"baslik": "O", "bolumler": [
        {"baslik": b, "roller": r, "ozet": "o", "kartlar": [], "hedef_sn": 150}
        for b, r in (("A", ["kanca", "baglam"]), ("T", ["taraflar"]), ("Ö", ["savas_oncesi"]), ("S", ["savas"]),
                     ("N", ["sonuc"]), ("E", ["etkiler"]), ("K", ["kapanis"]))]}}
    s = Sahte([taslak])
    t, gecmis = ou.uzun_taslak_uret(s, ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun"), ARA)
    assert len(t["bolumler"]) == 7 and gecmis[0]["hatalar"] == []
    assert s.cagrilar[0][1]["yanit_semasi"] == ou.TASLAK_API_SEMASI
    import inspect
    kaynak = inspect.getsource(ou.uzun_senaryo_uret)
    assert '"yanit_semasi": BOLUM_API_SEMASI' in kaynak and "normalize_senaryo(json_ayikla(" in kaynak
