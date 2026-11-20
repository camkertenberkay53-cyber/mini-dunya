"""MİNİ DÜNYA mekânları: katmanlı (parallax) arka planlar.
Her mekân 3 katmandır: uzak (bulanık, yavaş kayar), orta (karakterlerin durduğu zemin, kamerayla birebir),
ön (kameraya yakın, odak dışı, hızlı kayar; karakterlerin ÜSTÜNE çizilir).
Dünya koordinatı: karakterler y=1250'de durur. Zeminin arka kenarı y=GROUND."""
import math
from functools import lru_cache
import numpy as np
import cv2
from .draw import E, capsule, cel

X0, Y0, BW, BH = -1100, -700, 3500, 3000
GROUND = 1010
LOCATIONS = ['tezgah', 'lavabo', 'buzdolabi', 'baharat', 'zemin', 'cekmece', 'lonca']
REF = (550, 1050)
LAYER_K = {'far': 0.35, 'mid': 1.0, 'fg': 1.7}
LAYER_SC = {'far': 0.5, 'mid': 1.0, 'fg': 0.5}


class Layer:
    def __init__(self, name):
        self.sc = LAYER_SC[name]
        self.img = np.zeros((int(BH * self.sc), int(BW * self.sc), 4), np.uint8)

    def P(self, pts):
        return [((x - X0) * self.sc, (y - Y0) * self.sc) for x, y in pts]

    def cel(self, pts, col, w=6, **k):
        cel(self.img, self.P(pts), col, w=max(1, w * self.sc), **k)

    def grad_rect(self, x0, y0, x1, y1, c0, c1, horizontal=False):
        (a, b), (c, d) = self.P([(x0, y0), (x1, y1)])
        a, b, c, d = int(max(0, a)), int(max(0, b)), int(min(self.img.shape[1], c)), int(min(self.img.shape[0], d))
        if c <= a or d <= b:
            return
        n = (c - a) if horizontal else (d - b)
        u = np.linspace(0, 1, n, dtype=np.float32)[:, None]
        g = np.array(c0, np.float32) * (1 - u) + np.array(c1, np.float32) * u
        g = (g * 255).astype(np.uint8)
        if horizontal:
            self.img[b:d, a:c, :3] = g[None, :, :]
        else:
            self.img[b:d, a:c, :3] = g[:, None, :]
        self.img[b:d, a:c, 3] = 255

    def line(self, a, b, col, w):
        p = self.P([a, b])
        cv2.line(self.img, tuple(int(v * 4) for v in p[0]), tuple(int(v * 4) for v in p[1]),
                 tuple(int(c * 255) for c in col) + (255,), max(1, int(w * self.sc)), cv2.LINE_AA, shift=2)

    def blur(self, s):
        im = self.img.astype(np.float32)
        a = im[..., 3:4] / 255
        pre = np.concatenate([im[..., :3] * a, im[..., 3:4]], 2)
        pre = cv2.GaussianBlur(pre, (0, 0), s * self.sc)
        a2 = np.maximum(pre[..., 3:4], 1e-3)
        out = np.concatenate([pre[..., :3] / (a2 / 255), pre[..., 3:4]], 2)
        self.img = np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- ortak parçalar
def tiles(L, x0, y0, x1, y1, tw, th, c1, c2, grout, rng, stagger=True):
    L.grad_rect(x0, y0, x1, y1, grout, grout)
    r = 0
    y = y0
    while y < y1:
        x = x0 - (tw / 2 if stagger and r % 2 else 0)
        while x < x1:
            col = c1 if rng.random() > 0.18 else c2
            L.cel([(x + 5, y + 5), (x + tw - 5, y + 5), (x + tw - 5, y + th - 5), (x + 5, y + th - 5)], col,
                  w=3, shadow=0.12, rim=0.25, oc=tuple(c * 0.75 for c in grout))
            x += tw
        y += th
        r += 1


def window(L, x0, y0, x1, y1, frame=(0.95, 0.93, 0.88)):
    L.grad_rect(x0, y0, x1, y1, (1.0, 0.97, 0.85), (0.80, 0.90, 0.98))
    # dışarıda yapraklar (bulanık yeşil lekeler)
    rng = np.random.default_rng(4)
    for _ in range(40):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y0 + (y1 - y0) * 0.6)
        r = rng.uniform(40, 110)
        L.cel(E(cx, cy, r, r * 0.8), (0.45 + rng.uniform(0, 0.2), 0.68, 0.38), outline=False, shadow=0.2, rim=0)
    m = 34
    for xx in (x0, (x0 + x1) / 2, x1):
        L.cel([(xx - m / 2, y0), (xx + m / 2, y0), (xx + m / 2, y1), (xx - m / 2, y1)], frame, w=5)
    for yy in (y0, (y0 + y1) / 2, y1):
        L.cel([(x0 - m / 2, yy - m / 2), (x1 + m / 2, yy - m / 2), (x1 + m / 2, yy + m / 2), (x0 - m / 2, yy + m / 2)], frame, w=5)


