"""Kamera yolları. Her hareket t (0..1) için (cx, cy, zoom, aci) döndürür.
cx, cy: görselin normalize merkezi (0..1); zoom: 1 = görsel çerçeveyi tam doldurur; aci: derece."""
import math

import numpy as np


def ease(t, tip='inout'):
    t = min(1.0, max(0.0, t))
    if tip == 'lin':
        return t
    if tip == 'out':
        return 1 - (1 - t) ** 3
    if tip == 'in':
        return t ** 3
    return t * t * (3 - 2 * t)  # smoothstep


def _lerp(a, b, t):
    return a + (b - a) * t


# Hazır hareketler: (başlangıç (cx, cy, zoom), bitiş (cx, cy, zoom), yumuşatma)
HAREKETLER = {
    'zoom_in':      ((0.5, 0.5, 1.00), (0.5, 0.5, 1.18), 'inout'),
    'zoom_out':     ((0.5, 0.5, 1.20), (0.5, 0.5, 1.00), 'inout'),
    'push_in':      ((0.5, 0.52, 1.02), (0.5, 0.45, 1.35), 'in'),    # sinematik itme: yavaş başlar, hızlanır
    'pull_back':    ((0.5, 0.45, 1.40), (0.5, 0.5, 1.02), 'out'),
    'pan_sol':      ((0.62, 0.5, 1.22), (0.38, 0.5, 1.22), 'inout'),
    'pan_sag':      ((0.38, 0.5, 1.22), (0.62, 0.5, 1.22), 'inout'),
    'pan_yukari':   ((0.5, 0.62, 1.22), (0.5, 0.38, 1.22), 'inout'),
    'pan_asagi':    ((0.5, 0.38, 1.22), (0.5, 0.62, 1.22), 'inout'),
    'capraz':       ((0.40, 0.60, 1.15), (0.60, 0.40, 1.30), 'inout'),
    'takip':        ((0.30, 0.55, 1.30), (0.70, 0.50, 1.30), 'lin'),  # tracking: sabit hız
    'sabit':        ((0.5, 0.5, 1.05), (0.5, 0.5, 1.07), 'lin'),
}


def konum(hareket, t, odak=None, guc=1.0):
    """hareket: HAREKETLER anahtarı veya {'bas': [cx,cy,z], 'son': [...], 'ease': 'inout'}.
    odak: [cx, cy] verilirse hareket o noktaya doğru kaydırılır (yüz / önemli nesne)."""
    if isinstance(hareket, dict):
        a, b, e = tuple(hareket['bas']), tuple(hareket['son']), hareket.get('ease', 'inout')
    else:
        a, b, e = HAREKETLER.get(hareket, HAREKETLER['zoom_in'])
    k = ease(t, e)
    cx, cy, z = (_lerp(a[i], b[i], k) for i in range(3))
    # güç: hareket genliğini ölçekler (0.5 = daha sakin)
    cx = 0.5 + (cx - 0.5) * guc
    cy = 0.5 + (cy - 0.5) * guc
    z = 1.0 + (z - 1.0) * guc
    if odak:
        w = min(1.0, (z - 1.0) * 3)  # yakınlaştıkça odağa kay
        cx = _lerp(cx, odak[0], w * 0.8)
        cy = _lerp(cy, odak[1], w * 0.8)
    return cx, cy, max(1.0, z), 0.0


class Sarsinti:
    """Pürüzsüz kamera sarsıntısı (deterministik gürültü). guc piksel cinsinden genlik."""

    def __init__(self, guc=6.0, hiz=9.0, tohum=1):
        r = np.random.default_rng(tohum)
        self.f = r.uniform(0.6, 1.4, (3, 4)) * hiz
        self.p = r.uniform(0, 2 * math.pi, (3, 4))
        self.guc = guc

    def __call__(self, zaman, darbe=1.0):
        v = [sum(math.sin(self.f[i, j] * zaman + self.p[i, j]) / (j + 1) for j in range(4)) / 2.08 for i in range(3)]
        return v[0] * self.guc * darbe, v[1] * self.guc * darbe, v[2] * 0.25 * darbe
