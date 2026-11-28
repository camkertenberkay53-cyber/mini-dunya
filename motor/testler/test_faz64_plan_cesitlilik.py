"""Faz-64 — çekim planlayıcı: alt çekim / görsel tekrarı ve 3D çeşitlilik. Doğrulayıcılar (plan_denetim, cesitlilik
eşikleri) GEVŞETİLMEDİ; plan gerçekten farklı görüntüler üretecek biçimde kurulur.

- Bölücü: uzun cümle yalnız ikinci çekim gerçekten farklıysa bölünür (3D: kamera türü; 2.5D: havuzdan kullanılmamış
  ilgili görsel + farklı hareket; harita: bölünmez).
- Planlayıcı: çeşitlilik eşiğine yer kalmadıysa yeni hareket/yükseklik/açı getiren kamera türü önce denenir; bir
  hareketin payını kesin aşacak tür sona alınır. Pilot planları bayt bayt aynı kalır.
- Otonom Shorts: harita başlık tekrarı, ≥4 3D çekim ve ≥2 farklı 3D mesafe senaryo kapısında; plan kapısı hataları
  sınırlı sayıda senaryoya geri beslenir; aynı dosyanın kopyaları (SHA-256) reddedilir.
Varlık önbelleği gerektiren (gerçek planlayıcı) testler önbellek yoksa atlanır."""
from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import shutil
from pathlib import Path

import pytest

from motor.uretim import cesitlilik, plan_denetim, planlayici, sahne_bolucu, uretim_hatti, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_64", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOTLAR = KOK / "motor/uretim/pilotlar"
PILOT = PILOTLAR / "otlukbeli-1473"


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


# ================================================================== bölücü (Shorts)

def _cz(*sureler):
    t, z = 0.0, []
    for i, s in enumerate(sureler, 1):
        z.append({"cumle": f"S{i}", "ses_bas_sn": t, "ses_sure_sn": s, "goruntu_bas_sn": t, "goruntu_son_sn": t + s})
        t += s
    return z


def _sen(*niyetler, metin="Uzun Hasan'ın süvarileri tepelerden indi."):
    return {"format": "shorts", "cumleler": [{"id": f"S{i}", "metin": metin, "niyet": n, "amac": "olay"}
                                             for i, n in enumerate(niyetler, 1)]}


G25 = {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "a"}, "aciklama": "a portre"}
HAVUZ = [{"gorsel_id": "a", "aciklama": "Uzun Hasan portresi", "sahne": "taraflar"},
         {"gorsel_id": "b", "aciklama": "Venedik elçileri", "sahne": "taraflar"},
         {"gorsel_id": "c", "aciklama": "Akkoyunlu süvarileri minyatürü", "sahne": "savas"},
         {"gorsel_id": "d", "aciklama": "Deniz savaşı tablosu", "sahne": "baska"}]


def _ids(cekimler):
    return [c["id"] for c in cekimler]


def test_uzun_harita_bolunmez():
    c = sahne_bolucu.cekimlere_bol(_sen({"tur": "harita", "evre": "E1"}), _cz(8.0), HAVUZ)
    assert _ids(c) == ["S1"] and c[0]["sure_sn"] == 8.0


def test_uzun_3d_eskisi_gibi_ikiye_bolunur_kisa_bolunmez():
    c = sahne_bolucu.cekimlere_bol(_sen({"tur": "3d"}, {"tur": "3d"}), _cz(8.0, 4.0), HAVUZ)
    assert _ids(c) == ["S1a", "S1b", "S2"] and c[0]["niyet"] is c[1]["niyet"]


def test_uzun_25d_ikinci_cekim_havuzdan_farkli_gorsel_ve_hareket():
    c = sahne_bolucu.cekimlere_bol(_sen(copy.deepcopy(G25)), _cz(8.0), HAVUZ)
    assert _ids(c) == ["S1a", "S1b"]
    a, b = c[0]["niyet"], c[1]["niyet"]
    assert a == G25                                                              # ilk çekim cümlenin kendi niyeti
    assert b["gorsel25d"]["gorsel_id"] == "b" and b["aciklama"] == "Venedik elçileri"   # aynı sahne etiketi
    assert b["gorsel25d"]["hareket"] != a["gorsel25d"].get("hareket", "zoom_in")
    assert b["gorsel25d"]["hareket"] in sahne_bolucu.G25_HAREKET_SIRASI


