"""Faz-63c — normalize_senaryo(): küçük harfli ID (s1 → S1), kanca/final ↔ ilk/son cümle kimliği senkronu;
tartışmalı kaynaklar için ihtiyat kuralı (Shorts + uzun istem). Çevrimdışı; ağ ve Gemini YOK."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import anlati, sozlesme, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_63c", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
ARA = json.loads((PILOT / "arastirma.json").read_text())


def _c(i=None, metin="Bir cümle.", **ek):
    c = {"metin": metin, "kartlar": ["C1"], "niyet": {"tur": "3d", "aciklama": "x"}, **ek}
    if i is not None:
        c["id"] = i
    return c


def _shorts(cs, **ek):
    return {"surum": 1, "konu": "k", "format": "shorts", "baslik": "B", "kanca": "S1", "final": "S1",
            "ana_fikir": "Toplar savaşın kaderini belirledi.", "cumleler": cs, **ek}


def _ids(v):
    return [c.get("id") for c in v["cumleler"]]


# ================================================================== 1) küçük harfli ID

@pytest.mark.parametrize("girdi, beklenen", [
    (["s1", "s2"], ["S1", "S2"]),
    (["s12"], ["S12"]),
    (["S1", "s2", "S3"], ["S1", "S2", "S3"]),            # geçerli S1, S3 korunur
    (["s01"], ["S01"]),                                   # rakamlar aynen (şema ^S[0-9]+$ ile uyumlu)
])
def test_kucuk_harfli_id_buyuge(girdi, beklenen):
    assert _ids(ou.normalize_senaryo({"cumleler": [_c(i) for i in girdi]})) == beklenen


def test_cakisma_uretilmez_kucuk_harf_dokunulmadan_kalir_dogrulayici_yakalar():
    v = ou.normalize_senaryo(_shorts([_c("S1"), _c("s1"), _c("s1")]))
    assert _ids(v) == ["S1", "s1", "s1"]                                         # S1 zaten var → dönüşüm yok
    v = ou.normalize_senaryo(_shorts([_c("s1"), _c("s1")]))
    assert _ids(v) == ["S1", "s1"]                                               # ikincisi çakışırdı → olduğu gibi
    h = sozlesme.senaryo_denetle(v, ARA)
    assert any("s1" in x for x in h)                                             # açık hata sürer


def test_gecerli_ve_bicim_disi_idler_degismez():
    v = ou.normalize_senaryo({"cumleler": [_c("S7"), _c("x7"), _c("S"), _c("s1a"), _c(" s3")]})
    assert _ids(v) == ["S7", "x7", "S", "s1a", " s3"]


def test_eksik_id_atamasi_ile_uyumlu():
    v = ou.normalize_senaryo({"cumleler": [_c(), _c("s1"), _c(), _c("s3"), _c(None)]})
    # önce s1→S1, s3→S3; sonra eksikler çakışmasız en küçük boş: S2, S4, S5
    assert _ids(v) == ["S2", "S1", "S4", "S3", "S5"] and len(set(_ids(v))) == 5


def test_kucuk_harf_donusumu_eksik_atamayi_yaniltmaz():
    # eksik öğe önce gelse de 's1' dönüşümünden sonra S1 dolu sayılır → çakışma yok
    v = ou.normalize_senaryo({"cumleler": [_c(), _c("s1")]})
    assert _ids(v) == ["S2", "S1"]


# ================================================================== 2) kanca / final senkronu

def test_kanca_final_ilk_ve_son_cumle_kimligine_esitlenir():
    cs = [_c("S1", "İki ordu, tek kazanan."), _c("S2", "Ortada"), _c("S3", "Zafer Osmanlıların.")]
    v = ou.normalize_senaryo(_shorts(copy.deepcopy(cs), kanca="İki ordu, tek kazanan.", final="S2"))
    assert v["kanca"] == "S1" and v["final"] == "S3"
    assert [c["metin"] for c in v["cumleler"]] == [c["metin"] for c in cs] and _ids(v) == ["S1", "S2", "S3"]
    assert sozlesme.senaryo_denetle(v, ARA) == []


def test_kanca_final_eksikse_eklenir_kucuk_harf_ve_eksik_idden_sonra():
    s = _shorts([_c("s1"), _c(), _c("s3")])
    del s["kanca"], s["final"]
    v = ou.normalize_senaryo({"senaryo": s})
    assert (v["kanca"], v["final"]) == ("S1", "S3") and _ids(v) == ["S1", "S2", "S3"]


def test_kanca_final_kimlik_alanidir_metin_degil():
    """Şemada ve üretimde kanca/final cümle KİMLİĞİDİR: sozlesme kimlik listesinde arar, anlati cs[0]['id'] ile
    karşılaştırır, kurgu metni metin[senaryo['kanca']] ile çeker. Metin yazılsaydı üç denetim de kırılırdı."""
    pilot = json.loads((PILOT / "senaryo.json").read_text())
    assert pilot["kanca"] == pilot["cumleler"][0]["id"] and pilot["final"] == pilot["cumleler"][-1]["id"]
    metinli = dict(pilot, kanca=pilot["cumleler"][0]["metin"])
    assert any("kanca" in h and "cümlelerde yok" in h for h in sozlesme.senaryo_denetle(metinli, ARA))
    assert "metin[senaryo[\"kanca\"]]" in (KOK / "motor/uretim/kurgu.py").read_text()
    assert ou.normalize_senaryo(metinli)["kanca"] == pilot["cumleler"][0]["id"]


@pytest.mark.parametrize("cumleler", [
    [],
    [_c("S1"), {"id": "S2"}],                                # metin eksik
    [_c("S1"), _c("S2", "")],                                # metin boş
    [_c("S1"), "bozuk"],                                     # öğe dict değil
])
def test_bos_ya_da_bozuk_listede_icerik_uretilmez(cumleler):
    s = _shorts(copy.deepcopy(cumleler), kanca="X", final="Y")
    v = ou.normalize_senaryo(s)
    assert v["kanca"] == "X" and v["final"] == "Y" and v["cumleler"] == cumleler  # hiçbir alan doldurulmadı
    assert sozlesme.senaryo_denetle(v, ARA)                                      # doğrulayıcı hata verir


def test_cumleler_liste_degilse_dokunulmaz():
    v = ou.normalize_senaryo({"cumleler": "x", "kanca": "K"})
    assert v == {"cumleler": "x", "kanca": "K"}


def test_bolum_parcasinda_kanca_final_eklenmez():
    v = ou.normalize_senaryo({"cumleler": [_c("s1"), _c()]}, kanca_final=False)
    assert "kanca" not in v and "final" not in v and _ids(v) == ["S1", "S2"]


# ================================================================== idempotency, Shorts / uzun

@pytest.mark.parametrize("girdi", [
    {"cumleler": [_c("s1"), _c("S1"), _c(), _c("s12")]},
    {"senaryo": _shorts([_c("s2"), _c(), _c("s1")], kanca="metin")},
    {"cumleler": [_c("s1"), _c("s1")]},
    _shorts([]), _shorts([_c("S1"), {"id": "S2"}]),
])
def test_idempotent(girdi):
    for kf in (True, False):
        bir = ou.normalize_senaryo(copy.deepcopy(girdi), kanca_final=kf)
        assert ou.normalize_senaryo(copy.deepcopy(bir), kanca_final=kf) == bir


def test_shorts_ve_uzun_ortak_adaptor_ile_dogrulayicilardan_gecer():
    olc = {f"S{i}": {"sure_sn": 5.0} for i in range(1, 50)}
    # Shorts: küçük harf + metin kanca → şema geçer
    sh = _shorts([_c("s1", "İki ordu, tek kazanan?"), _c("s2", "Zafer.")], kanca="İki ordu", final="s2")
    assert sozlesme.senaryo_denetle(ou.normalize_senaryo(sh), ARA) == []
    # uzun: aynı adaptör; kanca/final anlati.uzun_denetle'nin ilk/son cümle şartını sağlar
    roller = veri.kural("uzun")["bolum"]["roller"]
    bolumler = [{"id": f"B{i + 1}", "baslik": f"b{i}", "roller": [r]} for i, r in enumerate(roller[:7])]
    bolumler[-1]["roller"] = ["etkiler", "kapanis"]
    cs = [_c(f"s{i + 1}", f"Belge {i} anlatımı " + " ".join(f"k{i}x{j}" for j in range(8)), bolum=f"B{i // 6 + 1}")
          for i in range(42)]
    cs[0]["metin"] = "Yalnızca 1 gün süren savaş neyi değiştirdi?"
    uz = {"surum": 1, "konu": "k", "format": "uzun", "baslik": "U", "bolumler": bolumler, "cumleler": cs,
          "kanca": "x", "final": "y"}
    n = ou.normalize_senaryo(uz)
    assert (n["kanca"], n["final"]) == ("S1", "S42")
    h, _ = anlati.uzun_denetle(n, olc)
    assert not [x for x in h if "kanca ilk" in x or "final son" in x]
    assert sozlesme.senaryo_denetle(n, ARA) == []


def test_uzun_birlesik_senaryo_ve_bolum_cagrisi_adaptoru_kullanir():
    import inspect
    k = inspect.getsource(ou.uzun_senaryo_uret)
    assert "s = normalize_senaryo(kur(bolum_cs))" in k and "kanca_final=False" in k
    assert "normalize_senaryo(s)" in inspect.getsource(ou.senaryo_uret)


# ================================================================== 3) tartışmalı kaynak ihtiyatı

ARA_T = {"kartlar": [{"id": "C1", "guven": "kesin", "iddia": "a"}, {"id": "C2", "guven": "tartismali", "iddia": "b"},
                     {"id": "C3", "guven": "makul", "iddia": "c"}, {"id": "C4", "guven": "belirsiz", "iddia": "d"}]}


def test_ihtiyat_kurali_icerigi():
    k = ou.kaynak_ihtiyati_kurali(ARA_T)
    assert "KESİN HÜKÜM KURMA" in k and '"bazı kaynaklara göre"' in k and '"rivayet"' in k
    assert "rivayet edilir" in k and "Kaynaklara göre" in k
    assert "tartışmalı kartlar: C2, C4" in k and "C1" not in k.split("tartışmalı kartlar:")[1]
    assert "gereksiz yere belirsizleştirme" in k and "'kesin' ve 'makul'" in k and "ihtiyat ifadesi KULLANMA" in k
    assert "Bu araştırmada tartışmalı kart yok" in ou.kaynak_ihtiyati_kurali({"kartlar": ARA_T["kartlar"][:1]})


def test_ihtiyat_ifadeleri_dogrulayicinin_kabul_ettikleri():
    """İstemde önerilen her ifade sozlesme'nin temkin denetiminden geçer (aksi halde üretim kendi kuralına takılırdı)."""
    temkin = veri.kural("dil_tr")["temkin_ifadeleri"]
    k = ou.kaynak_ihtiyati_kurali(ARA_T)
    satir = k.split("AYNEN içersin: ")[1].split(" (ör.")[0]
    oneriler = [x.strip().strip('"') for x in satir.split(",")]
    assert oneriler and all(x in temkin for x in oneriler)
    ara = {"kartlar": [{"id": "C2", "guven": "tartismali", "iddia": "b", "kaynaklar": []}]}
    for ornek in ("Bazı kaynaklara göre ordu yüz bin kişiydi.", "Ordunun yüz bin kişi olduğu rivayet edilir.",
                  "Kaynaklara göre ordu yüz bin kişiydi."):
        s = _shorts([_c("S1", ornek, kartlar=["C2"])])
        assert not [h for h in sozlesme.senaryo_denetle(s, ara) if "kesin dille" in h], ornek
    kesin = _shorts([_c("S1", "Ordu yüz bin kişiydi.", kartlar=["C2"])])
    assert any("kesin dille" in h for h in sozlesme.senaryo_denetle(kesin, ara))


def test_ihtiyat_kurali_shorts_ve_uzun_istemlerinde():
    class Sahte:
        def __init__(self):
            self.istem = None

        def tamamla(self, istem, adim, baglam):
            self.istem = istem
            return json.dumps(_shorts([_c("S1")]))
    s = Sahte()
    ara = dict(ARA, kartlar=ARA["kartlar"] + [{"id": "C9", "guven": "tartismali", "iddia": "x", "kaynaklar": ["K1"]}])
    with pytest.raises(Exception):
        ou.senaryo_uret(s, ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), ara, [], deneme=1, olc=lambda cs: {})
    assert "KAYNAK İHTİYATI" in s.istem and "tartışmalı kartlar: C9" in s.istem
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    i = ou.bolum_istemi(konu, ara, {"bolumler": []}, {"id": "B1", "baslik": "b", "roller": ["kanca"]}, [], [], [], {},
                        100, [], True, False)
    assert "KAYNAK İHTİYATI" in i and "tartışmalı kartlar: C9" in i