def jar(L, x, base, w, h, glass, lid, label=None, content=None):
    L.cel(capsule(x, base - h + w * 0.25, x, base - w * 0.25, w / 2, n=12), glass, w=8, shadow=0.25, rim=0.45)
    if content:
        L.cel(capsule(x, base - h * 0.55, x, base - w * 0.25, w / 2 - 14, n=12), content, w=0, outline=False, shadow=0.3, rim=0)
    L.cel([(x - w * 0.42, base - h - 30), (x + w * 0.42, base - h - 30), (x + w * 0.42, base - h + 25), (x - w * 0.42, base - h + 25)], lid, w=8)
    if label:
        L.cel([(x - w * 0.36, base - h * 0.62), (x + w * 0.36, base - h * 0.62), (x + w * 0.36, base - h * 0.3), (x - w * 0.36, base - h * 0.3)], label, w=6, shadow=0.1)
    # parlama
    L.line((x + w * 0.28, base - h + 70), (x + w * 0.28, base - h * 0.45), (1, 1, 1), 14)


def mug(L, x0, x1, top, base, col, inner=(0.38, 0.22, 0.12), handle_side=-1, pattern=None):
    cx, w = (x0 + x1) / 2, (x1 - x0)
    hx = x0 if handle_side < 0 else x1
    hcy, hr = (top + base) / 2 - 40, (base - top) * 0.26
    angs = np.linspace(0.05, math.pi - 0.05, 24)
    outer = [(hx - handle_side * 20 + handle_side * (hr + 45) * 0.8 * math.sin(a), hcy - (hr + 45) * math.cos(a)) for a in angs]
    inn = [(hx - handle_side * 20 + handle_side * (hr - 40) * 0.8 * math.sin(a), hcy - (hr - 40) * math.cos(a)) for a in angs]
    L.cel(outer + inn[::-1], col, w=10, shadow=0.3, rim=0.35)
    body = [(x0, top), (x1, top)] + [(cx + w / 2 * math.cos(a), base - 40 + 40 * math.sin(a)) for a in np.linspace(0, math.pi, 20)]
    L.cel(body, col, w=10, shadow=0.3, rim=0.35)
    if pattern:
        rng = np.random.default_rng(2)
        for k in range(14):
            px, py = x0 + 60 + (k % 4) * (w - 120) / 3, top + 90 + (k // 4) * 130 + (40 if k % 2 else 0)
            if py < base - 80:
                L.cel(E(px, py, 28, 28), pattern, w=5, shadow=0.15, rim=0.2)
    L.cel(E(cx, top, w / 2, 48), shade3(col, 0.9), w=10, shadow=0.1)
    L.cel(E(cx, top + 6, w / 2 - 26, 32), inner, w=6, shadow=0.35, rim=0)


def shade3(c, k):
    return tuple(min(1, v * k) for v in c)


def counter(L, y_back, y_front, col, plank=260):
    L.grad_rect(X0, y_back, X0 + BW, y_front, shade3(col, 0.92), col)
    rng = np.random.default_rng(9)
    for i in range(70):
        y = y_back + 12 + i * (y_front - y_back) / 70 + rng.uniform(-4, 4)
        pts = [(x, y + 7 * math.sin(x / 140 + i * 1.7)) for x in range(X0, X0 + BW + 80, 80)]
        for a, b in zip(pts, pts[1:]):
            L.line(a, b, shade3(col, 0.84), 3)
    for x in range(X0, X0 + BW, plank * 3):
        L.line((x, y_back), (x - 120, y_front), shade3(col, 0.7), 5)
    L.cel([(X0, y_back - 22), (X0 + BW, y_back - 22), (X0 + BW, y_back + 6), (X0, y_back + 6)], shade3(col, 0.8), w=6, shadow=0.1)


# ---------------------------------------------------------------- mekânlar
def build_tezgah():
    rng = np.random.default_rng(1)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.94, 0.86, 0.70), (0.80, 0.66, 0.48))
    window(far, 800, -560, 1900, 520)
    tiles(far, X0, 560, X0 + BW, 1100, 150, 75, (0.62, 0.78, 0.70), (0.90, 0.88, 0.80), (0.88, 0.85, 0.78), rng)
    # raf ve kavanozlar
    far.cel([(X0, 330), (650, 330), (650, 368), (X0, 368)], (0.50, 0.32, 0.18), w=6)
    for x, w, h, c in [(-950, 120, 210, (0.85, 0.45, 0.25)), (-790, 90, 150, (0.30, 0.55, 0.65)), (-650, 140, 250, (0.95, 0.80, 0.45)),
                       (-460, 100, 170, (0.60, 0.32, 0.45)), (-300, 90, 130, (0.45, 0.66, 0.42)), (-150, 130, 220, (0.92, 0.55, 0.30)),
                       (40, 110, 180, (0.40, 0.48, 0.70)), (200, 90, 140, (0.85, 0.75, 0.55)), (350, 130, 230, (0.78, 0.38, 0.30))]:
        far.cel([(x, 330 - h), (x + w, 330 - h), (x + w, 330), (x, 330)], c, w=6, shadow=0.25, rim=0.3)
        far.cel([(x + 10, 300 - h), (x + w - 10, 300 - h), (x + w - 10, 335 - h), (x + 10, 335 - h)], (0.35, 0.24, 0.18), w=5)
    # sarkan bitki
    for k in range(9):
        a = k / 8
        far.cel(E(620 + 40 * math.sin(k), 400 + k * 70, 34, 18, ang=0.6 if k % 2 else -0.6), (0.30, 0.52, 0.30), w=4, shadow=0.2)
    far.cel([(560, 300), (700, 300), (680, 420), (580, 420)], (0.80, 0.42, 0.28), w=6)
    far.blur(9)

    mid = Layer('mid')
    counter(mid, GROUND, 2300, (0.72, 0.48, 0.28))
    # ince belli çay bardağı (arkada)
    tg = [(560, 600), (740, 600), (716, 750), (690, 830), (722, 1010), (578, 1010), (610, 830), (584, 750)]
    mid.cel(tg, (0.80, 0.42, 0.20), w=8, shadow=0.3, rim=0.5)
    mid.cel([(560, 600), (740, 600), (735, 632), (565, 632)], (0.95, 0.90, 0.80), w=6, shadow=0.1)
    mid.line((710, 640), (698, 800), (1, 0.95, 0.85), 9)
    mid.cel(E(650, 1016, 120, 22), (0.85, 0.85, 0.88), w=6, shadow=0.2)
    # dev kupa (solda)
    mug(mid, -330, 170, 420, 1040, (0.86, 0.36, 0.24), handle_side=1, pattern=(0.98, 0.86, 0.62))
    # kavanoz (sağda)
    jar(mid, 1260, 1040, 420, 600, (0.62, 0.80, 0.82), (0.36, 0.25, 0.20), label=(0.97, 0.92, 0.80), content=(0.95, 0.92, 0.85))
    # şeker küpleri ve kırıntılar
    for x, y, s in [(930, 1200, 110), (1040, 1230, 80)]:
        mid.cel([(x, y - s), (x + s, y - s - 20), (x + s + 26, y - 6), (x + 22, y + 12)], (0.98, 0.97, 0.94), w=6, shadow=0.25, rim=0.3)
        mid.cel([(x, y - s), (x + s, y - s - 20), (x + s - 14, y - s - 40), (x - 18, y - s - 18)], (1, 1, 1), w=6, shadow=0)
    for _ in range(14):
        cx, cy = rng.uniform(-100, 1300), rng.uniform(1100, 1700)
        if 380 < cx < 800 and cy < 1300:
            continue
        r = rng.uniform(8, 20)
        n = 6
        pts = [(cx + r * (0.6 + 0.5 * rng.random()) * math.cos(2 * math.pi * k / n), cy + r * 0.7 * (0.6 + 0.5 * rng.random()) * math.sin(2 * math.pi * k / n)) for k in range(n)]
        mid.cel(pts, (0.80, 0.58, 0.32), w=3, shadow=0.35, rim=0.25)
    # yatık kaşık (köprü)
    mid.cel([(-480, 1520), (900, 1380), (912, 1408), (-470, 1552)], (0.80, 0.82, 0.86), w=7, shadow=0.25, rim=0.5)
    mid.cel(E(1010, 1384, 130, 66, ang=-0.1), (0.82, 0.84, 0.88), w=7, shadow=0.3, rim=0.5)

    fg = Layer('fg')
    fg.cel(E(-120, 2050, 360, 320), (0.80, 0.12, 0.08), w=12, shadow=0.3, rim=0.3)
    fg.cel([(-150, 1740), (-40, 1770), (-190, 1800)], (0.25, 0.48, 0.18), w=8)
    fg.cel([(1000, 1900), (1900, 1840), (1950, 2500), (950, 2500)], (0.92, 0.75, 0.46), w=12, shadow=0.25)
    fg.cel([(1000, 1900), (1900, 1840), (1910, 1940), (1010, 1990)], (0.70, 0.42, 0.20), w=10, shadow=0.1)
    fg.blur(22)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=dict(src=(1350, -300), col=(1.0, 0.86, 0.60), shafts=0.20, warm=(1.04, 1.0, 0.92), dust=True))


