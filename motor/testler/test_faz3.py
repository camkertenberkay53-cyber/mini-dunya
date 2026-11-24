"""Faz 3 kabul testleri: dönem kitleri, modüler karakter-ekipman sistemi, kalite sınıfları.

Çalıştırma: python3 -m pytest motor/testler/test_faz3.py -q
Önkoşul (sırayla): python3 -m motor.karakter.takim ; python3 -m motor.karakter.montaj ;
                   python3 -m motor.karakter.karsilastir ; python3 -m motor.karakter.kalite
Başarısız bir test, ilgili varlığın üretime alınmaması demektir (kalite.json'da RED).
"""
import copy
import json
from pathlib import Path

import pytest

from motor.karakter import kalite, montaj, siluet, takim
from motor.varlik import ekipman, katalog

K = Path(takim.__file__).resolve().parent


@pytest.fixture(scope="module")
def oz():
    return json.loads((K / "derlenmis3.json").read_text())


@pytest.fixture(scope="module")
def mt():
    return json.loads((K / "montaj_testi.json").read_text())["takimlar"]


@pytest.fixture(scope="module")
def kal():
    return json.loads((K / "kalite.json").read_text())


@pytest.fixture(scope="module")
def kat():
    return ekipman.katalog()


# ---------------------------------------------------------------- kitler ve dönem uyumu
def test_dort_kit_ve_sekiz_kategori(kat):
    kitler = takim.kitleri_yukle()
    assert set(kitler) == {"osmanli_15yy", "akkoyunlu_15yy", "bizans_15yy", "roma_cumhuriyet"}
    for ad, kit in kitler.items():
        assert takim.kit_kategori_denetle(kit, kat) == [], ad


def test_kit_rolleri_ve_ayrisan_varyantlar(oz, kal):
    """Kalabalık rolleri (piyade, okçu, süvari) en az 3, tekil roller en az 2 ayrışan, kullanılabilir karakter."""
    asgari = {"piyade": 3, "okcu": 3, "suvari": 3, "komutan": 2, "isci_sivil": 2}
    M = siluet.maskeler(sorted(oz["takimlar"]))
    for kit in takim.kitleri_yukle():
        for rol, n in asgari.items():
            uye = [a for a, t in oz["takimlar"].items() if t["kit"] == kit and t["rol"] == rol and kal["karakter"][a]["sinif"] != "RED"]
            ayr = []
            for a in uye:
                if all(siluet.benzer(M[a], M[b]) < 0.97 for b in ayr):
                    ayr.append(a)
            assert len(ayr) >= n, f"{kit}/{rol}: {len(ayr)} ayrışan varyant (en az {n})"


def test_donem_uyumsuz_ekipman_engellenir(kat):
    kit = takim.kitleri_yukle()["osmanli_15yy"]
    k = {"ad": "x", "govde": "erkek", "giysiler": ["roma_tunigi"], "takilanlar": {"bas": "montefortino", "sag_el_dik": "pilum"}}
    h = takim.kural_denetle(kit, k, kat)
    assert sum("DÖNEM UYUMSUZ" in x for x in h) == 3


def test_yanlis_yuva_ve_cakisan_yuva_engellenir(kat):
    kit = takim.kitleri_yukle()["roma_cumhuriyet"]
    k = {"ad": "x", "govde": "erkek", "giysiler": [], "takilanlar": {"sag_el": "scutum", "sol_kol": "scutum", "sol_el": "kompozit_yay"}}
    h = takim.kural_denetle(kit, k, kat)
    assert any("yuvasına aittir" in x for x in h) and any("aynı anda dolu olamaz" in x for x in h)


def test_kitlerde_reddedilen_tanim_yok(oz):
    assert oz["reddedilen"] == {}


# ---------------------------------------------------------------- montaj ve animasyon
def test_butun_takimlar_montaj_testini_gecti(oz, mt):
    assert set(mt) == set(oz["takimlar"])
    kalan = {a: x["hatalar"] for a, x in mt.items() if not x["gecti"]}
    assert kalan == {}