def test_ilgi_kelime_kokuyle_de_kurulur():
    havuz = [HAVUZ[0], {"gorsel_id": "x", "aciklama": "Süvari birliği minyatürü", "sahne": "baska"}]
    c = sahne_bolucu.cekimlere_bol(_sen(copy.deepcopy(G25)), _cz(8.0), havuz)
    assert c[1]["niyet"]["gorsel25d"]["gorsel_id"] == "x"                       # "süvarileri" ~ "Süvari"


def test_ilgisiz_ya_da_kullanilmis_gorsel_yoksa_tek_cekim():
    havuz = [HAVUZ[0], HAVUZ[3]]                                                # yalnız ilgisiz kaldı
    assert _ids(sahne_bolucu.cekimlere_bol(_sen(copy.deepcopy(G25)), _cz(8.0), havuz)) == ["S1"]
    s = _sen(copy.deepcopy(G25), {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "b"}, "aciklama": "x"})
    c = sahne_bolucu.cekimlere_bol(s, _cz(8.0, 3.0), HAVUZ[:2])                 # b başka cümlede kullanılıyor
    assert _ids(c) == ["S1", "S2"]


def test_ayni_sahnedeki_iki_cumle_ayni_havuz_gorselini_alamaz():
    havuz = [HAVUZ[0], {"gorsel_id": "a2", "aciklama": "Uzun Hasan otağı", "sahne": "taraflar"}, HAVUZ[1]]
    s = _sen(copy.deepcopy(G25), {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "a2"}, "aciklama": "x"})
    c = sahne_bolucu.cekimlere_bol(s, _cz(8.0, 8.0), havuz)
    assert _ids(c) == ["S1a", "S1b", "S2"] and c[1]["niyet"]["gorsel25d"]["gorsel_id"] == "b"   # b yalnız bir kez


def test_havuz_yoksa_25d_bolunmez():
    assert _ids(sahne_bolucu.cekimlere_bol(_sen(copy.deepcopy(G25)), _cz(8.0))) == ["S1"]


def test_tek_havuz_gorseli_iki_cumleye_verilmez():
    s = _sen(copy.deepcopy(G25), {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "c"}, "aciklama": "c"})
    c = sahne_bolucu.cekimlere_bol(s, _cz(8.0, 8.0), HAVUZ[:3])
    ikinci = [x["niyet"]["gorsel25d"]["gorsel_id"] for x in c if x["parca"] == 1]
    assert ikinci == ["b"] and _ids(c) == ["S1a", "S1b", "S2"]                 # c'nin sahnesinde boş görsel yok
    tum = [x["niyet"]["gorsel25d"]["gorsel_id"] for x in c]
    assert len(tum) == len(set(tum))                                             # hiçbir görsel iki kez yok


def test_bolucu_belirlenimci_ve_kapsama_bosluksuz():
    s = _sen(copy.deepcopy(G25), {"tur": "3d"}, {"tur": "harita", "evre": "E1"})
    a = sahne_bolucu.cekimlere_bol(s, _cz(8.0, 7.0, 9.0), HAVUZ)
    assert a == sahne_bolucu.cekimlere_bol(copy.deepcopy(s), _cz(8.0, 7.0, 9.0), copy.deepcopy(HAVUZ))
    assert abs(sum(x["sure_sn"] for x in a) - 24.0) < 0.01


def test_uzun_bicim_bolucusu_degismedi():
    s = dict(_sen(copy.deepcopy(G25), {"tur": "3d"}), format="uzun")
    for c in s["cumleler"]:
        c["bolum"] = "B1"
    c = sahne_bolucu.cekimlere_bol(s, _cz(14.0, 20.0), HAVUZ)
    assert _ids(c)[0] == "S1" and [x["cumle"] for x in c].count("S2") == 3


# ================================================================== kapsama önceliği (gerçek kamera.yaml değerleri)

