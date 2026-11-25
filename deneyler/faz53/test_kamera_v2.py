"""Faz 5.3 kamera v2 deney testleri (motor/testler'e dokunulmaz). Çalıştırma: python3 -m pytest deneyler/faz53 -q"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))
import kamera_v2  # noqa: E402
from motor.uretim import sahne_bolucu  # noqa: E402

PILOT = kamera_v2.REPO / "motor/uretim/pilotlar/roma-lejyon-kartali"
EN_BOY = 1080 / 1920


def _taslaklar():
    sen = json.loads((PILOT / "senaryo.json").read_text())
    plan = json.loads((PILOT / "cekim_plani.json").read_text())
    return sahne_bolucu.cekimlere_bol(sen, plan["ses"]["cizelge"]), plan["donem"]


def test_en_az_bes_tur_ayni_sahnede_temiz():
    ts, donem = _taslaklar()
    t = next(x for x in ts if x["id"].startswith("S4"))
    temiz = []
    for tur, x in kamera_v2._KURAL["cekimler"].items():
        y = json.loads(json.dumps(t))
        y["niyet"]["mesafe"] = "uzak" if "uzak" in x["mesafeler"] else "orta"
        y["niyet"]["kamera"] = None
        c, _, _ = kamera_v2.cekim_kur_v2(y, donem, EN_BOY, [], 7, None, zorla_tur=tur)
        if "kamera" in c and not c["meta"]["kalan_kusur"]:
            temiz.append(tur)
    assert len(temiz) >= 5, temiz
    assert len({kamera_v2._KURAL["cekimler"][t]["hareket"] for t in temiz}) >= 5


def test_secim_amaca_bagli_ve_tekrarsiz():
    ts, donem = _taslaklar()
    gecmis, turler = [], []
    for i, t in enumerate(ts):
        c, _, k = kamera_v2.cekim_kur_v2(t, donem, EN_BOY, gecmis, 7 + i, set())
        gecmis.append(k)
        turler.append(c["meta"]["tur"])
        assert c["meta"]["tur"] in c["meta"]["tercih_sirasi"] or c["meta"]["reddedilen_adaylar"], c["id"]
    hareketler = [kamera_v2._KURAL["cekimler"][t]["hareket"] for t in turler]
    assert all(a != b for a, b in zip(hareketler, hareketler[1:]))
    assert len(set(turler)) >= 8
    # aynı girdi → aynı plan (rastgele değil)
    gecmis2 = []
    turler2 = []
    for i, t in enumerate(ts):
        c, _, k = kamera_v2.cekim_kur_v2(t, donem, EN_BOY, gecmis2, 7 + i, set())
        gecmis2.append(k)
        turler2.append(c["meta"]["tur"])
    assert turler == turler2


def test_olumde_dramatik_alcak_yasak():
    sira, yasak, _ = kamera_v2.tercih_listesi("gerilim", "olum", [], "piyade", False, 3, None)
    assert "alcak_yaklasma" in yasak and "alcak_yaklasma" not in sira and sira[0] == "sabit_uzak"


def test_kusurlu_aday_reddedilir_alternatif_secilir():
    ts, donem = _taslaklar()
    t = next(x for x in ts if x["id"] == "S1")
    c, _, _ = kamera_v2.cekim_kur_v2(t, donem, EN_BOY, [], 7, set())
    ilk = c["meta"]["tur"]
    # aynı çekimi, ilk seçilen kameranın başlangıç noktasına bir asker koyarak yeniden kur → kusur → alternatif
    import motor.uretim.planlayici as p
    asil = p.dizilis_kur

    def engelli(*a, **k):
        ks, d, oi = asil(*a, **k)
        kam = c["kamera"]["bas"]["konum"]
        ks.append(dict(ks[oi], konum=[kam[0], kam[2]], hiz_m_sn=0.0))
        return ks, d, oi
    p.dizilis_kur = engelli
    try:
        c2, _, _ = kamera_v2.cekim_kur_v2(t, donem, EN_BOY, [], 7, set())
    finally:
        p.dizilis_kur = asil
    red = c2["meta"]["reddedilen_adaylar"]
    assert red and red[0]["tur"] == ilk and any("içinden" in n or "objektife" in n for n in red[0]["neden"])
    assert c2["meta"]["tur"] != ilk and not c2["meta"]["kalan_kusur"]
