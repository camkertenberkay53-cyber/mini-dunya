"""MİNİ DÜNYA karakterleri: Tuna, Nil, Bulut, Pire ve Benek (uğur böceği).
Her karakter dünya koordinatında (x, y) = iki ayağının ortası (yer hizası) noktasına çizilir.
Işık sağ üstten gelir; gölgeler hücre (cel) tarzında sol alttadır."""
import math
import numpy as np
import cv2
from .draw import (OUT2, EMO, E, capsule, cel, ellipse, circle, line, poly_line, ip, mouth, shade, mix)

SKIN = (0.93, 0.72, 0.56)
SKIN2 = (0.80, 0.56, 0.42)


class St:
    """Bir karakterin o andaki durumu."""
    def __init__(self, t=0.0, mo=0.0, ms=0.5, emotion='normal', look=(0, 0), blink=0.0, dy=0.0, sq=1.0, shake=0.0,
                 talking=False, walk=0.0):
        self.t, self.mo, self.ms, self.emotion, self.look, self.blink = t, mo, ms, emotion, look, blink
        self.dy, self.sq, self.shake, self.talking, self.walk = dy, sq, shake, talking, walk


def C(f, cam, pts, col, **k):
    k.setdefault('w', cam.lw(4.5))
    cel(f, cam.P(pts), col, **k)


def shadow(f, cam, x, y, w):
    c = cam.p(x + 10, y + 4)
    ov = f.copy()
    ellipse(ov, c, w / 2 * cam.z, 16 * cam.z, (0.12, 0.06, 0.04), False)
    f[:] = f * 0.7 + ov * 0.3


def face(f, cam, cx, cy, s, r=13, gap=1.55, iris=(0.30, 0.20, 0.12), mw=30, my=34, brow=(0.25, 0.14, 0.08), lashes=False, brow_up=0.0):
    """İnsan yüzü: göz akı, renkli iris, parlama, kaşlar ve konuşan ağız."""
    b, lid, scl, _ = EMO.get(s.emotion, EMO['normal'])
    r = r * scl
    lx, ly = s.look
    for side in (-1, 1):
        ex, ey = cx + side * r * gap + lx * 3, cy
        op = max(0.08, 1 - max(s.blink, lid))
        C(f, cam, E(ex, ey, r * 0.92, r * 1.12 * op, n=24), (1, 1, 1), shadow=0.12, rim=0, w=cam.lw(3))
        if op > 0.3:
            px, py = ex + lx * r * 0.35, ey + ly * r * 0.3
            circle(f, cam.p(px, py), r * 0.62 * cam.z, iris, False)
            circle(f, cam.p(px, py), r * 0.34 * cam.z, (0.05, 0.04, 0.05), False)
            circle(f, cam.p(px + r * 0.22, py - r * 0.28), r * 0.2 * cam.z, (1, 1, 1), False)
        if lashes:
            line(f, cam.p(ex + side * r * 0.7, ey - r * 0.8 * op), cam.p(ex + side * r * 1.1, ey - r * 1.1 * op), OUT2, cam.lw(3))
        yb_in = ey - r * (1.55 + brow_up) - b * r * 0.45
        yb_out = ey - r * (1.5 + brow_up) + b * r * 0.25
        x_in, x_out = ex - side * r * 0.75, ex + side * r * 0.95
        poly_line(f, cam.P([(x_in, yb_in), ((x_in + x_out) / 2, min(yb_in, yb_out) - 3), (x_out, yb_out)]), brow, cam.lw(r * 0.42))
    mouth(f, cam, cx + lx * 3, cy + my, mw, s.mo, s.ms, s.emotion, inner=(0.45, 0.13, 0.15))


def legs(f, cam, x, y, s, hip_y, sep, r, pants, boots, boot_w=1.0):
    ph = s.t * 14
    for i, side in enumerate((-1, 1)):
        sw = math.sin(ph + i * math.pi) * s.walk
        fx = x + side * sep + sw * 30
        fy = y - max(0, -math.cos(ph + i * math.pi)) * 18 * s.walk
        C(f, cam, capsule(x + side * sep * 0.8, hip_y, fx, fy - r * 1.4, r), pants)
        C(f, cam, E(fx + side * 6 * boot_w, fy - r * 0.75, r * 1.45 * boot_w, r * 0.95), boots, shadow=0.3)


