"""Kamera geometrisi: bir karakterin kamera hareketi boyunca ekranda ne kadar büyük göründüğünü ÖLÇER
(Godot Camera3D ile aynı izdüşüm: dikey FOV, KEEP_HEIGHT). Plan denetimi mesafe sınıfını buradan hesaplar."""
from __future__ import annotations

import math

import numpy as np

from motor.uretim import veri


def kolay(t: float, tip: str) -> float:
    if tip == "giris":
        return t * t
    if tip == "cikis":
        return 1 - (1 - t) * (1 - t)
    if tip == "giris_cikis":
        return t * t * (3 - 2 * t)
    return t


def kamera_ani(kamera: dict, t: float) -> tuple[np.ndarray, np.ndarray, float]:
    u = kolay(t, kamera.get("yumusatma", "giris_cikis"))
    b, s = kamera["bas"], kamera["son"]
    k = np.array(b["konum"]) * (1 - u) + np.array(s["konum"]) * u
    h = np.array(b["hedef"]) * (1 - u) + np.array(s["hedef"]) * u
    return k, h, b["fov"] * (1 - u) + s["fov"] * u


def karakter_konumu(c: dict, zaman: float) -> np.ndarray:
    """Plan koordinatı: konum [x, z] (Godot), yon_derece: 0 = +Z'ye bakar; hız ile ileri hareket."""
    a = math.radians(c.get("yon_derece", 0.0))
    ileri = np.array([math.sin(a), 0.0, math.cos(a)])
    p = np.array([c["konum"][0], 0.0, c["konum"][1]])
    return p + ileri * c.get("hiz_m_sn", 0.0) * zaman


def ekran(kamera_konum, hedef, fov, nokta, en_boy):
    ileri = hedef - kamera_konum
    ileri = ileri / np.linalg.norm(ileri)
    sag = np.cross(ileri, [0, 1, 0])
    sag = sag / np.linalg.norm(sag)
    yukari = np.cross(sag, ileri)
    v = nokta - kamera_konum
    z = float(v @ ileri)
    if z <= 0.05:
        return None
    th = math.tan(math.radians(fov) / 2)
    y = float(v @ yukari) / (z * th)
    x = float(v @ sag) / (z * th * en_boy)
    return x, y, z, th


def olc(cekim: dict, en_boy: float, boy: float | None = None) -> dict:
    """Her karakter için: görünür mü, en büyük ekran oranı, o oranın sınıfı."""
    m = veri.kural("mesafe")
    boy = boy or m["karakter_boyu_m"]
    n, pay = m["ornekleme"], m["kadraj_payi"]
    sonuc = {}
    for i, c in enumerate(cekim.get("karakterler", [])):
        en_buyuk, gorunur = 0.0, False
        for j in range(n):
            t = j / (n - 1)
            k, h, fov = kamera_ani(cekim["kamera"], t)
            ayak = karakter_konumu(c, t * cekim["sure_sn"])
            bas = ayak + np.array([0, boy * c.get("olcek", 1.0), 0])
            e1, e2 = ekran(k, h, fov, ayak, en_boy), ekran(k, h, fov, bas, en_boy)
            if e1 is None and e2 is None:
                continue
            # kadrajda mı (ayak ile baş arasındaki herhangi bir parça)
            xs = [e[0] for e in (e1, e2) if e]
            ys = [e[1] for e in (e1, e2) if e]
            if min(xs) > 1 + pay or max(xs) < -1 - pay or min(ys) > 1 + pay or max(ys) < -1 - pay:
                continue
            gorunur = True
            z = min(e[2] for e in (e1, e2) if e)
            th = (e1 or e2)[3]
            oran = boy * c.get("olcek", 1.0) / (2 * z * th)
            en_buyuk = max(en_buyuk, oran)
        sinif = None
        if gorunur:
            sinif = "yakin" if en_buyuk > m["sinirlar"]["yakin"] else ("uzak" if en_buyuk < m["sinirlar"]["uzak"] else "orta")
        sonuc[i] = {"takim": c["takim"], "gorunur": gorunur, "ekran_orani": round(en_buyuk, 3), "mesafe": sinif}
    return sonuc


def nokta_gorunurlugu(cekim: dict, k: dict, yukseklik: float, en_boy: float, n: int = 9) -> float:
    """Karakterin ayağının `yukseklik` m üstündeki noktanın (örn. taşıdığı sancağın tepesi) kamera hareketi boyunca
    kadrajda kaldığı anların oranı (0..1)."""
    icinde = 0
    for j in range(n):
        t = j / (n - 1)
        kk, h, fov = kamera_ani(cekim["kamera"], t)
        p = karakter_konumu(k, t * cekim["sure_sn"]) + np.array([0, yukseklik, 0])
        e = ekran(kk, h, fov, p, en_boy)
        if e and -1 <= e[0] <= 1 and -1 <= e[1] <= 1:
            icinde += 1
    return icinde / n