def _fx_light(src, col, shafts, warm, dust=True, **k):
    d = dict(src=src, col=col, shafts=shafts, warm=warm, dust=dust)
    d.update(k)
    return d


def build_lavabo():
    rng = np.random.default_rng(2)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.88, 0.93, 0.95), (0.70, 0.80, 0.84))
    tiles(far, X0, -700, X0 + BW, 1100, 110, 110, (0.92, 0.95, 0.96), (0.62, 0.80, 0.86), (0.78, 0.84, 0.86), rng, stagger=False)
    window(far, -1000, -600, -200, 300, frame=(0.98, 0.98, 0.96))
    far.cel([(1300, 200), (1900, 200), (1900, 240), (1300, 240)], (0.85, 0.85, 0.88), w=6)
    for x, h, c in [(1350, 160, (0.95, 0.70, 0.75)), (1480, 220, (0.55, 0.80, 0.70)), (1620, 120, (1.0, 0.95, 0.70))]:
        far.cel(capsule(x + 40, 200 - h + 40, x + 40, 160, 45, n=10), c, w=6, shadow=0.25, rim=0.4)
    far.blur(9)
    mid = Layer('mid')
    counter(mid, GROUND, 2300, (0.86, 0.86, 0.84), plank=600)
    # lavabo gölü (sağda): çukur ve su
    mid.cel(E(1500, 1450, 820, 330), (0.70, 0.74, 0.78), w=10, shadow=0.35, rim=0.3)
    mid.cel(E(1500, 1480, 760, 280), (0.40, 0.66, 0.80), w=0, outline=False, shadow=0.25, rim=0.5)
    for k in range(5):
        mid.cel(E(1400 + k * 60, 1430 + k * 30, 160 - k * 20, 22 - k * 3), (0.75, 0.90, 0.97), outline=False, shadow=0, rim=0)
    # dev musluk
    mid.cel([(1380, 120), (1520, 120), (1520, 1010), (1380, 1010)], (0.78, 0.80, 0.84), w=10, shadow=0.35, rim=0.55)
    mid.cel(capsule(1450, 160, 1820, 160, 70, n=10), (0.80, 0.82, 0.86), w=10, shadow=0.35, rim=0.55)
    mid.cel(capsule(1780, 160, 1780, 360, 55, n=10), (0.80, 0.82, 0.86), w=10, shadow=0.35, rim=0.55)
    mid.cel(E(1450, 80, 120, 50), (0.85, 0.30, 0.30), w=8)
    # sünger ve sabun şişesi
    mid.cel([(-420, 760), (60, 720), (90, 1060), (-400, 1090)], (0.95, 0.85, 0.30), w=8, shadow=0.3, rim=0.3)
    mid.cel([(-420, 760), (60, 720), (60, 790), (-420, 830)], (0.35, 0.60, 0.30), w=8, shadow=0.2)
    for _ in range(18):
        x, y = rng.uniform(-380, 40), rng.uniform(860, 1040)
        mid.cel(E(x, y, 10, 7), (0.85, 0.72, 0.22), outline=False, shadow=0, rim=0)
    mid.cel(capsule(500, 300, 500, 960, 140, n=12), (0.55, 0.78, 0.55), w=10, shadow=0.3, rim=0.5)
    mid.cel([(450, 120), (550, 120), (560, 230), (440, 230)], (0.95, 0.95, 0.95), w=8)
    mid.cel([(420, 520), (580, 520), (580, 700), (420, 700)], (0.97, 0.97, 0.92), w=6, shadow=0.1)
    # baloncuklar
    for _ in range(9):
        x, y, r = rng.uniform(-200, 1100), rng.uniform(400, 1150), rng.uniform(30, 70)
        mid.cel(E(x, y, r, r), (0.85, 0.92, 1.0), w=4, shadow=0.1, rim=0.7, oc=(0.55, 0.70, 0.85))
    fg = Layer('fg')
    fg.cel([(-700, 1750), (300, 1800), (250, 2600), (-750, 2600)], (0.40, 0.70, 0.85), w=12, shadow=0.3)
    fg.blur(22)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((-600, -400), (0.92, 0.96, 1.0), 0.16, (0.98, 1.0, 1.04), drip=(1780, 420, 1450)))