def arm(f, cam, sx, sy, ang, L, r, sleeve, hand=SKIN):
    ex, ey = sx + math.cos(ang) * L, sy + math.sin(ang) * L
    C(f, cam, capsule(sx, sy, ex, ey, r * 1.05, r * 0.9), sleeve)
    C(f, cam, E(ex + math.cos(ang) * r * 0.6, ey + math.sin(ang) * r * 0.6, r * 0.95, r * 0.95), hand, shadow=0.2)


def arm_angles(s, side, base=1.25):
    """Konuşurken el kol hareketi; duygu ile değişir."""
    t = s.t
    a = math.pi / 2 - side * 0.28
    if s.talking:
        a -= side * (0.35 + 0.55 * s.mo) * (0.6 + 0.4 * math.sin(t * 5 + side))
    if s.emotion in ('panik', 'saskin'):
        a = math.pi / 2 - side * 1.9 + 0.15 * math.sin(t * 9)
    if s.emotion == 'neseli' and s.talking and side == 1:
        a = -math.pi / 2 + 0.6 + 0.2 * math.sin(t * 6)
    a += 0.06 * math.sin(t * 2 + side) + s.walk * side * 0.5 * math.sin(t * 14)
    return a


def bob(s):
    return (math.sin(s.t * 2.2) * 3 + (math.sin(s.t * 11) * 4 * s.mo if s.talking else 0) +
            abs(math.sin(s.t * 14)) * -10 * s.walk)


# ---------------------------------------------------------------- TUNA (öncü)
def tuna(f, cam, x, y, s):
    t = s.t
    shadow(f, cam, x, y, 150)
    y = y + s.dy
    by = y + bob(s)
    coat = (0.90, 0.48, 0.14)
    legs(f, cam, x, y, s, by - 120, 22, 13, (0.22, 0.24, 0.34), (0.38, 0.22, 0.12))
    # sırt: makara ve ip
    C(f, cam, E(x + 40, by - 215, 30, 30), (0.62, 0.40, 0.20))
    C(f, cam, E(x + 40, by - 215, 12, 12), (0.85, 0.80, 0.70), shadow=0)
    # ceket
    C(f, cam, [(x - 44, by - 262), (x + 44, by - 262), (x + 58, by - 112), (x + 10, by - 100), (x - 62, by - 110)], coat)
    poly_line(f, cam.P([(x + 2, by - 255), (x - 2, by - 108)]), shade(coat, 0.6), cam.lw(4))
    C(f, cam, [(x - 58, by - 168), (x + 56, by - 168), (x + 57, by - 152), (x - 60, by - 152)], (0.36, 0.22, 0.12), shadow=0.1)
    for sd in (-1, 1):
        arm(f, cam, x + sd * 40, by - 245, arm_angles(s, sd), 82, 13, coat)
    # atkı (rüzgârda dalgalanan uzun kuyruk)
    C(f, cam, [(x - 42, by - 272), (x + 42, by - 272), (x + 38, by - 248), (x - 40, by - 248)], (0.10, 0.62, 0.64))
    tail = []
    for k in range(9):
        u = k / 8
        tail.append((x - 30 - u * 120, by - 262 + u * 30 + math.sin(t * 6 - u * 4) * 14 * u))
    back = [(px, py + 20 - 6 * k / 8) for k, (px, py) in enumerate(tail)][::-1]
    C(f, cam, tail + back, (0.10, 0.62, 0.64))
    # kafa
    hy = by - 330
    C(f, cam, capsule(x, by - 285, x, by - 262, 13), SKIN2, shadow=0)
    C(f, cam, E(x, hy, 52, 58), SKIN)
    # saç
    hair = (0.42, 0.20, 0.10)
    C(f, cam, [(x - 56, hy - 4), (x - 58, hy - 40), (x - 34, hy - 66), (x - 4, hy - 74), (x + 30, hy - 70),
               (x + 56, hy - 48), (x + 58, hy - 10), (x + 40, hy - 34), (x + 14, hy - 40), (x - 18, hy - 36), (x - 40, hy - 24)], hair)
    for k in range(3):
        sx = x - 20 + k * 22
        C(f, cam, [(sx - 10, hy - 66), (sx + 6 + math.sin(t * 3 + k) * 2, hy - 92), (sx + 14, hy - 64)], hair, shadow=0.1)
    # pilot gözlüğü
    C(f, cam, [(x - 56, hy - 40), (x + 56, hy - 40), (x + 56, hy - 28), (x - 56, hy - 28)], (0.30, 0.20, 0.14), shadow=0)
    for gx in (-22, 22):
        C(f, cam, E(x + gx, hy - 36, 17, 14), (0.55, 0.82, 0.88), shadow=0.15, rim=0.4)
    face(f, cam, x, hy + 6, s, r=11, gap=1.7, iris=(0.20, 0.42, 0.30), mw=26, my=30)
    for sd in (-1, 1):
        circle(f, cam.p(x + sd * 32, hy + 24), 7 * cam.z, (0.98, 0.58, 0.50), False)


