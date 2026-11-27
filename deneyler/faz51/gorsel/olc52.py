"""Faz 5.2 kare ölçüleri (vekil; insan değerlendirmesinin yerine geçmez).

Kullanım: python3 olc52.py <klasor> <cekim> <profil> [<profil> ...]
  ort_L        : ortalama parlaklık (0-1)
  beyaz_yuzde  : patlamış beyaz (L > 0.98) yüzdesi
  ufuk_beyaz   : ufuk bandında beyaz ve renksiz (L > 0.9, S < 0.12) piksel yüzdesi
  ufuk_ayrinti : ufuk bandında yerel ayrıntı (Laplace ortalaması ×100)
  karakter_L   : sabit karakter kutusunda ortalama parlaklık (ten/zırh aşırı parlaklaşmasın)
  karakter_beyaz: karakter kutusunda L > 0.95 yüzdesi
  zemin_koyu   : alt %45'te L < 0.25 yüzdesi
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Kare oranları (1080x1920): ufuk bandı (y0,y1) ve karakter kutusu (x0,y0,x1,y1)
BOLGE = {
    "S4a": {"ufuk": (0.30, 0.50), "karakter": (0.33, 0.43, 0.48, 0.65)},
    "S1": {"ufuk": (0.55, 0.80), "karakter": (0.35, 0.47, 0.65, 0.73)},
    "S2": {"ufuk": (0.30, 0.45), "karakter": (0.35, 0.36, 0.65, 0.68)},
}


def olc(yol: Path, cekim: str) -> dict:
    im = Image.open(yol).convert("RGB")
    a = np.asarray(im, dtype=np.float32) / 255
    S = np.asarray(im.convert("HSV"), dtype=np.float32)[..., 1] / 255
    L = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    h, w = L.shape
    b = BOLGE[cekim]
    u0, u1 = int(b["ufuk"][0] * h), int(b["ufuk"][1] * h)
    u, us = L[u0:u1], S[u0:u1]
    lap = np.abs(u[1:-1, 1:-1] * 4 - u[:-2, 1:-1] - u[2:, 1:-1] - u[1:-1, :-2] - u[1:-1, 2:])
    x0, y0, x1, y1 = b["karakter"]
    k = L[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    return {"ort_L": round(float(L.mean()), 3), "beyaz_yuzde": round(float((L > 0.98).mean() * 100), 2),
            "ufuk_beyaz": round(float(((u > 0.9) & (us < 0.12)).mean() * 100), 1),
            "ufuk_ayrinti": round(float(lap.mean() * 100), 3),
            "karakter_L": round(float(k.mean()), 3), "karakter_beyaz": round(float((k > 0.95).mean() * 100), 2),
            "zemin_koyu": round(float((L[int(0.55 * h):] < 0.25).mean() * 100), 2)}


if __name__ == "__main__":
    klasor, cekim = Path(sys.argv[1]), sys.argv[2]
    for p in sys.argv[3:]:
        print(cekim, p.ljust(6), json.dumps(olc(klasor / f"{cekim}_{p}.png", cekim)))
