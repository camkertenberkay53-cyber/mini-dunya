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
    """İsteğe bağlı alanlar verilmezse sahne_render, A2 öncesi koduyla (commit cabc8a5) piksel piksel aynı.
    1) Her ortamda: dondurulmuş A2 öncesi motor.py ile mevcut motor.py AYNI makinede çalıştırılır, ham kare SHA-256'ları
       birebir eşleşmeli (OpenCV/NumPy sürümü ve CPU farkından bağımsız; atlanmaz).
    2) Ortam taban kaydıyla aynıysa (python/opencv/numpy) mevcut çıktı kayıtlı tabanla da birebir eşleşmeli."""
    from motor.testler import sinema_regresyon as r
    taban = json.loads(r.TABAN.read_text())
    assert (taban["W"], taban["H"], taban["sure"]) == (r.W, r.H, r.SURE)
    assert r.eslik_ozeti() == taban["eslik"], "derinlik/efekt/kamera A2 öncesinden farklı: dondurulmuş karşılaştırma geçersiz"
    (tmp_path / "simdi").mkdir()
    (tmp_path / "once").mkdir()
    o = r.ozetle(tmp_path / "simdi")
    d = r.ozetle(tmp_path / "once", r.dondurulmus_motor())
    assert set(o) == set(d) == set(taban["sahneler"]) and len(o) == 10
    for sid in o:
        assert o[sid] == d[sid], f"{sid}: {sum(a != b for a, b in zip(o[sid], d[sid]))} kare A2 öncesi kodla farklı"
    if r.ortam() == taban["ortam"]:
        for sid, ozet in taban["sahneler"].items():
            assert o[sid] == ozet, f"{sid}: {sum(a != b for a, b in zip(o[sid], ozet))} kare kayıtlı tabandan farklı"
    else:
        print(f"ortam tabandan farklı ({r.ortam()} != {taban['ortam']}): kayıtlı taban yerine dondurulmuş kodla aynı ortamda karşılaştırıldı")


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


# ------------------------------------------------------------------ A2 mikro düzeltme: yakınlık destekli küçük parçalar

def _yuzen_disler(H=2000, W=3000):
    """Kale üretecindeki, kulelere değmeyen (çentik üstündeki) burç dişleri."""
    m = np.zeros((H, W), np.uint8)
    for x in range(1100, 1980, 60):
        if not any(x + 30 > tx and x < tx + 180 for tx in (1100, 1450, 1800)):
            cv2.rectangle(m, (x, 580), (x + 30, 620), 255, -1)
    return m


def test_yakin_parca_secimi_kurallari():
    """Birim: yakın+kontrastlı+gövde renkli parça eklenir; uzak, çok küçük ve zemin/açık renkli parça eklenmez."""
    img = np.full((300, 400, 3), (210, 200, 190), np.uint8)
    on = np.zeros((300, 400), np.uint8)
    cv2.rectangle(img, (100, 100), (300, 280), (50, 55, 60), -1); cv2.rectangle(on, (100, 100), (300, 280), 1, -1)   # ana gövde
    cv2.rectangle(img, (150, 80), (162, 92), (50, 55, 60), -1); cv2.rectangle(on, (150, 80), (162, 92), 1, -1)       # yakın diş
    cv2.rectangle(img, (20, 10), (34, 24), (50, 55, 60), -1); cv2.rectangle(on, (20, 10), (34, 24), 1, -1)           # uzak leke
    cv2.rectangle(img, (240, 92), (241, 93), (50, 55, 60), -1); cv2.rectangle(on, (240, 92), (241, 93), 1, -1)       # tuz (2x2)
    cv2.rectangle(img, (310, 150), (322, 162), (245, 245, 245), -1); cv2.rectangle(on, (310, 150), (322, 162), 1, -1)  # yakın açık
    n, lab, st, _ = cv2.connectedComponentsWithStats(on)
    y = g25.ayarlar()["kalite"]["yakin_parca"]
    ana = [int(np.argmax(st[1:, cv2.CC_STAT_AREA])) + 1]
    sec = g25.yakin_parca_sec(lab, st, ana, img, y)
    assert [lab[85, 155]] == sec                      # yalnızca yakın diş
    m, parca = g25._parcalar(on, 0.02, img, y)
    assert m[85, 155] == 1 and m[15, 25] == 0 and m[92, 240] == 0 and m[155, 315] == 0 and parca == 1
    m0, _ = g25._parcalar(on, 0.02, img, dict(y, acik=False))   # anahtar kapalı → A2 davranışı
    assert m0[85, 155] == 0


