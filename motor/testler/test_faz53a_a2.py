"""Faz-53A A2: 2.5D kalite katmanı (motor/uretim/gorsel25d.py) ve kaos/sinema isteğe bağlı girişleri.
Otomatik testler sentetik üreteçlerle koşar; gerçek tarihî görsel testi dosya yoksa atlanır (skipif)."""
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from motor import ayar
from motor.uretim import gorsel25d as g25
from motor.uretim import render, veri
from motor.varlik import tarihi_gorsel as tg


# ------------------------------------------------------------------ sentetik üreteçler

def kale(W=3000, H=2000, tohum=7):
    """Gravür benzeri kale: (görsel, özne maskesi, burç boşlukları maskesi, özne kutusu). Doğru maske bilinir."""
    r = np.random.default_rng(tohum)
    y = np.linspace(0, 1, H)[:, None]
    img = np.zeros((H, W, 3), np.float32)
    img[:] = np.dstack([225 - 40 * y, 215 - 50 * y, 190 - 60 * y])
    for i, (b, a, f, c) in enumerate([(900, 60, 1.3, (150, 160, 165)), (1150, 80, 2.1, (110, 120, 125)), (1450, 50, 1.7, (70, 80, 85))]):
        x = np.arange(W)
        rr = np.random.default_rng(i)
        h = b + a * np.sin(x / W * f * 6.28 + rr.uniform(0, 6)) + a * 0.4 * np.sin(x / W * f * 17 + rr.uniform(0, 6))
        m = np.arange(H)[:, None] > h[None, :]
        img[m] = img[m] * 0.35 + np.array(c, np.float32) * 0.65
    k = np.zeros((H, W), np.uint8)
    cv2.rectangle(k, (1150, 800), (1850, 1650), 255, -1)
    for x in (1100, 1450, 1800):
        cv2.rectangle(k, (x, 620), (x + 180, 1650), 255, -1)
    for x in range(1100, 1980, 60):
        cv2.rectangle(k, (x, 580), (x + 30, 620), 255, -1)
    cv2.rectangle(k, (1430, 1350), (1570, 1650), 0, -1)
    img[k > 0] = np.array((55, 60, 70), np.float32)
    for yy in range(0, H, 7):
        img[yy:yy + 1] *= 0.88
    img += r.normal(0, 6, img.shape)
    bosluk = np.zeros((H, W), np.uint8)
    for x in range(1100, 1980, 60):
        cv2.rectangle(bosluk, (x + 30, 580), (x + 60, 620), 255, -1)
    bosluk[k > 0] = 0
    return np.clip(img, 0, 255).astype(np.uint8), k, bosluk, [0.35, 0.27, 0.67, 0.84]


def _yukle_gibi(dizi, W, H, interp=cv2.INTER_AREA):
    """motor._yukle ile aynı ölçeğe getir (kaynağı geçici dosyaya yazıp gerçek yükleyiciyi kullanır)."""
    from kaos.sinema import motor
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.png"
        cv2.imwrite(str(p), dizi)
        out = motor._yukle(str(p), W, H)
    return out


def _olc(alfa, gt, bosluk):
    b, t = alfa > 0.5, gt > 127
    iou = (b & t).sum() / max(1, (b | t).sum())
    return float(iou), float(b[bosluk > 127].mean())


# ------------------------------------------------------------------ kaos/sinema regresyonu

def test_sahne_render_varsayilan_yol_kare_kare_ayni(tmp_path):
    from motor.testler import sinema_regresyon as r
    taban = json.loads(r.TABAN.read_text())
    assert (taban["W"], taban["H"], taban["sure"]) == (r.W, r.H, r.SURE)
    o = r.ozetle(tmp_path)
    assert set(o) == set(taban["sahneler"]) and len(o) == 10
    for sid, ozet in taban["sahneler"].items():
        assert o[sid] == ozet, f"{sid}: {sum(a != b for a, b in zip(o[sid], ozet))} kare farklı"


def test_sahne_anahtari_isteğe_bagli_alanlar_verilmezse_ayni():
    from kaos.sinema import motor
    s = {"id": "x", "gorsel": "yok.jpg", "kamera": "push_in", "sure_render": 1}
    a = motor.sahne_anahtari(s, 1080, 1920, 30)
    assert a == "62d3cea4d1028990"   # A2 öncesi (HEAD cabc8a5) kodla hesaplanan anahtar
    assert motor.sahne_anahtari(dict(s, nefes_aktif=False), 1080, 1920, 30) != a


# ------------------------------------------------------------------ maske

