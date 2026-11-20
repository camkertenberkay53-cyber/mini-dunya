"""Çizim yardımcıları: kamera, kenar çizgili şekiller, gölgeli dolgular, yüz parçaları."""
import math
import numpy as np
import cv2

OUT = (0.086, 0.094, 0.133)  # kontur rengi (RGB 0..1)
S = 4                        # alt-piksel çarpanı (cv2 shift=2)


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def seg(t, a, b):
    if b <= a:
        return 1.0 if t >= b else 0.0
    return min(1.0, max(0.0, (t - a) / (b - a)))


def lerp(a, b, u):
    return a + (b - a) * u


def shade(c, k):
    return tuple(min(1.0, max(0.0, v * k)) for v in c)


def mix(c1, c2, u):
    return tuple(a + (b - a) * u for a, b in zip(c1, c2))


class Cam:
    """Dünya koordinatından ekran koordinatına."""

    def __init__(self, W, H, cx, cy, z, sx=0.0, sy=0.0):
        self.W, self.H, self.cx, self.cy, self.z, self.sx, self.sy = W, H, cx, cy, z, sx, sy

    def p(self, x, y):
        return ((x - self.cx) * self.z + self.W / 2 + self.sx, (y - self.cy) * self.z + self.H / 2 + self.sy)

    def P(self, pts):
        return np.array([self.p(x, y) for x, y in pts], np.float32)

    def lw(self, w):  # ölçekli çizgi kalınlığı (cv2 piksel)
        return max(2, int(round(w * self.z)))


def ip(pts):
    return np.round(np.asarray(pts) * S).astype(np.int32)


def fill(f, pts, color, outline=True, w=6):
    cv2.fillPoly(f, [ip(pts)], color, cv2.LINE_AA, shift=2)
    if outline:
        cv2.polylines(f, [ip(pts)], True, OUT, max(2, w), cv2.LINE_AA, shift=2)


def poly_line(f, pts, color, w, closed=False):
    cv2.polylines(f, [ip(pts)], closed, color, max(2, w), cv2.LINE_AA, shift=2)


def line(f, a, b, color, w):
    cv2.line(f, tuple(ip(a)), tuple(ip(b)), color, max(2, int(w)), cv2.LINE_AA, shift=2)


def circle(f, c, r, color, outline=True, w=6):
    cv2.circle(f, tuple(ip(c)), max(1, int(r * S)), color, -1, cv2.LINE_AA, shift=2)
    if outline:
        cv2.circle(f, tuple(ip(c)), max(1, int(r * S)), OUT, max(2, w), cv2.LINE_AA, shift=2)


def ellipse(f, c, rx, ry, color, outline=True, w=6, ang=0, a0=0, a1=360):
    cv2.ellipse(f, tuple(ip(c)), (max(1, int(rx * S)), max(1, int(ry * S))), ang, a0, a1, color, -1, cv2.LINE_AA, shift=2)
    if outline:
        cv2.ellipse(f, tuple(ip(c)), (max(1, int(rx * S)), max(1, int(ry * S))), ang, a0, a1, OUT, max(2, w), cv2.LINE_AA, shift=2)