def build_buzdolabi():
    rng = np.random.default_rng(3)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.80, 0.88, 0.95), (0.58, 0.70, 0.82))
    for x in range(X0, X0 + BW, 90):
        far.line((x, -200), (x, 950), (0.78, 0.86, 0.94), 10)
    far.cel([(X0, -300), (X0 + BW, -300), (X0 + BW, -250), (X0, -250)], (0.85, 0.95, 1.0), w=6, rim=0.6)
    for x, y, w, h, c in [(-900, -250, 500, 420, (0.98, 0.98, 0.95)), (-300, -150, 300, 320, (0.95, 0.40, 0.35)), (1300, -260, 600, 300, (0.60, 0.80, 0.50))]:
        far.cel([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], c, w=6, shadow=0.25, rim=0.4)
    far.blur(10)
    mid = Layer('mid')
    # cam raf
    mid.grad_rect(X0, GROUND, X0 + BW, 2300, (0.66, 0.80, 0.86), (0.50, 0.66, 0.76))
    mid.cel([(X0, GROUND - 20), (X0 + BW, GROUND - 20), (X0 + BW, GROUND + 8), (X0, GROUND + 8)], (0.88, 0.97, 1.0), w=6, rim=0.6)
    for k in range(6):
        mid.line((X0 + k * 700, GROUND + 40), (X0 + k * 700 - 300, 2300), (0.90, 0.98, 1.0), 14)
    # süt kutusu (marka yok)
    mid.cel([(-700, 100), (-150, 100), (-150, 1030), (-700, 1030)], (0.97, 0.97, 0.98), w=10, shadow=0.3, rim=0.3)
    mid.cel([(-700, 100), (-425, -140), (-150, 100)], (0.90, 0.90, 0.95), w=10, shadow=0.2)
    mid.cel(E(-425, 560, 160, 120), (0.40, 0.60, 0.90), w=8, shadow=0.2)
    # peynir dilimi
    mid.cel([(950, 1030), (1650, 1030), (1650, 650), (950, 920)], (1.0, 0.82, 0.30), w=10, shadow=0.3, rim=0.35)
    for x, y, r in [(1200, 940, 40), (1420, 820, 55), (1550, 960, 30), (1350, 990, 25)]:
        mid.cel(E(x, y, r, r * 0.8), (0.88, 0.66, 0.18), w=5, shadow=0.4, rim=0)
    # yumurta
    for x in (250, 520):
        mid.cel(E(x, 800, 140, 190), (0.98, 0.92, 0.80), w=10, shadow=0.3, rim=0.4)
    # buz kristalleri
    for _ in range(10):
        x, y = rng.uniform(-500, 1600), rng.uniform(1080, 1700)
        mid.cel([(x, y - 22), (x + 10, y), (x, y + 22), (x - 10, y)], (0.92, 0.98, 1.0), w=3, shadow=0, rim=0.6, oc=(0.6, 0.75, 0.9))
    fg = Layer('fg')
    fg.cel(E(-200, 2100, 420, 300), (0.30, 0.62, 0.30), w=12, shadow=0.3)
    fg.blur(22)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((550, -900), (0.85, 0.93, 1.0), 0.10, (0.88, 0.95, 1.02), frost=True))


