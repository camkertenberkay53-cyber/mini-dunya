"""Ücretsiz kalite paketi: karakter çeşitliliği (klon azaltma) + yeni çevre varlıkları (top arabası, yük arabası)."""
import json
from pathlib import Path

import yaml

from motor import ayar
from motor.uretim import render, veri

KOK = ayar.REPO / "motor"


def test_karakter_cesit_ayari_var_ve_kapatilabilir():
    kc = veri.kural("gorsel")["karakter_cesit"]
    assert isinstance(kc["acik"], bool)
    for ad in ("kumas_deger", "deri_deger", "metal_deger", "ten", "sac", "genislik"):
        a, b = kc[ad]
        assert 0.0 < a <= b <= 1.2, ad          # parlaklık patlaması / sıfır renk yok
    a, b = kc["genislik"]
    assert 0.9 <= a and b <= 1.1                # gövde oranı bozulmaz


def test_karakter_cesit_ise_aktariliyor():
    plan = json.loads((KOK / "uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
    is_ = render.is_hazirla(plan, plan["cekimler"][0])
    assert is_["karakter_cesit"] == veri.kural("gorsel")["karakter_cesit"]


def test_godot_cesitle_tohumlu_ve_kanca_bagli():
    d = (KOK / "godot/sahneler/donatici.gd").read_text()
    c = (KOK / "godot/sahneler/cekim.gd").read_text()
    assert "static func cesitle(" in d and "r.seed = tohum" in d
    assert "mi_eyes" in d                         # gözler değişmez
    assert 'kc.get("acik", false)' in c and "D.cesitle(" in c


def test_yeni_cevre_varliklari_lisansli_ve_donemli():
    """Yeni parçalar dondurulmuş ekipman.yaml/kalite.json'a değil ek dosyalara girer; birleşik katalogda görünür."""
    ana = yaml.safe_load((KOK / "varlik/ekipman.yaml").read_text())["parcalar"]
    ek = yaml.safe_load((KOK / "varlik/ekipman_ek.yaml").read_text())["parcalar"]
    assert not set(ana) & set(ek)
    kayit = json.loads((KOK / "varlik/ekipman_kaydi.json").read_text())
    for pid in ("top_arabasi", "yuk_arabasi"):
        v = veri.ekipman_katalogu()["parcalar"][pid]
        assert v["kategori"] == "cevre" and v["donem"] and v["tarih"]["guven"]
        assert kayit[pid]["lisans"] == "kendi-uretim"
        assert veri.kalite()["ekipman"][pid]["sinif"] in ("A", "B")


def test_otlukbeli_kapanisinda_top_ve_araba():
    plan = json.loads((KOK / "uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
    s8 = [c for c in plan["cekimler"] if c["id"].startswith("S8")]
    ids = {x["id"] for c in s8 for x in c["ortam"].get("cevre", [])}
    assert {"top_arabasi", "yuk_arabasi"} <= ids
