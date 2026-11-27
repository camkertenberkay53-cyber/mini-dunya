"""Karakter ölçeği ve kamera perspektifi: dönem insan boyu, perspektif dengesi, kadraj/hız/render tutarlılığı."""
import copy
import json
import math

import pytest

from motor import ayar
from motor.uretim import animasyon_izni, kadraj, planlayici, render, veri

PLAN = ayar.REPO / "deneyler/mekan/planlar/mekan_M3.json"


def test_donem_boyu_orani_kaynaktan():
    k = veri.kural("insan_olcek")
    assert k["acik"] and k["model_boy_m"] == 1.84
    for d, b in k["donemler"].items():
        assert 1.6 <= b <= 1.75, d                               # tarihsel ortalama erkek boyu aralığı
        assert planlayici.insan_boy_orani(d) == round(b / 1.84, 3)
    assert 0.85 <= planlayici.insan_boy_orani("bilinmeyen-donem") <= 1.0


def test_cekim_orani_yazar_hiz_olcer_cesitlilik_degismez():
    c = {"karakterler": [{"takim": "x", "hiz_m_sn": 1.2, "olcek": 1.03}, {"takim": "y", "hiz_m_sn": 2.0, "binek": {"id": "at"}}]}
    planlayici.insan_olcegi(c, "osmanli-15yy")
    o = c["insan_boy_orani"]
    assert c["karakterler"][0]["olcek"] == 1.03                   # boy çeşitliliği alanına dokunulmaz (şema 0.9-1.1)
    assert c["karakterler"][0]["hiz_m_sn"] == round(1.2 * o, 4)    # adım boyu boyla orantılı
    assert c["karakterler"][1]["hiz_m_sn"] == 2.0                  # atlı ölçeklenmez


def test_sema_yeni_alani_sinirli_tutar():
    s = json.loads((ayar.REPO / "motor/uretim/semalar/cekim_plani.schema.json").read_text())
    alan = s["properties"]["cekimler"]["items"]["properties"]["insan_boy_orani"]
    assert alan["minimum"] == 0.85 and alan["maximum"] == 1.0
    kar = s["$defs"]["karakter"] if "$defs" in s and "karakter" in s["$defs"] else None
    if kar:
        assert kar["properties"]["olcek"]["minimum"] == 0.9


def test_ayak_kaymasi_denetimi_hala_yakalar():
    anim = "Walk_Loop"
    z = animasyon_izni.zemin_hizi(anim)
    o = planlayici.insan_boy_orani("osmanli-15yy")
    assert animasyon_izni.hiz_durumu(anim, z * o, o)[0]           # doğru ölçeklenmiş hız geçer
    assert not animasyon_izni.hiz_durumu(anim, z, o)[0]           # ölçeklenmemiş hız: ayak kayar, yakalanır


def test_kadraj_olcumu_orani_kullanir():
    plan = json.loads(PLAN.read_text())
    c = copy.deepcopy(plan["cekimler"][0])
    c.pop("insan_boy_orani", None)
    a = kadraj.olc(c, 9 / 16)
    c["insan_boy_orani"] = 0.9
    b = kadraj.olc(c, 9 / 16)
    i = next(k for k, v in a.items() if v["gorunur"])
    assert b[i]["ekran_orani"] == pytest.approx(a[i]["ekran_orani"] * 0.9, abs=0.002)


def test_perspektif_dengesi():
    x = veri.kural("kamera")["cekimler"]["kurulus_genis"]
    odak = {"konum": [0.0, 0.0], "yon_derece": 0.0, "hiz_m_sn": 0.0, "animasyon": "Idle"}
    duz = planlayici.kamera_kur("kurulus_genis", odak, 4.0, x["oran"])
    assert duz["bas"]["fov"] == x["fov"]                          # arka plan yoksa tür kendi geniş lensiyle
    B = 34.0
    k = planlayici.kamera_kur("kurulus_genis", odak, 4.0, x["oran"], None, B)
    d = math.dist(k["bas"]["konum"][::2], k["bas"]["hedef"][::2])
    assert (d + B) / d <= x["perspektif_k"] + 0.05                 # arka plan en çok k kat küçülür
    assert x["fov_en_az"] <= k["bas"]["fov"] < x["fov"]           # lens daralır (tele sıkıştırma)
    # odak karakterin ekran oranı korunur
    boy = veri.kural("mesafe")["karakter_boyu_m"]
    oran = boy / (2 * d * math.tan(math.radians(k["bas"]["fov"]) / 2))
    assert oran == pytest.approx(x["oran"], rel=0.12)


def test_arka_plan_uzakligi_yerlesimden():
    assert planlayici.arka_plan_uzakligi({"ortam": {"yerlesim": "kale"}}) == 34.0
    assert planlayici.arka_plan_uzakligi({"ortam": {"arazi": "ova_cimen"}}) is None
    for ad, y in veri.kural("yerlesim")["yerlesimler"].items():
        assert y.get("arka_plan_m", 1) > 0, ad


def test_render_kok_olcegi_ve_kalabalik():
    plan = json.loads(PLAN.read_text())
    c = copy.deepcopy(plan["cekimler"][0])
    c["insan_boy_orani"] = 0.918
    c["karakterler"][1]["olcek"] = 1.04
    r = render._insan_olcekli(c)
    assert r["karakterler"][1]["olcek"] == pytest.approx(1.04 * 0.918, abs=1e-3)
    assert r["karakterler"][0].get("olcek", 1.0) == pytest.approx(0.918, abs=1e-3)
    assert c["karakterler"][1]["olcek"] == 1.04                    # plan kopyası değişmez


def test_uretilen_planlar_semaya_uyar():
    from motor.uretim import plan_denetim
    plan = json.loads(PLAN.read_text())
    plan["cekimler"][0]["insan_boy_orani"] = 0.918
    assert plan_denetim.denetle(plan)["gecti"]
    plan["cekimler"][0]["insan_boy_orani"] = 0.7
    assert not plan_denetim.denetle(plan)["gecti"]                 # sınır dışı oran reddedilir