def build_baharat():
    rng = np.random.default_rng(5)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.55, 0.36, 0.24), (0.36, 0.22, 0.14))
    for y in (-300, 300):
        far.cel([(X0, y), (X0 + BW, y), (X0 + BW, y + 40), (X0, y + 40)], (0.62, 0.40, 0.22), w=6)
        for k in range(14):
            x = X0 + 80 + k * 250
            c = [(0.85, 0.30, 0.20), (0.95, 0.75, 0.25), (0.45, 0.60, 0.30), (0.60, 0.35, 0.20)][k % 4]
            far.cel(capsule(x + 60, y - 200, x + 60, y - 30, 60, n=8), c, w=6, shadow=0.3, rim=0.3)
    far.blur(9)
    mid = Layer('mid')
    counter(mid, GROUND, 2300, (0.66, 0.44, 0.26), plank=400)
    for x, c, pw in [(-700, (0.85, 0.22, 0.14), (0.75, 0.18, 0.10)), (1250, (0.95, 0.72, 0.18), (0.88, 0.62, 0.12))]:
        jar(mid, x, 1040, 440, 760, (0.80, 0.86, 0.85), (0.25, 0.20, 0.18), content=c)
        for _ in range(16):
            px, py = x + rng.uniform(-300, 300), rng.uniform(1060, 1300)
            mid.cel(E(px, py, rng.uniform(8, 20), 6), pw, outline=False, shadow=0, rim=0)
    # tarçın kütükleri
    for k in range(3):
        y = 980 - k * 70
        mid.cel(capsule(250 + k * 20, y, 760 - k * 20, y - 10, 34, n=8), (0.62, 0.34, 0.18), w=7, shadow=0.3, rim=0.3)
    # yıldız anason
    cx, cy = 1000, 1150
    pts = []
    for k in range(16):
        a = k * math.pi / 8
        r = 90 if k % 2 == 0 else 35
        pts.append((cx + r * math.cos(a), cy + 0.6 * r * math.sin(a)))
    mid.cel(pts, (0.45, 0.25, 0.14), w=6, shadow=0.3, rim=0.3)
    fg = Layer('fg')
    fg.cel(E(1500, 2200, 520, 330), (0.80, 0.25, 0.15), w=12, shadow=0.3)
    fg.blur(22)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((1300, -500), (1.0, 0.75, 0.45), 0.24, (1.06, 0.98, 0.88), spice=(0.85, 0.35, 0.15)))