def test_kale_kopuk_burc_disleri_korunur_iou_gerilemez(kale_yuklu):
    yi, gt, bos, kutu, alfa, puan = kale_yuklu
    ih, iw = yi.shape[:2]
    yz = cv2.resize(_yuzen_disler(), (iw, ih), interpolation=cv2.INTER_AREA) > 127
    iou, bosluk = _olc(alfa, gt, bos)
    assert iou >= 0.99 and bosluk <= 0.10, (iou, bosluk)          # A2 referansı 0,992 / %0,2
    assert (alfa > 0.5)[yz].mean() >= 0.95                         # A2'de %16,7
    a = dict(g25.ayarlar()["kalite"])
    a["yakin_parca"] = dict(a["yakin_parca"], acik=False)
    alfa0, p0 = g25.maske(yi, kutu, a)
    assert (alfa0 > 0.5)[yz].mean() < 0.5 and g25.seviye(p0, a) == g25.seviye(puan) == "tam"


def test_kale_gurultu_parcalari_eklenmez():
    img, gt, bos, kutu = kale()
    uzak = [(1365, 710), (1715, 710)]                               # çentik ortası: gövdeden uzak koyu leke
    for x, y in uzak:
        cv2.circle(img, (x, y), 12, (55, 60, 70), -1)
    cv2.circle(img, (1302, 760), 12, (240, 240, 245), -1)            # gövdeye yakın açık renkli leke
    r = np.random.default_rng(1)
    tuz = [(int(r.uniform(1290, 1440)), int(r.uniform(640, 790))) for _ in range(40)]
    for x, y in tuz:
        img[y:y + 3, x:x + 3] = (55, 60, 70)
    yi = _yukle_gibi(img, 1920, 1080)
    ih, iw = yi.shape[:2]
    s = iw / 3000
    alfa, puan = g25.maske(yi, kutu)
    b = alfa > 0.5
    assert not any(b[int(y * s), int(x * s)] for x, y in uzak)
    assert not b[int(760 * s), int(1302 * s)]
    assert sum(b[int((y + 1) * s), int((x + 1) * s)] for x, y in tuz) == 0
    gt_y = cv2.resize(gt, (iw, ih), interpolation=cv2.INTER_AREA)
    assert _olc(alfa, gt_y, cv2.resize(bos, (iw, ih), interpolation=cv2.INTER_AREA))[0] >= 0.99


# ------------------------------------------------------------------ gerçek görsel kalibrasyonu

def test_kenburns_kurali_doluluk_ve_guvenilirlik():
    a = g25.ayarlar()["kalite"]
    # Matrakçı ölçümü: doluluk 0,911, kenar 2,60 → kenburns (A2 mikroda 'sinirli' seçiliyordu)
    assert g25.seviye({"kararlilik": 1.0, "kenar_orani": 2.60, "doluluk": 0.911, "parca": 1}, a) == "kenburns"
    # tam kadraj portre: doluluk yüksek ama maske güvenilir → elenmez
    assert g25.seviye({"kararlilik": 0.998, "kenar_orani": 4.59, "doluluk": 0.88, "parca": 1}, a) == "tam"
    assert g25.seviye({"kararlilik": 0.998, "kenar_orani": 4.59, "doluluk": 0.93, "parca": 1}, a) == "sinirli"
    assert g25.seviye({"kararlilik": 0.90, "kenar_orani": 5.0, "doluluk": 0.86, "parca": 1}, a) == "kenburns"
    # Bellini ölçümü (doluluk 0,677) ve sentetik kale etkilenmez
    assert g25.seviye({"kararlilik": 0.998, "kenar_orani": 4.59, "doluluk": 0.677, "parca": 1}, a) == "tam"