def _kayit(ad):
    x = veri.kural("kamera")["cekimler"][ad]
    return {"tur": ad, "hareket": x["hareket"], "yukseklik": planlayici._yukseklik_sinifi(x["yukseklik_m"]),
            "aci_kovasi": planlayici._aci_kovasi(x["aci_derece"])}


def test_kapsama_esik_rahatken_sifir_daralinca_yeni_deger():
    esik = cesitlilik.esikler("shorts", 4)
    kat = veri.kural("kamera")["cekimler"]
    gecmis = [_kayit("alcak_yaklasma")]
    assert all(planlayici.kapsama_kazanci(ad, gecmis, {"kalan": 9, "toplam": 10, "esik": esik}) == 0 for ad in kat)
    kaz = {ad: planlayici.kapsama_kazanci(ad, gecmis, {"kalan": 3, "toplam": 4, "esik": esik}) for ad in kat}
    assert kaz["alcak_yaklasma"] <= 0 < max(kaz.values())
    yeni = [ad for ad, k in kaz.items() if k > 0]
    assert all(_kayit(ad)["hareket"] != gecmis[0]["hareket"] for ad in yeni)


def test_kapsama_hedefsiz_ise_siralama_faz5_ile_ayni():
    gecmis = [_kayit("alcak_yaklasma"), _kayit("yan_takip")]
    a = planlayici.cekim_turu_adaylari("orta", True, gecmis, 2)
    b = planlayici.cekim_turu_adaylari("orta", True, gecmis, 2, cesitlilik_hedefi=None)
    c = planlayici.cekim_turu_adaylari("orta", True, gecmis, 2, cesitlilik_hedefi={"kalan": 0, "toplam": 0,
                                                                                    "esik": cesitlilik.esikler("shorts", 0)})
    assert a == b == c


def test_hareket_payini_asacak_tur_sona():
    esik = cesitlilik.esikler("shorts", 4)
    gecmis = [_kayit("alcak_yaklasma")]
    h = gecmis[0]["hareket"]
    ayni = [ad for ad in veri.kural("kamera")["cekimler"] if _kayit(ad)["hareket"] == h]
    for ad in ayni:   # 2/4 = %50 > %34 → kesin ihlal
        assert planlayici.kapsama_kazanci(ad, gecmis, {"kalan": 3, "toplam": 4, "esik": esik}) <= -10


def test_cesitlilik_esikleri_tek_kaynak_davranis_ayni():
    k = veri.kural("cesitlilik")
    assert cesitlilik.esikler("shorts", 3) == k and cesitlilik.esikler(None, 1) == k
    u = cesitlilik.esikler("uzun", 2)
    assert u["en_az_farkli_hareket"] == 1 and u["bir_hareketin_en_cok_payi"] == 1.0


# ================================================================== gerçek planlayıcı

def _plan_klasoru(tmp, uc, mesafe_cesitli=True, uzun_25d=False, havuz=None):
    d = tmp / "is"
    shutil.copytree(PILOT, d)
    s = json.loads((d / "senaryo.json").read_text())
    k = json.loads((d / "konu.json").read_text())
    k["kimlik"] = s["konu"] = "faz64"
    k["hedef_sure_sn"] = [20, 60]
    e = itertools.cycle(["E1", "E2", "E3", "E4", "E5"])
    for i, c in enumerate(s["cumleler"]):
        if i not in uc:
            c["niyet"] = {"tur": "harita", "evre": next(e), "metin": f"başlık {i}"}
    if uzun_25d:
        s["cumleler"][2]["niyet"] = {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "g-a"}, "aciklama": "a"}
    if mesafe_cesitli:
        ms = {s["cumleler"][i]["niyet"].get("mesafe", "orta") for i in uc}
        if len(ms) < 2:
            s["cumleler"][uc[-1]]["niyet"]["mesafe"] = "orta" if "uzak" in ms else "uzak"
    (d / "senaryo.json").write_text(json.dumps(s, ensure_ascii=False))
    (d / "konu.json").write_text(json.dumps(k, ensure_ascii=False))
    if havuz is not None:
        (d / "gorsel_havuzu.json").write_text(json.dumps(havuz, ensure_ascii=False))
    return d


