"""Mekân arka planları. Dünya alanı: x -1300..2400, y -400..2300. Zemin (rıhtım kenarı) y=1000, karakterler y=1250'de durur."""
import math
from functools import lru_cache
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from .. import paths

X0, Y0, BW, BH = -1300, -400, 3700, 2700
GROUND = 1000
OUTI = (22, 24, 34)
LOCATIONS = ['rihtim', 'saha', 'gumruk', 'kantar', 'depo', 'ofis', 'gece']


def P(x, y):
    return (int(x - X0), int(y - Y0))


def _poly(img, pts, col, w=5):
    a = np.array([P(x, y) for x, y in pts], np.int32)
    cv2.fillPoly(img, [a], col, cv2.LINE_AA)
    if w:
        cv2.polylines(img, [a], True, OUTI, w, cv2.LINE_AA)


def _rect(img, x0, y0, x1, y1, col, w=5):
    _poly(img, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], col, w)


def _vgrad(img, y0, y1, c0, c1):
    a, b = P(0, y0)[1], P(0, y1)[1]
    a, b = max(0, a), min(BH, b)
    for yy in range(a, b):
        u = (yy - P(0, y0)[1]) / max(1, (P(0, y1)[1] - P(0, y0)[1]))
        img[yy] = (np.array(c0) * (1 - u) + np.array(c1) * u).astype(np.uint8)


def _text(img, txt, x, y, size, col, stroke=0):
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    fnt = ImageFont.truetype(paths.FONT, size)
    try:
        fnt.set_variation_by_axes([800])
    except Exception:
        pass
    d.text(P(x, y), txt, font=fnt, fill=col, anchor='mm', stroke_width=stroke, stroke_fill=OUTI)
    img[:] = np.asarray(im)


CCOLS = [(230, 120, 40), (60, 160, 90), (200, 60, 60), (60, 120, 200), (230, 200, 60), (120, 80, 170)]


def _container(img, x0, y0, w, h, col):
    _rect(img, x0, y0, x0 + w, y0 + h, col, 4)
    dark = tuple(int(c * 0.75) for c in col)
    n = max(4, int(w / 26))
    for k in range(1, n):
        xx = x0 + k * w / n
        cv2.line(img, P(xx, y0 + 7), P(xx, y0 + h - 7), dark, 3, cv2.LINE_AA)
    cv2.rectangle(img, P(x0, y0), P(x0 + w, y0 + 8), tuple(int(c * 0.85) for c in col), -1)


def _stack(img, x0, base, cols, rows, rng, w=250, h=88):
    for c in range(cols):
        for r in range(rows - (c % 2 if rows > 1 else 0)):
            _container(img, x0 + c * (w + 6), base - (r + 1) * h, w, h, CCOLS[int(rng.integers(0, len(CCOLS)))])


def _sky(img, top=(70, 150, 235), bot=(190, 228, 252), clouds=True, rng=None):
    _vgrad(img, Y0, 830, top, bot)
    if clouds:
        for k in range(12):
            cx, cy = rng.uniform(X0, X0 + BW), rng.uniform(-300, 500)
            for j in range(5):
                cv2.circle(img, P(cx + j * 60 - 120, cy + (j % 2) * -28), int(rng.uniform(45, 80)), (250, 252, 255), -1, cv2.LINE_AA)


def _quay(img, rng, c0=(178, 178, 172), c1=(118, 120, 124)):
    _vgrad(img, GROUND, Y0 + BH, c0, c1)
    cv2.line(img, P(X0, GROUND), P(X0 + BW, GROUND), OUTI, 6, cv2.LINE_AA)
    for k in range(-6, 10):
        cv2.line(img, P(k * 280, 1420), P(k * 280 + 130, 1420), (240, 200, 40), 16, cv2.LINE_AA)
    for k in range(260):  # asfalt dokusu
        x, y = rng.uniform(X0, X0 + BW), rng.uniform(GROUND + 20, Y0 + BH)
        cv2.circle(img, P(x, y), int(rng.uniform(1, 3)), (150, 150, 148), -1)


def _sea(img, rng, top=(40, 120, 190), line=(120, 190, 235), night=False):
    _rect(img, X0, 830, X0 + BW, GROUND, top, 0)
    for k in range(90):
        x, y = rng.uniform(X0, X0 + BW), rng.uniform(840, 990)
        cv2.line(img, P(x, y), P(x + 45, y), line, 3, cv2.LINE_AA)


def _skyline(img, col, rng, base=830):
    x = X0
    while x < X0 + BW:
        w = rng.uniform(40, 110); h = rng.uniform(30, 140)
        cv2.rectangle(img, P(x, base - h), P(x + w, base), col, -1)
        if rng.random() < 0.2:
            cv2.rectangle(img, P(x + w * 0.4, base - h - 60), P(x + w * 0.5, base - h), col, -1)
        x += w + rng.uniform(0, 20)