def test_minyatur_ve_harita_turu_kenburns(tmp_path):
    img, *_ = kale()
    p = tmp_path / "m.png"
    cv2.imwrite(str(p), img)
    for tur in ("minyatur", "harita"):
        ek, rap = g25.hazirla(p, _kayit(tmp_path, p, gorsel_turu=tur), {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
        assert rap["seviye"] == "kenburns" and "gorsel_turu" in rap["puan"]["neden"] and "ozne_maskesi" not in ek
    ek, rap = g25.hazirla(p, _kayit(tmp_path, p, gorsel_turu="gravur"), {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
    assert rap["seviye"] == "tam" and "ozne_maskesi" in ek          # aynı görsel, başka tür: maske ve parallax


def test_yakin_parca_kutu_ici_ve_zincir():
    img = np.full((300, 400, 3), (210, 200, 190), np.uint8)
    on = np.zeros((300, 400), np.uint8)

    def blok(x0, y0, x1, y1):
        cv2.rectangle(img, (x0, y0), (x1, y1), (50, 55, 60), -1)
        cv2.rectangle(on, (x0, y0), (x1, y1), 1, -1)
    blok(100, 120, 300, 280)          # gövde
    blok(150, 98, 160, 108)           # gövdeye 11 px → eklenir
    blok(172, 98, 182, 108)           # gövdeye 11 px → eklenir
    blok(194, 80, 204, 90)            # gövdeye 29 px ama eklenmiş dişe 11 px → zincirle eklenir
    blok(250, 70, 260, 80)            # her şeye > 15 px → eklenmez
    blok(320, 100, 330, 110)          # kutu dışında (gövdeye yakın olsa da) → eklenmez
    n, lab, st, _ = cv2.connectedComponentsWithStats(on)
    y = g25.ayarlar()["kalite"]["yakin_parca"]
    ana = [int(np.argmax(st[1:, cv2.CC_STAT_AREA])) + 1]
    kutu = (90, 60, 225, 230)        # x, y, w, h (maske ölçeği)
    sec = g25.yakin_parca_sec(lab, st, ana, img, y, kutu)
    assert sorted(lab[[103, 103, 85], [155, 177, 199]].tolist()) == sec
    assert lab[75, 255] not in sec and lab[105, 325] not in sec


def test_tuval_hedef_yuksekligin_olcek_kati(tmp_path):
    H, W = 4200, 3100
    img = np.full((H, W, 3), (190, 200, 205), np.uint8)
    cv2.ellipse(img, (1550, 2600), (900, 1500), 0, 0, 360, (50, 55, 60), -1)
    p = tmp_path / "buyuk.png"
    cv2.imwrite(str(p), img)
    k = _kayit(tmp_path, p, ozne_bilgisi={"kutu": [0.15, 0.08, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")
    ek, rap = g25.hazirla(p, k, {"hareket": "push_in"}, 1920, 1080, tmp_path, 1)
    assert rap["tuval"] and rap["tuval_boyut"][1] == round(1080 * 1.25)
    assert abs(rap["tuval_boyut"][0] / rap["tuval_boyut"][1] - 16 / 9) < 0.01
    t = cv2.imread(ek["gorsel"])
    assert t.shape[0] == round(1080 * 1.25)
    a = dict(g25.ayarlar())
    a["kalite"] = dict(a["kalite"], tuval_hareket=dict(a["kalite"]["tuval_hareket"], olcek_kat=0))
    import motor.uretim.gorsel25d as mod
    eski = mod.ayarlar
    mod.ayarlar = lambda: a
    try:
        ek0, rap0 = g25.hazirla(p, k, {"hareket": "push_in"}, 1920, 1080, tmp_path / "eski", 1) if (tmp_path / "eski").mkdir() is None else None
    finally:
        mod.ayarlar = eski
    assert rap0["tuval_boyut"][1] > 1500                               # olcek_kat 0 → A2 mikro (kaynak çözünürlük)


# ------------------------------------------------------------------ A2 mikro düzeltme: dikey görsel 16:9 tuval hareketi

def _portre(tmp_path, H=2400, W=1500):
    img = np.full((H, W, 3), (190, 200, 205), np.uint8)
    cv2.ellipse(img, (750, 1500), (430, 880), 0, 0, 360, (50, 55, 60), -1)
    cv2.circle(img, (750, 520), 230, (60, 80, 120), -1)                 # baş (görselin üst bölümü)
    p = tmp_path / "portre.png"
    cv2.imwrite(str(p), img)
    return p


def test_tuval_push_in_zoom_tavani_ve_tilt(tmp_path):
    from kaos.sinema import kamera
    p = _portre(tmp_path)
    k = _kayit(tmp_path, p, ozne_bilgisi={"kutu": [0.15, 0.08, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")
    ek, rap = g25.hazirla(p, k, {"hareket": "push_in", "guc": 1.4, "odak": [0.5, 0.2]}, 1920, 1080, tmp_path, 1)
    assert rap["tuval"] and ek["guc"] == 1.0 and ek["odak"] is None and ek["kamera"]["ease"] == "inout"
    u = np.linspace(0, 1, 91)
    yol = np.array([kamera.konum(ek["kamera"], t, None, 1.0)[:3] for t in u])
    cx, cy, z = yol.T
    oz = ek["izleme_oranlari"]
    assert z.max() <= 1.06 + 1e-9 and (1 + (z - 1) * oz["ozne_zoom"]).max() <= 1.06 + 1e-9 and (1 + (z - 1) * oz["arka_zoom"]).max() <= 1.06 + 1e-9
    assert np.allclose(cx, 0.5) and np.all(np.diff(cy) <= 1e-12) and cy[0] - cy[-1] > 0.03   # baş yönünde tilt
    hiz = np.abs(np.diff(cy))
    assert hiz[0] < 0.1 * hiz.max() and hiz[-1] < 0.1 * hiz.max()                               # yumuşak başla / bitir
    # _matris sınırı: merkez hiçbir karede görselin dışına itilmiyor (kırpma yerine gerçek tilt) ve üst/alt korunur
    gor = 1.0 / (1.04 * z)
    ust, alt = cy - gor / 2, cy + gor / 2
    assert ust.min() >= -1e-9 and alt.max() <= 1 + 1e-9
    assert gor.min() >= 0.90 and ust[-1] <= 0.02                                                 # bitişte baş kesilmez
    m = cv2.imread(ek["ozne_maskesi"], cv2.IMREAD_UNCHANGED)
    t_ = cv2.imread(ek["gorsel"])
    x0 = (t_.shape[1] - int(round(t_.shape[0] * 1500 / 2400))) // 2
    assert m[:, : x0 - 2].max() == 0 and m[:, -(x0 - 2):].max() == 0                            # yanlar maskede yok


def test_tuval_disi_hareket_degismez(tmp_path):
    img, *_ = kale(1500, 1000)
    p = tmp_path / "yatay.png"
    cv2.imwrite(str(p), img)
    k = _kayit(tmp_path, p)
    ek, rap = g25.hazirla(p, k, {"hareket": "push_in", "guc": 1.2, "odak": [0.5, 0.4]}, 1920, 1080, tmp_path, 1)
    beklenen, _ = g25.hareket("push_in", (1500, 1000), 1920, 1080, 1.2)
    assert not rap["tuval"] and ek["kamera"] == beklenen and "guc" not in ek and "odak" not in ek
    # Shorts çıktısında dikey görsel tuvale girmez, tuval hareketi uygulanmaz
    pp = _portre(tmp_path)
    ek2, rap2 = g25.hazirla(pp, _kayit(tmp_path, pp), {"hareket": "push_in"}, 1080, 1920, tmp_path, 1)
    assert not rap2["tuval"] and ek2["kamera"] == g25.hareket("push_in", (1500, 2400), 1080, 1920, 1.0)[0]


def test_tuval_hareketi_render_kareleri(tmp_path, monkeypatch):
    p = _portre(tmp_path)
    k = _kayit(tmp_path, p, ozne_bilgisi={"kutu": [0.15, 0.08, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")
    yol = tmp_path / "kayit.json"
    yol.write_text(json.dumps({"gorseller": [k]}))
    monkeypatch.setattr(tg, "KAYIT", yol)
    monkeypatch.setattr(render, "KOK", tmp_path / "uretim")
    c = {"id": "P", "cumleler": ["C1"], "sure_sn": 1.0, "tur": "gorsel25d", "metin": "x", "gorsel25d": {"gorsel_id": "t_g", "hareket": "push_in"}}
    r = render.render(str(_plan(tmp_path, c, (480, 270))), "P")
    assert r["durum"] == "TAMAM" and r["kalite"]["tuval"] and r["olculen"]["uretilen_kare"] == 30
    kareler = []
    for t in (0.0, 0.5, 0.95):
        gk = tmp_path / f"k{t}.png"
        import subprocess
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", r["video"], "-frames:v", "1", str(gk)], check=True)
        kareler.append(cv2.imread(str(gk)))
    for kr in kareler:   # başın üst kenarı başlangıç, orta ve bitişte kadrajın içinde (kesilmiyor)
        orta = kr[:, 170:310].astype(int)
        bas = np.abs(orta - np.array([60, 80, 120])).max(2) < 35
        assert bas.sum() > 1500 and np.nonzero(bas)[0].min() > 5


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


def _gercek_durum():
    from motor.testler.gorsel25d_kanit import gercek_gorseller
    try:
        return gercek_gorseller()
    except Exception as e:   # kayıt okunamıyorsa bu da raporlanır (sessiz geçiş yok)
        return [], [f"kayıt okunamadı: {e}"]


_GERCEK, _GERCEK_NOT = _gercek_durum()


def test_gercek_gorsel_dosyasi_varsa_kapidan_gecmeli():
    """Dosyası diskte olan bir kayıt lisans/SHA kapısından geçmiyorsa test BAŞARISIZ olur (atlanmaz, gizlenmez)."""
    kapi = [n for n in _GERCEK_NOT if n.startswith("KAPI ")]
    assert not kapi, kapi


@pytest.mark.skipif(not _GERCEK, reason="lisansı doğrulanmış gerçek tarihî görsel diskte yok: "
                    + ("; ".join(_GERCEK_NOT) if _GERCEK_NOT else "assets/tarihi_gorsel/ içinde kayıt yok"))
def test_gercek_tarihi_gorsel_kanit(tmp_path):
    """Gerçek görsel eklendiğinde kendiliğinden devreye girer: lisans + SHA, maske, dolgu, seviye, hareket, render
    süreleri ve kanıt panoları. Panolar ONBELLEK/faz53a_gercek_kanit/<gorsel_id>/ altına yazılır (depo kirlenmez)."""
    from motor.testler.gorsel25d_kanit import kanit_uret
    for k in _GERCEK:
        hedef = ayar.ONBELLEK / "faz53a_gercek_kanit" / k["gorsel_id"]
        o = kanit_uret(k["gorsel_id"], hedef, sure=2.0)
        assert o["kalite"]["seviye"] in ("tam", "sinirli", "kenburns")
        assert o["render"]["uretilen_kare"] == o["render"]["kare"]
        if o["kalite"]["seviye"] != "kenburns":
            assert o["kalite"]["kayma_px"] <= o["kalite"]["kayma_siniri_px"] + 0.5
        for ad in ("1_maske_dolgu.jpg", "3_hareket.jpg", "4_seviyeler.jpg", "ozet.json"):
            assert (hedef / ad).is_file(), ad
        print(f"GERÇEK GÖRSEL KANITI: {hedef}")
