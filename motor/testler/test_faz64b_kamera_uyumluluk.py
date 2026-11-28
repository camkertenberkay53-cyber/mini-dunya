"""Faz-64b — kamera şeması uyumluluğu ve gerçek çeşitlilik ölçümü.

Kök neden (gerçek koşu 'KeyError: kamera', cesitlilik.kayitlar): 2.5D/harita değil, KAMERASI KURULAMAMIŞ 3D çekim.
Planlayıcı (cekim_kur) oyuncu kuramadığında (niyette rol yok — sozlesme 'aciklama'lı rolsüz 3D niyeti kabul eder) ya
da uygun kamera türü yoksa 3D çekimi 'kamera'/'ortam' olmadan döndürür; plan_denetim bunu kontrollü raporlar ama
cesitlilik (ve niyette ortam varsa uyum) KeyError ile çöküyordu → Faz-64 plan geri beslemesi hiç çalışmıyordu.

Testler önce gerçek plan yapılarıyla (depodaki pilot cekim_plani.json) çalışır; gerçek planlayıcıyla üretilen karma
planlar varlık önbelleği gerektirir ve önbellek yoksa atlanır."""
from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from motor.uretim import cesitlilik, planlayici, sahne_bolucu, uretim_hatti, uyum, veri

KOK = Path(__file__).resolve().parents[2]
PILOTLAR = KOK / "motor/uretim/pilotlar"
PILOT = PILOTLAR / "otlukbeli-1473"
_spec = importlib.util.spec_from_file_location("otonom_uret_64b", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
BOS = {"cekimler": {}}


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


def _pilot(ad="otlukbeli-1473") -> dict:
    return json.loads((PILOTLAR / ad / "cekim_plani.json").read_text())


def _c(p: dict, cid: str) -> dict:
    return next(c for c in p["cekimler"] if c["id"] == cid)


# Gerçek planlayıcı çıktısı biçiminde 2.5D ve harita çekimleri (planlayici.cekim_kur dönüşleri; 3D kamerası yok)
G25 = {"id": "S9", "cumleler": ["S9"], "sure_sn": 3.2, "tur": "gorsel25d", "amac": "olay", "metin": "Bellini portresi",
       "gorsel25d": {"gorsel_id": "g-a", "hareket": "push_in"}}
HARITA = {"id": "S10", "cumleler": ["S10"], "sure_sn": 4.0, "tur": "harita", "amac": "olay", "metin": "Ordular",
          "harita": {"evre": "E1", "veri": {}}}


# ================================================================== kök neden ve kontrollü hata

def test_kamerasiz_3d_cekim_keyerror_degil_kontrollu_hata():
    p = _pilot()
    del _c(p, "S4")["kamera"]                                                  # S4: planlayıcı kamera kuramadı
    h, r = cesitlilik.denetle(p, BOS)
    assert any(x.startswith("S4: 3D çekimde gerçek kamera yapılandırması yok") for x in h)
    assert r["kamerasiz_3d"] == ["S4"] and "S4" not in [x["id"] for x in r["sira"]]
    assert "kamera" not in _c(p, "S4")                                           # varsayılanla DOLDURULMADI


@pytest.mark.parametrize("bozuk", [None, {}, {"hareket": "itme"}, {"hareket": "itme", "bas": {"konum": [1, 2]}}, "x"])
def test_bozuk_kamera_yapilandirmasi_kontrollu_hata(bozuk):
    p = _pilot()
    p["cekimler"][0]["kamera"] = bozuk
    h, _ = cesitlilik.denetle(p, BOS)
    assert any("S1: 3D çekimde gerçek kamera yapılandırması yok" in x for x in h)


def test_kamera_turu_bilinmiyor_ya_da_render_ile_tutarsiz():
    p = _pilot()
    p["cekimler"][0]["meta"]["tur"] = "olmayan_tur"
    assert any("S1: 3D çekimin kamera türü bilinmiyor" in x for x in cesitlilik.denetle(p, BOS)[0])
    p = _pilot()
    p["cekimler"][0]["kamera"]["hareket"] = "drone"                             # türü 'itme' olan kamera
    assert any("render kamerasının hareketi (drone)" in x for x in cesitlilik.denetle(p, BOS)[0])


def test_25d_ve_harita_kamerasiz_dogru_islenir_ve_degistirilmez():
    p = _pilot()
    taban_h, taban_r = cesitlilik.denetle(copy.deepcopy(p), BOS)
    p["cekimler"] += [copy.deepcopy(G25), copy.deepcopy(HARITA)]
    h, r = cesitlilik.denetle(p, BOS)
    assert h == taban_h and r["dagilim"] == taban_r["dagilim"] and "kamerasiz_3d" not in r
    assert "kamera" not in p["cekimler"][-1] and "kamera" not in p["cekimler"][-2]   # yapay kamera eklenmedi


# ================================================================== gerçek render yapılandırmasından ölçüm

def test_yukseklik_render_kamerasindan_okunur_meta_etiketinden_degil():
    p = _pilot()
    c = p["cekimler"][0]                                                         # itme_dramatik, göz hizası 1.45 m
    c["meta"]["yukseklik"] = "yuksek"                                            # sahte etiket → sayılmaz
    r = cesitlilik.denetle(p, BOS)[1]
    assert next(x for x in r["sira"] if x["id"] == "S1")["yukseklik"] == "goz"
    c["kamera"]["bas"]["konum"][1] = 6.0                                         # gerçek render kamerası yükselir
    r = cesitlilik.denetle(p, BOS)[1]
    assert next(x for x in r["sira"] if x["id"] == "S1")["yukseklik"] == "yuksek"


def test_hareket_render_kamerasindan_aci_kamera_turunden():
    p = _pilot()
    c = p["cekimler"][0]
    c["meta"]["hareket"], c["meta"]["aci_kovasi"] = "sahte", "sahte"           # etiketler sayılmaz
    r = cesitlilik.denetle(p, BOS)[1]
    s1 = next(x for x in r["sira"] if x["id"] == "S1")
    kat = veri.kural("kamera")["cekimler"]["itme_dramatik"]
    assert s1["hareket"] == c["kamera"]["hareket"] == kat["hareket"]
    assert s1["aci_kovasi"] == planlayici._aci_kovasi(kat["aci_derece"]) and "sahte" not in r["dagilim"]["hareket"]


@pytest.mark.parametrize("ad", ["otlukbeli-1473", "roma-lejyon-kartali"])
def test_pilotlarda_yeni_olcum_eski_meta_olcumuyle_ayni(ad):
    """Geriye dönük uyumluluk: depodaki pilot planlarında render-yapılandırması ölçümü, Faz-64 meta ölçümüyle aynı."""
    p = _pilot(ad)
    h, r = cesitlilik.denetle(p, BOS)
    eski = [c["meta"] for c in p["cekimler"] if c["tur"] == "3d"]
    for alan in ("hareket", "yukseklik", "aci_kovasi"):
        assert r["dagilim"][alan] == dict(Counter(m[alan] for m in eski)), alan
    assert "kamerasiz_3d" not in r and "kamera_tekrari" not in r
    assert not [x for x in h if "farklı" in x or "hareketi çekimlerin" in x]   # eşikler pilotlarda tutuyor


# ================================================================== aynı kamera, farklı kimlik

def test_ayni_kamera_farkli_kimlikle_cesitlilik_artirmaz():
    p = _pilot()
    taban = cesitlilik.denetle(copy.deepcopy(p), BOS)[1]
    kopya = copy.deepcopy(_c(p, "S5"))                                          # S5 alcak_yaklasma
    kopya["id"], kopya["cumleler"] = "S9", ["S9"]
    p["cekimler"].append(kopya)
    h, r = cesitlilik.denetle(p, BOS)
    assert r["dagilim"] == taban["dagilim"]                                      # sayım değişmedi
    assert r["kamera_tekrari"] == [["S5", "S9"]]
    assert any("aynı render kamerası: S5, S9" in x for x in h)


def test_kopyalar_payi_ve_esikleri_sisirmez():
    """Aynı hareketin kopyaları payı düşürüp eşik aldatmasın; yeni hareket de eklemesin."""
    p = _pilot()
    uc = [c for c in p["cekimler"] if c["tur"] == "3d"]
    for i in range(6):
        k = copy.deepcopy(uc[1])
        k["id"] = k["cumleler"][0] = f"K{i}"
        p["cekimler"].append(k)
    r = cesitlilik.denetle(p, BOS)[1]
    assert sum(r["dagilim"]["hareket"].values()) == len(uc)


# ================================================================== a/b alt çekimleri

def test_ab_alt_cekimleri_ana_cekimlerle_birlikte_degerlendirilir():
    p = _pilot()
    r = cesitlilik.denetle(p, BOS)[1]
    ids = [x["id"] for x in r["sira"]]
    assert ids == [c["id"] for c in p["cekimler"] if c["tur"] == "3d"] and {"S3a", "S3b", "S8a", "S8b"} <= set(ids)
    _c(p, "S3b")["kamera"] = copy.deepcopy(_c(p, "S3a")["kamera"])            # S3b ← S3a'nın kamerası
    _c(p, "S3b")["meta"]["tur"] = _c(p, "S3a")["meta"]["tur"]
    h, _ = cesitlilik.denetle(p, BOS)
    assert any("S3a ve S3b: ardışık aynı" in x for x in h) and any("aynı render kamerası: S3a, S3b" in x for x in h)


def test_alt_cekim_gorsel_tekrari_kurallari_korunur():
    havuz = [{"gorsel_id": "a", "aciklama": "a", "sahne": "s"}]
    sen = {"format": "shorts", "cumleler": [{"id": "S1", "metin": "m", "amac": "olay",
                                             "niyet": {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "a"}, "aciklama": "x"}}]}
    cz = [{"cumle": "S1", "ses_bas_sn": 0, "ses_sure_sn": 8, "goruntu_bas_sn": 0, "goruntu_son_sn": 8.0}]
    assert [c["id"] for c in sahne_bolucu.cekimlere_bol(sen, cz, havuz)] == ["S1"]   # tek görsel → bölünmez
    assert "görsel tekrarı yasak" in (KOK / "motor/uretim/plan_denetim.py").read_text()
    assert "aynı dosyanın kopyaları" in (KOK / "otonom_uret.py").read_text()


