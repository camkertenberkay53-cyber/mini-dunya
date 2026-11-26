"""Faz-53A A2: 2.5D kalite katmanı (kaos/sinema/motor.sahne_render'ın isteğe bağlı girişlerini hazırlar).

Akış (hazirla):
  1. Görsel sahne_render ile aynı ölçüde yüklenir (motor._yukle), kirp uygulanır.
  2. Dikey görsel + yatay çıktı: özgün görsel kırpılmadan 16:9 tuvalin ortasına konur; yanlar görselin bulanık
     genişletilmiş hâli (yanlar maskeye girmez → özne parallax'ına katılmaz).
  3. Maske: GrabCut (uzun kenar ≤ maske_olcek, grabcut_tur tur) + en büyüğün parca_esik'inden büyük bütün parçalar +
     yönlendirmeli filtre (yalnızca NumPy + cv2.boxFilter). Kararlılık için kararlilik_tur'a kadar sürdürülür.
  4. Kalite puanı → seviye: tam | sinirli | kenburns (hata değil; ölçüm raporuna yazılır).
  5. Boşluk doldurma: inpaint (≤ maske_olcek) yumuşak kenarın tamamı + pay; isteğe bağlı düşük opaklıklı, yerel
     standart sapmaya uyarlı ince gürültü/tarama dokusu (doku_doldurma.acik).
  6. Hareket: belgesel eğrisi (ease in-out), kaynak çözünürlüğe göre zoom tavanı; özne–arka plan göreli kayması seviye
     sınırına (px) göre ölçeklenir (zemin bükmesi dahil ölçülür).
Konudan bağımsızdır; bütün eşikler kurallar/gorsel.yaml → gorsel25d altındadır.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from motor.uretim import veri

SURUM = "g25-kalite-2"


def ayarlar() -> dict:
    return veri.kural("gorsel").get("gorsel25d", {})


def kalite_acik() -> bool:
    return bool(ayarlar().get("kalite", {}).get("acik", False))


# ------------------------------------------------------------------ yönlendirmeli filtre (He vd. 2010)

def yonlendirmeli_filtre(rehber: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """rehber: gri 0..1 float32, p: filtrelenecek 0..1 float32. Yalnızca cv2.boxFilter (opencv-python-headless)."""
    k = (2 * r + 1, 2 * r + 1)

    def kutu(x):
        return cv2.boxFilter(x, -1, k, normalize=True, borderType=cv2.BORDER_REFLECT)
    I = rehber.astype(np.float32)
    p = p.astype(np.float32)
    mI, mp = kutu(I), kutu(p)
    cov = kutu(I * p) - mI * mp
    var = kutu(I * I) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    return kutu(a) * I + kutu(b)


# ------------------------------------------------------------------ tuval

def tuval(img: np.ndarray, W: int, H: int, esik: float) -> tuple[np.ndarray, int]:
    """Dikey (en/boy < esik) görsel ve yatay çıktı: özgün görsel ortada, kırpılmadan; yanlar bulanık genişletilmiş
    arka plan. Dönüş: (tuval, sol_ofset). Uygulanmazsa (img, -1)."""
    ih, iw = img.shape[:2]
    if W / H < 1.2 or iw / ih >= esik:
        return img, -1
    cw = int(round(ih * W / H))
    if cw <= iw:
        return img, -1
    s = cw / iw
    gen = cv2.resize(img, (cw, int(round(ih * s))), interpolation=cv2.INTER_AREA)
    y0 = (gen.shape[0] - ih) // 2
    gen = gen[y0:y0 + ih]
    # σ = cw/40 bulanıklık; 1/4 ölçekte hesaplanıp büyütülür (büyük tuvalde saniyeler yerine milisaniyeler)
    kucuk = cv2.resize(gen, (max(1, cw // 4), max(1, ih // 4)), interpolation=cv2.INTER_AREA)
    gen = cv2.resize(cv2.GaussianBlur(kucuk, (0, 0), cw / 160), (cw, ih), interpolation=cv2.INTER_CUBIC)
    gri = cv2.cvtColor(gen, cv2.COLOR_BGR2GRAY)[..., None].astype(np.float32)
    gen = (0.55 * (0.6 * gen.astype(np.float32) + 0.4 * gri)).astype(np.uint8)   # koyulaştır + doygunluğu azalt
    x0 = (cw - iw) // 2
    gen[:, x0:x0 + iw] = img
    return gen, x0


# ------------------------------------------------------------------ maske

def _parcalar(on: np.ndarray, esik: float, goruntu: np.ndarray | None = None, yakin: dict | None = None,
              kutu_px: tuple | None = None) -> tuple[np.ndarray, int]:
    """En büyüğün 'esik' oranından büyük parçalar tutulur. 'yakin' açıksa eşiğin altındaki küçük parçalar
    yakin_parca_sec kurallarıyla ayrıca değerlendirilir; dönen parça sayısı yalnız eşiği geçen ana parçalardır."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(on.astype(np.uint8))
    if n <= 1:
        return np.zeros_like(on, np.float32), 0
    alan = st[1:, cv2.CC_STAT_AREA]
    tut = [i + 1 for i, a in enumerate(alan) if a >= esik * alan.max()]
    if yakin and yakin.get("acik") and goruntu is not None:
        ek = yakin_parca_sec(lab, st, tut, goruntu, yakin, kutu_px)
        return np.isin(lab, tut + ek).astype(np.float32), len(tut)
    return np.isin(lab, tut).astype(np.float32), len(tut)