def test_yonlendirmeli_filtre_kenar_korur():
    I = np.zeros((64, 64), np.float32)
    I[:, 32:] = 1.0
    p = cv2.GaussianBlur(I, (0, 0), 4)
    q = g25.yonlendirmeli_filtre(I, p, 4, 1e-4)
    assert abs(q[:, 31:33].mean() - 0.5) < 0.2
    assert np.abs(np.diff(q[32])).max() > np.abs(np.diff(p[32])).max() * 2   # kenar daha keskin
    sabit = g25.yonlendirmeli_filtre(I, np.full_like(I, 0.3), 4, 1e-3)
    assert np.allclose(sabit, 0.3, atol=1e-4)


@pytest.fixture(scope="module")
def kale_yuklu():
    img, gt, bos, kutu = kale()
    W, H = 1920, 1080
    yi = _yukle_gibi(img, W, H)
    ih, iw = yi.shape[:2]
    gt_y = cv2.resize(gt, (iw, ih), interpolation=cv2.INTER_AREA)
    bos_y = cv2.resize(bos, (iw, ih), interpolation=cv2.INTER_AREA)
    alfa, puan = g25.maske(yi, kutu)
    return yi, gt_y, bos_y, kutu, alfa, puan


def test_sentetik_maske_esikleri(kale_yuklu):
    yi, gt, bos, kutu, alfa, puan = kale_yuklu
    iou, bosluk = _olc(alfa, gt, bos)
    assert iou >= 0.95, iou
    assert bosluk <= 0.10, bosluk
    assert g25.seviye(puan) == "tam" and puan["kararlilik"] >= 0.95


def test_eski_maske_esigi_gecemiyordu(kale_yuklu):
    """Karşılaştırma: kaos/sinema'nın kendi maskesi (A1) burç boşluklarını özne sayıyordu."""
    from kaos.sinema import derinlik
    yi, gt, bos, kutu, _a, _p = kale_yuklu
    m = np.clip((derinlik.ozne_maskesi(yi, kutu) - 0.25) * 2.2, 0, 1)
    assert _olc(m, gt, bos)[1] > 0.3


