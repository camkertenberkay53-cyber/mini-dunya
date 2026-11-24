"""Görsel efektler (numpy + OpenCV, ücretsiz). Hepsi BGR uint8 kare üzerinde çalışır, yoğunluk 'guc' ile ayarlanır.
Efektler sahne başında bir kez hazırlanır (doku, partikül), sonra her kare için uygulanır."""
import math

import cv2
import numpy as np


def _gurultu_dokusu(w, h, tohum, olcekler=(64, 24, 9), kenar=True):
    """Pürüzsüz, döşenebilir duman/sis dokusu (0..1)."""
    r = np.random.default_rng(tohum)
    acc = np.zeros((h, w), np.float32)
    top = 0
    for i, s in enumerate(olcekler):
        k = r.random((max(2, h // s), max(2, w // s))).astype(np.float32)
        acc += cv2.resize(k, (w, h), interpolation=cv2.INTER_CUBIC) * (1.0 / (i + 1))
        top += 1.0 / (i + 1)
    acc = cv2.GaussianBlur(acc / top, (0, 0), 6)
    acc = (acc - acc.min()) / (np.ptp(acc) + 1e-6)
    return acc


class Partikul:
    """toz, kivilcim (kor), kar, yagmur partikülleri."""

    AYAR = {
        'toz':      dict(n=140, boy=(1.0, 3.2), hiz=(-14, 14, -10, 6), renk=(170, 205, 235), parlak=0.55, blur=1.4),
        'kivilcim': dict(n=90, boy=(1.2, 3.6), hiz=(-30, 30, -150, -60), renk=(60, 150, 255), parlak=1.0, blur=2.2),
        'kar':      dict(n=180, boy=(1.5, 4.0), hiz=(-20, 20, 40, 90), renk=(255, 255, 255), parlak=0.8, blur=1.2),
        'yagmur':   dict(n=260, boy=(1.0, 1.6), hiz=(-60, -40, 900, 1300), renk=(220, 220, 210), parlak=0.35, blur=0.0),
    }

    def __init__(self, tip, W, H, guc=1.0, tohum=3):
        a = self.AYAR[tip]
        self.tip, self.W, self.H, self.a = tip, W, H, a
        r = np.random.default_rng(tohum)
        n = int(a['n'] * guc * (W * H) / (1080 * 1920))
        self.x = r.uniform(0, W, n)
        self.y = r.uniform(0, H, n)
        self.r = r.uniform(*a['boy'], n) * W / 1080
        self.vx = r.uniform(a['hiz'][0], a['hiz'][1], n) * W / 1080
        self.vy = r.uniform(a['hiz'][2], a['hiz'][3], n) * W / 1080
        self.faz = r.uniform(0, 6.28, n)
        self.guc = guc

    def uygula(self, kare, t):
        a = self.a
        x = (self.x + self.vx * t + 12 * np.sin(t * 0.9 + self.faz)) % self.W
        y = (self.y + self.vy * t) % self.H
        kat = np.zeros(kare.shape[:2], np.float32)
        if self.tip == 'yagmur':
            for xi, yi in zip(x.astype(int), y.astype(int)):
                cv2.line(kat, (xi, yi), (xi - 4, yi + 34), 1.0, 1, cv2.LINE_AA)
        else:
            parla = 0.55 + 0.45 * np.sin(t * 3.0 + self.faz) if self.tip == 'kivilcim' else np.ones_like(x)
            for xi, yi, ri, pi in zip(x, y, self.r, parla):
                cv2.circle(kat, (int(xi), int(yi)), max(1, int(round(ri))), float(pi), -1, cv2.LINE_AA)
        if a['blur']:
            kat = cv2.GaussianBlur(kat, (0, 0), a['blur'])
            if self.tip == 'kivilcim':  # kor ışıltısı
                kat = kat + cv2.GaussianBlur(kat, (0, 0), 7) * 1.5
        kat = np.clip(kat * a['parlak'] * min(1.0, self.guc), 0, 1)[..., None]
        renk = np.array(a['renk'], np.float32)[None, None, :]
        return np.clip(kare.astype(np.float32) + kat * renk, 0, 255).astype(np.uint8)


class Duman:
    """duman / sis: kayan gürültü dokusu, alt kısımda yoğun (sis) ya da her yerde (duman)."""

    def __init__(self, tip, W, H, guc=1.0, tohum=5, renk=(200, 205, 210)):
        self.W, self.H, self.tip, self.guc = W, H, tip, guc
        self.doku = _gurultu_dokusu(W * 2, H, tohum, (90, 36, 14) if tip == 'duman' else (160, 60))
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        self.maske = (np.clip((y - 0.35) / 0.65, 0, 1) ** 1.3) if tip == 'sis' else np.full((H, 1), 0.85, np.float32)
        self.renk = np.array(renk, np.float32)[None, None, :]
        self.hiz = 38 if tip == 'duman' else 16

    def uygula(self, kare, t):
        ofs = int(t * self.hiz * self.W / 1080) % self.W
        d = self.doku[:, ofs:ofs + self.W]
        d = np.clip((d - 0.35) * 1.8, 0, 1) * self.maske
        al = (d * (0.36 if self.tip == 'duman' else 0.32) * self.guc)[..., None]
        return (kare.astype(np.float32) * (1 - al) + self.renk * al).astype(np.uint8)


class IsikHuzmesi:
    """Işık hüzmesi (god rays): kaynak noktasından yayılan sıcak çizgiler, hafif nabız."""

    def __init__(self, W, H, kaynak=(0.75, -0.05), guc=1.0, tohum=7, renk=(150, 210, 255)):
        r = np.random.default_rng(tohum)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        sx, sy = kaynak[0] * W, kaynak[1] * H
        ang = np.arctan2(yy - sy, xx - sx)
        mesafe = np.hypot(yy - sy, xx - sx) / max(W, H)
        bant = np.zeros_like(ang)
        for _ in range(9):
            a0, gen = r.uniform(-math.pi, math.pi), r.uniform(0.02, 0.06)
            bant += np.exp(-((np.angle(np.exp(1j * (ang - a0)))) / gen) ** 2) * r.uniform(0.4, 1.0)
        self.maske = (np.clip(bant, 0, 1.2) * np.exp(-mesafe * 1.6)).astype(np.float32)
        self.maske = cv2.GaussianBlur(self.maske, (0, 0), 9)
        self.renk = np.array(renk, np.float32)[None, None, :]
        self.guc = guc

    def uygula(self, kare, t):
        nabiz = 0.8 + 0.2 * math.sin(t * 1.7)
        return np.clip(kare.astype(np.float32) + (self.maske * 0.32 * self.guc * nabiz)[..., None] * self.renk, 0, 255).astype(np.uint8)


def parlama(kare, guc=1.0):
    """Glow / bloom: parlak bölgeler yumuşak ışık saçar."""
    k = kare.astype(np.float32)
    parlak = np.clip(k - 170, 0, 255)
    bl = cv2.GaussianBlur(parlak, (0, 0), 18)
    return np.clip(k + bl * 0.55 * guc, 0, 255).astype(np.uint8)


def vinyet_maskesi(W, H, guc=1.0):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / math.sqrt(2)
    return (1 - np.clip((d - 0.45) / 0.55, 0, 1) ** 1.8 * 0.55 * guc).astype(np.float32)[..., None]


def gren(kare, t, guc=1.0, tohum=0):
    r = np.random.default_rng(int(t * 1000) + tohum)
    g = r.normal(0, 7 * guc, kare.shape[:2]).astype(np.float32)[..., None]
    return np.clip(kare.astype(np.float32) + g, 0, 255).astype(np.uint8)


def alan_derinligi(kare, odak=(0.5, 0.45), yaricap=0.42, guc=1.0):
    """Odak dışı bulanıklık (DoF simülasyonu): odak elipsi net, kenarlar yumuşak."""
    H, W = kare.shape[:2]
    bl = cv2.GaussianBlur(kare, (0, 0), 6 * guc)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.hypot((xx / W - odak[0]) / 0.9, (yy / H - odak[1]) / 0.6)
    m = np.clip((d - yaricap) / 0.35, 0, 1)[..., None]
    return (kare * (1 - m) + bl * m).astype(np.uint8)


def renk_tonu(kare, tip='sicak', guc=1.0):
    """Sinematik renk derecelendirmesi."""
    k = kare.astype(np.float32)
    if tip == 'sicak':
        k[..., 2] *= 1 + 0.08 * guc
        k[..., 0] *= 1 - 0.06 * guc
    elif tip == 'soguk':
        k[..., 0] *= 1 + 0.08 * guc
        k[..., 2] *= 1 - 0.06 * guc
    elif tip == 'teal_turuncu':  # gölgeler camgöbeği, ışıklar turuncu
        l = k.mean(axis=2, keepdims=True) / 255
        k += (np.array([14, 4, -10]) * (1 - l) + np.array([-12, 2, 14]) * l) * guc
    # hafif kontrast eğrisi
    k = 255 * (0.5 + (k / 255 - 0.5) * (1 + 0.08 * guc))
    return np.clip(k, 0, 255).astype(np.uint8)