def _crane_bg(img, x, col=(245, 190, 30)):
    for lx in (x, x + 240):
        _rect(img, lx, 260, lx + 40, GROUND, col)
    _rect(img, x - 280, 220, x + 560, 280, col)
    for k in range(-6, 12):
        cv2.line(img, P(x - 280 + k * 60 + 280, 228), P(x - 250 + k * 60 + 280, 272), tuple(int(c * 0.75) for c in col), 3, cv2.LINE_AA)
    _rect(img, x + 60, 280, x + 200, 380, (250, 210, 60))


@lru_cache(8)
def build(loc):
    rng = np.random.default_rng(LOCATIONS.index(loc) + 3 if loc in LOCATIONS else 1)
    img = np.zeros((BH, BW, 3), np.uint8)
    if loc == 'rihtim':
        _sky(img, rng=rng)
        _skyline(img, (150, 175, 200), rng)
        _sea(img, rng)
        for sx in (-1100, 1700):  # uzak gemi siluetleri
            _poly(img, [(sx, 800), (sx + 500, 800), (sx + 460, 840), (sx + 30, 840)], (90, 110, 140), 0)
        _crane_bg(img, 1650)
        _quay(img, rng)
        _stack(img, -1250, GROUND, 2, 3, rng)
        _stack(img, 1350, GROUND, 3, 2, rng)
    elif loc == 'saha':
        _sky(img, rng=rng)
        _quay(img, rng, (186, 182, 170), (128, 126, 120))
        for i, x0 in enumerate([-1250, -650, -50, 550, 1150, 1750]):
            _stack(img, x0, GROUND, 2, 4 if i % 2 == 0 else 3, rng)
        for lx in (-300, 900, 2000):  # aydınlatma direkleri
            _rect(img, lx, 80, lx + 22, GROUND, (120, 125, 130), 4)
            _rect(img, lx - 60, 60, lx + 82, 100, (90, 95, 100), 4)
    elif loc == 'gumruk':
        _sky(img, rng=rng)
        _quay(img, rng, (176, 176, 170), (116, 118, 122))
        _rect(img, -700, 450, 900, GROUND, (220, 214, 200))
        _rect(img, -750, 400, 950, 470, (60, 90, 140))
        _text(img, 'GÜMRÜK', 100, 435, 70, (255, 255, 255))
        for wx in range(-620, 850, 210):
            _rect(img, wx, 560, wx + 150, 720, (150, 200, 230), 4)
            cv2.line(img, P(wx + 30, 580), P(wx + 70, 700), (220, 240, 255), 6, cv2.LINE_AA)
        _rect(img, 1150, 640, 1420, GROUND, (230, 225, 210))
        _rect(img, 1180, 680, 1390, 800, (150, 200, 230), 4)
        _rect(img, 1100, 600, 1470, 650, (200, 60, 60))
        # bariyer
        _rect(img, 1430, 820, 1470, GROUND, (90, 90, 95), 4)
        for k in range(8):
            col = (220, 40, 40) if k % 2 == 0 else (250, 250, 250)
            _rect(img, 1470 + k * 90, 830, 1560 + k * 90, 860, col, 3)
        # kuyrukta bekleyen tır siluetleri
        for k in range(4):
            tx = 1900 + k * 160
            _rect(img, tx, 760 - k * 10, tx + 140, 900 - k * 10, (120, 130, 150), 0)
    elif loc == 'kantar':
        _sky(img, rng=rng)
        _quay(img, rng)
        _poly(img, [(-200, 1180), (1300, 1180), (1380, 1330), (-280, 1330)], (140, 145, 150), 6)
        for k in range(12):
            cv2.line(img, P(-150 + k * 125, 1190), P(-190 + k * 125, 1320), (115, 120, 125), 3, cv2.LINE_AA)
        _rect(img, 1500, 520, 1900, GROUND, (230, 225, 210))
        _rect(img, 1560, 600, 1840, 720, (150, 200, 230), 4)
        _rect(img, 1450, 300, 1950, 470, (30, 30, 34))
        _text(img, 'KANTAR', 1700, 340, 46, (250, 250, 250))
        _text(img, '42.780 KG', 1700, 420, 72, (255, 70, 60))
        _stack(img, -1250, GROUND, 2, 2, rng)
    elif loc == 'depo':
        _vgrad(img, Y0, GROUND, (120, 128, 140), (165, 170, 178))
        for k in range(-30, 80):  # oluklu duvar
            x = k * 50
            cv2.line(img, P(x, Y0), P(x, GROUND), (135, 142, 152), 4)
        for lx in range(-1100, 2300, 450):  # tavan lambaları
            _rect(img, lx, -150, lx + 160, -120, (60, 60, 65), 3)
            cv2.circle(img, P(lx + 80, -110), 24, (255, 245, 200), -1, cv2.LINE_AA)
        for sx in (-1200, -500, 1300, 2000):  # raflar
            for r in range(4):
                yy = GROUND - r * 170
                _rect(img, sx, yy - 12, sx + 560, yy, (230, 130, 40), 3)
                for b in range(4):
                    bx = sx + 20 + b * 130
                    _rect(img, bx, yy - 12 - 120, bx + 110, yy - 12, (200, 160, 110), 3)
                    cv2.line(img, P(bx + 20, yy - 90), P(bx + 90, yy - 90), (150, 110, 70), 4)
            for px in (sx, sx + 550):
                _rect(img, px, GROUND - 700, px + 12, GROUND, (60, 90, 160), 3)
        _vgrad(img, GROUND, Y0 + BH, (170, 168, 160), (120, 118, 112))
        cv2.line(img, P(X0, GROUND), P(X0 + BW, GROUND), OUTI, 6, cv2.LINE_AA)
        for k in range(-6, 10):
            cv2.line(img, P(k * 280, 1420), P(k * 280 + 130, 1420), (240, 200, 40), 16, cv2.LINE_AA)
    elif loc == 'ofis':
        _vgrad(img, Y0, GROUND, (215, 205, 185), (235, 228, 210))
        _rect(img, -900, 200, 300, 760, (120, 170, 220), 8)  # pencere
        _vgrad_win = img[P(0, 210)[1]:P(0, 750)[1], P(-890, 0)[0]:P(290, 0)[0]]
        _vgrad_win[:] = np.linspace([110, 170, 230], [190, 225, 250], _vgrad_win.shape[0])[:, None, :].astype(np.uint8)
        _rect(img, -890, 620, 290, 750, (40, 110, 180), 0)
        for k in range(5):
            _rect(img, -850 + k * 220, 560, -650 + k * 220, 620, CCOLS[k], 3)
        cv2.line(img, P(-300, 200), P(-300, 760), OUTI, 8)
        _rect(img, 700, 180, 1400, 600, (250, 250, 248), 6)  # beyaz tahta
        _text(img, 'ETA: ???', 1050, 280, 70, (40, 60, 160))
        _text(img, 'CUT-OFF: DÜN', 1050, 380, 56, (200, 40, 40))
        _text(img, 'YÜK NEREDE?!', 1050, 480, 56, (30, 30, 30))
        cv2.circle(img, P(1700, 300), 90, (250, 250, 250), -1, cv2.LINE_AA)  # saat
        cv2.circle(img, P(1700, 300), 90, OUTI, 8, cv2.LINE_AA)
        cv2.line(img, P(1700, 300), P(1700, 240), OUTI, 8)
        cv2.line(img, P(1700, 300), P(1745, 320), OUTI, 8)
        _vgrad(img, GROUND, Y0 + BH, (150, 110, 80), (110, 80, 58))
        cv2.line(img, P(X0, GROUND), P(X0 + BW, GROUND), OUTI, 6, cv2.LINE_AA)
        for k in range(-20, 40):  # parke
            cv2.line(img, P(k * 120, GROUND), P(k * 120 - 300, Y0 + BH), (125, 90, 64), 3)
    elif loc == 'gece':
        _vgrad(img, Y0, 830, (10, 14, 40), (40, 50, 90))
        for k in range(220):
            cv2.circle(img, P(rng.uniform(X0, X0 + BW), rng.uniform(Y0, 760)), int(rng.uniform(1, 3)), (240, 240, 255), -1)
        cv2.circle(img, P(1900, 50), 70, (245, 240, 210), -1, cv2.LINE_AA)
        _skyline(img, (25, 30, 55), rng)
        for k in range(80):
            x = rng.uniform(X0, X0 + BW)
            cv2.circle(img, P(x, 830 - rng.uniform(5, 100)), 3, (255, 210, 120), -1)
        _sea(img, rng, (15, 30, 60), (60, 90, 140), night=True)
        _quay(img, rng, (90, 92, 100), (50, 52, 60))
        _stack(img, -1250, GROUND, 2, 3, rng)
        for lx in (-200, 1500):
            _rect(img, lx, 100, lx + 26, GROUND, (60, 60, 70), 4)
            _rect(img, lx - 70, 70, lx + 96, 110, (40, 40, 50), 4)
            cone = np.array([P(lx - 60, 110), P(lx + 86, 110), P(lx + 500, GROUND + 300), P(lx - 474, GROUND + 300)], np.int32)
            ov = img.copy()
            cv2.fillPoly(ov, [cone], (255, 240, 180), cv2.LINE_AA)
            img[:] = (img * 0.82 + ov * 0.18).astype(np.uint8)
    else:
        return build('rihtim')
    return img


def draw(loc, cam):
    img = build(loc)
    M = np.float32([[cam.z, 0, cam.W / 2 + cam.sx - (cam.cx - X0) * cam.z], [0, cam.z, cam.H / 2 + cam.sy - (cam.cy - Y0) * cam.z]])
    out = cv2.warpAffine(img, M, (cam.W, cam.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out.astype(np.float32) * (1 / 255.0)