def test_baslik_uyumu(mt):
    for a, x in mt.items():
        for eid, e in x["olcum"]["ekipman"].items():
            if e["kategori"] == "baslik":
                assert e["bas_tasma_orani"] is not None and e["bas_tasma_orani"] <= montaj.ESIK["bas_tasma_orani"], (a, eid)
                assert e["bas_bosluk_cm"] <= montaj.ESIK["bas_bosluk_cm"], (a, eid)


def test_silah_ve_kalkan_baglantisi_animasyonda_sabit(mt):
    sayac = 0
    for a, x in mt.items():
        for eid, e in x["olcum"]["ekipman"].items():
            if e["kategori"] in ("silah", "kalkan", "sancak"):
                sayac += 1
                assert e["kayma_mm"] <= montaj.ESIK["kayma_mm"] and e["kayma_derece"] <= montaj.ESIK["kayma_derece"], (a, eid)
                assert e["tutus_cm"] <= montaj.ESIK["tutus_cm"], (a, eid)
                if e["kategori"] == "kalkan":
                    assert e["gomulme_kare_orani"] <= montaj.ESIK["kalkan_gomulme_kare_orani"], (a, eid)
    assert sayac > 40


def test_giysi_katmanlari_temel_animasyonda_tasmiyor(mt):
    for a, x in mt.items():
        for g, r in x["olcum"]["giysi"].items():
            for anim in montaj.TEMEL_ANIMASYON:
                assert r.get("animasyon", {}).get(anim, 0.0) <= montaj.ESIK["giysi_tasma_orani"], (a, g, anim, r)


def test_taşan_animasyon_yasaklanir_ve_kayitli(mt):
    """Uç pozda (kılıç saldırısı, at sürme) taşan giysi: o animasyon o karakter için yasak listesine girer."""
    for a, x in mt.items():
        for g, r in x["olcum"]["giysi"].items():
            for anim, oran in r.get("animasyon", {}).items():
                if anim not in montaj.TEMEL_ANIMASYON and oran > montaj.ESIK["giysi_tasma_orani"]:
                    assert anim in x["yasak_animasyon"], (a, g, anim)


def test_kopuk_ve_gomulu_ekipman_yakalanir():
    """Negatif örnekler: yuvaya bağlanmayan kılıç kayar; 6 cm aşağı itilen (başa oturan) miğfer başa gömülür.
    Uzun börk gibi içi boş başlıkta aşağı itmek gömülme yaratmaz; bu yüzden başı saran Montefortino kullanılır."""
    t = json.loads((takim.TAKIM_CIKTI / "rom_lejyoner_gladius.json").read_text())
    kopuk = copy.deepcopy(t)
    kopuk["ad"] = "test_kopuk"
    for e in kopuk["takilanlar"]:
        if e["kategori"] == "silah":
            e["kopuk"] = True
    gomulu = copy.deepcopy(t)
    gomulu["ad"] = "test_gomulu"
    gomulu["govde_id"] = "test"
    for e in gomulu["takilanlar"]:
        if e["kategori"] == "baslik":
            e["ince_ayar"] = [0, 0, -0.06]
    r = montaj.test_et(adlar=["__yok__"], hizli=True, ek=[kopuk, gomulu])
    assert not r["test_kopuk"]["gecti"] and any("kayıyor" in h for h in r["test_kopuk"]["hatalar"])
    assert not r["test_gomulu"]["gecti"] and any("taşıyor" in h for h in r["test_gomulu"]["hatalar"])


# ---------------------------------------------------------------- siluet ayrışması
def test_kitler_arasi_siluet_farki(kal):
    assert kal["siluet"]["ayrismayan"] == [], kal["siluet"]["ayrismayan"]


def test_benzer_karakter_baska_doneme_karismaz(kal):
    assert kal["siluet"]["karisabilir"] == []
    assert kal["siluet"]["uzak_tanima_orani"] >= 0.85, kal["siluet"]["uzak_tanima_orani"]


