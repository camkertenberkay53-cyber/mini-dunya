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
ALIAS = {}
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


BUILDERS = {'tezgah': build_tezgah}


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
    br = np.clip(f - 0.80, 0, None)
    small = cv2.resize(br, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    f += cv2.resize(cv2.GaussianBlur(small, (0, 0), 8), (W, H)) * 0.9
    f *= np.array(L['warm'], np.float32)
    d = ((X - W * 0.55) / (W * 0.8)) ** 2 + ((Y - H * 0.45) / (H * 0.75)) ** 2
    f *= np.clip(1.12 - 0.42 * d, 0.5, 1.05)[..., None]
    return f
