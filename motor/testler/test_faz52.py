"""Faz 5.2 (sinematik belgesel) ölçüm disiplini ve adım testleri."""
import json

from motor import ayar
from motor.uretim import benchmark

KOK = ayar.REPO / "deneyler" / "faz52"


def test_taban_plani_ve_olcumu_kayitli():
    p = json.loads((KOK / "plan_taban.json").read_text())
    ids = {c["id"] for c in p["cekimler"]}
    assert set(benchmark.CEKIMLER) <= ids                      # sabit çekimler planda
    t = json.loads((KOK / "olcum" / "taban.json").read_text())
    for c in benchmark.CEKIMLER:
        x = t["cekimler"][c]
        assert x["render_sn"] > 0 and x["tepe_bellek_gb"] > 0 and x["kare"] > 0
        assert (KOK / "kareler" / f"taban_{c}.jpg").exists()   # görsel kanıt aynı kareden
    assert t["git"] and t["anahtarlar"]


def test_kapi_karari(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "KOK", tmp_path)
    (tmp_path / "olcum").mkdir()
    a = {"cekimler": {"S1": {"render_sn": 100.0, "tepe_bellek_gb": 1.0}, "S2": {"render_sn": 100.0, "tepe_bellek_gb": 1.0},
                      "S6": {"render_sn": 100.0, "tepe_bellek_gb": 1.0}}}
    b = {"cekimler": {"S1": {"render_sn": 108.0, "tepe_bellek_gb": 1.0}, "S2": {"render_sn": 120.0, "tepe_bellek_gb": 1.1},
                      "S6": {"render_sn": 140.0, "tepe_bellek_gb": 1.0}}}
    (tmp_path / "olcum" / "a.json").write_text(json.dumps(a))
    (tmp_path / "olcum" / "b.json").write_text(json.dumps(b))
    k = benchmark.kiyasla("a", "b")
    assert [k[c]["karar"] for c in ("S1", "S2", "S6")] == ["kabul", "rapor", "varsayilan_kapali"]
    assert benchmark.KAPI == {"kabul": 0.10, "rapor": 0.25}    # onaylanan kapı değişmedi


# ---------------------------------------------------------------- adım 2: atmosfer ön ayarları
def _plan2():
    return json.loads((KOK / "plan_adim2.json").read_text())


def test_atmosfer_on_ayarlari_tanimli_ve_dusuk_gunes():
    from motor.uretim import veri
    i = veri.kural("arazi")["isiklar"]
    for ad in ("kurak_altin", "kurak_altin_ogle", "soguk_safak"):
        assert {"gunes", "dolgu", "gok", "sis", "sinema", "pus"} <= set(i[ad]), ad
    assert 12 <= -i["kurak_altin"]["gunes"]["aci"][0] <= 18          # brief: düşük güneş 12-18°
    assert i["soguk_safak"]["sis"]["yogunluk"] > i["oglen_acik"]["sis"]["yogunluk"]   # şafakta yoğun pus
    s = i["soguk_safak"]["gunes"]["renk"]
    assert s[2] > s[0]                                                # soğuk (mavi baskın) ışık


def test_atmosfer_eslemesi_tek_anahtarla(monkeypatch):
    from motor.uretim import render, veri
    p = _plan2()
    s1 = next(c for c in p["cekimler"] if c["id"] == "S1")
    is_ = render.is_hazirla(p, s1)
    assert is_["isik"]["aciklama"].startswith("Kurak bozkırda alçak")
    assert is_["isik"]["gorsel"]["gok_tepe"] == veri.kural("arazi")["isiklar"]["kurak_altin"]["sinema"]["gok_tepe"]
    assert is_["film"]["pus_max"] == veri.kural("arazi")["isiklar"]["kurak_altin"]["pus"]["pus_max"]
    g = dict(veri.kural("gorsel"), isik_onayarlari={"acik": False})
    gercek = veri.kural
    monkeypatch.setattr(veri, "kural", lambda ad: g if ad == "gorsel" else gercek(ad))
    kapali = render.is_hazirla(p, s1)
    assert kapali["isik"]["aciklama"] == gercek("arazi")["isiklar"]["aksam_ustu"]["aciklama"]   # eski davranış
    assert "pus_max" not in kapali["film"] or kapali["film"]["pus_max"] == gercek("gorsel")["sinematik_render"]["film"]["pus_max"]


