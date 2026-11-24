"""Görsel deney analizi (Faz 5.1 P2/P3): ham (V0) / V1 / V2 / V2+PolyHaven karşılaştırması ve objektif ölçüler.

Kullanım: python3 analiz.py <girdi_klasoru> <cikti_klasoru>
V1 = Faz 5.0'da ölçülen "birleşik" ffmpeg grade'i, V0 karesine altyazıdan önce uygulanır.
Ölçüler (vekil; izleyici kalitesinin yerine geçmez):
  tüm kare: parlaklık, kontrast (σ), doygunluk, renklilik (Hasler-Süsstrunk), patlamış beyaz/siyah %
  gökyüzü (üst %22): doygunluk, mavi-kırmızı farkı, dikey parlaklık geçişi (düz gri gök = düşük)
  zemin (alt %20): yerel ayrıntı (Laplace ortalaması) — dokusuz düz zemin = düşük
Ayrıca: altyazı sırası testi — grade sonrası altyazı yakılır, altyazı renkleri ölçülür (grade altyazıyı boyamamalı).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[2]
V1_FILTRE = ("eq=contrast=1.12:saturation=1.15:brightness=-0.01,colortemperature=temperature=5600:mix=0.5,"
             "colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.04,split[a][b];[b]gblur=sigma=18,"
             "curves=all='0/0 0.6/0.15 1/1'[g];[a][g]blend=all_mode=screen:all_opacity=0.25,vignette=angle=PI/5")
PROFIL_AD = {"V0": "Ham (V0)", "V1": "V1 (Faz 5.0 grade)", "V2": "V2 (render profili)", "V2_PH": "V2 + Poly Haven"}


def olc(p: Path) -> dict:
    a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255
    L = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    hsv = np.asarray(Image.open(p).convert("HSV"), dtype=np.float32) / 255
    rg, yb = a[..., 0] - a[..., 1], 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    renklilik = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    h = a.shape[0]
    gok, gok_L, gok_S = a[: int(0.22 * h)], L[: int(0.22 * h)], hsv[: int(0.22 * h), :, 1]
    zemin_L = L[int(0.80 * h):]
    lap = np.abs(zemin_L[1:-1, 1:-1] * 4 - zemin_L[:-2, 1:-1] - zemin_L[2:, 1:-1] - zemin_L[1:-1, :-2] - zemin_L[1:-1, 2:])
    return {"parlaklik": round(float(L.mean()), 3), "kontrast": round(float(L.std()), 3),
            "doygunluk": round(float(hsv[..., 1].mean()), 3), "renklilik": round(renklilik, 3),
            "beyaz_yuzde": round(float((L > 0.98).mean() * 100), 2), "siyah_yuzde": round(float((L < 0.02).mean() * 100), 2),
            "gok_doygunluk": round(float(gok_S.mean()), 3),
            "gok_mavi_kirmizi": round(float((gok[..., 2] - gok[..., 0]).mean()), 3),
            "gok_gecis": round(float(gok_L.mean(1).std()), 4),
            "zemin_ayrinti": round(float(lap.mean() * 100), 3)}


def main() -> int:
    gir, cik = Path(sys.argv[1]), Path(sys.argv[2])
    cik.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    cekimler = sorted({p.name.split("_")[0] for p in gir.glob("*_V0.png")})
    sonuc = {"cekimler": {}, "render": {}}
    for c in cekimler:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(gir / f"{c}_V0.png"), "-filter_complex", V1_FILTRE,
                        str(gir / f"{c}_V1.png")], check=True)
        profiller = [p for p in ("V0", "V1", "V2", "V2_PH") if (gir / f"{c}_{p}.png").exists()]
        sonuc["cekimler"][c] = {p: olc(gir / f"{c}_{p}.png") for p in profiller}
        W, H = 540, 960
        pan = Image.new("RGB", (W * len(profiller), H + 44), "black")
        d = ImageDraw.Draw(pan)
        for i, p in enumerate(profiller):
            pan.paste(Image.open(gir / f"{c}_{p}.png").convert("RGB").resize((W, H)), (i * W, 44))
            d.text((i * W + 8, 8), PROFIL_AD[p], fill="white", font=font)
        pan.save(cik / f"panel_{c}.jpg", quality=88)
        for p in ("V0", "V2", "V2_PH"):
            j = gir / f"{c}_{p}.json"
            if j.exists():
                sonuc["render"].setdefault(c, {})[p] = json.loads(j.read_text())
    # Altyazı sırası testi: grade → altyazı. Altyazı kutusunun beyaz yazı rengi her sürümde aynı kalmalı.
    ass = REPO / "deneyler/faz51/altyapi/kurgu/altyazi.ass"
    fonts = REPO / "assets" / "fonts"
    alt = {}
    c0 = cekimler[0]
    for p in ("V0", "V1", "V2"):
        src = gir / f"{c0}_{p}.png"
        if not src.exists():
            continue
        out = gir / f"{c0}_{p}_altyazi.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src), "-t", "1.2", "-vf",
                        f"ass={ass}:fontsdir={fonts}", "-update", "1", "-frames:v", "30", str(out)], check=True)
        a = np.asarray(Image.open(out).convert("RGB"), dtype=np.float32)
        b = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
        fark = np.abs(a - b).sum(2) > 60
        yazi = a[fark & (a.min(2) > 200)]
        alt[p] = {"altyazi_piksel": int(fark.sum()), "yazi_rengi_ort": [round(float(v), 1) for v in yazi.mean(0)] if len(yazi) else None}
    sonuc["altyazi_testi"] = {"aciklama": "Grade altyazıdan önce uygulandı; altyazı beyaz yazısı her sürümde aynı olmalı.", **alt}
    if alt:
        W, H = 540, 960
        ks = [p for p in ("V0", "V1", "V2") if p in alt]
        pan = Image.new("RGB", (W * len(ks), H + 44), "black")
        d = ImageDraw.Draw(pan)
        for i, p in enumerate(ks):
            pan.paste(Image.open(gir / f"{c0}_{p}_altyazi.png").convert("RGB").resize((W, H)), (i * W, 44))
            d.text((i * W + 8, 8), PROFIL_AD[p] + " + altyazı", fill="white", font=font)
        pan.save(cik / "panel_altyazi.jpg", quality=88)
    (cik / "gorsel_olcum.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    print(json.dumps(sonuc, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
