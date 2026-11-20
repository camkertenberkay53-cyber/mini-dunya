"""LOJİSTİK KAOS karakterleri. Her karakter dünya koordinatında (x, y) noktasına çizilir.
Yer karakterlerinde (x, y) = ayak/teker hizasının ortası; Necati'de pruva su hattı; Vedat'ta kabin merkezi."""
import math
import cv2
from .draw import (OUT, Cam, ip, fill, line, circle, ellipse, rect_pts, rrect, shaded_box, ground_shadow,
                   eyes, mouth, anger_steam, shade, mix, poly_line)


class St:
    """Bir karakterin o andaki durumu."""
    def __init__(self, t=0.0, mo=0.0, ms=0.5, emotion='normal', look=(0, 0), blink=0.0, dy=0.0, sq=1.0, shake=0.0, talking=False):
        self.t, self.mo, self.ms, self.emotion, self.look, self.blink = t, mo, ms, emotion, look, blink
        self.dy, self.sq, self.shake, self.talking = dy, sq, shake, talking


# ---------------------------------------------------------------- KEMAL (konteyner)
def kemal(f, cam, x, y, s):
    t = s.t
    sq = s.sq * (1 + 0.025 * math.sin(t * 3) + s.mo * 0.04)
    x += s.shake * math.sin(t * 38) * 2.5
    w, h = 300, 330 * sq
    ground_shadow(f, cam, x, y, 340)
    y = y + s.dy
    x0, x1, y0, y1 = x - w / 2, x + w / 2, y - h, y
    orange = (0.93, 0.47, 0.16)
    shaded_box(f, cam, x0, y0, x1, y1, orange)
    for k in range(1, 10):
        xx = x0 + k * w / 10
        line(f, cam.p(xx, y0 + 16), cam.p(xx, y1 - 16), shade(orange, 0.72), cam.lw(4))
    for xx in (x - 52, x + 52):
        line(f, cam.p(xx, y0 + 6), cam.p(xx, y1 - 6), (0.45, 0.45, 0.48), cam.lw(9))
        for yy in (y0 + h * 0.3, y0 + h * 0.75):
            fill(f, cam.P(rect_pts(xx - 9, yy - 7, xx + 9, yy + 7)), (0.55, 0.55, 0.58), True, cam.lw(3))
    shaded_box(f, cam, x0 - 8, y0 - 10, x1 + 8, y0 + 12, (0.75, 0.38, 0.12), light=False, w=5)
    shaded_box(f, cam, x0 - 8, y1 - 12, x1 + 8, y1 + 8, (0.75, 0.38, 0.12), light=False, w=5)
    eyes(f, cam, x, y0 + 115, 38, s.look, s.blink, s.emotion, t=t)
    mouth(f, cam, x, y0 + 218, 112, s.mo, s.ms, s.emotion)
    if s.emotion == 'sinirli':
        anger_steam(f, cam, x, y0 - 10, t)


# ---------------------------------------------------------------- TAYFUN (tır)
def tayfun(f, cam, x, y, s):
    t = s.t
    x += s.shake * math.sin(t * 38) * 3
    ground_shadow(f, cam, x, y, 480)
    y = y + s.dy
    red = (0.85, 0.16, 0.14)
    for wx in (x - 175, x + 175):
        ellipse(f, cam.p(wx, y - 42), 50 * cam.z, 54 * cam.z, (0.12, 0.12, 0.14), True, cam.lw(5))
        ellipse(f, cam.p(wx, y - 42), 20 * cam.z, 22 * cam.z, (0.5, 0.5, 0.55), False)
    shaded_box(f, cam, x - 220, y - 520 * s.sq, x + 220, y - 70, red, r=40)
    top = y - 520 * s.sq
    shaded_box(f, cam, x - 180, top + 30, x + 180, top + 160, (0.6, 0.82, 0.95), r=24, light=False)
    line(f, cam.p(x - 120, top + 50), cam.p(x - 60, top + 140), (0.92, 0.98, 1), cam.lw(10))
    line(f, cam.p(x - 70, top + 50), cam.p(x - 40, top + 100), (0.92, 0.98, 1), cam.lw(6))
    shaded_box(f, cam, x - 205, top - 4, x + 205, top + 28, (0.97, 0.82, 0.2), r=8, light=False, w=5)
    for k in range(-3, 4):  # tepe lambaları
        circle(f, cam.p(x + k * 50, top + 12), 7 * cam.z, (1, 0.6, 0.15), False)
    shaded_box(f, cam, x - 232, y - 125, x + 232, y - 70, (0.78, 0.78, 0.82), r=10, w=5)
    for hx in (x - 175, x + 175):
        circle(f, cam.p(hx, y - 180), 30 * cam.z, (1, 0.95, 0.7), True, cam.lw(5))
        circle(f, cam.p(hx - 8, y - 188), 9 * cam.z, (1, 1, 1), False)
    eyes(f, cam, x, y - 290, 40, s.look, s.blink, s.emotion, t=t)
    for side in (-1, 1):  # bıyık
        m = [(x, y - 228), (x + side * 40, y - 242), (x + side * 95, y - 234), (x + side * 128, y - 202),
             (x + side * 100, y - 214), (x + side * 45, y - 207), (x, y - 214)]
        fill(f, cam.P(m), (0.15, 0.1, 0.08), True, cam.lw(4))
    mouth(f, cam, x, y - 168, 150, max(s.mo, 0.04 if s.emotion == 'sinirli' else 0), s.ms, s.emotion)
    if s.emotion == 'sinirli':
        anger_steam(f, cam, x, top - 10, t)