def test_cok_figur_iki_parca_korunur():
    H, W = 1200, 1800
    img = np.full((H, W, 3), (200, 210, 220), np.uint8)
    img[H // 2:] = (120, 140, 150)
    cv2.rectangle(img, (500, 350), (700, 900), (40, 45, 50), -1)
    cv2.rectangle(img, (1000, 450), (1150, 900), (40, 45, 50), -1)   # ikinci figür (ilkinin ~%50'si)
    alfa, puan = g25.maske(img, [0.25, 0.25, 0.68, 0.8])
    assert alfa[600, 600] > 0.9 and alfa[700, 1075] > 0.9 and puan["parca"] == 2


def test_ozne_yoksa_guvenli_mod():
    r = np.random.default_rng(3)
    img = (r.random((900, 1400, 3)) * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 2)
    alfa, puan = g25.maske(img, [0.3, 0.3, 0.7, 0.7])
    assert g25.seviye(puan) in ("kenburns", "sinirli")
    assert g25.seviye({"kararlilik": 0.5, "kenar_orani": 0.9, "doluluk": 0.5, "parca": 1}) == "kenburns"
    assert g25.seviye({"kararlilik": 0.9, "kenar_orani": 1.6, "doluluk": 0.5, "parca": 1}) == "sinirli"


# ------------------------------------------------------------------ dolgu

def test_dolgu_yalniz_delikte_degistirir_ve_deterministik(kale_yuklu, monkeypatch):
    yi, gt, bos, kutu, alfa, puan = kale_yuklu
    a1, b1 = g25.dolgu(yi, alfa, 5)
    a2, _ = g25.dolgu(yi, alfa, 5)
    assert np.array_equal(a1, a2) and b1["doku"] is True
    disari = cv2.dilate((alfa > 0.02).astype(np.uint8), np.ones((41, 41), np.uint8)) == 0
    assert np.array_equal(a1[disari], yi[disari])                     # özne dışında özgün piksel
    ic = alfa > 0.9
    assert np.abs(a1[ic].astype(int) - yi[ic].astype(int)).mean() > 40  # öznenin yerinde artık özne yok
    k = dict(g25.ayarlar())
    a3, b3 = g25.dolgu(yi, alfa, 5, dict(k, doku_doldurma={"acik": False}))
    assert b3["doku"] is False and not np.array_equal(a1, a3)
    assert np.array_equal(a3[disari], yi[disari])


# ------------------------------------------------------------------ hareket ve kayma

def test_hareket_belgesel_egrisi_ve_zoom_tavani():
    k, b = g25.hareket("push_in", (4000, 3000), 1920, 1080, 1.0)
    assert k["ease"] == "inout" and b["zoom_kisma"] == 1.0
    k, b = g25.hareket("push_in", (1100, 800), 1920, 1080, 1.0)   # kaynak yetersiz → zoom kısılır
    assert b["zoom_kisma"] < 1.0 and max(k["bas"][2], k["son"][2]) <= b["zoom_tavani"] + 1e-6


@pytest.mark.parametrize("sev,sinir", [("tam", 20.0), ("sinirli", 15.0)])
def test_goreli_kayma_siniri(kale_yuklu, sev, sinir):
    from kaos.sinema import derinlik
    yi, gt, bos, kutu, alfa, puan = kale_yuklu
    arka, _ = g25.dolgu(yi, alfa, 1)
    D = derinlik.harita(arka, None, 0.45)[0]
    kam, _ = g25.hareket("push_in", (3000, 2000), 1920, 1080, 1.0)
    nok = g25._sinir_noktalari(alfa)
    eski = {"arka_konum": 0.75, "arka_zoom": 0.8, "ozne_konum": 1.2, "ozne_zoom": 1.15, "ozne_sarsinti": 1.0}
    assert g25.kayma_olc(yi.shape, nok, D, kam, [0.5, 0.5], 1.0, 1.0, eski, 0.0, 1920, 1080) > 60   # A1: ~82 px
    for ng in (0.0, 0.4):
        iz, par, olcu = g25.izleme_coz(yi.shape, nok, D, kam, [0.5, 0.5], 1.0, 1.0, ng, 1920, 1080, sinir)
        assert olcu <= sinir + 0.5 and iz["ozne_konum"] >= iz["arka_konum"]
        assert g25.kayma_olc(yi.shape, nok, D, kam, [0.5, 0.5], 1.0, par, iz, ng, 1920, 1080) <= sinir + 0.5


# ------------------------------------------------------------------ tuval

def test_dikey_gorsel_16_9_tuval_kirpmaz():
    img = (np.random.default_rng(1).random((1600, 1000, 3)) * 255).astype(np.uint8)
    t, x0 = g25.tuval(img, 1920, 1080, 1.0)
    assert x0 > 0 and t.shape[0] == 1600 and abs(t.shape[1] / t.shape[0] - 16 / 9) < 0.01
    assert np.array_equal(t[:, x0:x0 + 1000], img)                     # özgün görsel bütünüyle, değişmeden
    assert g25.tuval(img, 1080, 1920, 1.0)[1] == -1                    # Shorts: tuval yok
    yatay = np.zeros((1000, 1600, 3), np.uint8)
    assert g25.tuval(yatay, 1920, 1080, 1.0)[1] == -1


def _kayit(tmp_path, p, **ek):
    k = {"gorsel_id": "t_g", "kaynak_url": "https://ornek.invalid", "kaynak_kurum": "x", "eser_adi": "x", "tarih": "1900",
         "bolge": "x", "donem": "x", "kultur": "x", "taraf_faction": "x", "gorsel_turu": "gravur", "uygun_sahne_turleri": ["x"],
         "cozunurluk": [1, 1], "ozne_bilgisi": {"kutu": [0.35, 0.27, 0.67, 0.84], "tur": "mimari"}, "derinlik_uygunlugu": "yuksek",
         "lisans_turu": "PD-Old", "kamu_mali_gerekcesi": "x", "lisans_dogrulandi": True, "onay": {"onaylayan": "test", "tarih": "2026"},
         "yerel_yol": str(p), "sha256": tg._sha(p)}
    k.update(ek)
    return k


def test_hazirla_tuval_yanlari_maskeye_girmez_portre_nefes_derinlik(tmp_path):
    H, W = 2400, 1500
    img = np.full((H, W, 3), (190, 200, 205), np.uint8)
    cv2.ellipse(img, (750, 1300), (420, 800), 0, 0, 360, (50, 55, 60), -1)
    p = tmp_path / "portre.png"
    cv2.imwrite(str(p), img)
    k = _kayit(tmp_path, p, ozne_bilgisi={"kutu": [0.15, 0.1, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")
    ek, rap = g25.hazirla(p, k, {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
    assert rap["tuval"] is True and ek["nefes_aktif"] is True and ek["nefes_genlik"] == 0.4
    assert ek["zemin_derinlik_aktif"] is False
    m = cv2.imread(ek["ozne_maskesi"], cv2.IMREAD_UNCHANGED)
    t = cv2.imread(ek["gorsel"])
    x0 = (t.shape[1] - int(round(t.shape[1] * 1500 / (H * 16 / 9)))) // 2
    assert m[:, : max(1, x0 - 2)].max() == 0 and m[:, -max(1, x0 - 2):].max() == 0
    assert rap["kayma_px"] <= rap["kayma_siniri_px"] + 0.5
    k2 = _kayit(tmp_path, p, ozne_bilgisi={"kutu": [0.15, 0.1, 0.85, 1.0], "tur": "mimari"})
    ek2, _ = g25.hazirla(p, k2, {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
    assert ek2["nefes_aktif"] is False and ek2["zemin_derinlik_aktif"] is True
    ek3, rap3 = g25.hazirla(p, _kayit(tmp_path, p, ozne_bilgisi="yok"), {"hareket": "pan_sol"}, 1920, 1080, tmp_path, 1)
    assert rap3["seviye"] == "kenburns" and ek3["parallax"] == 0.0 and "ozne_maskesi" not in ek3


# ------------------------------------------------------------------ render entegrasyonu ve önbellek

def _plan(tmp_path, cekim, coz=(480, 270)):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"surum": 1, "konu": "a2-deneme", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30,
                             "cozunurluk": list(coz), "tohum": 1, "cekimler": [cekim], "eksikler": [],
                             "ses": {"motor": "piper", "cizelge": [], "toplam_sn": 1.0}}))
    return p


def test_render_kalite_seviye_ve_onbellek_anahtari(tmp_path, monkeypatch):
    img, _gt, _b, kutu = kale(1500, 1000)
    p = tmp_path / "kale.png"
    cv2.imwrite(str(p), img)
    yol = tmp_path / "kayit.json"
    yol.write_text(json.dumps({"gorseller": [_kayit(tmp_path, p)]}))
    monkeypatch.setattr(tg, "KAYIT", yol)
    monkeypatch.setattr(render, "KOK", tmp_path / "uretim")
    c = {"id": "G1", "cumleler": ["C1"], "sure_sn": 0.5, "tur": "gorsel25d", "metin": "x", "gorsel25d": {"gorsel_id": "t_g", "hareket": "push_in"}}
    plan = _plan(tmp_path, c)
    r = render.render(str(plan), "G1")
    assert r["durum"] == "TAMAM" and r["olculen"]["seviye"] in ("tam", "sinirli", "kenburns") and "kalite" in r
    assert r["olculen"]["uretilen_kare"] == 15
    k1 = r["karma"]
    # metadata değişince anahtar değişir
    yol.write_text(json.dumps({"gorseller": [_kayit(tmp_path, p, eser_adi="başka")]}))
    k2 = render.render(str(plan), "G1")["karma"]
    assert k2 != k1
    # kalite ayarı değişince anahtar değişir; kalite kapalı → A1 yolu (kalite raporu yok)
    gercek = veri.kural

    def kural(ad, _g=gercek):
        x = _g(ad)
        if ad == "gorsel":
            x = dict(x, gorsel25d=dict(x["gorsel25d"], kalite=dict(x["gorsel25d"]["kalite"], acik=False)))
        return x
    monkeypatch.setattr(veri, "kural", kural)
    r3 = render.render(str(plan), "G1")
    assert r3["durum"] == "TAMAM" and "kalite" not in r3 and r3["karma"] not in (k1, k2)


# ------------------------------------------------------------------ kayıt, yan dosya, depo düzeni

def test_goreli_yol_ve_yan_dosya(tmp_path, monkeypatch):
    k = {"yerel_yol": "assets/tarihi_gorsel/x.jpg", "gorsel_id": "x"}
    assert tg.dosya_yolu(k) == ayar.REPO / "assets/tarihi_gorsel/x.jpg"
    yan = tmp_path / "yan"
    yan.mkdir()
    (yan / "y.json").write_text(json.dumps({"gorsel_id": "y_g"}))
    monkeypatch.setattr(tg, "YAN_DOSYA_KOK", yan)
    monkeypatch.setattr(tg, "KAYIT", tmp_path / "bos.json")
    assert [x["gorsel_id"] for x in tg.kayit()["gorseller"]] == ["y_g"]


def test_gitignore_gorsel_ikilileri():
    gi = (ayar.REPO / ".gitignore").read_text()
    for uz in ("jpg", "jpeg", "png", "tif", "tiff", "webp"):
        assert f"assets/tarihi_gorsel/*.{uz}" in gi


def _gercek_gorseller():
    try:
        return [x for x in tg.kayit()["gorseller"] if not tg.denetle(x)]
    except Exception:
        return []


@pytest.mark.skipif(not _gercek_gorseller(), reason="lisansı doğrulanmış gerçek tarihî görsel diskte yok")
def test_gercek_tarihi_gorsel_hazirlanir(tmp_path):
    k = _gercek_gorseller()[0]
    ek, rap = g25.hazirla(tg.dosya_yolu(k), k, {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
    assert rap["seviye"] in ("tam", "sinirli", "kenburns")
    if rap["seviye"] != "kenburns":
        assert rap["kayma_px"] <= rap["kayma_siniri_px"] + 0.5
