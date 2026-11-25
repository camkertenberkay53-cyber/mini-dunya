"""Mekân kalite paketi: gerçekçi CC0 varlıklar, lisans kaydı, yerine geçme (geri alınabilir), PBR malzeme kuralları."""
import json
import re
from pathlib import Path

import yaml

from motor import ayar
from motor.uretim import render, veri
from motor.varlik import mekan_varlik as mv

CC0 = ayar.REPO / "motor" / "varlik" / "cc0"


def test_cc0_lisans_kaydi_tam():
    """İndirilen her varlık: CC0, kaynak sayfası, dosya sha256; diskteki dosya kayıtla aynı."""
    import hashlib
    for v in json.loads((CC0 / "lisans.json").read_text())["varliklar"]:
        assert v["durum"] == "TAMAM", v["kimlik"]
        assert v["lisans"]["ad"] == "CC0 1.0" and v["lisans"]["kaynak"].startswith("https://")
        assert v["sayfa"].startswith(("https://polyhaven.com/a/", "https://ambientcg.com/view?id="))
        for f in v["dosyalar"]:
            assert hashlib.sha256((CC0 / f["dosya"]).read_bytes()).hexdigest() == f["sha256"], f["dosya"]


def test_katalog_varliklari_lisansli_ve_kaliteli():
    kat = mv.katalog()
    kayit = mv.kayit_oku()
    for vid, t in kat["varliklar"].items():
        for kay in mv.kaynaklar(t):
            mv.lisans_kaydi(kay)                           # doğrulanmamışsa hata
        k = kayit[vid]
        assert k["sinif"] == "A", (vid, k["neden"])
        assert k["lisans"] == "CC0 1.0"
        o = k["olcum"]
        assert o["uv"] >= 1 and o["doku"] and max(o["doku"]) <= kat["kalite"]["doku_en_cok"]   # gerçek dokulu, UV'li
        assert o["ucgen"] <= kat["kalite"]["ucgen_en_cok"] and o["bayt"] <= kat["kalite"]["bayt_en_cok"]
        assert o["yalniz_kose"] == 0


def test_kalite_siniri_dokusuz_ve_bozugu_reddeder():
    s = mv.katalog()["kalite"]
    temel = {"ucgen": 1000, "kose": 600, "yalniz_kose": 0, "bozuk_yuz": 0, "boyut_m": [5, 5, 5], "malzeme": 1, "uv": 1,
             "doku": [1024], "bayt": 100000}
    assert mv.kalite_sinifi(temel, s)[0] == "A"
    assert mv.kalite_sinifi(temel | {"doku": []}, s)[0] == "RED"
    assert mv.kalite_sinifi(temel | {"yalniz_kose": 3}, s)[0] == "RED"
    assert mv.kalite_sinifi(temel | {"ucgen": s["ucgen_en_cok"] + 1}, s)[0] == "RED"


def test_yerine_gecme_ve_kapaliyken_eski_parca():
    hd = [str(g) for g in render._cevre_glb(["sur_burclu", "yelkenli_gemi", "ev_tas"], "bizans-15yy", True)]
    assert any(g.endswith("sur_kalin_hd.glb") for g in hd)
    assert any(g.endswith("yelkenli_orta_hd.glb") for g in hd)
    assert any(g.endswith("ev_tas.glb") for g in hd)            # gerçekçi karşılığı yok: stilize kalır (malzeme yükseltilir)
    eski = [str(g) for g in render._cevre_glb(["sur_burclu", "yelkenli_gemi", "iskele_hd"], "bizans-15yy", False)]
    assert not any("/mekan/" in g for g in eski)                 # paket kapalı: önceki davranış, gerçekçi kimlik atlanır
    assert any(g.endswith("sur_burclu.glb") for g in eski)
    assert render._cevre_glb(["yelkenli_gemi"], "roma-cumhuriyet", True) == []   # dönem dışı: hiçbiri


def test_malzeme_kurallari_dokulari_var_ve_desenler_gecerli():
    m = yaml.safe_load((ayar.REPO / "motor/uretim/kurallar/malzeme.yaml").read_text())
    for r in m["kurallar"]:
        re.compile(r["desen"])
        for h in ("diff.jpg", "nor_gl.jpg", "arm.jpg"):
            assert (CC0 / r["doku"] / h).exists(), r
    # gerçekçi varlıkların kendi malzeme adları kurallara uymaz (kendi PBR'leri korunur)
    for ad in ("modular_fort_01_wall_1", "dutch_ship_medium_hull", "rock_face_01"):
        assert not any(re.search(r["desen"], ad) for r in m["kurallar"])


def test_is_json_paket_acik_ve_kapali(monkeypatch):
    plan = json.loads(Path(ayar.REPO / "deneyler/mekan/planlar/mekan_M5.json").read_text())
    c = plan["cekimler"][0]
    ac = render.is_hazirla(plan, c)
    assert ac["malzeme"]["acik"] and ac["yerlesim"]["roller"]["iskele"]
    assert any("/mekan/" in g for g in ac["yerlesim"]["roller"]["gemi"])
    g = veri.kural("gorsel")
    monkeypatch.setattr(veri, "kural", lambda ad: (dict(g, mekan_kalite={"acik": False}) if ad == "gorsel" else veri._yaml(veri.KURALLAR / f"{ad}.yaml")))
    kap = render.is_hazirla(plan, c)
    assert kap["malzeme"] == {"acik": False}
    assert not any("/mekan/" in x for v in kap["yerlesim"]["roller"].values() for x in v)
    assert "yamac_alb" not in kap["arazi"]["gorsel"]


def test_godot_kancalari():
    s = (ayar.GODOT_PROJE / "sahneler")
    mz = (s / "malzeme.gd").read_text()
    assert "uv1_world_triplanar = true" in mz and "TEXTURE_CHANNEL_GREEN" in mz
    y = (s / "yerlesim.gd").read_text()
    assert 'k.get("dose", false)' in y and "Mz.uygula(n)" in y
    o = (s / "ortam.gd").read_text()
    assert o.count("uniform float yamac_acik = 0.0") == 2   # zemin + uzak dağlar; varsayılan kapalı
    sp = (s / "serpme.gd").read_text()
    assert "on_yuz" in sp and "gomme_oran" in sp
