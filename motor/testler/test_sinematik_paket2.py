"""Sinematik paket 2: prosedürel doğa serpmesi, ordugâh, arka plan ordusu (pişirilmiş poz + MultiMesh), top atışı.
Hepsi konudan bağımsız, açılıp kapatılabilir; dış modeller lisanslı ve sınıflandırılmış; uydurma yok."""
import json

import yaml

from motor import ayar
from motor.uretim import planlayici, render, veri

KOK = ayar.MOTOR
PLAN = KOK / "uretim/pilotlar/otlukbeli-1473/cekim_plani.json"


def _plan():
    return json.loads(PLAN.read_text())


def test_doga_modelleri_cc0_ve_boyut_sinirinda():
    kayit = json.loads((KOK / "varlik/dis_cevre_kaydi.json").read_text())
    for pid in ("agac_yaprakli_1", "agac_yaprakli_2", "cam_1", "cam_2", "kuru_agac", "kaya_1", "kaya_2"):
        assert kayit[pid]["lisans"] == "CC0-1.0" and kayit[pid]["kaynak"]["commit"]
        assert kayit[pid]["olcum"]["bayt"] <= 390 * 1024, pid           # 390 KB sınırı: eşik değil doku küçültüldü
        assert veri.kalite()["ekipman"][pid]["sinif"] == "B"


def test_serpme_donem_ve_araziye_gore_kurulur():
    p = _plan()
    s3a = next(c for c in p["cekimler"] if c["id"] == "S3a")
    s = render.is_hazirla(p, s3a)["serpme"]
    assert s["acik"] and s["gorus_payi_m"] > 0 and s["serit_payi_m"] > 0
    assert any("cam_" in k["glb"] for k in s["katmanlar"])
    s2 = next(c for c in p["cekimler"] if c["id"] == "S2")          # kuru bozkır: yapraklı ağaç yok
    assert not any("yaprakli" in k["glb"] for k in render.is_hazirla(p, s2)["serpme"]["katmanlar"])


def test_ordugah_donemin_cadirini_kullanir_uydurmaz():
    p = _plan()
    s8 = next(c for c in p["cekimler"] if c["id"] == "S8a")
    y = render.is_hazirla(p, s8)["yerlesim"]
    assert y["acik"] and all(g.endswith("osmanli_cadiri.glb") for g in y["cadirlar"])
    t = {"id": "X", "cumle": "x", "sure_sn": 3.0, "amac": "baglam",
         "niyet": {"tur": "3d", "roller": [{"rol": "piyade", "adet": 3}], "mesafe": "uzak",
                   "ortam": {"arazi": "ova_cimen", "isik": "aksam_ustu", "yerlesim": "sehir_meydani"}, "eylem": "bekleme"}}
    c, eksik, _ = planlayici.cekim_kur(t, "osmanli-15yy", 9 / 16, [], 3)
    assert "yerlesim" not in c["ortam"] and any("yerleşim kuralı yok" in e for e in eksik)


def test_arka_plan_ordusu_ayni_taraftan_ve_sancaksiz():
    p = _plan()
    s2 = next(c for c in p["cekimler"] if c["id"] == "S2")
    k = render.is_hazirla(p, s2)["kalabalik"]
    assert k["acik"] and 1 <= len(k["takimlar"]) <= 3
    assert all(t.startswith("akk_") and not planlayici._sancakli(t) for t in k["takimlar"])
    assert k["adet"] >= 100 and k["mesafe_m"][0] >= 8


def test_top_atisi_yalniz_top_varliginda():
    g = veri.kural("gorsel")["vfx"]
    assert g["top"]["parcalar"] == ["top_arabasi"]
    p = _plan()
    s6 = next(c for c in p["cekimler"] if c["id"] == "S6")
    assert any(cv["id"] == "top_arabasi" for cv in s6["ortam"]["cevre"])


def test_yeni_sistemler_kapatilabilir_ve_godotta_bagli():
    assert isinstance(veri.kural("dogal")["acik"], bool)
    assert yaml.safe_load((KOK / "uretim/kurallar/yerlesim.yaml").read_text())["yerlesimler"]["ordugah"]
    assert veri.kural("kalabalik")["kalabaliklar"]["ordu"]["animasyon"] == "Idle_Loop"
    c = (KOK / "godot/sahneler/cekim.gd").read_text()
    for x in ("Serp.serp(", "Y.ordugah(", "K.kur(", "V.top_atisi("):
        assert x in c
    k = (KOK / "godot/sahneler/kalabalik.gd").read_text()
    assert "bake_mesh_from_current_skeleton_pose" in k and "NOTIFICATION_UPDATE_SKELETON" in k


def test_forward_plus_ozellikleri_varsayilan_kapali():
    """Forward+ (lavapipe) denendi, görüntü bu motorun ayarlarıyla kötüleşti: varsayılan profilde açılmaz."""
    g = veri.kural("gorsel")
    for ad, prof in g["profiller"].items():
        for bolum in ("isik", "arazi"):
            assert not (prof.get(bolum) or {}).get("hacimsel_sis") and not (prof.get(bolum) or {}).get("ssao"), ad