def test_esikler_dusurulmedi():
    k = cesitlilik.esikler("shorts", 3)
    assert (k["en_az_farkli_hareket"], k["en_az_farkli_yukseklik_sinifi"], k["en_az_farkli_aci_kovasi"]) == (4, 2, 3)


# ================================================================== uyum: aynı veri akışı

def test_uyum_kamerasiz_3d_cekimde_kontrollu_hata():
    p = _pilot()
    sen = json.loads((PILOT / "senaryo.json").read_text())
    c = _c(p, "S5")
    for alan in ("kamera", "ortam", "karakterler", "meta"):
        c.pop(alan, None)
    sen["cumleler"][4]["niyet"]["ortam"] = {"arazi": "ova_cimen"}
    h, satir = uyum.denetle(sen, p, BOS)
    assert any(x.startswith("S5: S5 3D çekim kuruldu — kamera/ortam yok") for x in h)


# ================================================================== gerçek planlayıcı: karma planlar, Shorts ve uzun

def _klasor(tmp, uc, gorsel=False, kamerasiz=None, bicim="shorts"):
    d = tmp / "is"
    shutil.copytree(PILOT, d)
    s = json.loads((d / "senaryo.json").read_text())
    k = json.loads((d / "konu.json").read_text())
    k["kimlik"] = s["konu"] = "f64b"
    k["hedef_sure_sn"] = [20, 120]
    e = itertools.cycle(["E1", "E2", "E3", "E4", "E5"])
    for i, c in enumerate(s["cumleler"]):
        if i not in uc:
            c["niyet"] = {"tur": "harita", "evre": next(e), "metin": f"başlık {i}"}
    if gorsel:
        s["cumleler"][2]["niyet"] = {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "g-a"}, "aciklama": "a"}
        (d / "gorsel_havuzu.json").write_text(json.dumps([{"gorsel_id": "g-a", "aciklama": "a", "sahne": "s"},
                                                          {"gorsel_id": "g-b", "aciklama": "b", "sahne": "s"}]))
    if kamerasiz is not None:
        s["cumleler"][kamerasiz]["niyet"] = {"tur": "3d", "aciklama": "Akkoyunlu ordusu ovada", "ortam": {"arazi": "ova_cimen"}}
    if bicim == "uzun":
        k["format"] = s["format"] = "uzun"
        s["bolumler"] = [{"id": "B1", "baslik": "Bölüm 1", "roller": ["kanca"]}]
        for c in s["cumleler"]:
            c["bolum"] = "B1"
    ms = {s["cumleler"][i]["niyet"].get("mesafe", "orta") for i in uc if i != kamerasiz}
    if len(ms) < 2:
        s["cumleler"][uc[-1]]["niyet"]["mesafe"] = "orta" if "uzak" in ms else "uzak"
    (d / "senaryo.json").write_text(json.dumps(s, ensure_ascii=False))
    (d / "konu.json").write_text(json.dumps(k, ensure_ascii=False))
    return d


