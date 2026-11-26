"""Savaş anlatımı paketi: taktik harita (harita.py), el kamerası / drone çekimleri, olaya bağlı efektler (ok yağmuru,
yangın, kıvılcım) ve kalabalıkta gerçekçi kişiler."""
import copy
import json
import subprocess

import numpy as np
import pytest

from motor import ayar
from motor.uretim import harita, planlayici, render, sozlesme, veri

KONU = ayar.MOTOR / "uretim/pilotlar/otlukbeli-1473/konu.json"
GODOT = ayar.MOTOR / "godot/sahneler"


def _harita():
    return json.loads(KONU.read_text())["harita"]


def test_konu_harita_verisi_kaynakli_ve_tutarli():
    h = _harita()
    assert "kaynak" in h and h["kaynak"]
    for e in h["evreler"]:
        for b in e["birlikler"]:
            assert b["taraf"] in h["taraflar"], (e["id"], b["id"])
            assert 0 <= b["konum"][0] <= h["alan_km"][0] and 0 <= b["konum"][1] <= h["alan_km"][1]
        for o in e.get("oklar", []):
            assert o["taraf"] in h["taraflar"] and len(o["yol"]) >= 2
            assert o.get("tur", "saldiri") in ("saldiri", "geri_cekilme", "kacis")


def test_harita_karesi_ilerler_ve_kamera_yaklasir():
    h = harita.Harita(_harita())
    ev, on = harita.evre_bul(_harita(), "E5")
    a = np.asarray(harita.kare(h, ev, on, 0.0, None).convert("RGB"), np.float32)
    b = np.asarray(harita.kare(h, ev, on, 1.0, None).convert("RGB"), np.float32)
    assert a.shape == (1920, 1080, 3)
    assert np.abs(a - b).mean() > 2.0                     # oklar çizilir, birlikler kayar, kamera yaklaşır


def test_harita_cekimi_planlanir_veri_yoksa_uydurulmaz():
    t = {"id": "S1", "cumle": "S1", "sure_sn": 3.0, "niyet": {"tur": "harita", "evre": "E3"}, "amac": "olay"}
    c, eks, _ = planlayici.cekim_kur(t, "osmanli-15yy", 1080 / 1920, [], 1, harita=_harita())
    assert not eks and c["harita"]["evre"] == "E3" and c["metin"]
    c, eks, _ = planlayici.cekim_kur(dict(t, niyet={"tur": "harita", "evre": "E99"}), "osmanli-15yy", 1080 / 1920, [], 1,
                                     harita=_harita())
    assert eks and "E99" in eks[0]
    c, eks, _ = planlayici.cekim_kur(t, "osmanli-15yy", 1080 / 1920, [], 1, harita=None)
    assert eks                                            # konu verisi yoksa harita çizilmez, eksik raporlanır


def test_harita_render_mp4(tmp_path):
    out = tmp_path / "h.mp4"
    r = harita.render(_harita(), "E2", 0.5, out, 30, (1080, 1920))
    assert r["kare"] == 15 and out.exists()
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json",
                        str(out)], capture_output=True, text=True)
    s = json.loads(p.stdout)["streams"][0]
    assert (s["width"], s["height"]) == (1080, 1920)


def test_sozlesme_harita_evresini_icerik_sayar():
    yol = ayar.MOTOR / "uretim/pilotlar/otlukbeli-1473"
    s = json.loads((yol / "senaryo.json").read_text())
    a = json.loads((yol / "arastirma.json").read_text())
    s2 = copy.deepcopy(s)
    s2["cumleler"][2]["niyet"] = {"tur": "harita", "evre": "E3"}
    assert not any("içeriği yok" in h for h in sozlesme.senaryo_denetle(s2, a))
    s2["cumleler"][2]["niyet"] = {"tur": "harita"}
    assert any("içeriği yok" in h for h in sozlesme.senaryo_denetle(s2, a))   # boş harita niyeti hâlâ hata