@ONBELLEK
@pytest.mark.parametrize("ad", ["otlukbeli-1473", "roma-lejyon-kartali"])
def test_pilot_planlari_bayt_bayt_ayni(tmp_path, ad):
    d = tmp_path / ad
    shutil.copytree(PILOTLAR / ad, d)
    r = uretim_hatti.planla(d)
    assert r["gecti"] and (d / "cekim_plani.json").read_text() == (PILOTLAR / ad / "cekim_plani.json").read_text()


def _esikler_gercek_parametrelerle(plan):
    uc_c = [c for c in plan["cekimler"] if c["tur"] == "3d"]
    kat = veri.kural("kamera")["cekimler"]
    hareket = {kat[c["meta"]["tur"]]["hareket"] for c in uc_c}
    yukseklik = {planlayici._yukseklik_sinifi(kat[c["meta"]["tur"]]["yukseklik_m"]) for c in uc_c}
    aci = {planlayici._aci_kovasi(kat[c["meta"]["tur"]]["aci_derece"]) for c in uc_c}
    return uc_c, kat, hareket, yukseklik, aci


@ONBELLEK
def test_karisik_shorts_butun_kombinasyonlar_plan_denetim_ve_cesitlilik(tmp_path):
    """Gerçek koşu deseni: uzun harita cümleleri + az 3D (eski bölücü/planlayıcı: 'S3b: S3a ile aynı çekim' ve
    'farklı hareket/yükseklik/açı' hataları). 8 pilot cümlesinden 3'ü 3D (56 kombinasyon), 3D'de iki mesafe:
    ≥4 3D çekimde plan_denetim + çeşitlilik 0 hata ve eşikler GERÇEK kamera parametreleriyle; <4'te doğrulayıcı hâlâ
    yakalar (gevşetilmedi) ve otonom senaryo kapısı bu senaryoyu plana hiç göndermez."""
    gecen, yakalanan = 0, 0
    for n, uc in enumerate(itertools.combinations(range(8), 3)):
        d = _plan_klasoru(tmp_path / str(n), uc)
        r = uretim_hatti.planla(d)
        plan = json.loads((d / "cekim_plani.json").read_text())
        assert r["hatalar"]["plan_denetimi"] == [], (uc, r["hatalar"]["plan_denetimi"])
        assert len({plan_denetim.imza(c) for c in plan["cekimler"]}) == len(plan["cekimler"])
        uc_c, kat, hareket, yukseklik, aci = _esikler_gercek_parametrelerle(plan)
        if len(uc_c) >= ou._shorts_3d_esik()[0]:
            assert r["hatalar"]["cesitlilik"] == [], (uc, r["hatalar"]["cesitlilik"])
            assert len(hareket) >= 4 and len(yukseklik) >= 2 and len(aci) >= 3, uc
            # etiket değil gerçek render parametresi: kamera hareketi kataloğa bağlı, konumlar birbirinden farklı
            assert all(c["kamera"]["hareket"] == kat[c["meta"]["tur"]]["hareket"] for c in uc_c)
            konumlar = [json.dumps(c["kamera"], sort_keys=True) for c in uc_c]
            assert len(set(konumlar)) == len(konumlar)
            gecen += 1
        else:
            assert r["hatalar"]["cesitlilik"], uc                                # doğrulayıcı gevşetilmedi
            yakalanan += 1
    assert gecen >= 30 and gecen + yakalanan == 56


@ONBELLEK
def test_cesitlilik_belirlenimci_ayni_girdi_ayni_plan(tmp_path):
    a = _plan_klasoru(tmp_path / "a", (1, 3, 7))
    b = _plan_klasoru(tmp_path / "b", (1, 3, 7))
    uretim_hatti.planla(a)
    uretim_hatti.planla(b)
    assert (a / "cekim_plani.json").read_text() == (b / "cekim_plani.json").read_text()


@ONBELLEK
def test_uc_3d_cekimle_esik_matematiksel_olarak_imkansiz_kapi_bunu_yakalar(tmp_path):
    d = _plan_klasoru(tmp_path, (0, 4, 5))
    r = uretim_hatti.planla(d)
    plan = json.loads((d / "cekim_plani.json").read_text())
    n = sum(c["tur"] == "3d" for c in plan["cekimler"])
    assert n < 4 and any("farklı hareket sayısı" in x for x in r["hatalar"]["cesitlilik"])   # doğrulayıcı gevşetilmedi