@ONBELLEK
def test_karma_plan_3d_25d_harita_ab_gercek_planlayici(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / f"{gid}.jpg", {}))
    d = _klasor(tmp_path, (1, 3, 7), gorsel=True)
    r = uretim_hatti.planla(d)                                                   # KeyError yok
    plan = json.loads((d / "cekim_plani.json").read_text())
    turler = {c["tur"] for c in plan["cekimler"]}
    ab = [c["id"] for c in plan["cekimler"] if c["id"][-1] in "ab"]
    assert {"3d", "gorsel25d", "harita"} <= turler and ab
    assert r["hatalar"]["cesitlilik"] == [] and r["hatalar"]["plan_denetimi"] == []
    assert all("kamera" not in c for c in plan["cekimler"] if c["tur"] != "3d")
    ids = [x["id"] for x in r["cesitlilik"]["sira"]]
    assert ids == [c["id"] for c in plan["cekimler"] if c["tur"] == "3d"]


@ONBELLEK
@pytest.mark.parametrize("bicim", ["shorts", "uzun"])
def test_rolsuz_3d_niyet_plan_kontrollu_hatayla_biter(tmp_path, bicim):
    """Gerçek koşu senaryosu: sozlesme'den geçen rolsüz 3D niyet → planlama KeyError'sız biter; hatalar Faz-64 plan
    geri beslemesinin yeniden denediği kategorilerde (plan_denetimi / cesitlilik / uyum)."""
    d = _klasor(tmp_path, (1, 3, 5, 7), kamerasiz=3, bicim=bicim)
    r = uretim_hatti.planla(d)
    assert not r["gecti"]
    assert "S4: 3D çekimde 'kamera' yok" in r["hatalar"]["plan_denetimi"]
    assert any(x.startswith("S4: 3D çekimde gerçek kamera yapılandırması yok") for x in r["hatalar"]["cesitlilik"])
    assert any("S4 3D çekim kuruldu" in x for x in r["hatalar"]["uyum"])
    assert {a for a, b in r["hatalar"].items() if b} <= {"plan_denetimi", "cesitlilik", "uyum", "anlati", "sure"}