# ---------------------------------------------------------------- NİL (haritacı)
def nil(f, cam, x, y, s):
    t = s.t
    shadow(f, cam, x, y, 130)
    y = y + s.dy
    by = y + bob(s) * 0.8
    vest = (0.16, 0.24, 0.45)
    shirt = (0.90, 0.70, 0.22)
    legs(f, cam, x, y, s, by - 95, 18, 11, (0.30, 0.22, 0.18), (0.20, 0.14, 0.10), 0.9)
    # sırtta rulo harita
    C(f, cam, capsule(x - 52, by - 300, x + 50, by - 150, 15), (0.92, 0.84, 0.64))
    poly_line(f, cam.P([(x - 6, by - 232), (x + 8, by - 216)]), (0.75, 0.18, 0.15), cam.lw(5))
    # gövde
    C(f, cam, [(x - 40, by - 215), (x + 40, by - 215), (x + 48, by - 92), (x - 48, by - 92)], shirt)
    C(f, cam, [(x - 42, by - 215), (x - 6, by - 215), (x - 2, by - 100), (x - 50, by - 98)], vest)
    C(f, cam, [(x + 6, by - 215), (x + 42, by - 215), (x + 50, by - 98), (x + 2, by - 100)], vest)
    for k in range(3):
        circle(f, cam.p(x + 14, by - 190 + k * 30), 4 * cam.z, (0.85, 0.70, 0.30), False)
    for sd in (-1, 1):
        a = arm_angles(s, sd)
        if sd == -1 and not s.talking:
            a = math.pi / 2 + 0.9  # kalem tutan el
        arm(f, cam, x + sd * 36, by - 200, a, 70, 11, shirt)
    # kafa
    hy = by - 270
    C(f, cam, capsule(x, by - 228, x, by - 210, 11), SKIN2, shadow=0)
    hair = (0.12, 0.08, 0.10)
    C(f, cam, [(x - 56, hy + 40), (x - 60, hy - 10), (x - 40, hy - 52), (x, hy - 62), (x + 40, hy - 52),
               (x + 60, hy - 10), (x + 56, hy + 40), (x + 40, hy + 46), (x - 40, hy + 46)], hair)
    C(f, cam, E(x, hy, 46, 52), SKIN)
    # perçem
    C(f, cam, [(x - 48, hy - 8), (x - 40, hy - 46), (x, hy - 56), (x + 40, hy - 46), (x + 50, hy - 6),
               (x + 30, hy - 26), (x + 4, hy - 20), (x - 22, hy - 26)], hair, shadow=0.1)
    face(f, cam, x, hy + 6, s, r=10, gap=1.75, iris=(0.20, 0.30, 0.50), mw=22, my=28, lashes=True, brow_up=0.9)
    # büyük yuvarlak gözlük
    for sd in (-1, 1):
        cx = x + sd * 17.5
        cv2.circle(f, tuple(ip(cam.p(cx, hy + 6))), int(21 * cam.z * 4), (0.25, 0.16, 0.10), cam.lw(4), cv2.LINE_AA, shift=2)
    line(f, cam.p(x - 3, hy + 4), cam.p(x + 3, hy + 4), (0.25, 0.16, 0.10), cam.lw(4))
    ov = f.copy()
    for sd in (-1, 1):
        line(ov, cam.p(x + sd * 17.5 + 4, hy - 8), cam.p(x + sd * 17.5 + 12, hy + 2), (1, 1, 1), cam.lw(3))
    f[:] = f * 0.6 + ov * 0.4