def yakin_parca_sec(lab: np.ndarray, st: np.ndarray, ana: list[int], goruntu: np.ndarray, y: dict,
                    kutu_px: tuple | None = None) -> list[int]:
    """Eşiğin altındaki küçük parçalardan özneye eklenecekler. Aday ancak HEPSİ sağlanırsa eklenir:
      - alan >= en_kucuk_oran × en büyük parça (tuz-biber gürültüsü dışarıda)
      - sınır kutusu bütünüyle özne kutusunun içinde (kutu_px = x, y, w, h; verilmişse)
      - çevresine göre kontrast >= kontrast (gri düzey) ve rengi ana gövdeye çevresinden daha yakın
      - ana gövdeye YA DA zaten eklenmiş bir parçaya uzaklığı <= yakinlik_px (maske ölçeğinde; zincirleme)
    Kutu dışındaki ya da gövdeye zincirle bağlanmayan süsler (ör. arka plan köşe süsleri) eklenmez.
    Maske dış sınırına dokunmaz: parçalar ya bütün eklenir ya hiç."""
    if not ana:
        return []
    alan = st[1:, cv2.CC_STAT_AREA]
    amax = alan.max()
    ana_m = np.isin(lab, ana)
    lab_ = cv2.cvtColor(goruntu, cv2.COLOR_BGR2LAB).astype(np.float32)
    gri = lab_[..., 0]
    ana_renk = lab_[ana_m].mean(0)
    cekirdek = np.ones((5, 5), np.uint8)
    adaylar = []
    for i in range(1, len(alan) + 1):
        if i in ana or alan[i - 1] < float(y.get("en_kucuk_oran", 0.0005)) * amax:
            continue
        if kutu_px is not None:
            x, yy, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]
            kx, ky, kw, kh = kutu_px
            if x < kx or yy < ky or x + w > kx + kw or yy + h > ky + kh:
                continue
        m = lab == i
        halka = (cv2.dilate(m.astype(np.uint8), cekirdek, iterations=2) > 0) & ~m & ~ana_m
        if not halka.any():
            continue
        if abs(float(gri[m].mean()) - float(gri[halka].mean())) < float(y.get("kontrast", 20)):
            continue
        renk = lab_[m].mean(0)
        if np.linalg.norm(renk - ana_renk) >= np.linalg.norm(renk - lab_[halka].mean(0)):
            continue
        adaylar.append(i)
    sinir = float(y.get("yakinlik_px", 15))
    secilen, secili_m = [], ana_m.copy()
    while adaylar:
        uzak = cv2.distanceTransform((~secili_m).astype(np.uint8), cv2.DIST_L2, 3)
        yeni = [i for i in adaylar if float(uzak[lab == i].min()) <= sinir]
        if not yeni:
            break
        for i in yeni:
            adaylar.remove(i)
            secilen.append(i)
            secili_m |= lab == i
    return sorted(secilen)