# ---------------------------------------------------------------- ERDAL (evrak)
def erdal(f, cam, x, y, s):
    t = s.t
    run = s.shake  # erdal'da shake = koşu fazı
    step = math.sin(t * 22) if run > 0 else 0.0
    ground_shadow(f, cam, x, y, 200)
    y_ = y + s.dy - abs(step) * 16
    for side in (-1, 1):
        a = (x + side * 30, y_ - 70)
        b = (x + side * 30 + step * side * 30, y)
        line(f, cam.p(*a), cam.p(*b), OUT, cam.lw(10))
        fill(f, cam.P(rrect(b[0] - 26, b[1] - 14, b[0] + 26, b[1] + 6, 8, 3)), (0.2, 0.2, 0.25), True, cam.lw(3))
    w, h = 200, 270 * s.sq
    x0, x1, y0, y1 = x - w / 2, x + w / 2, y_ - 70 - h, y_ - 70
    body = [(x0, y0), (x1 - 50, y0), (x1, y0 + 50), (x1, y1), (x0, y1)]
    fill(f, cam.P(body), (0.98, 0.98, 0.95), True, cam.lw(6))
    fill(f, cam.P([(x0, y1 - 40), (x1, y1 - 40), (x1, y1), (x0, y1)]), (0.9, 0.9, 0.86), False)
    fill(f, cam.P([(x1 - 50, y0), (x1 - 50, y0 + 50), (x1, y0 + 50)]), (0.85, 0.85, 0.82), True, cam.lw(5))
    poly_line(f, cam.P(body), OUT, cam.lw(6), closed=True)
    for k in range(5):
        yy = y0 + 152 + k * 20
        line(f, cam.p(x0 + 25, yy), cam.p(x1 - 25 - (k % 2) * 40, yy), (0.6, 0.65, 0.75), cam.lw(5))
    circle(f, cam.p(x1 - 48, y1 - 42), 24 * cam.z, (0.9, 0.3, 0.3), False)
    circle(f, cam.p(x1 - 48, y1 - 42), 15 * cam.z, (0.97, 0.6, 0.6), False)
    for side in (-1, 1):
        a = (x + side * w / 2, y0 + 150)
        b = (x + side * (w / 2 + 48), y0 + 210 + step * 20 * side)
        line(f, cam.p(*a), cam.p(*b), OUT, cam.lw(9))
    eyes(f, cam, x, y0 + 70, 25, s.look, s.blink, s.emotion, gap=1.4, t=t)
    for side in (-1, 1):
        cv2.circle(f, tuple(ip(cam.p(x + side * 35, y0 + 70))), int(36 * cam.z * 4), OUT, cam.lw(6), cv2.LINE_AA, shift=2)
    line(f, cam.p(x - 4, y0 + 70), cam.p(x + 4, y0 + 70), OUT, cam.lw(6))
    mouth(f, cam, x, y0 + 122, 62, s.mo, s.ms, s.emotion)