# ---------------------------------------------------------------- BULUT (mucit)
def bulut(f, cam, x, y, s):
    t = s.t
    shadow(f, cam, x, y, 190)
    y = y + s.dy
    by = y + bob(s) * 0.7
    shirt = (0.48, 0.32, 0.20)
    apron = (0.38, 0.52, 0.28)
    legs(f, cam, x, y, s, by - 70, 30, 15, (0.30, 0.26, 0.22), (0.25, 0.16, 0.10), 1.1)
    # yuvarlak gövde
    C(f, cam, E(x, by - 150, 84, 92), shirt)
    C(f, cam, [(x - 56, by - 190), (x + 56, by - 190), (x + 66, by - 90), (x + 40, by - 66), (x - 40, by - 66), (x - 66, by - 90)], apron)
    C(f, cam, [(x - 30, by - 140), (x + 30, by - 140), (x + 28, by - 102), (x - 28, by - 102)], shade(apron, 0.82), shadow=0)
    # cepte İngiliz anahtarı
    C(f, cam, capsule(x + 12, by - 150, x + 22, by - 118, 5), (0.75, 0.76, 0.80), shadow=0.1)
    C(f, cam, E(x + 10, by - 154, 10, 8), (0.75, 0.76, 0.80), shadow=0.1)
    for sd in (-1, 1):
        arm(f, cam, x + sd * 72, by - 190, arm_angles(s, sd), 74, 17, shirt)
    # kafa
    hy = by - 268
    C(f, cam, E(x, hy, 56, 52), SKIN)
    # şişe kapağı miğfer: tırtıklı bant + üst kubbe
    cap = (0.82, 0.16, 0.14)
    C(f, cam, E(x, hy - 30, 60, 46, n=40, a0=math.pi, a1=2 * math.pi) + [(x + 60, hy - 30)], cap)
    band = []
    for k in range(25):
        xx = x - 64 + 128 * k / 24
        band.append((xx, hy - 30 + (4 if k % 2 else 0)))
    band += [(x + 64, hy - 12), (x - 64, hy - 12)]
    C(f, cam, band, shade(cap, 0.85))
    for k in range(9):
        xx = x - 56 + 14 * k
        line(f, cam.p(xx, hy - 28), cam.p(xx, hy - 14), shade(cap, 0.6), cam.lw(2.5))
    C(f, cam, E(x + 18, hy - 56, 16, 7, ang=-0.3), (1.0, 0.70, 0.66), shadow=0, outline=False)
    face(f, cam, x, hy + 8, s, r=11, gap=1.8, iris=(0.35, 0.22, 0.10), mw=30, my=28)
    for sd in (-1, 1):
        circle(f, cam.p(x + sd * 38, hy + 24), 9 * cam.z, (0.98, 0.60, 0.52), False)


