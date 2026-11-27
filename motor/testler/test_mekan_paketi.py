"""Mekân paketi: su (deniz/nehir), yeni arazi ve ışık ön ayarları, kale/kasaba/liman/nehir yerleşimleri, mekân
kütüphanesi (tek kelimeyle otomatik seçim). Eski arazilerin davranışı değişmez; dış modeller lisanslı ve sınıflı."""
import json

from motor import ayar
from motor.uretim import planlayici, render, veri

KOK = ayar.MOTOR


def _taslak(mekan, donem="osmanli-15yy"):
    return {"id": "T", "cumle": "x", "sure_sn": 4.0, "amac": "baglam",
            "niyet": {"tur": "3d", "roller": [{"rol": "komutan", "donem": donem, "odak": True},
                                               {"rol": "piyade", "donem": donem, "adet": 4}],
                      "mesafe": "uzak", "ortam": {"mekan": mekan}, "eylem": "bekleme"}}


def test_mekan_kutuphanesi_alti_ortami_kapsar():
    m = veri.kural("mekan")["mekanlar"]
    for ad in ("dagli_savas_alani", "orman", "kale", "kasaba", "liman", "nehir_kiyisi"):
        assert ad in m
        assert m[ad]["arazi"] in veri.kural("arazi")["araziler"] and m[ad]["isik"] in veri.kural("arazi")["isiklar"]
        if "yerlesim" in m[ad]:
            assert m[ad]["yerlesim"] in veri.kural("yerlesim")["yerlesimler"]


def test_planlayici_mekani_cozer_aciki_ezmez_yoksa_raporlar():
    c, eksik, _ = planlayici.cekim_kur(_taslak("liman"), "osmanli-15yy", 9 / 16, [], 3)
    assert c["ortam"]["arazi"] == "deniz_kiyisi" and c["ortam"]["yerlesim"] == "liman" and not eksik
    t = _taslak("liman")
    t["niyet"]["ortam"]["isik"] = "oglen_acik"
    c, _, _ = planlayici.cekim_kur(t, "osmanli-15yy", 9 / 16, [], 3)
    assert c["ortam"]["isik"] == "oglen_acik"
    c, eksik, _ = planlayici.cekim_kur(_taslak("uzay_istasyonu"), "osmanli-15yy", 9 / 16, [], 3)
    assert any("mekânı kütüphanede yok" in e for e in eksik)


def test_su_yonu_kameraya_gore_ve_eski_araziler_susuz():
    c, _, _ = planlayici.cekim_kur(_taslak("liman"), "osmanli-15yy", 9 / 16, [], 3)
    p = {"konu": "t", "fps": 30, "cozunurluk": [1080, 1920], "donem": "osmanli-15yy", "tohum": 3}
    su = render.is_hazirla(p, c)["arazi"]["su"]
    assert su["tur"] == "deniz" and abs(sum(x * x for x in su["yon"]) - 1) < 1e-6
    for ad in ("ova_cimen", "kuru_bozkir"):
        assert "su" not in veri.kural("arazi")["araziler"][ad]


def test_yerlesim_parcalari_doneme_gore_ve_kaliteli():
    c, _, _ = planlayici.cekim_kur(_taslak("kasaba"), "osmanli-15yy", 9 / 16, [], 3)
    p = {"konu": "t", "fps": 30, "cozunurluk": [1080, 1920], "donem": "osmanli-15yy", "tohum": 3}
    y = render.is_hazirla(p, c)["yerlesim"]
    assert y["acik"] and y["tur"] == "kasaba" and y["roller"]["ev"]
    for pid in ("ev_kerpic_ahsap", "ev_tas", "pazar_tezgahi", "kale_kapisi", "burc_ev", "yelkenli_gemi", "sandal", "ucurum_1"):
        assert veri.kalite()["ekipman"][pid]["sinif"] == "B", pid
    kayit = json.loads((KOK / "varlik/dis_cevre_kaydi.json").read_text())
    assert all(kayit[p]["lisans"] == "CC0-1.0" for p in ("ev_tas", "yelkenli_gemi", "kale_kapisi"))
    assert "iskele" not in veri.ekipman_katalogu()["parcalar"]          # dokusuz iskele alınmadı


def test_godot_su_ve_yerlesim_bagli():
    o = (KOK / "godot/sahneler/ortam.gd").read_text()
    assert "SU_SHADER" in o and "uniform int su_tur = 0" in o            # su_tur 0 = önceki zemin aynen
    c = (KOK / "godot/sahneler/cekim.gd").read_text()
    assert "O.su(" in c and "Y.dizi(" in c and "O.su_guncelle(" in c
    assert "static func su_k(" in (KOK / "godot/sahneler/vfx.gd").read_text()