# ---------------------------------------------------------------- dosya, bütünlük, lisans, tekrar üretim
def test_dosya_boyutlari(oz):
    for gid, g in oz["govdeler"].items():
        assert g["bayt"] <= kalite.GOVDE_MAKS_BAYT, gid
    for pid, e in json.loads(ekipman.KAYIT.read_text()).items():
        assert e["olcum"]["bayt"] <= kalite.EKIPMAN_MAKS_BAYT, pid


def test_model_butunlugu(oz):
    for pid, e in json.loads(ekipman.KAYIT.read_text()).items():
        o = e["olcum"]
        assert o["bozuk_yuz"] == 0 and o["yalniz_kose"] == 0, pid
        lo, hi = kalite.OLCU[e["kategori"]]
        assert lo <= max(o["boyut_m"]) <= hi, (pid, o["boyut_m"])
    for gid, g in oz["govdeler"].items():
        assert g["olcum"]["evrensel_iskelet_eslesen"] == 65, gid
        assert 1.5 <= g["olcum"]["boy_m"] <= 2.05, gid


def test_lisans_kayitlari(oz):
    for pid, e in json.loads(ekipman.KAYIT.read_text()).items():
        assert e["lisans"] == "kendi-uretim" and e["sha256"] and e["betik_ozeti"], pid
    for gid, g in oz["govdeler"].items():
        assert set(g["lisanslar"]) <= kalite.IZINLI_LISANS, gid
        assert g["kaynaklar"], gid


def test_atif_gerektiren_lisans_atifsiz_reddedilir():
    kayit = katalog.yukle()
    v = copy.deepcopy(kayit["varliklar"][0])
    v["id"] = "deneme/ccby"
    v["lisans"] = "CC-BY-4.0"
    v.pop("atif", None)
    h = katalog.dogrula({"varliklar": [v]})
    assert any("atıf" in x for x in h)
    v["atif"] = "Model: Örnek Yazar, CC BY 4.0, https://ornek"
    assert not any("atıf" in x or "lisans" in x for x in katalog.dogrula({"varliklar": [v]}))


def test_ekipman_tekrarlanabilir():
    once = json.loads(ekipman.KAYIT.read_text())["sarik_migfer"]["sha256"]
    yeni = ekipman.uret(["sarik_migfer"], zorla=True)
    assert yeni["sarik_migfer"]["sha256"] == once


def test_govde_tek_komutla_ayni_sonuc(oz):
    import hashlib
    import subprocess
    import sys
    gid = sorted(oz["govdeler"])[0]
    tarif = json.loads((takim.GOVDE_CIKTI / f"{gid}.tarif.json").read_text())
    tarif["cikti"] = "/tmp/_tekrar.glb"
    Path("/tmp/_tekrar.json").write_text(json.dumps(tarif))
    subprocess.run([sys.executable, str(takim.BETIK / "karakter_kur.py"), "/tmp/_tekrar.json"], check=True, capture_output=True)
    assert hashlib.sha256(Path("/tmp/_tekrar.glb").read_bytes()).hexdigest() == oz["govdeler"][gid]["glb_sha256"]


# ---------------------------------------------------------------- kalite sınıfları
def test_her_varlik_siniflandi(oz, kal):
    assert set(kal["karakter"]) == set(oz["takimlar"])
    assert all(x["sinif"] in ("A", "B", "C", "RED") for x in kal["karakter"].values())
    assert all(x["sinif"] in ("A", "B", "C", "RED") for x in kal["ekipman"].values())


def test_yakin_cekim_yalniz_a(kal):
    for a, x in kal["karakter"].items():
        assert kalite.kullanilabilir_mi(x, "yakin") == (x["sinif"] == "A"), a
        if x["sinif"] == "RED":
            assert not kalite.kullanilabilir_mi(x, "uzak")


def test_belirsiz_parca_yakin_cekime_cikamaz(kal, kat):
    for pid, x in kal["ekipman"].items():
        if kat["parcalar"][pid]["tarih"]["guven"] == "belirsiz":
            assert x["sinif"] != "A", pid