# ---------------------------------------------------------------- PİRE (çaylak)
def pire(f, cam, x, y, s):
    t = s.t
    shadow(f, cam, x, y, 100)
    y = y + s.dy
    by = y + bob(s) * 1.2 - (abs(math.sin(t * 7)) * 4 if s.talking else 0)
    jacket = (0.95, 0.80, 0.30)
    legs(f, cam, x, y, s, by - 62, 13, 9, (0.20, 0.36, 0.55), (0.80, 0.20, 0.15), 0.95)
    # çanta
    C(f, cam, [(x + 18, by - 150), (x + 52, by - 146), (x + 50, by - 92), (x + 16, by - 96)], (0.45, 0.30, 0.55))
    C(f, cam, [(x - 30, by - 150), (x + 30, by - 150), (x + 36, by - 62), (x - 36, by - 62)], jacket)
    for sd in (-1, 1):
        arm(f, cam, x + sd * 28, by - 140, arm_angles(s, sd), 54, 9, jacket)
    hy = by - 205
    C(f, cam, E(x, hy, 48, 50), SKIN)
    hair = (0.90, 0.45, 0.15)
    C(f, cam, [(x - 50, hy), (x - 44, hy - 20), (x - 30, hy - 10), (x - 40, hy + 18)], hair, shadow=0.1)
    C(f, cam, [(x + 50, hy), (x + 44, hy - 20), (x + 30, hy - 10), (x + 42, hy + 18)], hair, shadow=0.1)
    # kocaman kırmızı bere
    sway = math.sin(t * 2.5) * 4
    C(f, cam, E(x + 10 + sway, hy - 50, 66, 30, ang=-0.12), (0.85, 0.12, 0.12))
    C(f, cam, [(x + 8 + sway, hy - 78), (x + 14 + sway, hy - 96), (x + 20 + sway, hy - 78)], (0.70, 0.08, 0.08), shadow=0)
    face(f, cam, x, hy + 8, s, r=12.5, gap=1.6, iris=(0.15, 0.40, 0.25), mw=22, my=26)
    for sd in (-1, 1):
        circle(f, cam.p(x + sd * 30, hy + 24), 7 * cam.z, (0.98, 0.55, 0.50), False)
    # çiller
    for k in range(3):
        circle(f, cam.p(x - 6 + k * 6, hy + 18 - (k % 2) * 3), 1.6 * cam.z, (0.75, 0.45, 0.30), False)


# ---------------------------------------------------------------- BENEK (uğur böceği)
def benek(f, cam, x, y, s):
    t = s.t
    shadow(f, cam, x, y, 260)
    y = y + s.dy
    by = y + math.sin(t * 2) * 2
    # bacaklar
    for k, lx in enumerate((-80, -20, 40)):
        ph = math.sin(t * 16 + k) * 10 * s.walk
        line(f, cam.p(x + lx, by - 40), cam.p(x + lx - 20 + ph, by - 2), (0.08, 0.06, 0.06), cam.lw(8))
    # kabuk
    C(f, cam, E(x - 10, by - 80, 120, 78), (0.85, 0.12, 0.10), shadow=0.28, rim=0.3)
    line(f, cam.p(x - 10, by - 156), cam.p(x - 6, by - 6), (0.10, 0.06, 0.06), cam.lw(5))
    for sx, sy, r in [(-70, -100, 18), (-40, -40, 15), (30, -110, 17), (55, -55, 14), (-95, -60, 11)]:
        circle(f, cam.p(x + sx, by + sy), r * cam.z, (0.10, 0.06, 0.06), False)
    # kafa
    hx = x + 120
    C(f, cam, E(hx, by - 70, 46, 42), (0.12, 0.10, 0.12), shadow=0.1, rim=0.35)
    for k, ax in enumerate((-10, 14)):
        tipx = hx + ax + 18 + math.sin(t * 4 + k) * 6
        poly_line(f, cam.P([(hx + ax, by - 104), (hx + ax + 8, by - 140), (tipx, by - 156)]), (0.10, 0.08, 0.10), cam.lw(4))
        circle(f, cam.p(tipx, by - 156), 6 * cam.z, (0.10, 0.08, 0.10), False)
    lx = s.look[0]
    for ex in (-14, 14):
        C(f, cam, E(hx + ex + 6, by - 76, 12, 15), (1, 1, 1), shadow=0, rim=0, w=cam.lw(2.5))
        circle(f, cam.p(hx + ex + 6 + lx * 4, by - 74), 6 * cam.z, (0.05, 0.04, 0.05), False)
        circle(f, cam.p(hx + ex + 8 + lx * 4, by - 78), 2.2 * cam.z, (1, 1, 1), False)


CHARS = {
    'tuna':  dict(fn=tuna,  w=180, h=430, face=(0, -320), ground=True, name='TUNA',  color=(255, 150, 50)),
    'nil':   dict(fn=nil,   w=150, h=340, face=(0, -262), ground=True, name='NİL',   color=(110, 160, 255)),
    'bulut': dict(fn=bulut, w=210, h=350, face=(0, -258), ground=True, name='BULUT', color=(140, 210, 110)),
    'pire':  dict(fn=pire,  w=130, h=270, face=(0, -196), ground=True, name='PİRE',  color=(255, 90, 80)),
    'benek': dict(fn=benek, w=290, h=190, face=(120, -76), ground=True, name='BENEK', color=(255, 80, 70)),
}