def rect_pts(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rrect(x0, y0, x1, y1, r, n=6):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = []
    for cx, cy, a0 in [(x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)]:
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def shaded_box(f, cam, x0, y0, x1, y1, color, r=0, w=6, light=True):
    """Gölge ve parlama ile dolu kutu (dünya koordinatı)."""
    pts = rrect(x0, y0, x1, y1, r) if r else rect_pts(x0, y0, x1, y1)
    cv2.fillPoly(f, [ip(cam.P(pts))], color, cv2.LINE_AA, shift=2)
    if light:
        h = y1 - y0
        sh = rrect(x0, y0 + h * 0.72, x1, y1, r) if r else rect_pts(x0, y0 + h * 0.72, x1, y1)
        cv2.fillPoly(f, [ip(cam.P(sh))], shade(color, 0.82), cv2.LINE_AA, shift=2)
        hl = rect_pts(x0 + (r or 6) + 4, y0 + 10, x1 - (r or 6) - 4, y0 + 10 + max(6, h * 0.05))
        cv2.fillPoly(f, [ip(cam.P(hl))], mix(color, (1, 1, 1), 0.35), cv2.LINE_AA, shift=2)
    cv2.polylines(f, [ip(cam.P(pts))], True, OUT, cam.lw(w), cv2.LINE_AA, shift=2)


def ground_shadow(f, cam, x, y, w):
    c = cam.p(x, y)
    ov = f.copy()
    ellipse(ov, c, w / 2 * cam.z, 20 * cam.z, (0.0, 0.0, 0.0), False)
    f[:] = f * 0.72 + ov * 0.28


# ---------------------------------------------------------------- yüz
EMO = {
    #            kaş   gözkapak  göz_büyüklüğü  ağız_kapalı
    'normal':   (0.0, 0.0, 1.00, 'flat'),
    'panik':    (1.1, 0.0, 1.12, 'frown'),
    'sinirli':  (-1.3, 0.15, 0.95, 'frown'),
    'bikkin':   (0.0, 0.55, 0.95, 'flat'),
    'neseli':   (0.35, 0.0, 1.0, 'smile'),
    'soguk':    (-0.35, 0.35, 0.95, 'flat'),
    'saskin':   (1.4, 0.0, 1.2, 'o'),
    'fisilti':  (0.4, 0.2, 1.0, 'smile'),
    'aglamakli': (1.2, 0.1, 1.05, 'frown'),
    'kibirli':  (-0.2, 0.45, 0.95, 'smile'),
}


def eyes(f, cam, cx, cy, r, look=(0, 0), blink=0.0, emotion='normal', gap=1.25, t=0.0, color_white=(1, 1, 1)):
    brow, lid, scale, _ = EMO.get(emotion, EMO['normal'])
    r = r * scale
    for side in (-1, 1):
        ex, ey = cx + side * r * gap, cy
        c = cam.p(ex, ey)
        rr = r * cam.z
        open_ = max(0.08, 1 - max(blink, lid))
        ellipse(f, c, rr, rr * open_, color_white, True, cam.lw(5))
        if open_ > 0.25:
            pr = 0.42 if emotion not in ('panik', 'saskin') else 0.3
            pc = (c[0] + look[0] * rr * 0.45, c[1] + look[1] * rr * 0.4 * open_ + (rr * (1 - open_) * 0.4))
            circle(f, pc, rr * pr, (0.1, 0.1, 0.14), False)
            circle(f, (pc[0] - rr * 0.13, pc[1] - rr * 0.15), rr * 0.12, (1, 1, 1), False)
        if lid > 0.05 and blink < 0.5:  # üst göz kapağı çizgisi
            yy = c[1] - rr * open_
            line(f, (c[0] - rr, yy), (c[0] + rr, yy), OUT, cam.lw(5))
        bx0, bx1 = ex - side * r * 0.95, ex + side * r * 0.95
        inner_y = ey - r * 1.3 - brow * r * 0.45
        outer_y = ey - r * 1.3 + brow * r * 0.25
        line(f, cam.p(bx0, inner_y), cam.p(bx1, outer_y), OUT, cam.lw(max(6, r * 0.3)))
    if emotion == 'panik':
        sx, sy = cx + r * gap + r * 1.4, cy - r * 0.6 + (t * 70 % 50)
        d = cam.P([(sx, sy - 20), (sx + 10, sy + 4), (sx, sy + 13), (sx - 10, sy + 4)])
        cv2.fillPoly(f, [ip(d)], (0.55, 0.8, 1.0), cv2.LINE_AA, shift=2)
    if emotion == 'aglamakli':
        for side in (-1, 1):
            tx = cx + side * r * gap
            ty = cy + r * 0.8 + (t * 90 % 70)
            d = cam.P([(tx, ty - 14), (tx + 8, ty + 4), (tx, ty + 11), (tx - 8, ty + 4)])
            cv2.fillPoly(f, [ip(d)], (0.55, 0.8, 1.0), cv2.LINE_AA, shift=2)


def mouth(f, cam, cx, cy, w, open_, shape=0.5, emotion='normal', inner=(0.43, 0.12, 0.16)):
    """open_: 0..1 genişlik/açıklık; shape: 0 = yuvarlak (o/u), 1 = yayvan (e/i)."""
    closed = EMO.get(emotion, EMO['normal'])[3]
    lw = cam.lw(6)
    if open_ < 0.08:
        if closed == 'smile':
            pts = [(cx - w / 2 + k * w / 12, cy - 6 + 14 * math.sin(k / 12 * math.pi)) for k in range(13)]
            poly_line(f, cam.P(pts), OUT, lw)
        elif closed == 'frown':
            pts = [(cx - w / 2 + k * w / 12, cy + 8 - 12 * math.sin(k / 12 * math.pi)) for k in range(13)]
            poly_line(f, cam.P(pts), OUT, lw)
        elif closed == 'o':
            ellipse(f, cam.p(cx, cy), w * 0.16 * cam.z, w * 0.2 * cam.z, inner, True, lw)
        else:
            poly_line(f, cam.P([(cx - w * 0.4, cy), (cx + w * 0.4, cy)]), OUT, lw)
        return
    ww = w * (0.55 + 0.45 * shape) * (0.85 + 0.25 * open_)
    hh = 6 + open_ * w * (0.62 - 0.25 * shape)
    if emotion == 'sinirli':
        hh *= 1.15
    pts = [(cx + ww / 2 * math.cos(a), cy + hh / 2 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 30)]
    fill(f, cam.P(pts), inner, True, lw)
    if open_ > 0.3:
        tp = [(cx + ww * 0.3 * math.cos(a), cy + hh * 0.3 + hh * 0.17 * math.sin(a)) for a in np.linspace(0, math.pi, 14)]
        cv2.fillPoly(f, [ip(cam.P(tp))], (0.9, 0.39, 0.43), cv2.LINE_AA, shift=2)
        tt = rect_pts(cx - ww * 0.3, cy - hh / 2 + 3, cx + ww * 0.3, cy - hh / 2 + 3 + hh * 0.16)
        cv2.fillPoly(f, [ip(cam.P(tt))], (1, 1, 1), cv2.LINE_AA, shift=2)


def anger_steam(f, cam, x, y, t, k=1.0):
    for i in range(3):
        u = (t * 1.6 + i / 3) % 1.0
        c = cam.p(x + (i - 1) * 40 + math.sin(u * 6 + i) * 10, y - u * 120)
        ov = f.copy()
        circle(ov, c, (14 + 26 * u) * cam.z, (1, 1, 1), False)
        a = 0.6 * (1 - u) * k
        f[:] = f * (1 - a) + ov * a
