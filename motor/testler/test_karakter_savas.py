"""Karakter kalite paketi: beden çeşitliliği, ten yüzeyi ve savaş koreografisi (rakipli düello)."""
import copy
import json

import pytest

from motor import ayar
from motor.uretim import animasyon_izni, koreografi, render, veri

PILOT = ayar.MOTOR / "uretim/pilotlar/otlukbeli-1473/cekim_plani.json"
GODOT = ayar.MOTOR / "godot/sahneler"


def _savas_cekimi():
    p = json.loads(PILOT.read_text())
    for c in p["cekimler"]:
        if any(str(x.get("animasyon", "")).startswith(("Sword", "ual2/Sword")) for x in c["karakterler"]) \
                and not any(x.get("binek") for x in c["karakterler"]):
            return c
    pytest.skip("pilotta yaya kılıç çekimi yok")


def _yaya_cekim(takim="osm_yeniceri_kilic", n=4):
    return {"karakterler": [{"takim": takim, "rol": "piyade", "konum": [i * 1.5, 0.0], "yon_derece": 0.0,
                             "animasyon": "Sword_Idle"} for i in range(n)]}


def test_koreografi_rakipli_cift_kurar_yalniz_izinli_animasyonla():
    c = _yaya_cekim()
    odak, meta = koreografi.uygula(c, 0, "savas", "osmanli-15yy", ["osmanli-15yy", "akkoyunlu-15yy"], "orta", 11)
    assert odak == 0 and meta and meta["tur"] == "duello" and meta["cift"] >= 2
    assert meta["karsi_donem"] == "akkoyunlu-15yy"
    karsi = [x for x in c["karakterler"] if x["rol"].startswith("karsi_")]
    assert len(karsi) == meta["cift"]                              # her ön saf askerinin bir rakibi var
    for x in c["karakterler"]:
        assert animasyon_izni.izinli(x["takim"], x["animasyon"])[0], (x["takim"], x["animasyon"])
        assert 0 <= x["faz_sn"] <= koreografi.sure(x["animasyon"]) + 1e-6
        assert 0.9 <= x.get("olcek", 1.0) <= 1.1
    for x in karsi:
        assert veri.takimlar()[x["takim"]]["kit"].startswith("akkoyunlu")            # karşı dönemin kiti
        assert 160 <= x["yon_derece"] <= 200 and x["konum"][1] > 1.2   # rakibe bakar, karşıda durur
    assert c["karakterler"][0]["konum"][0] == pytest.approx(0, abs=0.6)  # odak çifti kadrajın ortasında
    fazlar = {x["faz_sn"] for x in c["karakterler"]}
    assert len(fazlar) == len(c["karakterler"])                    # kimse senkron (kopya) hareket etmez


def test_koreografi_karsi_donem_yoksa_rakip_uydurmaz_atliya_dokunmaz():
    c = _yaya_cekim()
    _, meta = koreografi.uygula(c, 0, "savas", "osmanli-15yy", ["osmanli-15yy"], "orta", 3)
    assert meta["tur"] == "cesitleme" and meta["cift"] == 0
    assert not any(x["rol"].startswith("karsi_") for x in c["karakterler"])
    atli = _yaya_cekim()
    atli["karakterler"][0]["binek"] = {"id": "at"}
    once = copy.deepcopy(atli)
    assert koreografi.uygula(atli, 0, "savas", "osmanli-15yy", ["akkoyunlu-15yy"], "orta", 3) == (0, None)
    assert atli == once


def test_koreografi_tek_anahtarla_kapanir(monkeypatch):
    k = dict(veri.kural("koreografi"), acik=False)
    gercek = veri.kural
    monkeypatch.setattr(veri, "kural", lambda ad: k if ad == "koreografi" else gercek(ad))
    c = _yaya_cekim()
    once = copy.deepcopy(c)
    assert koreografi.uygula(c, 0, "savas", "osmanli-15yy", ["akkoyunlu-15yy"], "orta", 1) == (0, None)
    assert c == once


def test_yeni_kilic_animasyonlari_kayitli_eski_kayitlar_korunur():
    a = veri.kural("animasyon")["animasyonlar"]
    for x in ("ual2/Sword_Regular_A", "ual2/Sword_Regular_B", "ual2/Sword_Regular_C"):
        assert x in a and "kilic" in a[x]["gerekli"]["yuva_turu"]["sag_el"]
        assert koreografi.sure(x) > 0.3
    t = json.loads((ayar.MOTOR / "karakter/animasyon_testi.json").read_text())
    metin = json.dumps(t)
    assert "ual2/Sword_Regular_A" in metin and "ual2/Sword_Block" in metin


def test_agir_zirhli_reddedilen_animasyon_secilmez():
    """Zırh içinden geçme testi başarısız takım bu animasyonları alamaz (eşik gevşetilmedi)."""
    for takim in ("rom_lejyoner_gladius", "biz_piyade_kilic"):
        if takim not in veri.takimlar():
            continue
        if not animasyon_izni.izinli(takim, "ual2/Sword_Regular_A")[0]:
            assert "ual2/Sword_Regular_A" not in koreografi._izinli_secenekler(takim, ["ual2/Sword_Regular_A"])


def test_beden_ve_ten_tek_anahtarla(monkeypatch):
    g = copy.deepcopy(veri.kural("gorsel"))
    assert g["karakter_kalite"]["acik"] is True
    b = render._beden()
    assert b["acik"] and 0.85 <= b["taban"]["gogus"] <= 1.0
    assert any(r["desen"].startswith("^(mi_superhero") for r in render._yuzey()["kurallar"])
    g["karakter_kalite"]["acik"] = False
    gercek = veri.kural
    monkeypatch.setattr(veri, "kural", lambda ad: g if ad == "gorsel" else gercek(ad))
    assert render._beden() == {"acik": False}
    kur = render._yuzey().get("kurallar", [])
    assert not any("mi_superhero" in r["desen"] for r in kur)


def test_godot_kancalari():
    s = (GODOT / "beden.gd").read_text()
    assert "extends SkeletonModifier3D" in s and "_process_modification" in s
    assert "clavicle" in s                                         # kol/kalkan dalı telafi edilir (sızma yok)
    assert 'Bd.kur(kok' in (GODOT / "cekim.gd").read_text()


def test_olum_yon_yayilimi_kurali():
    y = veri.kural("dizilis")["eylem_yon_yayilimi"]
    assert y["olum"] >= 120 and y["darbe_alma"] >= 90