def test_atmosfer_konudan_plana_ve_denetime():
    from motor.uretim import plan_denetim
    k = json.loads((ayar.MOTOR / "uretim/pilotlar/otlukbeli-1473/konu.json").read_text())
    assert k["atmosfer"]["isik_eslesme"]["aksam_ustu"] == "kurak_altin"
    p = _plan2()
    assert plan_denetim.denetle(p)["gecti"]
    p["atmosfer"]["isik_eslesme"]["aksam_ustu"] = "olmayan_isik"
    assert any("atmosfer eşlemesi" in h for h in plan_denetim.denetle(p)["hatalar"])   # uydurma ön ayar reddedilir


# ---------------------------------------------------------------- adım 3: sahne türü renk profili
def _derecele(c, rp):
    """sinema.gd derecelendirmesinin birebir Python karşılığı (ton adımı hariç)."""
    import numpy as np
    c = np.array(c, float)
    l = c @ [0.299, 0.587, 0.114]
    gd = np.clip((c - 0.45) * rp["kontrast"] + 0.45, 0, 4)
    sm = lambda a, b, x: np.clip((x - a) / (b - a), 0, 1) ** 2 * (3 - 2 * np.clip((x - a) / (b - a), 0, 1))
    gd = gd * (1 - rp["golge_derinlik"] * (1 - sm(0.0, 0.32, l)))
    gd = gd * (1 + rp["vurgu_sikistir"]) / (1 + rp["vurgu_sikistir"] * gd)
    lg = gd @ [0.299, 0.587, 0.114]
    gd = lg + (gd - lg) * rp["doygunluk"]
    mx, mn = c.max(), c.min()
    sat = (mx - mn) / max(mx, 1e-3)
    ten = float(c[2] <= c[1] <= c[0]) * sm(0.12, 0.25, sat) * (1 - sm(0.55, 0.75, sat)) * sm(0.12, 0.25, l) * (1 - sm(0.8, 0.95, l))
    return gd * (1 - ten * rp["ten_koru"]) + c * ten * rp["ten_koru"]


def test_renk_profilleri_secimi_ve_harita_notr(monkeypatch):
    from motor.uretim import render, veri
    p = _plan2()
    ad = {c["id"]: render.renk_profili_3d(c).get("ad") for c in p["cekimler"]}
    assert ad["S6"] == "savas_3d" and ad["S7"] == "agir_3d" and ad["S1"] == "belgesel_3d"
    assert render.renk_profili_ffmpeg("harita") == ""                  # taktik harita nötr
    assert render.renk_profili_ffmpeg("gorsel25d").startswith("eq=")
    g = dict(veri.kural("gorsel"), renk_profilleri={"acik": False})
    gercek = veri.kural
    monkeypatch.setattr(veri, "kural", lambda a: g if a == "gorsel" else gercek(a))
    assert render.renk_profili_3d(p["cekimler"][0]) == {} and render.renk_profili_ffmpeg("gorsel25d") == ""


def test_shader_varsayilanlari_notr_ve_ten_korunur():
    from motor.uretim import veri
    s = (ayar.MOTOR / "godot/sahneler/sinema.gd").read_text()
    for u in ("uniform float kontrast = 1.0", "uniform float golge_derinlik = 0.0", "uniform float vurgu_sikistir = 0.0",
              "uniform float doygunluk = 1.0", "uniform float ten_koru = 0.0"):
        assert u in s                                                  # profil yoksa çıktı değişmez
    rp = veri.kural("gorsel")["renk_profilleri"]["savas_3d"]
    import numpy as np
    ten = [0.62, 0.42, 0.30]                                           # orta ten (doğrusal)
    zirh = [0.42, 0.45, 0.50]                                          # gri-mavi zırh
    d_ten = np.abs(_derecele(ten, rp) - ten).max()
    d_zirh = np.abs(_derecele(zirh, rp) - zirh).max()
    assert d_ten < d_zirh * 0.6                                        # derecelendirme tende belirgin daha az
    assert all(0 < x <= 1.2 for x in _derecele([0.95, 0.95, 0.95], rp))   # vurgu patlamaz