# ---------------------------------------------------------------- FİKRİ (forklift)
def fikri(f, cam, x, y, s):
    t = s.t
    x += s.shake * math.sin(t * 38) * 2.5
    ground_shadow(f, cam, x, y, 400)
    y = y + s.dy
    yel = (0.98, 0.76, 0.12)
    # direk ve çatallar (sol tarafta)
    mx = x - 175
    shaded_box(f, cam, mx - 18, y - 470, mx + 6, y - 40, (0.35, 0.35, 0.38), light=False, w=5)
    fork_y = y - 70 - 40 * (0.5 + 0.5 * math.sin(t * 1.3))
    fill(f, cam.P(rect_pts(mx - 150, fork_y, mx - 10, fork_y + 16)), (0.3, 0.3, 0.33), True, cam.lw(4))
    # gövde
    shaded_box(f, cam, x - 160, y - 230, x + 170, y - 60, yel, r=24)
    # kabin direkleri ve tavan
    for px in (x - 130, x + 120):
        line(f, cam.p(px, y - 230), cam.p(px, y - 470), OUT, cam.lw(12))
        line(f, cam.p(px, y - 230), cam.p(px, y - 470), (0.25, 0.25, 0.28), cam.lw(6))
    shaded_box(f, cam, x - 150, y - 490, x + 140, y - 455, (0.25, 0.25, 0.28), r=8, light=False, w=5)
    # yüz paneli
    shaded_box(f, cam, x - 115, y - 420, x + 105, y - 240, (1.0, 0.86, 0.35), r=30)
    # uyarı lambası
    blink_l = 0.5 + 0.5 * math.sin(t * 8)
    circle(f, cam.p(x + 60, y - 505), 16 * cam.z, mix((0.7, 0.35, 0.05), (1, 0.6, 0.1), blink_l), True, cam.lw(4))
    # tekerler
    for wx, r in ((x - 95, 55), (x + 115, 45)):
        ellipse(f, cam.p(wx, y - r + 4), r * cam.z, r * cam.z, (0.12, 0.12, 0.14), True, cam.lw(5))
        ellipse(f, cam.p(wx, y - r + 4), r * 0.4 * cam.z, r * 0.4 * cam.z, (0.6, 0.6, 0.62), False)
    # şeritler
    for k in range(4):
        xx = x - 150 + k * 90
        fill(f, cam.P([(xx, y - 110), (xx + 40, y - 110), (xx + 70, y - 70), (xx + 30, y - 70)]), (0.12, 0.12, 0.14), False)
    eyes(f, cam, x - 5, y - 355, 32, s.look, s.blink, s.emotion, t=t)
    mouth(f, cam, x - 5, y - 280, 90, s.mo, s.ms, s.emotion)


# ---------------------------------------------------------------- TELEFON (müşteri hattı)
def telefon(f, cam, x, y, s):
    t = s.t
    ring = s.shake
    jig = math.sin(t * 60) * 6 * ring
    ground_shadow(f, cam, x, y, 220)
    shaded_box(f, cam, x - 110, y - 130, x + 110, y, (0.62, 0.45, 0.28), w=5)
    for k in (-1, 1):
        line(f, cam.p(x - 110, y - 65 + k * 30), cam.p(x + 110, y - 65 + k * 30), shade((0.62, 0.45, 0.28), 0.7), cam.lw(4))
    y2 = y - 130 + s.dy
    x2 = x + jig
    red = (0.88, 0.18, 0.2)
    body = [(x2 - 95, y2), (x2 + 95, y2), (x2 + 70, y2 - 110), (x2 - 70, y2 - 110)]
    fill(f, cam.P(body), red, True, cam.lw(6))
    lift = 30 * ring * abs(math.sin(t * 30))
    hs = rrect(x2 - 110, y2 - 160 - lift, x2 + 110, y2 - 112 - lift, 22)
    fill(f, cam.P(hs), shade(red, 0.85), True, cam.lw(6))
    circle(f, cam.p(x2, y2 - 52), 30 * cam.z, (0.95, 0.95, 0.92), True, cam.lw(4))
    eyes(f, cam, x2, y2 - 62, 15, s.look, s.blink, s.emotion, gap=1.4, t=t)
    mouth(f, cam, x2, y2 - 32, 36, s.mo, s.ms, s.emotion)
    if ring > 0:
        for k in (-1, 1):
            for i in range(2):
                r0 = 130 + i * 28
                a0 = -60 if k > 0 else 200
                cv2.ellipse(f, tuple(ip(cam.p(x2, y2 - 110))), (int(r0 * cam.z * 4), int(r0 * cam.z * 4)), 0, a0, a0 + 40,
                            OUT, cam.lw(6), cv2.LINE_AA, shift=2)


