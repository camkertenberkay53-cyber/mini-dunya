"""Faz 5.3 kamera sistemi kabul testleri (üretim): anlatı amacına bağlı seçim, tür başına lens, kamera QC
(çarpışma, objektif yakınlığı, kesilme, hız) ve kusurlu adaydan otomatik alternatife geçiş."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from motor.uretim import kadraj, kamera_denetim, plan_denetim, planlayici, sahne_bolucu, veri

PILOT = Path(__file__).resolve().parents[1] / "uretim/pilotlar/roma-lejyon-kartali"
EN_BOY = 1080 / 1920


@pytest.fixture(scope="module")
def taslaklar():
    sen = json.loads((PILOT / "senaryo.json").read_text())
    plan = json.loads((PILOT / "cekim_plani.json").read_text())
    return sahne_bolucu.cekimlere_bol(sen, plan["ses"]["cizelge"]), plan["donem"]


def _kur(taslaklar):
    ts, donem = taslaklar
    gecmis, cs = [], []
    for i, t in enumerate(ts):
        c, _, k = planlayici.cekim_kur(t, donem, EN_BOY, gecmis, 7 + i, set())
        gecmis.append(k)
        cs.append(c)
    return cs


def test_katalogda_en_az_bes_tur_ve_tur_basina_lens():
    kat = veri.kural("kamera")["cekimler"]
    assert len(kat) >= 15
    assert len({x["hareket"] for x in kat.values()}) >= 8
    fovlar = {x.get("fov") for x in kat.values()}
    assert None not in fovlar and min(fovlar) <= 22 and max(fovlar) >= 50


def test_ayni_sahnede_en_az_bes_tur_kusursuz(taslaklar):
    ts, donem = taslaklar
    t = next(x for x in ts if x["id"].startswith("S4"))
    temiz = []
    for tur, x in veri.kural("kamera")["cekimler"].items():
        c = {"id": "T", "cumleler": ["S4"], "sure_sn": 4.0, "tur": "3d", "amac": "olay"}
        oyuncular, _ = planlayici.oyuncu_sec(t["niyet"], donem)
        c["karakterler"], _, oi = planlayici.dizilis_kur(oyuncular, t["niyet"]["eylem"], 7, None, 4.0)
        mesafe = "uzak" if "uzak" in x["mesafeler"] else "orta"
        if x.get("gerekli") == "hareketli" and c["karakterler"][oi]["hiz_m_sn"] <= 0:
            continue
        planlayici.kamera_ayarla(c, oi, mesafe, EN_BOY, tur)
        if not kamera_denetim.denetle(c, oi, EN_BOY):
            temiz.append(tur)
    assert len(temiz) >= 5, temiz
    assert len({veri.kural("kamera")["cekimler"][t]["hareket"] for t in temiz}) >= 5


def test_secim_amaca_bagli_belirlenimci_ve_tekrarsiz(taslaklar):
    cs = _kur(taslaklar)
    for c in cs:
        m = c["meta"]
        assert m["tur"] in m["tercih_sirasi"] or m["reddedilen_adaylar"] or not m["tercih_sirasi"], c["id"]
        assert m["secim_gerekcesi"], c["id"]
    hareket = [c["meta"]["hareket"] for c in cs]
    assert all(a != b for a, b in zip(hareket, hareket[1:]))
    assert len({c["meta"]["tur"] for c in cs}) >= 8
    assert [c["meta"]["tur"] for c in _kur(taslaklar)] == [c["meta"]["tur"] for c in cs]


def test_amac_grameri():
    s, _, _ = planlayici.kamera_tercihleri("baglam", "bekleme", "piyade", False, 3)
    assert s[0] == "kurulus_genis"
    s, _, _ = planlayici.kamera_tercihleri("donum", "bekleme", "piyade", False, 3)
    assert s[0] == "itme_dramatik"
    s, _, _ = planlayici.kamera_tercihleri("olay", "yuruyus", "piyade", True, 12)
    assert s[:2] == ["yan_takip", "tele_kalabalik"]
    s, _, _ = planlayici.kamera_tercihleri("final", "bekleme", "piyade", False, 3)
    assert s[0] == "yukselme"
    s, _, _ = planlayici.kamera_tercihleri("donum", "bekleme", "komutan", False, 2)
    assert s[0] == "orta_konusma"
    s, _, _ = planlayici.kamera_tercihleri("donum", "yuruyus", "komutan", True, 2)
    assert "orta_konusma" not in s[:1]


def test_olumde_alcak_aci_ve_itme_yasak():
    s, yasak, _ = planlayici.kamera_tercihleri("gerilim", "olum", "piyade", False, 3)
    assert {"alcak_yaklasma", "itme_dramatik"} <= yasak and s[0] == "sabit_uzak"
    a = planlayici.cekim_turu_adaylari("orta", False, [], 0, None, None, s, yasak)
    assert "alcak_yaklasma" not in a and "itme_dramatik" not in a


def test_kamera_qc_carpisma_ve_kesilmeyi_yakalar(taslaklar):
    cs = _kur(taslaklar)
    c = copy.deepcopy(next(x for x in cs if x["id"] == "S1"))
    oi = c["meta"]["odak_indeks"]
    assert kamera_denetim.denetle(c, oi, EN_BOY) == []
    kam = c["kamera"]["bas"]["konum"]
    engel = dict(c["karakterler"][oi], konum=[kam[0], kam[2]], hiz_m_sn=0.0)
    d = copy.deepcopy(c)
    d["karakterler"].append(engel)
    assert any("içinden" in k or "objektife" in k for k in kamera_denetim.denetle(d, oi, EN_BOY))
    e = copy.deepcopy(c)
    for an in ("bas", "son"):
        e["kamera"][an]["hedef"][1] -= 3.0   # bakış yere: baş kadrajdan çıkar
    assert any("başı" in k for k in kamera_denetim.denetle(e, oi, EN_BOY))
    f = copy.deepcopy(c)
    f["kamera"]["son"]["konum"] = [kam[0] + 40, kam[1], kam[2]]
    assert any("hızlı" in k for k in kamera_denetim.denetle(f, oi, EN_BOY))


def test_kusurlu_aday_reddedilir_alternatif_secilir(taslaklar):
    ts, donem = taslaklar
    t = next(x for x in ts if x["id"] == "S1")
    c, _, _ = planlayici.cekim_kur(t, donem, EN_BOY, [], 7, set())
    ilk = c["meta"]["tur"]
    asil = planlayici.dizilis_kur

    def engelli(*a, **k):
        ks, d, oi = asil(*a, **k)
        kam = c["kamera"]["bas"]["konum"]
        ks.append(dict(ks[oi], konum=[kam[0], kam[2]], hiz_m_sn=0.0))
        return ks, d, oi
    planlayici.dizilis_kur = engelli
    try:
        c2, _, _ = planlayici.cekim_kur(t, donem, EN_BOY, [], 7, set())
    finally:
        planlayici.dizilis_kur = asil
    red = c2["meta"]["reddedilen_adaylar"]
    assert red and red[0]["tur"] == ilk
    assert c2["meta"]["tur"] != ilk and kamera_denetim.denetle(c2, c2["meta"]["odak_indeks"], EN_BOY) == []


def test_plan_denetimi_kalan_kamera_kusurunu_hata_sayar(taslaklar):
    plan = json.loads((PILOT / "cekim_plani.json").read_text())
    assert plan_denetim.denetle(plan)["hatalar"] == []
    p = copy.deepcopy(plan)
    c = next(x for x in p["cekimler"] if x["id"] == "S1")
    k = c["kamera"]["bas"]["konum"]
    c["karakterler"].append(dict(c["karakterler"][c["meta"]["odak_indeks"]], konum=[k[0], k[2]], hiz_m_sn=0.0))
    assert any("kamera kusuru" in h for h in plan_denetim.denetle(p)["hatalar"])


def test_pilot_kamera_plani_render_alanlari_gecerli():
    plan = json.loads((PILOT / "cekim_plani.json").read_text())
    for c in plan["cekimler"]:
        if c["tur"] != "3d":
            continue
        assert set(c["kamera"]) <= {"plan", "hareket", "bas", "son", "yumusatma", "takip"}
        assert 10 <= c["kamera"]["bas"]["fov"] <= 70 and 10 <= c["kamera"]["son"]["fov"] <= 70
        assert kadraj.olc(c, EN_BOY)[c["meta"]["odak_indeks"]]["gorunur"]