@ONBELLEK
@pytest.mark.parametrize("ad", ["otlukbeli-1473", "roma-lejyon-kartali"])
def test_pilot_planlari_ve_cesitlilik_raporu_degismedi(tmp_path, ad):
    d = tmp_path / ad
    shutil.copytree(PILOTLAR / ad, d)
    r = uretim_hatti.planla(d)
    eski = json.loads((PILOTLAR / ad / "plan_raporu.json").read_text())
    assert r["gecti"] and (d / "cekim_plani.json").read_text() == (PILOTLAR / ad / "cekim_plani.json").read_text()
    assert r["cesitlilik"] == eski["cesitlilik"]


@ONBELLEK
def test_otonom_plan_geri_beslemesi_kamerasiz_hatayi_yeniden_dener(tmp_path, monkeypatch):
    """KeyError yerine kontrollü hata → otonom planla bunu senaryoya geri besler (Faz-64 döngüsü artık çalışır)."""
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "g")
    monkeypatch.setattr(ou, "senaryo_denetle", lambda *a, **k: [])
    monkeypatch.setattr(ou, "gorsel_sha", lambda gid: None)
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    d = _klasor(tmp_path / "x", (1, 3, 5, 7), kamerasiz=3)
    kotu = json.loads((d / "senaryo.json").read_text())
    iyi_d = _klasor(tmp_path / "y", (1, 3, 5, 7))
    iyi = json.loads((iyi_d / "senaryo.json").read_text())

    class Sahte:
        def __init__(self):
            self.yan, self.istemler, self.cagri_sayisi = [[], kotu, iyi], [], 0

        def tamamla(self, istem, adim, baglam):
            self.istemler.append(istem)
            self.cagri_sayisi += 1
            return json.dumps(self.yan.pop(0), ensure_ascii=False)
    s = Sahte()
    kayit = {"id": "ark_1", "durum": "dogrulanmis", "iddia": "i", "bagimsiz_kaynak_sayisi": 2,
             "kaynaklar": [{"id": "w", "eser": "w", "url": "u", "tur": "ansiklopedi"}, {"id": "t", "eser": "t", "url": "u", "tur": "x"}]}

    def planla_fn(is_):
        k = json.loads((is_ / "konu.json").read_text())
        k.update(hedef_sure_sn=[20, 120])
        (is_ / "konu.json").write_text(json.dumps(k, ensure_ascii=False))
        a = json.loads((PILOT / "arastirma.json").read_text())
        a["konu"] = k["kimlik"]
        (is_ / "arastirma.json").write_text(json.dumps(a, ensure_ascii=False))
        sen = json.loads((is_ / "senaryo.json").read_text())
        sen["konu"] = k["kimlik"]
        (is_ / "senaryo.json").write_text(json.dumps(sen, ensure_ascii=False))
        return uretim_hatti.planla(is_)
    r = ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [kayit]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {}, planla_fn=planla_fn, olc=lambda cs: {})
    assert r["isler"][0]["plan_turu"] == 2
    assert "ÇEKİM PLANI KAPISI (cesitlilik): S4: 3D çekimde gerçek kamera yapılandırması yok" in s.istemler[2]