# ---------------------------------------------------------------- NECATİ (gemi pruvası, su hattına demirli)
def necati(f, cam, x, y, s):
    t = s.t
    bob = math.sin(t * 1.1) * 6 + s.dy
    yb = y + bob
    navy = (0.12, 0.2, 0.42)
    hull = [(x - 420, yb - 520), (x + 260, yb - 520), (x + 330, yb - 300), (x + 280, yb + 40), (x - 420, yb + 40)]
    fill(f, cam.P(hull), navy, True, cam.lw(7))
    fill(f, cam.P([(x - 420, yb - 60), (x + 300, yb - 60), (x + 280, yb + 40), (x - 420, yb + 40)]), (0.75, 0.18, 0.18), True, cam.lw(6))
    fill(f, cam.P([(x - 420, yb - 520), (x + 260, yb - 520), (x + 270, yb - 490), (x - 420, yb - 490)]), (0.92, 0.92, 0.95), True, cam.lw(5))
    # konteyner yığını
    cols = [(0.9, 0.47, 0.16), (0.24, 0.62, 0.35), (0.8, 0.24, 0.24), (0.24, 0.47, 0.78), (0.9, 0.78, 0.24)]
    for r_ in range(3):
        for c_ in range(5):
            x0 = x - 410 + c_ * 120
            y0 = yb - 520 - (r_ + 1) * 58
            shaded_box(f, cam, x0, y0, x0 + 116, y0 + 56, cols[(c_ * 3 + r_) % 5], w=4)
    # çapa
    circle(f, cam.p(x + 150, yb - 330), 26 * cam.z, (0.75, 0.75, 0.78), True, cam.lw(4))
    # yüz
    eyes(f, cam, x + 60, yb - 420, 44, s.look, s.blink, s.emotion, gap=1.3, t=t)
    mouth(f, cam, x + 60, yb - 270, 170, s.mo, s.ms, s.emotion)
    # pruva dalgası
    for k in range(3):
        c = cam.p(x + 290 - k * 50, yb + 30)
        ellipse(f, c, (40 + 10 * math.sin(t * 3 + k)) * cam.z, 14 * cam.z, (0.92, 0.96, 1.0), False)


# ---------------------------------------------------------------- VEDAT (vinç kabini, yukarıdan sarkar)
def vedat(f, cam, x, y, s):
    t = s.t
    sway = math.sin(t * 0.9) * 8
    x = x + sway
    y = y + s.dy
    yel = (0.97, 0.75, 0.12)
    # bom ve halat
    line(f, cam.p(x - 600, y - 300), cam.p(x + 400, y - 300), OUT, cam.lw(46))
    line(f, cam.p(x - 600, y - 300), cam.p(x + 400, y - 300), yel, cam.lw(34))
    for k in range(-6, 5):
        xx = x + k * 90
        line(f, cam.p(xx, y - 318), cam.p(xx + 45, y - 282), shade(yel, 0.75), cam.lw(6))
    line(f, cam.p(x, y - 280), cam.p(x, y - 115), OUT, cam.lw(8))
    # kabin
    shaded_box(f, cam, x - 120, y - 115, x + 120, y + 95, yel, r=26)
    shaded_box(f, cam, x - 92, y - 90, x + 92, y + 5, (0.62, 0.84, 0.96), r=16, light=False)
    line(f, cam.p(x - 70, y - 75), cam.p(x - 30, y - 10), (0.92, 0.98, 1), cam.lw(8))
    eyes(f, cam, x, y - 42, 28, s.look, s.blink, s.emotion, t=t)
    mouth(f, cam, x, y + 52, 80, s.mo, s.ms, s.emotion)
    circle(f, cam.p(x + 95, y - 128), 10 * cam.z, (1, 0.2, 0.15) if int(t * 2) % 2 else (0.5, 0.1, 0.1), True, cam.lw(3))


CHARS = {
    'kemal':  dict(fn=kemal,  w=320, face=(0, -215), ground=True,  name='KONTEYNER KEMAL', color=(255, 140, 40)),
    'tayfun': dict(fn=tayfun, w=470, face=(0, -280), ground=True,  name='TIR TAYFUN',      color=(240, 70, 60)),
    'erdal':  dict(fn=erdal,  w=230, face=(0, -250), ground=True,  name='EVRAK ERDAL',     color=(90, 170, 255)),
    'fikri':  dict(fn=fikri,  w=420, face=(-5, -330), ground=True, name='FORKLİFT FİKRİ',  color=(255, 205, 40)),
    'telefon': dict(fn=telefon, w=240, face=(0, -190), ground=True, name='MÜŞTERİ HATTI',  color=(255, 90, 100)),
    'necati': dict(fn=necati, w=0,   face=(60, -360), ground=False, name='GEMİ NECATİ',     color=(110, 160, 255)),
    'vedat':  dict(fn=vedat,  w=0,   face=(0, -10),  ground=False,  name='VİNÇ VEDAT',      color=(255, 215, 60)),
}