def _bolge(kutu, iw, ih, pay):
    """Özne kutusu + her yönde kutu boyutunun 'pay' oranı (GrabCut'ın arka plan örneği için)."""
    bw, bh = (kutu[2] - kutu[0]) * iw, (kutu[3] - kutu[1]) * ih
    x0, y0 = max(0, int(kutu[0] * iw - pay * bw)), max(0, int(kutu[1] * ih - pay * bh))
    x1, y1 = min(iw, int(kutu[2] * iw + pay * bw)), min(ih, int(kutu[3] * ih + pay * bh))
    return x0, y0, x1, y1


def maske(img: np.ndarray, kutu: list[float], a: dict | None = None) -> tuple[np.ndarray, dict]:
    """img: BGR uint8 (sahne_render çözünürlüğü). kutu: [x0,y0,x1,y1] 0..1. Dönüş: (alfa 0..1 float32, bilgi).
    GrabCut yalnızca kutu + pay bölgesinde (uzun kenar ≤ maske_olcek) çalışır: daha hızlı ve bölgede daha ayrıntılı."""
    a = a or ayarlar().get("kalite", {})
    ih, iw = img.shape[:2]
    bx0, by0, bx1, by1 = _bolge(kutu, iw, ih, float(a.get("bolge_payi", 0.35)))
    roi = img[by0:by1, bx0:bx1]
    rh, rw = roi.shape[:2]
    k = min(1.0, float(a.get("maske_olcek", 1200)) / max(ih, iw))   # ölçek bütün görsele göre; yalnız bölge işlenir
    kc = cv2.resize(roi, (max(1, int(rw * k)), max(1, int(rh * k))), interpolation=cv2.INTER_AREA) if k < 1 else roi.copy()
    kh, kw = kc.shape[:2]
    sx, sy = kw / rw, kh / rh
    r = (int((kutu[0] * iw - bx0) * sx), int((kutu[1] * ih - by0) * sy),
         max(1, int((kutu[2] - kutu[0]) * iw * sx)), max(1, int((kutu[3] - kutu[1]) * ih * sy)))
    m = np.zeros((kh, kw), np.uint8)
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    t1, t2 = int(a.get("grabcut_tur", 5)), int(a.get("kararlilik_tur", 8))
    cv2.setRNGSeed(int(a.get("tohum", 0)))   # GrabCut OpenCV'nin genel RNG'sini kullanır: sonuç süreç geçmişine bağlı olmasın
    cv2.grabCut(kc, m, r, bg, fg, t1, cv2.GC_INIT_WITH_RECT)
    yk = a.get("yakin_parca")
    on5, parca = _parcalar((m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD), float(a.get("parca_esik", 0.02)), kc, yk, r)
    m8 = m.copy()
    if t2 > t1:
        cv2.grabCut(kc, m8, r, bg.copy(), fg.copy(), t2 - t1, cv2.GC_EVAL)
    on8, _ = _parcalar((m8 == cv2.GC_FGD) | (m8 == cv2.GC_PR_FGD), float(a.get("parca_esik", 0.02)), kc, yk, r)
    b5, b8 = on5 > 0.5, on8 > 0.5
    kararlilik = float((b5 & b8).sum() / max(1, (b5 | b8).sum()))
    up = cv2.resize(on5, (rw, rh), interpolation=cv2.INTER_LINEAR)
    gri = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    f = a.get("filtre", {"r": 8, "eps": 0.001})
    alfa_r = np.clip(yonlendirmeli_filtre(gri, up, int(f["r"]), float(f["eps"])), 0, 1)
    alfa_r[alfa_r < 0.04] = 0.0
    alfa = np.zeros((ih, iw), np.float32)
    alfa[by0:by1, bx0:bx1] = alfa_r
    # puan bileşenleri (bölge içinde)
    ikili = alfa_r > 0.5
    sinir = cv2.morphologyEx(ikili.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    gm = np.hypot(cv2.Sobel(gri, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gri, cv2.CV_32F, 0, 1, ksize=3))
    kenar = float(gm[sinir].mean() / (gm.mean() + 1e-6)) if sinir.any() else 0.0
    x0, y0, x1, y1 = (int(kutu[0] * iw) - bx0, int(kutu[1] * ih) - by0, int(kutu[2] * iw) - bx0, int(kutu[3] * ih) - by0)
    doluluk = float(ikili[y0:y1, x0:x1].mean()) if y1 > y0 and x1 > x0 else 0.0
    return alfa, {"kararlilik": round(kararlilik, 3), "kenar_orani": round(kenar, 2), "doluluk": round(doluluk, 3),
                  "parca": int(parca), "olcek": [kw, kh], "bolge": [bx0, by0, bx1, by1]}


def seviye(p: dict, a: dict | None = None) -> str:
    s = (a or ayarlar().get("kalite", {})).get("seviye", {})
    t, z = s.get("tam", {}), s.get("sinirli", {})
    kb = s.get("kenburns", {})
    # Maske görselin çoğunu kaplıyor VE güvenilirliği düşükse figür–zemin ayrımı yoktur (minyatür, harita, sayfa
    # düzeni): parallax anlamsız. Tam kadraj portreler (yüksek doluluk ama güvenilir maske) bu kurala takılmaz.
    if kb and p["doluluk"] >= kb.get("doluluk", 0.85) and (p["kenar_orani"] < kb.get("kenar_orani", 3.0)
                                                          or p["kararlilik"] < kb.get("kararlilik", 0.95)):
        return "kenburns"
    if (p["kararlilik"] >= t.get("kararlilik", 0.95) and p["kenar_orani"] >= t.get("kenar_orani", 2.0)
            and t.get("doluluk", [0.15, 0.9])[0] <= p["doluluk"] <= t.get("doluluk", [0.15, 0.9])[1]
            and 1 <= p["parca"] <= t.get("parca", 6)):
        return "tam"
    if (p["kararlilik"] >= z.get("kararlilik", 0.85) and p["kenar_orani"] >= z.get("kenar_orani", 1.3)
            and z.get("doluluk", [0.08, 0.95])[0] <= p["doluluk"] <= z.get("doluluk", [0.08, 0.95])[1] and p["parca"] >= 1):
        return "sinirli"
    return "kenburns"


# ------------------------------------------------------------------ boşluk doldurma

def dolgu(img: np.ndarray, alfa: np.ndarray, tohum: int, a: dict | None = None) -> tuple[np.ndarray, dict]:
    """Özne arkasını doldurur. Delik: yumuşak kenarın tamamı (alfa > 0.02) + pay. Inpaint deliğin çevresindeki bölgede
    (uzun kenar ≤ maske_olcek). Özgün görsel değişmez (kopya döner)."""
    a = a or ayarlar()
    ka = a.get("kalite", {})
    ih, iw = img.shape[:2]
    ys, xs = np.nonzero(alfa > 0.02)
    if len(xs) == 0:
        return img.copy(), {"delik_orani": 0.0, "doku": False}
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    x0, y0 = max(0, int(xs.min() - 0.3 * bw)), max(0, int(ys.min() - 0.3 * bh))
    x1, y1 = min(iw, int(xs.max() + 0.3 * bw)), min(ih, int(ys.max() + 0.3 * bh))
    roi = img[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    k = min(1.0, float(ka.get("maske_olcek", 1200)) / max(ih, iw))
    kw, kh = max(1, int(rw * k)), max(1, int(rh * k))
    ks = cv2.resize(roi, (kw, kh), interpolation=cv2.INTER_AREA) if k < 1 else roi.copy()
    pay = int(ka.get("dolgu_pay_px", 4))
    dk = cv2.resize((alfa[y0:y1, x0:x1] > 0.02).astype(np.uint8), (kw, kh), interpolation=cv2.INTER_NEAREST)
    dk = cv2.dilate(dk, np.ones((2 * pay + 1, 2 * pay + 1), np.uint8))
    onar = cv2.inpaint(ks, dk * 255, 5, cv2.INPAINT_TELEA)
    up = cv2.resize(onar, (rw, rh), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    delik_r = cv2.resize(dk.astype(np.float32), (rw, rh), interpolation=cv2.INTER_LINEAR)
    delik = np.zeros((ih, iw), np.float32)
    delik[y0:y1, x0:x1] = delik_r
    mf = np.clip(cv2.GaussianBlur(delik_r, (0, 0), 1.5) * 1.5, 0, 1)[..., None]
    arka = img.copy()
    bolge = roi.astype(np.float32) * (1 - mf) + up * mf
    bilgi = {"delik_orani": round(float((delik > 0.5).mean()), 4), "doku": False, "bolge": [x0, y0, x1, y1]}
    dd = a.get("doku_doldurma", {})
    if dd.get("acik", False):
        # yerel std'ye uyarlı ince doku: deliğin dışındaki yüksek frekansın yerel genliği deliğe taşınır (yama kopyalama yok)
        gri = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hp = gri - cv2.GaussianBlur(gri, (0, 0), 1.5)
        dis = (delik_r < 0.5).astype(np.float32)
        w = int(dd.get("pencere_px", 61)) | 1
        e2 = cv2.boxFilter(hp * hp * dis, -1, (w, w)) / (cv2.boxFilter(dis, -1, (w, w)) + 1e-4)
        e2 = cv2.dilate(e2, np.ones((w // 2 | 1, w // 2 | 1), np.uint8)) * (1 - dis) + e2 * dis
        std = np.sqrt(np.maximum(e2, 0))
        g = np.random.default_rng(tohum).normal(0, 1, (rh, rw)).astype(np.float32)
        g = cv2.GaussianBlur(g, (0, 0), sigmaX=float(dd.get("tarama_x", 1.2)), sigmaY=float(dd.get("tarama_y", 0.5)))
        g /= g.std() + 1e-6
        bolge = bolge + (g * std * float(dd.get("opaklik", 0.5)))[..., None] * mf
        bilgi["doku"] = True
    arka[y0:y1, x0:x1] = np.clip(bolge, 0, 255).astype(np.uint8)
    return arka, bilgi


# ------------------------------------------------------------------ hareket

def hareket(ad_ya_da_dict, kaynak: tuple[int, int], W: int, H: int, guc: float, a: dict | None = None) -> tuple[dict, dict]:
    """Belgesel eğrisi (inout) + zoom tavanı. kaynak: yüklemeden ÖNCEKİ özgün piksel boyutu (genişlik, yükseklik)."""
    from kaos.sinema import kamera
    a = a or ayarlar().get("kalite", {})
    if isinstance(ad_ya_da_dict, dict):
        bas, son = list(ad_ya_da_dict["bas"]), list(ad_ya_da_dict["son"])
    else:
        b, s_, _e = kamera.HAREKETLER.get(ad_ya_da_dict, kamera.HAREKETLER["zoom_in"])
        bas, son = list(b), list(s_)
    sw, sh = kaynak
    tavan = max(1.0, float(a.get("zoom_tolerans", 1.1)) / (max(W / sw, H / sh) * 1.04))
    zmax = 1 + (max(bas[2], son[2]) - 1) * guc
    oran = 1.0
    if zmax > tavan and zmax > 1:
        oran = max(0.0, (tavan - 1) / (zmax - 1))
        bas[2] = 1 + (bas[2] - 1) * oran
        son[2] = 1 + (son[2] - 1) * oran
    return {"bas": bas, "son": son, "ease": "inout"}, {"zoom_tavani": round(tavan, 3), "zoom_kisma": round(oran, 3)}


def tuval_hareketi(kam: dict, tavan: float = 1.06, pay: float = 0.8) -> dict:
    """Yalnızca dikey görsel 16:9 tuvaldeyken (A2 mikro düzeltme): zoom en çok 'tavan'; push-in / zoom-in hareketi
    ağırlıkla hafif dikey kaydırmaya (tilt, figürün başına doğru) dönüşür, pull/zoom-out tersi. Eğri ease in-out kalır.
    cy, _matris'in görsel sınırına kırpmayacağı aralıkta tutulur (pay < 1)."""
    bas, son = list(kam["bas"]), list(kam["son"])
    zb, zs = bas[2], son[2]
    zlo, zhi = min(zb, zs), max(zb, zs)
    if zhi - zlo > 0.01:
        bas[2] = 1.0 + (zb - zlo) / (zhi - zlo) * (tavan - 1.0)
        son[2] = 1.0 + (zs - zlo) / (zhi - zlo) * (tavan - 1.0)
    else:
        bas[2], son[2] = min(zb, tavan), min(zs, tavan)

    def marj(z):   # merkezin dikeyde gidebileceği yarı aralık (16:9 tuval, _matris'teki 1,04 kaplama payı)
        return max(0.0, 0.5 - 1.0 / (2 * 1.04 * z)) * pay
    if zhi - zlo > 0.01:
        yon = 1.0 if zs > zb else -1.0   # yakınlaşırken yukarı (baş), uzaklaşırken aşağı
        bas[0] = son[0] = 0.5
        bas[1] = 0.5 + yon * marj(bas[2])
        son[1] = 0.5 - yon * marj(son[2])
    else:
        for k in (bas, son):
            k[1] = float(np.clip(k[1], 0.5 - marj(k[2]), 0.5 + marj(k[2])))
    return {"bas": bas, "son": son, "ease": "inout"}


def _sinir_noktalari(alfa: np.ndarray, n: int = 240) -> np.ndarray:
    b = (alfa > 0.5).astype(np.uint8)
    cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    p = np.concatenate([c[:, 0, :] for c in cs], 0) if cs else np.zeros((0, 2), np.int32)
    if len(p) > n:
        p = p[np.linspace(0, len(p) - 1, n).astype(int)]
    return p.astype(np.float64)


def kayma_olc(img_shape, noktalar, D, kam: dict, odak, guc: float, par: float, izleme: dict, ng: float,
              W: int, H: int, ornek: int = 31) -> float:
    """sahne_render'ın kare geometrisini taklit ederek özne katmanı ile arka plan arasındaki en büyük göreli kaymayı
    (px, çıktı karesinde) ölçer: afin fark + zemin bükmesi (remap) + nefes. Sarsıntı her iki katmanda eşit tutulur."""
    from kaos.sinema import kamera, motor
    if len(noktalar) == 0:
        return 0.0
    ih, iw = img_shape[:2]
    sahte = np.zeros((ih, iw), np.uint8)
    k0 = kamera.konum(kam, 0, odak, guc)
    fark = (D[noktalar[:, 1].astype(int).clip(0, ih - 1), noktalar[:, 0].astype(int).clip(0, iw - 1)] - 0.45) if D is not None else None
    P = np.c_[noktalar, np.ones(len(noktalar))]
    en = 0.0
    sinir = W * 0.018
    for u in np.linspace(0, 1, ornek):
        cx, cy, z, aci = kamera.konum(kam, u, odak, guc)
        M, _ = motor._matris(sahte, W, H, k0[0] + (cx - k0[0]) * izleme["arka_konum"], k0[1] + (cy - k0[1]) * izleme["arka_konum"],
                             k0[2] + (z - k0[2]) * izleme["arka_zoom"], aci)
        Mo, _ = motor._matris(sahte, W, H, k0[0] + (cx - k0[0]) * izleme["ozne_konum"], k0[1] + (cy - k0[1]) * izleme["ozne_konum"],
                              k0[2] + (z - k0[2]) * izleme["ozne_zoom"], aci)
        pb, po = P @ M.T, P @ Mo.T
        d = np.hypot(*(po - pb).T)
        if fark is not None:
            px_ = float(np.clip(((cx - k0[0]) * 1.2 + 0.6 * 0.006 * math.sin(math.pi * u)) * W * par, -sinir, sinir))
            py_ = float(np.clip((cy - k0[1]) * 0.8 * H * par, -sinir, sinir))
            zz = float(np.clip((z - k0[2]) * 0.25 * par, -0.04, 0.04))
            d = d + np.abs(fark) * (math.hypot(px_, py_) + np.hypot(pb[:, 0] - W / 2, pb[:, 1] - H / 2) * abs(zz))
        d = d + ng * (2.0 + 0.006 * H)
        en = max(en, float(d.max()))
    return en


def izleme_coz(img_shape, noktalar, D, kam, odak, guc, par, ng, W, H, sinir_px: float, k_ust: float = 1.0) -> tuple[dict, float, float]:
    """Arka plan oranları özgün (0.75 / 0.8); özne oranları arka + k·(0.45, 0.35). k ∈ [0, k_ust] sınırı sağlayan en
    büyük. Zemin bükmesi bütçeyi aşıyorsa par da küçültülür. Dönüş: (izleme, par, ölçülen kayma)."""
    def iz(k):
        return {"arka_konum": 0.75, "arka_zoom": 0.8, "ozne_konum": 0.75 + 0.45 * k, "ozne_zoom": 0.8 + 0.35 * k, "ozne_sarsinti": 1.0}
    taban = kayma_olc(img_shape, noktalar, D, kam, odak, guc, par, iz(0.0), ng, W, H)
    while taban > 0.6 * sinir_px and par > 0.05 and D is not None:
        par *= 0.6
        taban = kayma_olc(img_shape, noktalar, D, kam, odak, guc, par, iz(0.0), ng, W, H)
    lo, hi = 0.0, k_ust
    if kayma_olc(img_shape, noktalar, D, kam, odak, guc, par, iz(k_ust), ng, W, H) <= sinir_px:
        lo = k_ust
    else:
        for _ in range(12):
            m = (lo + hi) / 2
            if kayma_olc(img_shape, noktalar, D, kam, odak, guc, par, iz(m), ng, W, H) <= sinir_px:
                lo = m
            else:
                hi = m
    olcu = kayma_olc(img_shape, noktalar, D, kam, odak, guc, par, iz(lo), ng, W, H)
    return iz(lo), par, olcu


# ------------------------------------------------------------------ ana giriş

def anahtar_parcasi() -> str:
    """Önbellek anahtarına girecek: bu dosyanın içeriği + ilgili ayarlar."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    h.update(json.dumps([SURUM, ayarlar()], sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def hazirla(kaynak: Path, kayit: dict, g: dict, W: int, H: int, klasor: Path, tohum: int) -> tuple[dict, dict]:
    """sahne_render için ek alanlar (dosyalar klasor içine yazılır) ve ölçüm raporu."""
    from kaos.sinema import derinlik, motor
    a = ayarlar()
    ka = a.get("kalite", {})
    t0 = time.time()
    oz = cv2.imread(str(kaynak), cv2.IMREAD_COLOR)
    kaynak_boyut = (oz.shape[1], oz.shape[0])
    img = motor._yukle(str(kaynak), W, H)[..., :3]
    if g.get("kirp"):
        ih, iw = img.shape[:2]
        x0, y0, x1, y1 = g["kirp"]
        img = img[int(y0 * ih):int(y1 * ih), int(x0 * iw):int(x1 * iw)].copy()
        kaynak_boyut = (int(kaynak_boyut[0] * (x1 - x0)), int(kaynak_boyut[1] * (y1 - y0)))
    ih0, iw0 = img.shape[:2]
    tv = ka.get("tuval_hareket", {})
    olcek_kat = float(tv.get("olcek_kat", 0) or 0)
    tuval_olur = W / H >= 1.2 and iw0 / ih0 < float(ka.get("tuval_en_boy_esigi", 1.0)) and tv.get("acik", True)
    if tuval_olur and olcek_kat > 0 and ih0 > round(H * olcek_kat):
        # Tuval modunda zoom <= 1,06: kaynak yüksekliğin tamamı gereksiz; tuval hedef yüksekliğin olcek_kat katında kurulur
        h_ = int(round(H * olcek_kat))
        img = cv2.resize(img, (max(1, int(round(iw0 * h_ / ih0))), h_), interpolation=cv2.INTER_AREA)
        ih0, iw0 = img.shape[:2]
    img, x0 = tuval(img, W, H, float(ka.get("tuval_en_boy_esigi", 1.0)))
    ih, iw = img.shape[:2]
    if x0 >= 0:   # tuvalde özgün görselin kapladığı kaynak piksel genişliği (zoom tavanı için)
        kaynak_boyut = (int(kaynak_boyut[0] * iw / iw0), kaynak_boyut[1])
    gorsel = klasor / "g25_gorsel.png"
    cv2.imwrite(str(gorsel), img)
    ob = kayit.get("ozne_bilgisi") if isinstance(kayit.get("ozne_bilgisi"), dict) else {}
    kutu = g.get("ozne") or ob.get("kutu")
    if kutu and x0 >= 0:
        kutu = [(x0 + kutu[0] * iw0) / iw, kutu[1], (x0 + kutu[2] * iw0) / iw, kutu[3]]
    portre = ob.get("tur") == "insan_portre"
    derin = kayit.get("derinlik_uygunlugu", "orta") != "dusuk"
    guc = float(g.get("guc", 1.0))
    kam, hk = hareket(g.get("hareket", "zoom_in"), kaynak_boyut, W, H, guc, ka)
    odak = g.get("odak")
    ek = {"gorsel": str(gorsel), "kamera": kam, "zemin_derinlik_aktif": derin,
          "nefes_aktif": portre, "nefes_genlik": float(ka.get("nefes_portre_genlik", 0.4))}
    k_ust = 1.0
    tv = ka.get("tuval_hareket", {})
    if x0 >= 0 and tv.get("acik", True):
        # A2 mikro düzeltme: dikey görsel 16:9 tuvalde — zoom ≤ tavan, push-in ağırlıkla tilt; güç hareketin içine
        # gömülür (sahne_render'a guc=1, odak yok) ki zoom tavanı aşılmasın. Özne katmanı kameradan fazla zoom yapmaz.
        tavan = min(float(tv.get("zoom_tavani", 1.06)), max(1.0, hk["zoom_tavani"]))
        gucl = {"bas": [0.5 + (v - 0.5) * guc if i < 2 else 1 + (v - 1) * guc for i, v in enumerate(kam["bas"])],
                "son": [0.5 + (v - 0.5) * guc if i < 2 else 1 + (v - 1) * guc for i, v in enumerate(kam["son"])], "ease": "inout"}
        kam = tuval_hareketi(gucl, tavan, float(tv.get("pay", 0.8)))
        guc, odak = 1.0, None
        ek.update({"kamera": kam, "guc": 1.0, "odak": None})
        k_ust = (1.0 - 0.8) / 0.35   # özne zoom oranı ≤ 1 (kameranın zoomunu aşmaz)
        hk = dict(hk, tuval_zoom_tavani=tavan)
    rapor = {"surum": SURUM, "tuval": x0 >= 0, "kaynak_px": list(kaynak_boyut), "hareket": kam, **hk,
             "tuval_boyut": [int(img.shape[1]), int(img.shape[0])] if x0 >= 0 else None,
             "zemin_derinlik": derin, "nefes": portre}
    t1 = time.time()
    tur_kb = str(kayit.get("gorsel_turu", "")) in set(ka.get("kenburns_turleri", []))
    # Faz-53B: otomatik özne tespiti kenburns önerdiyse (düşük güven / çok figür) ve kutu elle verilmediyse uyulur
    tespit_kb = (ka.get("tespit_onerisine_uy", True) and kayit.get("onerilen_seviye") == "kenburns"
                 and ob.get("kutu_kaynagi", "otomatik") != "elle" and not g.get("ozne"))
    if tur_kb:   # minyatür / harita: figür–zemin ayrımı yok, maske hesaplanmaz
        sev, puan, alfa = "kenburns", {"neden": f"gorsel_turu={kayit.get('gorsel_turu')}"}, None
    elif tespit_kb:
        sev, puan, alfa = "kenburns", {"neden": f"ozne_tespit={kayit.get('tespit_durumu')}"}, None
    elif not kutu:
        sev, puan, alfa = "kenburns", {"neden": "özne kutusu yok"}, None
    else:
        alfa, puan = maske(img, kutu, ka)
        sev = seviye(puan, ka)
    t2 = time.time()
    rapor.update({"seviye": sev, "puan": puan, "maske_sn": round(t2 - t1, 2), "kutu": kutu})
    if sev == "kenburns":
        ek.update({"parallax": 0.0})
        rapor.update({"dolgu_sn": 0.0, "kayma_px": 0.0, "hazirlik_sn": round(time.time() - t0, 2)})
        return ek, rapor
    arka, db = dolgu(img, alfa, tohum, a)
    t3 = time.time()
    mpath, apath = klasor / "g25_maske.png", klasor / "g25_arka.png"
    cv2.imwrite(str(mpath), (alfa * 65535).astype(np.uint16))
    cv2.imwrite(str(apath), arka)
    D = derinlik.harita(arka, None, float(g.get("ufuk", 0.38)))[0] if derin else None
    ng = float(ek["nefes_genlik"]) if portre else 0.0
    sinir_px = float(ka.get("kayma_px", {}).get(sev, 20 if sev == "tam" else 15))
    izleme, par, olcu = izleme_coz(img.shape, _sinir_noktalari(alfa), D, kam, odak, guc, 1.0, ng, W, H, sinir_px, k_ust)
    ek.update({"ozne_maskesi": str(mpath), "arka_plan_dolgu": str(apath), "izleme_oranlari": izleme, "parallax": round(par, 4)})
    rapor.update({"dolgu": db, "dolgu_sn": round(t3 - t2, 2), "kayma_px": round(olcu, 1), "kayma_siniri_px": sinir_px,
                  "izleme": izleme, "zemin_par": round(par, 4), "hazirlik_sn": round(time.time() - t0, 2)})
    return ek, rapor
