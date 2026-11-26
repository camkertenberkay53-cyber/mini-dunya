"""Faz-53B — güven skorlu tür ve özne kutusu tespiti (motor/varlik/ozne_tespit.py).

Sentetik görseller: portre, mimari, çok figürlü yoğun minyatür (yüzlü ve yüzsüz), belirsiz/düşük güven. Yüz
algılayıcı sentetik çizimde gerçek bir yüz bulamaz. Bu yüzden karar mantığı enjekte edilen deterministik bir
bulucuyla sınanır. Gerçek YuNet modeli ise ayrı testlerde çalıştırılır: model indirme + SHA-256, ve gerçek tarihî
görsel diskte varsa o görsel üzerinde.
"""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from motor.varlik import ozne_tespit as ot


def _sahte(yuzler):
    return lambda img, uzun, esik: [dict(y) for y in yuzler]


def portre(H=1600, W=1200):
    r = np.random.default_rng(1)
    img = np.full((H, W, 3), (25, 28, 32), np.uint8)
    img = cv2.add(img, r.normal(0, 3, img.shape).clip(0, 255).astype(np.uint8))
    cv2.ellipse(img, (600, 1450), (420, 520), 0, 180, 360, (40, 40, 150), -1)
    for _ in range(60):
        cv2.line(img, (int(r.integers(250, 950)), int(r.integers(1050, 1600))),
                 (int(r.integers(250, 950)), int(r.integers(1050, 1600))), (60, 60, 190), 3)
    cv2.ellipse(img, (600, 700), (170, 220), 0, 0, 360, (140, 170, 210), -1)
    cv2.ellipse(img, (600, 470), (230, 150), 0, 0, 360, (220, 225, 230), -1)
    for i in range(40):
        cv2.ellipse(img, (600, 470), (230 - i * 4, 150 - i * 3), 0, 180, 360, (180, 185, 190), 1)
    return img, [{"kutu": [480 / W, 560 / H, 720 / W, 860 / H], "skor": 0.93}]