def test_el_kamerasi_ve_drone_kayitli():
    k = veri.kural("kamera")
    assert k["cekimler"]["el_kamerasi"]["sarsinti"]["derece"] <= 1.2      # aşırı sarsıntı yok
    assert "el_kamerasi" in k["eylem_kamera"]["olum"]["yasak"]            # ölüm dramatize edilmez
    for e in ("savas", "carpisma", "kilic_saldirisi"):
        assert k["eylem_kamera"][e]["once"][0] == "el_kamerasi"
    assert k["cekimler"]["drone_gecis"]["hareket"] == "drone" and "drone_gecis" in k["kalabalik_kamera"]["once"]
    odak = {"konum": [0, 0], "yon_derece": 0, "hiz_m_sn": 0.0, "animasyon": "Idle_Loop"}
    kam = planlayici.kamera_kur("el_kamerasi", odak, 3.0, 0.5)
    assert kam["sarsinti"]["derece"] > 0
    d = planlayici.kamera_kur("drone_gecis", odak, 4.0, 0.11)
    assert d["bas"]["konum"][1] > 8 and d["bas"]["konum"] != d["son"]["konum"]
    assert "sarsinti" not in planlayici.kamera_kur("yan_profil", odak, 3.0, 0.5)
    s = json.loads((ayar.MOTOR / "uretim/semalar/cekim_plani.schema.json").read_text())
    assert "sarsinti" in s["properties"]["cekimler"]["items"]["properties"]["kamera"]["properties"]
    assert "rotate_object_local" in (GODOT / "cekim.gd").read_text()


def test_efektler_niyetten_kurala_bagli():
    v = veri.kural("gorsel")["vfx"]
    assert set(v["efektler"]) == {"ok_yagmuru", "yangin"}
    for d in ("alev_doku", "duman_doku"):
        assert (ayar.MOTOR / v["yangin"][d]).exists()
    assert (ayar.MOTOR / v["kivilcim"]["doku"]).exists()
    t = {"id": "S1", "cumle": "S1", "sure_sn": 3.0, "amac": "olay",
         "niyet": {"tur": "3d", "roller": [{"rol": "piyade", "adet": 3, "odak": True}], "eylem": "bekleme", "mesafe": "orta",
                   "ortam": {"arazi": "ova_cimen", "isik": "oglen_acik", "efekt": ["ok_yagmuru", "meteor"]}}}
    c, eks, _ = planlayici.cekim_kur(t, "osmanli-15yy", 1080 / 1920, [], 1)
    assert c["ortam"]["efekt"] == ["ok_yagmuru"]
    assert any("meteor" in e for e in eks)                 # kuralı olmayan efekt uydurulmaz
    g = (GODOT / "vfx.gd").read_text()
    for f in ("func ok_yagmuru", "func ok_guncelle", "func yangin", "func kivilcim"):
        assert f in g


def test_kivilcim_duello_ciftlerinden():
    from motor.uretim import koreografi
    c = {"karakterler": [{"takim": "osm_yeniceri_kilic", "rol": "piyade", "konum": [i * 1.5, 0.0], "yon_derece": 0.0,
                          "animasyon": "Sword_Idle"} for i in range(4)]}
    _, meta = koreografi.uygula(c, 0, "savas", "osmanli-15yy", ["osmanli-15yy", "akkoyunlu-15yy"], "orta", 11)
    assert len(meta["ciftler"]) == meta["cift"] and all(len(x) == 2 for x in meta["ciftler"])
    assert "ciftler" in (GODOT / "cekim.gd").read_text()


def test_kalabalik_gercekci_kisiler():
    k = veri.kural("kalabalik")["kalabaliklar"]["ordu"]
    assert k["kisi_carpani"] >= 2
    g = (GODOT / "kalabalik.gd").read_text()
    assert 'k.get("gercekci", false)' in g and 'tk["glb"] = ks[' in g
    assert 'k["gercekci"] = _insan_acik()' in (ayar.MOTOR / "uretim/render.py").read_text()