@ONBELLEK
def test_uzun_25d_cumlesi_havuzla_iki_farkli_gorsel_havuzsuz_tek_cekim(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / f"{gid}.jpg", {}))
    havuz = [{"gorsel_id": "g-a", "aciklama": "a", "sahne": "s"}, {"gorsel_id": "g-b", "aciklama": "Tercan ovası", "sahne": "s"}]
    d = _plan_klasoru(tmp_path / "1", (1, 3, 7), uzun_25d=True, havuz=havuz)
    r = uretim_hatti.planla(d)
    plan = json.loads((d / "cekim_plani.json").read_text())
    g = [(c["id"], c["gorsel25d"]["gorsel_id"], c["gorsel25d"].get("hareket")) for c in plan["cekimler"] if c["tur"] == "gorsel25d"]
    s3 = next(c for c in plan["cekimler"] if c["cumleler"] == ["S3"])
    assert s3["sure_sn"] > 2.5                                                   # pilot S3 > 5 sn (pilot de böler)
    assert [x[0] for x in g] == ["S3a", "S3b"] and [x[1] for x in g] == ["g-a", "g-b"] and g[0][2] != g[1][2]
    assert r["hatalar"]["plan_denetimi"] == []
    d2 = _plan_klasoru(tmp_path / "2", (1, 3, 7), uzun_25d=True)
    r2 = uretim_hatti.planla(d2)
    g2 = [c for c in json.loads((d2 / "cekim_plani.json").read_text())["cekimler"] if c["tur"] == "gorsel25d"]
    assert len(g2) == 1 and r2["hatalar"]["plan_denetimi"] == []


# ================================================================== otonom Shorts senaryo kapıları

def _olc(cs):
    return {c["id"]: {"sure_sn": 6.0 if c["niyet"]["tur"] == "3d" else 4.0, "harf_sn": 14, "motor": "s", "wav": "x"}
            for c in cs}


@pytest.fixture
def kapilar(monkeypatch):
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    return ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")


def _c(i, tur="3d", **n):
    return {"id": f"S{i}", "metin": "m", "kartlar": ["C1"], "niyet": {"tur": tur, **n}}


def test_harita_baslik_tekrari_reddedilir_farkli_baslik_kabul(kapilar):
    k = kapilar
    s = {"format": "shorts", "cumleler": [_c(1, "harita", evre="E1", metin="Ordular"), _c(2, "harita", evre="E1", metin="Ordular"),
                                          _c(3, mesafe="orta"), _c(4, mesafe="uzak")]}
    h = ou.senaryo_denetle(s, {}, k, [], _olc)
    assert any("S2: S1 ile aynı harita" in x for x in h)
    s["cumleler"][1]["niyet"]["metin"] = "Kanatlar çöküyor"
    assert not any("aynı harita" in x for x in ou.senaryo_denetle(s, {}, k, [], _olc))
    s["cumleler"][1]["niyet"].pop("metin")
    s["cumleler"][0]["niyet"].pop("metin")
    assert any("aynı harita" in x for x in ou.senaryo_denetle(s, {}, k, [], _olc))   # başlıksız ikisi de evre başlığı


def test_3d_mesafe_cesitliligi_zorunlu(kapilar):
    s = {"format": "shorts", "cumleler": [_c(1, mesafe="uzak"), _c(2, mesafe="uzak"), _c(3, mesafe="uzak")]}
    h = ou.senaryo_denetle(s, {}, kapilar, [], _olc)
    assert any("1 farklı mesafe" in x for x in h)


