"""Prosedürel malzeme dokuları (numpy). Blender içinde ve dışında çalışır; tohumla belirlenir (tekrarlanabilir).

Her malzeme: renk (RGBA), pürüzlülük ve normal haritası. Amaç düz renkli "oyuncak" görünümünü önlemek:
dokuma, deri damarı, metal çizik ve pası, zincir halkası, lamel plakası, hasır, ahşap, keçe.
"""
from __future__ import annotations

import numpy as np

BOYUT = 512


def _gurultu(n: int, olcek: int, rng: np.random.Generator) -> np.ndarray:
    """Değer gürültüsü (yumuşak, döşenebilir) 0..1."""
    k = rng.random((olcek, olcek))
    x = np.linspace(0, olcek, n, endpoint=False)
    i0 = np.floor(x).astype(int) % olcek
    i1 = (i0 + 1) % olcek
    f = x - np.floor(x)
    f = f * f * (3 - 2 * f)
    a = k[i0][:, i0] * (1 - f)[None, :] + k[i0][:, i1] * f[None, :]
    b = k[i1][:, i0] * (1 - f)[None, :] + k[i1][:, i1] * f[None, :]
    return a * (1 - f)[:, None] + b * f[:, None]


def fbm(n: int, rng: np.random.Generator, oktav=(4, 8, 16, 32, 64)) -> np.ndarray:
    t, w = np.zeros((n, n)), 0.0
    for i, o in enumerate(oktav):
        a = 0.5 ** i
        t += a * _gurultu(n, o, rng)
        w += a
    return t / w


def _normal(yukseklik: np.ndarray, guc: float) -> np.ndarray:
    gy, gx = np.gradient(yukseklik)
    nx, ny = -gx * guc, -gy * guc
    nz = np.ones_like(nx)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / L * 0.5 + 0.5, ny / L * 0.5 + 0.5, nz / L * 0.5 + 0.5], -1)


def _renkle(taban: np.ndarray, renk, degisim: float) -> np.ndarray:
    r = np.array(renk[:3], float)
    return np.clip(r[None, None, :] * (1 - degisim + 2 * degisim * taban[..., None]), 0, 1)