def build_zemin():
    rng = np.random.default_rng(6)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.86, 0.80, 0.70), (0.70, 0.60, 0.48))
    # dolap altları
    far.cel([(X0, -700), (X0 + BW, -700), (X0 + BW, 820), (X0, 820)], (0.40, 0.55, 0.50), w=8, shadow=0.2)
    for x in range(X0, X0 + BW, 700):
        far.cel([(x + 30, -650), (x + 670, -650), (x + 670, 700), (x + 30, 700)], (0.46, 0.62, 0.56), w=6, shadow=0.25, rim=0.25)
    far.cel([(X0, 820), (X0 + BW, 820), (X0 + BW, 960), (X0, 960)], (0.20, 0.18, 0.18), w=0, outline=False)
    # uzakta uyuyan kedi Paşa (dev, bulanık)
    far.cel(E(1900, 760, 700, 300), (0.92, 0.58, 0.22), w=10, shadow=0.3)
    far.cel(E(1350, 760, 230, 210), (0.92, 0.58, 0.22), w=10, shadow=0.3)
    far.cel([(1200, 600), (1250, 470), (1320, 590)], (0.92, 0.58, 0.22), w=8)
    far.cel([(1380, 580), (1450, 460), (1490, 600)], (0.92, 0.58, 0.22), w=8)
    far.blur(10)
    mid = Layer('mid')
    # büyük karo zemin
    mid.grad_rect(X0, GROUND - 40, X0 + BW, 2300, (0.90, 0.86, 0.78), (0.80, 0.74, 0.64))
    for i, y in enumerate(range(GROUND - 40, 2300, 330)):
        for j, x in enumerate(range(X0, X0 + BW, 420)):
            if (i + j) % 2:
                mid.cel([(x, y), (x + 420, y), (x + 420, y + 330), (x, y + 330)], (0.70, 0.62, 0.52), w=0, outline=False, shadow=0, rim=0)
    # mama kabı
    mid.cel(E(-350, 1000, 620, 140), (0.75, 0.78, 0.82), w=10, shadow=0.35, rim=0.5)
    mid.cel([(-970, 1000), (270, 1000), (150, 620), (-850, 620)], (0.70, 0.74, 0.78), w=10, shadow=0.35, rim=0.5)
    mid.cel(E(-350, 620, 500, 90), (0.55, 0.40, 0.25), w=8, shadow=0.2)
    for _ in range(14):
        x, y = rng.uniform(-760, 60), rng.uniform(560, 640)
        mid.cel(E(x, y, 46, 30), (0.62, 0.40, 0.22), w=5, shadow=0.35, rim=0.3)
    for _ in range(5):
        x, y = rng.uniform(-200, 900), rng.uniform(1080, 1500)
        mid.cel(E(x, y, 42, 28), (0.62, 0.40, 0.22), w=5, shadow=0.35, rim=0.3)
    # karınca yolu
    for k in range(12):
        x, y = 900 + k * 110, 1120 + 25 * math.sin(k)
        mid.cel(E(x, y, 26, 14), (0.18, 0.10, 0.08), w=3, shadow=0.1, rim=0.3)
        mid.cel(E(x + 28, y - 2, 14, 12), (0.18, 0.10, 0.08), w=3, shadow=0.1, rim=0.3)
    fg = Layer('fg')
    fg.cel(E(1700, 2250, 520, 280), (0.62, 0.40, 0.22), w=12, shadow=0.3)
    fg.blur(22)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((-300, -700), (1.0, 0.88, 0.68), 0.16, (1.02, 1.0, 0.95)))


def build_cekmece():
    rng = np.random.default_rng(7)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.30, 0.22, 0.16), (0.18, 0.12, 0.08))
    far.grad_rect(X0, -700, X0 + BW, -380, (1.0, 0.92, 0.75), (0.75, 0.60, 0.42))
    for x in range(X0, X0 + BW, 260):
        far.line((x, -380), (x, 1000), (0.24, 0.16, 0.10), 6)
    far.blur(8)
    mid = Layer('mid')
    counter(mid, GROUND, 2300, (0.52, 0.34, 0.20), plank=300)
    # bölmeler
    for x in (-650, 1350):
        mid.cel([(x, 200), (x + 70, 200), (x + 70, 1040), (x, 1040)], (0.62, 0.42, 0.24), w=8, shadow=0.3, rim=0.3)
    # dev çatal (yatık) ve kaşık
    mid.cel([(-600, 900), (300, 830), (310, 870), (-590, 940)], (0.78, 0.80, 0.85), w=8, shadow=0.3, rim=0.55)
    for k in range(4):
        y = 780 + k * 40
        mid.cel([(300, 830 + k * 12), (720, y), (722, y + 20), (305, 846 + k * 12)], (0.80, 0.82, 0.86), w=6, shadow=0.25, rim=0.5)
    mid.cel(E(1000, 1000, 260, 90, ang=-0.05), (0.80, 0.82, 0.86), w=8, shadow=0.35, rim=0.55)
    mid.cel([(1240, 990), (1900, 940), (1905, 970), (1245, 1015)], (0.78, 0.80, 0.85), w=7, shadow=0.3, rim=0.5)
    # lastik ve ip yumağı
    mid.cel(E(-200, 1300, 150, 60), (0.85, 0.30, 0.25), w=8, shadow=0.3)
    mid.cel(E(-200, 1300, 90, 32), (0.40, 0.28, 0.18), w=6, shadow=0)
    mid.cel(E(1250, 1350, 130, 110), (0.92, 0.85, 0.65), w=8, shadow=0.35, rim=0.3)
    for k in range(5):
        mid.line((1150, 1290 + k * 25), (1350, 1330 + k * 18), (0.75, 0.65, 0.45), 4)
    fg = Layer('fg')
    fg.cel([(-800, 1800), (2300, 1750), (2300, 2600), (-800, 2600)], (0.62, 0.42, 0.24), w=12, shadow=0.2)
    fg.blur(18)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((550, -1000), (1.0, 0.85, 0.55), 0.28, (1.05, 0.98, 0.86)))