def test_en_az_dort_3d_cekim_gercek_bolucu_ve_tts_suresiyle(kapilar):
    k = dict(kapilar, hedef_sure_sn=[1, 100])
    az = {"format": "shorts", "cumleler": [_c(1, mesafe="orta"), _c(2, mesafe="uzak"), _c(3, "harita", evre="E1")]}
    olc_kisa = lambda cs: {c["id"]: {"sure_sn": 3.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}
    h = ou.senaryo_denetle(az, {}, k, [], olc_kisa)
    assert h and "2 3D çekim" in h[0] and "en az 4" in h[0]
    olc_uzun = lambda cs: {c["id"]: {"sure_sn": 6.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}
    assert ou.senaryo_denetle(az, {}, k, [], olc_uzun) == []                    # iki uzun 3D cümle → 4 çekim
    assert ou._shorts_3d_esik() == (veri.kural("cesitlilik")["en_az_farkli_hareket"],
                                    veri.kural("cesitlilik")["en_az_farkli_plan_olcegi"])


def test_istem_3d_cesitlilik_ve_harita_basligi_kurali():
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    m = ou.gorsel_kurallari(k, [])
    assert "3D ÇEŞİTLİLİK" in m and "en az 4 3D çekim" in m and "'orta'" in m and "'uzak'" in m
    assert "BENZERSİZ harita başlığı" in m and "FARKLI 'metin'" in m


# ================================================================== otonom planla: yeniden deneme, havuz, kopyalar

class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.istemler, self.cagri_sayisi = list(yanitlar), [], 0

    def tamamla(self, istem, adim, baglam):
        self.istemler.append((adim, istem))
        self.cagri_sayisi += 1
        y = self.yanitlar.pop(0)
        return y if isinstance(y, str) else json.dumps(y, ensure_ascii=False)


def _kayit_h(i):
    return {"id": f"ark_{i}", "durum": "dogrulanmis", "iddia": f"iddia {i}", "bagimsiz_kaynak_sayisi": 2,
            "kaynaklar": [{"id": f"wp_{i}", "eser": "w", "url": "u", "tur": "ansiklopedi"},
                          {"id": f"t_{i}", "eser": "t", "url": "u", "tur": "ansiklopedi"}]}


@pytest.fixture
def otonom(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "g")
    monkeypatch.setattr(ou, "senaryo_denetle", lambda *a, **k: [])
    monkeypatch.setattr(ou, "gorsel_sha", lambda gid: None)
    return tmp_path


SORGU = [{"gorsel_id": f"g{i}", "sorgu": f"q{i}", "aciklama": f"görsel {i}", "sahne": "s"} for i in range(4)]
KIM = "otlukbeli-1473-oto"


def _shorts_sen():
    return {"cumleler": [{"id": f"S{i + 1}", "metin": "m", "kartlar": ["C1"], "niyet": {
        "tur": "gorsel25d", "gorsel25d": {"gorsel_id": f"{KIM}-g{i}"}, "aciklama": f"a{i}"}} for i in range(3)],
        "kanca": "S1", "final": "S3"}


def _topla(q, h):
    return {"lisans_turu": "PD-Old", "toplama": {"baslik": f"File:{q['gorsel_id']}"}}


def _planla_sahte(sirali_sonuclar, b_gorseli=None):
    cagri = []

    def f(is_):
        cagri.append(json.loads((is_ / "gorsel_havuzu.json").read_text()))
        sen = json.loads((is_ / "senaryo.json").read_text())
        ck = [{"id": c["id"], "tur": c["niyet"]["tur"], "sure_sn": 4.0, "cumleler": [c["id"]],
               **({"gorsel25d": c["niyet"]["gorsel25d"]} if c["niyet"].get("gorsel25d") else {})} for c in sen["cumleler"]]
        if b_gorseli:
            ck.append({"id": "S1b", "tur": "gorsel25d", "sure_sn": 4.0, "cumleler": ["S1"], "gorsel25d": {"gorsel_id": b_gorseli}})
        (is_ / "cekim_plani.json").write_text(json.dumps({"konu": sen["konu"], "cekimler": ck}))
        h = sirali_sonuclar.pop(0)
        return {"gecti": not h, "hatalar": h, "toplam_sure_sn": 50.0}
    return f, cagri


def test_plan_kapisi_hatalari_senaryoya_geri_beslenir_sonra_gecer(otonom):
    s = Sahte([SORGU, _shorts_sen(), _shorts_sen()])
    planla_fn, cagri = _planla_sahte([{"cesitlilik": ["farklı hareket sayısı 3; en az 4"]}, {}])
    r = ou.planla("Otlukbeli Savaşı", "shorts", otonom / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit_h(1)]},
                  saglayici_fn=lambda: s, topla=_topla, planla_fn=planla_fn, olc=lambda cs: {})
    assert r["isler"][0]["plan_turu"] == 2 and len(cagri) == 2
    assert "ÇEKİM PLANI KAPISI (cesitlilik): farklı hareket sayısı 3; en az 4" in s.istemler[2][1]
    assert {g["gorsel_id"] for g in cagri[0]} == {f"{KIM}-g{i}" for i in range(4)}   # havuz planlayıcıya yazıldı


