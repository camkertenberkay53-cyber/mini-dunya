"""Belgesel kalite paketi: gerçekçi ağaçlar, karakter yüzeyi, fiziksel lens; tek anahtarla geri alınabilir."""
import json
import math
import re

import yaml

from motor import ayar
from motor.uretim import render, veri
from motor.varlik import mekan_varlik as mv

PLAN = ayar.REPO / "deneyler/mekan/planlar/mekan_M2.json"


def _gorsel(monkeypatch, **alt):
    g = veri.kural("gorsel")
    b = dict(g["belgesel_kalite"], **alt)
    yeni = dict(g, belgesel_kalite=b)
    monkeypatch.setattr(veri, "kural", lambda ad: yeni if ad == "gorsel" else veri._yaml(veri.KURALLAR / f"{ad}.yaml"))


def test_agaclar_uretilmis_kaliteli_lisansli():
    kat = mv.katalog()["varliklar"]
    kayit = mv.kayit_oku()
    agaclar = [v for v, t in kat.items() if t.get("uretici") == "agac"]
    assert {kat[v]["tur"] for v in agaclar} == {"yaprakli", "igne", "kuru"}
    for v in agaclar:
        k = kayit[v]
        assert k["sinif"] == "A" and k["lisans"] == "CC0 1.0", v
        assert len(k["kaynak"]["tum_kaynaklar"]) == len(mv.kaynaklar(kat[v]))   # kabuk + yaprak/iğne fotoğrafı kayıtlı
        assert k["olcum"]["ucgen"] <= 12000 and k["olcum"]["bayt"] <= 1_000_000   # sahnede onlarca kopya: hafif
        assert 6.0 <= k["olcum"]["boyut_m"][2] <= 16.0                            # gerçek ağaç boyu
        if kat[v]["tur"] != "kuru":
            assert k["olcum"]["kart"] > 100                                       # yaprak/iğne kartları var


def test_agac_yerine_gecme_ve_anahtar(monkeypatch):
    g = [str(x) for x in render._cevre_glb(["cam_1", "agac_yaprakli_1", "kuru_agac"], "osmanli-15yy", True)]
    assert any("/mekan/cam_hd_" in x for x in g) and any("/mekan/yaprakli_hd_" in x for x in g) and any("/mekan/kuru_hd_" in x for x in g)
    _gorsel(monkeypatch, agac=False)
    g = [str(x) for x in render._cevre_glb(["cam_1", "agac_yaprakli_1"], "osmanli-15yy", True)]
    assert any(x.endswith("/ekipman/cam_1.glb") for x in g) and not any("_hd_" in x for x in g)


def test_karakter_yuzey_kurallari():
    k = yaml.safe_load((ayar.REPO / "motor/uretim/kurallar/yuzey.yaml").read_text())["kurallar"]
    adlar = ["kaftan_yesil", "dolama_lacivert", "salvar_bej", "tunik_gri_mavi", "kusak_kirmizi", "cizme_kahve",
             "kemer_deri", "lamel_celik", "celik", "tunc", "kece_kirmizi"]
    for ad in adlar:
        assert any(re.search(r["desen"], ad) for r in k), ad
    assert not any(re.search(r["desen"], "zincir") for r in k)          # kendi halka dokusu korunur
    assert not any(re.search(r["desen"], x) for r in k for x in ("mi_superhero_male", "mi_eyes", "mi_hair_1"))
    plan = json.loads(PLAN.read_text())
    y = render.is_hazirla(plan, plan["cekimler"][0])["yuzey"]
    assert y["acik"]
    for r in y["kurallar"]:
        for h in ("diff", "nor", "pur"):
            assert (ayar.REPO / r[h]).exists() or __import__("pathlib").Path(r[h]).exists(), r[h]


def test_fiziksel_lens_derin_odak_ve_portre():
    def coc_px(fov, odak, uz, n=2.8, sensor=0.036, h=1920):
        f = sensor * 0.5 / math.tan(math.radians(fov) * 0.5)
        return f * f / (n * (odak - f)) * abs(uz - odak) / uz / sensor * h * 0.5
    assert coc_px(55, 16, 100) < 1.0           # geniş plan: arka plan neredeyse keskin (derin odak)
    assert coc_px(32, 6, 80) > 4.0             # orta-yakın tele: arka plan ayrışır
    plan = json.loads(PLAN.read_text())
    f = render.is_hazirla(plan, plan["cekimler"][0])["film"]
    assert f["dof_fizik"] == 1 and f["diyafram"] >= 2.0


def test_ana_anahtar_kapali_onceki_goruntu(monkeypatch):
    _gorsel(monkeypatch, acik=False)
    plan = json.loads(PLAN.read_text())
    is_ = render.is_hazirla(plan, plan["cekimler"][0])
    assert is_["yuzey"] == {"acik": False}
    assert is_["film"]["dof_fizik"] == 0 and is_["film"]["dof_guc"] == 0.3        # sinematik render kabul ayarı
    assert not any("_hd_" in k["glb"] and ("cam_" in k["glb"] or "yaprakli" in k["glb"]) for k in is_["serpme"]["katmanlar"])


def test_godot_kancalari():
    s = ayar.GODOT_PROJE / "sahneler"
    y = (s / "yuzey.gd").read_text()
    assert "UV * tekrar" in y and "world" not in y.lower()             # UV tabanlı: iskeletli animasyonda kaymaz
    assert "Yz.uygula(kok)" in (s / "cekim.gd").read_text()
    assert "dof_fizik" in (s / "film.gd").read_text()
