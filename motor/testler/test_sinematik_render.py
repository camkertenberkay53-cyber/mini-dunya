"""Sinematik render iyileştirmesi: tek anahtar, profil zinciri, film geçişi, geri alınabilirlik."""
import json
from pathlib import Path

from motor import ayar
from motor.uretim import render, veri

PLAN = ayar.REPO / "deneyler/mekan/planlar/mekan_M3.json"


def _gorsel(monkeypatch, acik: bool):
    g = veri.kural("gorsel")
    yeni = dict(g, sinematik_render=dict(g["sinematik_render"], acik=acik))
    monkeypatch.setattr(veri, "kural", lambda ad: yeni if ad == "gorsel" else veri._yaml(veri.KURALLAR / f"{ad}.yaml"))
    return yeni


def test_tek_anahtar_profil_zinciri(monkeypatch):
    g = _gorsel(monkeypatch, True)
    p = render.gorsel_profili(g, "dagli_vadi")
    assert p["isik"]["tonemap"] == "agx" and p["isik"]["golge_mesafe"] > 60
    assert p["isik"]["gok_bulut"] is True          # taban zinciri (faz54 → faz52) korunur
    assert "zemin_alb" in p["arazi"]


def test_is_json_film_ve_sinema_ekleri(monkeypatch):
    _gorsel(monkeypatch, True)
    plan = json.loads(PLAN.read_text())
    is_ = render.is_hazirla(plan, plan["cekimler"][0])
    f = is_["film"]
    assert f["acik"] and 0 < f["pus_max"] <= 0.35        # sis görüntüyü yıkamamalı: üst sınır
    assert len(f["pus_renk"]) == 3 and f["dof_bas"] >= 2.0  # alan derinliği yalnız odak çok ötesinde
    assert is_["sinema"]["gren"] <= 0.02 and is_["sinema"]["vinyet"] <= 0.35
    assert is_["isik"]["gorsel"]["tonemap"] == "agx"


def test_kapaliyken_onceki_goruntu(monkeypatch):
    plan = json.loads(PLAN.read_text())
    _gorsel(monkeypatch, False)
    is_ = render.is_hazirla(plan, plan["cekimler"][0])
    assert is_["film"] == {"acik": False}
    assert is_["isik"]["gorsel"]["tonemap"] == "filmic"   # faz54 profili
    assert "golge_mesafe" not in is_["isik"]["gorsel"]
    g = veri.kural("gorsel")
    assert is_["sinema"]["gren"] == g["sinema"]["gren"] and is_["sinema"]["vinyet"] == g["sinema"]["vinyet"]


def test_godot_kancalari():
    s = ayar.GODOT_PROJE / "sahneler"
    f = (s / "film.gd").read_text()
    assert "hint_depth_texture" in f and "hint_screen_texture" in f
    assert "gok" in f and "pus_max" in f                   # gök pikseli ayrı işlenir; pus sınırlı
    c = (s / "cekim.gd").read_text()
    assert 'is_.get("film", {}).get("acik", false)' in c   # kapalıyken düğüm eklenmez
    o = (s / "ortam.gd").read_text()
    assert 'float(g.get("golge_mesafe", 60.0))' in o       # varsayılan eski değer