def build_lonca():
    rng = np.random.default_rng(8)
    far = Layer('far')
    far.grad_rect(X0, Y0, X0 + BW, Y0 + BH, (0.70, 0.56, 0.40), (0.45, 0.32, 0.22))
    for x in range(X0, X0 + BW, 600):
        far.cel([(x, Y0), (x + 70, Y0), (x + 70, 1010), (x, 1010)], (0.42, 0.28, 0.16), w=6, shadow=0.25, rim=0.2)
    # Büyük Harita
    far.cel([(-500, 0), (1600, 0), (1650, 950), (-540, 930)], (0.94, 0.86, 0.66), w=10, shadow=0.25, rim=0.3)
    for k in range(9):
        x0 = -400 + (k % 3) * 650 + rng.uniform(-40, 40)
        y0 = 60 + (k // 3) * 290 + rng.uniform(-30, 30)
        far.cel([(x0, y0), (x0 + 520, y0 + 10), (x0 + 510, y0 + 220), (x0 - 10, y0 + 210)],
                [(0.75, 0.82, 0.60), (0.85, 0.70, 0.55), (0.62, 0.75, 0.82)][k % 3] if k < 5 else (0.94, 0.86, 0.66), w=5, shadow=0.1, rim=0)
    far.cel(E(1450, 820, 60, 60), (0.80, 0.20, 0.18), w=6)
    # düğme kapı
    far.cel(E(-850, 600, 220, 220), (0.30, 0.45, 0.65), w=8, shadow=0.3, rim=0.3)
    for dx, dy in ((-60, -60), (60, -60), (-60, 60), (60, 60)):
        far.cel(E(-850 + dx, 600 + dy, 30, 30), (0.18, 0.28, 0.42), w=5, shadow=0)
    far.blur(7)
    mid = Layer('mid')
    counter(mid, GROUND, 2300, (0.58, 0.38, 0.22), plank=140)
    # makara masa
    mid.cel([(-420, 600), (120, 600), (60, 1030), (-360, 1030)], (0.85, 0.75, 0.55), w=10, shadow=0.3, rim=0.3)
    mid.cel(E(-150, 600, 300, 70), (0.70, 0.50, 0.30), w=10, shadow=0.2)
    mid.cel(E(-150, 1030, 240, 50), (0.70, 0.50, 0.30), w=10, shadow=0.2)
    for k in range(6):
        mid.line((-380, 680 + k * 55), (90, 680 + k * 55), (0.75, 0.25, 0.25), 18)
    # şişe kapağı lamba
    mid.cel([(1250, 300), (1290, 300), (1290, 1030), (1250, 1030)], (0.45, 0.45, 0.48), w=6)
    mid.cel(E(1270, 260, 150, 60), (0.85, 0.75, 0.30), w=8, shadow=0.2)
    mid.cel(E(1270, 300, 70, 50), (1.0, 0.95, 0.70), w=4, shadow=0, rim=0)
    # ataç merdiven
    pts = [(1650, 1040), (1650, 0), (1820, 0), (1820, 1040)]
    for a, b in zip(pts, pts[1:]):
        mid.line(a, b, (0.70, 0.72, 0.76), 26)
    for y in range(80, 1040, 140):
        mid.line((1650, y), (1820, y), (0.70, 0.72, 0.76), 18)
    fg = Layer('fg')
    fg.cel(E(-300, 2200, 500, 320), (0.92, 0.86, 0.66), w=12, shadow=0.25)
    fg.blur(20)
    return dict(far=far.img, mid=mid.img, fg=fg.img,
                light=_fx_light((1270, 300), (1.0, 0.82, 0.50), 0.06, (1.06, 0.98, 0.86), lamp=(1270, 300)))


BUILDERS = {'tezgah': build_tezgah, 'lavabo': build_lavabo, 'buzdolabi': build_buzdolabi, 'baharat': build_baharat,
            'zemin': build_zemin, 'cekmece': build_cekmece, 'lonca': build_lonca}



@lru_cache(8)
def build(loc):
    fn = BUILDERS.get(loc) or BUILDERS['tezgah']
    return fn()


def _warp(img, sc, cam, k, W, H, flags=cv2.INTER_LINEAR):
    z = cam.z ** (0.4 + 0.6 * k) if k < 1 else cam.z * (1 + (k - 1) * 0.15)
    cx = REF[0] + (cam.cx - REF[0]) * k
    cy = REF[1] + (cam.cy - REF[1]) * k
    a = z / sc
    M = np.array([[a, 0, -(X0 * sc) * a / sc * 0 + (X0 - cx) * z + W / 2 + cam.sx * k],
                  [0, a, (Y0 - cy) * z + H / 2 + cam.sy * k]], np.float32)
    return cv2.warpAffine(img, M, (W, H), flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _over(f, rgba):
    a = rgba[..., 3:4].astype(np.float32) / 255
    f *= (1 - a)
    f += rgba[..., :3].astype(np.float32) / 255 * a
    return f


def draw(loc, cam):
    L = build(loc)
    W, H = cam.W, cam.H
    f = np.zeros((H, W, 3), np.float32)
    f[:] = (0.80, 0.66, 0.48)
    f = _over(f, _warp(L['far'], LAYER_SC['far'], cam, LAYER_K['far'], W, H))
    f = _over(f, _warp(L['mid'], LAYER_SC['mid'], cam, LAYER_K['mid'], W, H))
    return f


def draw_fg(loc, cam, f):
    L = build(loc)
    return _over(f, _warp(L['fg'], LAYER_SC['fg'], cam, LAYER_K['fg'], cam.W, cam.H))


@lru_cache(4)
def _grid(W, H):
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    return X, Y


def post(loc, f, cam, t):
    """Sinematik ışık: ışık hüzmeleri, toz, parlama (bloom), renk ve vinyet."""
    L = build(loc)['light']
    W, H = cam.W, cam.H
    X, Y = _grid(W, H)
    sx, sy = cam.p(*L['src'])
    if L.get('shafts'):
        ang = math.atan2(H - sy, W * 0.3 - sx)
        dx, dy = math.cos(ang), math.sin(ang)
        px, py = X - sx, Y - sy
        across = -px * dy + py * dx
        along = px * dx + py * dy
        band = (0.5 + 0.5 * np.sin(across / (90 * cam.z) + 1.3)) ** 6 + 0.6 * (0.5 + 0.5 * np.sin(across / (37 * cam.z))) ** 10
        fade = np.clip(1 - along / (H * 1.2), 0, 1) * (along > 0)
        sh = cv2.GaussianBlur((band * fade).astype(np.float32), (0, 0), 6)
        f += sh[..., None] * L['shafts'] * np.array(L['col'], np.float32)
    if L.get('dust'):
        rng = np.random.default_rng(11)
        n = 70
        bx, by = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
        sp = rng.uniform(0.2, 1, n)
        for i in range(n):
            x = ((bx[i] + 0.012 * math.sin(t * sp[i] + i)) % 1) * W
            y = ((by[i] - t * 0.008 * sp[i]) % 1) * H * 0.85
            r = 1.5 + 3 * sp[i]
            a = 0.35 + 0.4 * (0.5 + 0.5 * math.sin(t * 2 * sp[i] + i))
            cv2.circle(f, (int(x * 4), int(y * 4)), int(r * 4), tuple(float(c) * a + 0.2 for c in L['col']), -1, cv2.LINE_AA, shift=2)
    if L.get('drip'):
        dx, y0, y1 = L['drip']
        u = (t % 1.6) / 1.6
        yy = y0 + (y1 - y0) * u * u
        p = cam.p(dx, yy)
        cv2.ellipse(f, (int(p[0] * 4), int(p[1] * 4)), (int(22 * cam.z * 4), int(30 * cam.z * 4)), 0, 0, 360, (0.70, 0.88, 1.0), -1, cv2.LINE_AA, 2)
        if u > 0.92:
            q = cam.p(dx, y1)
            cv2.ellipse(f, (int(q[0] * 4), int(q[1] * 4)), (int(90 * cam.z * 4), int(20 * cam.z * 4)), 0, 0, 360, (0.85, 0.95, 1.0), 3, cv2.LINE_AA, 2)
    if L.get('lamp'):
        p = cam.p(*L['lamp'])
        g = np.exp(-(((X - p[0]) ** 2 + (Y - p[1]) ** 2) / (2 * (420 * cam.z) ** 2)))
        f += g[..., None] * np.array([0.16, 0.11, 0.04], np.float32) * (0.9 + 0.1 * math.sin(t * 7))
    br = np.clip(f - 0.80, 0, None)
    small = cv2.resize(br, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    f += cv2.resize(cv2.GaussianBlur(small, (0, 0), 8), (W, H)) * 0.9
    # odak dışı ışık lekeleri (bokeh)
    sw, shh = W // 4, H // 4
    bk = np.zeros((shh, sw, 3), np.float32)
    rng2 = np.random.default_rng(21)
    for i in range(9):
        bx = (rng2.uniform(0, 1) + 0.01 * t * rng2.uniform(-1, 1)) % 1 * sw
        by = rng2.uniform(0.05, 0.6) * shh + 6 * math.sin(t * 0.5 + i)
        r = rng2.uniform(8, 22)
        cv2.circle(bk, (int(bx), int(by)), int(r), tuple(float(c) * 0.10 for c in L['col']), -1, cv2.LINE_AA)
    bk = cv2.GaussianBlur(bk, (0, 0), 2.5)
    f += cv2.resize(bk, (W, H))
    f *= np.array(L['warm'], np.float32)
    # sinematik renk: yumuşak S-eğrisi kontrast + hafif doygunluk
    f = np.clip(f, 0, 1)
    f = f * 0.62 + (f * f * (3 - 2 * f)) * 0.38
    lum = (f * np.array([0.3, 0.59, 0.11], np.float32)).sum(2, keepdims=True)
    f = lum + (f - lum) * 1.12
    d = ((X - W * 0.55) / (W * 0.8)) ** 2 + ((Y - H * 0.45) / (H * 0.75)) ** 2
    f *= np.clip(1.12 - 0.42 * d, 0.5, 1.05)[..., None]
    return f
