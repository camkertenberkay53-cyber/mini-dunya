"""Faz 4 kontrol noktası 2 kabul testleri: kaynak takibi, Shorts anlatı yapısı (ölçülen seslendirme), sahne bölücü,
çekim planlayıcı, çeşitlilik ve benzer çekim tespiti, sahne-anlatım uyumu, pilotun uçtan uca planlanması."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from motor.uretim import (anlati, arastirma, cesitlilik, plan_denetim, planlayici, sahne_bolucu, uretim_hatti, uyum,
                          veri)

URETIM = Path(__file__).resolve().parents[1] / "uretim"
PILOT = URETIM / "pilotlar" / "roma-lejyon-kartali"


def _y(ad):
    return json.loads((PILOT / f"{ad}.json").read_text())


@pytest.fixture(scope="module")
def pilot():
    r = uretim_hatti.planla(PILOT)
    return r, json.loads((PILOT / "cekim_plani.json").read_text())


# ---------------------------------------------------------------- konudan bağımsızlık

def test_uretim_kodunda_konuya_ozel_ifade_yok():
    """Konu yalnızca veri dosyalarında yaşar: üretim kodunda dönem, kişi, yer ya da konu adı geçmez."""
    yasak = re.compile(r"roma|lejyon|aquil|kartal|carrhae|harran|crassus|augustus|osmanl|akkoyunlu|bizans|otlukbeli", re.I)
    for p in list(URETIM.glob("*.py")) + [URETIM.parent / "godot" / "sahneler" / x for x in ("cekim.gd", "ortam.gd")]:
        bulunan = yasak.findall(p.read_text())
        assert not bulunan, f"{p.name}: {set(bulunan)}"


# ---------------------------------------------------------------- kaynak takibi

def test_kesin_kart_tek_kaynakla_olamaz():
    a = _y("arastirma")
    assert arastirma.kart_denetle(a) == []
    b = copy.deepcopy(a)
    b["kartlar"][0]["kaynaklar"] = b["kartlar"][0]["kaynaklar"][:1]
    assert any("'kesin' için" in h for h in arastirma.kart_denetle(b))


def test_ikincil_kaynakta_baglanti_zorunlu():
    b = copy.deepcopy(_y("arastirma"))
    del b["kaynaklar"][1]["url"]
    assert any("bağlantı" in h for h in arastirma.kart_denetle(b))


def test_kaynak_izi_her_olgusal_cumleyi_kaynaga_baglar():
    iz = arastirma.kaynak_izi(_y("senaryo"), _y("arastirma"))
    for satir in iz:
        if satir["olgusal"]:
            assert satir["kartlar"] and all(k.get("kaynaklar") for k in satir["kartlar"]), satir


def test_pilot_tartismali_ve_belirsiz_kartlari_kesin_dille_kullanmaz():
    """KN3'te değişti: KN2'de pilot hiç tartışmalı kart kullanmıyordu ve test bunu arıyordu. Yönetim S7'de Tiberius'un
    rolünün anlatılmasını istedi; bu bilgi tek antik kaynağa dayandığı için 'tartışmalı' kartla ve temkinli dille
    girdi. Test artık asıl kuralı denetler: tartışmalı/belirsiz karta dayanan her cümle temkin ifadesi taşır ve
    en az bir cümle bu sınamadan gerçekten geçer (kural boşta kalmaz)."""
    a, s = _y("arastirma"), _y("senaryo")
    guven = {c["id"]: c["guven"] for c in a["kartlar"]}
    temkin = veri.kural("dil_tr")["temkin_ifadeleri"]
    sinanan = 0
    for c in s["cumleler"]:
        if any(guven[k] in ("belirsiz", "tartismali") for k in c["kartlar"]):
            sinanan += 1
            assert any(t in c["metin"].lower() for t in temkin), c["id"]
    assert sinanan >= 1


# ---------------------------------------------------------------- anlatı yapısı

def _sureler(s, kanca=1.5):
    return {c["id"]: {"sure_sn": kanca if i == 0 else 2.5} for i, c in enumerate(s["cumleler"])}


def test_kanca_iki_saniyeyi_asamaz_ve_merak_tasimali():
    s = _y("senaryo")
    assert anlati.shorts_denetle(s, _sureler(s))[0] == []
    assert any("kanca seslendirmesi" in h for h in anlati.shorts_denetle(s, _sureler(s, 2.4))[0])
    s2 = copy.deepcopy(s)
    s2["cumleler"][0]["metin"] = "Bu bir lejyon hikâyesi."
    assert any("merak" in h for h in anlati.shorts_denetle(s2, _sureler(s2))[0])


def test_anlati_sirasi_ve_final():
    s = copy.deepcopy(_y("senaryo"))
    s["cumleler"][2]["amac"] = "donum"   # dönüm noktası olaydan önce gelemez
    assert any("sırasını bozuyor" in h for h in anlati.shorts_denetle(s, _sureler(s))[0])
    s = copy.deepcopy(_y("senaryo"))
    s["cumleler"][-1]["amac"] = "gerilim"
    assert any("final son cümle" in h for h in anlati.shorts_denetle(s, _sureler(s))[0])


def test_cok_uzun_cumle_reddedilir():
    s = copy.deepcopy(_y("senaryo"))
    s["cumleler"][1]["metin"] = " ".join(["kelime"] * 20)
    assert any("kelime" in h for h in anlati.shorts_denetle(s, _sureler(s))[0])


# ---------------------------------------------------------------- sahne bölücü

def test_zaman_cizelgesi_ardisik_ve_uzun_cumle_bolunur():
    s = _y("senaryo")
    sure = _sureler(s)
    sure[s["cumleler"][3]["id"]]["sure_sn"] = 6.0
    z = sahne_bolucu.zaman_cizelgesi(s, sure)
    for a, b in zip(z, z[1:]):
        assert a["goruntu_son_sn"] == b["goruntu_bas_sn"]
        assert b["ses_bas_sn"] >= a["ses_bas_sn"] + a["ses_sure_sn"]
    t = sahne_bolucu.cekimlere_bol(s, z)
    assert sum(1 for x in t if x["cumle"] == s["cumleler"][3]["id"]) == 2
    assert abs(sum(x["sure_sn"] for x in t) - sahne_bolucu.toplam_sure(z)) < 0.01


# ---------------------------------------------------------------- planlayıcı

def test_tek_nesne_tasiyan_kalabaliga_katilmaz():
    n = {"tur": "3d", "roller": [{"rol": "piyade", "adet": 8}], "eylem": "yuruyus", "mesafe": "uzak"}
    o, _ = planlayici.oyuncu_sec(n, "roma-cumhuriyet")
    assert o and not any(planlayici._sancakli(x["takim"]) for x in o)


def test_olmayan_rol_ve_eylem_uydurulmaz():
    for n in ({"tur": "3d", "roller": [{"rol": "suvari"}], "eylem": "binicilik", "mesafe": "uzak"},
              {"tur": "3d", "roller": [{"rol": "isci_sivil"}], "eylem": "tamir", "mesafe": "uzak"}):
        o, eksik = planlayici.oyuncu_sec(n, "roma-cumhuriyet")
        assert not o and eksik


def test_planlayici_yakin_plan_kurmaz(pilot):
    _, plan = pilot
    den = plan_denetim.denetle(plan)
    assert all(x["olcum"].get("kamera_plani_olculen") in ("orta", "uzak", None) for x in den["cekimler"].values())


def test_cekim_turu_onceki_hareketi_tekrarlamaz():
    onceki = [{"tur": "yan_takip", "hareket": "takip", "yukseklik": "goz", "aci_kovasi": "yan"}]
    a = planlayici.cekim_turu_adaylari("orta", True, onceki, 1)
    assert veri.kural("kamera")["cekimler"][a[0]]["hareket"] != "takip"


def test_2d_niyet_eksik_olarak_raporlanir():
    t = {"id": "X1", "cumle": "S1", "sure_sn": 2.0, "niyet": {"tur": "harita", "metin": "harita"}, "amac": "olay"}
    c, eksik, _ = planlayici.cekim_kur(t, "roma-cumhuriyet", 0.5625, [], 1)
    assert c["tur"] == "harita" and any("2D" in e for e in eksik)


# ---------------------------------------------------------------- çeşitlilik ve benzer çekim

def test_ardisik_ayni_hareket_ve_benzer_cekim_reddedilir(pilot):
    _, plan = pilot
    den = plan_denetim.denetle(plan)
    assert cesitlilik.denetle(plan, den)[0] == []
    p = copy.deepcopy(plan)
    p["cekimler"][2]["meta"]["hareket"] = p["cekimler"][1]["meta"]["hareket"]
    assert any("ardışık" in h for h in cesitlilik.denetle(p, den)[0])
    p = copy.deepcopy(plan)
    p["cekimler"][5]["meta"] = dict(p["cekimler"][2]["meta"])
    h = cesitlilik.denetle(p, den)[0]
    assert any("benzer çekim" in x for x in h) or any("ardışık" in x for x in h)


def test_az_cesitlilik_reddedilir(pilot):
    _, plan = pilot
    den = plan_denetim.denetle(plan)
    p = copy.deepcopy(plan)
    for c in p["cekimler"]:
        c["meta"]["hareket"] = "sabit" if int(c["id"][1]) % 2 else "takip"
    assert any("farklı hareket" in h or "%" in h for h in cesitlilik.denetle(p, den)[0])


# ---------------------------------------------------------------- sahne-anlatım uyumu

def test_uyum_nesne_eylem_ve_mesafe_ihlallerini_yakalar(pilot):
    _, plan = pilot
    s = _y("senaryo")
    assert uyum.denetle(s, plan, plan_denetim.denetle(plan))[0] == []
    p = copy.deepcopy(plan)
    c = next(x for x in p["cekimler"] if x["id"] == "S1")
    c["karakterler"][0]["takim"] = "rom_lejyoner_pilum"        # kartal taşımayan
    c["karakterler"][0]["animasyon"] = "Walk_Formal_Loop"      # bekleme değil
    c["karakterler"][0]["hiz_m_sn"] = 0.817
    h = uyum.denetle(s, p, plan_denetim.denetle(p))[0]
    assert any("aquila" in x for x in h) and any("eylem" in x for x in h)


# ---------------------------------------------------------------- pilot uçtan uca

def test_pilot_plani_butun_denetimlerden_gecer(pilot):
    r, plan = pilot
    assert r["gecti"], {k: v for k, v in r["hatalar"].items() if v}
    assert 30 <= r["toplam_sure_sn"] <= 40
    assert r["anlati_olcum"]["kanca_sure_sn"] <= 2.0
    assert r["seslendirme"]["S1"]["motor"] == "piper"
    assert abs(sum(c["sure_sn"] for c in plan["cekimler"]) - r["toplam_sure_sn"]) < 0.05


def test_pilot_plani_belirlenimci():
    a = uretim_hatti.planla(PILOT)
    p1 = (PILOT / "cekim_plani.json").read_text()
    uretim_hatti.planla(PILOT)
    assert (PILOT / "cekim_plani.json").read_text() == p1 and a["gecti"]