def uret(tur: str, renk=(0.5, 0.5, 0.5), tohum: int = 1, n: int = BOYUT, ikinci_renk=None):
    """(renk[n,n,4], puruzluluk[n,n], normal[n,n,3]) döner; hepsi 0..1."""
    rng = np.random.default_rng(tohum)
    y = np.mgrid[0:n, 0:n][0] / n
    x = np.mgrid[0:n, 0:n][1] / n
    g = fbm(n, rng)
    if tur == "kumas":  # dokuma: çözgü ve atkı + leke
        dok = 0.5 + 0.25 * np.sin(x * n * np.pi * 0.5) * np.sin(y * n * np.pi * 0.5)
        h = 0.6 * dok + 0.4 * g
        alb = _renkle(0.7 * g + 0.3 * dok, renk, 0.18)
        rough = 0.85 + 0.1 * g
        nm = _normal(h, 1.5)
    elif tur == "kece":  # keçe: yumuşak, lifli
        h = fbm(n, rng, (16, 32, 64, 128))
        alb = _renkle(0.5 * g + 0.5 * h, renk, 0.10)
        rough = 0.95 + 0.0 * g
        nm = _normal(h, 1.0)
    elif tur == "deri":
        hucre = fbm(n, rng, (24, 48, 96))
        h = 0.6 * hucre + 0.4 * g
        alb = _renkle(h, renk, 0.22)
        rough = 0.6 + 0.3 * hucre
        nm = _normal(h, 2.0)
    elif tur in ("metal", "bronz"):
        firca = fbm(n, rng, (2, 4, 256))  # fırçalanmış çizgiler
        cizik = (rng.random((n, n)) > 0.9985).astype(float)
        for _ in range(3):
            cizik = np.maximum(cizik, np.roll(cizik, 1, axis=1))
        pas = np.clip((fbm(n, rng, (3, 6, 12)) - 0.62) * 4, 0, 1)
        h = 0.5 * firca + 0.3 * g - 0.4 * cizik
        alb = _renkle(0.6 * g + 0.4 * firca, renk, 0.15)
        pas_renk = np.array([0.33, 0.18, 0.09]) if tur == "metal" else np.array([0.20, 0.33, 0.25])
        alb = alb * (1 - pas[..., None] * 0.7) + pas_renk * pas[..., None] * 0.7
        alb = np.clip(alb + cizik[..., None] * 0.25, 0, 1)
        rough = np.clip(0.35 + 0.35 * g + 0.4 * pas - 0.2 * cizik, 0, 1)
        nm = _normal(h, 1.2)
    elif tur == "zincir":  # zincir zırh: iç içe halkalar
        k = 40  # daha iri halka: uzak planda kum gibi titreşmesin
        u, v = x * k, y * k * 1.15
        ofs = (np.floor(v) % 2) * 0.5
        dx = (u + ofs) % 1 - 0.5
        dy = v % 1 - 0.5
        r = np.sqrt(dx * dx + dy * dy)
        halka = np.clip(1 - np.abs(r - 0.32) * 9, 0, 1)
        h = halka * 0.9 + 0.1 * g
        alb = _renkle(0.55 + 0.45 * halka * (0.7 + 0.3 * g), renk, 0.35)
        alb *= (0.62 + 0.38 * halka)[..., None]  # halka arası koyu ama siyah değil
        rough = 0.35 + 0.5 * (1 - halka)
        nm = _normal(h, 4.0)
    elif tur == "lamel":  # dikdörtgen plakalar, sıralar halinde, perçinli
        sx, sy = 16, 9
        u, v = x * sx, y * sy
        ofs = (np.floor(v) % 2) * 0.5
        fu = (u + ofs) % 1
        fv = v % 1
        kenar = np.minimum(np.minimum(fu, 1 - fu) * 6, np.minimum(fv, 1 - fv) * 4)
        plaka = np.clip(kenar, 0, 1)
        egim = fv * 0.3  # üst sıra alttakinin üstüne biner
        percin = np.clip(1 - np.hypot((fu - 0.5) * 6, (fv - 0.18) * 6), 0, 1)
        h = plaka * 0.6 + egim + percin * 0.5 + 0.1 * g
        alb = _renkle(0.4 + 0.6 * plaka * (0.6 + 0.4 * g), renk, 0.35)
        alb *= (0.35 + 0.65 * plaka)[..., None]
        rough = 0.4 + 0.3 * g
        nm = _normal(h, 3.0)
    elif tur == "hasir":  # sarmal hasır kalkan: merkezden dönen halkalar + iplik sargısı
        cx, cy = x - 0.5, y - 0.5
        r = np.sqrt(cx * cx + cy * cy)
        a = np.arctan2(cy, cx)
        halka = 0.5 + 0.5 * np.sin(r * 2 * np.pi * 48 + a)
        sargi = 0.5 + 0.5 * np.sin(a * 90)
        h = 0.7 * halka + 0.3 * sargi * (halka > 0.5) + 0.1 * g
        b = np.array(ikinci_renk or (0.55, 0.12, 0.1))
        ip = ((sargi > 0.75) & (halka > 0.4)).astype(float)
        alb = _renkle(0.5 * halka + 0.5 * g, renk, 0.3)
        alb = alb * (1 - ip[..., None]) + b[None, None, :] * ip[..., None]
        rough = 0.8 + 0.1 * g
        nm = _normal(h, 2.5)
    elif tur == "ahsap":
        lif = 0.5 + 0.5 * np.sin((y * 40 + fbm(n, rng, (2, 4, 8)) * 6) * np.pi)
        h = 0.5 * lif + 0.5 * g
        alb = _renkle(0.6 * lif + 0.4 * g, renk, 0.25)
        rough = 0.75 + 0.15 * g
        nm = _normal(h, 1.2)
    elif tur == "boyali_ahsap":  # boyanmış, kenarları aşınmış kalkan yüzü
        lif = 0.5 + 0.5 * np.sin((y * 30 + fbm(n, rng, (2, 4, 8)) * 5) * np.pi)
        asinma = np.clip((fbm(n, rng, (8, 16, 32)) - 0.6) * 5, 0, 1)
        alb = _renkle(0.7 + 0.3 * g, renk, 0.12)
        ah = _renkle(lif, (0.45, 0.32, 0.2), 0.2)
        alb = alb * (1 - asinma[..., None]) + ah * asinma[..., None]
        h = 0.3 * g + 0.4 * asinma * lif
        rough = 0.7 + 0.2 * asinma
        nm = _normal(h, 1.0)
    elif tur == "tas":
        h = fbm(n, rng, (4, 8, 16, 32, 64))
        blok = (np.minimum((x * 6) % 1, (y * 3 + (np.floor(x * 6) % 2) * 0.5) % 1) < 0.04).astype(float)
        alb = _renkle(h, renk, 0.25) * (1 - 0.5 * blok[..., None])
        rough = 0.9 + 0.0 * h
        nm = _normal(h - blok * 0.6, 2.0)
    else:
        raise ValueError(f"bilinmeyen doku: {tur}")
    rgba = np.concatenate([alb, np.ones((n, n, 1))], -1)
    return rgba.astype(np.float32), np.clip(rough, 0, 1).astype(np.float32), nm.astype(np.float32)
