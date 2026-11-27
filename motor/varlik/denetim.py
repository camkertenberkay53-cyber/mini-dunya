"""Otomatik varlık denetimi.

python3 -m motor.varlik.denetim

Her derlenmiş karakter için:
1. Ölçümler (derle.py): boy, üçgen, evrensel iskelet, animasyon, doku, baş oranı.
2. Godot'ta 3 açıdan ışıklı ve siluet görüntü; kontak sayfası (ONBELLEK/denetim/<ad>.jpg).
3. Normalize siluet maskesi (kit ayrışma testi bunu kullanır).
4. Kalite seviyesi: A / B / C. C kütüphaneye giremez. Gerekçeler rapora yazılır.

Dönem uygunluğu kaliteden AYRIDIR: kıyafetin kayıttaki dönem etiketi, hangi kitlere girebileceğini belirler.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from motor import ayar
from motor.varlik import derle, katalog

CIKTI = ayar.ONBELLEK / "denetim"
MASKE_BOY = 160

# Stil rehberi eşikleri (Plan v2, "Görsel kalite standardı")
BAS_ORANI_MAX = 0.22      # gerçek insan ~0,13-0,18 (başlık dahil); stilize/chibi 0,35+
BOY_ARALIGI = (1.50, 2.05)  # m, dinlenme duruşunda (başlık/miğfer dahil)
UCGEN_MIN_C = 8000        # altı: düşük poligon, ön planda kullanılamaz
UCGEN_MIN_A = 15000
DOKU_MIN_A = 1024


def seviye(o: dict) -> tuple[str, list[str]]:
    red, eksik = [], []
    if o["bas_orani"] is None or o["bas_orani"] > BAS_ORANI_MAX:
        red.append(f"oran stilize/chibi (baş oranı {o['bas_orani']}, sınır {BAS_ORANI_MAX})")
    if not (BOY_ARALIGI[0] <= o["boy_m"] <= BOY_ARALIGI[1]):
        red.append(f"boy {o['boy_m']} m gerçek insan aralığı dışında")
    if o["evrensel_iskelet_eslesen"] < o["evrensel_iskelet_toplam"]:
        red.append(f"evrensel iskelet {o['evrensel_iskelet_eslesen']}/{o['evrensel_iskelet_toplam']}: ortak animasyonları kullanamaz")
    if o["ucgen"] < UCGEN_MIN_C:
        red.append(f"{o['ucgen']} üçgen: düşük poligon")
    if red:
        return "C", red
    if o["ucgen"] < UCGEN_MIN_A:
        eksik.append(f"{o['ucgen']} üçgen (A için {UCGEN_MIN_A})")
    if o["en_buyuk_doku"] < DOKU_MIN_A:
        eksik.append(f"doku {o['en_buyuk_doku']} px (A için {DOKU_MIN_A})")
    if len(o["animasyonlar"]) < 10:
        eksik.append(f"yalnızca {len(o['animasyonlar'])} animasyon")
    return ("B" if eksik else "A"), eksik


def maske(png: Path) -> np.ndarray:
    """Siyah siluet -> boyu MASKE_BOY olan, yatayda ortalanmış ikili maske."""
    a = np.asarray(Image.open(png).convert("L")) < 128
    ys, xs = np.nonzero(a)
    if len(ys) == 0:
        return np.zeros((MASKE_BOY, MASKE_BOY), bool)
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape
    yeni_w = max(1, round(w * MASKE_BOY / h))
    a = np.asarray(Image.fromarray(a.astype(np.uint8) * 255).resize((yeni_w, MASKE_BOY), Image.NEAREST)) > 127
    tuval = np.zeros((MASKE_BOY, MASKE_BOY * 2), bool)
    x0 = max(0, (tuval.shape[1] - yeni_w) // 2)
    tuval[:, x0:x0 + min(yeni_w, tuval.shape[1])] = a[:, :tuval.shape[1]]
    return tuval


def kontak_sayfasi(ad: str, sev: str, gerekce: list[str], olc: dict) -> Path:
    kareler = [Image.open(CIKTI / f"{ad}_isik_{a}.png").convert("RGB") for a in (0, 90, 180)]
    kareler += [Image.open(CIKTI / f"{ad}_siluet_{a}.png").convert("RGB") for a in (0, 90)]
    w, h = kareler[0].size
    s = Image.new("RGB", (w * 5, h + 90), "white")
    for i, k in enumerate(kareler):
        s.paste(k, (i * w, 90))
    d = ImageDraw.Draw(s)
    try:
        from PIL import ImageFont
        f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    except OSError:
        f1 = f2 = None
    renk = {"A": (20, 120, 40), "B": (170, 120, 0), "C": (180, 30, 30)}[sev]
    d.text((10, 6), f"{ad}  |  SEVİYE {sev}", fill=renk, font=f1)
    d.text((10, 30), f"boy {olc['boy_m']} m  üçgen {olc['ucgen']}  baş oranı {olc['bas_orani']}  iskelet {olc['evrensel_iskelet_eslesen']}/65  anim {len(olc['animasyonlar'])}  doku {olc['en_buyuk_doku']}", fill=(0, 0, 0), font=f2)
    d.text((10, 58), ("; ".join(gerekce) or "eksik yok")[:150], fill=renk, font=f2)
    yol = CIKTI / f"{ad}.jpg"
    s.save(yol, quality=88)
    # Repoda küçük bir kopya tutulur: denetim sonucu kodla birlikte incelenebilsin
    kucuk = Path(__file__).resolve().parent / "kontak"
    kucuk.mkdir(exist_ok=True)
    s.resize((s.width // 2, s.height // 2)).save(kucuk / f"{ad}.jpg", quality=80)
    return yol


def godot_cek(glblar: list[Path]) -> None:
    komut = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", ayar.GODOT, "--path", str(ayar.GODOT_PROJE),
             "--rendering-driver", "opengl3", "--", str(CIKTI)] + [str(g) for g in glblar]
    p = subprocess.run(komut, capture_output=True, text=True, timeout=1800)
    eksik = [g.stem for g in glblar if not (CIKTI / f"{g.stem}_siluet_0.png").exists()]
    if p.returncode != 0 or eksik:
        print(p.stdout[-2000:], p.stderr[-2000:])
        raise SystemExit(f"GODOT ÇEKİMİ BAŞARISIZ: {eksik}")


def denetle() -> dict:
    CIKTI.mkdir(parents=True, exist_ok=True)
    ozet = derle.derle()
    tarifler = derle.tarifleri_yukle()
    kayit = katalog.yukle()
    glblar = [derle.CIKTI / f"{ad}.glb" for ad in ozet]
    godot_cek(glblar)
    rapor = {}
    for ad, d in ozet.items():
        sev, gerekce = seviye(d["olcum"])
        kiyafet = katalog.bul(kayit, tarifler[ad]["kiyafet"])
        for a in (0, 90):
            np.save(CIKTI / f"{ad}_maske_{a}.npy", maske(CIKTI / f"{ad}_siluet_{a}.png"))
        kontak_sayfasi(ad, sev, gerekce, d["olcum"])
        rapor[ad] = {
            "seviye": sev,
            "gerekce": gerekce,
            "donem": kiyafet["donem"],
            "kiyafet": kiyafet["id"],
            "test": tarifler[ad].get("test"),
            "renk_degisikligi": tarifler[ad].get("renk") is not None,
            "olcum": {k: v for k, v in d["olcum"].items() if k != "animasyonlar"},
            "animasyon_sayisi": len(d["olcum"]["animasyonlar"]),
            "kontak": f"{ad}.jpg",
        }
    ayar.DENETIM_RAPOR.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    return rapor


if __name__ == "__main__":
    r = denetle()
    for ad, x in r.items():
        print(f"{x['seviye']}  {ad:22s} {','.join(x['donem']):28s} {'; '.join(x['gerekce'])[:110]}")