def test_plan_yeniden_deneme_sinirli_ve_baska_hata_aninda_durur(otonom):
    s = Sahte([SORGU] + [_shorts_sen()] * 3)
    planla_fn, _ = _planla_sahte([{"plan_denetimi": ["S2b: S2a ile aynı çekim"]}] * 3)
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "shorts", otonom / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit_h(1)]},
                  saglayici_fn=lambda: s, topla=_topla, planla_fn=planla_fn, olc=lambda cs: {})
    assert e.value.asama == "plan" and s.cagri_sayisi == 1 + 1 + ou.PLAN_YENIDEN_DENEME
    s2 = Sahte([SORGU, _shorts_sen()])
    planla_fn2, c2 = _planla_sahte([{"sure": ["toplam 30 sn"]}])
    with pytest.raises(ou.UretimHatasi):
        ou.planla("Otlukbeli Savaşı", "shorts", otonom / "is2", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit_h(1)]},
                  saglayici_fn=lambda: s2, topla=_topla, planla_fn=planla_fn2, olc=lambda cs: {})
    assert len(c2) == 1 and s2.cagri_sayisi == 2                                 # süre hatası yeniden denenmez


def test_ikinci_cekim_gorseli_kullanilanlara_ve_atiflara_girer(otonom):
    s = Sahte([SORGU, _shorts_sen()])
    planla_fn, _ = _planla_sahte([{}], b_gorseli=f"{KIM}-g3")
    r = ou.planla("Otlukbeli Savaşı", "shorts", otonom / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit_h(1)]},
                  saglayici_fn=lambda: s, topla=_topla, planla_fn=planla_fn, olc=lambda cs: {})
    i = r["isler"][0]
    assert i["gorseller"] == [f"{KIM}-g{x}" for x in range(4)]
    at = json.loads((Path(i["is"]) / "gorsel_atiflari.json").read_text())
    assert {g["gorsel_id"] for g in at} == set(i["gorseller"])


def test_ayni_dosyanin_kopyasi_farkli_kimlikle_reddedilir(otonom, monkeypatch):
    monkeypatch.setattr(ou, "gorsel_sha", lambda gid: "AYNI" if gid in (f"{KIM}-g0", f"{KIM}-g2") else gid)
    assert ou.ayni_dosya_kopyalari([f"{KIM}-g0", f"{KIM}-g1", f"{KIM}-g2"]) == [[f"{KIM}-g0", f"{KIM}-g2"]]
    s = Sahte([SORGU, _shorts_sen()])
    planla_fn, _ = _planla_sahte([{}])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "shorts", otonom / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit_h(1)]},
                  saglayici_fn=lambda: s, topla=_topla, planla_fn=planla_fn, olc=lambda cs: {})
    assert e.value.kod == 5 and "aynı görsel dosyası" in str(e.value)


def test_render_kapisi_ayni_dosya_kopyasini_durdurur(tmp_path, monkeypatch):
    monkeypatch.setattr(ou, "gorsel_sha", lambda gid: "AYNI")
    (tmp_path / "gorsel_kapisi.json").write_text(json.dumps({"en_az": 1}))
    (tmp_path / "cekim_plani.json").write_text(json.dumps({"cekimler": [
        {"id": "S1", "tur": "gorsel25d", "gorsel25d": {"gorsel_id": "a"}},
        {"id": "S2", "tur": "gorsel25d", "gorsel25d": {"gorsel_id": "b"}}]}))
    with pytest.raises(ou.UretimHatasi) as e:
        ou.render_kapisi(tmp_path)
    assert "aynı dosyanın kopyaları" in str(e.value)


def test_gorsel_sha_kayit_yoksa_none():
    assert ou.gorsel_sha("kesinlikle-olmayan-gorsel") is None
