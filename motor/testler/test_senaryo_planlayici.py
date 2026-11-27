"""Otonom araştırma–senaryo–sahne planlayıcısı: uzun belgesel, Shorts, Validation Gate, hedefli onarım, fail-safe.
Ağsız: MockLLMProvider (bütün kayıtlar mock_ önekli ve sentetik_mock:true)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from motor.orkestrasyon import senaryo_planlayici as sp
from motor.orkestrasyon.llm import MockLLMProvider

KONU = "Örnek Kale Kuşatması"


@pytest.fixture(scope="module")
def uzun():
    return sp.plan_uret(KONU, "uzun", MockLLMProvider())


@pytest.fixture(scope="module")
def shorts():
    return sp.plan_uret(KONU, "shorts", MockLLMProvider())


def _ardisik_en_cok(sahneler):
    en, n = 1, 1
    for a, b in zip(sahneler, sahneler[1:]):
        n = n + 1 if a["gorsel_tur"] == b["gorsel_tur"] else 1
        en = max(en, n)
    return en


# ------------------------------------------------------------------ uzun belgesel

def test_uzun_plan_uretime_hazir_ve_kurallara_uyar(uzun):
    r = uzun
    assert r["durum"] == "uretime_hazir" and r["render_baslatildi"] is False
    p = r["plan"]
    assert p["format"]["en_boy"] == "16:9" and p["format"]["cozunurluk"] == [1920, 1080]
    assert 900 <= r["ozet"]["toplam_sn"] <= 1200
    sira = ["hook", "baglam", "catisma", "donum_noktasi", "sonuc"]
    idx = [sira.index(s["bolum"]) for s in p["sahneler"]]
    assert idx == sorted(idx) and set(idx) == set(range(5))
    assert _ardisik_en_cok(p["sahneler"]) <= 2
    for s in p["sahneler"]:
        assert 3 <= s["sure_sn"] <= 20
        if s["sure_sn"] < 6:
            assert s["ritim"] == "vurgu"
        if s["sure_sn"] > 12:
            assert s["gorsel_tur"] == "harita" and s["ritim"] == "kritik_harita"
        if s["gorsel_tur"] == "harita":
            assert s["cografi_amac"].strip()
        if s["gorsel_tur"] == "gorsel25d":
            assert s["arama_sorgulari"] and all(q.strip() for q in s["arama_sorgulari"])
        if s["gorsel_tur"] == "sahne3d":
            assert s["uc_boyut_gerekcesi"].strip()
        assert s["ton"] in ("ciddi", "gerilimli", "epos") and s["gecis_efekti"] in ("boom", "yok")
        assert s["ambiyans"] in ("ruzgar", "kusatma", "saray", "sessiz")
    d = r["ozet"]["dagilim"]
    assert abs(d["harita"] - 0.4) < 0.15 and abs(d["gorsel25d"] - 0.4) < 0.15 and abs(d["sahne3d"] - 0.2) < 0.15


def test_her_sahnenin_dayanagi_var_ve_mock_gercek_kaynak_gibi_gosterilmez(uzun):
    r = uzun
    havuz = {k["id"]: k for k in r["havuz"]["kayitlar"]}
    for k in havuz.values():
        assert k["id"].startswith("mock_") and k["sentetik_mock"] is True
        assert all(c["id"].startswith("mock_") and c["sentetik_mock"] is True for c in k["kaynaklar"])
    for s in r["plan"]["sahneler"]:
        assert s["dayanak_ids"] and all(i in havuz for i in s["dayanak_ids"])
        assert s["guven_durumu"] == "sentetik_mock"          # "kaynaklarla_destekleniyor" DENMEZ
    assert r["plan"]["sentetik_mock"] is True and r["plan"]["yayin_icin_uygun"] is False


def test_bilgi_havuzu_dogrulanmis_tartismali_belirsiz_ayrilir(uzun):
    h = uzun["havuz"]
    assert "mock_013" in h["tartismali"] and "mock_022" in h["belirsiz"]
    assert not set(h["dogrulanmis"]) & (set(h["tartismali"]) | set(h["belirsiz"]))
    yillar = [o["yil"] for o in h["kronoloji"] if o["yil"] is not None]
    assert yillar == sorted(yillar)
    # tartışmalı/belirsiz dayanaklı sahneler temkinli ve 'kesin' değil
    for s in uzun["plan"]["sahneler"]:
        if set(s["dayanak_ids"]) & (set(h["tartismali"]) | set(h["belirsiz"])):
            assert s["kesinlik"] != "kesin" and any(t in s["anlatim"].lower() for t in sp.temkin_ifadeleri())


def test_celiskili_yillar_tartismaliya_duser():
    v = MockLLMProvider()._arastirma({"konu": KONU})
    v["kayitlar"][0]["yil"] = 1390   # aynı olay için doğrulanmış iki farklı yıl
    h = sp.bilgi_havuzu(v)
    assert h["celiskiler"] and h["celiskiler"][0]["olay_id"] == "mock_olay_1"
    assert "mock_001" in h["tartismali"] and "mock_001" not in h["dogrulanmis"]


# ------------------------------------------------------------------ Shorts (ayrı üretim)

def test_shorts_ayri_uretilir_hook_ilk_3sn_hareketli_tek_fikir(shorts):
    r = shorts
    assert r["durum"] == "uretime_hazir"
    p = r["plan"]
    assert p["format"]["en_boy"] == "9:16" and p["format"]["cozunurluk"] == [1080, 1920]
    assert p["uretim"] == "ayri" and 50 <= r["ozet"]["toplam_sn"] <= 60
    s0 = p["sahneler"][0]
    assert s0["hook"] is True and s0["bolum"] == "hook"
    t = 0
    for s in p["sahneler"]:
        if t < 3:
            assert s["gorsel_tur"] in ("gorsel25d", "sahne3d") and s["hareketli"] is True
        t += s["sure_sn"]
    havuz = {k["id"]: k for k in r["havuz"]["kayitlar"]}
    assert {havuz[i]["olay_id"] for s in p["sahneler"] for i in s["dayanak_ids"]} == {p["ana_olay_id"]}
    bas = 0
    for s in p["sahneler"]:
        if s["bolum"] == "kapanis":
            assert 35 <= bas <= 45
            break
        bas += s["sure_sn"]
    assert _ardisik_en_cok(p["sahneler"]) <= 2


def test_shorts_kendi_istemleriyle_uretilir_uzundan_kesit_degil():
    m = MockLLMProvider()
    sp.plan_uret(KONU, "shorts", m)
    adimlar = [c["adim"] for c in m.cagrilar]
    assert adimlar == ["arastirma", "anlati", "sahne_plani"]
    assert "Shorts" in m.cagrilar[2]["istem"] and "9:16" in m.cagrilar[2]["istem"]


# ------------------------------------------------------------------ Validation Gate: tek tek ihlaller

def _kapi(rapor, mod, boz):
    p = copy.deepcopy(rapor["plan"])
    for a in ("format", "sentetik_mock", "yayin_icin_uygun", "ozet", "uyarilar", "kaynakca"):
        p.pop(a, None)
    for s in p["sahneler"]:
        s.pop("guven_durumu", None)
    boz(p)
    e, u, _ = sp.plan_dogrula(p, rapor["havuz"], mod)
    return {h["kod"] for h in e}, e, u


def _ilk(p, tur):
    return next(i for i, s in enumerate(p["sahneler"]) if s["gorsel_tur"] == tur)


@pytest.mark.parametrize("ad,boz,kod", [
    ("dayanak_yok", lambda p: p["sahneler"][5].__setitem__("dayanak_ids", ["mock_999"]), "dayanak_yok"),
    ("dayanaksiz", lambda p: p["sahneler"][5].__setitem__("dayanak_ids", []), "dayanaksiz"),
    ("uydurma_sayi", lambda p: p["sahneler"][7].__setitem__("anlatim", p["sahneler"][7]["anlatim"] + " Ordu 12000 kişiydi."), "dayanaksiz_sayi"),
    ("ardisik_3", lambda p: [p["sahneler"][i].__setitem__("gorsel_tur", "sahne3d") or p["sahneler"][i].__setitem__("uc_boyut_gerekcesi", "x")
                             for i in (10, 11, 12)], "ardisik_tekrar"),
    ("cografi_amac", lambda p: p["sahneler"][_ilk(p, "harita")].pop("cografi_amac"), "cografi_amac_yok"),
    ("cografi_amac_icerksiz", lambda p: p["sahneler"][_ilk(p, "harita")].__setitem__("cografi_amac", "harita"), "cografi_amac_yok"),
    ("sorgu_bos", lambda p: p["sahneler"][_ilk(p, "gorsel25d")].__setitem__("arama_sorgulari", []), "sorgu_yok"),
    ("3d_gerekce", lambda p: p["sahneler"][_ilk(p, "sahne3d")].pop("uc_boyut_gerekcesi"), "3d_gerekcesiz"),
    ("kisa_vurgusuz", lambda p: p["sahneler"][2].update(sure_sn=4, ritim="normal"), "kisa_sahne"),
    ("uzun_haritasiz", lambda p: p["sahneler"][_ilk(p, "gorsel25d")].update(sure_sn=15), "uzun_sahne"),
    ("tekrar_sahne", lambda p: p["sahneler"][9].__setitem__("anlatim", p["sahneler"][8]["anlatim"]), "tekrar_sahne"),
    ("tekrar_katki", lambda p: p["sahneler"][9].__setitem__("katki", p["sahneler"][8]["katki"]), "tekrar_katki"),
    ("toplam_sure", lambda p: [s.__setitem__("sure_sn", 6) for s in p["sahneler"] if s["ritim"] == "normal"] and
     [s.update(ritim="normal", sure_sn=6) for s in p["sahneler"]], "toplam_sure"),
    ("ton_enum", lambda p: p["sahneler"][3].__setitem__("ton", "komik"), "enum"),
    ("yapi_sirasi", lambda p: p["sahneler"][-1].__setitem__("bolum", "hook"), "yapi_sirasi"),
    ("kesit", lambda p: p["sahneler"][3].__setitem__("uzun_kesit_ref", "x"), "kesit"),
])
def test_kapi_uzun_ihlalleri_yakalar(uzun, ad, boz, kod):
    kodlar, e, _ = _kapi(uzun, "uzun", boz)
    assert kod in kodlar, (ad, [(h["yol"], h["kod"]) for h in e[:5]])
    assert all(h["yol"] is not None and h["asama"] in ("sema", "kronoloji_dayanak", "sure_ritim", "gorsel_sorgu") for h in e)


def test_kapi_tartismali_kesin_sunulamaz_ve_temkin_ister(uzun):
    h = uzun["havuz"]
    i = next(i for i, s in enumerate(uzun["plan"]["sahneler"]) if "mock_013" in s["dayanak_ids"])

    def boz(p):
        p["sahneler"][i]["kesinlik"] = "kesin"
        p["sahneler"][i]["anlatim"] = p["sahneler"][i]["anlatim"].replace("Bazı kaynaklara göre ", "")
    kodlar, _, _ = _kapi(uzun, "uzun", boz)
    assert {"tartismali_kesin_sunulmus", "temkin_yok"} <= kodlar
    assert "mock_013" in h["tartismali"]


def test_kapi_kronoloji_geri_gidemez_geri_donus_isaretiyle_gecer(uzun):
    p = uzun["plan"]["sahneler"]
    j = next(i for i, s in enumerate(p) if s["bolum"] == "donum_noktasi")
    erken = next(s["dayanak_ids"] for s in p if s["bolum"] == "baglam")

    def boz(pl):
        pl["sahneler"][j]["dayanak_ids"] = list(erken)
        pl["sahneler"][j]["anlatim"] = p[0]["anlatim"].split("Bu sahne")[0]   # sayılar dayanakla uyumlu kalsın
        pl["sahneler"][j]["anlatim"] = next(s["anlatim"] for s in p if s["dayanak_ids"] == erken).replace("[", "[Z")
    kodlar, _, _ = _kapi(uzun, "uzun", boz)
    assert "kronoloji_geri" in kodlar
    kodlar2, _, _ = _kapi(uzun, "uzun", lambda pl: (boz(pl), pl["sahneler"][j].__setitem__("geri_donus", True)))
    assert "kronoloji_geri" not in kodlar2


def test_dagilim_kota_degil_uyari(uzun):
    def boz(p):   # harita ağırlıklı ama ardışık kuralına uyan bir dizilim
        for i, s in enumerate(p["sahneler"]):
            t = ["harita", "harita", "gorsel25d"][i % 3]
            s["gorsel_tur"] = t
            s["hareketli"] = t != "harita"
            s.setdefault("cografi_amac", "kuvvetlerin konumu ve hareket yönü")
            s.setdefault("arama_sorgulari", ["örnek arama"])
            if s["sure_sn"] > 12:
                s["ritim"] = "kritik_harita" if t == "harita" else s["ritim"]
                if t != "harita":
                    s["sure_sn"], s["ritim"] = 12, "atmosfer"
    kodlar, e, u = _kapi(uzun, "uzun", boz)
    assert not e, [(h["yol"], h["kod"]) for h in e[:5]]
    assert any("dağılım" in x for x in u)


@pytest.mark.parametrize("ad,boz,kod", [
    ("ilk_harita", lambda p: p["sahneler"][0].update(gorsel_tur="harita", hareketli=False, cografi_amac="kuvvetlerin konumu ve yönü"), "ilk_3sn_duragan"),
    ("hook_isaretsiz", lambda p: p["sahneler"][0].update(hook=False), "hook_yok"),
    ("baska_olay", lambda p: p["sahneler"][4].update(dayanak_ids=["mock_001"], anlatim="Bazı kaynaklara göre ayrı bir olay [Q].",
                                                    kesinlik="tartismali"), "tek_fikir"),
    ("uzun_sure", lambda p: p["sahneler"][3].update(sure_sn=20), "toplam_sure"),
    ("kapanis_gec", lambda p: (p["sahneler"][1].update(sure_sn=10), p["sahneler"][2].update(sure_sn=9)), "kapanis_zamani"),
    ("ana_fikir_yok", lambda p: p.update(ana_fikir=""), "eksik"),
    ("kesit", lambda p: p.update(uretim="uzundan_kesit"), "ayri_uretim"),
])
def test_kapi_shorts_ihlalleri_yakalar(shorts, ad, boz, kod):
    kodlar, e, _ = _kapi(shorts, "shorts", boz)
    assert kod in kodlar, (ad, [(h["yol"], h["kod"]) for h in e[:5]])


# ------------------------------------------------------------------ hedefli onarım, en çok 3 deneme, fail-safe

def _boz_plan(v):
    i = next(i for i, s in enumerate(v["sahneler"]) if s["gorsel_tur"] == "harita")
    v["sahneler"][i].pop("cografi_amac")
    j = next(i for i, s in enumerate(v["sahneler"]) if s["gorsel_tur"] == "gorsel25d")
    v["sahneler"][j]["arama_sorgulari"] = []


def test_hedefli_onarim_yalnizca_hatali_alanlari_duzeltir_gecerli_sahneleri_korur():
    m = MockLLMProvider(bozulmalar={"sahne_plani": [_boz_plan]})
    gonderilen = []
    r = sp.plan_uret(KONU, "uzun", m, uretime_gonder=gonderilen.append)
    assert r["durum"] == "uretime_hazir" and len(gonderilen) == 1 and r["render_baslatildi"] is True
    d = r["katmanlar"]["4_5_sahne_plani_ve_kapi"]["denemeler"]
    assert [x["tur"] for x in d] == ["tam_uretim", "hedefli_onarim"] and d[0]["hata_sayisi"] == 2
    onarim = [c for c in m.cagrilar if c["adim"] == "onarim"]
    assert len(onarim) == 1 and sp.ONARIM_TALIMATI in onarim[0]["istem"]
    assert "cografi_amac" in onarim[0]["istem"] and "arama_sorgulari" in onarim[0]["istem"]
    # tam senaryo yeniden yazdırılmadı: sahne_plani tam üretimi tek sefer
    assert sum(1 for c in m.cagrilar if c["adim"] == "sahne_plani") == 1
    dogru = m._dogru["sahne_plani"]
    son = copy.deepcopy(r["plan"])
    for s in son["sahneler"]:
        s.pop("guven_durumu")
    assert son["sahneler"] == dogru["sahneler"]   # geçerli sahneler aynen korundu


def test_izinsiz_alan_yamasi_reddedilir_ve_fail_safe():
    m = MockLLMProvider(bozulmalar={"sahne_plani": [_boz_plan]}, onarim_kipi="alan_disi")
    gonderilen = []
    r = sp.plan_uret(KONU, "uzun", m, uretime_gonder=gonderilen.append)
    assert r["durum"] == "durduruldu" and r["durdugu_katman"] == "4_5_sahne_plani_ve_kapi"
    assert gonderilen == [] and r["render_baslatildi"] is False
    d = r["katmanlar"]["4_5_sahne_plani_ve_kapi"]["denemeler"]
    assert len(d) == 3 and all(x.get("yama_reddedildi") for x in d[1:])
    assert any(h["kod"] == "izinsiz_yama" for h in d[1]["hatalar"])


def test_onarilamayan_cikti_en_cok_3_denemede_durur_render_baslamaz():
    m = MockLLMProvider(bozulmalar={"sahne_plani": [_boz_plan]}, onarim_kipi="hicbir")
    cagrildi = []
    r = sp.plan_uret(KONU, "uzun", m, uretime_gonder=cagrildi.append)
    assert r["durum"] == "durduruldu" and cagrildi == [] and r["render_baslatildi"] is False
    plan_cagri = [c for c in m.cagrilar if c["adim"] in ("sahne_plani", "onarim")]
    assert len(plan_cagri) == 3                                    # sonsuz döngü yok
    assert {h["kod"] for h in r["hatalar"]} == {"cografi_amac_yok", "sorgu_yok"}
    assert all({"asama", "yol", "kod", "mesaj"} <= set(h) for h in r["hatalar"])
    assert "fail-safe" in r["ozet_hata"] and "plan" not in r


def test_bozuk_json_tam_uretimle_yeniden_istenir_ve_sinirli():
    r = sp.plan_uret(KONU, "shorts", MockLLMProvider(ham_bozuk={"sahne_plani": 1}))
    d = r["katmanlar"]["4_5_sahne_plani_ve_kapi"]["denemeler"]
    assert r["durum"] == "uretime_hazir" and d[0]["hatalar"][0]["kod"] == "json_parse" and len(d) == 2
    r2 = sp.plan_uret(KONU, "shorts", MockLLMProvider(ham_bozuk={"anlati": 5}))
    assert r2["durum"] == "durduruldu" and r2["durdugu_katman"] == "3_anlati"
    assert len(r2["katmanlar"]["3_anlati"]["denemeler"]) == 3 and "4_5_sahne_plani_ve_kapi" not in r2["katmanlar"]


def test_shorts_hook_hatasi_onarilir():
    def boz(v):
        v["sahneler"][0].update(hook=False)
    r = sp.plan_uret(KONU, "shorts", MockLLMProvider(bozulmalar={"sahne_plani": [boz]}))
    assert r["durum"] == "uretime_hazir" and r["plan"]["sahneler"][0]["hook"] is True
    assert len(r["katmanlar"]["4_5_sahne_plani_ve_kapi"]["denemeler"]) == 2


# ------------------------------------------------------------------ sentetik / gerçek ayrımı

def test_gercek_saglayici_mock_kimligi_tasiyamaz_mock_isaretsiz_olamaz():
    v = MockLLMProvider()._arastirma({"konu": KONU})
    assert any(h["kod"] == "sentetik_gercek_gibi" for h in sp.arastirma_dogrula(v, sentetik=False))
    v2 = copy.deepcopy(v)
    v2["kayitlar"][0]["sentetik_mock"] = False
    assert any(h["kod"] == "sentetik_isaretsiz" for h in sp.arastirma_dogrula(v2, sentetik=True))
    v3 = copy.deepcopy(v)
    v3["kayitlar"][0]["kaynaklar"] = []
    assert any(h["kod"] == "kaynaksiz_dogrulanmis" for h in sp.arastirma_dogrula(v3, sentetik=True))
    assert sp.arastirma_dogrula(v, sentetik=True) == []


def test_cli_mocksuz_gercek_saglayici_yok_diye_acik_soyler(capsys):
    assert sp.main([KONU, "uzun"]) == 2
    assert "Gerçek LLM sağlayıcısı henüz bağlı değil" in capsys.readouterr().out


def test_orkestrasyon_konu_kelimesi_yok_ve_korunan_moduller_ithal_edilmez():
    kok = Path(sp.__file__).parent
    for f in kok.glob("*.py"):
        t = f.read_text().lower()
        assert not re.search(r"roma|lejyon|aquil|kartal|carrhae|harran|crassus|augustus|osmanl|akkoyunlu|bizans|otlukbeli", t), f
        assert not re.search(r"import .*(kurgu|harita|planlayici|kaos\.sinema)|from kaos|from motor\.uretim import (kurgu|harita|planlayici)", t), f
    json.dumps(sp.kurallar())