def mimari(H=1400, W=2000):
    img = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        img[y] = (200 - y // 12, 180 - y // 14, 150 - y // 20)
    cv2.rectangle(img, (400, 500), (1600, 1300), (120, 140, 160), -1)
    for x in range(450, 1600, 110):
        cv2.rectangle(img, (x, 560), (x + 40, 1300), (80, 90, 100), -1)
    cv2.line(img, (380, 500), (1620, 500), (50, 50, 50), 8)
    cv2.line(img, (380, 540), (1620, 540), (50, 50, 50), 5)
    for x in range(480, 1560, 220):
        for y in (700, 950, 1150):
            cv2.rectangle(img, (x + 50, y), (x + 110, y + 90), (30, 30, 40), -1)
    cv2.fillPoly(img, [np.array([[400, 500], [1000, 250], [1600, 500]])], (100, 110, 130))
    return img, []


def minyatur(H=2000, W=1400, yuzlu=False):
    r = np.random.default_rng(2)
    img = np.full((H, W, 3), (150, 190, 210), np.uint8)
    for _ in range(2500):
        x, y = int(r.integers(0, W)), int(r.integers(0, H))
        c = tuple(int(v) for v in r.integers(0, 255, 3))
        t = r.integers(0, 3)
        if t == 0:
            cv2.rectangle(img, (x, y), (x + int(r.integers(8, 40)), y + int(r.integers(8, 40))), c, int(r.choice([-1, 2])))
        elif t == 1:
            cv2.circle(img, (x, y), int(r.integers(4, 20)), c, int(r.choice([-1, 2])))
        else:
            cv2.line(img, (x, y), (x + int(r.integers(-40, 40)), y + int(r.integers(-40, 40))), c, 2)
    yuzler = []
    if yuzlu:   # sahnenin dört bir yanına dağılmış beş küçük figür
        for cx, cy in [(250, 400), (1100, 500), (700, 1100), (300, 1600), (1150, 1700)]:
            yuzler.append({"kutu": [(cx - 30) / W, (cy - 35) / H, (cx + 30) / W, (cy + 35) / H], "skor": 0.8})
    return img, yuzler


def belirsiz(H=1500, W=1500):
    r = np.random.default_rng(3)
    g = np.tile(np.linspace(90, 140, W), (H, 1))
    img = np.dstack([g, g * 0.95, g * 0.9]).astype(np.float32)
    img = cv2.GaussianBlur(img + r.normal(0, 6, img.shape).astype(np.float32), (0, 0), 6)
    return img.clip(0, 255).astype(np.uint8), []


def izgara_cizgi(H=1500, W=1500):
    """Bütün kadraja yayılmış düzenli çizgi deseni: mimari ölçüsü yüksek ama özne ayrışmaz → düşük güven fallback."""
    img = np.full((H, W, 3), 170, np.uint8)
    for x in range(0, W, 75):
        cv2.line(img, (x, 0), (x, H), (60, 60, 60), 3)
    for y in range(0, H, 75):
        cv2.line(img, (0, y), (W, y), (60, 60, 60), 3)
    return img, []


def _alan(k):
    return (k[2] - k[0]) * (k[3] - k[1])


def _gecerli(r):
    for a in ot.ZORUNLU_ALANLAR:
        assert a in r, a
    k = r["ozne_bilgisi"]["kutu"]
    assert 0 <= k[0] < k[2] <= 1 and 0 <= k[1] < k[3] <= 1
    assert 0.0 <= r["guven_skoru"] <= 1.0
    assert r["tespit_durumu"] in ("kesin_yuz", "geometrik_tahmin", "belirsiz_fallback")
    assert r["tespit_yontemi"] in ("yuz_algilama", "kontur_kompozisyon", "tam_kadraj_fallback")
    assert r["onerilen_seviye"] in ("tam", "sinirli", "kenburns")
    assert r["fallback_uygulandi"] is (r["tespit_durumu"] == "belirsiz_fallback")
    if r["fallback_uygulandi"]:
        assert k == [0.0, 0.0, 1.0, 1.0] and r["onerilen_seviye"] == "kenburns"
    json.dumps(r)   # metadata'ya yazılabilir (numpy tipi kalmamalı)


def test_portre_kesin_yuz_dar_olmayan_kutu_ve_tam():
    img, y = portre()
    r = ot.tespit(img, yuz_bulucu=_sahte(y))
    _gecerli(r)
    assert r["gorsel_turu"] == "portre" and r["tespit_yontemi"] == "yuz_algilama" and r["tespit_durumu"] == "kesin_yuz"
    k = r["ozne_bilgisi"]["kutu"]
    yk = y[0]["kutu"]
    assert k[0] < yk[0] and k[2] > yk[2] and k[1] < yk[1] and k[3] == 1.0   # baş-omuz-gövde, yüzden geniş
    assert r["onerilen_seviye"] == "tam" and r["fallback_uygulandi"] is False
    assert r["ozne_bilgisi"]["figur_sayisi"] == 1


def test_dusuk_skorlu_ya_da_kararsiz_yuz_kesin_sayilmaz():
    img, y = portre()
    zayif = [dict(y[0], skor=0.7)]
    r = ot.tespit(img, yuz_bulucu=_sahte(zayif))
    _gecerli(r)
    assert r["tespit_durumu"] != "kesin_yuz" and r["onerilen_seviye"] != "tam"
    calls = {"n": 0}

    def kararsiz(img_, uzun, esik):   # ikinci ölçekte yüz kayboluyor
        calls["n"] += 1
        return [dict(y[0])] if calls["n"] == 1 else []
    r2 = ot.tespit(img, yuz_bulucu=kararsiz)
    _gecerli(r2)
    assert r2["tespit_durumu"] != "kesin_yuz" and r2["onerilen_seviye"] != "tam"
    assert r2["olcumler"]["kararli_yuz_sayisi"] == 0


def test_mimari_geometrik_tahmin_tam_onerilmez():
    img, y = mimari()
    r = ot.tespit(img, yuz_bulucu=_sahte(y))
    _gecerli(r)
    assert r["gorsel_turu"] == "mimari" and r["tespit_yontemi"] == "kontur_kompozisyon"
    assert r["tespit_durumu"] == "geometrik_tahmin" and r["onerilen_seviye"] == "sinirli"
    assert r["guven_skoru"] <= 0.8   # semantik doğrulama yok: geometrik kanıt "tam"a çıkaramaz
    k = r["ozne_bilgisi"]["kutu"]
    assert k[0] <= 400 / 2000 + 0.01 and k[2] >= 1600 / 2000 - 0.01   # binanın tamamı kutuda


def test_cok_figurlu_minyatur_tek_dar_kutuya_sikistirilmaz():
    img, y = minyatur(yuzlu=True)
    r = ot.tespit(img, yuz_bulucu=_sahte(y))
    _gecerli(r)
    assert r["gorsel_turu"] == "cok_figurlu" and r["ozne_bilgisi"]["figur_sayisi"] == 5
    assert r["ozne_bilgisi"]["ana_karakter"] == "belirlenemez"   # kim olduğu / ana karakter semantik olarak bilinmez
    assert r["tespit_durumu"] == "geometrik_tahmin" and r["onerilen_seviye"] == "kenburns"
    k = r["ozne_bilgisi"]["kutu"]
    for f in y:   # bütün figürler kutuda
        fk = f["kutu"]
        assert k[0] <= fk[0] and k[1] <= fk[1] and k[2] >= fk[2] and k[3] >= fk[3]


def test_yogun_minyatur_yuzsuz_tam_kadraj_fallback():
    img, y = minyatur()
    r = ot.tespit(img, yuz_bulucu=_sahte(y))
    _gecerli(r)
    assert r["gorsel_turu"] == "yogun_kompozisyon" and r["fallback_uygulandi"] is True
    assert r["tespit_durumu"] == "belirsiz_fallback" and r["onerilen_seviye"] == "kenburns"


def test_belirsiz_ve_ayrismayan_gorsel_fallback():
    img, y = belirsiz()
    r = ot.tespit(img, yuz_bulucu=_sahte(y))
    _gecerli(r)
    assert r["gorsel_turu"] == "belirsiz" and r["fallback_uygulandi"] is True and r["guven_skoru"] == 0.0
    img2, _ = izgara_cizgi()
    r2 = ot.tespit(img2, yuz_bulucu=_sahte([]))
    _gecerli(r2)
    assert r2["fallback_uygulandi"] is True and r2["neden"] in ("ozne_ayrismiyor", "dusuk_guven", "yogun_kompozisyon_tek_ozne_yok")


def test_guven_skoru_olcumden_gelir_sabit_degil_ve_deterministik():
    sonuclar = []
    for f in (portre, mimari, lambda: minyatur(yuzlu=True)):
        img, y = f()
        a = ot.tespit(img, yuz_bulucu=_sahte(y))
        b = ot.tespit(img.copy(), yuz_bulucu=_sahte(y))
        assert a == b   # aynı girdi → aynı çıktı
        sonuclar.append(a["guven_skoru"])
    assert len(set(sonuclar)) == len(sonuclar)   # farklı görsel → farklı ölçülmüş güven
    img, y = portre()
    yuksek = ot.tespit(img, yuz_bulucu=_sahte(y))["guven_skoru"]
    dusuk = ot.tespit(img, yuz_bulucu=_sahte([dict(y[0], skor=0.65)]))["guven_skoru"]
    assert dusuk < yuksek   # güven yüz skoruyla birlikte değişir


def test_numpy_tipli_dedektor_ciktisi_jsona_yazilabilir():
    """Gerçek dedektörler numpy float32 döndürür (CI'da toplayıcıyı düşüren hata): sonuç yine JSON'a yazılmalı."""
    img, y = portre()
    np_yuz = [{"kutu": [np.float32(v) for v in y[0]["kutu"]], "skor": np.float32(0.93)}]
    r = ot.tespit(img, yuz_bulucu=_sahte(np_yuz))
    _gecerli(r)
    assert r["tespit_durumu"] == "kesin_yuz"

    def tip_tara(o):
        if isinstance(o, dict):
            return all(tip_tara(v) for v in o.values())
        if isinstance(o, list):
            return all(tip_tara(v) for v in o)
        return o is None or type(o) in (bool, int, float, str)
    assert tip_tara(r)


def test_hata_sureci_durdurmaz(tmp_path):
    r = ot.tespit(tmp_path / "yok.jpg")
    _gecerli(r)
    assert r["fallback_uygulandi"] and "gorsel_okunamadi" in r["uyarilar"]

    def patlayan(img, uzun, esik):
        raise RuntimeError("yuz_modeli_yok")
    img, _ = portre()
    r2 = ot.tespit(img, yuz_bulucu=patlayan)
    _gecerli(r2)
    assert r2["olcumler"]["yuz_algilama"] == "kullanilamadi"
    assert any("yuz_algilama_kullanilamadi" in u for u in r2["uyarilar"])
    assert r2["tespit_durumu"] != "kesin_yuz"   # yüz algılanamadıysa "kesin yüz" denmez


def test_yunet_modeli_indirilir_ve_sha_dogrulanir():
    yol = ot.model_yolu()
    assert yol is not None and yol.is_file(), "YuNet modeli indirilemedi (ağ?)"
    assert ot._sha256(yol) == ot.MODEL["sha256"]
    img, _ = portre()
    assert isinstance(ot.yunet_bulucu(img, 640, 0.6), list)   # gerçek dedektör çalışır (çizimde yüz beklenmez)
    r = ot.tespit(img)
    _gecerli(r)
    assert r["olcumler"]["yuz_algilama"] == "calisti"


def test_motor_uretim_konu_kelimesi_yok():
    import re
    from pathlib import Path
    metin = Path(ot.__file__).read_text().lower()
    assert not re.search(r"roma|lejyon|aquil|kartal|carrhae|harran|crassus|augustus|osmanl|akkoyunlu|bizans|otlukbeli", metin)


# ------------------------------------------------------------------ gerçek tarihî görseller (CI'da toplanır)

def _gercek():
    from motor.testler.gorsel25d_kanit import gercek_gorseller
    try:
        return gercek_gorseller()[0]
    except Exception:
        return []


_G = _gercek()


@pytest.mark.skipif(not _G, reason="gerçek tarihî görsel diskte yok (CI'da commons_toplayici ile toplanır)")
def test_gercek_gorsellerde_tespit():
    from motor.varlik import tarihi_gorsel as tg
    for k in _G:
        r = ot.tespit(tg.dosya_yolu(k))
        _gecerli(r)
        print("OZNE_TESPIT", k["gorsel_id"], json.dumps({a: r[a] for a in ot.ZORUNLU_ALANLAR} | {
            "kutu": r["ozne_bilgisi"]["kutu"], "olcumler": {x: v for x, v in r["olcumler"].items() if x != "yuzler"},
            "yuzler": r["olcumler"].get("yuzler")}, ensure_ascii=False))
        assert r["olcumler"]["yuz_algilama"] == "calisti"
        if (k.get("ozne_bilgisi") or {}).get("tur") == "insan_portre":   # sorgu portre diyor: yüz bulunmalı
            assert r["olcumler"]["yuz_sayisi"] >= 1 and r["tespit_yontemi"] == "yuz_algilama", r
        if k.get("gorsel_turu") in ("minyatur", "harita"):              # yoğun minyatür: "tam" önerilmez
            assert r["onerilen_seviye"] != "tam"
            assert r["fallback_uygulandi"] or _alan(r["ozne_bilgisi"]["kutu"]) >= 0.5


# ------------------------------------------------------------------ 2.5D motoru: öneriye uyma

def test_gorsel25d_kenburns_onerisine_uyar_elle_kutuda_uymaz(tmp_path):
    from motor.testler.test_faz53a_a2 import _kayit, kale
    from motor.uretim import gorsel25d as g25
    img, *_ = kale()
    p = tmp_path / "m.png"
    cv2.imwrite(str(p), img)
    oto = {"kutu": [0.35, 0.27, 0.67, 0.84], "tur": "mimari", "kutu_kaynagi": "otomatik"}
    ek, rap = g25.hazirla(p, _kayit(tmp_path, p, ozne_bilgisi=oto, onerilen_seviye="kenburns",
                                    tespit_durumu="belirsiz_fallback"), {"hareket": "push_in"}, 1920, 1080, tmp_path / "a", 1)
    assert rap["seviye"] == "kenburns" and "ozne_tespit" in rap["puan"]["neden"] and "ozne_maskesi" not in ek
    elle = dict(oto, kutu_kaynagi="elle")
    ek, rap = g25.hazirla(p, _kayit(tmp_path, p, ozne_bilgisi=elle, onerilen_seviye="kenburns"),
                          {"hareket": "push_in"}, 1920, 1080, tmp_path / "b", 1)
    assert rap["seviye"] == "tam" and "ozne_maskesi" in ek     # insanın verdiği kutu öneriyi geçersiz kılar
    ek, rap = g25.hazirla(p, _kayit(tmp_path, p, ozne_bilgisi=oto, onerilen_seviye="sinirli"),
                          {"hareket": "push_in"}, 1920, 1080, tmp_path / "c", 1)
    assert rap["seviye"] == "tam"                               # yalnızca kenburns önerisi bağlayıcı; ölçüm karar verir
